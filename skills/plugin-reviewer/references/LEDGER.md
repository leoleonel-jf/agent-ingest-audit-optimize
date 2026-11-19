# Ledger

The ledger is this plugin's own audit record: a local JSON file set the plugin reads and
writes. It is never transmitted.

## Bookkeeping is not implementation

Writing to the ledger and to its records is audit bookkeeping, not a change to the user's
environment. It is permitted in ANALYSIS, DELIBERATION, and IMPLEMENTATION, it never requires
authorization, and it never constitutes implementing a proposal. Never present a ledger write
as an implemented change. Creating a backup is not bookkeeping: it belongs to IMPLEMENTATION,
which already requires a recoverable backup before the first change.

## Where the rest is

This file holds what writing a record needs. Open another only for its subject:

| Subject | File |
|---|---|
| Path anchors, path safety, and the reasons a path is refused | [LEDGER_PATHS.md](LEDGER_PATHS.md) |
| Baselines, `scan`, the adapter format, the unknown client, and what a baseline does not cover | [LEDGER_BASELINES.md](LEDGER_BASELINES.md) |
| Runs, `drift`, and `rollback-preview` | [LEDGER_CHANGES.md](LEDGER_CHANGES.md) |
| `agent.lock`, the hash chain, and recovering from a git merge conflict | [LEDGER_INTEGRITY.md](LEDGER_INTEGRITY.md) |

## One review, one record

A review of a plugin, a skill, or an MCP server writes one `MATERIAL` record and one file under
`records/`. This is a complete ledger holding the first review of an installation, and `verify`
accepts it as written:

```json
{
  "schema_version": "1.0",
  "ledger_id": "global-claude-code",
  "scope": "global",
  "language": "en",
  "client": "claude-code",
  "adapter_version": 1,
  "created": "2026-11-19",
  "updated": "2026-11-19",
  "id_authority": true,
  "sequences": {"MAT": 1, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0},
  "known_projects": [],
  "records": [
    {
      "id": "MAT-2026-000",
      "type": "MATERIAL",
      "title": "Review: example-server (MCP server) at v1.4.2",
      "status": "ANALYZED",
      "classification": "TEST IN ISOLATION",
      "scope": "user-global",
      "created": "2026-11-19",
      "updated": "2026-11-19",
      "file": "records/MAT-2026-000.md",
      "links": {},
      "evidence": [
        {
          "source": "https://example.com/example-server/tree/v1.4.2",
          "kind": "repository",
          "verified_on": "2026-11-19",
          "time_sensitive": true,
          "expires_on": "2027-02-17"
        }
      ]
    }
  ],
  "baselines": [],
  "backlog": [
    {
      "id": "MAT-2026-000",
      "classification": "TEST IN ISOLATION",
      "reason": "Its launcher downloads an unpinned package at start.",
      "revisit_trigger": "The publisher pins the package, or a sandboxed trial shows what it fetches.",
      "revisit_after": null
    }
  ]
}
```

For the next review, append one record to the ledger its scope routes to (Scope routing), take
its number from the ID authority (Identifiers), raise `sequences.MAT` to one past the highest
number used, and set `updated`. The backlog entry is there only because this verdict names what
would change it; a verdict that names no such condition writes none. Everything below is the
detail behind these fields.

## Layout

Global scope, at the client's user configuration root:

```text
plugin-reviewer/
├── ledger.json
├── baseline/
├── records/
└── backups/
```

Before 0.11.0 this directory was named `agent-ingest-audit-optimize/`. A machine that already has
it keeps using it where it is: read and write that directory, for everything in the layout above
and for a user adapter. Never move it, copy it, or create the new directory beside it.

Renaming the directory to its new name is the user's to ask for, and it is not always harmless.
`verify`, `verify --chain`, and `chain --head` read the ledger document only, and answer the same
before and after. A `RUN` whose `backup.path` points into the directory does not: the path is
anchored, it names the directory, and after the move it resolves to nothing, so
`rollback-preview` reports that run `BROKEN`. Rewriting the path repairs the preview and, in a
sealed ledger, breaks the chain. Before a move, read every `backup.path`. When one names the
directory, say so, and let the user choose between keeping the former name and losing the preview
of those runs. After a move, run `rollback-preview` on each run and compare with before.

When both exist, stop, name both, and ask which one is the ledger. Use the one the user names,
leave the other untouched, and offer to settle it, so that the next session does not stop on the
same question. Two directories would each hold a ledger claiming to be the ID authority, which is
the conflict the Identifiers section exists to prevent, and merging them is a decision, never a
default.

Project scope, at the project root:

```text
.agent-audit/
├── ledger.json
└── records/
```

Backups always live in the global scope, even for project-scoped changes. Backups may contain
configuration values and must never be committed by accident.

