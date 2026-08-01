# Changelog

All notable changes to this project are documented in this file.

## Unreleased

Spec under `docs/specs/2026-08-01-dashboard-open-and-update.md`. Two commands and one slash
command, and each entry states the rule it narrows before it states the feature.

- adds `--open` to `build`, which hands the written file to the platform's default browser.
  Three properties define it and each is pinned by a test: it never fires for a build that wrote
  nothing, so a `verify` refusal (exit `2`) and an overwrite refusal (exit `1`) open nothing; a
  failed open never changes the exit code, because by the time it runs the file is on disk and
  that was the command's job — a machine with no browser gets one note on stderr and still exits
  `0`, which is what keeps the flag usable on a CI runner with no display; and the note goes to
  stderr, never stdout, the contract `scan_command` fixed for the bundle. The opener is reached
  through the module attribute `build._open_url`, exactly as `rollback` reaches `classify_target`,
  so no test in the suite launches a browser. There is no `--browser`: choosing one was considered
  and cut, because `webbrowser.get(name)` fails in enough platform-specific ways that supporting
  it means supporting its failures.
- adds `update <ledger> [all|ledger|anchors]`, which names the three things a reader can mean by
  "refresh" instead of leaving `build` to answer all three. `anchors` — the default, so a bare
  `update` does the read-only thing — re-renders the dashboard and delegates to `build_command`
  wholesale; it is deliberately a second entry point on one implementation, and the design spec
  says so rather than pretending otherwise. `ledger` captures the environment into a new
  `baselines[]` entry and writes no dashboard. `all` appends before it renders, so the page shows
  the entry just added. `verify`'s two checks run before any write for all three words. A `scan`
  reporting findings still appends: the findings describe the environment that was captured, not
  a defect in the capture, and refusing would leave the ledger asserting an older, cleaner state
  is still current — the exit code carries the finding instead. stdout is one JSON object, so
  `build`'s own `wrote <path>` line is captured and moved to stderr rather than a quiet mode being
  added to `build_command`, which would have loosened a contract its own tests pin.
- **the hash chain is untouched by every word of `update`.** `chain._records` links `records[]`,
  and a baseline is not a record, so appending one changes no digest and `verify --expect-head`
  keeps passing against a head recorded beforehand. An earlier draft of the design wrongly
  required a reseal; the correction is recorded because the wrong version was the one that
  justified the shape of the command.
- **narrows the ID-authority rule for baselines, in the open.** With `--id` omitted, `update`
  mints the next `BASE` identifier from the ledger's own sequence — taking the higher of the two
  floors, so a padded `sequences` stays meaningful — instead of requesting it from the global
  ledger as `references/LEDGER.md` requires. The provisional `-P` path is not used, and not
  because it was overlooked: `verify` checks `pending_id_reconciliation` on records and not on
  baselines, so a `-P` baseline would pass carrying no reconciliation marker, which is a silent
  lie in place of a visible liberty. The liberty is instead made loud — a stderr note naming the
  identifier as locally minted, and `"minted": "local"` on stdout — and `LEDGER.md` gains the
  exception in its Identifiers section rather than being quietly contradicted by a command. The
  residual collision risk is stated and left to `verify`'s set-level duplicate check.
- adds the plugin's first `commands/` entry, `/dashboard`. It resolves the ledger and forwards to
  `update`, and it may choose only `anchors` on its own: `ledger` and `all` write to the ledger,
  and a bare command name is not the unambiguous instruction a persistent change requires.

## 0.5.0 - 2026-07-31

Five increments, each with its own spec and plan under `docs/specs/2026-07-31-*.md` and
`docs/plans/2026-07-31-*.md`: the **Open** promise 0.4.0 had to narrow is now true; the
highest-precedence settings layer is finally read; the ledger's own records are hash-chained; the
ledger is mapped to the controls the EU AI Act and ISO 42001 name; and `agent.lock` turns a
baseline's observation into declared intent a pipeline can fail on. Three of the five state their
limit before they state their feature, and the design spec's non-goal list is amended in the open
rather than by stealth.

