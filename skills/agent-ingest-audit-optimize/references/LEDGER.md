# Ledger

The ledger is this plugin's own audit record: a local JSON file set the plugin reads and
writes. It is never transmitted.

## Bookkeeping is not implementation

Writing to the ledger and to its records is audit bookkeeping, not a change to the user's
environment. It is permitted in ANALYSIS, DELIBERATION, and IMPLEMENTATION, it never requires
authorization, and it never constitutes implementing a proposal. Never present a ledger write
as an implemented change. Creating a backup is not bookkeeping: it belongs to IMPLEMENTATION,
which already requires a recoverable backup before the first change.

## Layout

Global scope, at the client's user configuration root:

```text
agent-ingest-audit-optimize/
├── ledger.json
├── baseline/
├── records/
└── backups/
```

Project scope, at the project root:

```text
.agent-audit/
├── ledger.json
└── records/
```

Backups always live in the global scope, even for project-scoped changes. Backups may contain
configuration values and must never be committed by accident.

This layout is a convention `verify` does not check — `verify` validates the ledger document's
contents only, never the directory structure or where backups are stored.

## The ledger document

`ledger.json` is a single JSON object. `dashboard.py verify` requires every one of these
top-level fields, and flags any other field as unknown:

| Field | Rule |
|---|---|
| `schema_version` | must be `"1.0"` |
| `ledger_id` | non-empty string |
| `scope` | `global` or `project` |
| `language` | string, at least 2 characters (e.g. `en`, `pt-BR`) |
| `client` | non-empty string |
| `adapter_version` | integer, at least 1 |
| `created`, `updated` | `YYYY-MM-DD` |
| `id_authority` | boolean — `true` when `scope` is `global`, `false` when `scope` is `project`; the other combination is a finding |
| `sequences` | object, exactly the keys below |
| `known_projects` | array (see Known projects) |
| `records` | array (see Records) |
| `baselines` | array (see Baselines) |
| `backlog` | array (see Backlog) |

`sequences` holds a floor for each identifier prefix, not the next free number outright — integer
at least 0, with no keys beyond `MAT`, `PROP`, `RUN`, `ADR`, `BASE`. See Identifiers for the exact
rule.

## Scope routing

| Record scope | Destination |
|---|---|
| `session`, `project`, `workspace` | The project ledger when a project root exists, otherwise the global ledger |
| `user-global`, `organization`, `fleet` | Always the global ledger |

Update `known_projects` in the global ledger on every project-ledger write. This routing is a
writing convention, not something `verify` checks — `verify` only checks that a record's
`scope` is one of the six values above, never which physical ledger holds the record.

## Path anchors

Three anchors exist: `$USER_CONFIG` is the client's user-level configuration root, `$PROJECT` is
the project root of the ledger that owns the record, and `$PLUGIN` is the installed bundle root.
`anchor_path` supplies the roots the caller has in hand; this release decides none of them itself.

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
    `RuntimeError`, and `scan` (0.2.4) can report a finding and keep walking instead of aborting;
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

No probe field may contain a glob that escapes its anchor. This release only validates the
pattern; nothing here expands a glob — expansion arrives with `scan` in 0.2.4.

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

## Identifiers

Identifiers match `^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$`: `MAT` for MATERIAL, `PROP` for
PROPOSAL, `RUN` for RUN, `ADR` for ADR, `BASE` for BASELINE.

The global ledger is the only ID authority (`id_authority: true`). When more than one ledger
in a verified set claims authority, that is a finding.

Request the next ID from the global ledger. When it is unreachable, mint a provisional ID with
a `-P` suffix, set `pending_id_reconciliation` to `true` on the record, and reconcile on the
next successful global write, rewriting every reference. `verify` checks only the flag: a
`-P` id without `pending_id_reconciliation: true` is a finding. It does not check that
references were actually rewritten.

`verify` checks that a ledger's `sequences` value for a prefix is at least one past the highest
number that ledger's own records already use. It is a floor, not an equality: a value above it
passes too, so a padded `sequences` is never flagged. Keeping it at exactly the next free number is
a house convention, stricter than what is enforced.

The ledger that declares `id_authority: true` is additionally checked against every record in the
verified set, not just its own — it is the ledger that issued those identifiers, and it usually
holds no records itself. This includes provisional (`-P`) identifiers: one minted while the
authority was unreachable still counts toward this check, so the authority can be asked to cover a
number it never itself issued and that reconciliation will later discard. This is consistent with
`-P` ids being treated the same as any other identifier everywhere else in this check, and the
remedy is harmless — the rule is a floor, so bumping the counter costs nothing.

A `baselines[]` entry's `id` participates in these sequence rules exactly as a record's `id` does,
in both forms above: it feeds the per-document floor (a ledger's `sequences.BASE` must be at least
one past the highest `BASE` number that ledger's own baselines, or records, already use), and it
feeds the ID authority's set-wide coverage (the authority's `sequences.BASE` must cover a `BASE` id
spent in any ledger in the verified set, wherever it was actually spent). A baseline identifier is
an identifier; nothing in this check treats it differently from a record's.

