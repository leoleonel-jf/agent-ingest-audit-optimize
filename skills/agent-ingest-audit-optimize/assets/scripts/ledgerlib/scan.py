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

import datetime
import fnmatch
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from ledgerlib.adapters import (
    FALLBACK_SELECTION_REASONS,
    PARSE_FORMATS,
    USER_CONFIG_ANCHOR,
    resolve_anchor_roots,
    select_adapter_detail,
)
from ledgerlib.constants import ANCHOR_REFERENCE, DATE, RECORD_ID
from ledgerlib.errors import LedgerError, PathSafetyError
from ledgerlib.paths import anchor_path, file_digest, resolve_anchored

try:  # pragma: no cover - which branch runs is the interpreter's choice
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10, which this bundle supports
    # Bound to `None` rather than left undefined, and every use below branches
    # on the binding rather than on `sys.version_info`. A test can patch this
    # name; it cannot patch the interpreter it is running on, and a degradation
    # path only exercised on an interpreter nobody has is not exercised.
    tomllib = None  # type: ignore[assignment]


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
        "not_regular_file",
        "unreadable",
        "pointer_unresolved",
    }
)

# The values `attributes.parse_error` may take, following `SCAN_REASONS`:
# a closed set of stable strings, never the parser's own message. CPython
# rewrote every `json` decoder message in 3.13 and `tomllib`'s carry byte
# offsets, so a baseline holding one would diff against itself on the next
# interpreter -- reporting a change in a file nobody touched.
PARSE_ERRORS = frozenset({"malformed_json", "malformed_toml", "unreadable"})

_MALFORMED = {"json": "malformed_json", "toml": "malformed_toml"}

# The one identifier prefix a `baselines[]` entry may carry. `validate_baseline`
# enforces the same thing on the other side of the boundary; this module checks
# it before a single directory is walked, so a typo costs nothing.
BASELINE_PREFIX = "BASE"

# The bundle's own adapter directory: `assets/adapters/`, two levels up from
# `assets/scripts/ledgerlib/scan.py`. Derived from `__file__` rather than from
# the process's working directory, because `scan` is run from wherever the
# project being scanned happens to live.
BUNDLED_ADAPTERS = Path(__file__).resolve().parents[2] / "adapters"

