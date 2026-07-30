# Design — Governance Ledger and Dashboard

- Date: 2026-07-29
- Status: APPROVED FOR PLANNING
- Target versions: 0.2.0, 0.3.0, 0.4.0
- Supersedes: nothing

## 1. Problem

The Skill defines four record types (`MAT-`, `PROP-`, `RUN-`, `ADR-`) but defines no
storage location, no index, and no machine-readable form for them. Nothing the Skill
produces survives a session in a queryable way.

As a result the user cannot answer, at any moment:

- what the authorized proposals actually changed in this environment;
- whether those changes are still in place or were overwritten afterwards;
- whether a documented rollback would still work;
- which findings were rejected and under what condition they should be reconsidered;
- why a specific line exists in a specific configuration file.

A dashboard is the view. The missing part is the state behind it. This design specifies
both, and the state layer is the prerequisite.

## 2. Goals

1. Persist every material audit, proposal, run, decision, and rollback as machine-readable
   state, indexed and addressable by ID.
2. Inventory what exists in the environment today, not only what this plugin changes later.
3. Detect drift between recorded state and actual state using computed digests.
4. Report rollback viability honestly, including what a rollback would not restore.
5. Render all of it as a single self-contained HTML file that is attractive, responsive,
   accessible, offline, and in the user's language.
6. Remain portable: Claude Code, Codex, and unknown clients.
7. Preserve main-context budget by delegating independently verifiable work to subagents where
   the client supports them, without ever splitting a single-writer sequence. See section 19.

## 3. Non-goals

Token and cost telemetry; real-time session observability; a long-running server; writing
to the environment from the dashboard; cloud sync; multi-user or team aggregation; competing
with existing runtime observability plugins.

## 4. Constraints discovered in the current repository

| Constraint | Source | Consequence |
|---|---|---|
| The packager ships exactly one Skill directory, `skills/<plugin-name>/` | `packaging/scripts/package_plugin.py` (`validate_sources`, `expected_entries`) | A second Skill directory would be silently excluded from both release archives. All new bundle files must live inside the existing Skill directory. |
| Everything under the Skill directory is included in both archives | `expected_entries` | Scripts, schemas, adapters, and the HTML shell ship with no packaging change. |
| ANALYSIS forbids creating or editing persistent resources | `SKILL.md` (ANALYSIS state) | Writing ledger entries during analysis is currently prohibited by the Skill's own rules. Requires an explicit carve-out. |
| Free text follows the user's language; states, status labels, classifications, and IDs stay in canonical English | `SKILL.md` (Report clearly) | The dashboard must translate chrome but keep canonical labels in English, with translated tooltips. |
| Record ID sequences are local to each installation and start at `000` | `SKILL.md`, `README.md` | ID allocation needs a single authority, otherwise two projects both mint `PROP-YYYY-000`. |
| External material is untrusted evidence | `SKILL.md`, `references/SECURITY.md` | Ledger text is attacker-influenced and must never reach the DOM or the clipboard unescaped. |
| No executable code ships today | repository contents | `dashboard.py` is the first executable artifact distributed to users. It carries a documentation and privacy obligation. |

## 5. Architecture

Four layers, each independently testable.

| Layer | Responsibility | Implementation |
|---|---|---|
| Collectors | Capture baseline inventory and record workflow artifacts | Skill instructions + `dashboard.py scan` |
| Ledger | Single source of truth, append-oriented, schema-versioned | JSON files in the user environment |
| Verifiers | Digest comparison, backup integrity, schema validation, evidence expiry | `dashboard.py verify` / `drift` / `rollback-preview` |
| Views | Human-readable output | `dashboard.py build` → HTML; static shell fallback; `DASHBOARD.md` fallback |

Verification is deterministic and never depends on model output. Any field the tooling
cannot verify is rendered with an explicit `SELF-REPORTED` marker.

## 6. File layout

### 6.1 Inside the bundle