## Records

Every record requires `id`, `type`, `title`, `status`, `classification`, `scope`, `created`,
`updated`, `file`, `links`, `evidence`.

| Field | Rule |
|---|---|
| `type` | `MATERIAL`, `PROPOSAL`, `RUN`, `ADR`, `BASELINE` |
| `status` | `ANALYZED`, `PROPOSED`, `DECIDED`, `IMPLEMENTED`, `VALIDATED`, `VALIDATED WITH CAVEATS`, `NOT IMPLEMENTED`, `PENDING`, `ROLLBACK`, `SUPERSEDED` |
| `classification` | the vocabulary in `SKILL.md` |
| `scope` | `session`, `project`, `workspace`, `user-global`, `organization`, `fleet` |
| `title` | non-empty string |
| `file` | non-empty string. Convention (not checked by `verify`): a path relative to the ledger's own directory, e.g. `records/PROP-2026-000.md` |
| `created`, `updated` | `YYYY-MM-DD` |
| `links.materials`, `links.runs`, `links.adrs` | optional arrays of record ids; a missing key means empty |

A record's `status` reuses `SKILL.md`'s reporting labels, plus `PROPOSED` (awaiting decision)
and `SUPERSEDED` (replaced by newer ADR).

`ADOPT GLOBALLY`, `ADOPT AS A DEFAULT FOR NEW PROJECTS`, `MIGRATE EXISTING PROJECTS`,
`ADOPT LOCALLY`, and `ADAPT` are neither backlog nor terminal classifications: they carry
through to a PROPOSAL and, once authorized, a RUN. See Backlog for the other eight
classifications.

A record whose `id` ends `-P` requires `pending_id_reconciliation: true`.

## Evidence

Every evidence item requires `source`, `kind`, `verified_on`, and `time_sensitive`. `verify`
checks only that these four keys are present and that `time_sensitive` is a boolean — it does
not check the type or format of `source`, `kind`, or `verified_on`. Write `verified_on` as
`YYYY-MM-DD` regardless, for consistency with every other date in the ledger.

Model names, prices, feature availability, and defaults are always time sensitive. A
time-sensitive item additionally requires `expires_on`, checked only for presence as a
non-blank string — `verify` does not parse it as a date or compare it to today. Default
validity is 90 days from `verified_on`; this is a house convention, not something `verify`
enforces.

## Backlog

A finding classified `REJECT`, `NEEDS MORE EVIDENCE`, `RISK EXCEEDS BENEFIT`, `MONITOR`, or
`TEST IN ISOLATION` becomes a backlog entry: `id`, `classification`, `reason`,
`revisit_trigger`, `revisit_after`.

`revisit_trigger` is a string or `null`. `revisit_after` is `null` or `YYYY-MM-DD`. At least
one of the two must be non-empty and non-falsy.

`OBSOLETE`, `NOT APPLICABLE`, and `ALREADY IMPLEMENTED` are terminal. They are recorded as
records and never enter the backlog; using one of them on a backlog entry is itself a finding.

A backlog entry's `id` is a **back-reference** to the record whose evidence produced the finding,
not an identifier of the entry itself. It is deliberately not unique: one material routinely
produces several backlog entries, and two entries sharing an id is correct. `verify` checks that the
id resolves to a record declared somewhere in the verified set, and suppresses that check, like the
link checks, when any ledger in the set could not be read.

## Runs

A RUN record additionally requires `proposal`, `authorization`, `result`, `targets`, `backup`,
`rollback`, `self_reported`.

| Field | Rule |
|---|---|
| `proposal` | a record id |
| `authorization.quote` | non-empty string, the authorization verbatim |
| `authorization.recorded_on` | `YYYY-MM-DD` |
| `result` | `VALIDATED`, `VALIDATED WITH CAVEATS`, `PARTIALLY VALIDATED`, `NOT VALIDATED`, `FAILED`, `ROLLBACK COMPLETED` |
| `targets` | non-empty array |
| `backup` | object or `null` |
| `rollback.tested` | `NOT_TESTED`, `PARTIAL`, `PASSED`, `FAILED` |
| `self_reported` | array of strings naming the fields no tool can confirm |

Each target requires `anchor`, `kind`, `before_digest`, `after_digest`, `reversible`,
`residual_effect`. `before_digest` and `after_digest` are `sha256:<64 hex>` or `null`. A target
that is not reversible must carry a non-empty, non-falsy `residual_effect`.

A target may also carry `portable` — a boolean, optional, never required. See Baselines for why.

`backup`, when not `null`, requires `digest` (`sha256:<64 hex>`) and `verified` (boolean).
`rollback` may also carry a `file` pointing at the written rollback document; only `tested` is
required.

