# Dashboard

`dashboard.py build` renders one ledger into a single offline HTML file: vanilla JS, no
framework, no network request. It is a read view, not a second ledger — it never writes back.
Implements design spec §12 and `docs/specs/2026-07-31-dashboard-build.md`.

## The nine panels

Every panel reads only what the payload carries (see the payload contract below). Default
ordering is severity-then-recency.

| Panel | Question it answers |
|---|---|
| `overview` | What needs attention right now — active changes, drift, at-risk rollbacks, expired evidence, unreachable projects, known-project links? |
| `inventory` | What does the current baseline say is present, and where did each item come from (pre-existing or a `PROP-` id)? |
| `changes` | What did each `RUN` actually touch, what did it claim, and where does it self-report a gap? |
| `provenance` | For a given file or key, which runs touched it, through which proposal, back to which material and evidence? |
| `rollback` | If a run were undone now, what would be restored, left alone, or unrestorable — and is the backup trustworthy? |
| `backlog` | What was deferred, why, and what brings it back (a trigger or a date)? |
| `decisions` | What was decided, and by what later decision was it superseded? Nothing here is ever filtered out. |
| `materials` | What was audited, its classification, and which evidence has already expired? |
| `help` | What do the operating states, classifications, statuses, and commands mean, in this UI language? |

## `build` usage

```
dashboard.py build LEDGER [--out PATH] [--lang CODE] [--force]
                          [--project PATH] [--adapter FILE] [--user-config PATH]
```

| Flag | Meaning |
|---|---|
| `--out` | Where to write the dashboard. Default: `dashboard.html` next to `LEDGER`. |
| `--lang` | Overrides `ledger.language`. An unrecognized code falls back to `en` with a warning on stderr. |
| `--force` | Overrides the overwrite guard (see below). |
| `--project`, `--adapter`, `--user-config` | Same meaning as for `scan`/`drift`: they feed the `computed.drift` and `computed.previews` sub-computations. |

**Overwrite guard.** `build` refuses to overwrite an existing `--out` file unless that file
itself carries the shell marker `id="aio-payload"` — the file being replaced must already be a
dashboard. `--force` overrides the guard. This is the first ledger-adjacent command that writes;
it writes exactly one file, atomically (temp file, then rename), and never creates a directory.

**Verification gate.** A ledger that `verify` would reject — `validate_ledger` plus the
single-document `validate_collection` pass, same code, not similar code — fails the build with
`verify`'s own exit semantics, and writes nothing.

**Exit codes.** `0` built; `1` I/O error or overwrite refusal; `2` invalid ledger.

**No `--template` flag.** The template is read from the bundle
(`assets/templates/dashboard.html`) only. Injection replaces the payload island's content and
nothing else, and the code asserts the marker `id="aio-payload"` occurs exactly once before it
splices.

## Static injection: building a dashboard with no Python

When there is no Python available, assemble the same file by hand. This is a verbatim recipe;
skipping the escaping step is unsafe.

1. Copy `assets/templates/dashboard.html` to sit next to `ledger.json` (or wherever you want the
   dashboard to live).
2. Find the script element with `id="aio-payload"` (the payload island) and replace everything
   between its opening and closing tags with this envelope, where the placeholder text is the
   ledger document verbatim:

   ```json
   {"payload_schema":1,"mode":"static","generated_at":null,"tool_version":null,"lang":null,"ledger":PUT_THE_LEDGER_JSON_HERE,"computed":null}
   ```

3. Apply the escaping, by string replacement, over the *entire serialized JSON text* you just
   produced (the whole envelope, not just the ledger). Every occurrence of the less-than
   character becomes a six-character JSON string escape: a backslash, followed by a lowercase
   `u`, followed by the four digits `0`, `0`, `3`, `c`. If the ledger text contains a line
   separator or paragraph separator character, escape each of those the same way, as a backslash
   followed by `u`, followed by `2028` or `2029` respectively. Every other character is left
   exactly as `json.dumps` would have produced it.
4. Save the file. Do not reformat or pretty-print the JSON afterward — reformatting can
   reintroduce whitespace the escaping step didn't touch, but must never reintroduce a literal
   less-than character where step 3 already removed one.

