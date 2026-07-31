# Dashboard and `build` (0.4.0) — Specification

Implements design spec §12 (dashboard), §13 items 1–2 (XSS, clipboard), §14 (degradation),
§16 (0.4.0 acceptance), and three §17 eval additions. Parent:
`docs/specs/2026-07-29-ledger-and-dashboard-design.md`.

The handoff for this increment required the escaping/CSP design to precede any code. It is
therefore section 1 of this document.

## 1. Security design

Ledger content is attacker-influenced: material titles, evidence sources, backlog reasons,
and file paths all originate in audited external material. The dashboard renders all of it.

### 1.1 The injection boundary

The generated `dashboard.html` embeds exactly one data island:

```html
<script type="application/json" id="aio-payload">{...}</script>
```

The serializer is `serialize_payload(payload) -> str`:

1. `json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)`
2. replace, in the serialized text, every `<` with the six characters `\u003c`, and every
   U+2028/U+2029 with `\u2028`/`\u2029`.

`\u003c` is a JSON string escape, so `JSON.parse`
restores the original character — but the *document* never contains a literal `<` inside the
island. `</script>`, `<script>`, and `<!--` are thereby unrepresentable regardless of what
the ledger contains. This is the primary stored-XSS control and it is testable at the Python
layer: `assert "<" not in serialized` — the property is global, not pattern-based.

The shell reads the island with `JSON.parse(document.getElementById("aio-payload").textContent)`.
A parse failure renders a static error state; it never falls through to partial rendering.

### 1.2 Rendering discipline

All DOM construction goes through one helper:

```js
function h(tag, attrs, ...children) // createElement + setAttribute + textContent/append
```

Text always lands via `textContent` or `document.createTextNode`. The following never appear
in the shell, enforced by a static test over the template source (comments and string
literals included — the grep is unconditional):

`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`,
`srcdoc`, `setTimeout("`, `setInterval("`, `javascript:`.

`setAttribute("href", …)` is permitted only for two generated forms: `#`-fragment links and
`file://` links assembled from resolved anchor strings; both pass through a single
`safeHref()` gate that rejects any other scheme.

### 1.3 CSP

The document carries, verbatim:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
```

Per the design spec, hash-based `script-src` is not used (unreliable under `file:` across
browsers). The meta tag is defense in depth; the primary controls are 1.1, 1.2, and the
zero-network evaluation. No `http://` or `https://` literal may appear anywhere in the
*template*; the static test enforces this (the Help panel cites record IDs and commands,
never URLs). The *generated* file necessarily carries ledger evidence URLs inside the
payload island as inert JSON string data; they render as text, never as links, and the
zero-network property rests on the rendering discipline plus the CSP, not on their absence.

### 1.4 Clipboard actions

Instruction text is assembled exclusively as `TEMPLATES[action] + " " + id` where
`TEMPLATES` is a frozen English dictionary in the shell and `id` matched
`^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$` immediately before assembly. No other string
reaches the clipboard path. Templates stay English in every UI language — they address the
agent, not the reader.

`file:` pages are not secure contexts, so `navigator.clipboard` is typically absent. Tiered:
try `navigator.clipboard.writeText`; fall back to range-selection + `document.execCommand("copy")`;
in all cases the instruction text is also rendered visibly in a read-only `<textarea>` so
manual copy always works. The Rollback action additionally requires a two-step confirmation
and shows the embedded §11 preview before its copy control enables.

## 2. Payload contract

```jsonc
{
  "payload_schema": 1,
  "mode": "built",              // "built" (dashboard.py) or "static" (template default)
  "generated_at": "2026-07-31T12:00:00Z",  // null in static mode
  "tool_version": "0.4.0",                 // null in static mode
  "lang": "pt-BR",              // build --lang or ledger.language; null in static mode
  "ledger": { ... },            // the ledger document, verbatim; null in the template
  "computed": {                 // null in static mode — the shell must degrade honestly
    "drift":    { ... },        // dashboard.py drift report for this ledger
    "previews": { "RUN-2026-000": { ... } },  // rollback-preview per RUN with a backup
    "expired_evidence": [ {"record": "MAT-…", "source": "…", "expires_on": "…"} ],
    "unreachable_projects": [ "…" ]
  }
}
```

`computed.drift` and each `previews` entry are the exact JSON the 0.3.0 commands print —
same code, not similar code. If a sub-computation fails, its key holds
`{"error": "<message>"}` and the shell shows the panel in a degraded state naming the
missing guarantee (design spec §14); build still succeeds. A ledger that `verify` would
reject — `validate_ledger` plus the single-document `validate_collection` pass, same code —
fails the build with `verify`'s exit semantics and writes nothing. There is consequently no
`computed.verify` key: a built payload exists only for a ledger that already passed
verification, and the shell may state exactly that in built mode.

The template ships with the island containing
`{"payload_schema":1,"mode":"static","generated_at":null,"tool_version":null,"lang":null,"ledger":null,"computed":null}`.
The no-Python degradation path (design spec §14) replaces the island's content with the raw
ledger wrapped in this same envelope (`mode:"static"`), applying the 1.1 escaping by string
replacement; `references/DASHBOARD.md` carries the instruction. In static mode the overview
panel states that digest verification, drift, and rollback preview are unavailable.

