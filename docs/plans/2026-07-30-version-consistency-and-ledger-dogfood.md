# Version Consistency and Ledger Dogfood (0.2.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 0.2.1 with every version pin held aligned by a test, and stand up this repository's own two-scope governance ledger with real records for the release.

**Architecture:** A new `packaging/tests/test_version_consistency.py` elects `.claude-plugin/plugin.json` → `version` as the single source of truth and asserts six other pins derive from it, each in its own test method so a failure names the file that drifted. The four stale pins are then corrected as part of the 0.2.1 bump. Separately, an untracked ledger pair — global at the Claude Code configuration root, project at `.agent-audit/` — records this release as MATERIAL, PROPOSAL, ADR, and RUN, validated by `dashboard.py verify` over both ledgers in one invocation.

**Tech Stack:** Python 3.10+, standard library only. `unittest` (not pytest) — the repository's suites are discovered with `python -m unittest discover`.

**Spec:** `docs/specs/2026-07-30-version-consistency-and-ledger-dogfood.md`

## Global Constraints

- No third-party dependency may be introduced. Standard library only, in both the packaging tests and anything the ledger work runs.
- Tests are `unittest`, discovered with `python -m unittest discover -s <dir>/tests`. Do not introduce pytest.
- Every path is resolved from the repository root, matching `packaging/scripts/package_plugin.py`.
- `.claude-plugin/plugin.json` → `version` is the single source of truth for the version. Nothing else may be treated as authoritative.
- The target version for this release is `0.2.1`. Tags from `v0.2.1` onward are lightweight (`git tag v0.2.1`), never annotated.
- Neither ledger is ever committed. `.agent-audit/` is git-ignored, and the global ledger lives outside the repository.
- Never record a digest that was not computed. Never mark a backup verified without reading it. (`references/LEDGER.md`)
- `docs/validation/ledger-dogfood-0.2.1.md` must not contain any concrete record identifier.
- Free text in the ledger follows the user's working language (pt-BR). Operating states, status labels, classification labels, and record identifiers stay in canonical English.
- Do not edit `docs/plans/2026-07-29-ledger-0.2.0.md`. That plan is closed.

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `packaging/tests/test_version_consistency.py` | Asserts every version pin derives from the source of truth | Create |
| `.claude-plugin/plugin.json` | Source of truth for the version | Modify |
| `.codex-plugin/plugin.json` | Codex plugin manifest version | Modify |
| `.claude-plugin/marketplace.json` | Claude marketplace entry version | Modify |
| `.agents/plugins/marketplace.json` | Codex marketplace git ref pin | Modify |
| `README.md` | Install commands and asset name | Modify |
| `docs/SUBMISSION.md` | Listing version and release-notes case count | Modify |
| `CHANGELOG.md` | 0.2.1 entry | Modify |
| `packaging/README.md` | Names the version test as the authoritative pin list | Modify |
| `docs/releases/v0.2.0.md` | Missing release document | Create |
| `docs/releases/v0.2.1.md` | This release's document | Create |
| `.gitignore` | Ignores the project ledger | Modify |
| `.agent-audit/ledger.json` + `records/` | Project-scope ledger (untracked) | Create |
| `~/.claude/agent-ingest-audit-optimize/ledger.json` | Global-scope ledger, ID authority (outside repo) | Create |
| `docs/validation/ledger-dogfood-0.2.1.md` | What the dogfood exercise found | Create |

---

### Task 1: The version-consistency test

Establishes the check before any value is corrected. Run against the current tree, it must fail on exactly four pins.

**Files:**
- Create: `packaging/tests/test_version_consistency.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `VersionConsistencyTests`, a `unittest.TestCase` with one method per pin. Task 2 relies on every method passing after the bump.

- [ ] **Step 1: Write the failing test**

Create `packaging/tests/test_version_consistency.py`:

```python
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]

CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
README = REPO_ROOT / "README.md"
SUBMISSION = REPO_ROOT / "docs" / "SUBMISSION.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

SEMVER = r"\d+\.\d+\.\d+"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def single_match(pattern: str, text: str, path: Path) -> str:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if not matches:
        raise AssertionError(f"{path.name}: no line matched {pattern!r}")
    return matches[0]