When first creating a project-scope `.agent-audit/`, also write `.agent-audit/.gitignore`
containing exactly one line, `dashboard.html`. Records are meant to be committed; a generated
dashboard is not — it is regenerable from the ledger with `dashboard.py build` (see
[references/DASHBOARD.md](DASHBOARD.md)) and carries no information the ledger itself lacks.

This layout is a convention `verify` does not check — `verify` validates the ledger document's
contents only, never the directory structure or where backups are stored.

## Viewing the ledger

`dashboard.py build` renders `ledger.json` into a single offline `dashboard.html`: nine panels
(overview, inventory, changes, provenance, rollback, backlog, decisions, materials, help), no
network request. It writes exactly one file, next to the ledger by default, and refuses to
overwrite a file that is not already a dashboard. Read
[references/DASHBOARD.md](DASHBOARD.md) for panel semantics, the `build` flags, the no-Python
static-injection procedure, and the degraded text view for machines with no browser at all.

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
| `baselines` | array (see Baselines in [LEDGER_BASELINES.md](LEDGER_BASELINES.md)) |
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

**`update` is a stated exception to the paragraph above, for baselines only.** When `--id` is
omitted, `dashboard.py update ledger` mints the next `BASE` identifier from the ledger's own
sequence rather than requesting it from the authority, and it does not use the `-P` form. The
provisional path would be worse here than the liberty it avoids: `verify` checks
`pending_id_reconciliation` on records, not on baselines, so a `-P` baseline would pass carrying
no reconciliation marker — a silent lie in place of a visible one. Instead the command names the
identifier as locally minted on stderr and reports `"minted": "local"` on stdout, and the
residual risk is left where the layer that can see it lives: if the authority later issues the
same number, a verified set holding both documents reports the duplicate. Pass `--id` to keep
the authority in the loop. The reasoning is recorded in
`docs/specs/2026-08-01-dashboard-open-and-update.md` section 4.

The `update` summary on stdout always carries `findings`, a list of `{"code", "message"}` pairs
(empty when nothing was found or when the word is `anchors`), and `refused`, `null` unless the
command declined to write. The codes are `generic_fallback`, `adapter_expired`,
`user_config_unresolved` and `unredacted_parse`. By default a finding still appends the baseline and
the exit code `1` carries it. With `--strict`, `update ledger` and `update all` write nothing when the
scan reports any finding: the ledger keeps its bytes, no dashboard is rendered, `baseline_id` is
`null`, `refused` is `"strict"` and the exit code is `1`. `--strict` has no effect on `update anchors`.

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
| `classification` | one of the thirteen labels named below. `SKILL.md` teaches the five verdicts a review ends on; the others stay valid for records that already use them and for a material audit that needs one |
| `scope` | `session`, `project`, `workspace`, `user-global`, `organization`, `fleet` |
| `title` | non-empty string |
| `file` | non-empty string. Convention (not checked by `verify`): a path relative to the ledger's own directory, e.g. `records/PROP-2026-000.md` |
| `created`, `updated` | `YYYY-MM-DD` |
| `links.materials`, `links.runs`, `links.adrs` | optional arrays of record ids; a missing key means empty |

A record's `status` says how far it got: `PROPOSED` is awaiting a decision, `SUPERSEDED` was
replaced by a newer ADR, and the others mean what they name.

`ADOPT GLOBALLY`, `ADOPT AS A DEFAULT FOR NEW PROJECTS`, `MIGRATE EXISTING PROJECTS`,
`ADOPT LOCALLY`, and `ADAPT` are neither backlog nor terminal classifications. A review records
one of them on its `MATERIAL` record and stops there; when the adoption is authorized, the same
classification carries through to a PROPOSAL and a RUN. See Backlog for the other eight
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

A backlog entry keeps a finding to come back to: `id`, `classification`, `reason`,
`revisit_trigger`, `revisit_after`. Only `REJECT`, `NEEDS MORE EVIDENCE`, `RISK EXCEEDS BENEFIT`,
`MONITOR`, and `TEST IN ISOLATION` may appear on one. Write an entry when the finding names what
would change it; `verify` does not ask for one behind every such record.

`revisit_trigger` is a string or `null`. `revisit_after` is `null` or `YYYY-MM-DD`. At least
one of the two must be non-empty and non-falsy.

`OBSOLETE`, `NOT APPLICABLE`, and `ALREADY IMPLEMENTED` are terminal. They are recorded as
records and never enter the backlog; using one of them on a backlog entry is itself a finding.

A backlog entry's `id` is a **back-reference** to the record whose evidence produced the finding,
not an identifier of the entry itself. It is deliberately not unique: one material routinely
produces several backlog entries, and two entries sharing an id is correct. `verify` checks that the
id resolves to a record declared somewhere in the verified set, and suppresses that check, like the
link checks, when any ledger in the set could not be read.

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
