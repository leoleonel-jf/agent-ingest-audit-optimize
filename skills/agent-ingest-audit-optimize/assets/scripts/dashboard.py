#!/usr/bin/env python3
"""Validate the agent-ingest-audit-optimize governance ledger.

`verify` is the only command implemented. Scanning, drift detection, rollback
preview, and dashboard rendering arrive in later phases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


SCHEMA_VERSION = "1.0"

REQUIRED_LEDGER_FIELDS = {
    "schema_version",
    "ledger_id",
    "scope",
    "language",
    "client",
    "adapter_version",
    "created",
    "updated",
    "id_authority",
    "sequences",
    "known_projects",
    "records",
    "baselines",
    "backlog",
}

SEQUENCE_PREFIXES = ("MAT", "PROP", "RUN", "ADR", "BASE")
LEDGER_SCOPES = {"global", "project"}
ARRAY_FIELDS = ("known_projects", "records", "baselines", "backlog")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

RECORD_ID = re.compile(r"^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$")
PROVISIONAL_ID = re.compile(r"-P$")
RECORD_TYPES = {"MATERIAL", "PROPOSAL", "RUN", "ADR", "BASELINE"}
RECORD_STATUSES = {
    "ANALYZED",
    "PROPOSED",
    "DECIDED",
    "IMPLEMENTED",
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "NOT IMPLEMENTED",
    "PENDING",
    "ROLLBACK",
    "SUPERSEDED",
}
CLASSIFICATIONS = {
    "ADOPT GLOBALLY",
    "ADOPT AS A DEFAULT FOR NEW PROJECTS",
    "MIGRATE EXISTING PROJECTS",
    "ADOPT LOCALLY",
    "TEST IN ISOLATION",
    "ADAPT",
    "MONITOR",
    "REJECT",
    "OBSOLETE",
    "ALREADY IMPLEMENTED",
    "NOT APPLICABLE",
    "NEEDS MORE EVIDENCE",
    "RISK EXCEEDS BENEFIT",
}
RECORD_SCOPES = {
    "session",
    "project",
    "workspace",
    "user-global",
    "organization",
    "fleet",
}
LINK_FIELDS = ("materials", "runs", "adrs")
REQUIRED_RECORD_FIELDS = {
    "id",
    "type",
    "title",
    "status",
    "classification",
    "scope",
    "created",
    "updated",
    "file",
    "links",
    "evidence",
}
EVIDENCE_FIELDS = {"source", "kind", "verified_on", "time_sensitive"}

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RESULTS = {
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "PARTIALLY VALIDATED",
    "NOT VALIDATED",
    "FAILED",
    "ROLLBACK COMPLETED",
}
ROLLBACK_TEST_STATES = {"NOT_TESTED", "PARTIAL", "PASSED", "FAILED"}
REQUIRED_RUN_FIELDS = {
    "proposal",
    "authorization",
    "result",
    "targets",
    "backup",
    "rollback",
    "self_reported",
}
REQUIRED_TARGET_FIELDS = {
    "anchor",
    "kind",
    "before_digest",
    "after_digest",
    "reversible",
    "residual_effect",
}

BACKLOG_CLASSIFICATIONS = {
    "REJECT",
    "NEEDS MORE EVIDENCE",
    "RISK EXCEEDS BENEFIT",
    "MONITOR",
    "TEST IN ISOLATION",
}
TERMINAL_CLASSIFICATIONS = {"OBSOLETE", "NOT APPLICABLE", "ALREADY IMPLEMENTED"}
REQUIRED_BACKLOG_FIELDS = {
    "id",
    "classification",
    "reason",
    "revisit_trigger",
    "revisit_after",
}
PROJECT_STATUSES = {"OK", "UNREACHABLE", "CHANGED_EXTERNALLY"}
REQUIRED_PROJECT_FIELDS = {
    "project_root",
    "ledger_path",
    "last_seen",
    "last_digest",
    "status",
}

BASELINE_ITEM_KINDS = {
    "instruction-file",
    "skill",
    "plugin",
    "agent",
    "command",
    "hook",
    "mcp-server",
    "permission-rule",
    "model-setting",
    "env-var-name",
}
BASELINE_ITEM_STATES = {"present", "not_present"}
REQUIRED_BASELINE_FIELDS = {"id", "captured_on", "client", "adapter_version", "items"}
REQUIRED_BASELINE_ITEM_FIELDS = {
    "kind",
    "name",
    "anchor",
    "digest",
    "attributes",
    "origin",
    "state",
}

ANCHOR_REFERENCE = re.compile(r"^\$([A-Z_]+)(?:/(.*))?\Z")
ANCHOR_NAME = re.compile(r"^[A-Z_]+$")
# CON, PRN, AUX, NUL, COM1-9, LPT1-9, with or without an extension. Reserved
# on Windows regardless of extension or case; refused on every platform
# because a ledger written on Windows may be validated on Linux and must get
# the same answer either way.
DEVICE_NAME = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", re.IGNORECASE)


class LedgerError(RuntimeError):
    """Raised when a ledger cannot be read at all."""


class PathSafetyError(RuntimeError):
    """Raised when a path may not be resolved under its anchor.

    Every refusal carries a stable `reason` key in addition to its ordinary
    human-readable message, so a caller -- and this module's own alignment
    test against `references/LEDGER.md` -- can enumerate every refusal the
    path-safety layer can produce without parsing message text.
    `PATH_SAFETY_REASONS` is the definitive, exhaustive set of keys this
    exception can carry.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# The exhaustive set of reason keys any PathSafetyError raised anywhere in