class VersionConsistencyTests(unittest.TestCase):
    """Every version pin in the repository derives from one source of truth.

    The source of truth is .claude-plugin/plugin.json -> version. Each pin gets
    its own test method so a failure names the file that drifted.
    """

    def setUp(self) -> None:
        self.version = load_json(CLAUDE_MANIFEST)["version"]

    def test_source_of_truth_is_strict_semver(self) -> None:
        self.assertRegex(self.version, f"^{SEMVER}$")

    def test_codex_manifest_version_matches(self) -> None:
        self.assertEqual(load_json(CODEX_MANIFEST)["version"], self.version)

    def test_claude_marketplace_version_matches(self) -> None:
        entry = load_json(CLAUDE_MARKETPLACE)["plugins"][0]
        self.assertEqual(entry["version"], self.version)

    def test_agents_marketplace_ref_matches(self) -> None:
        entry = load_json(AGENTS_MARKETPLACE)["plugins"][0]
        self.assertEqual(entry["source"]["ref"], f"v{self.version}")

    def test_readme_codex_ref_matches(self) -> None:
        found = single_match(rf"--ref v({SEMVER})", read_text(README), README)
        self.assertEqual(found, self.version)

    def test_readme_skill_asset_name_matches(self) -> None:
        found = single_match(
            rf"agent-ingest-audit-optimize-({SEMVER})-skill\.zip",
            read_text(README),
            README,
        )
        self.assertEqual(found, self.version)

    def test_submission_listing_version_matches(self) -> None:
        found = single_match(
            rf"^- \*\*Version:\*\* ({SEMVER})$", read_text(SUBMISSION), SUBMISSION
        )
        self.assertEqual(found, self.version)

    def test_changelog_newest_entry_matches(self) -> None:
        found = single_match(rf"^## ({SEMVER})", read_text(CHANGELOG), CHANGELOG)
        self.assertEqual(found, self.version)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails on exactly four pins**

Run:

```bash
python -m unittest discover -s packaging/tests -v
```

Expected: 12 tests run, 8 pass, **exactly 4 failures**, and they are these and only these:

- `test_agents_marketplace_ref_matches` — `'v0.1.3' != 'v0.2.0'`
- `test_readme_codex_ref_matches` — `'0.1.3' != '0.2.0'`
- `test_readme_skill_asset_name_matches` — `'0.1.3' != '0.2.0'`
- `test_submission_listing_version_matches` — `'0.1.3' != '0.2.0'`

If any other test fails, stop: either a regex is wrong or a pin drifted that the spec did not account for. Do not proceed to Task 2 until the failure set matches exactly.

- [ ] **Step 3: Commit the test alone**

The test is committed while still failing, so the defect it catches is visible in history.

```bash
git add packaging/tests/test_version_consistency.py && git commit -m "test: assert every version pin derives from one source of truth

The packager cross-checks only .codex-plugin/plugin.json against
.claude-plugin/plugin.json, no test asserted any version, and there is no CI,
so the 0.2.0 bump aligned three pins and left four behind. This test elects
.claude-plugin/plugin.json as the source of truth and fails on each of the
four that drifted. It is committed failing; Task 2 corrects the values.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Bump to 0.2.1 and align every pin

**Files:**
- Modify: `.claude-plugin/plugin.json:4`
- Modify: `.codex-plugin/plugin.json:3`
- Modify: `.claude-plugin/marketplace.json:12`
- Modify: `.agents/plugins/marketplace.json` → `plugins[0].source.ref`
- Modify: `README.md:67`, `README.md:90`
- Modify: `docs/SUBMISSION.md:19`, `docs/SUBMISSION.md:95`
- Modify: `CHANGELOG.md` (new entry at the top of the entry list)

**Interfaces:**
- Consumes: `VersionConsistencyTests` from Task 1.
- Produces: version `0.2.1` everywhere. Task 3's release document and Task 5's RUN record both name this version.

- [ ] **Step 1: Bump the source of truth and the two other manifests**

`.claude-plugin/plugin.json` line 4:

```json
  "version": "0.2.1",
```

`.codex-plugin/plugin.json` line 3:

```json
  "version": "0.2.1",
```

`.claude-plugin/marketplace.json` line 12:

```json
      "version": "0.2.1",
```

- [ ] **Step 2: Bump the Codex marketplace ref**

`.agents/plugins/marketplace.json`, inside `plugins[0].source`:

```json
      "source": {
        "source": "url",
        "url": "https://github.com/leoleonel-jf/agent-ingest-audit-optimize.git",
        "ref": "v0.2.1"
      },