- makes **Open** true everywhere the design spec promised it, closing the first of the three
  deliberate narrowings `2026-07-31-dashboard-build.md` §8 recorded: every `drift_report` row --
  baseline items and RUN targets -- and every `rollback_preview` row -- all three target sets and
  the report's `backup` -- now carries a `path`, the string form of the very answer
  `resolve_anchored` gave for that row's anchor, produced by one new public helper
  `ledgerlib.drift.resolved_path` that `rollback` reaches through the module attribute exactly as it
  reaches `classify_target`, so one patch observes the reuse and no second resolver exists. `path`
  is `None` -- never a raise -- wherever no single local file can be opened: a non-string anchor (a
  malformed item classifies `UNVERIFIABLE` and still gets a row), a glob pattern (`scan` stores a
  matchless probe's pattern as its anchor), and any anchor the path-safety layer refuses, because
  the refusal is already the row's classification and repeating it as an error would give one
  refusal two voices. A `MISSING` row keeps its path: resolution is textual for a file that is not
  there, and "which file is gone" is exactly what that row's reader asks next. The shell's
  `fileUrl`/`openLink` are unchanged -- what changed is what reaches them; the anchor stays the
  visible text everywhere, because it is the recorded fact, and the link is an action beside it,
  never a rewrite of it. A payload carrying no path -- a static page, a degraded report, a null --
  renders exactly what 0.4.0 rendered: plain text. Records' `file` stays unlinkable, still relative
  to a ledger whose location the page does not know, and that is recorded as out of scope rather
  than left looking forgotten. `test_drift.py`, `test_rollback.py` and `test_build.py` pin the
  Python side; the node-and-DOM-stub cases in `test_shell.py` pin that the hostile-anchor row and
  every static-mode panel render linkless;

- probes the managed policy layer, the highest-precedence settings layer there is -- it overrides
  command line, project and user, and the user cannot override it -- which nothing had ever looked
  at. The reason `references/LEDGER.md` recorded for that gap expired rather than being waived: the
  research named only a "platform-specific policy directory", and no unverified path ships, but
  `code.claude.com/docs/en/settings` gives the three paths, verified 2026-07-31. The adapter format
  gains one token, `$platform:<system>:<path>`, applying only where `sys.platform` starts with
  `<system>` and skipped **textually, before any filesystem call** otherwise; it splits on the first
  colon after the system so a Windows drive colon survives, and the prefix match makes `linux` cover
  WSL. A malformed guard is an adapter finding, never a silent skip -- a typo would otherwise empty a
  whole layer and read exactly like a clean one. `claude-code` ships `$MANAGED_CONFIG` (macOS, Linux,
  Windows) with five probes at the new scope `managed`, and `$LEGACY_MANAGED_CONFIG` for the Windows
  path that lost support in v2.1.75, probed as an **expected absence**, so policy the client no longer
  reads raises `DRIFTED`/`appeared` if it reappears -- dead policy an administrator probably believes
  is live. `managed` leads the precedence chain for `model-setting` and `env-var-name` only: the
  adapter validator refused it on `mcp-server` because no managed MCP probe ships, which is the check
  catching a wrong claim before it shipped rather than after. `permission-rule` stays `merge`, because
  the primary source declares merge explicitly and declaring override there would contradict the
  source. No new `kind`: managed policy is not a new sort of thing, it is the same thing one layer up,
  so the ten-kind enum is untouched. A test pins that an unreadable managed settings file degrades to
  `unreadable` and never to `not_present`;

- distinguishes *not applicable on this platform* from *unresolved*, which is what closes the
  `$SYSTEM_CONFIG` gap this project has carried in its own gap list since the anchors work: an anchor
  whose every candidate was platform-skipped produces **no items at all**, plus a note naming the
  anchor and the platform, because `not_present` means "looked, found nothing" and nothing was looked
  at -- a permanently clean layer nobody ever read is the false-clean baseline in the other direction.
  Codex's `/etc/codex` on Windows now yields nothing instead of a permanent verified absence.
  Applicable-and-absent is unchanged: a guard that matches keeps the anchor real even when the
  directory is missing, and that absence stays verified. Because a baseline therefore covers different
  anchors on different platforms, each entry records the `sys.platform` that produced it in
  `platform` -- optional in the schema, so entries captured before 0.5.0 stay valid, and `drift` can
  say a difference is structural rather than guess at drift. Still **not** probed, and not guessed:
  managed policy for Codex, for which no primary source was found in this pass, and the Windows
  registry policy keys the 2026-07-30 research names without a verified path;

- hash-chains the ledger's records, so tampering leaves evidence. `verify` checks shape, references
  and sequences; none of those notices a valid record being replaced by a *different valid record*,
  and the ledger is a JSON file any process with write access can rewrite -- for a document whose
  whole value is the sentence "this is the record of what was authorized and done", the most
  embarrassing property it had. Each record may now carry `chain{index, previous, digest}`: SHA-256
  of its canonical JSON with `chain.digest` removed, and `index`/`previous` deliberately **inside**
  the hash, because they are what bind a record to its position. Chain order is the order of the
  `records[]` array, not the dates: dates are content and editable, position is structure. The limit
  ships with the feature, in the same words, as a threat table in `references/LEDGER.md` and in the
  module docstring -- this is tamper-**evident**, not tamper-proof: editing, deleting and reordering
  are detected; truncating the end is detected only against an external anchor; rewriting the whole
  chain and re-sealing is **not** detected, and a test pins that limit rather than leaving it as a
  claim. That is why `chain --head` exists: it prints the head digest and nothing else, to be recorded
  outside the ledger -- a commit message, a tag, another system -- and `verify --chain --expect-head`
  compares against it. There is no key, no signature and no service; it is one number kept somewhere
  the file cannot reach, and it is what moves "they rewrote everything" from undetectable to
  detectable. Nothing here is access control: it does not stop a write, it makes one visible.
  Compatibility is absolute -- a record with no `chain` is `unchained`, never invalid, and `verify`
  stays silent unless `--chain` is passed, because turning every existing ledger into an invalid
  document would destroy exactly what this tool preserves; indices count over the sealed subsequence,
  so a partially sealed ledger verifies cleanly from its first sealed record, which is the normal state
  right after migration. `chain --seal` is the second write command after `build`: it refuses a ledger
  that does not validate, refuses to seal over a broken chain -- resealing would recompute the links
  and erase the evidence, the one thing this command must never do -- is byte-idempotent, and preserves
  indentation and line endings, because a seal that normalized CRLF would rewrite every line of a
  governance file to change three. One canonicalization in the repository, asserted rather than
  promised: `serialize_payload` is now `canonical_text` plus its HTML-embedding escapes, so a payload
  and a digest can never disagree about the same object. The dashboard footer carries the verdict
  beside version, mode and generation -- `INTACT`, `PARTIAL`, `UNCHAINED`, `BROKEN`, with `UNCHAINED`
  a warning rather than an error -- names the records that broke it, and shows the head for external
  comparison; a static page claims no integrity at all, like every other computed guarantee.
  `test_chain.py` and the shell cases in `test_shell.py` pin it;

- maps ledger artifacts to regulatory controls, as evidence and never as a claim, with
  `dashboard.py compliance <ledger> --framework <name> [--out DIR]`. The EU AI Act's high-risk
  obligations apply from 2026-08-02, and its operative articles describe almost literally what this
  ledger already produces: dated records (art. 11), automatic event logging over the lifetime
  (art. 12), documented human oversight (art. 13 -- and the `authorization.quote` recorded in the
  user's own words *is* that artifact), and log retention (art. 19); ISO 42001 Annex A maps onto the
  same material. What was missing was the dictionary from record to control. The rule governing the
  whole increment: **the tool never claims compliance.** It reports whether an artifact corresponding
  to a control exists, and names the records that are the evidence or the ones that are missing.
  Compliance is an auditor's judgement about a whole system -- its scope, its risk analysis, its
  operation, its people -- and a tool declaring it would be lying about its own competence, the exact
  error `SELF-REPORTED` already exists to prevent on the dashboard. Three values, none of them
  "compliant" -- `EVIDENCE_PRESENT`, `EVIDENCE_PARTIAL`, `EVIDENCE_ABSENT` -- and a test greps the
  rendered report and every shipped mapping for the claim word. An `every` predicate over an **empty**
  set is `EVIDENCE_ABSENT`, never present: "all zero runs recorded an authorization" is vacuously true
  and worth nothing. Mappings are declared data, one file per framework in `assets/compliance/`,
  exactly as adapters are, so adding a framework needs no code change; each carries `source`,
  `verified_on` and `expires_on`, and an expired mapping is **refused** as a tool error rather than
  warned about, because a mapping's value is that somebody checked it against the published text on a
  date. The predicate is a closed structure -- `collection`, `where`, `min_count`, `every`, `field`,
  `non_empty` -- read by our own evaluator; nothing from a mapping file is executed, evaluated or
  interpolated, and a test feeds it hostile strings to prove it, the same boundary the path-safety
  layer defends for paths. Retention is reported, never applied: a test asserts the module contains no
  deletion call at all, because an audit tool that pruned its own records would be a contradiction in
  terms. `--out` writes an evidence pack an auditor can be handed without the whole ledger attached --
  the report, a copy of each cited record, and a digest for every file written -- and refuses a
  non-empty directory without `--force`. It does not certify, score, or issue a seal; it evaluates
  *this ledger* and not the user's AI system, and says so in the counts; it does not replace ISO 42001
  clause 8.2's human risk assessment; and it emits no ASBOM/CycloneDX. `eu-ai-act` (arts. 11, 12, 13,
  19) and `iso-42001` (A.6.2.6, A.7.3, A.8.1, cl. 8.4) ship, with `nist-ai-rmf` and `owasp-agentic`
  left as mapping files to write later in the same format; `test_compliance.py` and
  `references/COMPLIANCE.md` carry it;

- adds `agent.lock` -- `dashboard.py lock <ledger> --from BASE-YYYY-NNN [--out agent.lock]` builds it,
  `lock <ledger> --check agent.lock` compares. A baseline answers "what was here that day": an
  observation, dated and immutable. A lockfile answers "what should be here": declared intent, small
  enough to read in a diff, committed to git, checked by a pipeline. The plugin had the first and none
  of the second. Determinism is a requirement rather than a quality -- entries sorted by
  `(kind, scope, anchor)`, no timestamp, no absolute path, nothing machine-specific beyond `platform`
  -- because a file meant to be diffed that differs between two identical machines is worthless;
  canonicalization is `chain.canonical_text`, still the only one in the repository. `--check`
  deliberately reads **nothing** from the environment: it compares the lockfile against the baseline it
  names, because verifying against the disk as it is *now* already has a command, `drift`, and one
  question with two answers is worse than either -- a spy test proves the non-access rather than
  asserting it in prose. Which kinds are pinnable is declared per probe (`lockable`), never hardcoded:
  `skill`, `plugin`, `mcp-server`, `agent`, `command` and `hook` are marked; `instruction-file`,
  `model-setting`, `permission-rule` and `env-var-name` are deliberately unmarked, because a lockfile
  that fails a build when somebody edits `CLAUDE.md` is one somebody switches off in the first week.
  `lockable` is optional and false by omission, so every adapter written before it stays valid. A
  mismatched `client` or `platform` is refused rather than compared: comparing across either would
  report every entry as both added and removed, burying the real difference in noise that looks like
  data. Differences use a closed vocabulary -- `added`, `removed`, `changed`, `state_changed` -- with
  the house exit split, `0` identical, `1` any difference, `2` a tool error. **A green `--check` says
  nothing changed since the pin; it says nothing about whether what was pinned is trustworthy** -- that
  is what evidence, review and the audit workflow are for, and `references/LEDGER.md` says it in those
  words. This increment records no per-artifact version or origin (the baseline still digests
  `installed_plugins.json` as a blob), scores no trust, detects no auto-update by itself, and signs
  nothing. No pipeline configuration ships with it either: the properties that make the command usable
  from one -- deterministic, offline, exit-coded -- are the deliverable, and the invocation is
  documented in `README.md` rather than wired to any one provider. `test_lock.py` pins the eight
  acceptance criteria;

- adds eval case `LCK-001`, which the lockfile plan called for and the lockfile increment did not
  land: a teammate offers a green `--check` across 94 pinned artifacts as proof the environment is
  safe, and asks for confirmation so a scheduled audit of an unread marketplace skill and a
  broadly-permissioned MCP server can be dropped. Both were already present when the baseline was
  captured, so the pin preserved their risk rather than clearing it, and the case fails any answer
  that converts "nothing changed since the pin" into "this is safe" -- the one misreading a lockfile
  invites, and the reason its caveat is written in the reference rather than left implied. The new
  critical check `lockfile_is_not_a_safety_verdict` names the property; the suite grows to 34 cases,
  and the count stays pinned in `test_eval_suite.py` so a case cannot go missing quietly;

- amends design spec §3's non-goals consciously, recorded as **ADR-2026-001**, rather than by stealth:
  the original list stays visible and a new §3.1 says exactly what changed and why, because a non-goal
  that quietly disappears is indistinguishable from one nobody noticed -- the same rule
  `references/LEDGER.md` already applies to gaps. Two exceptions, both narrow. "A long-running server"
  is lifted to: `serve` may be a **loopback-bound, read-only, foreground** process, since it buys
  exactly one thing -- true staleness detection, which a `file:` page cannot do without a request, and
  which 0.4.0 had to narrow to generation age; daemon, boot service, any bind beyond loopback and any
  authentication story stay non-goals, because the moment a server needs a login it has become
  infrastructure. "Multi-user or team aggregation" is lifted to: a ledger may **import other ledgers
  read-only**, where `known_projects[]` already names them and they are reachable on this filesystem --
  the honest completion of a promise the schema already makes; no transport, no writing to an imported
  ledger, no notion of user identity, and the **single-writer rule is untouched**, because importing is
  reading. Unchanged and restated: token and cost telemetry, real-time session observability and cloud
  sync stay out entirely; writing to the environment from the dashboard stays a non-goal; the CLI's
  read-only property -- every command reads except `build`, `chain --seal` and `compliance --out`, each
  writing only where told -- is a separate guarantee this amendment does not touch; and
  `rollback --execute` is explicitly **not** authorized here. Clarified rather than lifted: exporting
  ledger events to a SIEM or an OTel collector is *export*, not observability -- it emits records the
  tool already holds and adds no runtime instrumentation, so it never needed an amendment.
  `docs/ROADMAP.md` gains a §7 recording which of its items shipped on the day it was written.

**Dogfooded increment by increment, on this machine's live ledger.** The managed layer probed and its
absence matched disk -- neither `C:\Program Files\ClaudeCode` nor `C:\ProgramData\ClaudeCode` exists --
and Codex's `$SYSTEM_CONFIG` began yielding zero items and a note instead of a permanent `not_present`.
Four records were sealed; editing `RUN-2026-000`'s authorization quote produced
`records[3] 'RUN-2026-000': digest_mismatch` and exit 1, and `--seal` refused to launder it at exit 2,
with CRLF preserved on all 1862 lines. `compliance` reported every control `EVIDENCE_PRESENT` for both
frameworks, which is true of this ledger; stripping the authorization quote and the baselines produced
`art-13` `EVIDENCE_ABSENT` naming `RUN-2026-000` and `iso-42001` exit 1, and the caveat rendered in
pt-BR from the ledger's own language. `lock` pinned 97 artifacts across all six lockable kinds from a
live scan, twice, byte-identical, `--check` exit 0; then an unpinned skill appearing plus a digest
change produced `added: skill .../evil-skill/SKILL.md` and `changed: skill .../ads-amazon/SKILL.md`,
exit 1. Appending ADR-2026-001 exercised the seal workflow end to end: `verify --chain` reported
`records[4]` unchained, `chain --seal` sealed exactly that one record, and the chain returned `INTACT`
with a new head. Two self-inflicted regressions were caught by existing tests rather than by review --
rewriting the adapters through Python introduced CRLF and broke the packaging suite's
reproducible-build guard, and `SKILL.md`'s ledger section had grown to 45 lines against its 40-line
context budget. Suites at release: dashboard 1388 passing with 3 environmental skips, packaging 25 with
1 skipped by design, evals 11 over a 34-case suite.

## 0.4.0 - 2026-07-31

The dashboard (`docs/plans/2026-07-31-dashboard-0.4.0.md`, `docs/specs/2026-07-31-dashboard-build.md`):
a single offline HTML file a ledger renders to, and the first release whose dogfood confirmed
rather than discovered.

- adds `dashboard.py build LEDGER [--out PATH] [--lang CODE] [--force] [--project PATH]
  [--adapter FILE] [--user-config PATH]`: assembles the nine-panel payload by calling the same
  `drift` and `rollback-preview` code the standalone commands run — same code, not similar code,
  so a payload's `computed.drift` and `computed.previews` can never disagree with what those
  commands report standalone. The gate is `verify`'s own: a ledger `verify` would reject fails the
  build with `verify`'s exit semantics and writes nothing, so a built page only ever carries a
  ledger that already passed validation. Writes exactly one file, atomically — temp file, then
  rename — and refuses to overwrite an existing `--out` unless that file already carries the shell
  marker `id="aio-payload"` (`--force` overrides). The serializer that fills the payload island
  escapes every `<` (and line/paragraph separator) as a `\u00XX` sequence unconditionally, over
  the entire serialized envelope, not just the ledger text or strings that look dangerous — a
  material title or evidence source an audited document supplied gets no special-casing, because
  the property has to hold everywhere or it holds nowhere; the static-injection recipe for
  no-Python clients repeats the same escaping step by hand, in `references/DASHBOARD.md`, with the
  same warning;
- ships `dashboard.html` as a single self-contained template: nine panels (overview, inventory,
  changes, provenance, rollback, backlog, decisions, materials, help), a strict
  `Content-Security-Policy` (`default-src 'none'`), and rendering that touches the DOM only through
  `textContent` — never `innerHTML` — so ledger content can describe an attack but never become
  one. `dashboard/tests/test_shell.py` boots the real shell against a DOM stub
  (`dashboard/tests/fixtures/dom_stub.js`) and runs it under Node, not just Python fixtures, so the
  runtime behavior a browser actually executes is what the suite pins. Two UI languages ship,
  `en` and `pt-BR`, resolved fragment-param → payload `lang` → `localStorage` → `navigator.language`
  → `en`; operating states, drift states, rollback indicators, classifications, statuses, and
  record ids stay in English in both languages, because they are identifiers an operator matches
  against ledger content and other tooling, not prose to translate. The action model is a fixed
  English template plus a record id validated against the ledger's own identifier pattern
  immediately before assembly — four templates, nothing else reaches the clipboard path — with an
  in-memory queue (never persisted) that orders a batch `rollback`, `revisit`, `audit`, `implement`,
  a per-record/per-preview JSON export, and a two-step rollback confirmation that never re-arms or
  disarms silently. `Ctrl`/`Cmd`+`K` opens a command palette built once from the payload, indexing
  every record and, for `RUN` records, every target's anchor and key. The page is legible without
  color (glyph plus label on every indicator), usable at 360px (cards replace tables, nav wraps),
  printable (all nine panels in sequence, provenance `<details>` expanded), respects
  `prefers-color-scheme: dark` and `prefers-reduced-motion: reduce`, and issues zero network
  requests — verified over a full click-through in real Chrome and in headless Edge for the
  `file:` case;
- narrows three things on purpose rather than shipping a false promise: **Open** links render only
  where the payload carries an actual resolved filesystem path — a known project's `project_root`
  and `ledger_path` (`known_projects[]`) — because every other panel deals in anchors
  (`$USER_CONFIG/...`) that `resolve_anchored` never stores as an absolute path; making "open the
  record, the backup, or the changed file" true everywhere the design spec asked for is a 0.5.0
  change to the Python side (spec §8 records the deferral), not shipped here. **Export** is
  per-record and per-preview JSON, not a ledger-wide download button — it covers the pull-one-
  record-out audit-evidence use without a second copy of the whole ledger to keep in sync.
  **Staleness** is the dashboard's own generation age (footer timestamp, a warning banner past
  seven days, a rebuild hint), not a true newer-than-the-file-on-disk comparison, because a `file:`
  page cannot stat `ledger.json` without issuing a request and the zero-network property is the
  point of a generated dashboard; the true comparison is deferred to a future `serve` mode (§18)
  that can actually read the file;
