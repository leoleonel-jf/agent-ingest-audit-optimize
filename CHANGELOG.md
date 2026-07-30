# Changelog

All notable changes to this project are documented in this file.

## 0.2.0 - 2026-07-30

- adds a local governance ledger recording every material audit, proposal, run, decision, and
  rollback, split between a global scope and git-versionable project scopes;
- makes the global ledger the sole authority for record identifiers, requiring
  `pending_id_reconciliation` on any provisional (`-P`) identifier until it is reconciled;
- states that writing to the plugin's own ledger is audit bookkeeping, permitted in every
  operating state and never counted as implementing a proposal;
- requires a revisit trigger or date for every non-adopted finding, and keeps terminal
  classifications out of the backlog;
- ships `assets/scripts/dashboard.py verify`, a standard-library validator covering the ledger
  document, records, runs, backlog, and known projects, publishing
  `assets/schemas/ledger.schema.json` as the ledger contract with every schema rule mirrored by
  a matching runtime check and a test asserting the two agree;
- tests `verify`'s output contract by capturing stdout and stderr: clean runs report validated
  ledger count on stdout, findings and read errors to stderr;
- enforces `authorization.recorded_on`, `revisit_after`, and `last_seen` as dates in the
  ledger's standard `YYYY-MM-DD` format;
- resolves cross-ledger identifier collisions, sequence drift, and dangling links across every
  ledger passed to `verify` in one invocation, skipping link resolution when a ledger in the set
  could not be read so a missing ledger cannot produce a false dangling-link finding;
- reports findings from every readable ledger plus the read errors for the rest, exiting `2`
  when any ledger was unreadable, `1` when there were findings and all ledgers were readable,
  and `0` when clean;
- hardens nine set-membership checks in the validator against unhashable ledger content (list or
  object values in enum-checked fields), which previously raised `TypeError` instead of
  producing a finding;
- delegates material acquisition, per-claim verification, environment inventory, and alternative
  evaluation to subagents where the client supports them, while forbidding delegation of
  implementation, running more than one authorized proposal at once, splitting one
  implementation across workers, or granting a subagent authority to authorize;
- adds four evaluation cases (`LDG-001`, `LDG-002`, `LDG-003`, `DLG-001`) and four critical-check
  definitions covering ledger bookkeeping, backlog revisit conditions, identifier authority, and
  non-delegated implementation;
- documents the ledger's location and locality in `README.md` and `PRIVACY.md`, and locks its
  bundle assets into both the plugin and portable Skill archives with a packaging test.

## 0.1.3 - 2026-07-28

- instructs the Skill to communicate in the user's language for all prose, summaries, questions, and reports;
- keeps operating states, status labels, classification labels, and record IDs in canonical English regardless of conversation language;
- directs template free-text fields to the user's working language while preserving canonical headings and labels.

## 0.1.2 - 2026-07-28

- ships the required `description` field in the Claude Code marketplace manifest (previously only on `main`, missing from the v0.1.1 tag);
- documents the marketplace-based Claude Code install flow as the primary method, keeping `--plugin-dir` for development;
- clarifies that record ID sequences (`MAT-`, `PROP-`, `RUN-`, `ADR-`) are local to each installation and start at `000`;
- removes internal author-history record IDs from the public README and validation record so fresh installations start their own sequences;
- adds Claude Code community-marketplace submission data alongside the existing OpenAI directory listing.

## 0.1.1 - 2026-07-28

- replaces the initial complex logo with the approved minimal magnifying-glass, shield, and check mark;
- adds the deterministic SVG source and regenerates the official PNG from exactly three flat colors;
- reduces the PNG asset size while improving small-size legibility.

## 0.1.0 - 2026-07-28

Initial public release.

- adds the portable `agent-ingest-audit-optimize` Agent Skill;
- audits external recommendations against current primary evidence;
- separates analysis, deliberation, and explicitly authorized implementation;
- includes scope, security, rollback, and platform-adaptation guidance;
- evaluates model and reasoning-effort choices by representative task category;
- provides a 24-case behavioral evaluation suite;
- packages one canonical Skill for Codex, Claude Code, Claude API, and compatible Agent Skills clients;
- adds deterministic plugin and portable-Skill archives.