```

- [ ] **Step 3: Fix both README references**

`README.md` line 67:

```text
codex plugin marketplace add leoleonel-jf/agent-ingest-audit-optimize --ref v0.2.1
```

`README.md` line 90:

```text
Download the `agent-ingest-audit-optimize-0.2.1-skill.zip` release asset and install its single top-level Skill directory according to the client's documentation.
```

- [ ] **Step 4: Fix both `docs/SUBMISSION.md` references**

Line 19:

```text
- **Version:** 0.2.1
```

Line 95, replacing the stale case count and the "initial release" framing:

```text
Skills-only submission. The plugin ingests external material, verifies recommendations against current primary evidence, creates scoped proposals, and applies only explicitly authorized improvements. It includes security boundaries, rollback procedures, portability guidance, deterministic packaging, a local governance ledger with a standard-library validator, and a 28-case evaluation suite.
```

- [ ] **Step 5: Add the CHANGELOG entry**

Insert immediately above the `## 0.2.0 - 2026-07-30` heading:

```markdown
## 0.2.1 - 2026-07-30

- corrects `.agents/plugins/marketplace.json`, the OpenAI Codex marketplace manifest, whose
  `ref` still pinned `v0.1.3`; because a pinned ref never advances and `codex plugin marketplace
  upgrade` refreshes the catalog rather than an installed plugin, every new Codex install
  resolved 0.1.3 and 0.2.0 was unreachable through that path;
- corrects the Codex install command and the Skill asset name in `README.md`, and the listing
  version and evaluation-suite case count in `docs/SUBMISSION.md`;
- adds `packaging/tests/test_version_consistency.py`, which elects `.claude-plugin/plugin.json`
  as the single source of truth for the version and fails when any of the six other pins drifts
  from it, naming the file that drifted;
- documents that test in `packaging/README.md` as the authoritative list of version pins,
  replacing per-release checklists that named four files while seven carry the version;
- adds the release documents for 0.2.0 and 0.2.1.
```

- [ ] **Step 6: Run the version test to verify it passes**

```bash
python -m unittest discover -s packaging/tests -v
```

Expected: 12 tests, **OK**, zero failures.

- [ ] **Step 7: Run the packager to verify the manifests still agree**

```bash
python packaging/scripts/package_plugin.py build && python packaging/scripts/package_plugin.py verify
```

Expected: build writes `dist/agent-ingest-audit-optimize-0.2.1-plugin.zip`, `-0.2.1-skill.zip`, and `SHA256SUMS`; verify prints `VALID` and the `dist` path. `dist/` is git-ignored, so nothing is staged from it.

- [ ] **Step 8: Commit**

```bash
git add .claude-plugin .codex-plugin .agents README.md docs/SUBMISSION.md CHANGELOG.md && git commit -m "release: v0.2.1 -- restore Codex installability and lock the version pins

.agents/plugins/marketplace.json is the OpenAI Codex marketplace manifest,
documented at developers.openai.com, and its ref still pinned v0.1.3. A pinned
ref does not advance on its own and marketplace upgrade refreshes the catalog
rather than an installed plugin, so every new Codex install resolved 0.1.3 and
the 0.2.0 release was unreachable through that path.

Three further pins had drifted for the same reason -- nothing checked them.
Bump all seven to 0.2.1 and make the test from the previous commit pass.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Release documents and the packaging pin list

**Files:**
- Create: `docs/releases/v0.2.0.md`
- Create: `docs/releases/v0.2.1.md`
- Modify: `packaging/README.md` (new section after "Verify")

**Interfaces:**
- Consumes: the 0.2.1 version from Task 2, and the `dist/SHA256SUMS` written by Task 2 Step 7.
- Produces: nothing later tasks read programmatically.

- [ ] **Step 1: Write `docs/releases/v0.2.0.md`**

Follow the existing convention exactly (see `docs/releases/v0.1.3.md`): title, one-line release name, `## Changes`, `## Assets`, `## Checksums`, `## Claude Code installation`, `## Codex installation`.

The 0.2.0 checksums are already published and must be copied verbatim, not recomputed:

```text
3ea37c02a5f70716eca4c5ed92c5964eb070d3a932fc7068f06b9fc3a05c8675  agent-ingest-audit-optimize-0.2.0-plugin.zip
4999c04e8330bbc11186c67efb779d32fea22203669a5742065104716064a92e  agent-ingest-audit-optimize-0.2.0-skill.zip
```