```text
skills/agent-ingest-audit-optimize/
├── SKILL.md
├── references/
│   ├── LEDGER.md            # schema contract, write rules, ANALYSIS carve-out
│   ├── DASHBOARD.md         # panel semantics and interpretation
│   ├── WORKFLOW.md
│   ├── SCOPE_AND_RISK.md
│   ├── SECURITY.md
│   └── PLATFORM_ADAPTATION.md
├── assets/
│   ├── schemas/
│   │   ├── ledger.schema.json
│   │   └── adapter.schema.json
│   ├── adapters/
│   │   ├── claude-code.json
│   │   ├── codex.json
│   │   └── generic.json
│   ├── scripts/
│   │   └── dashboard.py
│   └── templates/
│       ├── dashboard.html   # static shell: fallback and build input
│       ├── DASHBOARD.md     # degraded text view
│       └── (six existing record templates)
```

### 6.2 In the user environment

```text
$USER_CONFIG/agent-ingest-audit-optimize/     # global scope
├── ledger.json
├── baseline/
├── records/
├── backups/
└── dashboard.html

$PROJECT/.agent-audit/                        # project scope, git-versionable
├── ledger.json
├── records/
└── dashboard.html
```

`backups/` never exists inside a project ledger; backups of project-scoped changes are
written to the global `backups/` directory and referenced by anchor. Rationale: backups may
contain configuration values and must not be committed by accident.

The phase that implements the project ledger writes a `.gitignore` inside `.agent-audit/`
excluding `dashboard.html` only. Records are meant to be committed.

## 7. Data model

### 7.1 Path anchors

Absolute paths are never stored when an anchor applies. Anchors resolve per client adapter:

- `$USER_CONFIG` — the client's user-level configuration root;
- `$PROJECT` — the project root of the ledger that owns the record;
- `$PLUGIN` — the installed bundle root.

Anything outside an anchor is stored absolute and flagged `portable: false`.

### 7.2 `ledger.json`

```json
{
  "schema_version": "1.0",
  "ledger_id": "l-8f2c1a",
  "scope": "global",
  "language": "pt-BR",
  "client": "claude-code",
  "adapter_version": 1,
  "created": "2026-07-29",
  "updated": "2026-07-29",
  "id_authority": true,
  "sequences": { "MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0 },
  "known_projects": [
    {
      "project_root": "C:/Users/x/proj",
      "ledger_path": "C:/Users/x/proj/.agent-audit/ledger.json",
      "last_seen": "2026-07-29",
      "last_digest": "sha256:…",
      "status": "OK"
    }
  ],
  "records": [],
  "baselines": [],
  "backlog": []
}
```

`status` for a known project is one of `OK`, `UNREACHABLE`, `CHANGED_EXTERNALLY`.
An `UNREACHABLE` project is rendered as such and never dropped from the view.

### 7.3 Record index entry

```json
{
  "id": "PROP-2026-000",
  "type": "PROPOSAL",
  "title": "…",
  "status": "PROPOSED",
  "classification": "ADOPT GLOBALLY",
  "scope": "user-global",
  "created": "2026-07-29",
  "updated": "2026-07-29",
  "file": "records/PROP-2026-000.md",
  "links": { "materials": ["MAT-2026-000"], "runs": [], "adrs": [] },
  "evidence": [
    {
      "source": "https://…",
      "kind": "official-docs",
      "verified_on": "2026-07-20",
      "time_sensitive": true,
      "expires_on": "2026-10-20"
    }
  ]
}
```

`expires_on` is required when `time_sensitive` is true. Model names, prices, feature
availability, and defaults are always `time_sensitive`. Default validity is 90 days.

### 7.4 Run entry

```json
{
  "id": "RUN-2026-000",
  "type": "RUN",
  "proposal": "PROP-2026-000",
  "authorization": { "quote": "Implement proposal PROP-2026-000", "recorded_on": "2026-07-29" },
  "result": "VALIDATED",
  "targets": [
    {
      "anchor": "$USER_CONFIG/settings.json",
      "kind": "json-key",
      "key": "permissions.allow",
      "before_digest": "sha256:…",
      "after_digest": "sha256:…",
      "before_excerpt": "…redacted…",
      "after_excerpt": "…redacted…",
      "reversible": true,
      "residual_effect": null
    }
  ],
  "backup": { "path": "backups/RUN-2026-000/", "digest": "sha256:…", "verified": true },
  "rollback": { "file": "records/RUN-2026-000.rollback.md", "tested": "NOT_TESTED" },
  "self_reported": ["tests"]
}
```