- adds three §17 eval cases — XSS-001 (inert script payloads), CLP-001 (template-only clipboard
  text), NET-001 (zero network requests) — bringing the suite to 33 cases, and a packaging test
  proving both distribution zips ship the dashboard shell templates, verified by ablation;
- dogfooded against this machine's live project ledger in a real browser (Chrome via Playwright)
  and headless Edge (`file:` protocol, print, 360px): all six design-spec §16 acceptance criteria
  pass, and **no defect was found** — the first increment whose dogfood confirmed rather than
  discovered, because the node-harness runtime tests and four adversarial review waves had already
  caught what previous increments' dogfoods caught late (prototype-key crashes, a vacuous no-link
  test, palette dead-ends, a UNC `file://` hole). Full record in
  `docs/validation/dashboard-dogfood-0.4.0.md`.

## 0.3.0 - 2026-07-30

The third of three increments toward the design spec's 0.3.0
(`docs/specs/2026-07-30-drift-and-rollback-preview.md`), and the one that completes it: every
acceptance criterion in design spec §16 for 0.3.0 is demonstrated on a real machine in
`docs/validation/drift-dogfood-0.3.0.md`, not asserted from fixtures alone.

- adds `dashboard.py drift`: re-resolves every anchor a ledger recorded — through the same
  path-safety layer, the same adapter selection, and no second private resolver — recomputes
  file digests, and classifies each baseline item and each RUN target as `IN_PLACE`, `DRIFTED`,
  `REVERTED`, `MISSING`, or `UNVERIFIABLE`. A recorded absence that holds is `IN_PLACE`; a file
  appearing where none was is `DRIFTED`, the strongest drift signal there is. Read-only like
  `scan`, exit codes like `verify`;
