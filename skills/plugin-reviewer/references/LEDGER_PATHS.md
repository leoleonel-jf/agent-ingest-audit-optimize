# Ledger: path anchors and path safety

How a recorded path is anchored, and what the commands refuse to read. Part of the ledger
reference; [LEDGER.md](LEDGER.md) holds the index.

## Path anchors

The design spec names three anchors: `$USER_CONFIG` is the client's user-level configuration root,
`$PROJECT` is the project root of the ledger that owns the record, and `$PLUGIN` is the installed
bundle root. `anchor_path` supplies the roots the caller has in hand; the path layer decides none
of them itself. An adapter may declare anchors beyond these three — the shipped ones do, and
The adapter format ([LEDGER_BASELINES.md](LEDGER_BASELINES.md)) says which and why.

A path that falls under an anchor is stored anchored, never absolute: the stored form is
`$NAME/rest` for a path under the root, or bare `$NAME` when the path names the root itself.

When more than one anchor contains a path, the longest anchor wins. A project nested inside a
user configuration root — for example a project rooted at `$USER_CONFIG/projects/widget`, where
`$PROJECT` is also rooted there — anchors to `$PROJECT`, not `$USER_CONFIG`: the more specific
anchor is the only choice that keeps both anchors meaningful.

A path that lies outside every anchor is stored absolute and marked `portable: false`. This is the
one case an anchored path does not take the `$NAME/...` form.

## Path safety

`resolve_anchored` turns a stored anchored path back into an absolute one, refusing with a
distinct, named reason whenever:

1. **unknown anchor** — the stored path names an anchor that was not supplied;
2. **`..` segment** — the path contains a `..` segment. This check is textual and runs before any
   normalization, so `$PROJECT/a/../b` is refused even though it normalizes back inside the root —
   the form is the problem, not just the destination;
3. **absolute path** — the path is absolute where an anchored form was required;
4. **resolves outside the anchor** — the final resolved path lies outside the anchor's root;
5. **symlink crosses the anchor boundary** — any component of the path is a symlink (or a
   platform-equivalent redirection, such as a Windows junction) whose target lies outside the
   anchor's root, even when the path's final resolution lands back inside the anchor afterward.
   Rule 5 is deliberately stricter than rule 4: a link that leaves the anchor is one an attacker
   can re-point later, so it is refused on that basis alone, independent of where it happens to
   lead today.

Nine further refusals close the gap between this list and what the code actually enforces — added
during a security review but never previously brought into this document:

6. **invalid anchor name** — the `roots` mapping itself contains a key that is not a valid
   `[A-Z_]+` identifier. Checked before any path is resolved: a malformed key could otherwise
   produce a stored form this function can never parse back, or let a key containing `/` steal a
   prefix of another key's namespace;
7. **empty path** — the stored value is missing or is not a non-empty string;
8. **embedded NUL byte** — the stored path contains a NUL byte, refused before anything touches
   the filesystem. Without this check the NUL survives every other textual check (it is not a
   `..` segment, not absolute, not an unknown anchor) and would otherwise reach the hardlink
   check's `stat()` call, which raises a bare `ValueError` rather than an `OSError` — the same
   NUL-byte guard `check_glob` applies to a probe pattern, see Adapter glob safety below;
9. **malformed anchor reference** — the path does not parse as `$NAME/...` at all, and was not
   already refused as absolute;