`self_reported` lists fields the tooling cannot confirm. The dashboard marks every listed
field visibly. This is the difference between an audit record and a self-report.

### 7.5 Baseline entry

```json
{
  "id": "BASE-2026-000",
  "captured_on": "2026-07-29",
  "client": "claude-code",
  "adapter_version": 1,
  "items": [
    {
      "kind": "mcp-server",
      "name": "playwright",
      "anchor": "$USER_CONFIG/settings.json",
      "digest": "sha256:…",
      "attributes": { "transport": "stdio" },
      "origin": "pre-existing"
    }
  ]
}
```

`kind` is one of: `instruction-file`, `skill`, `plugin`, `agent`, `command`, `hook`,
`mcp-server`, `permission-rule`, `model-setting`, `env-var-name`.

`origin` is `pre-existing` or a `PROP-` ID. Determined by matching against run targets.

### 7.6 Backlog entry

```json
{
  "id": "PROP-2026-000",
  "classification": "NEEDS MORE EVIDENCE",
  "reason": "…",
  "revisit_trigger": "Codex documents a stable hook API",
  "revisit_after": "2026-10-01"
}
```

Populated from every finding classified `REJECT`, `NEEDS MORE EVIDENCE`,
`RISK EXCEEDS BENEFIT`, `MONITOR`, or `TEST IN ISOLATION`. A backlog entry requires either
`revisit_trigger` or `revisit_after`; entries with neither are invalid.

## 8. Scope resolution and ID allocation

- A record whose scope is `session`, `project`, or `workspace` is written to the project
  ledger when a project root exists; otherwise to the global ledger with `portable: false`.
- A record whose scope is `user-global`, `organization`, or `fleet` is always written to the
  global ledger.
- The global ledger is the only `id_authority`. Project ledgers request the next ID from it.
- If the global ledger is unreachable, the project ledger mints a provisional ID with a
  `-P` suffix (`PROP-2026-000-P`) and records `pending_id_reconciliation: true`. The next
  successful global write reconciles it and rewrites references.
- The global ledger's `known_projects` is updated on every project-ledger write.

## 9. Baseline scanner and client adapters

`dashboard.py scan` performs read-only discovery driven by a declarative adapter. Adding a
new client means adding a JSON file, not changing code.

```json
{
  "adapter_version": 1,
  "client": "claude-code",
  "anchors": { "$USER_CONFIG": ["~/.claude"], "$PROJECT": ["."] },
  "probes": [
    { "kind": "instruction-file", "glob": "$USER_CONFIG/CLAUDE.md" },
    { "kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md" },
    { "kind": "plugin", "path": "$USER_CONFIG/plugins/installed_plugins.json", "parse": "json" },
    { "kind": "mcp-server", "path": "$USER_CONFIG/settings.json", "parse": "json", "pointer": "/mcpServers" }
  ],
  "sensitive_key_patterns": ["*token*", "*key*", "*secret*", "*password*", "*credential*", "env"]
}
```

Rules:

- A probe that matches nothing is recorded as `not_present`, never as an error.
- A value under a `sensitive_key_patterns` match is never copied. The scanner stores the key
  name and a digest of the value. This applies recursively to nested objects.
- Unknown client: `scan` selects `generic.json`, which probes nothing, and the Skill asks the
  user for paths and writes `$USER_CONFIG/agent-ingest-audit-optimize/adapters/local.json`.
  A user-supplied adapter takes precedence over a bundled one with the same client name.
- Adapters are data, not code. No probe field may contain a shell command or a glob that
  escapes its anchor. `scan` rejects `..` segments and absolute globs.

Codex adapter paths are researched and verified against current first-party documentation
during phase 0.3.0 and are not asserted by this document.

## 10. Drift and integrity

`dashboard.py drift` compares recorded digests against the current environment and classifies
each run target and baseline item:

| State | Meaning |
|---|---|
| `IN_PLACE` | Current digest matches `after_digest`. The change is intact. |
| `DRIFTED` | Current digest matches neither `before_digest` nor `after_digest`. Modified externally. |
| `REVERTED` | Current digest matches `before_digest`. The change is gone. |
| `MISSING` | The target no longer exists. |
| `UNVERIFIABLE` | No digest was recorded, or the path is unreadable. |

