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

The design spec names three anchors: `$USER_CONFIG` is the client's user-level configuration root,
`$PROJECT` is the project root of the ledger that owns the record, and `$PLUGIN` is the installed
bundle root. `anchor_path` supplies the roots the caller has in hand; the path layer decides none
of them itself. An adapter may declare anchors beyond these three — the shipped ones do, and
The adapter format below says which and why.

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

## Capturing a baseline with `scan`

```text
python assets/scripts/dashboard.py scan --id BASE-2026-000 [--client NAME] [--project PATH]
                                        [--adapter FILE] [--user-config PATH]
```

`scan` reads one client's configuration and emits exactly one `baselines[]` entry, as JSON, on
stdout. It opens files, hashes their bytes, and parses JSON and TOML; it writes no file and creates
no directory anywhere, so stdout is the only thing it produces. It never runs anything a
configuration file names: a settings key whose value is a shell command that mints a credential is
recorded as a name and a digest like every other value.

| Argument | Meaning |
|---|---|
| `--id` | required; the `BASE` identifier the emitted entry carries |
| `--client` | the client to scan; detected when omitted, see The unknown client below |
| `--project` | the root `$PROJECT` anchors to; the process working directory when omitted |
| `--adapter` | one adapter file to run, overriding selection entirely and validated like any other |
| `--user-config` | the configuration root user adapters are read from; that directory is never read when omitted |

`--id` is required because allocation is a ledger concern and `scan` does not get a second, private
implementation of it. The rules about sequences, provisional suffixes, and cross-scope collision are
stated once, in Identifiers above, and they need a ledger to apply; `scan` opens no ledger. It checks
only that what it was handed is a well-formed `BASE` identifier, before the adapter is opened, so a
typo costs no walk over anyone's configuration.

Placing the entry is the agent's work, not the command's: take the next free `BASE` number under the
Identifiers rules — from the global ID authority, or as a `-P` provisional identifier when the
authority is unreachable — pass it as `--id`, and append the emitted object to the target ledger's
`baselines[]` array. A baseline identifier is spent when the entry is placed, exactly as a record's
is.

Exit codes: `0` clean, `1` findings, `2` a tool error — a malformed `--id`, an adapter that does not
validate, an unknown `--client`. The entry still reaches stdout at `1`; nothing reaches it at `2`.
Selection notes and findings go to stderr, so stdout parses as one JSON document whatever the
outcome.

A finding here means the baseline may be reporting a clean machine when it in fact looked at almost
nothing, and three raise one: the adapter is past its `expires_on`; its `$USER_CONFIG` resolved to no
directory on this machine, so every probe beneath it is `not_present` rather than looked at; or
selection fell back to `generic`, which probes nothing. Any other unresolved anchor is still recorded
on each probe beneath it, as `reason: "unresolved_anchor"` in the item's attributes, but does not
move the exit code — `codex.json`'s `$SYSTEM_CONFIG` can never resolve on Windows, and a finding an
operator can never clear teaches them to ignore the exit code, which costs every other finding its
meaning.

## The adapter format

An adapter is data, one JSON document per client, and `scan` knows nothing about any client except
what it reads from one. `assets/schemas/adapter.schema.json` states the format for humans and
external tools; the bundle carries no JSON Schema library, so the loader's own validator is what
actually runs, and a test compares the two in both directions. A single finding refuses the whole
document. Unlike a ledger's findings, which are reported and counted, an adapter's are fatal: every
probe beneath a broken adapter is suspect, and continuing would produce a baseline that looks clean
because it scanned nothing.

Every top-level field is required, and any other field is a finding:

<!-- ADAPTER_FIELDS_START -->
| Field | Rule |
|---|---|
| `adapter_version` | integer, at least 1; copied onto the emitted entry so a baseline records which generation of the adapter produced it |
| `client` | non-empty string matching `[a-z0-9-]+`. This, not the file name, is the adapter's identity: `--client` resolves against it, and a user adapter overrides a bundled one by matching it |
| `expires_on` | `YYYY-MM-DD` |
| `anchors` | object; each key an anchor name in `$NAME` form, each value a non-empty array of candidate roots |
| `probes` | array, and it may be empty — an adapter that probes nothing is the entire point of `generic.json` |
| `sensitive_key_patterns` | array of non-empty strings; required, and may be empty |
<!-- ADAPTER_FIELDS_END -->

**Anchor candidates are tried in order and the first that exists wins.** A candidate is either
`$env:NAME` — the value of that environment variable, where unset and empty are the same thing and
both are skipped, because an empty variable is what a shell leaves behind after `export NAME=` — or a
filesystem path, with a leading `~` expanded and a relative candidate resolved against `--project`
rather than against the process working directory. A candidate qualifies only when it resolves to an
existing **directory**; one that exists as a file does not, since joining a probe's tail onto a file
yields paths that can never resolve. When no candidate qualifies the anchor is *unresolved*: it is
absent from the roots rather than guessed at, and every probe beneath it is recorded `not_present`.
Guessing the vendor's default instead is the failure the research names outright — `CLAUDE_CONFIG_DIR`
and `CODEX_HOME` relocate everything, and an adapter that scans the default tree anyway reports a
clean baseline for a configuration it never looked at. This is why every `$env:` candidate is written
ahead of the default it overrides.

