# Ledger: lockfile, hash chain and merge recovery

Three optional tools around the ledger file itself. Part of the ledger reference;
[LEDGER.md](LEDGER.md) holds the index.

## Pinning the supply chain: `agent.lock`

```text
python assets/scripts/dashboard.py lock <ledger> --from BASE-YYYY-NNN --out agent.lock
python assets/scripts/dashboard.py lock <ledger> --check agent.lock
```

A baseline answers **"what was here that day"** — an observation, dated and immutable. A lockfile
answers **"what should be here"** — declared intent, small enough to read in a diff, committed to
git, and checked by CI. The difference is the one between a `pip freeze` filed in a log and a
`requirements.lock` in the repository.

`--check` compares the lockfile against the baseline it names and **reads nothing from the
environment**. Verifying against the disk as it is *now* already has a command — `drift` — and
giving one question two answers is worse than either. Run both when you want both.

Differences use a closed vocabulary: `added`, `removed`, `changed` (a different digest),
`state_changed`. Exit codes: `0` identical, `1` any difference, `2` a tool error.

Only kinds an adapter marks `lockable` are pinned — the ones naming an installable artifact
(`skill`, `plugin`, `mcp-server`, `agent`, `command`, `hook`). Instruction files, model settings,
permission rules and environment variable names are deliberately left out: a lockfile that fails
CI because somebody edited `CLAUDE.md` is one somebody switches off in the first week.

A lockfile carries no timestamp and no absolute path, so two machines with the same configuration
produce identical bytes. A mismatched `client` or `platform` is refused outright rather than
compared, because comparing across either would report every entry as both added and removed.

**What a green `--check` does and does not say.** It says nothing changed since the pin. It says
nothing about whether what was pinned is trustworthy — that is what evidence, review and the
audit workflow are for.

## Tamper-evidence: the hash chain

Each entry in `records[]` may carry a `chain` object — `index`, `previous`, and `digest` — where
`digest` is the SHA-256 of that record's canonical JSON (sorted keys, compact separators) with
`chain.digest` itself removed, and `index`/`previous` deliberately inside the hash, because they
are what bind a record to its position.

```text
python assets/scripts/dashboard.py verify <ledger> --chain
python assets/scripts/dashboard.py chain <ledger> --seal
python assets/scripts/dashboard.py chain <ledger> --head
```

**What this is, precisely.** Tamper-**evident**, not tamper-proof:

| Scenario | Detected? |
|---|---|
| Editing a record | yes — its digest no longer matches |
| Deleting a record from the middle | yes — the following record's `index`/`previous` no longer line up |
| Reordering records | yes — `index` and `previous` are inside the hash |
| Truncating the end of the chain | only with an external anchor |
| Rewriting everything and re-sealing | **no** — without an external anchor |

The last row is the reason `chain --head` exists. It prints the head digest and nothing else, so
the value can be recorded **outside** the ledger — a commit message, a tag, another system — and
`verify --chain --expect-head <digest>` compares against it. There is no key and no service: it is
one number kept somewhere the ledger cannot reach, and it is what moves "they rewrote everything"
from undetectable to detectable. A tool that claimed more than this table would be lying about the
one thing it exists to be trusted about.

Nothing here is access control. It does not stop a write; it makes one visible.

**Compatibility.** A record with no `chain` is `unchained`, never invalid. Every ledger written
before this shipped is unchained, and `verify` stays silent about it unless `--chain` is passed —
turning existing records invalid would destroy exactly what this tool preserves. Indices count
over the sealed subsequence, so a partially sealed ledger verifies cleanly from its first sealed
record onward, which is the normal state right after migration.

**Sealing.** `chain --seal` writes `chain` onto records that lack it and leaves existing ones
alone, so it is byte-idempotent. It refuses a ledger that does not validate, and it refuses to
seal over a chain that is already broken — resealing would recompute the links and erase the
evidence, which is the one thing this command must never do. It preserves the file's indentation
and line endings, and writes through `os.replace`.

## Recovering `ledger.json` from a git merge conflict

No merge driver ships, and that is a decision rather than a gap in tooling: a git merge driver is
executable configuration every user must install per-clone, and a plugin that asks users to
install merge tooling as a precondition for a governance file has inverted its risk story. The
single-writer rule makes concurrent divergence rare by construction, and the JSON structure makes
a conflicted document loudly invalid rather than quietly wrong — `verify` exits `2` on a file git
left conflict markers in.

When a conflict does happen, recover in three steps:

1. **Verify both sides.** Take each side of the conflict whole — never the marker-riddled file —
   and run `verify` on each, so recovery starts from two documents that are individually sound.
2. **Re-allocate colliding identifiers from the authority.** Where both sides spent the same
   identifier on different things, request fresh identifiers from the global ID authority for one
   side's entries and rewrite every reference to them, exactly as provisional-ID reconciliation
   already does.
3. **Verify the union.** Merge the surviving entries into one document and run `verify` on it,
   together with every other reachable ledger, so the duplicate-identifier and sequence-floor
   checks confirm the collision is actually gone.
