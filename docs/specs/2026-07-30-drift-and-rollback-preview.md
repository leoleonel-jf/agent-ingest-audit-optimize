# `drift` and `rollback-preview` (0.3.0)

Status: approved 2026-07-30 under standing autonomy
Target version: 0.3.0
Phase: the third of three increments toward the design spec's 0.3.0 — this one completes it

## 1. Where this sits

`docs/specs/2026-07-30-adapters-and-scan.md` §1 left one increment between 0.2.5 and the design
spec's 0.3.0 acceptance line. This is it. It delivers `drift` and `rollback-preview`, the two
commands design spec §10 and §11 define, and it resolves the three §18 questions marked
"Resolved in 0.3.0". When this ships, every acceptance criterion in design spec §16 for 0.3.0 is
met, and the version number 0.3.0 is earned rather than counted to.

The blocking design question, recorded in `references/LEDGER.md` ("What a baseline does not
cover") and in the 2026-07-30 handoff, was per-subsystem precedence: `drift` was said to need an
ordering that exists nowhere in the shipped data. §3.1 resolves it. The resolution is smaller than
the gap suggested, and the reason is a fact the 0.2.5 code already recorded:
`ledgerlib/scan.py` — every baseline item's digest is the digest of the **file's bytes**, never of
its own parsed value. Drift classification is therefore pure digest mechanics and needs no
precedence at all. Precedence is needed only to say whether a drifted item *matters*, and that is
an annotation, not a classification.

## 2. What comes due now

- Design spec §10: the five-state classification of run targets and baseline items.
- Design spec §11: the four-set rollback preview and the three-value health indicator.
- The precedence ordering `references/LEDGER.md` promised `drift` would need "from somewhere".
- Design spec §18, three questions: Codex paths, subagent ledger write authority, merge driver.
- Two evaluation additions from §17: externally modified → `DRIFTED`, drifted target → not
  restorable in preview.

`docs/research/2026-07-30-client-configuration-paths.md` remains the verified input for every
client fact in this spec. It expires 2026-10-28, and everything derived from it inherits that
expiry.

## 3. Design

### 3.1 Precedence is declared data, and most kinds have no winner

The gap as recorded: "Settings and skills resolve in different orders inside one client … a single
'which layer wins' answer computed at scan time would be wrong for half the kinds. The adapter
format has nowhere to state an ordering, so `drift` will need that ordering from somewhere."

The resolution starts from what the research actually found, which is stronger than "different
orders": for half the kinds, **"which layer wins" is not a well-formed question.** Claude Code
permission rules merge across scopes — nothing shadows anything. Instruction files concatenate,
managed → user → project, and every file in the chain is live. Settings values resolve per key
across a file chain, so a whole-file item cannot name a winner even in principle. Only
whole-entry-by-name kinds — an MCP server, a skill — have shadowing an item-granularity tool can
state truthfully.

So the adapter format gains one optional top-level field, `resolution`: a map from `kind` to a
declaration of how that client resolves that kind across layers.

```json
"resolution": {
  "mcp-server":       { "mode": "override",     "order": ["project", "user"] },
  "skill":            { "mode": "override",     "order": ["user", "project"] },
  "instruction-file": { "mode": "concatenate" },
  "permission-rule":  { "mode": "merge" },
  "model-setting":    { "mode": "key-override", "order": ["project", "user"] },
  "env-var-name":     { "mode": "key-override", "order": ["project", "user"] }
}
```

The four modes, and what `drift` may do under each:

| Mode | Meaning | What `drift` computes |
|---|---|---|
| `override` | A same-kind, same-name item at an earlier scope shadows one at a later scope, whole | A winner: `effective` / `shadowed_by` annotations |
| `key-override` | Layers resolve per key inside parsed documents; item granularity cannot rank files | No winner. The declared chain is reported as context |
| `merge` | Every layer contributes; nothing shadows | No winner. The mode itself is the answer |
| `concatenate` | Layers are read in a defined order; all are live | No winner. The mode itself is the answer |

A kind absent from `resolution` is **undeclared**, and `drift` reports exactly that. Undeclared is
not a defect: it is the honest state for a kind whose resolution the research did not verify.
Claude Code hooks, agents, and commands ship undeclared in this increment for precisely that
reason — no primary source in the research document states their cross-scope behaviour, and this
project does not ship an ordering nobody verified.

Validation, in `ledgerlib/adapters.py` where adapter validation already lives:

- every key of `resolution` must be a valid baseline item kind;
- `mode` must be one of the four; anything else is a refusal, not a skip;
- `order` is required under `override` and `key-override` and forbidden under `merge` and
  `concatenate`;
- every scope named in an `order` must be a scope some probe of that kind actually declares, and
  every scope that kind's probes declare must appear in the `order` — an ordering that cannot rank
  all the items it will meet is refused at load, when the author can still fix it, not at drift
  time.

`order` is highest-precedence first. It ranks the scope vocabulary the adapter itself uses —
`user`, `project`, `system` in the shipped files — and claims nothing about layers the adapter
does not probe. The claude-code adapter's `mcp-server` order is `["project", "user"]`, which is
the research's local → project → user chain restricted to what the probes see: the `/mcpServers`
pointer into `$HOME/.claude.json` selects the file's top-level, user-scope servers only, so
local-scope servers (which live under per-project keys deeper in that file) are outside the
baseline and outside the ordering alike. The research's full chains are quoted in comments-free
adapter data by being restricted to probed scopes; the unrestricted chains stay in the research
document, which the `expires_on` date already ties the adapters to.

Codex declares `skill` as `override` `["project", "user", "system"]` (the research's repository →
user → admin → system, restricted: no admin scope is probed), `instruction-file` as `concatenate`,
and `model-setting` as `key-override` `["project", "user", "system"]`. The generic adapter, which
probes nothing, declares nothing.

`adapter_version` in all three shipped adapters becomes 2. A baseline captured at version 1 is
still comparable — item digests are file digests and the anchors did not move — and `drift`
reports the version difference as a finding rather than refusing or staying silent about it.

This closes the LEDGER.md gap on the terms the gap itself set: the ordering now exists in shipped
data, it lives beside the probes it ranks, it carries the research expiry, and it cannot claim a
winner for a kind whose semantics do not have one.

### 3.2 `drift`

```
dashboard.py drift LEDGER [--project PATH] [--user-config PATH] [--adapter PATH]
```

Read-only, like `scan`: it writes no file anywhere and emits one JSON report on stdout. It reads
the ledger named as an argument, re-resolves each recorded anchor against the current environment,
recomputes file digests, and classifies.

**Anchor resolution.** Baseline entries name their `client`; the ledger's top-level `client` names
the client for run targets. Adapter selection reuses the 0.2.5 machinery unchanged — bundled
adapters by client name, a user adapter overriding on the same terms, `--adapter` overriding
selection entirely — because anchor roots (`$USER_CONFIG` candidates above all) are adapter data
and `drift` does not get a second, private resolver. `--project` names the `$PROJECT` root exactly
as it does for `scan`; unset, it is the working directory. An anchor that cannot be resolved —
`$SYSTEM_CONFIG` on Windows, a `$USER_CONFIG` with no resolving candidate — makes its items
`UNVERIFIABLE` with a reason, never an error: the environment being unreadable is a finding about
the environment, not a crash in the tool.

**Classification of a baseline item.** The recorded state and digest pair with the current file:

| Recorded | Current | State |
|---|---|---|
| `present`, digest D | file exists, digest D | `IN_PLACE` |
| `present`, digest D | file exists, digest ≠ D | `DRIFTED` |
| `present`, digest D | file gone | `MISSING` |
| `not_present` | still absent | `IN_PLACE` |
| `not_present` | file exists now | `DRIFTED` |
| `present`, digest null (unreadable at scan) | any | `UNVERIFIABLE` |
| any | unreadable now | `UNVERIFIABLE`, with the reason |

A recorded absence that holds is `IN_PLACE` — the baseline recorded that it looked and found
nothing, and nothing is still there. A file appearing where none was is `DRIFTED`, and it is one
of the strongest drift signals there is: configuration arriving from outside. `REVERTED` cannot
occur for a baseline item — there is no before/after pair to revert between — and the report does
not manufacture one.

**Classification of a run target** follows design spec §10's table literally: current digest
equals `after_digest` → `IN_PLACE`; equals `before_digest` → `REVERTED`; equals neither →
`DRIFTED`; target path gone → `MISSING`; no digest recorded or path unreadable → `UNVERIFIABLE`.

**Resolution annotations.** For every set of baseline items sharing (kind, name) across more than
one scope, the report attaches the adapter's declared resolution. Under `override`, the item at
the earliest scope in `order` is marked `effective` and the others `shadowed_by: <scope>`. Under
`key-override`, `merge`, and `concatenate`, the items are marked with the mode and, where an
`order` exists, the chain — context, not judgment. Undeclared kinds are marked
`resolution: "undeclared"`. The annotation changes no classification: a shadowed item that drifted
is still `DRIFTED`, because shadowing is a fact about today's layering and the reader deciding
what to do about the drift is entitled to both facts.

**Adapter version drift.** A baseline whose `adapter_version` differs from the selected adapter's
is reported as a finding on the entry; items are still classified. An adapter past its
`expires_on` is likewise a finding, mirroring `scan`.

**Digest semantics are inherited, not reimplemented.** An item digest is the file's bytes; a
glob-derived item re-resolves to its recorded per-file anchor. The per-value digests inside
redacted markers are *not* recomputed by `drift` in this increment: doing so would re-run parse
and redaction against the live file, and the file-level digest already answers "did this file
change" — which is the classification contract. The finer answer ("this server's token changed,
that one's is gone") remains available to a reader comparing two baselines, which is `scan`'s job
to produce, not `drift`'s to duplicate.

**Exit codes**, aligned with `verify`: `0` when every classified thing is `IN_PLACE`, `1` when
anything is `DRIFTED`, `REVERTED`, `MISSING`, or `UNVERIFIABLE`, or any finding was raised, `2` on
tool error — an unreadable ledger, an invalid adapter, an invalid ledger.

### 3.3 `rollback-preview`

```
dashboard.py rollback-preview LEDGER RUN-ID [--project PATH] [--user-config PATH] [--adapter PATH]
```

Read-only; one JSON report on stdout; performs no writes, ever — the design spec's "modeled on an
infrastructure plan" is a statement about honesty of scope, and a preview that wrote anything
would be lying about its name.

It loads the ledger, finds the named `RUN` record (a missing or non-RUN ID is a tool error, exit
`2`), classifies that run's targets exactly as `drift` does — same code, not similar code — and
verifies the backup: the recorded `backup.digest` is recomputed from the backup path and compared,
reusing the machinery `verify` already has. The four sets of design spec §11, all four always
present in the report even when empty:

1. **`will_be_restored`** — targets `IN_PLACE` with a verified backup.
2. **`will_not_change`** — targets already `REVERTED`.
3. **`cannot_be_restored`** — targets `DRIFTED` (restoring would destroy a later, unrelated
   edit), `MISSING`, or `UNVERIFIABLE`, each with its state as the reason.
4. **`residual_effects`** — every non-null `residual_effect` on the run's targets, verbatim.
   The tool cannot undo an installed dependency or a published artifact, and the preview's job is
   to make sure nobody believes otherwise.

The health indicator derives mechanically: `BROKEN` when the backup is missing, unreadable, or its
digest mismatches — a backup that cannot be trusted makes every other promise moot, so it is
checked first and short-circuits nothing else (the sets are still reported). `AT_RISK` when the
backup verifies but any target is `DRIFTED` or any residual effect exists. `HEALTHY` when the
backup verifies, every target is `IN_PLACE`, and no residual effects exist.

Design spec §11's table, read literally, leaves one run unclassified: backup verified, a target
`MISSING` or `UNVERIFIABLE`, nothing `DRIFTED`, no residuals — not `HEALTHY` (a target is not
`IN_PLACE`), not `AT_RISK` (nothing drifted, no residuals), not `BROKEN` (the backup verifies).
This spec closes the gap as `AT_RISK`: a rollback that cannot restore everything is at risk by
the same rationale that puts those targets in `cannot_be_restored`. The condition column for
`AT_RISK` is therefore "backup verified but at least one target not `IN_PLACE`, or residual
effects exist", and `REVERTED` targets alone do not disturb `HEALTHY`'s spirit but do disturb its
letter — a run whose targets all reverted has nothing left to restore, and reporting it `HEALTHY`
would claim a rollback story it no longer has, so `REVERTED` counts as not-`IN_PLACE` here too.

Exit codes: `0` for `HEALTHY`, `1` for `AT_RISK` or `BROKEN`, `2` for tool error. A CI gate can
therefore refuse to proceed past a run whose rollback story has decayed.

### 3.4 The §18 questions, resolved

**Exact Codex configuration paths.** Resolved by
`docs/research/2026-07-30-client-configuration-paths.md`, verified against first-party
documentation, shipped in `codex.json` at 0.2.5. Time-limited like all evidence: the research and
the adapters expire 2026-10-28, and the expiry is machine-checked at scan and drift time. Nothing
further ships in this increment.

**Whether a delegating client can pass ledger write authority to a subagent safely.** **No.** The
ledger has a single writer: the delegating agent holds the pen, allocates IDs, and writes entries;
subagents return structured findings and never touch `ledger.json`. Three reasons, each
sufficient. ID allocation is a cross-scope invariant (design spec §8) and two writers race on
`sequences` with no coordination mechanism the format provides. Authorization quotes (§7.4) record
the *user's* words to the *delegating* agent — a subagent holds no authorization to record. And
the 0.2.2 path boundary argument applies to authority as it does to paths: a capability that
arrives as content (a prompt) rather than as an argument (the user's own instruction) is not a
capability, it is data. `SKILL.md`'s delegation section already forbids delegating ledger writes
implicitly; this makes it explicit and closes the question.

**Whether project ledgers should carry a merge driver for git conflicts on `ledger.json`.**
**No merge driver ships.** A git merge driver is executable configuration installed per-clone
(`.gitattributes` names it, but each user must define the driver in their git config); a plugin
that asks users to install merge tooling as a precondition for a governance file has inverted its
risk story. The single-writer rule above makes concurrent divergence rare by construction, and the
JSON structure makes a conflicted file loudly invalid rather than quietly wrong — `verify` exits
`2` on a file git left conflict markers in. What ships instead is a documented recovery procedure
in `references/LEDGER.md`: take both sides, `verify` each, re-allocate colliding IDs from the
authority, and re-run `verify` on the union. A backlog entry records the decision with the revisit
trigger "a real ledger.json merge conflict occurs in a multi-writer project", because the right
time to build merge tooling is when reality demonstrates the need the design currently denies.

### 3.5 `SKILL.md` and `references/LEDGER.md` changes

- `SKILL.md`: the drift and rollback-preview commands enter the workflow — a drift check before
  proposing changes to an environment with a baseline, a rollback preview before and after any
  `RUN` rollback discussion; the subagent ledger-write prohibition becomes explicit.
- `references/LEDGER.md`: the "Per-subsystem precedence is not expressible" paragraph is rewritten
  to describe the `resolution` field and what `drift` does and does not compute; the merge-conflict
  recovery procedure lands; the "What a baseline does not cover" list drops gap 4 and keeps the
  other six, which remain true.
- `PRIVACY.md`: `drift` and `rollback-preview` read the same files `scan` reads plus backup
  directories, and write nothing; the report contains digests, states, and recorded ledger data
  only.

## 4. Scope

In scope: the `resolution` field in `adapter.schema.json` and its validation; resolution data in
the three shipped adapters; `adapter_version` 2; `ledgerlib/drift.py`; `ledgerlib/rollback.py`;
both CLI commands; the §18 resolutions and their documentation; tests for all of it; the two §17
evaluation additions; the 0.3.0 release.

Out of scope: `build` and the dashboard (0.4.0); baseline-to-baseline comparison; recomputing
redacted value digests at drift time; writing into `ledger.json` from any command — `drift` and
`rollback-preview` are read-only like everything before them; an eleventh `kind` for credential
files; hook-script digesting; managed-policy probes. The last three remain documented gaps in
`references/LEDGER.md`, still deliberate, still recorded.

## 5. Compatibility

Additive. No existing command changes behaviour. A version-1 adapter without `resolution` remains
valid — the field is optional, and its absence means every kind is undeclared, which `drift`
reports honestly. Ledgers written under 0.2.x validate unchanged. The two new commands are opt-in
by being new.

## 6. Acceptance

Design spec §16, 0.3.0, quoted and mapped:

> "a scan on a real environment produces a baseline with no sensitive value stored"

Held since 0.2.5 (`docs/validation/scan-dogfood-0.2.5.md`); re-demonstrated in this increment's
dogfood by writing the baseline into the live ledger.

> "an externally modified target is reported `DRIFTED`"

`drift` on this machine, against a captured baseline, with a controlled modification to a probed
project-scope file. Also a named test.

> "a rollback preview lists all four sets including residual effects"

`rollback-preview` on `RUN-2026-000` in the live ledger, plus tests covering each set non-empty.

> "a missing backup yields `BROKEN`"

A named test with a fixture ledger whose backup path does not exist; and the exit code is `1`.
