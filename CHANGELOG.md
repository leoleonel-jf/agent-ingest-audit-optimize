# Changelog

All notable changes to this project are documented in this file.

## 0.2.4 - 2026-07-30

A patch release for a real defect in the shipped path-safety layer, found by running the test
suite on Ubuntu for the first time -- until now it had only ever run on Windows.

- fixes `resolve_anchored` leaking a raw `RuntimeError` out of the path-safety layer instead of
  refusing with `PathSafetyError`, when a stored path crosses a symlink loop
  (`root/a -> root/b -> root/a`). `pathlib`'s own `Path.resolve()` detects the loop in Python and
  raises a bare `RuntimeError` for it, not an `OSError`, so `_resolve_or_raise`'s `except OSError`
  let it pass straight through uncaught; the guard was invisible on Windows because Windows has no
  equivalent construct and the `pathlib` code path that raises it does not exist on that platform.
  `_resolve_or_raise` now also catches `RuntimeError`, under the existing `resolve_failed` reason;
  `_refuse_if_hardlinked`'s `stat()` catches it too now, defensively, for symmetry;
- fixes two tests that encoded Windows-only filesystem assumptions, found by the same Ubuntu run,
  so each now asserts what is actually correct on its own platform instead of a Windows-only
  outcome: `test_oserror_from_resolve_becomes_path_safety_error` skips on POSIX, where no
  construct reliably provokes the `OSError` this guard exists to wrap (non-strict
  `Path.resolve()` accepts a trailing dot/space segment silently instead of raising); and
  `test_path_key_normalizes_separator_and_case` now asserts a digest finding on Windows and a
  clean exit with no finding on POSIX, since a differently-cased path is a genuinely different
  file on a case-sensitive filesystem rather than "the same path, not compared";
- scopes `test_release_document_checksums_match_a_real_build` to skip, with its reasoning stated,
  when no release document exists yet for the current version, rather than going red for the
  entire development cycle every time packaged content changes before the release document for
  that version has been written.

**Compatibility:** additive and corrective; no ledger or public interface changes. The
cross-platform build was verified byte-identical -- the same commit's archives carry identical
SHA-256 checksums whether built on Windows or on the Ubuntu 24.04 host that surfaced these
platform differences, because `package_plugin.py` fixes archive timestamps and uses POSIX-style
paths regardless of the host OS. Only the POSIX-only failure mode changes; already-passing
behavior on either platform is unaffected.

## 0.2.3 - 2026-07-30

The first of three increments toward the design spec's 0.3.0 (`docs/specs/2026-07-30-anchors-and-path-safety.md`).
Adds no new command: it builds the anchor and path-safety layer the next release's `scan` will
consume, and gives `baselines[]` a real field schema.

- adds `anchor_path`, storing a path relative to the anchor that contains it — `$USER_CONFIG`,
  `$PROJECT`, or `$PLUGIN` — with the longest matching root winning when more than one anchor
  applies, and marking a path outside every anchor absolute with `portable: false`;
- adds `resolve_anchored` and `PathSafetyError`, refusing with a distinct, named reason an unknown
  anchor, a `..` segment (checked textually before any normalization), an absolute path where an
  anchored form was required, a resolved result outside the anchor, and — stricter than mere
  resolution — a symlink or junction whose target leaves the anchor even when the path's final
  resolution lands back inside it; none of this touches how `verify` reads its own command-line
  arguments or opens a path read out of ledger content;
- adds `check_glob`, refusing an adapter probe glob containing a `..` segment or an absolute form,
  without expanding any glob;
- gives `baselines[]` entries and their items a real field schema in
  `assets/schemas/ledger.schema.json` and a matching `validate_baseline` in `dashboard.py`,
  replacing "each element must be an object, but no field-level schema yet"; adds a `state` field
  (`present` / `not_present`) the design spec's field table never defined, recording a probe that
  matched nothing without overloading `kind` or a null `digest`;
- makes a `baselines[]` entry's `id` participate in the sequence rules exactly as a record's `id`
  does, in both the per-document floor and the ID authority's set-wide coverage;
- adds `portable` as an optional boolean on a run target and on a baseline item, checked for type
  only when present and never required;
- documents all of it in `references/LEDGER.md`: Path anchors, Path safety, Adapter glob safety,
  the `BASE`-identifier sequence rule, and the Baselines field tables, each guarded by an ablated
  reference test.
