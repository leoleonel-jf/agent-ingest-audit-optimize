# Ledger: runs, `drift` and `rollback-preview`

What an implementation run records, and the two read-only commands used around a change.
Part of the ledger reference; [LEDGER.md](LEDGER.md) holds the index.

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

A target may also carry `portable` — a boolean, optional, never required. See Baselines in
[LEDGER_BASELINES.md](LEDGER_BASELINES.md) for why.

`backup`, when not `null`, requires `digest` (`sha256:<64 hex>`) and `verified` (boolean).
`rollback` may also carry a `file` pointing at the written rollback document; only `tested` is
required.

Never record a digest that was not computed. Never mark a backup verified without reading it.

`self_reported` must name `targets`. `verify` checks every target's shape and can never check that
the array covers what the run actually changed — nothing in a ledger states how many files a run was
supposed to touch. A RUN record naming three targets for a fourteen-file change validates clean.
Listing `targets` in `self_reported` does not make coverage verifiable; it stops the record from
being silent about the one thing it cannot prove.

## Checking a baseline with `drift`

```text
python assets/scripts/dashboard.py drift <path-to-ledger.json> [--project PATH]
                                         [--adapter FILE] [--user-config PATH]
```

`drift` re-resolves every anchor a ledger recorded against the environment as it is now,
recomputes file digests, and classifies each baseline item and each RUN target into one of
`IN_PLACE`, `DRIFTED`, `REVERTED`, `MISSING`, or `UNVERIFIABLE`. It is read-only in the same
terms `scan` is: it opens files and hashes their bytes, writes no file, creates no directory, and
executes nothing a configuration file names. The report is one JSON document on stdout; selection
notes and findings go to stderr, so a caller can pipe stdout straight into a JSON reader.

| Argument | Meaning |
|---|---|
| `<path-to-ledger.json>` | the ledger whose recorded baselines and runs are classified |
| `--project` | names the `$PROJECT` root exactly as it does for `scan`; unset, it is the working directory |
| `--adapter` | one adapter file, replacing selection outright |
| `--user-config` | where user adapters are looked for; without it, none are |

There is no `--client` flag, on purpose: each baseline entry names its client, the ledger's
top-level `client` names the client for run targets, and a flag overriding recorded provenance
would classify one client's files under another client's anchors. Everything else is the `scan`
selection machinery unchanged — anchor roots are adapter data, and `drift` does not get a second,
private resolver. An anchor that cannot be resolved — `$SYSTEM_CONFIG` on Windows, a
`$USER_CONFIG` with no resolving candidate — makes each item beneath it `UNVERIFIABLE` with a
reason, never an error: the environment being unreadable is a finding about the environment, not
a crash in the tool.

**A baseline item** pairs its recorded state and digest with the current file:

| Recorded | Current | State |
|---|---|---|
| `present`, digest D | file exists, digest D | `IN_PLACE` |
| `present`, digest D | file exists, digest differs from D | `DRIFTED` |
| `present`, digest D | file gone | `MISSING` |
| `not_present` | still absent | `IN_PLACE` |
| `not_present` | file exists now | `DRIFTED` |
| `present`, digest `null` (unreadable at scan) | anything | `UNVERIFIABLE` |
| anything | unreadable now | `UNVERIFIABLE`, with the reason |

A recorded absence that holds is `IN_PLACE`: the baseline recorded that it looked and found
nothing, and nothing is still there. A file where none was recorded is `DRIFTED`, and it is one
of the strongest drift signals there is — configuration arriving from outside. `REVERTED` cannot
occur for a baseline item: there is no before/after pair to revert between, and the report does
not manufacture one.

An absence recorded *inside* a file is re-verified differently: for an item whose attributes
carry a recorded `pointer` and `parse` format — what `scan` writes on `pointer_unresolved` and
pointer-derived `no_match` items — the file's existence answers nothing, because the file existed
at scan time too, or there would have been no document to walk. `drift` re-resolves the recorded
location the way `scan` resolved it: parse, redact with the same adapter patterns, walk the same
pointer. The location still absent or still an empty mapping is `IN_PLACE`; the location
resolving now is `DRIFTED`, `appeared`; a file that no longer parses is `UNVERIFIABLE`. Nothing
the parse produces reaches the report — the recheck's entire output is a state and a reason. An
in-file absence recorded by a baseline that predates the recorded pointer is `UNVERIFIABLE`,
`pointer_unrecorded`: nothing to re-resolve, no verified answer in either direction. A
`no_match` item *without* a recorded pointer is a literal, wildcard-free glob that matched
nothing, and for that item the file appearing is exactly the drift it looks like.

**A run target** compares the current digest against the pair its RUN record carries:

| Current | State |
|---|---|
| equals `after_digest` | `IN_PLACE` |
| equals `before_digest` | `REVERTED` |
| equals neither | `DRIFTED` |
| path gone | `MISSING` |
| neither digest recorded | `UNVERIFIABLE` |