# "no value was parsed" as distinct from "the parsed value was `null`". A
# configuration file may hold `null`, and the two must not collapse.
_ABSENT = object()


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
    expanded from a glob or named literally, is re-checked before it is opened,
    and the anchor it is checked against is **the one its own probe named**.
    `check_glob` ran at load time against the pattern and says nothing about
    what the filesystem holds now -- a symlinked or junctioned directory inside
    `$USER_CONFIG/skills/` can carry a match clean out of the anchor between
    the adapter being validated and this walk running. A refusal becomes one
    item with `state: "not_present"` and the `PathSafetyError` reason in
    `attributes`, and the scan continues: refusing to look at one path is not
    a reason to abandon the baseline.

    "Its own probe's anchor" is the whole of it, and asking the weaker question
    -- is this inside *some* anchor -- is a hole rather than a shortcut. An
    adapter declares several anchors and one of them is usually enormous:
    `claude-code.json` declares `$HOME: ["~"]`, so every path a user owns is
    inside an anchor. A junction at `$USER_CONFIG/skills/evil` pointing at
    `~/.ssh` lands a match that `anchor_path` will happily store as
    `$HOME/.ssh/...` with `portable: true`, and a check that only asked
    whether the anchored form re-resolves would accept it -- reading, digesting
    and recording a file the probe never named. `own_root` below is therefore
    passed down and re-checked in `_probe_one`: a match that lands under a
    *different* anchor has still escaped the one it was probed under.

    The stored form still comes from `anchor_path`, never from string
    concatenation, and it keeps the longest-anchor rule that function owns -- a
    project nested inside a user configuration root is recorded against
    `$PROJECT`, which is the more useful of the two true statements about where
    it lives. That is a question about *how to write the path down*, and it is
    deliberately not the question about *whether the path may be opened*: a
    second anchor may relabel a path, and may never launder one out of the
    first. A match that truly lands outside every anchor comes back absolute
    and `portable: false`; feeding that absolute form to `resolve_anchored` is
    what turns that escape into a refusal, since an anchored form that is not
    anchored is exactly the thing rule 3 rejects.

    Glob results are sorted by their anchored path. `Path.glob` yields
    whatever order the directory index hands back, which differs by filesystem
    and by insertion history; an unordered baseline diffs against itself.

    `patterns` is the adapter's `sensitive_key_patterns`, and it is used on the
    parsing path only: a probe without `parse` reads no value out of a file, so
    there is nothing for it to protect. With `parse`, every value that reaches
    an item passes through `redact` first.
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
        return _probe_one(probe, spec, roots, patterns, own_root=root)

    tail = reference.group(2) or ""
    try:
        matches = [root] if not tail else list(root.glob(tail))
    except (
        OSError,
        ValueError,
        IndexError,
        RecursionError,
        NotImplementedError,
    ) as exc:
        # `Path.glob` raises ValueError for a pattern it will not accept and
        # OSError for a tree it cannot walk. Neither is a reason to abandon
        # the whole scan, and neither may escape this function.
        #
        # `NotImplementedError` is named explicitly, and the tuple is NOT
        # widened to its base `RuntimeError`. `Path.glob` raises it -- "Non-
        # relative patterns are unsupported" -- for a tail that is not
        # relative, which `check_glob` cannot refuse: `$USER_CONFIG//Windows/
        # *.ini` has no `..` segment and is not itself absolute, yet its tail
        # `/Windows/*.ini` is, and so is `C:/...` on Windows. That is probe
        # data reaching a documented refusal, exactly like the `ValueError`
        # beside it, and a user `local.json` can carry it. Bare `RuntimeError`
        # is a different animal: CPython raises it for genuine defects -- a
        # container mutated during iteration, an interpreter invariant broken
        # -- and catching it here would convert a bug in this tool into a
        # `glob_failed` item saying the probe found nothing. Neither `pathlib`
        # nor `glob` raises a bare `RuntimeError` on this path (a symlink loop
        # reaches this module through `resolve_anchored`, which converts it to
        # `PathSafetyError`), so nothing is lost by leaving it uncaught, and a
        # traceback naming the real fault is the right answer if one appears.
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
        items.extend(
            _probe_one(
                probe, stored, roots, patterns, own_root=root, portable=portable
            )
        )

    if not items:
        # The probe's own pattern is the name, so the baseline records *what*
        # was absent rather than merely that something was.
        return [_item(probe, name=spec, anchor=spec, state="not_present",
                      reason="no_match")]

    items.sort(key=lambda item: item["anchor"])
    return items