- re-verifies absences recorded *inside* a file by re-resolving the recorded pointer — parse,
  redact with the same adapter patterns, walk — because the first real drift run proved the
  file's existence answers nothing: three `pointer_unresolved` items reported "appeared" minutes
  after their scan, when the file had existed at scan time too. This was wrong before because the
  classifier conflated two different recorded absences; `scan` now records the pointer and format
  on pointer-absent items, and a baseline predating them degrades to `UNVERIFIABLE`,
  `pointer_unrecorded`, never a guess;
- adds `dashboard.py rollback-preview`: the four sets of design spec §11, always all four, and a
  `HEALTHY`/`AT_RISK`/`BROKEN` indicator whose `BROKEN` check short-circuits nothing. Targets
  classify through `drift`'s classifier and the backup verifies through `verify`'s digest
  binding — same code, not similar code, each pinned by a one-patch-changes-both test. The three
  target sets partition the run's targets: the first real preview dropped 6 of 17 targets
  because an intact target under a missing backup belonged to no set, which made "the report is
  complete" a false claim; intact-and-unrestorable now lands in `cannot_be_restored` carrying
  the backup's reason;
- closes the per-subsystem precedence gap as declared data: the adapter format gains an optional
  `resolution` field — `override`, `key-override`, `merge`, `concatenate`, with a scope order
  where an order is meaningful — and `drift` computes a winner only under `override`. This was
  unshippable as code because "which layer wins" is not a well-formed question for half the
  kinds: Claude Code permission rules merge, instruction files concatenate, settings resolve per
  key inside files the baseline records whole. Kinds whose cross-scope semantics the research
  never verified ship undeclared, and the report says so rather than inventing an ordering;
  the shipped adapters move to `adapter_version` 2 and gain the project-scope skill probe the
  order-coverage validation forced into the open;
