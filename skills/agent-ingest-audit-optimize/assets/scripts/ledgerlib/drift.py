"""Classifying recorded baselines and run targets against the environment now.

`drift` is the second read-only half of the ledger tools: it re-resolves the
anchors a ledger recorded, recomputes file digests, and assigns each baseline
item and each `RUN` target one of the five `DRIFT_STATES`. It writes nothing
-- no file, no directory -- and it executes nothing a configuration file
names. Spec `docs/specs/2026-07-30-drift-and-rollback-preview.md` section 3.2
owns the behaviour; design spec section 10 owns the tables below.

Two boundaries are structural rather than stylistic:

- Every path re-resolved from ledger data goes through `resolve_anchored`
  before it is opened. A ledger is content, and its anchors earn dereference
  only because section 10 sanctions exactly that, and only under the path
  safety layer -- there is no second, private resolver here.

- Classification never depends on `resolution` annotations. `classify_item`
  and `classify_target` take the resolved anchor roots and nothing else, so
  the adapter's declared precedence *cannot* reach a classification even by
  accident; `_annotate_resolution` runs after every row is classified and
  writes only the `resolution` key it owns. A shadowed item that drifted is
  still `DRIFTED`.

Nothing reachable from ledger data raises. An anchor that cannot be resolved,
a file that cannot be read, an item that is not even an object -- each becomes
`UNVERIFIABLE` with a reason, because the environment (or the ledger) being
unreadable is a finding about the environment, not a crash in the tool.
"""

from __future__ import annotations

import datetime
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from ledgerlib.adapters import (
    resolve_anchor_roots,
    select_adapter_detail,
)
from ledgerlib.constants import (
    ANCHOR_REFERENCE,
    BASELINE_ITEM_STATES,
    DATE,
    DRIFT_STATES,
)
from ledgerlib.errors import LedgerError, PathSafetyError
from ledgerlib.paths import check_glob, file_digest, load_json, resolve_anchored
from ledgerlib.scan import BUNDLED_ADAPTERS, _resolve_pointer, redact, tomllib
from ledgerlib.validate import validate_ledger


IN_PLACE = "IN_PLACE"
DRIFTED = "DRIFTED"
REVERTED = "REVERTED"
MISSING = "MISSING"
UNVERIFIABLE = "UNVERIFIABLE"

# The reasons this module itself attaches to a classification, following
# `SCAN_REASONS`: a closed set of stable strings, never an exception's own
# text. `PathSafetyError.reason` keys pass through unchanged -- the path layer
# already owns a stable vocabulary for its refusals, and `drift` restating
# them would give one refusal two names. `glob_failed` is shared with
# `SCAN_REASONS` deliberately: it is the same failure, met while re-checking a
# recorded absence rather than while scanning.
DRIFT_REASONS = frozenset(
    {
        "malformed",
        "digest_not_recorded",
        "unreadable",
        "not_regular_file",
        "appeared",
        "glob_failed",
        # The pointer-recheck vocabulary. An absence recorded *inside* a file
        # (`pointer_unresolved`, `no_match`) cannot be re-verified from the
        # file's existence, so it is re-resolved -- or, when the baseline
        # predates the recorded pointer, honestly not verified at all.
        "pointer_unrecorded",
        "parse_unavailable",
        "unparseable",
    }
)

# Characters that mark a stored anchor as a pattern rather than a path. A
# glob probe that matched nothing records its pattern as the item's anchor
# (`scan` has no per-file anchor to record), so re-checking that absence
# means re-matching the pattern -- stat-ing a path with a literal `*` in it
# raises on Windows and answers the wrong question everywhere.
_GLOB_CHARS = frozenset("*?[")