## 3. `build` command

```
dashboard.py build LEDGER [--out PATH] [--lang CODE]
```

- Default `--out`: `dashboard.html` next to the ledger (design spec §6.2).
- Overwrite guard: refuses to overwrite an existing file unless it contains the shell
  marker `id="aio-payload"` — the file being replaced must itself be a dashboard. `--force`
  overrides. This is the first ledger-adjacent write command; it writes exactly one file,
  atomically (temp file + rename), and never creates directories.
- `--lang` overrides `ledger.language`; unknown codes fall back to `en` with a warning on
  stderr (design spec §12.4).
- Exit codes: 0 built; 1 I/O or refusal; 2 invalid ledger (mirrors `verify`).
- The template is read from the bundle (`assets/templates/dashboard.html`) only; there is no
  `--template` flag. Injection replaces the island content and nothing else
  (`inject_payload(template_text, serialized) -> str`), and asserts the marker occurs
  exactly once.

## 4. Shell

Single self-contained file, vanilla JS, no framework, no request of any kind. Nine panels
(design spec §12.1) with default ordering severity-then-recency. Hash-fragment router:
`#panel=<id>&lang=<code>&f=<filter>` — filter state bookmarkable, no history spam
(`location.replace`). Command palette on `Ctrl`/`Cmd`+`K` over records, files, and keys.
Density toggle and language choice persist via `localStorage` in try/catch — on `file:`
origins this may silently fail, and that is acceptable (preferences reset per session).

Panel data sources, all from the payload:

| Panel | Source |
|---|---|
| Overview | counts over `records[]`, `computed.drift`, `computed.previews`, `computed.expired_evidence`, `computed.unreachable_projects` |
| Inventory | `baselines[].items[]` (kind, name, anchor, `origin`: `PROP-` ID or `pre-existing`) |
| Changes | `RUN` records: `targets[]` with `before_digest`/`after_digest`, `result`, `deviations`, `self_reported` markers |
| Provenance | reverse index built in JS: target anchor/key → RUN → `links`/`proposal` → MATERIAL → `evidence[]` |
| Rollback | `computed.previews` per RUN: indicator + four sets; static mode: unavailable, says so |
| Backlog | `backlog[]`: classification, reason, `revisit.trigger`/`revisit.date` |
| Decisions | `ADR` records: status, supersession via `links`; never filtered out |
| Materials | `MATERIAL` records: status, classification, evidence with expiry |
| Help | static i18n content: operating states, classification vocabulary, command examples |

Anything the tooling did not verify renders with the `SELF-REPORTED` marker (design spec
§5); digests, drift states, and preview sets render as verified only in `built` mode.

Empty states are instructional and name the exact command that populates the panel.
Staleness (§12.3) — **deviation**: a `file:` page cannot stat `ledger.json` without issuing
a request, which §13.4 forbids. The shell instead renders the generation timestamp and its
age prominently, with a rebuild hint when the age exceeds seven days, and `static` mode says
the data is whatever was last injected. The true newer-than comparison belongs to a future
`serve` mode (§18).

UI and UX requirements from design spec §12.3 apply as written: `prefers-color-scheme`,
`prefers-reduced-motion`, table→card at narrow widths (usable at 360 px), sticky filter bar,
WCAG 2.2 AA contrast both themes, icon+label on every status (never color alone), full
keyboard navigation with visible focus, print stylesheet, CSS logical properties.

## 5. Language

Two dictionaries embedded in the shell: `en`, `pt-BR` — flat JSON objects with identical key
sets (tested). Resolution: fragment `lang` → payload `lang` → stored preference (the
persistence §4 mandates; effectively static-mode-only, since built payloads always carry a
`lang`) → `navigator.language` prefix match → `en`. Canonical vocabulary — operating states, drift states, classifications,
statuses, record IDs, clipboard templates — stays English on screen with translated
tooltips. Adding a language is data-only.

## 6. Degraded text view

`assets/templates/DASHBOARD.md` — a markdown skeleton with one section per panel and
placeholder tokens (`{{overview_counts}}` etc.) that the skill fills from the ledger when no
browser exists. `references/DASHBOARD.md` documents panel semantics, the build command, the
static-injection procedure, and interpretation rules (what SELF-REPORTED means, why
canonical labels are English).

## 7. Acceptance (design spec §16, 0.4.0)

1. Generated file opens offline with zero network requests (browser-verified in dogfood).
2. A material title containing a script payload renders as inert text.
3. Every indicator legible without color.
4. Usable at 360 px.
5. Print stylesheet produces a readable PDF.
6. Language switch changes chrome; canonical labels stay English.

Eval additions (§17): script payload in material text renders inert in generated HTML;
clipboard text never contains material-derived text; generated dashboard issues no network
request.

## 8. Out of scope

`dashboard.py serve`, further languages beyond `en`/`pt-BR` (§18 defers both), multi-ledger
builds (one ledger per dashboard, per §6.2), true staleness detection (see §4 deviation),
and any change to scan/drift/rollback semantics.
