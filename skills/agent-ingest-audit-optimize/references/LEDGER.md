# Ledger

The ledger is this plugin's own audit record: a local JSON file set the plugin reads and
writes. It is never transmitted.

## Bookkeeping is not implementation

Writing to the ledger, to its records, and to its backups is audit bookkeeping, not a change
to the user's environment. It is permitted in ANALYSIS, DELIBERATION, and IMPLEMENTATION, it
never requires authorization, and it never constitutes implementing a proposal. Never present
a ledger write as an implemented change.

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
| `baselines` | array; each element must be an object, but no field-level schema yet |
| `backlog` | array (see Backlog) |

`sequences` holds the next free number for each identifier prefix, integer at least 0, with no
keys beyond `MAT`, `PROP`, `RUN`, `ADR`, `BASE`.

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

`verify` also checks that a ledger's `sequences` value for a prefix is high enough to cover the
highest number already used by that prefix — never that it matches exactly. A sequence value
higher than necessary is not flagged.

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

`backup`, when not `null`, requires `digest` (`sha256:<64 hex>`) and `verified` (boolean).
`rollback` may also carry a `file` pointing at the written rollback document; only `tested` is
required.

Never record a digest that was not computed. Never mark a backup verified without reading it.

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

## Language

Free text follows the user's working language. Operating states, status labels, classification
labels, and record identifiers stay in canonical English.

## Validation

```text
python assets/scripts/dashboard.py verify <path-to-ledger.json> [more...]
```

Pass every reachable ledger in one invocation so cross-ledger checks run: duplicate
identifiers (within or across ledgers), sequence consistency, unreconciled provisional
identifiers, dangling links, and more than one ledger claiming ID authority.

`verify` prints every finding it can compute plus a read error for each ledger it could not
parse. If any ledger in the set could not be read, dangling-link checks are skipped for the
whole set — a partial set must not produce a misleading dangling-link finding — but every
other check still runs against the ledgers that were readable.

Exit codes: `0` clean, `1` findings with every ledger readable, `2` at least one ledger could
not be read (missing, invalid JSON, or not a JSON object).