- **correction:** `references/LEDGER.md`'s Path safety section originally named only five of
  `resolve_anchored`'s refusal reasons, though the code already enforced fourteen; the hardlinked
  regular file, reserved DOS device name, and alternate-data-stream (`:` component) refusals —
  all added during the same security review as the other checks above — never reached this or any
  other public document, alongside four narrower reasons (invalid anchor name, empty path,
  malformed anchor reference, and a resolve/inspect `OSError` wrapped rather than left to escape).
  The document now names all fourteen, plus the four reasons `check_glob` can raise, in a
  machine-checked block an alignment test compares against the code directly.
  **Operational consequence:** a user whose instruction file is hardlinked between two client
  roots — a routine setup for sharing one file across projects — will see the hardlink refusal.

**Compatibility:** additive. A ledger valid under 0.2.2 stays valid — `baselines` is empty in every
ledger that exists, because nothing has ever written one, and `portable` is optional everywhere,
including on every RUN record written before this release, so no existing ledger is invalidated.

## 0.2.2 - 2026-07-30

- compares `known_projects[].last_digest` against the referenced ledger when that ledger is passed
  in the same invocation, closing a gap where a wrong-but-well-formed digest was indistinguishable
  from a correct one; the comparison never opens a path read out of ledger content, so it cannot be
  steered by a crafted `ledger_path`;
- checks the `id_authority` ledger's `sequences` against every record in the verified set rather
  than only its own, since the ledger designated as sole ID authority normally holds no records and
  was therefore the one ledger whose allocation counter nothing validated;
- defines a backlog entry's `id` as a back-reference to the record whose evidence produced the
  finding, deliberately not unique, and checks that it resolves to a record that exists;
- requires every RUN record to name `targets` in `self_reported`, because `verify` checks each
  target's shape and can never check that the array covers what the run changed;
- states in `references/LEDGER.md` that a digest is taken from the referenced ledger's final
  on-disk bytes, and that the sequence check is a floor rather than the equality the prose implied;
- guards the marketplace plugin-entry count and the evaluation-case count stated in
  `docs/SUBMISSION.md`, neither of which had a check.

**Compatibility:** a ledger that validated clean under 0.2.1 may now produce findings. The new
checks describe conditions that were always wrong and merely unobserved. Two are hard requirements
rather than detections: add `"targets"` to every RUN record's `self_reported` array; and, for
whichever ledger holds `id_authority: true`, raise `sequences[prefix]` to cover every identifier
of that prefix anywhere in the verified set, not only that ledger's own records — bump the
authority's counters. A user who followed the previous `references/LEDGER.md`, which said a
ledger's sequences must cover "its own records", can land here: a global ledger with
`id_authority: true`, no records of its own, and `sequences.MAT: 0` validated clean against a
project ledger holding `MAT-2026-000` with `sequences.MAT: 1` under 0.2.1, and now reports
`sequences.MAT is 0 but the ID authority must cover MAT-2026-000, allocated in project.json`.

## 0.2.1 - 2026-07-30

- corrects `.agents/plugins/marketplace.json`, the OpenAI Codex marketplace manifest, whose
  `ref` still pinned `v0.1.3`; because a pinned ref never advances and `codex plugin marketplace
  upgrade` refreshes the catalog rather than an installed plugin, every new Codex install
  resolved 0.1.3 and 0.2.0 was unreachable through that path;
- corrects the Codex install command and the Skill asset name in `README.md`, and the listing
  version and evaluation-suite case count in `docs/SUBMISSION.md`;
- adds `packaging/tests/test_version_consistency.py`, which elects `.claude-plugin/plugin.json`
  as the single source of truth for the version and fails when any of the seven other pins drifts
  from it, naming the file that drifted;
- documents that test in `packaging/README.md` as the authoritative list of version pins,
  replacing per-release checklists that named four files while seven carry the version;
- adds the release documents for 0.2.0 and 0.2.1;
- excludes `__pycache__` directories and `.pyc`/`.pyo`/`.pyd` files from the archive walk in
  `packaging/scripts/package_plugin.py`; `build` and `verify` shared that walk, so `verify`
  could not catch it, and published archives carried whatever compiled bytecode happened to
  sit under `skills/agent-ingest-audit-optimize/assets/scripts/__pycache__/` on the build
  machine, meaning republished checksums could not be reproduced from a clean checkout,
  contradicting the deterministic-packaging claim in `docs/SUBMISSION.md`.

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