def _recheck_pointer(
    path: Path, attributes: Mapping[str, object], patterns: Sequence[str]
) -> tuple[str, str | None]:
    """Re-resolve a recorded in-file absence against the file as it is now.

    This is the one place `drift` parses a configuration file, and it mirrors
    `scan` exactly -- parse, then `redact` with the same patterns, then walk
    the same pointer -- so the two commands cannot disagree about what
    "absent" means: a pointer that `scan` could not resolve through a redacted
    marker is equally unresolvable here. Nothing the parse produces survives
    this function; the only outputs are a state and a reason, which is what
    keeps a live secret out of a drift report even in memory-dump distance.

    A baseline written before the pointer was recorded (0.2.5 and earlier)
    has nothing to re-resolve and is `UNVERIFIABLE`, `pointer_unrecorded` --
    the honest degradation, not a guess in either direction.
    """
    pointer = attributes.get("pointer")
    fmt = attributes.get("parse")
    if not isinstance(pointer, str) or not pointer or fmt not in ("json", "toml"):
        return UNVERIFIABLE, "pointer_unrecorded"
    if fmt == "toml" and tomllib is None:
        return UNVERIFIABLE, "parse_unavailable"
    try:
        data = path.read_bytes()
    except (OSError, MemoryError):
        return UNVERIFIABLE, "unreadable"
    try:
        if fmt == "toml":
            document: object = tomllib.loads(data.decode("utf-8"))
        else:
            document = json.loads(data)
    except (ValueError, RecursionError):
        return UNVERIFIABLE, "unparseable"
    document = redact(document, patterns)
    found, value = _resolve_pointer(document, pointer)
    # `scan` records `not_present` both for a pointer that does not resolve
    # (`pointer_unresolved`) and for one that resolves to an empty mapping
    # (`no_match`); either condition holding now means the recorded absence
    # holds. Anything else at the location is configuration that appeared.
    if not found or (isinstance(value, dict) and not value):
        return IN_PLACE, None
    return DRIFTED, "appeared"


def classify_item(
    item: object,
    resolved: Mapping[str, Path],
    patterns: Sequence[str] = (),
) -> tuple[str, str | None]:
    """One baseline item against the current environment: spec 3.2's table.

    `resolved` is the anchor-roots mapping `resolve_anchor_roots` returns --
    bare names to resolved directories -- and it is the only context
    classification is allowed: precedence, annotations, and everything else
    the adapter declares stay out of this function by construction.

    The recorded-absence rows are the ones worth stating in prose because
    they are the ones a refactor inverts silently: an absence that holds is
    `IN_PLACE` -- the baseline recorded that it looked and found nothing, and
    nothing is still there -- while a file appearing where none was is
    `DRIFTED`, one of the strongest drift signals there is: configuration
    arriving from outside.

    A `present` item with a null digest was unreadable at scan time; there is
    nothing to compare the current bytes against, whatever they are, so it is
    `UNVERIFIABLE` before the filesystem is touched at all.
    """
    if not isinstance(item, dict):
        return UNVERIFIABLE, "malformed"
    state = item.get("state")
    if state not in BASELINE_ITEM_STATES:
        return UNVERIFIABLE, "malformed"

    recorded = item.get("digest")
    if state == "present" and not isinstance(recorded, str):
        return UNVERIFIABLE, "digest_not_recorded"

    anchor = item.get("anchor")
    if (
        state == "not_present"
        and isinstance(anchor, str)
        and any(char in _GLOB_CHARS for char in anchor)
    ):
        return _classify_absent_pattern(anchor, resolved)

    try:
        path = resolve_anchored(anchor, resolved)
    except PathSafetyError as exc:
        return UNVERIFIABLE, exc.reason

    current, reason = _current_digest(path)

    if state == "not_present":
        if reason == "missing":
            return IN_PLACE, None
        if reason == "unreadable":
            # Something is there but cannot be inspected: neither a verified
            # absence nor a verified arrival.
            return UNVERIFIABLE, reason
        attributes = item.get("attributes")
        recorded_reason = (
            attributes.get("reason") if isinstance(attributes, dict) else None
        )
        # The recorded pointer -- not the reason -- is what marks an in-file
        # absence: `no_match` is also what a literal, wildcard-free glob
        # records when it matches nothing, and for that item the file
        # appearing IS the drift. The baseline verified an absence *inside*
        # a file only when it recorded the location it walked; its presence
        # now answers nothing, so that location is re-resolved.
        if isinstance(attributes, dict) and "pointer" in attributes:
            return _recheck_pointer(path, attributes, patterns)
        if recorded_reason == "pointer_unresolved":
            # An in-file absence from a baseline that predates the recorded
            # pointer: nothing to re-resolve, no verified answer either way.
            return UNVERIFIABLE, "pointer_unrecorded"
        # A digest, a directory, a FIFO: something exists where the baseline
        # verified nothing did.
        return DRIFTED, "appeared"

    if current is None:
        if reason == "missing":
            return MISSING, None
        return UNVERIFIABLE, reason
    if current == recorded:
        return IN_PLACE, None
    return DRIFTED, None


