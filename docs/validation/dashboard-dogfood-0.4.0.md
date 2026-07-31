# Dashboard dogfood — 0.4.0, 2026-07-31

The first real build of `dashboard.html`, run against this machine's live project ledger
(`.agent-audit/ledger.json`: 4 records, 115 baseline items, 3 backlog entries, pt-BR), and
the design spec §16 acceptance pass for 0.4.0, performed in a real browser (Chrome via
Playwright over localhost) and headless Edge (for `file:`-protocol, print, and 360 px runs).

## The build

- `verify` before: exit 0. `dashboard.py build .agent-audit/ledger.json --project .` →
  exit 0, wrote `.agent-audit/dashboard.html` (281 KB). `verify` after: exit 0 — build
  reads the ledger and writes exactly the one file.
- The page opens in pt-BR (the ledger's own `language`), mode `built`, and the overview
  reports the environment as it is: **1 active change, 12 drifted items, 0 rollbacks at
  risk, 0 expired evidence, 0 unreachable projects**. The 12 drifted are real (releases
  0.2.2–0.3.0 modified recorded targets); previews are honestly absent because
  `RUN-2026-000` kept no backup, and the Rollback panel says so instead of pretending.

## §16 acceptance, item by item

1. **Zero network requests.** Playwright's per-page network log over the full click-through:
   the document fetch and one Chrome-extension content script (the user's Tag Assistant —
   browser-injected, not page-initiated). Nothing else. A separate headless-Edge run over
   `file://` with `--log-net-log`: every non-`file:` URL in the log belongs to Edge's own
   update/telemetry services (componentupdater, config.edge.skype.com, bing NTP), none
   initiated by the document.
2. **Script payload renders inert.** A copy of the live ledger was given the material title
   `</script><script>document.title="PWNED"</script><img src=x onerror=alert(1)>` and a
   backlog reason containing `<!-- sneaky --><style>body{display:none}</style>`. The built
   file kept exactly 3 `<script` openings (the template's own) and zero literal `<` in the
   payload island. In the real browser: title stayed "Governance ledger", `<main>` visible,
   `document.getElementsByTagName("script").length === 3`, zero `img` elements, and both
   hostile strings visible as literal text in their panels.
3. **Legible without color.** Every indicator carries a glyph (`✕`/`▲`/`●`) plus a text
   label; verified in the 360 px screenshot and the panel snapshots.
4. **Usable at 360 px.** Measured in a 360×900 window: `innerWidth` 364,
   `documentElement.scrollWidth` 349, and no element wider than the viewport (a full-DOM
   sweep found zero overflowing elements). Cards replace tables; nav wraps to two rows.
5. **Print → readable PDF.** Headless Edge `--print-to-pdf`: 13 pages, all nine panels in
   sequence, 42 k characters of extractable text including canonical labels (`IN_PLACE`),
   record ids (`RUN-2026-000` — i.e. the provenance `<details>` expanded in print), and the
   pt-BR chrome.
6. **Language switch.** `#lang=en` re-rendered the chrome in English ("Governance ledger",
   "Drifted items") while canonical vocabulary stayed English in both languages — the drift
   card cites `IN_PLACE` verbatim under either language.

## Beyond the checklist

- **Palette:** `Ctrl+K` opened the dialog; typing `RUN-2026-000` matched exactly 1 entry;
  Enter navigated to `#panel=changes&lang=en&f=RUN-2026-000` and closed the dialog.
- **Action model:** "Copy instruction" on `MAT-2026-000` produced exactly
  `Re-audit material MAT-2026-000` in the always-visible read-only textarea — template +
  validated id, nothing else, with a hostile title in the same fixture never reaching any
  copy path.
- **Panels on real data:** 115 inventory rows with drift states joined per item; 17
  provenance chains; backlog and materials populated; Materials renders evidence sources as
  text — zero anchor elements.

## Defects found

None. This is the first increment whose dogfood surfaced no defect — the node-harness
runtime tests (which boot the real shell against real payloads) and four adversarial review
waves had already caught what previous increments' dogfoods caught late: the
prototype-key crashes, the vacuous no-link test, the palette dead-ends, the UNC `file://`
hole. The browser pass confirmed rather than discovered.

## Known cosmetic issue, pre-existing

The live ledger's record titles carry multiply-encoded UTF-8 (mojibake) from an earlier
session; the dashboard reproduces the stored bytes faithfully, as it should. Repairing the
ledger text is a separate, ledger-editing task (backlogged since the 0.3.0 handoff), with
`verify` before and after.

## Environment notes

- The in-app browser pane's `navigate` hung at 300 s twice (as it did for two implementer
  subagents); the acceptance therefore ran through the Playwright MCP attached to the real
  Chrome (localhost HTTP serve of the built file) plus headless Edge for the `file:`
  protocol, print, and viewport runs. No user tabs were touched or resized; the one 360 px
  measurement used a popup that closed itself.
- `tool_version` in the footer reads 0.3.0 until the release commit bumps the pinned
  constant (`packaging/tests` enforces equality with `plugin.json`).