The shipped adapters declare two anchors beyond the design spec's three, and they are extensions
rather than part of that design:

- `$SYSTEM_CONFIG`, declared by `codex.json` with the single candidate `/etc/codex`, exists because
  that location cannot be written as a probe at all: `check_glob` refuses an absolute pattern, so a
  system path can only reach an adapter as an anchor root.
- `$HOME`, declared as `~` by both client adapters, exists because the research places
  `<home>/.claude.json` and `<home>/.agents/skills/` against the home directory itself rather than
  under the relocatable user configuration root. `CLAUDE_CONFIG_DIR` moves `$USER_CONFIG` and does
  not move `~/.claude.json`, so anchoring that file to `$USER_CONFIG` would probe a path that stops
  existing the moment the root is relocated.

Nothing in the path layer treats either name specially: a path found under one is stored anchored,
and the longest-anchor rule decides between them like any other pair.

**Probes.** Each requires `kind` and exactly one of `glob` or `path` — both is a finding, neither is
a finding:

<!-- PROBE_FIELDS_START -->
| Field | Rule |
|---|---|
| `kind` | required; one of the ten `items[].kind` values in Baselines above, imported from the same closed enum rather than restated |
| `glob` | anchored pattern, expanded under its resolved anchor, one item per match and one `not_present` item when it matches nothing |
| `path` | anchored path, yielding exactly one item |
| `scope` | optional non-empty string, copied onto the item's attributes |
| `parse` | optional `json` or `toml`, and only alongside `path` |
| `pointer` | optional RFC 6901 JSON pointer, and only alongside `parse` |
<!-- PROBE_FIELDS_END -->

`glob` and `path` both pass `check_glob` at **load** time, under the rules in Adapter glob safety
above, so an adapter carrying a `..` segment or an absolute form is refused before a single probe
runs. That check is about the pattern; every path a probe actually produces is re-checked against its
anchor before it is opened, because a symlinked directory can carry a match out of the tree between
the adapter being validated and the walk running.

`parse` reads the file, and `pointer` selects a sub-document within it: the location a pointer names
becomes one item per key, which is what turns one `settings.json` into one `mcp-server` item per
server. `parse` pairs only with `path` because parsing is per-document and a glob yields many
documents against one pointer. A pointer that does not resolve is one `not_present` item, not an
error — a client with no MCP servers configured has no `mcpServers` key, and the baseline has to
record that it looked. A file that will not parse is `present`, with its digest and a stable
`parse_error`; a `toml` probe under an interpreter without `tomllib` is `present`, with its digest and
`parse_unavailable`, never a crash and never a pretence that the file held nothing.

`scope` is recorded and never resolved. It names the layer an item came from — the shipped adapters
use `user`, `project`, and `system` — and `scan` computes no precedence winner from it; see
What a baseline does not cover below for why.

`sensitive_key_patterns` are `fnmatch` patterns matched case-insensitively against key names in a
parsed document, so `*key*` and the literal `env` both work, and `env` matches the key `env` without
matching `environment`. A matching key keeps its name; its value is replaced by
`{"redacted": true, "digest": "sha256:…"}` whatever its type, because an object and an array carry
secrets as readily as a string. Recursion stops at the match: nothing beneath a redacted value is
walked or recorded, which is why the single pattern `env` protects an entire MCP `env` block without
enumerating what is inside it. The digest is there so drift can tell "the token changed" from "the
token is gone" without ever having held either. The patterns live in adapter data rather than in code
because the key name a vendor invents next is not something the code can know.

`expires_on` exists because a vendor path is time-sensitive evidence, under the same rule Evidence
above states for every other claim: the shipped adapters were built from one research document and
inherit its expiry. Running an adapter past that date is a finding rather than an error, and the scan
still produces its baseline, because an adapter whose paths have quietly gone stale is exactly the
case that produces a clean-looking baseline of nothing.

## The unknown client

Without `--client`, `scan` detects: an adapter matches when at least one of its `$USER_CONFIG`
candidates resolves, under the candidate rules above and no others, so an adapter is detected on
exactly the conditions its probes would later run under. Exactly one match selects that adapter. Two
or more, or none, selects `generic`, which declares no probes and therefore emits an entry whose
`items` array is empty. Detection never guesses between two plausible clients silently.

Reaching `generic` by falling back and asking for it by name are deliberately different outcomes.
`--client generic` is an answer, and it exits `0`. A fallback is not an answer; it is a scan that
covered nothing while looking clean, so it is a finding that names the clients weighed and points at
`--client`. The two are told apart by structured data carried out of selection, never by matching on
the wording of a note.