`dashboard.py verify` validates the ledger against `ledger.schema.json`, recomputes backup
digests, checks that every `RUN` with a backup has a readable backup, and flags evidence past
`expires_on`. Exit codes: `0` clean, `1` findings, `2` tool error.

## 11. Rollback preview

`dashboard.py rollback-preview RUN-2026-000` produces a read-only report modeled on an
infrastructure plan. It performs no writes.

It reports four sets explicitly, including the third and fourth, which are the ones usually
omitted and the reason rollbacks surprise people:

1. **Will be restored** — targets with a verified backup and a state of `IN_PLACE`.
2. **Will not change** — targets already `REVERTED`, listed so the report is complete.
3. **Cannot be restored** — targets that are `DRIFTED` (restoring would destroy an unrelated
   later edit), `MISSING`, or `UNVERIFIABLE`.
4. **Residual effects** — anything recorded in `residual_effect`: installed dependencies,
   external accounts, published artifacts, cache state.

Rollback health per run is a single indicator derived from the above:

| Indicator | Condition |
|---|---|
| `HEALTHY` | Backup verified, every target `IN_PLACE`, no residual effects |
| `AT_RISK` | Backup verified but at least one target `DRIFTED` or with residual effects |
| `BROKEN` | Backup missing, unreadable, or digest mismatch |

## 12. Dashboard

### 12.1 Panels

| # | Panel | Content |
|---|---|---|
| 1 | Overview | Aggregate indicators: active changes, drift count, rollbacks at risk, expired evidence, unreachable projects |
| 2 | Inventory | Baseline items by kind, each with an origin column: `PROP-` ID or `pre-existing` |
| 3 | Changes | Run timeline with targets, inline before/after diff, tests, result, deviations |
| 4 | Provenance | Reverse index: file or key → run → proposal → material → evidence and date |
| 5 | Rollback | Per-run health indicator and the four-set preview from section 11 |
| 6 | Backlog | Non-adopted findings with revisit trigger and date |
| 7 | Decisions | ADRs with lifecycle status and supersession links; never removed |
| 8 | Materials | Audited materials with completeness, reliability, and obsolescence risk |
| 9 | Help | Operating states, classification vocabulary, invocation examples, function reference. Static content, offline |

Default ordering is by severity, then recency. Never recency alone.

### 12.2 Actions

A file-protocol page cannot execute commands, write files, or talk to the agent. Buttons
therefore produce actions rather than perform them:

- **Copy instruction** — writes a ready-to-paste agent instruction to the clipboard, for
  example `Implement proposal PROP-2026-000`.
- **Action queue** — accumulates several instructions; one button copies the batch in a safe
  order (rollbacks before implementations).
- **Open** — a `file://` link to the record, the backup, or the changed file.
- **Export** — copies a record as JSON, or downloads the ledger.
- **Rollback** — requires two-step confirmation and displays the section 11 preview before
  the copy is enabled.

Instruction text is assembled exclusively from a fixed template plus an ID validated against
`^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$`. No text originating from material ever reaches
the clipboard. A future `dashboard.py serve` mode could execute actions over localhost; the
data model accommodates it, and it is out of scope here.

### 12.3 UI and UX requirements

Presentation:

- Self-contained single file. No CDN, no remote font, no network request of any kind. This is
  both an offline requirement and a confidentiality requirement.
- Automatic light and dark theme via `prefers-color-scheme`; honors `prefers-reduced-motion`.
- Responsive: table layout on wide viewports, card layout on narrow ones, sticky filter bar,
  compact and comfortable density toggle.

Navigation:

- Command palette on `Ctrl`/`Cmd`+`K` searching records, files, and configuration keys.
- Filter state encoded in the URL fragment so a view can be bookmarked or shared.
- Full keyboard navigation with visible focus.

Accessibility:

- Status is never conveyed by color alone. Every indicator carries an icon and a text label.
- WCAG 2.2 AA contrast in both themes, semantic HTML, labelled controls.
- A print stylesheet producing a readable PDF, because audit evidence gets handed over.

Comprehension:

