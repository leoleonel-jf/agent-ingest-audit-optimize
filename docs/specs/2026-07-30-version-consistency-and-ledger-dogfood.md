# Version Consistency and Ledger Dogfood (0.2.1)

Status: approved 2026-07-30
Target version: 0.2.1

This design covers two pieces of work that share one release: closing the version-pin drift
that shipped with 0.2.0, and standing up this repository's own governance ledger for the first
time.

## 1. Why

### 1.1 A released version nobody can install through Codex

`.agents/plugins/marketplace.json` pins `plugins[0].source.ref` to `v0.1.3`. That file is the
OpenAI Codex marketplace manifest, documented at
<https://developers.openai.com/plugins/build/plugins> as `$REPO_ROOT/.agents/plugins/marketplace.json`,
with every key this repository uses — `interface.displayName`, `source.source: "url"`,
`policy.installation: AVAILABLE`, `policy.authentication: ON_INSTALL` — present in OpenAI's
published schema and in their reference repository `openai/plugins`. The consumer shipped in
`openai/codex` PR #21396, merged 2026-05-14. Verified 2026-07-30.

A pinned `ref` does not advance on its own, and `codex plugin marketplace upgrade` refreshes the
catalog rather than an installed plugin. The consequence is concrete: every new Codex install
resolves v0.1.3, and existing users never see 0.2.0. The release published on 2026-07-30 is
unreachable through that path.

Codex reads `.claude-plugin/marketplace.json` only for legacy compatibility, so it is not a
substitute.

### 1.2 Four version pins, two of them checked

`packaging/scripts/package_plugin.py:57-70` reads `.codex-plugin/plugin.json` and
`.claude-plugin/plugin.json` and asserts they carry the same non-empty semver. It never reads
either marketplace manifest. No test in `packaging/tests/test_package_plugin.py` asserts
anything about versions. The repository has no CI.

The 0.2.0 release therefore updated the three pins its checklist named
(`docs/plans/2026-07-29-ledger-0.2.0.md:2071`) and left four behind:

| Location | Value | Should be |
|---|---|---|
| `.agents/plugins/marketplace.json` → `plugins[0].source.ref` | `v0.1.3` | `v0.2.1` |
| `README.md:67` | `--ref v0.1.3` | `--ref v0.2.1` |
| `README.md:90` | `agent-ingest-audit-optimize-0.1.3-skill.zip` | `-0.2.1-skill.zip` |
| `docs/SUBMISSION.md:19` | `**Version:** 0.1.3` | `0.2.1` |

`docs/SUBMISSION.md:95` separately describes "a 24-case evaluation suite"; the suite has held 28
cases since 0.2.0.

The defect is not the four wrong values. It is that nothing fails when they are wrong. Fixing
the values without adding a check reproduces the same drift at 0.3.0.

### 1.3 No ledger of its own

0.2.0 shipped the ledger machinery — `references/LEDGER.md`, `assets/schemas/ledger.schema.json`,
and `assets/scripts/dashboard.py verify` — but the repository keeps no ledger. This is not a
rule violation: `SKILL.md:181` addresses an agent auditing a target environment, and spec §19.4
constrains subagent delegation, not bookkeeping. Standing one up is a choice, made for one
reason: `verify` has never run against a ledger that was written by hand for real work, only
against test fixtures.

## 2. Scope

In scope: the four stale pins, the check that keeps them aligned, the two missing release
documents, and a working two-scope ledger with records for this release.

Out of scope: CI, the 0.3.0 deferrals (anchor resolution spec §7.1, filesystem path safety spec
§13.6, splitting `dashboard.py` into a package), and any change to `verify` itself. If the
dogfood surfaces a `verify` defect, it is recorded and scheduled, not fixed here.

## 3. Part A — version consistency

### 3.1 Source of truth

`.claude-plugin/plugin.json` → `version` is the single source of truth. Every other pin derives
from it. It is chosen because `package_plugin.py` already reads it and because it is the manifest
the Claude Code marketplace consumes directly.

### 3.2 The check

A new test module under `packaging/tests/` asserts that each pin below agrees with the source of
truth. It is written failing first: run against the current tree at 0.2.0, it must report exactly
the four rows of §1.2 and nothing else.