def classify_target(
    target: object, resolved: Mapping[str, Path]
) -> tuple[str, str | None]:
    """One run target against the current environment: design spec 10's table.

    `after_digest` is compared before `before_digest`, and the order is a
    behaviour, not an implementation detail: a target whose two digests are
    equal -- a run that rewrote a file to the same bytes, or recorded a
    no-op honestly -- matches both, and the tie means the change is intact.
    Checking `before` first would report a rollback nobody performed.

    A target with neither digest recorded cannot be compared against
    anything, so it is `UNVERIFIABLE` before the filesystem is touched --
    mirroring the null-digest baseline row, and for the same reason.
    """
    if not isinstance(target, dict):
        return UNVERIFIABLE, "malformed"
    after = target.get("after_digest")
    before = target.get("before_digest")
    if not isinstance(after, str) and not isinstance(before, str):
        return UNVERIFIABLE, "digest_not_recorded"

    try:
        path = resolve_anchored(target.get("anchor"), resolved)
    except PathSafetyError as exc:
        return UNVERIFIABLE, exc.reason

    current, reason = _current_digest(path)
    if current is None:
        if reason == "missing":
            return MISSING, None
        return UNVERIFIABLE, reason
    if current == after:
        return IN_PLACE, None
    if current == before:
        return REVERTED, None
    return DRIFTED, None


def _current_digest(path: Path) -> tuple[str | None, str | None]:
    """The digest of `path`'s bytes now, or `(None, why_not)`.

    The `why_not` vocabulary is deliberately small -- `missing`,
    `not_regular_file`, `unreadable` -- because the two callers branch on it:
    `missing` is a classification of its own, and everything else is a way of
    saying the bytes could not be compared. A FIFO or device node is refused
    for the reason `scan` refuses it: `file_digest` reads the whole file, and
    `open()` on a FIFO nobody feeds blocks forever.
    """
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    if not stat.S_ISREG(info.st_mode):
        return None, "not_regular_file"
    try:
        return file_digest(path), None
    except (OSError, ValueError, MemoryError):
        return None, "unreadable"


def _classify_absent_pattern(
    anchor: str, resolved: Mapping[str, Path]
) -> tuple[str, str | None]:
    """Re-check a recorded absence whose stored form is a glob pattern.

    Matches are tested for existence only, never opened, so the per-path
    `resolve_anchored` discipline does not apply here: the question is "did
    anything appear under this pattern", and answering it reads no bytes. The
    pattern itself still goes through `check_glob` first -- it is ledger
    content, and a `..` segment or an absolute form must be refused exactly
    as it would be at scan time, not walked.
    """
    try:
        check_glob(anchor)
    except PathSafetyError as exc:
        return UNVERIFIABLE, exc.reason
    reference = ANCHOR_REFERENCE.match(anchor.replace("\\", "/"))
    if reference is None:
        return UNVERIFIABLE, "path_malformed_anchor_reference"
    root = resolved.get(reference.group(1))
    if root is None:
        return UNVERIFIABLE, "path_unknown_anchor"
    tail = reference.group(2) or ""
    try:
        matched = any(True for _ in root.glob(tail)) if tail else root.is_dir()
    except (OSError, ValueError, RecursionError, NotImplementedError):
        # The same refusal set `run_probe` catches around `Path.glob`, for
        # the same reason: a pattern the filesystem will not expand is a
        # finding, not a crash, and bare `RuntimeError` stays uncaught
        # because CPython reserves it for genuine defects.
        return UNVERIFIABLE, "glob_failed"
    if matched:
        return DRIFTED, "appeared"
    return IN_PLACE, None