A client no bundled adapter covers is served by a user adapter, at:

```text
<user-config>/agent-ingest-audit-optimize/adapters/local.json
```

`<user-config>` is what `--user-config` names, and without it that directory is never opened — not
defaulted to the home directory. The tool cannot know which client's configuration root is meant on a
machine that may have several, and reading a directory the user did not name is the thing the whole
path boundary exists to prevent.

A user adapter is keyed by its `client` value like every other adapter, and a user adapter beats a
bundled one declaring the same client, with a note recording the override and naming both files. Two
adapters in the *same* directory declaring one client is refused outright: whichever won would be
decided by sort order, and the loser would be invisible — including to the user who edited it and saw
nothing change.

A user adapter is validated exactly as a bundled one is, and refused the same way. It is never
silently skipped in favour of the bundled file it was written to replace: routing around a broken
override leaves the user reading a baseline from the adapter they thought they had overridden.
`SKILL.md` owns the other half of this — how the agent asks for the paths and what it may write.

## What a baseline does not cover

`scan` reads less than the configuration it walks, and each of these is a decision rather than an
oversight. They are recorded because a gap nobody wrote down is indistinguishable from a gap nobody
noticed.

**Credential files are not probed at all.** Codex's `auth.json` and Claude Code's credentials file
are the two highest-risk files the research names, and nothing looks at either — not even for a
digest and a `present`/`not_present` state, which would hold no secret. The obstacle is the `kind`
enum: it is closed by the design spec, all ten values name a kind of configuration, and none of them
fits a credential store. The cost is a drift signal one would very much want, because a credentials
file appearing where there was none says the store moved from the OS keyring onto the disk. Deferred
until there is an eleventh kind to record it under.

**Hook scripts are not digested, only their registrations.** A `hook` item records that a hook is
registered under a settings file's `hooks` key; the script it runs is not opened and not hashed, so
rewriting that script produces an identical baseline. This is deliberate and not an oversight:
resolving a path read out of a configuration file would cross the boundary drawn in 0.2.2, which
`verify` states as never dereferencing a path that arrived as content rather than as an argument.
A probe naming a hooks directory outright would be a different thing and is allowed by the format;
none is shipped.

**Managed and enterprise policy is not probed.** The research gives no path for it, only
"platform-specific policy directory", and no path ships that was not verified. Managed policy is the
highest-precedence settings layer there is, so a baseline missing it is incomplete in the one layer
that overrides all the others.

**Per-subsystem precedence is not expressible.** Settings and skills resolve in different orders
inside one client — Claude Code resolves settings managed, local, project, user, and skills
enterprise, personal, project — so a single "which layer wins" answer computed at scan time would be
wrong for half the kinds. `scan` therefore records the layer each item came from in `attributes.scope`
and computes no winner. The adapter format has nowhere to state an ordering, so `drift` will need
that ordering from somewhere and it is currently nowhere in the shipped data.

**`$SYSTEM_CONFIG` is POSIX-only and cannot be declared optional.** Its only candidate is
`/etc/codex`, and the format has no way to mark an anchor as absent by design on a platform, so on
Windows it is permanently unresolved and its probes are permanently `not_present`.

**Redaction matches names and never values.** A secret is protected by the key it sits under, not by
what it looks like, so a secret sitting under a key no pattern names is copied whole. Two shapes
where that was found to happen are closed in the shipped client adapters — `args`, which is where an
MCP server conventionally receives `--api-key` as a positional argument, and `*url*`, which is where
a query-string token hides — and closing them costs baseline detail, deliberately. A redacted
argument list still carries the file's digest, so `drift` can say that a server's arguments changed;
the baseline no longer records what they were, and the same now goes for every `base_url` a Codex
model provider declares. That trade is the point: an argument list a reader can recover from a
baseline is worth less than one that cannot leak out of it. `*url*` is a substring match and will
also redact a key that merely contains those three letters, `curl` among them, which costs a server
named that way its whole entry. What stays open is everything neither pattern names: a secret
under a key name nobody has seen yet is still copied, and the only remedy is a user adapter
declaring that name.

**A `parse` probe over an empty `sensitive_key_patterns` is a finding, not a refusal.** An adapter
may legitimately declare no patterns — `generic.json` does, and it probes nothing — so refusing the
empty list outright would refuse the one file that needs it. But an adapter that parses a document
while redacting nothing writes every value it reads straight into the baseline, and a user adapter
overriding a bundled client by name is exactly how that arrives: the override is honoured whole, the
bundled patterns are not merged into it, and a scan that used to redact would then dump a parsed
settings file verbatim while exiting `0`. `scan` therefore raises a finding for the combination,
which moves the exit code without withholding the baseline. It is recorded here as a gap rather than
as a fix because the finding reaches stderr beside the baseline it warns about: an operator who
redirects stdout and ignores the exit code has the values anyway.

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