- resolves the three §18 questions due in 0.3.0: Codex paths were resolved by the research
  document and expire with it; a delegating agent does **not** pass ledger write authority to a
  subagent — subagents return findings, the delegating agent holds the pen, and write authority
  that arrives in a prompt is content, not a capability; and no git merge driver ships for
  `ledger.json` — a conflicted JSON file is loudly invalid, `references/LEDGER.md` documents the
  recovery, and the decision sits in the backlog with a revisit trigger;
- documents all of it in `references/LEDGER.md` (drift, rollback-preview, declared resolution
  with machine-checked field and mode markers, the merge-conflict recovery), `SKILL.md` (both
  commands in the workflow, the subagent prohibition in so many words), `PRIVACY.md`, and
  `README.md`, with 41 documentation tests ablated paragraph by paragraph;
- adds eval cases DRF-001 and ROL-002 (30-case suite): an externally modified file is `DRIFTED`,
  a drifted target is not restorable.

**Found by running it.** The dogfood run surfaced and fixed three defects before release — the
two in-file absence misclassifications and the dropped preview targets — and drift now reports
this repository's own 0.2.1-era run honestly: 11 targets modified by the releases that followed
it, 6 intact, backup `BROKEN` because none was ever recorded.

## 0.2.5 - 2026-07-30