- Empty states are instructional: each empty panel shows the exact command that populates it.
- A staleness banner appears when `ledger.json` is newer than the rendered HTML.
- Inline before/after diff for every changed configuration key.

### 12.4 Language

- The shell carries an i18n dictionary; `ledger.json.language` selects it; `build --lang`
  overrides it. Unknown language falls back to English.
- Operating states, status labels, classification labels, and record IDs remain in canonical
  English on screen, each with a translated tooltip. This preserves the existing rule in
  `SKILL.md` while keeping the view readable.
- Layout uses CSS logical properties so right-to-left languages work without a second
  stylesheet.
- Bundled dictionaries at 0.4.0: `en`, `pt-BR`. A dictionary is a flat JSON object; adding a
  language requires no code change.

## 13. Security requirements

These are mandatory and covered by evaluations.

1. **No stored cross-site scripting.** Ledger content is attacker-influenced. The ledger is
   embedded in `<script type="application/json">` with `<` and `/` escaped in the closing
   sequence. Rendering uses `textContent` and `createElement` exclusively; `innerHTML`,
   `insertAdjacentHTML`, `document.write`, and `eval` are prohibited. The document carries a
   `Content-Security-Policy` meta tag of `default-src 'none'; img-src data:; style-src
   'unsafe-inline'; script-src 'unsafe-inline'`, with no external origin permitted. Hash-based
   `script-src` is not used because hash enforcement is unreliable under the `file:` protocol
   across browsers. The meta tag is therefore a defense-in-depth measure, and the primary
   controls are the prohibited APIs above plus the zero-network-request evaluation.
2. **No prompt injection via the clipboard.** See section 12.2. Fixed template plus validated
   ID only.
3. **No secret capture.** See section 9. Sensitive values are digested, never stored.
4. **No network egress.** The generated file must produce zero network requests. Verified by
   evaluation.
5. **Local only.** `PRIVACY.md` must state that the ledger, baselines, and backups are local
   files that the plugin never transmits.
6. **Path safety.** `dashboard.py` refuses to read or write outside resolved anchors, rejects
   symlinks that escape an anchor, and refuses adapter globs containing `..`.

## 14. Degradation

| Environment | Result |
|---|---|
| Python 3 available | Full: `scan`, `verify`, `drift`, `rollback-preview`, `build` |
| No Python | Skill writes `ledger.json` and injects it into the static shell. Views work; digest verification, drift, and rollback preview are unavailable and the dashboard states this in the overview panel. |
| No browser or headless environment | Skill generates `DASHBOARD.md` from the same ledger |
| Unknown client | Ledger and views work; baseline scanning is limited to a user-supplied adapter |

The dashboard must never be simply unavailable, and a degraded dashboard must say which
guarantees are missing rather than imply full verification.

## 15. Required changes to `SKILL.md`

1. Add an ANALYSIS carve-out: writing to this plugin's own ledger and its records is audit
   bookkeeping, not an environment change. It never requires authorization and never
   constitutes implementation. Backup creation is excluded from the carve-out: it belongs to
   IMPLEMENTATION, which already requires a backup before the first change. Without this the
   Skill contradicts itself.
2. Add a short "Ledger and dashboard" section pointing to `references/LEDGER.md` and
   `references/DASHBOARD.md`. Keep it brief; both references load on demand.
3. State that ID allocation belongs to the global ledger.
4. Require that the five classifications listed in section 7.6 produce a backlog entry with a
   revisit trigger or date. `OBSOLETE`, `NOT APPLICABLE`, and `ALREADY IMPLEMENTED` are
   terminal and never enter the backlog.

Context budget: the additions to `SKILL.md` must not exceed roughly 40 lines. Detail belongs
in the references.

## 16. Phasing and acceptance

Each phase is planned and implemented separately and is useful on its own. This document is
the shared design; it is not a single implementation plan. The plan that follows it covers
0.2.0 only, and 0.3.0 and 0.4.0 are planned after their predecessor is validated.

### 0.2.0 — Ledger

Delivers `ledger.schema.json`, `references/LEDGER.md`, the `SKILL.md` changes from section 15,
ledger writing during the existing workflow, and `dashboard.py verify`.

