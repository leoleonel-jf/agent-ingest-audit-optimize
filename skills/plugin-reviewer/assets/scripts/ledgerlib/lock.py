"""Pinning the supply chain: turning a baseline into a lockfile.

A baseline answers "what was in this environment that day". It is an
observation, dated and immutable. A lockfile answers a different question --
**"what should be here"** -- and the difference is the one between a `pip
freeze` filed in a log and a `requirements.lock` committed to the repository:
the second is declared intent, small enough to read in a diff, and a CI pass
fails when reality drifts from it.

Two design decisions carry the module.

**Determinism is a requirement, not a quality.** The file is meant to be
committed and read in a diff, so two runs over one baseline produce identical
bytes: entries sorted by `(kind, scope, anchor)`, no timestamp, no absolute
path, nothing machine-specific beyond the platform the baseline itself
recorded. Canonicalization is `chain.canonical_text`, the one canonicalization
in this repository.

**`--check` never reads the environment.** It compares a lockfile against a
baseline recorded in the ledger, and nothing else. Verifying against the disk
as it is *now* already has a command -- `drift` -- and giving one question two
answers is worse than either answer alone. A caller who wants both runs both.

Which kinds are pinnable is declared per probe in the adapter (`lockable`),
never hardcoded here: configuration that legitimately changes every day --
instruction files, model settings, permission rules, environment variable
names -- is deliberately left out, because a lockfile that fails CI over an
edited `CLAUDE.md` is one somebody switches off in the first week.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from ledgerlib.chain import canonical_text
from ledgerlib.errors import LedgerError
from ledgerlib.paths import load_json


LOCK_VERSION = 1

# The closed vocabulary of differences, following `DRIFT_REASONS`.
LOCK_DIFFERENCES = frozenset({"added", "removed", "changed", "state_changed"})

_MARKER = '"lock_version"'


def _baseline(ledger: Mapping, baseline_id: object) -> dict:
    baselines = ledger.get("baselines") if isinstance(ledger, Mapping) else None
    for entry in baselines if isinstance(baselines, list) else []:
        if isinstance(entry, Mapping) and entry.get("id") == baseline_id:
            return dict(entry)
    raise LedgerError(f"no baseline with id {baseline_id!r} exists in this ledger")


def _key(entry: Mapping) -> tuple[str, str, str]:
    return (
        str(entry.get("kind") or ""),
        str(entry.get("scope") or ""),
        str(entry.get("anchor") or ""),
    )


def _entries(baseline: Mapping, lockable: frozenset[str]) -> list[dict]:
    rows: list[dict] = []
    items = baseline.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("kind")
        if kind not in lockable:
            continue
        attributes = item.get("attributes")
        scope = attributes.get("scope") if isinstance(attributes, Mapping) else None
        rows.append(
            {
                "kind": kind,
                "name": item.get("name"),
                "anchor": item.get("anchor"),
                "scope": scope if isinstance(scope, str) else None,
                "digest": item.get("digest"),
                "state": item.get("state"),
            }
        )
    rows.sort(key=_key)
    return rows


def build_lock(
    ledger: Mapping, *, baseline_id: str, lockable: frozenset[str]
) -> dict:
    """Assemble the lockfile document from one baseline. Raises on an unknown id."""
    baseline = _baseline(ledger, baseline_id)
    return {
        "lock_version": LOCK_VERSION,
        "generated_from": baseline_id,
        "client": baseline.get("client"),
        "adapter_version": baseline.get("adapter_version"),
        # Carried so a lock taken on one platform is not silently compared
        # against a baseline from another, where whole anchors legitimately
        # do not exist.
        "platform": baseline.get("platform"),
        "entries": _entries(baseline, lockable),
    }


def render_lock(document: Mapping) -> str:
    """The bytes written to disk: indented for reading, ordered for diffing.

    Indented rather than compact because a human reads this in a pull request;
    `sort_keys` and the pre-sorted `entries` are what make the diff mean
    something.
    """
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def check_lock(
    locked: Mapping, ledger: Mapping, *, lockable: frozenset[str]
) -> tuple[list[dict], int]:
    """Compare a lockfile against the baseline it was generated from.

    Returns `(rows, code)`: one row per difference, `0` when identical and `1`
    otherwise. A mismatched `lock_version`, `client` or `platform` is raised
    rather than reported, because comparing across any of those would report
    every entry as added and removed at once, burying the real difference in
    noise that looks like data.
    """
    version = locked.get("lock_version")
    if version != LOCK_VERSION:
        raise LedgerError(
            f"unsupported lock_version {version!r}; this tool writes and reads "
            f"version {LOCK_VERSION}"
        )

    baseline_id = locked.get("generated_from")
    baseline = _baseline(ledger, baseline_id)

    for field in ("client", "platform"):
        expected, found = locked.get(field), baseline.get(field)
        if expected != found:
            raise LedgerError(
                f"this lockfile was generated for {field} {expected!r} and "
                f"baseline {baseline_id!r} records {found!r}: comparing across "
                f"{field}s would report every entry as both added and removed"
            )

    current = {_key(entry): entry for entry in _entries(baseline, lockable)}
    pinned_entries = locked.get("entries")
    pinned = {
        _key(entry): entry
        for entry in (pinned_entries if isinstance(pinned_entries, list) else [])
        if isinstance(entry, Mapping)
    }

    rows: list[dict] = []
    for key in sorted(set(pinned) | set(current)):
        before, after = pinned.get(key), current.get(key)
        if before is None:
            rows.append({**after, "difference": "added"})
            continue
        if after is None:
            rows.append({**before, "difference": "removed"})
            continue
        if before.get("state") != after.get("state"):
            rows.append({**after, "difference": "state_changed"})
        elif before.get("digest") != after.get("digest"):
            rows.append({**after, "difference": "changed"})

    return rows, 1 if rows else 0


def lockable_kinds(adapter: Mapping) -> frozenset[str]:
    """The kinds this adapter declares pinnable. Declared data, never hardcoded."""
    probes = adapter.get("probes") if isinstance(adapter, Mapping) else None
    return frozenset(
        probe["kind"]
        for probe in (probes if isinstance(probes, list) else [])
        if isinstance(probe, Mapping)
        and probe.get("lockable") is True
        and isinstance(probe.get("kind"), str)
    )


def _write_lock(text: str, out: Path, *, force: bool) -> None:
    """Write the lockfile, refusing to clobber a file that is not one.

    The guard `write_dashboard` uses, for the reason it uses it: a typo'd
    `--out` must not consume a file that had nothing to do with this tool.
    """
    if out.exists() and not force:
        try:
            existing = out.read_bytes()
        except OSError as exc:
            raise LedgerError(
                f"cannot read existing file {str(out)!r} to check the "
                f"overwrite guard: {exc}"
            ) from exc
        if _MARKER.encode("utf-8") not in existing:
            raise LedgerError(
                f"refusing to overwrite {str(out)!r}: it does not look like a "
                "lockfile (no lock_version key); pass --force to overwrite it "
                "anyway"
            )
    out.write_text(text, encoding="utf-8", newline="\n")


def lock_command(
    *,
    ledger: Path,
    baseline_id: str | None,
    check: Path | None,
    out: Path | None,
    force: bool,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
) -> int:
    """`lock` as a command. Exit `0` identical or written, `1` differences, `2` tool error."""
    # Imported here rather than at module scope: `adapters` imports nothing
    # from this module, and keeping the dependency at the call site makes that
    # one-way relationship obvious.
    from ledgerlib.adapters import select_adapter_detail
    from ledgerlib.scan import BUNDLED_ADAPTERS

    try:
        document = load_json(ledger)
        client = document.get("client")
        selection = select_adapter_detail(
            client=client if isinstance(client, str) and adapter is None else None,
            adapter=adapter,
            user_config=user_config,
            bundled=BUNDLED_ADAPTERS,
            environ={},
            project=Path.cwd() if project is None else project,
        )
        lockable = lockable_kinds(selection["document"])

        if check is not None:
            locked = load_json(check)
            rows, code = check_lock(locked, document, lockable=lockable)
            for row in rows:
                print(
                    f"{row['difference']}: {row.get('kind')} {row.get('anchor')}",
                    file=sys.stderr,
                )
            print(json.dumps(rows, indent=2, ensure_ascii=False))
            return code

        built = build_lock(document, baseline_id=baseline_id, lockable=lockable)
        text = render_lock(built)
        if out is None:
            print(text, end="")
            return 0
        _write_lock(text, out, force=force)
        print(f"wrote {out}", file=sys.stderr)
        # Printed so `lock --from ... --out ...` still yields the document on
        # stdout for a caller that pipes it, exactly as `scan` does.
        print(canonical_text({"wrote": str(out), "entries": len(built["entries"])}))
        return 0
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2