def _annotate_resolution(rows: list[dict], resolution: object) -> None:
    """Attach spec 3.2's resolution annotations beside -- never into -- states.

    Mutates only the `resolution` key of each row, after the whole entry is
    classified. Under `override` a winner is computed for each (kind, name)
    present at more than one scope: the item at the earliest declared scope is
    `effective` and the rest are `shadowed_by` it. `key-override` computes NO
    winner -- layers resolve per key inside parsed documents, so item
    granularity cannot rank whole files -- and carries the declared chain as
    context only. `merge` and `concatenate` carry the mode alone, because the
    mode itself is the answer. A kind absent from the declaration -- or a
    document with no declaration at all -- is reported `"undeclared"`, the
    honest state for cross-scope semantics nobody verified.

    Nothing reachable from ledger or adapter data raises: a malformed kind or
    name (a list is unhashable) simply cannot be declared, so it is
    `undeclared`, and a scope the order does not rank gets no shadowing claim
    rather than an invented rank.
    """
    declared = resolution if isinstance(resolution, dict) else {}

    # Which scopes each (kind, name) is recorded at, across this one entry.
    # Only string-valued scopes can be ranked; a row without one never joins
    # a group and can neither shadow nor be shadowed.
    scopes_present: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        kind, name, scope = row.get("kind"), row.get("name"), row.get("scope")
        if isinstance(kind, str) and isinstance(name, str) and isinstance(scope, str):
            scopes_present.setdefault((kind, name), set()).add(scope)

    for row in rows:
        kind = row.get("kind")
        rule = declared.get(kind) if isinstance(kind, str) else None
        mode = rule.get("mode") if isinstance(rule, dict) else None
        if not isinstance(mode, str):
            row["resolution"] = "undeclared"
            continue
        annotation: dict = {"mode": mode}
        order = rule.get("order")
        if isinstance(order, list):
            annotation["order"] = list(order)
            if mode == "override":
                annotation.update(_override_claim(row, order, scopes_present))
        row["resolution"] = annotation


def _override_claim(
    row: dict,
    order: list,
    scopes_present: Mapping[tuple[str, str], set[str]],
) -> dict:
    """`effective` or `shadowed_by` for one row, or nothing to claim.

    A claim needs a group: an item unique to its scope shadows nothing and is
    shadowed by nothing, so it gets the mode and the chain but no verdict --
    stating `effective` for an unopposed item would read as a computed win
    where no contest happened.
    """
    name, scope = row.get("name"), row.get("scope")
    kind = row.get("kind")
    if not (
        isinstance(kind, str) and isinstance(name, str) and isinstance(scope, str)
    ):
        return {}
    present = scopes_present.get((kind, name), set())
    if len(present) < 2 or scope not in order:
        return {}
    ranked = [candidate for candidate in order if candidate in present]
    if not ranked:
        return {}
    if scope == ranked[0]:
        return {"effective": True}
    return {"shadowed_by": ranked[0]}