10. **reserved device name** — a path component is a Windows-reserved device name (`CON`, `PRN`,
    `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, with or without an extension), refused on every
    platform because a ledger written on Windows may be validated on Linux, and a reserved name
    resolves "inside" the anchor there without behaving like an ordinary file: writes vanish,
    reads return empty, `exists()` lies;
11. **alternate data stream** — a path component contains a `:`, which opens an NTFS alternate
    data stream; writing there is invisible to a directory listing and leaves the visible file
    unchanged;
12. **resolve failed** — resolving a path (the anchor root itself, or any prefix while checking
    rule 5) raised an `OSError` from the filesystem — most concretely, a trailing dot/space
    segment following an existing file component raises `NotADirectoryError` on Windows — or,
    since 0.2.4, a bare `RuntimeError`: a symlink loop (`root/a` -> `root/b`, `root/b` -> `root/a`)
    makes non-strict `Path.resolve()` raise `RuntimeError("Symlink loop from ...")` rather than an
    `OSError`, a POSIX-only case invisible to a Windows-only test run. Both are wrapped rather than
    allowed to escape, so a caller need only ever catch `PathSafetyError`, never a raw `OSError` or
    `RuntimeError`, and `scan` (0.2.5) can report a finding and keep walking instead of aborting;
13. **path resolves to a hardlinked file** — the resolved path names an existing regular file with
    more than one hard link. A hardlink needs no elevation to create (`mklink /H` on Windows, `ln`
    on POSIX) and has no symlink target for rules 4/5 to follow, so it defeats every rule above by
    construction: writing through it writes through to whatever else the same file is linked from,
    wherever that is. Directories are excluded — a directory's link count is an ordinary
    filesystem property, not evidence of anything. **Operational consequence:** a user whose
    instruction file is hardlinked between two client roots — a routine setup for sharing one file
    across projects — will see this refusal;
14. **inspect failed** — inspecting the resolved path for rule 13 raised an `OSError`, or,
    defensively, a `ValueError` (the same NUL-byte failure mode rule 8 already refuses earlier, in
    case one ever reached this point by some other route) or a `RuntimeError` (the same symlink-loop
    failure mode rule 12 refuses earlier, kept here too rather than assumed unreachable). Wrapped
    for the same reason as rule 12.

None of this changes how `verify` itself operates: it still reads only the paths a caller names on
its own command line, and it still never dereferences a path that arrived as ledger content rather
than a command-line argument.

## Adapter glob safety

`check_glob` refuses an adapter probe glob, each with its own named reason:

- **not a string** — the pattern is missing or not a non-empty string;
- **NUL byte** — the pattern contains a NUL byte;
- **`..` segment** — the pattern contains a `..` segment, including dot/space variants (`...`,
  `.. `, `. .`, and similar) that collapse to one, mirroring how `ntpath.realpath` normalizes a
  path built from this glob later;
- **absolute** — the pattern is absolute (either the POSIX `/...` form or a Windows drive-letter
  form).

No probe field may contain a glob that escapes its anchor. This check validates the pattern, at the
moment an adapter is loaded and before anything is expanded. Expansion is `scan`'s, and every path
it yields is checked again against its anchor before the file is opened.

## Path-safety refusal reasons

Every `PathSafetyError` raised anywhere in `dashboard.py` — by `resolve_anchored`, `anchor_path`,
or `check_glob` — carries a stable `reason` key in addition to the prose above. The block below is
the ground truth an alignment test in `dashboard/tests/test_dashboard.py` checks against: it
asserts this exact set of keys equals `dashboard.PATH_SAFETY_REASONS` in both directions, so a
refusal added to the code without being named here fails the test, and a name removed from here
that the code can still raise fails it too.

<!-- PATH_SAFETY_REASONS_START -->
- `invalid_anchor_name`
- `glob_not_string`
- `glob_nul_byte`
- `glob_dotdot_segment`
- `glob_absolute`
- `resolve_failed`
- `path_empty`
- `path_embedded_nul`
- `path_dotdot_segment`
- `path_absolute`
- `path_malformed_anchor_reference`
- `path_unknown_anchor`
- `path_reserved_device_name`
- `path_alternate_data_stream`
- `path_link_crosses_anchor`
- `path_resolves_outside_anchor`
- `path_inspect_failed`
- `path_hardlinked`
<!-- PATH_SAFETY_REASONS_END -->