**Skipping step 3 is unsafe.** A literal less-than character inside the island can close the
`<script>` tag early and let ledger content — a material title, an evidence source, anything an
audited external document supplied — turn into a second script element on the page. This is the
whole reason the serializer escapes unconditionally rather than only escaping the specific
strings believed to be dangerous: the property has to be global (no less-than character survives
anywhere in the serialized text), not pattern-matched against the ledger content anyone happens
to test with.

The shell parses the island with `JSON.parse` on load. If the result does not parse — including
because step 3 was skipped and a stray less-than character broke the surrounding markup before
the browser ever got to it — the shell renders a static error state. It never falls through to a
partial render. An unparseable island is a fatal error for the shell, not a degraded panel.

## Degradation table (design spec §14, restated for practice)

| Client situation | What you get |
|---|---|
| **Full** (Python + browser) | Run `build`; open the generated file. All panels populate; `computed.drift`, `computed.previews`, `computed.expired_evidence`, `computed.unreachable_projects` are present; mode is `built`. |
| **No Python** | Follow the static-injection recipe above against `assets/templates/dashboard.html`. Open the resulting file in a browser. `mode` is `static`; the overview states plainly that digest verification, drift, and rollback preview are unavailable — nothing shown has been checked against a file on disk. |
| **No browser** | Generate the degraded text view instead (see below): fill `assets/templates/DASHBOARD.md`'s token placeholders from the ledger and read the resulting Markdown. |
| **Unknown client** (neither a bundled adapter nor a confirmed local one) | `scan`/`drift`/`build`'s `--adapter`/`--user-config` machinery still runs, but a `computed.drift` or `computed.previews` sub-computation that fails carries an `error` message instead of a report, and `build` still succeeds. The corresponding panel shows an "unavailable" note naming the exact command that would compute it (see `card.unavailable.*` in the template), rather than a false zero. |

## What SELF-REPORTED means

A `RUN` record's `self_reported` array names the fields no tool can confirm — most commonly
`targets`, because nothing in a ledger states how many files a run was actually supposed to
touch. The Changes panel renders a `SELF-REPORTED` badge next to any field a record lists there.
It is not a warning that the field is wrong; it is an honest label that the field is the record's
own claim about itself, never independently verified. A record naming three targets for a
fourteen-file change still validates clean — `SELF-REPORTED` is what stops that gap from being
silent, not what closes it.

Anything the tooling did not verify renders with this marker. Digests, drift states, and rollback
preview sets render as verified only in `built` mode, because only `built` mode carries
`computed` at all.

## Why canonical labels stay English

Operating states, drift states (`IN_PLACE`, `DRIFTED`, `REVERTED`, `MISSING`, `UNVERIFIABLE`),
rollback indicators (`HEALTHY`, `AT_RISK`, `BROKEN`), classifications, record statuses, and record
IDs render in English on screen in every UI language, with a translated tooltip. This is the same
rule `SKILL.md` and `LEDGER.md` state for free text versus canonical vocabulary: these strings are
identifiers an operator matches against ledger content, commands, and other tooling — translating
the label would make "DRIFTED" in one language and "DRIFTED" in a ledger's own JSON two different
strings to search for. Clipboard instruction templates (see Action model, below) are English for
the same reason and are not dictionary content at all: they address the agent that will read them,
not the person reading the page.

## The staleness deviation

Design spec §12.3 asked for a true "is this newer than the ledger on disk" comparison. A `file:`
page cannot stat `ledger.json` without issuing a request, and §13.4 forbids any request at all —
the zero-network property is the point of a generated dashboard. The shipped behavior instead
renders the dashboard's own generation timestamp and its age prominently (in the footer, and as a
warning banner once the age exceeds seven days), with a rebuild hint: `dashboard.py build
LEDGER`. In `static` mode there is no generation timestamp at all, and the page says plainly that
the data is whatever was last injected by hand. The true newer-than comparison is deferred to a
future `serve` mode (§18) that can actually read the file.

## No `computed.verify`

There is no `computed.verify` key in the payload, on purpose. `build` fails outright — writing
nothing — for any ledger `verify` would reject. A built payload therefore exists only for a
ledger that already passed verification, and the Help panel says exactly that: a built page
carries a ledger that already passed verification, because build refuses any ledger verify would
reject. Re-stating a pass/fail the build gate already enforced would be redundant at best and
misleading if the two ever disagreed.

## Language resolution order