`after_digest` is compared first, so a target whose two digests are equal — a run that rewrote a
file to the same bytes, recorded honestly — reads as the change intact, never as a rollback
nobody performed.

**Resolution annotations** sit beside classifications and never inside them. For every (kind,
name) recorded at more than one scope, the report attaches the adapter's declared resolution
under the modes in Declared resolution ([LEDGER_BASELINES.md](LEDGER_BASELINES.md)); a shadowed item that drifted is still `DRIFTED`,
because shadowing is a fact about today's layering and the reader deciding what to do about the
drift is entitled to both facts.

**Adapter versions.** A baseline whose `adapter_version` differs from the selected adapter's
raises a finding on the entry, and its items are still classified — the comparison crosses
adapter versions, which the reader should know and the tool should not refuse over. An adapter
past its `expires_on` is likewise a finding, mirroring `scan`.

Exit codes, aligned with `verify`: `0` when every classified thing is `IN_PLACE` and nothing was
found; `1` when any state is not `IN_PLACE` or any finding was raised; `2` a tool error — an
unreadable or invalid ledger, an invalid adapter.

## Previewing a rollback with `rollback-preview`

```text
python assets/scripts/dashboard.py rollback-preview <path-to-ledger.json> RUN-YYYY-NNN
                                                    [--project PATH] [--adapter FILE]
                                                    [--user-config PATH]
```

`rollback-preview` answers one question before anyone acts on it: if this RUN were rolled back
now, what would actually be restored? It loads the ledger, finds the named RUN record, classifies
that run's targets with `drift`'s classifier — same code, not similar code, because a second
classifier would eventually disagree about the very states this report is built from — and
verifies the recorded backup by recomputing its digest with the machinery `verify` already has.
The backup's recorded `verified` flag is the run's own claim about itself, and the preview
recomputes rather than believes it. Like the other commands it is read-only, and here that is the
entire point: a preview that wrote anything would be lying about its name.

All four sets are always present in the report, an empty one as `[]`:

1. **`will_be_restored`** — targets `IN_PLACE` under a verified backup that proves their
   recovery: the backup's digest is the target's own `before_digest` (the backup is, byte for
   byte, what the target held), or the target has no `before_digest` (the run created it, and
   rolling back removes it).
2. **`will_not_change`** — targets already `REVERTED`.
3. **`cannot_be_restored`** — targets `DRIFTED` (restoring would destroy a later, unrelated
   edit), `MISSING`, or `UNVERIFIABLE`, each carrying its state as the reason; and, under a
   backup that failed verification, the `IN_PLACE` targets too, carrying the backup's failure
   reason — intact and unrestorable, because the backup is what there is to restore *from*;
   and, under a verified backup, the `IN_PLACE` targets it does not prove, with the reason
   `recovery_unverified`. A backup's digest proves the backup file is the one recorded, never
   what it holds: a backup that bundles several files proves no target's recovery, and the
   preview says so on stderr instead of promising it.
   The three target sets partition the run's targets: every target appears in exactly one,
   whatever the backup did.
4. **`residual_effects`** — every non-null `residual_effect` on the run's targets, verbatim: the
   tool cannot undo an installed dependency or a published artifact, and the preview's job is to
   make sure nobody believes otherwise.

The health indicator is one of `HEALTHY`, `AT_RISK`, or `BROKEN`:

| Indicator | Condition |
|---|---|
| `HEALTHY` | the backup verifies and proves every target's recovery, every target is `IN_PLACE`, and no residual effects exist |
| `AT_RISK` | the backup verifies, but at least one target is not `IN_PLACE`, or residual effects exist, or a target's recovery is unverified (`recovery_unverified`) |
| `BROKEN` | the backup is missing, unreadable, or its digest mismatches the recorded one |

`BROKEN` is decided first, because a backup that cannot be trusted makes every other promise
moot, and it short-circuits nothing else: the four sets are still computed and reported, because
the reader deciding what to do next is entitled to the target states either way.

The design spec's indicator table, read literally, leaves one run unclassified: backup verified,
a target `MISSING`, `UNVERIFIABLE`, or already `REVERTED`, nothing `DRIFTED`, no residuals. That
run is `AT_RISK`, by the same rationale that fills the third set above: a rollback that cannot
restore everything is at risk, and a run whose targets all reverted has nothing left to restore,
so calling it `HEALTHY` would claim a rollback story it no longer has. That is why the `AT_RISK`
condition reads "not `IN_PLACE`" rather than "`DRIFTED`".

Exit codes: `0` for `HEALTHY`, `1` for `AT_RISK` or `BROKEN`, `2` a tool error — an unknown run
ID, an ID naming a record that is not a RUN, an unreadable or invalid ledger, an invalid adapter.
A CI gate can therefore refuse to proceed past a run whose rollback story has decayed.
