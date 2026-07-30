"""Adapter loading, validation, and anchor-root resolution.

An adapter is data: which anchors a client keeps its configuration under,
which files to probe beneath them, and which key names carry secrets. Spec
`docs/specs/2026-07-30-adapters-and-scan.md` section 3.2 owns the format;
`assets/schemas/adapter.schema.json` documents it for humans and external
tools, and `validate_adapter` below is what actually runs -- the bundle has
no JSON Schema library and never grows one. The two are held together by
`SchemaAgreementTests`, which compares them in both directions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ledgerlib.constants import (
    ANCHOR_NAME,
    BASELINE_ITEM_KINDS,
    DATE,
)
from ledgerlib.errors import (
    LedgerError,
    PathSafetyError,
)
from ledgerlib.paths import check_glob, load_json


CLIENT_NAME = re.compile(r"^[a-z0-9-]+$")

REQUIRED_ADAPTER_FIELDS = {
    "adapter_version",
    "client",
    "expires_on",
    "anchors",
    "probes",
    "sensitive_key_patterns",
}
# Every top-level field is required, so the known set and the required set are
# the same set today. They are named separately because the schema states them
# separately (`required` and `properties`), and the agreement test compares
# each against its own counterpart: an optional field added later must appear
# in `properties` and not in `required`, and one shared constant would hide
# exactly that mistake.
ADAPTER_FIELDS = set(REQUIRED_ADAPTER_FIELDS)

REQUIRED_PROBE_FIELDS = {"kind"}
PROBE_FIELDS = {"kind", "scope", "glob", "path", "parse", "pointer"}
PARSE_FORMATS = {"json", "toml"}

ENV_CANDIDATE_PREFIX = "$env:"


def validate_adapter(data: dict, *, source: str) -> list[str]:
    """Collect every finding an adapter document produces.

    Follows `validate_ledger`'s shape exactly: findings are collected and
    returned, nothing is raised for bad content, and every message that
    interpolates adapter content uses `!r`. `load_adapter` is the one place
    that turns findings into an exception, because a caller holding a broken
    adapter has nothing to proceed with.
    """
    if not isinstance(data, dict):
        return [f"{source}: adapter must be a JSON object"]

    findings: list[str] = []
    missing = REQUIRED_ADAPTER_FIELDS - set(data)
    unknown = set(data) - ADAPTER_FIELDS
    if missing:
        findings.append(f"{source}: missing fields: {sorted(missing)}")
    if unknown:
        findings.append(f"{source}: unknown fields: {sorted(unknown)}")
    if missing:
        return findings

    # `type(x) is not int` rather than isinstance, for the same reason
    # `validate_ledger` does it: bool is a subclass of int, and `True` would
    # otherwise pass as a valid version number.
    if type(data["adapter_version"]) is not int or data["adapter_version"] < 1:
        findings.append(f"{source}: adapter_version must be an integer of at least 1")

    client = data["client"]
    if not isinstance(client, str) or not client:
        findings.append(f"{source}: client must be a non-empty string")
    elif not CLIENT_NAME.fullmatch(client):
        # A separate message from the empty case on purpose: an uppercase or
        # spaced name is a naming mistake, not a missing value, and the two
        # are fixed differently.
        findings.append(f"{source}: client must match [a-z0-9-]+: {client!r}")

    expires_on = data["expires_on"]
    if not isinstance(expires_on, str) or not DATE.fullmatch(expires_on):
        findings.append(f"{source}: expires_on must match YYYY-MM-DD")

    findings.extend(_validate_anchors(data["anchors"], source=source))

    probes = data["probes"]
    if not isinstance(probes, list):
        findings.append(f"{source}: probes must be an array")
    else:
        for index, probe in enumerate(probes):
            findings.extend(_validate_probe(probe, index, source=source))

    patterns = data["sensitive_key_patterns"]
    if not isinstance(patterns, list):
        findings.append(f"{source}: sensitive_key_patterns must be an array")
    else:
        for index, pattern in enumerate(patterns):
            if not isinstance(pattern, str) or not pattern:
                findings.append(
                    f"{source}: sensitive_key_patterns[{index}] must be a "
                    f"non-empty string: {pattern!r}"
                )

    return findings


def _validate_anchors(anchors: object, *, source: str) -> list[str]:
    if not isinstance(anchors, dict):
        return [f"{source}: anchors must be an object"]

    findings: list[str] = []
    for name, candidates in anchors.items():
        # The stored form is `$NAME`; `ANCHOR_NAME` owns the grammar of what
        # follows the `$`, and is imported rather than restated so an anchor
        # name this file accepts is one `resolve_anchored` can parse back.
        if (
            not isinstance(name, str)
            or not name.startswith("$")
            or not ANCHOR_NAME.fullmatch(name[1:])
        ):
            findings.append(f"{source}: anchors has an invalid anchor name: {name!r}")
            continue
        if not isinstance(candidates, list) or not candidates:
            findings.append(
                f"{source}: anchors.{name} must be a non-empty array of candidates"
            )
            continue
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, str) or not candidate:
                findings.append(
                    f"{source}: anchors.{name}[{index}] must be a "
                    f"non-empty string: {candidate!r}"
                )
    return findings


def _validate_probe(probe: object, index: int, *, source: str) -> list[str]:
    label = f"{source}: probes[{index}]"
    if not isinstance(probe, dict):
        return [f"{label} must be an object"]

    missing = REQUIRED_PROBE_FIELDS - set(probe)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]
    unknown = set(probe) - PROBE_FIELDS
    if unknown:
        return [f"{label} has unknown fields: {sorted(unknown)}"]

    findings: list[str] = []
    kind = probe["kind"]
    if not isinstance(kind, str) or kind not in BASELINE_ITEM_KINDS:
        findings.append(f"{label} has an invalid kind: {kind!r}")

    has_glob = "glob" in probe
    has_path = "path" in probe
    if has_glob and has_path:
        findings.append(f"{label} must have exactly one of glob or path: it has both")
    elif not has_glob and not has_path:
        findings.append(f"{label} must have exactly one of glob or path: it has neither")

    # Both fields go through `check_glob`, at LOAD time. A `..` segment or an
    # absolute form is refused here, before any anchor has been resolved and
    # long before anything is expanded, so a hostile adapter cannot get one
    # directory walk out of the tool. This says nothing about what the
    # filesystem holds at scan time -- `resolve_anchored` per opened path is
    # the other half, and neither replaces the other.
    for field in ("glob", "path"):
        if field in probe:
            try:
                check_glob(probe[field])
            except PathSafetyError as exc:
                findings.append(
                    f"{label} {field} is refused by check_glob [{exc.reason}]: {exc}"
                )

    if "scope" in probe:
        scope = probe["scope"]
        if not isinstance(scope, str) or not scope.strip():
            findings.append(f"{label} scope must be a non-empty string: {scope!r}")

    if "parse" in probe:
        parse = probe["parse"]
        if not isinstance(parse, str) or parse not in PARSE_FORMATS:
            findings.append(f"{label} has an invalid parse: {parse!r}")
        if has_glob and not has_path:
            # Parsing is per-document. A glob yields many documents and the
            # probe names one pointer, so the pairing has no meaning to honour.
            findings.append(f"{label} parse requires path, not glob")

    if "pointer" in probe:
        pointer = probe["pointer"]
        if "parse" not in probe:
            findings.append(f"{label} pointer requires parse")
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            findings.append(f"{label} pointer must start with '/': {pointer!r}")

    return findings


def load_adapter(path: Path) -> dict:
    """Read and validate an adapter, raising on any finding.

    Unlike a ledger, whose findings are reported and counted, an adapter with
    a finding is unusable: every probe under it is suspect, and continuing
    would produce a baseline that looks clean because it scanned nothing.
    """
    data = load_json(path)
    findings = validate_adapter(data, source=str(path))
    if findings:
        raise LedgerError("\n".join(findings))
    return data


def resolve_anchor_roots(
    adapter: dict, *, project: Path, environ: Mapping[str, str]
) -> tuple[dict[str, Path], list[str]]:
    """Resolve each anchor to the first candidate that is an existing directory.

    Returns the resolved roots and the names of the anchors that resolved to
    nothing. Both use the anchor's BARE name -- `USER_CONFIG`, not
    `$USER_CONFIG` -- because that is the key space `anchor_path` and
    `resolve_anchored` require: `_validate_anchor_names` refuses a key that
    is not `[A-Z_]+`, and `ANCHOR_REFERENCE` parses `$USER_CONFIG/x` back to
    exactly that bare name. One key space, used by both directions.

    `environ` is a parameter rather than a read of `os.environ` so a caller --
    and every test -- can supply an environment without mutating the process.

    An unresolved anchor is absent from the mapping rather than mapped to a
    guess. `scan` records every probe beneath it as `not_present`; the
    alternative, defaulting to the vendor's documented root, is precisely the
    failure `docs/research/2026-07-30-client-configuration-paths.md` section 1
    warns about -- `CLAUDE_CONFIG_DIR` and `CODEX_HOME` relocate everything,
    and an adapter that scans the default tree anyway reports a clean baseline
    for a configuration it never looked at.

    Roots are returned absolute and resolved because that is what the path
    layer expects: `anchor_path` matches a resolved path against them with
    `relative_to`, which compares components literally.
    """
    anchors = adapter.get("anchors")
    if not isinstance(anchors, dict):
        return {}, []

    base = _safe_resolve(project)
    roots: dict[str, Path] = {}
    unresolved: list[str] = []
    for name, candidates in anchors.items():
        bare = name[1:] if isinstance(name, str) and name.startswith("$") else name
        root = _first_existing_directory(candidates, project=base, environ=environ)
        if root is None:
            unresolved.append(bare)
        else:
            roots[bare] = root
    return roots, unresolved


def _first_existing_directory(
    candidates: object, *, project: Path | None, environ: Mapping[str, str]
) -> Path | None:
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        if candidate.startswith(ENV_CANDIDATE_PREFIX):
            # Unset and empty are the same thing here. An empty variable is
            # what a shell leaves behind after `export CLAUDE_CONFIG_DIR=`,
            # and treating it as a root would resolve to the process's
            # working directory.
            value = environ.get(candidate[len(ENV_CANDIDATE_PREFIX) :], "")
            if not value:
                continue
            resolved = _candidate_path(value, project=project)
        else:
            resolved = _candidate_path(candidate, project=project)
        if resolved is None:
            continue
        try:
            # A candidate that exists but is a file does not qualify: an
            # anchor root is a directory, and joining a probe's tail onto a
            # file would produce paths that can never resolve.
            if resolved.is_dir():
                return resolved
        except (OSError, ValueError):
            continue
    return None


def _candidate_path(candidate: str, *, project: Path | None) -> Path | None:
    """Expand `~`, anchor a relative candidate at `project`, and resolve."""
    try:
        path = Path(candidate).expanduser()
    except (OSError, ValueError, RuntimeError):
        # `expanduser` raises RuntimeError when `~` cannot be resolved to a
        # home directory at all. A candidate that cannot be expanded is a
        # candidate that does not qualify, not a reason to abandon the anchor.
        return None
    if not path.is_absolute() and project is not None:
        # `.` -- and any other relative candidate -- resolves against the
        # `project` argument, never the process working directory. `scan` may
        # be invoked from anywhere; the tree it reports on is the one the
        # caller named.
        path = project / path
    return _safe_resolve(path)


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        # Same failure set `paths._resolve_or_raise` converts: a NUL byte, a
        # trailing-dot segment on Windows, a POSIX symlink loop. Here it means
        # "this candidate does not qualify", so it is swallowed rather than
        # raised -- resolving an anchor root is a survey, not an access.
        return None