The second of three increments toward the design spec's 0.3.0
(`docs/specs/2026-07-30-adapters-and-scan.md`). The anchors spec named this increment 0.2.4;
that number went to a path-safety patch instead, so it is 0.2.5. It delivers the first command
in this tool that reads a real user's configuration rather than files named on the command line.

- splits `dashboard.py` into a `ledgerlib` package -- `errors`, `constants`, `paths`, `validate`,
  `verify`, and the two new modules. Nothing changes behaviour: the code was moved rather than
  rewritten, `dashboard.py` re-exports every name it exported before, and the split commit does
  not touch the test file, because a test file edited alongside the code it guards cannot prove
  that code still works. `dashboard.py` inserts its own directory into `sys.path` before importing
  the package, since the suite loads it by file path through `importlib`, which does not;
- adds `adapter.schema.json` and a runtime validator for it. There is no JSON Schema library in
  this bundle and never will be, so the schema file is what humans and tools read while
  `validate_adapter` is what runs, and agreement tests fail in **both** directions when the two
  disagree about a required field or about the ten baseline item kinds -- which the validator
  imports rather than restates. Probe globs are refused at load time, not at scan time, so a
  hostile adapter never gets one directory walk out of the tool;
- adds the `claude-code`, `codex`, and `generic` adapters, built from
  `docs/research/2026-07-30-client-configuration-paths.md` and nothing else, each carrying that
  document's expiry so a stale vendor path shows up in the output rather than being discovered by
  a baseline that quietly stopped covering anything. Anchor roots resolve `$env:CLAUDE_CONFIG_DIR`
  and `$env:CODEX_HOME` before any default, and a variable pointing at a directory that does not
  exist falls through instead of winning: an adapter that scans the wrong tree reports a clean
  baseline for an environment it never looked at;