def drift_report(
    ledger: dict,
    *,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
    bundled: Path | None = None,
    environ: Mapping[str, str] | None = None,
    today: str | None = None,
) -> tuple[dict, list[str], int]:
    """Classify everything a ledger records. Returns `(report, messages, code)`.

    `today` is a parameter for the reason `scan` takes `captured_on`: expiry
    is a comparison between two dates, and a test must be able to supply both
    sides. Unset, it is the clock's date.

    `messages` follows `scan`'s contract: adapter-selection notes first, then
    findings, one list because they share one stream -- but only findings and
    non-`IN_PLACE` states move `code`. `code` is `0` when every classified
    thing is `IN_PLACE` and nothing was found, `1` otherwise; `2` is not
    returned here at all. A tool error -- an unknown client named by the
    ledger, an unreadable adapter -- is raised as `LedgerError`, and the
    command wrapper is the one place that turns it into `2`, exactly as
    `scan_command` does.

    Anchor resolution reuses the 0.2.5 machinery unchanged: baseline entries
    name their `client`, the ledger's top-level `client` names the client for
    run targets, and `--adapter` overrides selection entirely. `drift` does
    not get a second resolver, because anchor roots are adapter data and two
    resolvers would eventually disagree about which tree is being compared.

    Nothing here writes. The whole call graph beneath it opens files for
    reading and hashes them; a malformed entry becomes a finding naming the
    content `!r` and the report goes on without it, because refusing to
    classify the rest over one broken entry would hide exactly the drift the
    command exists to surface.
    """
    if not isinstance(ledger, dict):
        raise LedgerError("ledger must be a JSON object")

    project = Path.cwd() if project is None else project
    environ = os.environ if environ is None else environ
    bundled = BUNDLED_ADAPTERS if bundled is None else bundled
    today = datetime.date.today().isoformat() if today is None else today

    notes: list[str] = []
    findings: list[str] = []
    # One adapter selection -- and one root resolution -- per client, cached:
    # a ledger with ten baselines for one client must not print ten selection
    # notes or walk the candidate index ten times. With `--adapter` every
    # client shares the one named file, so the cache collapses to one entry.
    # The cache keeps the selected document beside the roots because two
    # later consumers need it: the `resolution` annotations and the
    # adapter-version finding both read declared adapter data.
    context_by_client: dict[object, dict[str, object]] = {}

    def context_for(client: object) -> dict[str, object]:
        name = client if isinstance(client, str) else None
        key = "--adapter" if adapter is not None else name
        if key not in context_by_client:
            selection = select_adapter_detail(
                client=name if adapter is None else None,
                adapter=adapter,
                user_config=user_config,
                bundled=bundled,
                environ=environ,
                project=project,
            )
            notes.extend(selection["notes"])
            document = selection["document"]
            # Expiry mirrors `scan`: both sides are YYYY-MM-DD, which sorts
            # lexicographically in date order, so no parsing is needed. The
            # check lives inside the cache fill so one expired adapter raises
            # one finding, not one per baseline that selected it.
            expires_on = document.get("expires_on")
            if (
                isinstance(expires_on, str)
                and DATE.fullmatch(expires_on)
                and today > expires_on
            ):
                findings.append(
                    f"adapter for client {selection['client']!r} expired on "
                    f"{expires_on!r} and this drift check ran on {today!r}: "
                    "its paths were verified against the vendor's "
                    "documentation before that date and may no longer name "
                    "the files the client reads, so a state reported here "
                    "may describe the wrong tree"
                )
            roots, _unresolved = resolve_anchor_roots(
                document, project=project, environ=environ
            )
            context_by_client[key] = {"roots": roots, "document": document}
        return context_by_client[key]

    counts = {state: 0 for state in sorted(DRIFT_STATES)}

    def classified(state: str) -> None:
        counts[state] += 1

    baselines: list[dict] = []
    entries = ledger.get("baselines")
    if not isinstance(entries, list):
        if entries is not None:
            findings.append(
                f"ledger baselines must be an array and was not classified: "
                f"{entries!r}"
            )
        entries = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            findings.append(
                f"baselines[{position}] is not an object and was not "
                f"classified: {entry!r}"
            )
            continue
        client = entry.get("client")
        if not isinstance(client, str):
            # A baseline that does not say whose configuration it recorded is
            # classified under the ledger's own client rather than skipped:
            # the items still name anchors, and the top-level client is the
            # only honest guess the document offers.
            client = ledger.get("client")
        context = context_for(client)
        roots = context["roots"]
        document = context["document"]
        # A version-1 baseline is still comparable under a version-2 adapter
        # -- item digests are file digests and the anchors did not move -- so
        # the mismatch is a finding on the entry, never a refusal and never
        # silence (spec 3.1).
        recorded_version = entry.get("adapter_version")
        current_version = document.get("adapter_version")
        if recorded_version != current_version:
            findings.append(
                f"baseline {entry.get('id')!r} was captured at "
                f"adapter_version {recorded_version!r} and the selected "
                f"adapter for client {client!r} is version "
                f"{current_version!r}: the items are still classified, and "
                "the comparison crosses adapter versions"
            )
        rows: list[dict] = []
        items = entry.get("items")
        if not isinstance(items, list):
            findings.append(
                f"baseline {entry.get('id')!r} items must be an array and "
                f"was not classified: {items!r}"
            )
            items = []
        # The adapter's redaction patterns ride along so the pointer recheck
        # walks the same document `scan` walked, not a more revealing one.
        declared_patterns = document.get("sensitive_key_patterns")
        patterns = (
            tuple(p for p in declared_patterns if isinstance(p, str))
            if isinstance(declared_patterns, list)
            else ()
        )
        for item in items:
            state, reason = classify_item(item, roots, patterns)
            classified(state)
            attributes = item.get("attributes") if isinstance(item, dict) else None
            scope = (
                attributes.get("scope") if isinstance(attributes, dict) else None
            )
            rows.append(
                {
                    "kind": item.get("kind") if isinstance(item, dict) else None,
                    "name": item.get("name") if isinstance(item, dict) else None,
                    "anchor": item.get("anchor") if isinstance(item, dict) else None,
                    "scope": scope if isinstance(scope, str) else None,
                    "recorded_state": (
                        item.get("state") if isinstance(item, dict) else None
                    ),
                    "state": state,
                    "reason": reason,
                }
            )
        # After the whole entry is classified, never before or during: the
        # annotation pass reads states only to sit beside them, and running it
        # last is what keeps the adapter's declared precedence out of
        # `classify_item` structurally rather than by good intentions.
        _annotate_resolution(rows, document.get("resolution"))
        baselines.append({"id": entry.get("id"), "client": client, "items": rows})

    runs: list[dict] = []
    records = ledger.get("records")
    if not isinstance(records, list):
        if records is not None:
            findings.append(
                f"ledger records must be an array and was not classified: "
                f"{records!r}"
            )
        records = []
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "RUN":
            continue
        targets = record.get("targets")
        if not isinstance(targets, list):
            findings.append(
                f"record {record.get('id')!r} targets must be an array and "
                f"was not classified: {targets!r}"
            )
            continue
        roots = context_for(ledger.get("client"))["roots"]
        rows = []
        for target in targets:
            state, reason = classify_target(target, roots)
            classified(state)
            rows.append(
                {
                    "kind": target.get("kind") if isinstance(target, dict) else None,
                    "anchor": (
                        target.get("anchor") if isinstance(target, dict) else None
                    ),
                    "state": state,
                    "reason": reason,
                }
            )
        runs.append({"id": record.get("id"), "targets": rows})

    report = {"baselines": baselines, "runs": runs, "summary": counts}
    drifted = sum(count for state, count in counts.items() if state != IN_PLACE)
    code = 1 if findings or drifted else 0
    return report, [*notes, *findings], code