| Pin | Expected form |
|---|---|
| `.codex-plugin/plugin.json` → `version` | equal to source |
| `.claude-plugin/marketplace.json` → `version` | equal to source |
| `.agents/plugins/marketplace.json` → `plugins[0].source.ref` | `v` + source |
| `README.md` → the `--ref vX.Y.Z` argument | `v` + source |
| `README.md` → the `.zip` release-asset filename | contains source |
| `docs/SUBMISSION.md` → the `**Version:**` line | equal to source |
| `CHANGELOG.md` → the first `## X.Y.Z` heading | equal to source |

Each pin is asserted separately, so a failure names the file that drifted rather than reporting
one opaque mismatch. Every path is resolved from the repository root, matching how
`package_plugin.py` locates its manifests.

The test reads `README.md` and `docs/SUBMISSION.md` with anchored regular expressions rather than
substring search, so an unrelated mention of an old version elsewhere in those files does not
satisfy or break the assertion.

### 3.3 Where the release checklist lives from now on

`packaging/README.md` gains a short section naming this test as the authoritative list of version
pins, replacing the per-plan checklists that omitted three files. No human re-checks seven
locations by hand.

The 0.2.0 plan document is closed and is not edited.

### 3.4 Release sequencing

`ref` may only name a tag that exists. The order is: bump every pin to 0.2.1 in the release
commit, merge, push the tag `v0.2.1` immediately, and only then treat the release as installable.
Between merge and tag push there is a window in which a Codex install would fail to resolve the
ref; keeping that window short is the reason the tag push follows the merge directly.

### 3.5 Tag style