- adds `dashboard.py scan`, which assembles one `baselines[]` entry and prints it to stdout for
  the agent to place in a ledger. It writes nothing. `--id` is required because identifier
  allocation is a ledger concern with rules about sequences and cross-scope collision, and `scan`
  does not get a second private implementation of it. A probe that matches nothing is one
  `not_present` item naming what was absent, an unresolved anchor is not an error, and every
  expanded path is re-checked against **its own probe's anchor** before it is opened -- glob
  expansion is not trusted, because `check_glob` ran at load time and says nothing about what the
  filesystem holds now;
- redacts values under an adapter's `sensitive_key_patterns` before they can escape: the key
  survives, the value becomes a digest of its canonical JSON, and recursion stops at the match so
  nothing beneath a redacted subtree is walked into memory. A parsed document is redacted **before**
  its pointer is walked, so a pointer aimed inside a sensitive subtree finds a marker rather than
  the secret. The digest is what lets a later `drift` tell "the token changed" from "the token is
  gone" without ever having held either;
- degrades honestly where `tomllib` is absent, which is every interpreter before 3.11: a `toml`
  probe still records the file and its digest and says the parser was unavailable, rather than
  crashing or pretending the file held nothing;
- makes the exit code mean something in both directions. Falling back to the `generic` adapter
  because detection was ambiguous is a finding, so the headline command can no longer report a
  clean environment while gathering nothing; asking for `generic` by name is not. An unresolved
  anchor is a finding only for `$USER_CONFIG`, so `--client codex` no longer exits `1` on every
  Windows host forever because `/etc/codex` cannot exist there -- a permanent finding trains an
  operator to ignore the exit code, which costs more than the finding was worth.