The `## Changes` list is the CHANGELOG 0.2.0 entry. The Codex install block keeps `--ref v0.2.0`, because a release document records what that release shipped.

- [ ] **Step 2: Write `docs/releases/v0.2.1.md`**

Same structure. Release name: "Codex installability and version-pin release." The `## Changes` list is the CHANGELOG 0.2.1 entry written in Task 2 Step 5. The Codex install block uses `--ref v0.2.1`.

The checksums come from the build in Task 2 Step 7 — read them, do not invent them:

```bash
cat dist/SHA256SUMS
```

- [ ] **Step 3: Add the pin list to `packaging/README.md`**

Insert after the "Verify" section, before "Local use":

```markdown
## Version pins

`.claude-plugin/plugin.json` → `version` is the single source of truth for the plugin version.
Six other places restate it, and `packaging/tests/test_version_consistency.py` is the
authoritative list — it fails when any of them drifts, naming the file that did:

| Pin | Form |
| --- | --- |
| `.codex-plugin/plugin.json` → `version` | the version |
| `.claude-plugin/marketplace.json` → `plugins[0].version` | the version |
| `.agents/plugins/marketplace.json` → `plugins[0].source.ref` | `v` + the version |
| `README.md` → the `--ref` argument | `v` + the version |
| `README.md` → the Skill asset filename | contains the version |
| `docs/SUBMISSION.md` → the `**Version:**` line | the version |
| `CHANGELOG.md` → the first `## x.y.z` heading | the version |

Run it with the rest of the packaging suite:

```text
python -m unittest discover -s packaging/tests
```

A release that adds a new pin extends that test in the same commit. Do not maintain a
per-release checklist; the omission of `.agents/`, `README.md`, and `docs/SUBMISSION.md` from
the 0.2.0 checklist is what left the four stale pins that 0.2.1 corrected.