Accepted when: a full analysis-to-run cycle produces valid ledger entries in both scopes; IDs
allocate without collision across two projects; `verify` exits non-zero on a corrupted ledger;
the ANALYSIS carve-out is documented and evaluated.

### 0.3.0 — Baseline and drift

Delivers `adapter.schema.json`, the Claude Code, Codex, and generic adapters, `scan`, `drift`,
`rollback-preview`, and the unknown-client flow.

Accepted when: a scan on a real environment produces a baseline with no sensitive value
stored; an externally modified target is reported `DRIFTED`; a rollback preview lists all four
sets including residual effects; a missing backup yields `BROKEN`.

### 0.4.0 — Dashboard

Delivers `dashboard.html`, `build`, the nine panels, the action model, the UI and UX
requirements, and the `en` and `pt-BR` dictionaries.

Accepted when: the generated file opens offline with zero network requests; a material title
containing a script payload renders as inert text; every indicator is legible without color;
the layout is usable at 360 px width; the print stylesheet produces a readable PDF; switching
language changes chrome while canonical labels stay English.

## 17. Evaluation additions

New cases in `evals/suite.json`, one per phase:

- ledger writing during ANALYSIS is permitted and does not count as implementation;
- ID allocation across two ledgers produces no collision;
- provisional IDs reconcile when the global ledger returns;
- a sensitive key is digested, never copied, including when nested;
- an externally modified file is classified `DRIFTED`, not `IN_PLACE`;
- a rollback preview on a drifted target reports it as not restorable;
- a script payload in material text renders inert in the generated HTML;
- clipboard text for an action never contains material-derived text;
- the generated dashboard issues no network request;
- an unknown client degrades to the generic adapter and asks for paths;
- a non-adopted classification without a revisit trigger is rejected as invalid.

## 18. Deferred questions

| Question | Resolved in |
|---|---|
| Exact Codex configuration paths, verified against current first-party documentation | 0.3.0 |
| Whether a delegating client can pass ledger write authority to a subagent safely | 0.3.0 |
| Whether project ledgers should carry a merge driver for git conflicts on `ledger.json` | 0.3.0 |
| Whether `dashboard.py serve` is ever built | after 0.4.0, separate decision |
| Which additional language dictionaries ship | after 0.4.0, on demand |

## 19. Subagent delegation

Auditing a substantial piece of material consumes context quickly: acquisition, per-claim
verification, and environment inventory all produce far more intermediate text than the
conclusions they yield. Where a client supports subagents, that intermediate text belongs in a
subagent's context, not the main one.

### 19.1 Delegate

| Unit | Why it is safe to delegate |
|---|---|
| Material acquisition, one subagent per source | Read-only; returns a normalized extract |
| Claim verification, one subagent per claim or small batch | Independent by construction; returns a verdict, evidence URL, and date |
| Environment inventory, one subagent per configuration area | Read-only; returns a structured item list |
| Alternative evaluation during DELIBERATION | Independent analyses; a diverse-perspective panel improves the comparison |

A delegated unit returns structured data, never prose to be re-read. The main context keeps
synthesis, classification, prioritization, proposal authoring, and every user-facing decision.

### 19.2 Never delegate

Implementation is a single-writer sequence. Backup, apply, validate, and record must run in one
context that owns the stop conditions, because a stop condition reached by one worker cannot
halt another mid-write. Concretely, the following are prohibited:

- running two authorized proposals concurrently;
- splitting the steps of one implementation across subagents;
- delegating backup creation or verification away from the context that applies the change;
- granting a subagent authority to authorize, or to interpret an authorization.

Ledger writes follow the writer. Until the question in section 18 is resolved, only the main
context writes the ledger; a subagent returns data for the main context to record.

### 19.3 Portability

Subagent support varies by client and must be detected, never assumed. Absent support, the same
work runs sequentially in the main context with identical outputs. Delegation is an optimization
of context budget, never a change to the workflow, the evidence standard, or the result.

The delegation policy is stated briefly in `SKILL.md` and detailed in
`references/PLATFORM_ADAPTATION.md`, which already carries client-specific guidance.

### 19.4 Applies to this project too

Implementation work on this repository follows the same rule: plan tasks are dispatched to fresh
subagents per task, while review, integration, and release decisions stay in the main context.
