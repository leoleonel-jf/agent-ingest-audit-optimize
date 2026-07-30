"""Reading, hashing, anchoring, and safely resolving ledger paths."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from ledgerlib.constants import (
    ANCHOR_NAME,
    ANCHOR_REFERENCE,
    DEVICE_NAME,
)
from ledgerlib.errors import (
    LedgerError,
    PathSafetyError,
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

    I6: a symlink loop (`root/a` -> `root/b`, `root/b` -> `root/a`) makes
    `Path.resolve()` raise a bare `RuntimeError` -- "Symlink loop from
    '<path>'" -- not an `OSError`. Non-strict `resolve()` detects ELOOP
    itself, in Python, rather than letting the OS's ELOOP surface as an
    `OSError`, and it reports the loop it found via `RuntimeError`
    deliberately. That is invisible on Windows, which has no equivalent
    construct, but entirely plausible in a real client configuration
    directory `scan` (0.2.4) will walk, so it is caught here exactly like
    `OSError` and given the same `resolve_failed` reason: both describe the
    identical failure -- the filesystem call inside `resolve()` did not
    produce a usable path -- so a caller checking `reason` need not learn a
    second key for what is, from `resolve_anchored`'s contract, the same
    outcome.
    """
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
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

    I6: every filesystem-touching call this function makes -- resolving the
    anchor root, resolving each prefix while checking rule 5, resolving the
    final candidate, and inspecting it for a hardlink -- is routed through
    `_resolve_or_raise` or `_refuse_if_hardlinked`, both of which now also
    catch `RuntimeError`: a symlink loop (`root/a` -> `root/b`, `root/b` ->
    `root/a`) makes `Path.resolve()` raise `RuntimeError`, not `OSError`,
    POSIX-only and invisible on Windows. Without this, a loop reachable from
    a real client configuration directory would abort `scan` (0.2.4) mid-walk
    instead of producing one finding and continuing -- exactly the failure
    mode I1 and I5 already closed for a NUL byte and a trailing dot/space
    segment, respectively.
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

    I6: `RuntimeError` is caught here too, for the same defensive reason --
    `path` here has already been through `_resolve_or_raise` in this
    function's one current caller, so a symlink loop is normally refused
    there first and this function never sees one. `stat()` itself follows
    symlinks via a single OS syscall rather than pathlib's own Python-level
    loop detection, so it is not expected to raise `RuntimeError` for a loop
    the way `resolve()` does -- but this is not relied upon; the same
    conversion is applied here rather than assumed unreachable.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        return
    except (OSError, ValueError, RuntimeError) as exc:
        raise PathSafetyError(
            f"path could not be inspected: {stored!r}: {exc}",
            reason="path_inspect_failed",
        ) from exc
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise PathSafetyError(
            f"path resolves to a hardlinked file: {stored!r}", reason="path_hardlinked"
        )