# this module can carry. `references/LEDGER.md` must document exactly this
# set -- no more, no fewer. `PathSafetyReasonAlignmentTests` in
# dashboard/tests/test_dashboard.py checks both directions: every key here
# must be documented there, and every key documented there must be one the
# code can actually raise -- so a tenth refusal added to the code without
# being documented fails the test, and so does a documented reason the code
# can no longer raise.
PATH_SAFETY_REASONS = frozenset(
    {
        "invalid_anchor_name",
        "glob_not_string",
        "glob_nul_byte",
        "glob_dotdot_segment",
        "glob_absolute",
        "resolve_failed",
        "path_empty",
        "path_embedded_nul",
        "path_dotdot_segment",
        "path_absolute",
        "path_malformed_anchor_reference",
        "path_unknown_anchor",
        "path_reserved_device_name",
        "path_alternate_data_stream",
        "path_link_crosses_anchor",
        "path_resolves_outside_anchor",
        "path_inspect_failed",
        "path_hardlinked",
    }
)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LedgerError(f"Missing ledger: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise LedgerError(f"Unreadable ledger: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LedgerError(f"Ledger must be a JSON object: {path}")
    return value


def file_digest(path: Path) -> str:
    """Hash a ledger's final on-disk bytes.

    The digest recorded in `known_projects[].last_digest` describes the file as
    written, so it must be taken from the bytes on disk: a trailing newline or a
    line-ending difference changes the hash of an otherwise identical document.
    """
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _path_key(value: str) -> str:
    """Normalize a path for comparison without touching the filesystem.

    `ledger_path` is ledger content, and ledger content is attacker-influenced.
    This normalizes textually -- never resolving, never opening -- so comparing
    a ledger's stored path against the paths the user named cannot be steered
    into reading somewhere else.

    `normpath`'s textual `..` collapse is correct on Windows, whose own path
    normalization is likewise textual, but it is unsound across POSIX
    symlinks. `resolve()` is deliberately not used here: the whole point is
    to never touch the filesystem for a ledger-supplied value.
    """
    return os.path.normcase(os.path.normpath(value))


def _validate_anchor_names(roots: dict[str, Path]) -> None:
    """Refuse a roots mapping containing a key that is not a valid anchor name.

    A key must match the same `[A-Z_]+` grammar `ANCHOR_REFERENCE` uses. Two
    concrete dangers motivate checking every key, not just the one a given
    call happens to look up: a key containing '/' (e.g. "A/B") can steal a
    prefix of another key's namespace -- a stored form like "$A/B/x" is
    parsed as anchor "A" with tail "B/x", silently redirecting into whatever
    root "A" names instead of the "A/B" root that produced the string. And
    any other malformed key (lowercase, digits, hyphens, empty) produces a
    stored form `resolve_anchored` can never parse back, since `ANCHOR_REFERENCE`
    would not match it either -- a silent dead end for a plausible adapter
    name, rather than a loud rejection at the point the mapping was built.
    """
    for name in roots:
        if not ANCHOR_NAME.fullmatch(name):
            raise PathSafetyError(
                f"anchor name is not a valid identifier: {name!r}",
                reason="invalid_anchor_name",
            )


def anchor_path(path: Path, roots: dict[str, Path]) -> tuple[str, bool]:
    """Store a path relative to the anchor that contains it.

    Returns the stored form and whether it is portable. Per design spec 7.1,
    absolute paths are never stored when an anchor applies, and anything
    outside every anchor is stored absolute and flagged portable: false.

    When more than one anchor contains the path the longest root wins, so a
    project nested inside a user configuration root anchors to $PROJECT rather
    than $USER_CONFIG. The design spec does not state this; the more specific
    anchor is the only choice that keeps both meaningful.

    `path` is always resolved before matching, even when it is already
    absolute: an absolute path can still carry a fabricated `..` segment
    (e.g. `root/../outside/secret.txt`), and `relative_to` matches such a
    path against `root` textually, since `root`'s components remain a
    literal prefix of it. Resolving first collapses `..` (and any symlink)
    to where the path actually points, so a path that truly lands outside
    every anchor is matched -- and stored -- honestly, per design spec 7.1.

    M13: when two different names map to roots of the same depth (most
    concretely, two names for the identical root), the winner is the one
    that sorts first by anchor name -- not whichever happened to be inserted
    into `roots` first. `dict` iteration order is insertion order, and a tie
    broken by "first seen" is not a property of the anchors at all.

    I2: `path.resolve()` is routed through `_resolve_or_raise` rather than
    called bare, exactly as `resolve_anchored` already does for the identical
    operation. Some inputs make the filesystem itself raise here too -- a
    trailing-dot/space segment following an existing file component raises
    `NotADirectoryError` on Windows -- and a raw `OSError` escaping this
    function would break the same contract `resolve_anchored` protects:
    `PathSafetyError` is the only thing a caller should have to catch.
    """
    _validate_anchor_names(roots)
    absolute = _resolve_or_raise(path, str(path))
    best: tuple[int, str, Path] | None = None
    for name, root in roots.items():
        try:
            relative = absolute.relative_to(root)
        except ValueError:
            continue  # not under this root; relative_to compares components
        depth = len(root.parts)
        if best is None or depth > best[0] or (depth == best[0] and name < best[1]):
            best = (depth, name, relative)
    if best is None:
        return str(absolute), False
    _, name, relative = best
    tail = relative.as_posix()
    return (f"${name}" if tail == "." else f"${name}/{tail}"), True


def check_glob(pattern: str) -> None:
    """Refuse a probe glob that could escape its anchor.

    Design spec section 9: no probe field may contain a glob that escapes its
    anchor; `scan` rejects `..` segments and absolute globs.

    This validates the PATTERN only. Nothing here expands it: every path a
    glob later expands to must still be passed through `resolve_anchored`,
    because a glob hit can itself be a link that leaves the anchor -- a
    clean pattern says nothing about what it might match once there is a
    directory to expand it against.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        raise PathSafetyError(
            f"glob must be a non-empty string: {pattern!r}", reason="glob_not_string"
        )
    if "\0" in pattern:
        raise PathSafetyError(
            f"glob contains a NUL byte: {pattern!r}", reason="glob_nul_byte"
        )
    normalized = pattern.replace("\\", "/")
    for part in normalized.split("/"):
        # A segment made up entirely of dots and/or spaces -- ".." itself,
        # but also "...", ".. ", ". .", and similar -- collapses to nothing
        # once Windows strips trailing dots and spaces from it, exactly the
        # way ntpath.realpath does when a path built from this glob is later
        # resolved. Stripping trailing dots/spaces here before testing is
        # what keeps this normalizer from being more relaxed than that one.
        # "" and "." are excluded: an empty segment (from a repeated "/")
        # and a literal single-dot segment are ordinary no-ops, not escapes.
        if part not in ("", ".") and part.rstrip(" .") == "":
            raise PathSafetyError(
                f"glob contains a '..' segment: {pattern!r}",
                reason="glob_dotdot_segment",
            )
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise PathSafetyError(f"glob is absolute: {pattern!r}", reason="glob_absolute")


def _resolve_or_raise(path: Path, stored: str) -> Path:
    """Resolve `path`, turning any `OSError` into a `PathSafetyError`.

    Some inputs make the filesystem itself raise -- a trailing-dot/space
    segment following an existing file component raises `NotADirectoryError`
    on Windows, for instance. Design spec section 3.2 says a `PathSafetyError`
    carries the offending path and the rule that refused it, and callers
    (`scan`, eventually) report it as a finding; a raw `OSError` escaping here
    would instead abort a caller mid-walk on a ledger-supplied string.

    Shared by `resolve_anchored` and `anchor_path` (I2): both resolve a path
    at the point they touch the filesystem, and both must give the identical
    guarantee that only `PathSafetyError` ever escapes.
    """
    try:
        return path.resolve()
    except OSError as exc:
        raise PathSafetyError(
            f"path could not be resolved: {stored!r}: {exc}", reason="resolve_failed"
        ) from exc


def resolve_anchored(stored: str, roots: dict[str, Path]) -> Path:
    """Resolve an anchored path, refusing anything that escapes its anchor.

    Design spec section 13.6: refuse to read or write outside resolved anchors,
    and reject symlinks that escape an anchor. The `..` check is textual and
    runs before any normalization, so a path that normalizes back inside the
    root is still refused -- the form is the problem, not just the destination.

    The returned path is validated at resolution time only. A caller that
    resolves many paths over time -- rather than resolving one path and
    immediately acting on it -- must re-check per use rather than trust a
    single resolution done once per root: nothing here can see a link
    created after this call returns.

    I1: a stored path carrying an embedded NUL byte is refused here, before
    anything touches the filesystem -- mirroring `check_glob`'s identical
    guard on a probe pattern. Without it, a NUL survives every textual check
    below (it is not a `..` segment, not absolute, not an unknown anchor) and
    reaches `_refuse_if_hardlinked`'s `path.stat()`, which raises a bare
    `ValueError` -- `stat: embedded null character in path` -- that is not an
    `OSError` and was not caught there.
    """
    if not isinstance(stored, str) or not stored.strip():
        raise PathSafetyError(
            f"path must be a non-empty string: {stored!r}", reason="path_empty"
        )
    if "\0" in stored:
        raise PathSafetyError(
            f"path contains a NUL byte: {stored!r}", reason="path_embedded_nul"
        )
    _validate_anchor_names(roots)
    normalized = stored.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        raise PathSafetyError(
            f"path contains a '..' segment: {stored!r}", reason="path_dotdot_segment"
        )
    # Rule 3 gets its own message, distinct from a malformed-or-missing
    # anchor reference below: an absolute path is a different problem from a
    # string that merely fails to parse as $NAME/..., and a caller cannot
    # tell them apart from one shared "not anchored" message.
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise PathSafetyError(
            f"path is absolute; an anchor reference was required: {stored!r}",
            reason="path_absolute",
        )
    match = ANCHOR_REFERENCE.match(normalized)
    if match is None:
        raise PathSafetyError(
            f"path does not match a valid anchor reference: {stored!r}",
            reason="path_malformed_anchor_reference",
        )
    name, tail = match.group(1), match.group(2) or ""
    root = roots.get(name)
    if root is None:
        raise PathSafetyError(
            f"path names an unknown anchor ${name}: {stored!r}",
            reason="path_unknown_anchor",
        )

    base = _resolve_or_raise(root, stored)
    candidate = base if not tail else base.joinpath(*tail.split("/"))

    # Rule 5 before rule 4: this does not ask whether a component IS a link --
    # Path.is_symlink() returns False for a Windows directory junction even
    # though Path.resolve() follows one, so an is_symlink() test misses
    # exactly the redirection a junction performs. Instead this asks where
    # each PREFIX of the path resolves: for every component walked so far,
    # resolve that prefix and require the result to still be within the
    # anchor. A symlink or junction whose target leaves the anchor makes some
    # prefix resolve outside, so both are caught identically, even when the
    # full path later leads back inside -- because a link that leaves the
    # anchor is one an attacker can re-point later. This is what makes the
    # rule work for any redirection mechanism the platform offers, not only
    # the ones Path.is_symlink() happens to recognize. A prefix that does not
    # exist yet resolves normally (Path.resolve() is non-strict by default)
    # and simply is not yet outside anything.
    walked = base
    for part in (tail.split("/") if tail else []):
        # Textual, component-level refusals: these run before the prefix is
        # ever resolved, since a DOS device name or an alternate data stream
        # is a property of the component itself, not of where it resolves.
        if DEVICE_NAME.fullmatch(part):
            raise PathSafetyError(
                f"path contains a reserved device name {part!r}: {stored!r}",
                reason="path_reserved_device_name",
            )
        if ":" in part:
            raise PathSafetyError(
                f"path component contains ':': {stored!r}",
                reason="path_alternate_data_stream",
            )
        walked = walked / part
        resolved_prefix = _resolve_or_raise(walked, stored)
        if not _is_within(resolved_prefix, base):
            raise PathSafetyError(
                f"path crosses a link that leaves its anchor: {stored!r}",
                reason="path_link_crosses_anchor",
            )

    # Rule 4 is not an ordinary backstop -- for any non-empty tail it looks at
    # exactly the same prefix rule 5's last loop iteration already resolved,
    # so in a single deterministic pass it never fires first. What it actually
    # is: a re-check against a TOCTOU window. `candidate.resolve()` here is a
    # LATER syscall than the loop's last `walked.resolve()` above, so between
    # that call and this one a component could change (a directory replaced
    # by a symlink or junction, for instance) and this is what would catch it.
    # Keep it ordered after rule 5, with its own message, precisely because it
    # covers a different moment in time, not a different path.
    final = _resolve_or_raise(candidate, stored)
    if not _is_within(final, base):
        raise PathSafetyError(
            f"path resolves outside its anchor: {stored!r}",
            reason="path_resolves_outside_anchor",
        )
    _refuse_if_hardlinked(final, stored)
    return final


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _refuse_if_hardlinked(path: Path, stored: str) -> None:
    """Refuse a resolved path that names an existing hardlinked regular file.

    I4: a hardlink defeats every rule above by construction -- it needs no
    elevation to create (`mklink /H` on Windows, `ln` on POSIX), and it has
    no symlink target for rules 4/5 to follow, so they cannot see it at all.
    Writing through it writes through to whatever else the same file is
    linked from, wherever that is.

    Directories are deliberately excluded: a directory's link count is an
    ordinary filesystem property, not evidence of anything, and refusing on
    it would misfire on perfectly normal directories.

    This is a heuristic on link count, not a proof of where the other links
    point, and it has a real limit: it only catches a hardlink that EXISTS
    at the moment of resolution. A hardlink created after this call returns
    is invisible to it, the same TOCTOU limit documented on
    `resolve_anchored` itself.

    I1: `stat()` also catches `ValueError` alongside `OSError`, defensively --
    `resolve_anchored` already refuses an embedded NUL byte in the stored
    path before this function ever runs, but that guard lives in the one
    caller this function currently has. `path.stat()` itself raises a bare
    `ValueError` (not an `OSError`) for a NUL byte in a path, so this
    function does not rely solely on a caller's upstream check to keep that
    exception from escaping as something other than `PathSafetyError`.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        raise PathSafetyError(
            f"path could not be inspected: {stored!r}: {exc}",
            reason="path_inspect_failed",
        ) from exc
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise PathSafetyError(
            f"path resolves to a hardlinked file: {stored!r}", reason="path_hardlinked"
        )


def validate_ledger(data: dict, *, source: str) -> list[str]:
    findings: list[str] = []
    missing = REQUIRED_LEDGER_FIELDS - set(data)
    unknown = set(data) - REQUIRED_LEDGER_FIELDS
    if missing:
        findings.append(f"{source}: missing fields: {sorted(missing)}")
    if unknown:
        findings.append(f"{source}: unknown fields: {sorted(unknown)}")
    if missing:
        return findings

    if data["schema_version"] != SCHEMA_VERSION:
        findings.append(
            f"{source}: unsupported schema_version: {data['schema_version']!r}"
        )
    if not isinstance(data["ledger_id"], str) or len(data["ledger_id"]) < 1:
        findings.append(f"{source}: ledger_id must be a non-empty string")
    if not isinstance(data["scope"], str) or data["scope"] not in LEDGER_SCOPES:
        findings.append(f"{source}: invalid scope: {data['scope']!r}")
    if not isinstance(data["language"], str) or len(data["language"]) < 2:
        findings.append(f"{source}: language must be a string of at least 2 characters")
    if not isinstance(data["client"], str) or len(data["client"]) < 1:
        findings.append(f"{source}: client must be a non-empty string")
    # adapter_version deliberately uses `type(x) is not int` rather than
    # isinstance: bool is a subclass of int, so isinstance(True, int) is
    # True, which would let a boolean silently pass as a valid count.
    if type(data["adapter_version"]) is not int or data["adapter_version"] < 1:
        findings.append(f"{source}: adapter_version must be an integer of at least 1")
    for field in ("created", "updated"):
        value = data[field]
        if not isinstance(value, str) or not DATE.fullmatch(value):
            findings.append(f"{source}: {field} must match YYYY-MM-DD")
    if type(data["id_authority"]) is not bool:
        findings.append(f"{source}: id_authority must be a boolean")
    if data["scope"] == "global" and data.get("id_authority") is False:
        findings.append(f"{source}: the global ledger must be the ID authority")
    if data["scope"] == "project" and data.get("id_authority") is True:
        findings.append(f"{source}: a project ledger must not be the ID authority")

    sequences = data["sequences"]
    if not isinstance(sequences, dict):
        findings.append(f"{source}: sequences must be an object")
    else:
        for prefix in SEQUENCE_PREFIXES:
            value = sequences.get(prefix)
            if type(value) is not int or value < 0:
                findings.append(
                    f"{source}: sequences.{prefix} must be an integer of at least 0"
                )
        unexpected = set(sequences) - set(SEQUENCE_PREFIXES)
        if unexpected:
            findings.append(
                f"{source}: sequences has unexpected keys: {sorted(unexpected)}"
            )

    # ARRAY_FIELDS is ("known_projects", "records", "baselines", "backlog"):
    # every one of the four has an explicit elif arm below, so there is no
    # fifth case left for a trailing `else` to ever handle.
    for field in ARRAY_FIELDS:
        if not isinstance(data[field], list):
            findings.append(f"{source}: {field} must be an array")
        elif field == "records":
            for index, record in enumerate(data[field]):
                findings.extend(validate_record(record, index, source=source))
        elif field == "backlog":
            for index, entry in enumerate(data[field]):
                findings.extend(validate_backlog_entry(entry, index, source=source))
        elif field == "known_projects":
            for index, entry in enumerate(data[field]):
                findings.extend(validate_known_project(entry, index, source=source))
        elif field == "baselines":
            for index, entry in enumerate(data[field]):
                findings.extend(validate_baseline(entry, index, source=source))

    return findings


def validate_run(record: dict, *, label: str) -> list[str]:
    findings: list[str] = []
    missing = REQUIRED_RUN_FIELDS - set(record)
    if missing:
        return [f"{label} is a RUN and is missing fields: {sorted(missing)}"]

    proposal = record["proposal"]
    if not isinstance(proposal, str) or not RECORD_ID.fullmatch(proposal):
        findings.append(f"{label} has an invalid proposal reference: {proposal!r}")

    authorization = record["authorization"]
    if not isinstance(authorization, dict):
        findings.append(f"{label} authorization must be an object")
    else:
        quote = authorization.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            findings.append(f"{label} authorization quote must be a non-empty string")
        recorded_on = authorization.get("recorded_on")
        if not isinstance(recorded_on, str) or not DATE.fullmatch(recorded_on):
            findings.append(f"{label} authorization.recorded_on must match YYYY-MM-DD")

    if not isinstance(record["result"], str) or record["result"] not in RUN_RESULTS:
        findings.append(f"{label} has an invalid result: {record['result']!r}")

    targets = record["targets"]
    if not isinstance(targets, list) or not targets:
        findings.append(f"{label} targets must be a non-empty array")
    else:
        for position, target in enumerate(targets):
            place = f"{label} targets[{position}]"
            if not isinstance(target, dict):
                findings.append(f"{place} must be an object")
                continue
            absent = REQUIRED_TARGET_FIELDS - set(target)
            if absent:
                findings.append(f"{place} missing fields: {sorted(absent)}")
                continue
            for field in ("before_digest", "after_digest"):
                value = target[field]
                if value is not None and (
                    not isinstance(value, str) or not DIGEST.fullmatch(value)
                ):
                    findings.append(f"{place} {field} must be a sha256 digest or null")
            if type(target["reversible"]) is not bool:
                findings.append(f"{place} reversible must be a boolean")
            elif not target["reversible"] and not target["residual_effect"]:
                findings.append(
                    f"{place} is not reversible and requires a residual_effect"
                )
            if "portable" in target and type(target["portable"]) is not bool:
                findings.append(f"{place} portable must be a boolean")

    backup = record["backup"]
    if backup is not None:
        if not isinstance(backup, dict):
            findings.append(f"{label} backup must be an object or null")
        else:
            digest = backup.get("digest")
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                findings.append(f"{label} backup digest must be a sha256 digest")
            if type(backup.get("verified")) is not bool:
                findings.append(f"{label} backup verified must be a boolean")

    rollback = record["rollback"]
    if not isinstance(rollback, dict):
        findings.append(f"{label} rollback must be an object")
    elif (
        not isinstance(rollback.get("tested"), str)
        or rollback.get("tested") not in ROLLBACK_TEST_STATES
    ):
        findings.append(
            f"{label} rollback tested must be one of {sorted(ROLLBACK_TEST_STATES)}"
        )

    reported = record["self_reported"]
    if not isinstance(reported, list) or any(
        not isinstance(item, str) for item in reported
    ):
        findings.append(f"{label} self_reported must be an array of strings")
    elif "targets" not in reported:
        # Every target's shape is checked; the array's coverage cannot be.
        # Nothing in a ledger says how many files a run was supposed to touch,
        # so a RUN can name three targets for a fourteen-file change and pass.
        # The record must say so in the field built for exactly that admission.
        findings.append(
            f"{label} self_reported must name 'targets': verify checks each "
            "target's shape and can never check that the array covers what the "
            "run changed"
        )

    return findings


def validate_record(record: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: records[{index}]"
    findings: list[str] = []
    if not isinstance(record, dict):
        return [f"{label} must be an object"]

    missing = REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    identifier = record["id"]
    if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
        findings.append(f"{label} has an invalid id: {identifier!r}")
    else:
        label = f"{source}: {identifier}"

    if not isinstance(record["type"], str) or record["type"] not in RECORD_TYPES:
        findings.append(f"{label} has an invalid type: {record['type']!r}")
    if not isinstance(record["status"], str) or record["status"] not in RECORD_STATUSES:
        findings.append(f"{label} has an invalid status: {record['status']!r}")
    if (
        not isinstance(record["classification"], str)
        or record["classification"] not in CLASSIFICATIONS
    ):
        findings.append(
            f"{label} has an invalid classification: {record['classification']!r}"
        )
    if not isinstance(record["scope"], str) or record["scope"] not in RECORD_SCOPES:
        findings.append(f"{label} has an invalid scope: {record['scope']!r}")
    for field in ("title", "file"):
        if not isinstance(record[field], str) or not record[field].strip():
            findings.append(f"{label} {field} must be a non-empty string")
    for field in ("created", "updated"):
        value = record[field]
        if not isinstance(value, str) or not DATE.fullmatch(value):
            findings.append(f"{label} {field} must match YYYY-MM-DD")

    links = record["links"]
    if not isinstance(links, dict):
        findings.append(f"{label} links must be an object")
    else:
        for field in LINK_FIELDS:
            targets = links.get(field, [])
            if not isinstance(targets, list):
                findings.append(f"{label} links.{field} must be an array")
                continue
            for target in targets:
                if not isinstance(target, str) or not RECORD_ID.fullmatch(target):
                    findings.append(f"{label} links.{field} has an invalid id: {target!r}")

    evidence = record["evidence"]
    if not isinstance(evidence, list):
        findings.append(f"{label} evidence must be an array")
    else:
        for position, item in enumerate(evidence):
            if not isinstance(item, dict):
                findings.append(f"{label} evidence[{position}] must be an object")
                continue
            absent = EVIDENCE_FIELDS - set(item)
            if absent:
                findings.append(
                    f"{label} evidence[{position}] missing fields: {sorted(absent)}"
                )
                continue
            if type(item["time_sensitive"]) is not bool:
                findings.append(
                    f"{label} evidence[{position}] time_sensitive must be a boolean"
                )
            elif item["time_sensitive"]:
                expires_on = item.get("expires_on")
                if not isinstance(expires_on, str) or not expires_on.strip():
                    findings.append(
                        f"{label} evidence[{position}] is time_sensitive and requires expires_on"
                    )

    if "pending_id_reconciliation" in record and type(record["pending_id_reconciliation"]) is not bool:
        findings.append(f"{label} pending_id_reconciliation must be a boolean")

    if record["type"] == "RUN":
        findings.extend(validate_run(record, label=label))

    return findings


def validate_backlog_entry(entry: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: backlog[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be an object"]
    missing = REQUIRED_BACKLOG_FIELDS - set(entry)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    findings: list[str] = []
    identifier = entry["id"]
    if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
        findings.append(f"{label} has an invalid id: {identifier!r}")
    else:
        label = f"{source}: backlog {identifier}"

    classification = entry["classification"]
    if not isinstance(classification, str):
        findings.append(f"{label} has an invalid classification: {classification!r}")
    elif classification in TERMINAL_CLASSIFICATIONS:
        findings.append(
            f"{label} uses the terminal classification {classification!r}, "
            "which never enters the backlog"
        )
    elif classification not in BACKLOG_CLASSIFICATIONS:
        findings.append(f"{label} has an invalid classification: {classification!r}")

    if not isinstance(entry["reason"], str) or not entry["reason"].strip():
        findings.append(f"{label} reason must be a non-empty string")

    # revisit_trigger mirrors the schema's `"type": ["string", "null"]`:
    # any other type (int, list, dict, ...) is a finding, independent of
    # the "at least one of trigger/date" rule below.
    revisit_trigger = entry["revisit_trigger"]
    if revisit_trigger is not None and not isinstance(revisit_trigger, str):
        findings.append(f"{label} revisit_trigger must be null or a string")

    # revisit_after is a date field like every other date in this ledger
    # (created, updated, verified_on, recorded_on): when present it must
    # match YYYY-MM-DD. Unlike those fields it is nullable — null means
    # "no date condition", which is legitimate as long as revisit_trigger
    # supplies the revisit condition instead.
    revisit_after = entry["revisit_after"]
    if revisit_after is not None and (
        not isinstance(revisit_after, str) or not DATE.fullmatch(revisit_after)
    ):
        findings.append(f"{label} revisit_after must be null or match YYYY-MM-DD")

    if not entry["revisit_trigger"] and not entry["revisit_after"]:
        findings.append(f"{label} requires a revisit_trigger or a revisit_after date")

    return findings


def validate_known_project(entry: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: known_projects[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be an object"]
    missing = REQUIRED_PROJECT_FIELDS - set(entry)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    findings: list[str] = []
    for field in ("project_root", "ledger_path"):
        if not isinstance(entry[field], str) or not entry[field].strip():
            findings.append(f"{label} {field} must be a non-empty string")

    # last_seen is a date field like created/updated/verified_on/recorded_on
    # elsewhere in this ledger, and unlike revisit_after it is not nullable.
    last_seen = entry["last_seen"]
    if not isinstance(last_seen, str) or not DATE.fullmatch(last_seen):
        findings.append(f"{label} last_seen must match YYYY-MM-DD")

    digest = entry["last_digest"]
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        findings.append(f"{label} last_digest must be a sha256 digest")
    if not isinstance(entry["status"], str) or entry["status"] not in PROJECT_STATUSES:
        findings.append(f"{label} has an invalid status: {entry['status']!r}")
    return findings


def validate_baseline(entry: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: baselines[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be an object"]
    missing = REQUIRED_BASELINE_FIELDS - set(entry)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    findings: list[str] = []
    identifier = entry["id"]
    if (
        not isinstance(identifier, str)
        or not RECORD_ID.fullmatch(identifier)
        or _prefix_and_number(identifier)[0] != "BASE"
    ):
        findings.append(f"{label} has an invalid id: {identifier!r}")
    else:
        label = f"{source}: {identifier}"

    captured_on = entry["captured_on"]
    if not isinstance(captured_on, str) or not DATE.fullmatch(captured_on):
        findings.append(f"{label} captured_on must match YYYY-MM-DD")

    if not isinstance(entry["client"], str) or not entry["client"].strip():
        findings.append(f"{label} client must be a non-empty string")

    if type(entry["adapter_version"]) is not int or entry["adapter_version"] < 1:
        findings.append(f"{label} adapter_version must be an integer of at least 1")

    items = entry["items"]
    if not isinstance(items, list):
        findings.append(f"{label} items must be an array")
    else:
        for position, item in enumerate(items):
            place = f"{label} items[{position}]"
            if not isinstance(item, dict):
                findings.append(f"{place} must be an object")
                continue
            absent = REQUIRED_BASELINE_ITEM_FIELDS - set(item)
            if absent:
                findings.append(f"{place} missing fields: {sorted(absent)}")
                continue

            if not isinstance(item["kind"], str) or item["kind"] not in BASELINE_ITEM_KINDS:
                findings.append(f"{place} has an invalid kind: {item['kind']!r}")
            if not isinstance(item["name"], str) or not item["name"].strip():
                findings.append(f"{place} name must be a non-empty string")
            if not isinstance(item["anchor"], str) or not item["anchor"].strip():
                findings.append(f"{place} anchor must be a non-empty string")

            digest = item["digest"]
            if digest is not None and (
                not isinstance(digest, str) or not DIGEST.fullmatch(digest)
            ):
                findings.append(f"{place} digest must be a sha256 digest or null")

            if not isinstance(item["attributes"], dict):
                findings.append(f"{place} attributes must be an object")

            origin = item["origin"]
            if not (
                origin == "pre-existing"
                or (
                    isinstance(origin, str)
                    and RECORD_ID.fullmatch(origin)
                    and _prefix_and_number(origin)[0] == "PROP"
                )
            ):
                findings.append(f"{place} has an invalid origin: {origin!r}")

            if not isinstance(item["state"], str) or item["state"] not in BASELINE_ITEM_STATES:
                findings.append(f"{place} has an invalid state: {item['state']!r}")

            if "portable" in item and type(item["portable"]) is not bool:
                findings.append(f"{place} portable must be a boolean")

    return findings


def _prefix_and_number(identifier: str) -> tuple[str, int]:
    # identifier is RECORD_ID-valid and has already passed RECORD_ID.fullmatch(),
    # e.g., "PROP-2026-001" or "PROP-2026-001-P"
    parts = identifier.split("-")
    prefix = parts[0]
    number = int(parts[2])  # Skip year (parts[1]), use number (parts[2])
    return prefix, number


def validate_collection(
    documents: list[tuple[str, dict]],
    *,
    complete: bool = True,
    digests: dict[str, str] | None = None,
) -> list[str]:
    # complete=False skips link checks to avoid false dangling-link findings.
    findings: list[str] = []
    seen: dict[str, str] = {}
    declared: set[str] = set()
    authorities: list[str] = []
    all_records: list[tuple[str, dict]] = []
    # Highest number seen per prefix across the whole verified set, with the
    # identifier and the ledger that holds it, so the authority check below can
    # name where the id was actually spent.
    spent: dict[str, tuple[int, str, str]] = {}
    for source, data in documents:
        if isinstance(data, dict) and data.get("id_authority") is True:
            authorities.append(source)
        records = data.get("records") if isinstance(data, dict) else None
        # Maps prefix -> (highest number seen, identifier that set it), so
        # the sequence-drift finding below can name the record that
        # actually holds the high-water mark instead of whichever record
        # happened to be last in the `for record in records` loop.
        highest: dict[str, tuple[int, str]] = {}
        records = records if isinstance(records, list) else []
        for record in records:
            if not isinstance(record, dict):
                continue
            all_records.append((source, record))
            identifier = record.get("id")
            if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                continue
            if identifier in seen:
                findings.append(
                    f"Duplicate record id {identifier} in {source} and {seen[identifier]}"
                )
            else:
                seen[identifier] = source
            declared.add(identifier)
            reconciled = record.get("pending_id_reconciliation") is True
            if PROVISIONAL_ID.search(identifier) and not reconciled:
                findings.append(
                    f"{source}: {identifier} is provisional and requires "
                    "pending_id_reconciliation to be true"
                )
            prefix, number = _prefix_and_number(identifier)
            current = highest.get(prefix)
            if current is None or number > current[0]:
                highest[prefix] = (number, identifier)
            current_spent = spent.get(prefix)
            if current_spent is None or number > current_spent[0]:
                spent[prefix] = (number, identifier, source)

        # A baseline is just another identifier holder: its `id` competes for
        # the same BASE sequence slot a record's id would, so it feeds the
        # same per-document floor and authority-wide coverage below.
        baselines = data.get("baselines") if isinstance(data, dict) else None
        baselines = baselines if isinstance(baselines, list) else []
        for baseline in baselines:
            if not isinstance(baseline, dict):
                continue
            identifier = baseline.get("id")
            if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                continue
            prefix, number = _prefix_and_number(identifier)
            current = highest.get(prefix)
            if current is None or number > current[0]:
                highest[prefix] = (number, identifier)
            current_spent = spent.get(prefix)
            if current_spent is None or number > current_spent[0]:
                spent[prefix] = (number, identifier, source)

        sequences = data.get("sequences") if isinstance(data, dict) else None
        if isinstance(sequences, dict):
            for prefix, (number, highest_identifier) in highest.items():
                allocated = sequences.get(prefix)
                if type(allocated) is int and allocated < number + 1:
                    findings.append(
                        f"{source}: sequences.{prefix} is {allocated} but "
                        f"{highest_identifier} is already allocated"
                    )

    # The global ledger is the sole ID authority, and normally holds no records
    # of its own: every project-scoped record routes to a project ledger. So the
    # per-document rule above never relates the authority's allocation counter to
    # the ids it actually issued. Fold in the whole set.
    for source, data in documents:
        if not isinstance(data, dict) or data.get("id_authority") is not True:
            continue
        sequences = data.get("sequences")
        if not isinstance(sequences, dict):
            continue
        for prefix, (number, identifier, holder) in spent.items():
            if holder == source:
                continue  # the per-document rule already covers this one
            allocated = sequences.get(prefix)
            if type(allocated) is int and allocated < number + 1:
                findings.append(
                    f"{source}: sequences.{prefix} is {allocated} but the ID "
                    f"authority must cover {identifier}, allocated in {holder}"
                )

    if complete:
        for source, record in all_records:
            links = record.get("links")
            if not isinstance(links, dict):
                continue
            for field in LINK_FIELDS:
                targets = links.get(field)
                if not isinstance(targets, list):
                    continue
                for target in targets:
                    if isinstance(target, str) and target not in declared:
                        findings.append(
                            f"{source}: {record.get('id')!r} links to an "
                            f"unknown record: {target!r}"
                        )

        # A backlog entry's id is a back-reference to the record whose evidence
        # produced the finding, not a unique key: one material routinely yields
        # several backlog entries, so duplicates are correct here. What is
        # checkable is that the record exists. Suppressed with the link checks
        # when the set is partial, for the same reason: the record may live in
        # the ledger that could not be read.
        for source, data in documents:
            backlog = data.get("backlog") if isinstance(data, dict) else None
            if not isinstance(backlog, list):
                continue
            for index, entry in enumerate(backlog):
                if not isinstance(entry, dict):
                    continue
                identifier = entry.get("id")
                if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                    continue  # validate_backlog_entry already reported the shape
                if identifier not in declared:
                    findings.append(
                        f"{source}: backlog[{index}] id {identifier!r} references "
                        "a record that exists in no verified ledger"
                    )

    if digests:
        for source, data in documents:
            projects = data.get("known_projects") if isinstance(data, dict) else None
            if not isinstance(projects, list):
                continue
            for index, entry in enumerate(projects):
                if not isinstance(entry, dict):
                    continue
                ledger_path = entry.get("ledger_path")
                recorded = entry.get("last_digest")
                if not isinstance(ledger_path, str) or not isinstance(recorded, str):
                    continue
                # A path that was not passed on the command line is not
                # comparable. Silence here means "not checked", never "correct".
                actual = digests.get(_path_key(ledger_path))
                if actual is None or actual == recorded:
                    continue
                findings.append(
                    f"{source}: known_projects[{index}] last_digest {recorded!r} "
                    f"does not match {ledger_path!r}, which hashes to {actual!r}"
                )

    if len(authorities) > 1:
        findings.append(
            f"More than one ledger claims ID authority: {sorted(authorities)}"
        )

    return findings


def verify(paths: list[Path]) -> int:
    findings: list[str] = []
    documents: list[tuple[str, dict]] = []
    errors: list[str] = []
    digests: dict[str, str] = {}

    for path in paths:
        source = str(path)
        try:
            # load_json and file_digest each open the file independently, so
            # in principle the digest could describe different bytes than
            # the parsed document if the file changes between the two reads.
            # Accepted: a local validator run by the ledger's owner over
            # their own files has no privilege boundary to defend, and the
            # realistic outcome of that microsecond window is a spurious
            # finding that a re-run clears.
            data = load_json(path)
            digest = file_digest(path)
        except LedgerError as exc:
            errors.append(str(exc))
            continue
        except OSError as exc:
            errors.append(f"Unreadable ledger: {path}: {exc}")
            continue
        # Register both the path as given and its resolved form, so a ledger
        # that stores an absolute path still matches a relative invocation.
        digests[_path_key(source)] = digest
        digests[_path_key(str(path.resolve()))] = digest
        findings.extend(validate_ledger(data, source=source))
        documents.append((source, data))

    findings.extend(
        validate_collection(documents, complete=not errors, digests=digests)
    )
    for line in (*findings, *errors):
        print(line, file=sys.stderr)

    if errors:
        return 2
    if findings:
        print(f"{len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"{len(paths)} ledger(s) validated")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="validate one or more ledgers")
    verify_parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args(argv)

    if arguments.command == "verify":
        return verify(arguments.paths)


if __name__ == "__main__":
    sys.exit(main())
