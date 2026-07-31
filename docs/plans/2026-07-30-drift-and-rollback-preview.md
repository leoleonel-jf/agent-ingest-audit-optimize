# `drift` and `rollback-preview` (0.3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two read-only commands that complete design spec §16's 0.3.0: `drift`, which re-resolves recorded anchors and classifies every run target and baseline item against the current environment, and `rollback-preview`, which reports the four sets and the health indicator for one `RUN`. Ship the `resolution` field that closes the per-subsystem precedence gap as declared adapter data. Resolve the three §18 questions. Release 0.3.0.

**Architecture:** Two new modules join `ledgerlib/`: `drift.py` (anchor re-resolution, digest recomputation, five-state classification, resolution annotations) and `rollback.py` (backup verification, the four sets, the indicator — reusing `drift.py`'s classifier, same code not similar code). `adapters.py` grows `resolution` validation. Both commands write nothing but stdout/stderr.

**Tech Stack:** Python 3.10+, standard library only. `unittest`.

**Spec:** `docs/specs/2026-07-30-drift-and-rollback-preview.md`
**Design spec sections implemented:** §10 in full, §11 in full, §16 (0.3.0 acceptance), §17 (two eval additions), §18 (three resolutions).

## Global Constraints

- No third-party dependency. Standard library only. Tests are `unittest`.
- `drift` and `rollback-preview` are read-only: no file written, no directory created, nothing executed. The write-refusal test pattern from `scan` applies to both.
- Every path re-resolved from ledger data goes through `resolve_anchored` before it is opened. A ledger is content; its anchors earn dereference only because §10/§11 sanction exactly that, and only under the path-safety layer.
- Classification changes never depend on resolution annotations, and annotations never change a classification.
- Every finding message interpolating ledger or adapter content uses `!r`.
- Every new schema rule needs a matching runtime check and an agreement test failing in both directions.
- **Every task ends in an ablation step.** Delete the code, run the suite, name the test that fails, restore, report verbatim. A test that passes with its target deleted guards nothing.
- `.claude-plugin/plugin.json` → `version` is the single source of truth. Target `0.3.0`. Tags lightweight.
- This repository's own ledger is untracked and must never be staged. The dogfood task writes to it deliberately and stages nothing.

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `.../assets/scripts/ledgerlib/drift.py` | Anchor re-resolution, classification, annotations, `drift_command` | Create |
| `.../assets/scripts/ledgerlib/rollback.py` | Backup verification, four sets, indicator, `rollback_preview_command` | Create |
| `.../assets/scripts/ledgerlib/adapters.py` | `resolution` validation | Modify |
| `.../assets/scripts/ledgerlib/constants.py` | `DRIFT_STATES`, `RESOLUTION_MODES`, `ROLLBACK_INDICATORS` | Modify |
| `.../assets/scripts/dashboard.py` | Two subcommands, re-exports | Modify |
| `.../assets/schemas/adapter.schema.json` | The `resolution` field | Modify |
| `.../assets/adapters/{claude-code,codex,generic}.json` | Resolution data, `adapter_version` 2 | Modify |
| `.../references/LEDGER.md` | `drift`, `rollback-preview`, resolution, merge-conflict recovery; gap 4 rewritten | Modify |
| `.../SKILL.md` | Workflow integration; explicit subagent ledger-write prohibition | Modify |
| `.../PRIVACY.md` | What the two commands read; that they write nothing | Modify |
| `dashboard/tests/test_drift.py`, `test_rollback.py` | New suites | Create |
| `dashboard/tests/test_adapters.py` | `resolution` validation cases | Modify |
| `evals/suite.json` | §17: externally modified → `DRIFTED`; drifted target → not restorable | Modify |
| `docs/validation/drift-dogfood-0.3.0.md` | The dogfood record | Create |
| `README.md`, `CHANGELOG.md`, version pins, `docs/releases/v0.3.0.md`, `dist/` | The release | Modify / Create |

---

### Task 1: The `resolution` field — schema and validation

**Files:** `assets/schemas/adapter.schema.json`; `ledgerlib/adapters.py`; `ledgerlib/constants.py`; `dashboard/tests/test_adapters.py`.

**Interfaces:**
- Produces: `RESOLUTION_MODES = {"override", "key-override", "merge", "concatenate"}`; `validate_adapter` findings for every malformed `resolution`.

- [ ] **Step 1: Write the failing tests**

- an adapter without `resolution` validates — the field is optional and version-1 adapters stay valid;
- a `resolution` key that is not a baseline item kind is refused, naming the key `!r`;
- a mode outside the four is refused, never skipped;
- `order` missing under `override` or `key-override` is refused; `order` present under `merge` or `concatenate` is refused;
- an `order` naming a scope no probe of that kind declares is refused;
- an `order` omitting a scope some probe of that kind declares is refused — an ordering that cannot rank every item it will meet fails at load, not at drift time;
- an `order` with a duplicate scope is refused;
- schema/runtime agreement: every property name the schema's `resolution` sub-schema declares appears in `validate_adapter`'s checks and vice versa, failing in both directions.

- [ ] **Step 2: Run the tests to verify they fail.**
- [ ] **Step 3: Write the implementation.**
- [ ] **Step 4: Run the tests to verify they pass.**
- [ ] **Step 5: Ablate**

Delete the order-covers-all-scopes check. Name the test that fails. Restore. Then delete the mode whitelist. Name the test that fails. Restore, report both verbatim.

---

### Task 2: Resolution data in the shipped adapters, `adapter_version` 2

**Files:** the three adapter files; `dashboard/tests/test_adapters.py`.

Sequential on Task 1.

- [ ] **Step 1: Write the failing tests**

- all three shipped adapters validate under the Task 1 rules;
- claude-code declares exactly: `mcp-server` override `["project", "user"]`; `skill` override `["user", "project"]` — the inversion the research warns about, asserted as data; `instruction-file` concatenate; `permission-rule` merge; `model-setting` and `env-var-name` key-override `["project", "user"]`;
- claude-code declares **nothing** for `hook`, `agent`, `command`, `plugin` — undeclared is the recorded state for unverified semantics, and a test pins it so nobody "helpfully" adds an ordering without a source;
- codex declares exactly: `skill` override `["project", "user", "system"]`; `instruction-file` concatenate; `model-setting` key-override `["project", "user", "system"]`; nothing else;
- generic declares no `resolution`;
- all three carry `adapter_version` 2.

- [ ] **Step 2: Run, confirm they fail.**
- [ ] **Step 3: Write the adapter data.**
- [ ] **Step 4: Run, confirm they pass.**
- [ ] **Step 5: Ablate**

Swap claude-code's `skill` order to `["project", "user"]` — the exact mistake the settings-order habit produces. Name the test that fails. Restore, report verbatim.

---

### Task 3: `drift` classification — baseline items and run targets

**Files:** `ledgerlib/drift.py`; `ledgerlib/constants.py`; `dashboard/tests/test_drift.py`.

May run parallel to Tasks 1–2; touches no adapter code.

**Interfaces:**
- Produces: `DRIFT_STATES = {"IN_PLACE", "DRIFTED", "REVERTED", "MISSING", "UNVERIFIABLE"}`; `classify_item(item, resolved) -> tuple[state, reason|None]`; `classify_target(target, resolved) -> tuple[state, reason|None]`; `drift_report(ledger, ...) -> tuple[dict, list[str], int]`.

- [ ] **Step 1: Write the failing tests**

Baseline items, one test per spec table row:
- `present` + digest matches → `IN_PLACE`;
- `present` + digest differs → `DRIFTED`;
- `present` + file gone → `MISSING`;
- `not_present` + still absent → `IN_PLACE` — the recorded absence held;
- `not_present` + file exists now → `DRIFTED` — configuration arrived from outside;
- `present` with null digest (unreadable at scan) → `UNVERIFIABLE` with reason;
- unreadable now (permission patch) → `UNVERIFIABLE` with reason, never a crash;
- unresolvable anchor (`$SYSTEM_CONFIG` on Windows) → every item under it `UNVERIFIABLE` with reason, never an error.

Run targets, per design spec §10's table literally:
- current == `after_digest` → `IN_PLACE`; current == `before_digest` → `REVERTED`; equals neither → `DRIFTED`; path gone → `MISSING`; no digest recorded → `UNVERIFIABLE`;
- a target whose `before_digest` equals its `after_digest` and matches → `IN_PLACE`, not `REVERTED` — check `after` first, the tie means the change is intact.

Classification purity:
- classification is identical with and without any `resolution` data present — asserted by running the same fixture through both.

- [ ] **Step 2: Run, confirm they fail.**
- [ ] **Step 3: Write the implementation.** Re-resolution through `resolve_anchored` only; digest through `file_digest`.
- [ ] **Step 4: Run, confirm they pass.**
- [ ] **Step 5: Ablate**

Invert the not_present rules so an appearing file is `IN_PLACE`. Name the test that fails. Restore. Then swap the target check order so `before` is checked first; the tie test must fail. Restore, report both verbatim.

---

### Task 4: Resolution annotations

**Files:** `ledgerlib/drift.py`; `dashboard/tests/test_drift.py`.

Sequential on Tasks 2 and 3.

- [ ] **Step 1: Write the failing tests**

- two same-(kind, name) items at scopes `project` and `user`, kind declared override `["project", "user"]` → the project item is `effective`, the user item `shadowed_by: "project"`;
- same pair under `key-override` → both carry the mode and the chain, neither is `effective` — no winner is claimed;
- same pair under `merge` and under `concatenate` → the mode, nothing else;
- a kind with no declaration → `resolution: "undeclared"`;
- a shadowed item that drifted is still `DRIFTED` — annotation changes no classification;
- items unique to one scope get no shadowing annotation.

- [ ] **Step 2: Run, confirm they fail.**
- [ ] **Step 3: Write the implementation.**
- [ ] **Step 4: Run, confirm they pass.**
- [ ] **Step 5: Ablate**

Make `key-override` compute a winner — the overreach the mode exists to prevent. Name the test that fails. Restore, report verbatim.

---

### Task 5: The `drift` command — CLI, findings, exit codes

**Files:** `ledgerlib/drift.py`; `dashboard.py`; `dashboard/tests/test_drift.py`.

Sequential on Task 4.

- [ ] **Step 1: Write the failing tests**

- `dashboard.py drift LEDGER` emits one JSON report on stdout, findings on stderr;
- exit `0` when everything is `IN_PLACE`; `1` when any state is not `IN_PLACE` or any finding was raised; `2` on unreadable or invalid ledger, invalid adapter;
- adapter selection reuses `select_adapter` — `--adapter`, `--user-config`, `--project` behave as they do for `scan`, asserted through the CLI;
- a baseline whose `adapter_version` differs from the selected adapter's raises a finding and still classifies;
- an adapter past `expires_on` raises a finding, mirroring `scan`;
- **`drift` writes nothing:** the write-refusal patch from the `scan` suite, exit `0` on a clean fixture;
- the wiring test: the subcommand reaches `drift_report` through `main`, not only through direct calls.

- [ ] **Step 2: Run, confirm they fail.**
- [ ] **Step 3: Write the implementation.**
- [ ] **Step 4: Run, confirm they pass.**
- [ ] **Step 5: Ablate**

Delete the subcommand wiring from `main`, leaving `drift_report` intact; the CLI test must fail. Restore. Then delete the adapter-version finding; its test must fail. Restore, report both verbatim.

---

### Task 6: `rollback-preview`

**Files:** `ledgerlib/rollback.py`; `dashboard.py`; `dashboard/tests/test_rollback.py`.

Sequential on Task 3 (imports its classifier). May run parallel to Tasks 4–5.

**Interfaces:**
- Produces: `ROLLBACK_INDICATORS = {"HEALTHY", "AT_RISK", "BROKEN"}`; `rollback_preview(ledger, run_id, ...) -> tuple[dict, list[str], int]`; the subcommand.

- [ ] **Step 1: Write the failing tests**

- the report always contains all four sets, empty ones as `[]` — asserted on a run with every set empty but one, for each set in turn;
- a target `IN_PLACE` with verified backup → `will_be_restored`;
- a target `REVERTED` → `will_not_change`;
- targets `DRIFTED`, `MISSING`, `UNVERIFIABLE` → `cannot_be_restored`, each carrying its state as the reason;
- every non-null `residual_effect` appears verbatim in `residual_effects`;
- backup verification reuses the digest recomputation `verify` uses — asserted by patching it once and seeing both commands change behaviour;
- **a missing backup yields `BROKEN`** and exit `1` — the §16 acceptance criterion, as a named test;
- a backup whose digest mismatches → `BROKEN`; backup verified + a drifted target → `AT_RISK`; backup verified + residual effect → `AT_RISK`; backup verified, all `IN_PLACE`, no residuals → `HEALTHY`, exit `0`;
- `BROKEN` does not short-circuit the sets — they are still reported, asserted together with the indicator;
- an unknown run ID, or an ID naming a non-RUN record, → exit `2` naming the ID `!r`;
- classification comes from `drift.py`'s classifier — same code, asserted by patching it once and seeing both commands change;
- the write-refusal patch, and the wiring test through `main`.

- [ ] **Step 2: Run, confirm they fail.**
- [ ] **Step 3: Write the implementation.**
- [ ] **Step 4: Run, confirm they pass.**
- [ ] **Step 5: Ablate**

Make `BROKEN` short-circuit set reporting. Name the test that fails. Restore. Then drop `will_not_change` from the report — the always-four-sets test must fail. Restore, report both verbatim.

---

### Task 7: Documentation

**Files:** `references/LEDGER.md`, `SKILL.md`, `PRIVACY.md`, `README.md`; documentation tests in `dashboard/tests/test_dashboard.py`.

Sequential on Tasks 5–6. Anchor phrases must be unique — grep the file before writing each test.

- [ ] **Step 1: Write the failing documentation tests**

- `LEDGER.md` documents `drift`: arguments, the five states including both `not_present` rows, exit codes, read-only;
- `LEDGER.md` documents `rollback-preview`: the four sets, the indicator table, exit codes, read-only;
- `LEDGER.md` documents `resolution` field by field, the four modes, and that `drift` computes a winner only under `override`; agreement test between `validate_adapter`'s resolution checks and the documented field names, both directions;
- `LEDGER.md`'s "What a baseline does not cover" no longer contains the per-subsystem-precedence gap and still contains the other six — asserted in both directions;
- `LEDGER.md` documents the merge-conflict recovery procedure: verify both sides, re-allocate colliding IDs, verify the union;
- `SKILL.md` states the subagent ledger-write prohibition in so many words: subagents return findings, the delegating agent holds the pen;
- `SKILL.md` places `drift` before proposing changes where a baseline exists, and `rollback-preview` in the rollback workflow;
- `PRIVACY.md` covers both commands: what they read, that they write nothing, that reports carry digests and recorded ledger data only.

- [ ] **Step 2: Run, confirm they fail.**
- [ ] **Step 3: Write the documentation.**
- [ ] **Step 4: Run, confirm they pass.**
- [ ] **Step 5: Ablate**

Delete each documented paragraph in turn; its own test must fail. A test surviving its paragraph's deletion found the phrase elsewhere — change the phrase. Report verbatim.

---

### Task 8: Evaluation additions

**Files:** `evals/suite.json`; `evals/tests/` as the existing pattern requires.

Sequential on Tasks 5–6.

- [ ] **Step 1** Add the two §17 cases in the suite's existing shape: an externally modified file is classified `DRIFTED`, not `IN_PLACE`; a rollback preview on a drifted target reports it as not restorable.
- [ ] **Step 2** Run the evals suite green.
- [ ] **Step 3: Ablate** — break each behaviour in `drift.py`/`rollback.py` in turn and confirm the corresponding eval fails. Restore, report verbatim.

---

### Task 9: Dogfood on this machine

**Files:** `.agent-audit/ledger.json` (untracked, deliberately); `docs/validation/drift-dogfood-0.3.0.md`.

Sequential on everything above. Single-writer sequence — do not delegate, do not parallelise.

- [ ] **Step 1** Allocate a `BASE-` ID from the ledger's authority, run `scan --id BASE-… --project .`, read the output by eye — no secret value anywhere — and write the entry into `.agent-audit/ledger.json`'s `baselines[]`. Run `verify`: exit `0`. This is the §16 criterion "a scan on a real environment produces a baseline with no sensitive value stored", now demonstrated end-to-end into a live ledger.
- [ ] **Step 2** Run `drift` immediately: expect `IN_PLACE` across the board, or document exactly what already moved and why.
- [ ] **Step 3** Modify a probed project-scope file (add a trailing newline to `./CLAUDE.md` or a scratch project fixture — never a user-scope credential-adjacent file), re-run `drift`, confirm `DRIFTED` for that item and only that item. Revert the modification, re-run, confirm `IN_PLACE`.
- [ ] **Step 4** Run `rollback-preview` against `RUN-2026-000`. Read all four sets. Record the indicator and whether it is honest about that run.
- [ ] **Step 5** Write `docs/validation/drift-dogfood-0.3.0.md`: what was run, what was found, what was wrong, what was right. Findings that survive triage become ledger backlog entries or fixes before release.
- [ ] **Step 6** Add the merge-driver backlog entry to the live ledger with trigger "a real ledger.json merge conflict occurs in a multi-writer project". Run `verify`: exit `0`.

---

### Task 10: Release 0.3.0

**Files:** version pins, `CHANGELOG.md`, `docs/releases/v0.3.0.md`, `dist/`.

Single-writer sequence, one context.

- [ ] **Step 1** Full suite, all three test directories, green. This repository's own ledger exits `0`.
- [ ] **Step 2** Bump all version pins to `0.3.0`; run the version-consistency guard.
- [ ] **Step 3** `CHANGELOG.md` and `docs/releases/v0.3.0.md` in house style — what changed and why it was wrong before. Name the precedence gap as closed by declared data, the §18 resolutions, and the research expiry the resolution data inherits.
- [ ] **Step 4** Build the archives, record checksums, checksum test green.
- [ ] **Step 5** Branch, PR, merge, tag `v0.3.0` (lightweight), publish the release.
- [ ] **Step 6** Extract the published zip somewhere clean; run `drift --help`, `rollback-preview --help`, and `verify` against a fixture.

---

## Delegation

Per design spec §19: one task per subagent, verbatim ablation output required in every report. Task 3 may run parallel to Tasks 1–2. Task 4 waits on 2 and 3. Task 6 waits on 3 and may run parallel to 4–5. Tasks 7–8 wait on 5–6. Tasks 9 and 10 are single-writer sequences and stay in the delegating context. The subagent ledger-write prohibition this very release codifies applies to its own build: no subagent touches `.agent-audit/ledger.json`.