def _probe_one(
    probe: dict,
    stored: str,
    roots: dict[str, Path],
    patterns: Sequence[str],
    *,
    own_root: Path | None = None,
    portable: bool | None = None,
) -> list[dict]:
    """The items for one anchored path, re-checking it before opening it.

    A list rather than a single item because a probe carrying `parse` turns one
    file into one item per key at the pointed-to location -- one `settings.json`
    into one `mcp-server` item per server. Without `parse` the list holds
    exactly one item and this function behaves as it always has.

    `own_root` is the resolved root of the anchor the **probe** named, and it
    is the containment test that actually matters. `resolve_anchored` answers
    "does this stored form stay inside the anchor the *stored form* names",
    which is the right question only when the two anchors are the same one.
    For a glob match the stored form was re-derived by `anchor_path` across
    every root, so a link out of `$USER_CONFIG` that lands under `$HOME` comes
    back as a perfectly well-formed `$HOME/...` that `resolve_anchored`
    accepts. Re-checking the resolved path against `own_root` is what makes a
    second anchor unable to launder a path out of the first. It is `None` only
    for a caller that has no probe anchor to offer, in which case the older,
    weaker check is all there is.

    `portable` is what `anchor_path` already reported for a glob match, kept
    only so a refusal can still record it: design spec 7.1 stores a path
    outside every anchor absolute and flagged `portable: false`, and that flag
    is the difference between "a path I refused" and "a path that was never
    anchored at all".
    """
    try:
        resolved = resolve_anchored(stored, roots)
        if own_root is not None and not _within(resolved, own_root):
            raise PathSafetyError(
                f"path resolves outside the anchor its probe named: {stored!r}",
                reason="path_resolves_outside_anchor",
            )
        anchor, portable = anchor_path(resolved, roots)
    except PathSafetyError as exc:
        return [_item(probe, name=_leaf(stored), anchor=stored,
                      state="not_present", reason=exc.reason, portable=portable)]

    name = resolved.name or anchor
    try:
        info = os.stat(resolved)
    except (FileNotFoundError, NotADirectoryError):
        return [_item(probe, name=name, anchor=anchor, state="not_present",
                      reason="missing", portable=portable)]
    except (OSError, ValueError):
        return [_item(probe, name=name, anchor=anchor, state="not_present",
                      reason="inaccessible", portable=portable)]

    if stat.S_ISDIR(info.st_mode):
        # A directory is present and has no bytes to hash. Recording it with a
        # null digest and the reason is the honest answer; omitting it would
        # lose a skill directory that exists but holds no SKILL.md.
        return [_item(probe, name=name, anchor=anchor, state="present",
                      reason="directory", portable=portable)]

    if not stat.S_ISREG(info.st_mode):
        # Everything that is neither a directory nor a regular file, recorded
        # the same way a directory is: present, no digest, and a reason. This
        # is not tidiness. `file_digest` reads the whole file, and `open()` on
        # a FIFO blocks until a writer appears -- which, for a scan nobody is
        # feeding, is forever. `claude-code.json` probes
        # `$USER_CONFIG/agents/*`, which matches any name, so a FIFO, socket,
        # or device node anywhere under a configuration directory is inside
        # the probe's own anchor and passes every path-safety rule; nothing
        # before this asked what *kind* of file it was. Only a regular file is
        # opened, and the item still says the thing exists.
        return [_item(probe, name=name, anchor=anchor, state="present",
                      reason="not_regular_file", portable=portable)]

    try:
        digest = file_digest(resolved)
    except (OSError, ValueError, MemoryError):
        return [_item(probe, name=name, anchor=anchor, state="present",
                      reason="unreadable", portable=portable)]

    fmt = _parse_format(probe)
    if fmt is None:
        return [_item(probe, name=name, anchor=anchor, state="present",
                      digest=digest, portable=portable)]

    return _parse_items(
        probe,
        path=resolved,
        fmt=fmt,
        name=name,
        anchor=anchor,
        digest=digest,
        portable=portable,
        patterns=patterns,
    )