1. The `lang` fragment parameter (`#panel=...&lang=pt-BR`), if it names a recognized language.
2. The payload's own `lang` (`build --lang`, or `ledger.language`) — always present in `built`
   mode, absent in `static` mode.
3. A language stored in `localStorage` from an earlier visit — effectively static-mode-only,
   since a built payload always supplies its own `lang` and step 2 wins first.
4. `navigator.language`, matched by prefix.
5. `en`, unconditionally, if nothing above resolved.

Two dictionaries ship, `en` and `pt-BR`, as flat objects with identical key sets (a test checks
this). Adding a language is data-only — a new dictionary with the same keys.

## Generating the degraded text view

`assets/templates/DASHBOARD.md` is a Markdown skeleton with one section per panel and token
placeholders written as `{{name}}` (for example `{{overview_counts}}`, `{{inventory_rows}}`).
Use it when there is no browser to open an HTML file in at all:

1. Copy `assets/templates/DASHBOARD.md` next to the ledger (or wherever the text view should
   live).
2. For each token, read the corresponding data straight from `ledger.json` (and, if available,
   from `dashboard.py drift` / `rollback-preview` output) and replace the token with the
   plain-text or table rendering of that data. Each panel section in the template names which
   ledger fields feed its tokens.
3. Do not invent a value for a token the ledger has nothing for — write the panel's own empty
   state instead (for example "No active changes.") exactly as the HTML shell would.
4. Save the filled-in file under its own name; never edit `assets/templates/DASHBOARD.md` itself,
   which is the template, not an output.

The generated file is data, not a program: it carries no script and makes no promise beyond what
it states in text, so there is no escaping step to perform here — the injection procedure above is
specific to the HTML shell's data island.

## The action model

Every action produces text for a human to paste to an agent, or a per-record export. Nothing here
runs a command, and nothing derived from ledger content ever reaches the clipboard except through
an export.

- **Copy instruction.** A fixed English template plus a record id the page validated itself
  against the ledger's own identifier pattern immediately before assembly — the template text,
  a space, then the id, and nothing else. The four templates: "Implement proposal", "Roll back
  run", "Revisit backlog entry", "Re-audit material". No other string reaches this path.
- **Queue.** Copied or queued instructions accumulate in an in-memory queue (never persisted), and
  "copy all" orders them `rollback`, `revisit`, `audit`, `implement` — the order most useful to
  read down when acting on a batch — regardless of the order entries were added in. Two identical
  instruction lines never appear twice.
- **Export.** Every record and every rollback preview gets an "Export" action: it copies that one
  record (or preview object) as formatted JSON. There is no ledger-wide download button — the
  design spec's promise there is deliberately narrowed to per-record export, which covers the
  audit-evidence use (pull one record out to paste or attach) without a second copy of the whole
  ledger to keep in sync.
- **Open's current scope.** "Open" links render only for the two real filesystem paths the payload
  actually carries: a known project's `project_root` and `ledger_path`
  (`known_projects[]` in the global ledger). Every other panel deals in anchors
  (`$USER_CONFIG/...`), not resolved paths — `resolve_anchored` never stores an absolute path for
  a portable one, and neither the drift report nor a rollback preview carries the filesystem path
  it actually opened, only the anchor it classified. Making "open the record, the backup, or the
  changed file" true everywhere the design spec originally asked for is a 0.5.0 change to the
  Python side, not shipped here. A project marked unreachable, or a root that is not an absolute
  local path, gets no Open link and says so, rather than a link that goes nowhere.
- **Rollback is two-step.** "Prepare" reveals the §11 preview summary and a confirmation prompt;
  only after "Yes, undo this run" is clicked does the instruction's copy and queue buttons enable.
  Nothing re-arms or disarms silently — there is no timeout, and leaving the Rollback panel and
  returning resets the confirmation to unconfirmed.

## What the palette searches

`Ctrl`/`Cmd`+`K` opens a command palette built once from the payload (never from anything the
reader types): every record's id and title, and, for `RUN` records, every target's anchor and
key. Each entry remembers which panel shows it (`MATERIAL`→materials, `PROPOSAL`→provenance,
`RUN`→changes, `ADR`→decisions, `BASELINE`→inventory; a run's own targets index to provenance,
where a search for a touched file or key has to land to see every run that touched it). Selecting
a match is exactly a jump to that panel and filter — the palette can reach no view the
hash-fragment router could not already address on its own.