Tag style is currently inconsistent: `v0.1.0`, `v0.1.1`, and `v0.2.0` are annotated; `v0.1.2` and
`v0.1.3` are lightweight. Codex's auto-upgrade compares `git ls-remote` output against the cloned
commit, and for an annotated tag those differ, so the marketplace re-clones on every pass
(`openai/codex` PR #17425, flagged P2, 2026-04). This wastes work but breaks nothing.

Decision: standardize on lightweight tags from `v0.2.1` onward. `v0.2.0` is published and is not
retagged.

### 3.6 Release documents

`docs/releases/v0.2.0.md` is missing and is written from the shipped CHANGELOG entry and release
notes. `docs/releases/v0.2.1.md` is written for this release. Both follow the existing
one-file-per-version convention.

## 4. Part B — the ledger dogfood

### 4.1 Layout

Global scope, at the Claude Code user configuration root:

```text
C:\Users\leole\.claude\agent-ingest-audit-optimize\
├── ledger.json
└── records/
```

Project scope, at the repository root:

```text
.agent-audit/
├── ledger.json
└── records/
```

`.agent-audit/` is added to `.gitignore`. Neither ledger is committed. This preserves the 0.1.2
decision that removed author-local record identifiers from public files so that fresh
installations start their own sequences.

`backups/` and `baseline/` are not created: nothing in this release writes either, and the layout
is a convention `verify` does not check.

### 4.2 The global ledger

`scope: "global"`, `id_authority: true`, `client: "claude-code"`, `adapter_version: 1`,
`language: "pt-BR"`, `created` and `updated` `2026-07-30`, all five `sequences` keys present, and
one `known_projects` entry for this repository with a real `sha256` of the project ledger,
`status: "OK"`, `last_seen: 2026-07-30`.

`records` is empty. Under the scope routing in `references/LEDGER.md`, every record in this
release is `project`-scoped and belongs to the project ledger; the global ledger is the
identifier authority and the project catalog, nothing more.

### 4.3 The project ledger

`scope: "project"`, `id_authority: false`, and `sequences` held at or above the highest number its
own records use, as `verify` requires of every ledger including one that allocates nothing.

Four records, each with evidence that was actually gathered:

| Type | Subject |
|---|---|
| `MATERIAL` | The OpenAI Codex plugin documentation researched on 2026-07-30 |
| `PROPOSAL` | The 0.2.1 change described in Part A |
| `ADR` | Electing `.claude-plugin/plugin.json` as the version source of truth |
| `RUN` | The authorized execution of the proposal |

Each record's `file` field points at a markdown document under the ledger's own `records/`
directory, following the convention in `references/LEDGER.md` — `records/PROP-2026-000.md` and so
on. Those four documents are written, not just referenced: a `file` field naming a document that
does not exist is the kind of gap `verify` cannot catch and the exercise is meant to surface.

The MATERIAL record's evidence item carries the documentation URL, `verified_on: 2026-07-30`,
`time_sensitive: true` — feature availability is always time sensitive per
`references/LEDGER.md` — and `expires_on: 2026-10-28`, the house 90-day default.

### 4.4 Honesty constraints on the RUN record

`references/LEDGER.md` states: never record a digest that was not computed, and never mark a
backup verified without reading it. Accordingly:

- each target's `before_digest` and `after_digest` is a `sha256` computed from the file at the
  moment of the change, never reconstructed;
- `backup` is `null`. Recoverability here is the preceding git commit, which the schema does not
  model as a backup object. `"backup"` is named in `self_reported`;
- `rollback.tested` is `NOT_TESTED` unless a revert is actually exercised, in which case it
  becomes `PASSED`;
- `authorization.quote` carries the authorization verbatim, in the language it was given.

### 4.5 Backlog

Two entries, both genuine non-adoptions:

| Classification | Entry | Revisit condition |
|---|---|---|
| `MONITOR` | Codex re-clones annotated-tag marketplaces on every auto-upgrade pass | `openai/codex` PR #17425 P2 resolved |
| `NEEDS MORE EVIDENCE` | Validating the marketplace manifest with `codex app-server generate-json-schema` | Codex CLI installed on this machine |

The 0.3.0 deferrals do not enter the backlog. The five backlog classifications all describe
findings that were **not** adopted; those items were adopted and scheduled, which the vocabulary
does not model. Recording them as `MONITOR` would be a misuse of the label.

### 4.6 Validation protocol

`verify` runs after every ledger write, with both ledgers passed in one invocation so the
cross-ledger checks execute:

```text
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify \
  "C:\Users\leole\.claude\agent-ingest-audit-optimize\ledger.json" \
  ".agent-audit/ledger.json"
```

Expected terminal state: exit `0`, no findings.

### 4.7 What gets committed

`docs/validation/ledger-dogfood-0.2.1.md` records what was created, what `verify` reported, the
exit codes observed, and any schema or usability friction the exercise surfaced.

It must not quote concrete record identifiers. Publishing author-local identifiers is what 0.1.2
deliberately removed from public files, and a validation record is a public file.

One friction is anticipated and will be confirmed or refuted by the exercise: `verify` checks
that `known_projects[].last_digest` has the shape `sha256:<64 hex>` but never that it matches the
project ledger it names, so the field can silently go stale. If confirmed, it is recorded as a
finding and scheduled — not fixed in this release.

## 5. Acceptance

| Criterion | Evidence |
|---|---|
| The version check fails on the pre-fix tree | The new test reports exactly the four pins of §1.2 |
| The version check passes on the fixed tree | Full `packaging/tests` run is green |
| Codex resolves the current release | `.agents/plugins/marketplace.json` ref equals the pushed tag |
| Both release documents exist | `docs/releases/v0.2.0.md` and `v0.2.1.md` present |
| The ledger validates | `verify` over both ledgers exits `0` |
| No ledger is committed | No `.agent-audit` path appears in `git status` after the writes |
| No author identifiers are published | `docs/validation/ledger-dogfood-0.2.1.md` contains no record id |
| Nothing regressed | dashboard, evals, and packaging suites green; suite valid; `dist` verified |

## 6. Risks

Standing up a global ledger under `~/.claude/` creates a file outside this repository that will
outlive this release and serve future projects. It holds no secrets — it records identifiers,
titles, classifications, and digests — but it is not disposable the way `.agent-audit/` is.

The version check hard-codes seven pin locations. A future release that introduces an eighth pin
without extending the test reproduces the drift in a new place. This is a smaller surface than
the current zero-coverage state, not a permanent fix.