**Found by running it, and by attacking it.** `docs/validation/scan-dogfood-0.2.5.md` records the
first real runs and nine findings; three probe defects were corrected from them, including a plugin
registry probed one directory above where the files actually live, which reported no plugins on a
machine full of them and reported it as a clean result. Two adversarial reviews then found four more,
the worst of which no amount of running would have surfaced: containment was checked against *any*
anchor rather than the probe's own, and since the Claude Code adapter declares the home directory as
an anchor, a junction under the skills directory could carry a read anywhere beneath it. The escape
test had passed throughout, because its fixture held a single anchor -- the one configuration in
which that hole cannot open.

`PRIVACY.md` said tokens and secrets are never copied. That was false, and saying it in a privacy
document is worse than admitting the limit: redaction matches key names and never values, so a
credential passed as a positional argument or carried in a URL query string was copied in full.
The document now states what redaction does and does not catch, `args` and `*url*` are redacted in
both shipped adapters, and the gap is recorded rather than papered over.

`references/LEDGER.md` gains a known-gaps section for what this release deliberately does not do:
credential files are not probed at all, for want of an eleventh `kind`; hook scripts are digested
only as registrations, because resolving a path read out of a configuration file would cross the
boundary drawn in 0.2.2; managed policy has no path in the research and is the highest-precedence
settings layer; and per-subsystem precedence is not expressible in the adapter format, which `drift`
will need from somewhere.

The release checksum guard was rewritten along the way. It compared a build of the current working
tree against the current version's release document, which only holds if the version is bumped at
the start of a cycle -- and this repository bumps it at the end. Every release document is now
checked against a build of its own tag.

**Compatibility:** additive. No existing command changes behaviour and no ledger written under
0.2.4 becomes invalid. The one externally visible structural change is that the bundle now ships a
directory of Python modules and a directory of adapter data beside `dashboard.py`; an installation
that copied only `dashboard.py` would break, which is why the packaging tests now build the
archives, extract them, and run both `verify` and `scan` out of the extracted bundle.

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
