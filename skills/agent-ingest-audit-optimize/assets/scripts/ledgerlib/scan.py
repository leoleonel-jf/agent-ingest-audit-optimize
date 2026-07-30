"""Reading a client's configuration into baseline items, keeping no secrets.

`scan` is the read-only half of the ledger tools. Given an adapter's resolved
anchor roots it probes the files the adapter names, digests them, parses the
two formats the adapters use, and emits baseline items. It writes nothing --
no file, no directory -- and it never executes anything a configuration file
names; a key whose value is a shell command is recorded as a name like any
other value. Spec `docs/specs/2026-07-30-adapters-and-scan.md` section 3
owns the behaviour; design spec section 9 owns the rules below.

Redaction is deliberately the first thing this module grew, before any
probing or parsing existed, so that no function here can ever read a value
into an item before there is somewhere safe to put it. Design spec section 9
requires that a sensitive value never enters an item's attributes -- not even
briefly -- so redaction happens at the point a document is read, not on the
way out.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path

from ledgerlib.constants import ANCHOR_REFERENCE
from ledgerlib.errors import PathSafetyError
from ledgerlib.paths import anchor_path, file_digest, resolve_anchored


# The reasons `scan` itself puts in `attributes.reason`, as opposed to the
# `PathSafetyError.reason` keys `errors.PATH_SAFETY_REASONS` owns. The two
# sets share one attribute because they answer one question -- why this item
# is not a plain digested file -- and a caller that wants to know whether the
# path layer refused the path can test membership in `PATH_SAFETY_REASONS`.
SCAN_REASONS = frozenset(
    {
        "malformed_probe",
        "unresolved_anchor",
        "glob_failed",
        "no_match",
        "missing",
        "inaccessible",
        "directory",
        "unreadable",
    }
)


def _value_digest(value: object) -> str:
    """Digest a value over its canonical JSON encoding.

    Spec section 3.5: `sort_keys=True`, `separators=(",", ":")`, UTF-8. Two
    equal values therefore digest identically regardless of the key order the
    file happened to use, and two different values digest differently. That
    is the whole contract the digest owes `drift`, which uses it to tell "the
    token changed" from "the token is gone" without ever having held either.

    Nothing here can raise. A value the canonical encoder cannot handle is
    still a value that must be replaced by a marker, and raising would abort a
    scan over a file that is otherwise perfectly readable -- `tomllib` yields
    `datetime.datetime`, `datetime.date`, and `datetime.time` objects, and
    `json.dumps` refuses all three. Such a value is encoded through `repr`
    instead (`default=repr`, which reaches non-serialisable leaves nested
    inside an otherwise-encodable container), and if the encoder still fails
    -- a circular reference raises `ValueError`, a pathologically deep one
    `RecursionError` -- the whole value's `repr` is hashed instead.

    The fallback is weaker than the canonical encoding: two distinct objects
    sharing a `repr` collide. It is not weaker in the way that matters, since
    a digest is a change detector and never a value that can be read back.
    """
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=repr
        )
    except (TypeError, ValueError, RecursionError):
        encoded = repr(value)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_sensitive(key: object, patterns: Sequence[str]) -> bool:
    """Whether a key name matches any sensitive-key pattern.

    `fnmatchcase` against both sides lowered, rather than `fnmatch`, because
    `fnmatch` normalizes case through `os.path.normcase` -- which lowercases
    on Windows and does nothing on POSIX. That would make `API_TOKEN` match
    `*token*` on one platform and not the other, and a redaction rule that
    depends on the operating system is not a redaction rule.

    A non-string key cannot match: JSON and TOML both guarantee string keys,
    so this only arises for a caller passing a hand-built mapping, and
    inventing a string form for such a key would invent a match rule nothing
    documents. Recursion still descends into its value.
    """
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(
        isinstance(pattern, str) and fnmatch.fnmatchcase(lowered, pattern.lower())
        for pattern in patterns
    )


def redact(value: object, patterns: Sequence[str]) -> object:
    """Copy `value`, replacing every sensitive key's value with a marker.

    Design spec section 9: a value under a `sensitive_key_patterns` match is
    never copied -- the key name and a digest of the value are stored -- and
    the rule applies recursively into nested objects, including objects inside
    arrays. A matched key's value becomes
    `{"redacted": True, "digest": "sha256:..."}` whatever its type: a number,
    an array, and an object are as capable of carrying a secret as a string,
    and a rule that only covered strings would leave `{"env": {...}}`
    untouched -- exactly the shape the research names as secret-bearing in
    both clients.

    Recursion stops at a match. Nothing beneath a redacted subtree is walked,
    because walking it would put those values in memory and one bug away from
    output; the subtree is digested whole and its interior never becomes keys
    of the result. This is why the pattern `env` alone is enough to protect an
    entire MCP `env` block without enumerating what is inside it.

    A structure with no match passes through unchanged by equality. Containers
    are always rebuilt, so the caller's document is never mutated; leaves are
    shared, since they are not modified.

    `patterns` is a parameter rather than a module constant: the patterns come
    from the adapter, which is data, and a second client's secret-bearing key
    names are not this module's business to know.
    """
    if isinstance(value, dict):
        result: dict = {}
        for key, item in value.items():
            if _is_sensitive(key, patterns):
                result[key] = {"redacted": True, "digest": _value_digest(item)}
            else:
                result[key] = redact(item, patterns)
        return result
    if isinstance(value, list):
        return [redact(item, patterns) for item in value]
    return value


def run_probe(
    probe: dict, roots: dict[str, Path], patterns: Sequence[str]
) -> list[dict]:
    """The baseline items one probe yields.

    Always at least one item, never an empty list, and never an exception for
    anything reachable from probe data or from the filesystem. Spec section
    3.4: a probe that matches nothing is recorded as exactly one item with
    `state: "not_present"` and a `null` digest -- never an error, never
    silence. A baseline that omits what it failed to find is a baseline that
    looks clean, which is the worst output this tool can produce.

    The security rule this function exists to enforce: **every** path, whether
    expanded from a glob or named literally, is re-checked with
    `resolve_anchored` on its anchored form before it is opened. `check_glob`
    ran at load time against the pattern and says nothing about what the
    filesystem holds now -- a symlinked or junctioned directory inside
    `$USER_CONFIG/skills/` can carry a match clean out of the anchor between
    the adapter being validated and this walk running. A refusal becomes one
    item with `state: "not_present"` and the `PathSafetyError` reason in
    `attributes`, and the scan continues: refusing to look at one path is not
    a reason to abandon the baseline.

    The stored form always comes from `anchor_path`, never from string
    concatenation. That function owns the longest-anchor rule -- a project
    nested inside a user configuration root anchors to `$PROJECT` -- and it
    resolves before matching, so a match that truly lands outside every anchor
    comes back absolute and `portable: false`. Feeding that absolute form to
    `resolve_anchored` is what turns the escape into a refusal: an anchored
    form that is not anchored is exactly the thing rule 3 rejects.

    Glob results are sorted by their anchored path. `Path.glob` yields
    whatever order the directory index hands back, which differs by filesystem
    and by insertion history; an unordered baseline diffs against itself.

    `patterns` is accepted and unused here on purpose. Parsing arrives in the
    next task and is where redaction is wired in; a probe carrying `parse` or
    `pointer` yields the whole-file item for now.
    """
    spec, is_glob = _probe_target(probe)
    if spec is None:
        return [_item(probe, name=_probe_label(probe), anchor=_probe_label(probe),
                      state="not_present", reason="malformed_probe")]

    reference = ANCHOR_REFERENCE.match(spec.replace("\\", "/"))
    if reference is None:
        return [_item(probe, name=spec, anchor=spec, state="not_present",
                      reason="path_malformed_anchor_reference")]

    root = roots.get(reference.group(1))
    if root is None:
        # An unresolved anchor is not an error. `resolve_anchor_roots` returns
        # the names it could not resolve rather than guessing a vendor default,
        # and every probe beneath one is recorded absent rather than silently
        # skipped.
        return [_item(probe, name=spec, anchor=spec, state="not_present",
                      reason="unresolved_anchor")]

    if not is_glob:
        return [_probe_one(probe, spec, roots)]

    tail = reference.group(2) or ""
    try:
        matches = [root] if not tail else list(root.glob(tail))
    except (OSError, ValueError, IndexError, RecursionError) as exc:
        # `Path.glob` raises ValueError for a pattern it will not accept and
        # OSError for a tree it cannot walk. Neither is a reason to abandon
        # the whole scan, and neither may escape this function.
        del exc
        return [_item(probe, name=spec, anchor=spec, state="not_present",
                      reason="glob_failed")]

    items: list[dict] = []
    for match in matches:
        try:
            stored, portable = anchor_path(match, roots)
        except PathSafetyError as exc:
            items.append(_item(probe, name=_leaf(str(match)), anchor=str(match),
                               state="not_present", reason=exc.reason))
            continue
        items.append(_probe_one(probe, stored, roots, portable=portable))

    if not items:
        # The probe's own pattern is the name, so the baseline records *what*
        # was absent rather than merely that something was.
        return [_item(probe, name=spec, anchor=spec, state="not_present",
                      reason="no_match")]

    items.sort(key=lambda item: item["anchor"])
    return items


def _probe_one(
    probe: dict, stored: str, roots: dict[str, Path], *, portable: bool | None = None
) -> dict:
    """One item for one anchored path, re-checking it before opening it.

    `portable` is what `anchor_path` already reported for a glob match, kept
    only so a refusal can still record it: design spec 7.1 stores a path
    outside every anchor absolute and flagged `portable: false`, and that flag
    is the difference between "a path I refused" and "a path that was never
    anchored at all".
    """
    try:
        resolved = resolve_anchored(stored, roots)
        anchor, portable = anchor_path(resolved, roots)
    except PathSafetyError as exc:
        return _item(probe, name=_leaf(stored), anchor=stored,
                     state="not_present", reason=exc.reason, portable=portable)

    name = resolved.name or anchor
    try:
        info = os.stat(resolved)
    except (FileNotFoundError, NotADirectoryError):
        return _item(probe, name=name, anchor=anchor, state="not_present",
                     reason="missing", portable=portable)
    except (OSError, ValueError):
        return _item(probe, name=name, anchor=anchor, state="not_present",
                     reason="inaccessible", portable=portable)

    if stat.S_ISDIR(info.st_mode):
        # A directory is present and has no bytes to hash. Recording it with a
        # null digest and the reason is the honest answer; omitting it would
        # lose a skill directory that exists but holds no SKILL.md.
        return _item(probe, name=name, anchor=anchor, state="present",
                     reason="directory", portable=portable)

    try:
        digest = file_digest(resolved)
    except (OSError, ValueError, MemoryError):
        return _item(probe, name=name, anchor=anchor, state="present",
                     reason="unreadable", portable=portable)

    return _item(probe, name=name, anchor=anchor, state="present",
                 digest=digest, portable=portable)


def _probe_target(probe: object) -> tuple[str | None, bool]:
    """The probe's `glob` or `path`, and which of the two it was.

    A probe with neither, with both, or with a non-string value is malformed:
    `validate_adapter` refuses all three at load time, so reaching here means
    a caller built a probe by hand. It still yields an item rather than an
    exception -- this function's contract is that nothing reachable from probe
    data raises.
    """
    if not isinstance(probe, dict):
        return None, False
    for field, is_glob in (("glob", True), ("path", False)):
        if field in probe:
            value = probe[field]
            if isinstance(value, str) and value.strip():
                return value, is_glob
            return None, is_glob
    return None, False


def _probe_label(probe: object) -> str:
    """A non-empty name for a probe whose target is unusable.

    `name` is required to be a non-empty string, so a malformed probe still
    needs one. The kind is the only field left worth naming; `"probe"` is the
    floor.
    """
    if isinstance(probe, dict):
        kind = probe.get("kind")
        if isinstance(kind, str) and kind.strip():
            return f"probe:{kind}"
    return "probe"


def _leaf(stored: str) -> str:
    """The last component of a stored path, falling back to the whole form."""
    tail = stored.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return tail or stored


def _item(
    probe: object,
    *,
    name: str,
    anchor: str,
    state: str,
    digest: str | None = None,
    reason: str | None = None,
    portable: bool | None = None,
) -> dict:
    """Assemble one baseline item.

    `origin` is `pre-existing` for every item `scan` produces. Design spec
    section 7.5 determines origin by matching against run targets, and that
    match needs a ledger, which `scan` does not read.

    `scope` is copied from the probe when it has one and computed from nothing:
    the research found precedence in both clients is per-subsystem, so any
    single "which layer wins" answer computed here would be wrong for half the
    kinds. `scan` records the layer and leaves the winner to `drift`.

    No file content ever reaches an item. The only thing derived from bytes is
    the digest.
    """
    attributes: dict = {}
    if isinstance(probe, dict):
        scope = probe.get("scope")
        if isinstance(scope, str) and scope.strip():
            attributes["scope"] = scope
    if reason is not None:
        attributes["reason"] = reason

    item = {
        "kind": probe.get("kind") if isinstance(probe, dict) else None,
        "name": name,
        "anchor": anchor,
        "digest": digest,
        "attributes": attributes,
        "origin": "pre-existing",
        "state": state,
    }
    if portable is not None:
        item["portable"] = portable
    return item