def drift_command(
    *,
    ledger: Path,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
) -> int:
    """`drift` as a command: the report to stdout, everything else to stderr.

    The split of streams is `scan_command`'s contract, kept for the same
    reason: a caller pipes stdout straight into a JSON reader, so not one
    byte that is not the report may go there -- notes, findings, and tool
    errors all go to stderr.

    Exit codes match `verify` and `scan`: `0` when everything is `IN_PLACE`
    and nothing was found, `1` when any state is not `IN_PLACE` or any
    finding was raised, `2` on tool error. An invalid ledger is a tool error
    rather than a finding, and `validate_ledger` is reused rather than
    re-implemented: `drift` classifies what a ledger records, and a document
    the validator refuses is not a record of anything -- classifying its
    contents anyway would print states derived from fields nothing vouched
    for.

    `sys.stdout` and `sys.stderr` are looked up at call time rather than
    bound as defaults, so a caller redirecting either -- as the tests do --
    gets what it redirected.
    """
    try:
        document = load_json(ledger)
        invalid = validate_ledger(document, source=str(ledger))
        if invalid:
            for finding in invalid:
                print(finding, file=sys.stderr)
            return 2
        report, messages, code = drift_report(
            document,
            adapter=adapter,
            user_config=user_config,
            project=project,
        )
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2

    for message in messages:
        print(message, file=sys.stderr)
    print(json.dumps(report, indent=2))
    return code