`.agents/plugins/marketplace.json` is the OpenAI Codex marketplace manifest
(<https://developers.openai.com/plugins/build/plugins>). Its `ref` is a git ref that does not
advance on its own, so it must name a tag that exists: bump it in the release commit, then push
the tag immediately after the merge.

Tags are lightweight from `v0.2.1` onward. Codex compares `git ls-remote` output against the
cloned commit, and for an annotated tag those differ, so an annotated tag makes the marketplace
re-clone on every auto-upgrade pass.
```

- [ ] **Step 4: Run the packaging suite to confirm nothing broke**

```bash
python -m unittest discover -s packaging/tests
```

Expected: **OK**.

- [ ] **Step 5: Commit**

```bash
git add docs/releases packaging/README.md && git commit -m "docs: add the 0.2.0 and 0.2.1 release documents and the version-pin list

docs/releases/ had one file per version through v0.1.3 and then stopped; 0.2.0
shipped without one. Write both, and give packaging/README.md a section naming
the new test as the authoritative pin list, so no release reconstructs a
by-hand checklist of the seven places that carry the version.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The ledger pair

Creates both ledgers empty and validating, before any record exists. This is bookkeeping under `references/LEDGER.md` — permitted in every operating state, and never presented as an implemented change.

**Files:**
- Modify: `.gitignore`
- Create: `.agent-audit/ledger.json`, `.agent-audit/records/` (untracked)
- Create: `~/.claude/agent-ingest-audit-optimize/ledger.json` and `records/` (outside the repository)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: two ledgers whose `sequences` Task 5 allocates from, and a `known_projects` entry whose `last_digest` Task 5 must refresh.

- [ ] **Step 1: Ignore the project ledger**

Append to `.gitignore`:

```text
.agent-audit/
```

- [ ] **Step 2: Create the global ledger**

Create `~/.claude/agent-ingest-audit-optimize/records/` (empty) and `~/.claude/agent-ingest-audit-optimize/ledger.json`:

```json
{
  "schema_version": "1.0",
  "ledger_id": "global-claude-code",
  "scope": "global",
  "language": "pt-BR",
  "client": "claude-code",
  "adapter_version": 1,
  "created": "2026-07-30",
  "updated": "2026-07-30",
  "id_authority": true,
  "sequences": { "MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0 },
  "known_projects": [],
  "records": [],
  "baselines": [],
  "backlog": []
}
```

`known_projects` is empty at this step because the project ledger does not exist yet and
`last_digest` may not be invented. Step 4 fills it.

- [ ] **Step 3: Create the project ledger**

Create `.agent-audit/records/` (empty) and `.agent-audit/ledger.json`:

```json
{
  "schema_version": "1.0",
  "ledger_id": "project-agent-ingest-audit-optimize",
  "scope": "project",
  "language": "pt-BR",
  "client": "claude-code",
  "adapter_version": 1,
  "created": "2026-07-30",
  "updated": "2026-07-30",
  "id_authority": false,
  "sequences": { "MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0 },
  "known_projects": [],
  "records": [],
  "baselines": [],
  "backlog": []
}
```

- [ ] **Step 4: Register the project in the global ledger**

Compute the real digest of the project ledger:

```bash
python -c "import hashlib,pathlib;print('sha256:'+hashlib.sha256(pathlib.Path('.agent-audit/ledger.json').read_bytes()).hexdigest())"
```

Put that exact value into the global ledger's `known_projects`, replacing the empty array:

```json
  "known_projects": [
    {
      "project_root": "C:/Users/x/proj",
      "ledger_path": "C:/Users/x/proj/.agent-audit/ledger.json",
      "last_seen": "2026-07-30",
      "last_digest": "<the sha256: value printed above>",
      "status": "OK"
    }
  ],
```

- [ ] **Step 5: Verify both ledgers in one invocation**

```bash
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify "~/.claude/agent-ingest-audit-optimize/ledger.json" ".agent-audit/ledger.json"; echo "exit=$?"
```

Expected: a line reporting two validated ledgers, no findings, `exit=0`.

If `exit=1`, read each finding and fix the ledger — not the validator. `verify` is out of scope
for this release; a genuine validator defect is written down in Task 6, not patched here.

- [ ] **Step 6: Confirm nothing is staged**

```bash
git status --short
```

Expected: `.gitignore` modified, and **no** `.agent-audit` path listed.

- [ ] **Step 7: Commit the ignore rule only**

```bash
git add .gitignore && git commit -m "chore: keep this repository's own ledger out of git

The ledger records identifiers minted by a global ledger that exists only on
one machine. 0.1.2 removed author-local record IDs from public files so fresh
installations start their own sequences; committing .agent-audit/ would put
them back.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The release records

Four records and two backlog entries, written after the 0.2.1 changes exist so every digest is
computed rather than reconstructed.

**Files:**
- Modify: `.agent-audit/ledger.json` (untracked)
- Create: `.agent-audit/records/MAT-2026-000.md`, `PROP-2026-000.md`, `ADR-2026-000.md`, `RUN-2026-000.md` (untracked)
- Modify: `~/.claude/agent-ingest-audit-optimize/ledger.json` (sequences and `last_digest`)

**Interfaces:**
- Consumes: both ledgers from Task 4; the committed 0.2.1 changes from Tasks 2 and 3.
- Produces: the observations Task 6 writes up.

- [ ] **Step 1: Allocate the identifiers in the global ledger**

The global ledger is the only ID authority. Set its `sequences` to the next free number after
allocating one of each, and its `updated` to `2026-07-30`:

```json
  "sequences": { "MAT": 1, "PROP": 1, "RUN": 1, "ADR": 1, "BASE": 0 },
```

The allocated identifiers are `MAT-2026-000`, `PROP-2026-000`, `ADR-2026-000`, `RUN-2026-000`.
None carries a `-P` suffix: the authority was reachable, so no provisional identifier is minted
and `pending_id_reconciliation` appears nowhere.

- [ ] **Step 2: Compute the digests the RUN record needs**

For every file the 0.2.1 change touched, capture the digest before and after. `before` comes from
git, `after` from the working tree:

```bash
for f in .agents/plugins/marketplace.json README.md docs/SUBMISSION.md; do
  before=$(git show v0.2.0:"$f" | python -c "import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())")
  after=$(python -c "import hashlib,pathlib,sys;print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())" "$f")
  echo "$f before=sha256:$before after=sha256:$after"
done
```

Record those exact values. Do not round, abbreviate, or reuse one file's digest for another.

- [ ] **Step 3: Write the four record documents**

Each is a short markdown document under `.agent-audit/records/`, named for its identifier. They
are written, not merely referenced — a `file` field naming a document that does not exist is a
gap `verify` cannot catch.

`MAT-2026-000.md` — what the OpenAI Codex plugin documentation says about
`.agents/plugins/marketplace.json`, the keys it defines, and the ref semantics; the URL; the date
verified.

`PROP-2026-000.md` — the 0.2.1 proposal: the four stale pins, the missing check, the source of
truth, and the seven pins the test covers.

`ADR-2026-000.md` — the decision to elect `.claude-plugin/plugin.json` as the version source of
truth, the alternatives considered (a `version-check` subcommand in the packager; both), and why
a test was chosen: the release ritual already runs the packaging suite, and no CI exists to run
anything else.

`RUN-2026-000.md` — what was changed, the commands run, and their results.

All four use this skeleton, with the free text in pt-BR and the headings and labels as shown:

```markdown
# <IDENTIFIER> — <title>

- **Type:** <MATERIAL | PROPOSAL | ADR | RUN>
- **Status:** <status, canonical English>
- **Classification:** <classification, canonical English>
- **Scope:** project
- **Created:** 2026-07-30

## Contexto

<why this record exists, two or three sentences>

## Conteúdo

<the substance: for MATERIAL, what the source says; for PROPOSAL, what is proposed;
for ADR, the decision and the alternatives rejected; for RUN, what was changed>

## Evidência

| Fonte | Tipo | Verificado em | Sensível ao tempo |
| --- | --- | --- | --- |
| <source> | <kind> | 2026-07-30 | <sim, expira em AAAA-MM-DD / não> |

## Ligações

<the record ids this one links to, or "nenhuma">
```

The evidence table restates what the ledger's `evidence` array carries for that record. If the
two disagree, the ledger is authoritative and the document is wrong — fix the document.

- [ ] **Step 4: Write the records into the project ledger**

Replace the project ledger's `records` array. Set `sequences` to `{"MAT": 1, "PROP": 1, "RUN": 1,
"ADR": 1, "BASE": 0}` — at or above the highest number its own records use, as `verify` requires
of every ledger including one that allocates nothing. Set `updated` to `2026-07-30`.

```json
  "records": [
    {
      "id": "MAT-2026-000",
      "type": "MATERIAL",
      "title": "Documentação de marketplace de plugins do Codex (OpenAI)",
      "status": "ANALYZED",
      "classification": "ADOPT LOCALLY",
      "scope": "project",
      "created": "2026-07-30",
      "updated": "2026-07-30",
      "file": "records/MAT-2026-000.md",
      "links": {},
      "evidence": [
        {
          "source": "https://developers.openai.com/plugins/build/plugins",
          "kind": "vendor documentation",
          "verified_on": "2026-07-30",
          "time_sensitive": true,
          "expires_on": "2026-10-28"
        },
        {
          "source": "https://github.com/openai/codex/pull/21396",
          "kind": "merged pull request",
          "verified_on": "2026-07-30",
          "time_sensitive": true,
          "expires_on": "2026-10-28"
        }
      ]
    },
    {
      "id": "PROP-2026-000",
      "type": "PROPOSAL",
      "title": "Corrigir os pinos de versão e travá-los com um teste (0.2.1)",
      "status": "IMPLEMENTED",
      "classification": "ADOPT LOCALLY",
      "scope": "project",
      "created": "2026-07-30",
      "updated": "2026-07-30",
      "file": "records/PROP-2026-000.md",
      "links": { "materials": ["MAT-2026-000"], "adrs": ["ADR-2026-000"] },
      "evidence": [
        {
          "source": "docs/specs/2026-07-30-version-consistency-and-ledger-dogfood.md",
          "kind": "design specification",
          "verified_on": "2026-07-30",
          "time_sensitive": false
        }
      ]
    },
    {
      "id": "ADR-2026-000",
      "type": "ADR",
      "title": "A fonte da verdade de versão é .claude-plugin/plugin.json",
      "status": "DECIDED",
      "classification": "ADOPT LOCALLY",
      "scope": "project",
      "created": "2026-07-30",
      "updated": "2026-07-30",
      "file": "records/ADR-2026-000.md",
      "links": { "materials": ["MAT-2026-000"] },
      "evidence": [
        {
          "source": "packaging/scripts/package_plugin.py:57-70",
          "kind": "source code",
          "verified_on": "2026-07-30",
          "time_sensitive": false
        }
      ]
    },
    {
      "id": "RUN-2026-000",
      "type": "RUN",
      "title": "Execução autorizada da 0.2.1",
      "status": "VALIDATED",
      "classification": "ADOPT LOCALLY",
      "scope": "project",
      "created": "2026-07-30",
      "updated": "2026-07-30",
      "file": "records/RUN-2026-000.md",
      "links": { "materials": ["MAT-2026-000"], "adrs": ["ADR-2026-000"] },
      "evidence": [
        {
          "source": "python -m unittest discover -s packaging/tests",
          "kind": "test run",
          "verified_on": "2026-07-30",
          "time_sensitive": false
        }
      ],
      "proposal": "PROP-2026-000",
      "authorization": {
        "quote": "certo, escreve o plano",
        "recorded_on": "2026-07-30"
      },
      "result": "VALIDATED",
      "targets": [
        {
          "anchor": ".agents/plugins/marketplace.json#/plugins/0/source/ref",
          "kind": "json field",
          "before_digest": "<computed in Step 2>",
          "after_digest": "<computed in Step 2>",
          "reversible": true,
          "residual_effect": null
        },
        {
          "anchor": "README.md",
          "kind": "markdown document",
          "before_digest": "<computed in Step 2>",
          "after_digest": "<computed in Step 2>",
          "reversible": true,
          "residual_effect": null
        },
        {
          "anchor": "docs/SUBMISSION.md",
          "kind": "markdown document",
          "before_digest": "<computed in Step 2>",
          "after_digest": "<computed in Step 2>",
          "reversible": true,
          "residual_effect": null
        }
      ],
      "backup": null,
      "rollback": { "tested": "NOT_TESTED" },
      "self_reported": ["backup", "rollback.tested", "result"]
    }
  ],
```

`backup` is `null` because recoverability here is the preceding git commit, which the schema does
not model as a backup object; `"backup"` is named in `self_reported` for exactly that reason.
`result` is self-reported because no tool confirms that a green suite means the change achieved
its purpose.

- [ ] **Step 5: Write the two backlog entries**

Replace the project ledger's `backlog` array:

```json
  "backlog": [
    {
      "id": "MAT-2026-000",
      "classification": "MONITOR",
      "reason": "O Codex reclona marketplaces pinados em tag anotada a cada passagem de auto-upgrade, porque git ls-remote devolve o objeto da tag e o clone guarda o commit. Mitigado adotando tags leves a partir de v0.2.1; a ineficiência a montante permanece.",
      "revisit_trigger": "openai/codex PR #17425 resolver o P2 de tags anotadas",
      "revisit_after": null
    },
    {
      "id": "MAT-2026-000",
      "classification": "NEEDS MORE EVIDENCE",
      "reason": "A documentação da OpenAI cita `codex app-server generate-json-schema` para validar o manifesto de marketplace em CI. Não foi executado: o Codex CLI não está instalado nesta máquina, então não há evidência de que cubra .agents/plugins/marketplace.json.",
      "revisit_trigger": "Codex CLI instalado nesta máquina",
      "revisit_after": "2026-10-28"
    }
  ],
```

- [ ] **Step 6: Refresh the global ledger's project digest**

The project ledger changed, so its recorded digest is now stale. Recompute and update
`known_projects[0].last_digest`:

```bash
python -c "import hashlib,pathlib;print('sha256:'+hashlib.sha256(pathlib.Path('.agent-audit/ledger.json').read_bytes()).hexdigest())"
```

`verify` checks that this field has the shape `sha256:<64 hex>`, never that it matches the ledger
it names. Keeping it true is discipline, not enforcement. Note whether this felt error-prone —
Task 6 writes it up.

- [ ] **Step 7: Verify both ledgers**

```bash
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify "~/.claude/agent-ingest-audit-optimize/ledger.json" ".agent-audit/ledger.json"; echo "exit=$?"
```

Expected: two ledgers validated, no findings, `exit=0`.

- [ ] **Step 8: Prove a corrupted ledger is caught**

A clean run alone does not show the validator works. Break one field on purpose, confirm the
finding, then restore it:

```bash
cp .agent-audit/ledger.json /tmp/ledger.bak && python -c "
import json,pathlib
p=pathlib.Path('.agent-audit/ledger.json')
d=json.loads(p.read_text(encoding='utf-8'))
d['id_authority']=True
p.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding='utf-8')
" && python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify "~/.claude/agent-ingest-audit-optimize/ledger.json" ".agent-audit/ledger.json"; echo "exit=$?"; cp /tmp/ledger.bak .agent-audit/ledger.json
```

Expected: `exit=1`, with findings naming both the project ledger's `scope`/`id_authority`
mismatch and more than one ledger claiming authority. Then the restore returns the tree to a
state where Step 7's command exits `0` — re-run it to confirm.

- [ ] **Step 9: Confirm nothing is staged**

```bash
git status --short
```

Expected: empty. No `.agent-audit` path, no ledger file. There is nothing to commit in this task
— the ledger is bookkeeping and lives outside git by design.

---

### Task 6: The validation record and the full check

**Files:**
- Create: `docs/validation/ledger-dogfood-0.2.1.md`

**Interfaces:**
- Consumes: everything observed in Tasks 4 and 5.
- Produces: the release's final state.

- [ ] **Step 1: Write the validation record**

`docs/validation/ledger-dogfood-0.2.1.md`, following the naming style of
`docs/validation/codex-runtime-validation-0.1.1.md`. It records:

- what was created — two ledgers, four records, two backlog entries — **without naming a single
  record identifier**. 0.1.2 removed author-local identifiers from public files; a validation
  record is a public file;
- the exact `verify` invocation and its exit code on the clean run;
- the deliberate corruption from Task 5 Step 8, the findings it produced, and the exit code;
- every friction the exercise surfaced. At minimum, confirm or refute the anticipated one:
  `known_projects[].last_digest` is shape-checked but never compared against the ledger it names,
  so it goes stale silently after any project-ledger write;
- whether `sequences` was ambiguous in practice. `references/LEDGER.md` calls it "the next free
  number," but `verify` only enforces a floor: after allocating `-000`, anything at or above the
  next-free value of `1` passes, and only a value below it — `0` — is flagged. The plan chose `1`.
  Say plainly whether the gap between that floor and `references/LEDGER.md`'s stricter "next free
  number" phrasing is worth closing;
- anything else that felt wrong while writing a ledger by hand.

Findings are recorded and scheduled, never fixed here. `verify` is out of scope for 0.2.1.

- [ ] **Step 2: Run every check one last time**

```bash
python -m unittest discover -s dashboard/tests && python -m unittest discover -s evals/tests && python -m unittest discover -s packaging/tests && python evals/scripts/eval_suite.py validate && python packaging/scripts/package_plugin.py verify
```

Expected: 203 dashboard tests OK; 11 evals tests OK; 12 packaging tests OK (4 pre-existing plus
the 8 new version tests — confirm the count rather than assuming it); suite valid with 28 cases
and 7 task categories; `VALID` with the `dist` path.

- [ ] **Step 3: Commit**

```bash
git add docs/validation/ledger-dogfood-0.2.1.md && git commit -m "docs: record what the first real ledger exercise found