def _within(path: Path, root: Path) -> bool:
    """Whether an already-resolved `path` lies inside an already-resolved root.

    Purely a comparison of components -- `relative_to` never touches the
    filesystem -- so it says nothing on its own about links. It is sound here
    because both sides arrive resolved: `root` from `resolve_anchor_roots` and
    `path` from `resolve_anchored`, which is where the link-following happened.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _parse_format(probe: object) -> str | None:
    """The probe's `parse`, or `None` when it names no format this can read.

    An unrecognised `parse` is treated as absent rather than as an error.
    `validate_adapter` refuses anything outside `PARSE_FORMATS` at load time,
    so reaching here means a hand-built probe, and the honest answer for a
    format nothing can read is the whole-file item -- which is still a true
    statement about the file.
    """
    if not isinstance(probe, dict):
        return None
    fmt = probe.get("parse")
    if isinstance(fmt, str) and fmt in PARSE_FORMATS:
        return fmt
    return None


def _parse_items(
    probe: dict,
    *,
    path: Path,
    fmt: str,
    name: str,
    anchor: str,
    digest: str,
    portable: bool | None,
    patterns: Sequence[str],
) -> list[dict]:
    """Read, parse, redact, and turn the pointed-to location into items.

    The order is the point. The document is redacted **immediately** after it
    is parsed and before anything else looks at it, so the value a pointer
    walks and the value an item stores are the redacted one -- there is no
    window in which an unredacted value is a candidate for an item. A pointer
    aimed inside a redacted subtree therefore finds a marker rather than the
    secret, which is the correct answer: the tool knows something is there and
    will not enumerate it.

    Every item keeps the digest of the **file's bytes**, not of its own value.
    A parsed item still has to answer "which file, and did that file change",
    and a per-value digest would answer neither.

    Nothing here raises. A file that cannot be read or cannot be parsed is
    still a file that exists, and the item says so with `parse_error`.
    """
    if fmt == "toml" and tomllib is None:
        # Design spec section 14. Not a crash, and not a pretence that the file
        # held nothing -- the digest is real and the item says why there are no
        # keys under it.
        return [_item(probe, name=name, anchor=anchor, state="present",
                      digest=digest, portable=portable, parse_unavailable=fmt)]

    try:
        data = path.read_bytes()
    except (OSError, MemoryError):
        return [_item(probe, name=name, anchor=anchor, state="present",
                      digest=digest, portable=portable, parse_error="unreadable")]

    try:
        if fmt == "toml":
            document: object = tomllib.loads(data.decode("utf-8"))
        else:
            document = json.loads(data)
    except (ValueError, RecursionError):
        # `json.JSONDecodeError`, `tomllib.TOMLDecodeError`, and
        # `UnicodeDecodeError` are all `ValueError`; a pathologically nested
        # document raises `RecursionError`. The exception is discarded rather
        # than recorded: its text is the one thing that must not reach the
        # item.
        return [_item(probe, name=name, anchor=anchor, state="present",
                      digest=digest, portable=portable,
                      parse_error=_MALFORMED[fmt])]

    document = redact(document, patterns)

    pointer = probe.get("pointer") if isinstance(probe, dict) else None
    if not isinstance(pointer, str) or not pointer:
        # Spec section 3.4: with no pointer there is no pointed-to location to
        # enumerate, and the file is one item carrying the whole document.
        return [_item(probe, name=name, anchor=anchor, state="present",
                      digest=digest, portable=portable,
                      value=_jsonable(document))]

    found, value = _resolve_pointer(document, pointer)
    if not found:
        # Not an error. An adapter pointing at a key a particular machine's
        # file does not have is the ordinary case -- a client with no MCP
        # servers configured has no `mcpServers` -- and the baseline has to
        # record that it looked.
        return [_item(probe, name=f"{name}{pointer}", anchor=anchor,
                      state="not_present", reason="pointer_unresolved",
                      portable=portable, pointer=pointer, parse_format=fmt)]

    if not isinstance(value, dict) or _is_marker(value):
        # No mapping means no keys to enumerate: an array, a scalar, or a
        # redacted subtree. One item carries the value as it stands.
        return [_item(probe, name=name, anchor=anchor, state="present",
                      digest=digest, portable=portable, value=_jsonable(value))]

    if not value:
        return [_item(probe, name=name, anchor=anchor, state="not_present",
                      reason="no_match", portable=portable, pointer=pointer,
                      parse_format=fmt)]

    # Sorted for the same reason glob matches are: a user reordering the keys
    # in their own `settings.json` must not reorder the baseline, or the next
    # diff reports a change nobody made.
    return [
        _item(
            probe,
            name=key if key.strip() else name,
            anchor=anchor,
            state="present",
            digest=digest,
            portable=portable,
            value=_jsonable(value[key]),
        )
        for key in sorted(value, key=str)
        if isinstance(key, str)
    ]


def _resolve_pointer(document: object, pointer: str) -> tuple[bool, object]:
    """Walk an RFC 6901 JSON pointer, reporting whether it resolved.

    A `(found, value)` pair rather than a sentinel, because `None` is a value a
    document can legitimately hold at the pointed-to location and a sentinel
    would make "the key is absent" and "the key is null" the same answer.

    The escapes are unescaped `~1` -> `/` first and `~0` -> `~` second, which
    is the order RFC 6901 section 3 requires and not an implementation detail:
    the other order turns the token `~01` into `~1` and then into `/`, silently
    resolving a different key than the one the adapter named.
    """
    node = document
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and not _is_marker(node):
            if key not in node:
                return False, None
            node = node[key]
        elif isinstance(node, list):
            # RFC 6901 section 4: an array index is a decimal number with no
            # leading zeros. `"-"` names the nonexistent element past the end
            # and never resolves for reading.
            if not key.isdigit() or (len(key) > 1 and key[0] == "0"):
                return False, None
            index = int(key)
            if index >= len(node):
                return False, None
            node = node[index]
        else:
            return False, None
    return True, node


def _is_marker(value: object) -> bool:
    """Whether a value is one of `redact`'s replacement markers.

    Checked so a pointer aimed into a redacted subtree is not enumerated into
    two items called `redacted` and `digest`, which would read as configuration
    the file does not contain.
    """
    return (
        isinstance(value, dict)
        and set(value) == {"redacted", "digest"}
        and value.get("redacted") is True
    )


def _jsonable(value: object) -> object:
    """A copy of `value` that `json.dumps` will accept.

    `tomllib` yields `datetime.datetime`, `datetime.date`, and `datetime.time`,
    and `json.dumps` refuses all three. The entry `scan` emits is JSON, so such
    a value reaching an item's attributes would not produce a bad baseline --
    it would produce no baseline at all, the command failing at the last step
    on a file it had already read successfully. Leaves that JSON cannot carry
    become their `repr`; every JSON-native leaf passes through untouched.

    Runs after `redact`, never instead of it. Markers are ordinary dicts of
    JSON-native leaves and pass through unchanged.
    """
    if isinstance(value, dict):
        return {
            key if isinstance(key, str) else repr(key): _jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return repr(value)


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
    value: object = _ABSENT,
    parse_error: str | None = None,
    parse_unavailable: str | None = None,
    pointer: str | None = None,
    parse_format: str | None = None,
) -> dict:
    """Assemble one baseline item.

    `origin` is `pre-existing` for every item `scan` produces. Design spec
    section 7.5 determines origin by matching against run targets, and that
    match needs a ledger, which `scan` does not read.

    `scope` is copied from the probe when it has one and computed from nothing:
    the research found precedence in both clients is per-subsystem, so any
    single "which layer wins" answer computed here would be wrong for half the
    kinds. `scan` records the layer and leaves the winner to `drift`.

    `value` is the only route by which file content reaches an item, it is
    reached only from `_parse_items`, and what arrives has already been through
    `redact`. It is defaulted to a sentinel rather than to `None` because
    `null` is a value a configuration file can legitimately hold, and an item
    whose parsed value is `null` must be distinguishable from an item that was
    never parsed at all.

    Outside that one attribute no file content reaches an item; the only other
    thing derived from bytes is the digest.
    """
    attributes: dict = {}
    if isinstance(probe, dict):
        scope = probe.get("scope")
        if isinstance(scope, str) and scope.strip():
            attributes["scope"] = scope
    if reason is not None:
        attributes["reason"] = reason
    if parse_error is not None:
        attributes["parse_error"] = parse_error
    if parse_unavailable is not None:
        attributes["parse_unavailable"] = parse_unavailable
    # A recorded absence of a pointed-to location is ambiguous without the
    # location: the file exists, so "did the absent thing appear" cannot be
    # answered from the file's existence alone. The pointer and its format
    # are recorded so `drift` can re-resolve the same location the same way,
    # instead of mistaking the always-present file for arriving configuration.
    if pointer is not None:
        attributes["pointer"] = pointer
    if parse_format is not None:
        attributes["parse"] = parse_format
    if value is not _ABSENT:
        attributes["value"] = value

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


def scan(
    *,
    identifier: str,
    client: str | None = None,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
    bundled: Path | None = None,
    environ: Mapping[str, str] | None = None,
    captured_on: str | None = None,
) -> tuple[dict, list[str], int]:
    """Assemble one `baselines[]` entry from one client's configuration.

    Returns `(entry, messages, exit_code)`.

    `messages` is everything the caller should put on stderr, in order: the
    adapter-selection notes first, then the findings. The two share one list
    because they share one stream -- an operator reading a scan needs to know
    *which* adapter ran before being told what it found -- but only the
    findings move `exit_code`, which is why a note does not turn an ordinary
    run into a failing one. `exit_code` is `0` clean and `1` with findings,
    matching `verify`; `2` is not returned here at all. A tool error is raised
    as `LedgerError`, the channel every other command in this bundle already
    uses, and `scan_command` is the one place that turns it into `2`.

    `captured_on` is a parameter rather than a read of the clock so that a
    test is not time-dependent and so that expiry is judged against the date
    the entry claims -- an entry stamped with one date and expiry-checked
    against another would be internally inconsistent the moment a scan crossed
    midnight.

    `environ` and `project` are parameters for the same reason
    `resolve_anchor_roots` takes them: nothing about which tree gets read may
    depend on process state a caller cannot see.

    Nothing here writes. The whole call graph beneath it -- `select_adapter_detail`,
    `resolve_anchor_roots`, `run_probe` -- opens files for reading and hashes
    them, and `ScanWritesNothingTests` holds that by patching every write API
    in `pathlib` and `builtins` to fail loudly.
    """
    identifier = _check_identifier(identifier)
    captured_on = _check_captured_on(captured_on)

    project = Path.cwd() if project is None else project
    environ = os.environ if environ is None else environ
    bundled = BUNDLED_ADAPTERS if bundled is None else bundled

    selection = select_adapter_detail(
        client=client,
        adapter=adapter,
        user_config=user_config,
        bundled=bundled,
        environ=environ,
        project=project,
    )
    document = selection["document"]
    notes = selection["notes"]

    roots, unresolved = resolve_anchor_roots(
        document, project=project, environ=environ
    )
    findings = _coverage_findings(
        document,
        unresolved=unresolved,
        captured_on=captured_on,
        selection=selection,
    )

    patterns = document["sensitive_key_patterns"]
    items: list[dict] = []
    for probe in document["probes"]:
        items.extend(run_probe(probe, roots, patterns))

    entry = {
        "id": identifier,
        "captured_on": captured_on,
        "client": document["client"],
        "adapter_version": document["adapter_version"],
        "items": items,
    }
    # Exactly the five fields design spec section 7.5 requires. The selection
    # notes are deliberately not among them: they describe how this scan was
    # configured, not what it found, and a note inside `items` would read as
    # configuration the machine does not have.
    return entry, [*notes, *findings], 1 if findings else 0


def _check_identifier(identifier: object) -> str:
    """Refuse anything that is not a well-formed `BASE` identifier.

    Allocation is a ledger concern -- `references/LEDGER.md` owns the rules
    about sequences, provisional suffixes, and cross-scope collision -- so
    `scan` takes the identifier it is given and checks only that it is one a
    ledger could hold. This runs before the adapter is opened: a typo must not
    cost a directory walk over somebody's configuration.
    """
    if (
        not isinstance(identifier, str)
        or not RECORD_ID.fullmatch(identifier)
        or identifier.split("-")[0] != BASELINE_PREFIX
    ):
        raise LedgerError(
            f"invalid --id {identifier!r}: a baseline identifier must match "
            f"{RECORD_ID.pattern} with the prefix {BASELINE_PREFIX}, for "
            f"example {BASELINE_PREFIX}-2026-001. Take the next free number "
            "from the ID authority's sequences; scan does not allocate one."
        )
    return identifier


def _check_captured_on(captured_on: object) -> str:
    """Today, or the injected date, refusing anything that is not a date.

    A malformed date would produce an entry that fails `validate_baseline` at
    the far end of a pipe, long after the scan that could have said so.
    """
    if captured_on is None:
        return datetime.date.today().isoformat()
    if not isinstance(captured_on, str) or not DATE.fullmatch(captured_on):
        raise LedgerError(f"invalid captured_on {captured_on!r}: must be YYYY-MM-DD")
    return captured_on


def _coverage_findings(
    document: dict,
    *,
    unresolved: Sequence[str],
    captured_on: str,
    selection: Mapping[str, object],
) -> list[str]:
    """The four ways a baseline can look clean, or safe, without being either.

    All are findings and none is an error: the scan runs, the entry is
    emitted, and the exit code says the output is not to be trusted as a
    complete picture. Refusing outright would leave the operator with no
    baseline at all, which is worse than a baseline that says what it missed.

    The first is expiry. `docs/specs/2026-07-30-adapters-and-scan.md` section
    3.3: vendor paths are time-sensitive, so each adapter carries the research
    document's expiry, and an adapter run past it may be naming files the
    client no longer reads.

    The second -- an unresolved `$USER_CONFIG` -- the spec does not name. It is
    recorded on the same grounds: every probe beneath it is `not_present`
    whether the client is genuinely absent or the tool merely looked in the
    wrong tree, and those two must not come out of the command looking
    identical.

    The third is a fallback to `generic`, which probes nothing. Spec section
    3.4 treats that as a selection outcome; the first real run
    (`docs/validation/scan-dogfood-0.2.5.md` finding 1) showed it is a coverage
    failure, because a machine with two supported clients installed answered
    the default invocation with `"items": []` and exit `0`.

    The fourth is the odd one out: it is about safety rather than coverage, and
    it is here because it has the same shape -- a run that looks fine and is
    not. An adapter whose `sensitive_key_patterns` is empty makes `redact` the
    identity function, so if any of its probes carries `parse`, every value
    read out of those documents is copied into the baseline exactly as written.
    A user `local.json` overriding a bundled adapter by client name is enough
    to arrange that, and before this the run printed nothing and exited `0`
    while dumping the parsed file verbatim. It is deliberately conditional on a
    `parse` probe existing: an adapter that parses nothing reads no values at
    all, so empty patterns are the correct configuration for it -- which is
    what `generic.json` ships, and it must stay clean.
    """
    client = document["client"]
    findings: list[str] = []

    reason = selection.get("reason")
    if reason in FALLBACK_SELECTION_REASONS:
        candidates = selection.get("candidates") or []
        findings.append(
            f"no client was detected and this scan fell back to the {client!r} "
            f"adapter, which probes nothing: $USER_CONFIG was weighed for "
            f"{sorted(candidates)} and produced no single answer, so this "
            "baseline is empty because nothing was looked at, not because the "
            "machine is clean. Name the client explicitly with --client to "
            "scan it."
        )

    expires_on = document["expires_on"]
    # Both are `YYYY-MM-DD` -- `validate_adapter` and `_check_captured_on`
    # each guarantee their side -- and that form sorts lexicographically in
    # date order, so no parsing is needed to compare them.
    if captured_on > expires_on:
        findings.append(
            f"adapter for client {client!r} expired on {expires_on!r} and this "
            f"scan ran on {captured_on!r}: its paths were verified against the "
            "vendor's documentation before that date and may no longer name "
            "the files the client reads, so this baseline may look clean "
            "because it looked in the wrong place"
        )

    # Only `$USER_CONFIG`, and this narrowness is the point -- do not widen it
    # back to `if unresolved`. Every unresolved anchor is still recorded on
    # each probe beneath it as `reason: "unresolved_anchor"`, which is the
    # honest record and is not being taken away here; what is narrowed is which
    # of them moves the exit code.
    #
    # `$USER_CONFIG` is the one anchor the design spec makes universal and the
    # one detection keys on. If it does not resolve, every probe comes back
    # `not_present` and the baseline is about nothing while looking clean --
    # the failure this whole function exists for.
    #
    # Any other anchor may be legitimately absent on a platform, and a finding
    # for that is permanent and unfixable: `codex.json` declares
    # `$SYSTEM_CONFIG` as `/etc/codex`, so before this narrowing
    # `--client codex` exited 1 on every Windows host on every run, forever
    # (`docs/validation/scan-dogfood-0.2.5.md` finding 9). A finding an
    # operator can never clear teaches them to ignore the exit code, which
    # costs every other finding its meaning.
    if USER_CONFIG_ANCHOR in unresolved:
        findings.append(
            f"adapter for client {client!r} has an unresolved anchor "
            f"${USER_CONFIG_ANCHOR}: no candidate root for it exists on this "
            "machine, so every probe beneath it is recorded not_present rather "
            "than looked at, and this baseline covers nothing under it"
        )

    parsing = sum(
        1
        for probe in document["probes"]
        if isinstance(probe, dict) and _parse_format(probe) is not None
    )
    if parsing and not document["sensitive_key_patterns"]:
        findings.append(
            f"adapter for client {client!r} has {parsing} probe(s) with parse "
            "but an empty sensitive_key_patterns: redaction matches key names, "
            "so an empty list redacts nothing and every value read out of "
            "those documents is copied into this baseline exactly as the file "
            "wrote it -- API tokens and MCP env blocks included. Add the key "
            "names that carry secrets for this client, for example "
            '["*token*", "*key*", "*secret*", "*password*", "*credential*", '
            '"*auth*", "env", "headers"], or drop parse from those probes to '
            "record the files by digest alone"
        )

    return findings


def scan_command(
    *,
    identifier: str,
    client: str | None = None,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
) -> int:
    """`scan` as a command: entry to stdout, everything else to stderr.

    The split of streams is the contract. A caller pipes stdout straight into
    a JSON reader, so not one byte that is not the entry may go there --
    notes, findings, and tool errors all go to stderr, and a scan that found
    nothing writes exactly the same shape as one that found everything.

    Exit codes match `verify`: `0` clean, `1` findings, `2` tool error.
    `sys.stdout` and `sys.stderr` are looked up at call time rather than bound
    as defaults, so a caller redirecting either -- as the tests do -- gets
    what it redirected.
    """
    try:
        entry, messages, code = scan(
            identifier=identifier,
            client=client,
            adapter=adapter,
            user_config=user_config,
            project=project,
        )
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2

    for message in messages:
        print(message, file=sys.stderr)
    print(json.dumps(entry, indent=2))
    return code