Never record a digest that was not computed. Never mark a backup verified without reading it.

`self_reported` must name `targets`. `verify` checks every target's shape and can never check that
the array covers what the run actually changed — nothing in a ledger states how many files a run was
supposed to touch. A RUN record naming three targets for a fourteen-file change validates clean.
Listing `targets` in `self_reported` does not make coverage verifiable; it stops the record from
being silent about the one thing it cannot prove.

## Known projects

Each entry in the global ledger's `known_projects` requires `project_root`, `ledger_path`,
`last_seen`, `last_digest`, `status`.

| Field | Rule |
|---|---|
| `project_root`, `ledger_path` | non-empty strings |
| `last_seen` | `YYYY-MM-DD` |
| `last_digest` | `sha256:<64 hex>` |
| `status` | `OK`, `UNREACHABLE`, `CHANGED_EXTERNALLY` |

Mark a project `UNREACHABLE` rather than removing its entry.

`last_digest` is the sha256 of the referenced ledger's **final on-disk bytes**, taken after every
other edit to that ledger is complete. Hash the file, not the JSON text in an editor: a trailing
newline or a line-ending difference changes the digest of an otherwise identical document.

The digest is recompared, and a mismatch is a finding, when a normalized `ledger_path` textually
agrees with a normalized path passed to that `verify` invocation. The comparison is purely
textual — case-insensitive, separator-normalized, never resolved against the filesystem — so it is
not "the same file was passed" that triggers it but "the same string, once normalized". A
`ledger_path` stored as a relative path is not compared against an invocation that names the same
file with an absolute path, or with a relative path built from a different starting directory, or
in a different case or separator style on a case-sensitive filesystem: those are different strings
after normalization, so the comparison is silently skipped even though the referenced ledger was in
fact passed. When there is no textual match, nothing is checked — silence there means
**not comparable**, never "correct". `verify` deliberately does not open a path read out of
ledger content.

## Baselines

Each entry in `baselines[]` requires `id`, `captured_on`, `client`, `adapter_version`, `items`.

| Field | Rule |
|---|---|
| `id` | a `BASE`-prefixed identifier, matching the pattern in Identifiers |
| `captured_on` | `YYYY-MM-DD` |
| `client` | non-empty string |
| `adapter_version` | integer, at least 1 |
| `items` | array (see below) |

Each element of `items` requires `kind`, `name`, `anchor`, `digest`, `attributes`, `origin`,
`state`.

| Field | Rule |
|---|---|
| `kind` | one of `instruction-file`, `skill`, `plugin`, `agent`, `command`, `hook`, `mcp-server`, `permission-rule`, `model-setting`, `env-var-name` |
| `name` | non-empty string |
| `anchor` | non-empty string |
| `digest` | `sha256:<64 hex>` or `null` |
| `attributes` | object |
| `origin` | `pre-existing`, or a record identifier with prefix `PROP` |
| `state` | `present` or `not_present` |
| `portable` | boolean, optional |

`state` records that a probe matched nothing. The design spec requires that a probe matching
nothing be recorded as `not_present`, never as an error, but gives no field to hold that outcome —
it is neither a `kind` nor one of the other documented item fields. A separate `state` field is
used rather than overloading `kind` (a closed enum client adapters are written against) or relying
on a `null` `digest`: a present item can legitimately have nothing to hash — an `env-var-name` has
a name and no readable value — so `null` already means something else.

`portable`, on a baseline item or on a run target, is a boolean when present and is never required.
Requiring it would invalidate every RUN record written before this release, including this
repository's own, none of which ever carried it.

## Language

Free text follows the user's working language. Operating states, status labels, classification
labels, and record identifiers stay in canonical English.

## Validation

Run `verify` after every ledger write, passing every reachable ledger in the same invocation so
the cross-ledger checks run. Running `verify` is bookkeeping too: it is read-only and permitted
in any operating state.

```text
python assets/scripts/dashboard.py verify <path-to-ledger.json> [more...]
```

Pass every reachable ledger in one invocation so cross-ledger checks run: known-project digest
comparison against the referenced ledger's on-disk bytes (the check that depends most on every
ledger being present, since a ledger left out of the invocation cannot be compared at all),
duplicate identifiers (within or across ledgers), sequence consistency, unreconciled provisional
identifiers, dangling links, backlog `id` back-references, and more than one ledger claiming ID
authority.

`verify` prints every finding it can compute plus a read error for each ledger it could not
parse. If any ledger in the set could not be read, dangling-link checks and backlog
back-reference checks are both skipped for the whole set — a partial set must not produce a
misleading finding for either, since the record a link or a backlog entry points to could live in
the ledger that could not be read — but every other check still runs against the ledgers that were
readable.

Exit codes: `0` clean, `1` findings with every ledger readable, `2` at least one ledger could
not be read (missing, invalid JSON, or not a JSON object).