0.2.0 shipped the ledger machinery but nothing had ever written a ledger by
hand for real work -- verify had only ever run against test fixtures. This
records the two-scope ledger built for the 0.2.1 release, the clean run, the
deliberate corruption that proves the validator catches a real fault, and the
friction the exercise surfaced. No record identifier appears here; 0.1.2
removed author-local identifiers from public files.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Acceptance

| Criterion | Evidence |
|---|---|
| The check fails before the fix | Task 1 Step 2 reports exactly the four pins of the spec §1.2 |
| The check passes after the fix | Task 2 Step 6 — packaging suite OK |
| Codex resolves the current release | `.agents/plugins/marketplace.json` ref is `v0.2.1`, matching the tag pushed after merge |
| Both release documents exist | `docs/releases/v0.2.0.md` and `docs/releases/v0.2.1.md` |
| The pin list has one home | `packaging/README.md` names the test; no new per-release checklist |
| The ledger validates | Task 5 Step 7 — `verify` over both ledgers exits `0` |
| The validator catches a real fault | Task 5 Step 8 — deliberate corruption exits `1` with the expected findings |
| No ledger is committed | Task 5 Step 9 — `git status --short` empty |
| No author identifier is published | `docs/validation/ledger-dogfood-0.2.1.md` contains no record id |
| Nothing regressed | Task 6 Step 2 — every suite green, suite valid, `dist` verified |

## Release sequencing after this plan

Merging is a decision, not a plan step. Once merged: push the lightweight tag `v0.2.1`
immediately, then create the GitHub release with the two archives and `SHA256SUMS` from `dist/`,
following the body format of the v0.2.0 release. Until the tag exists, `.agents/plugins/marketplace.json`
names a ref that cannot be resolved.

## Out of scope

CI; any change to `dashboard.py verify`; the 0.3.0 deferrals (anchor resolution spec §7.1,
filesystem path safety spec §13.6, splitting `dashboard.py` into a package); retagging `v0.2.0`;
creating `baseline/` or `backups/` directories.
