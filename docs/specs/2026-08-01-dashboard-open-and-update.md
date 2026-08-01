# Opening and updating the dashboard (toward 0.6.0)

Status: approved 2026-08-01 under standing autonomy
Target version: 0.6.0 (does not bump the version by itself)
Phase: first increment after 0.5.0

## 1. Where this sits

0.4.0 shipped `build`, which renders a ledger into one offline HTML file. Two things it does
not do came up in use, and this spec covers both.

The first is trivially missing: `build` writes a file and says nothing about how to look at it.
A reader has to know the output path and open it by hand. `--open` closes that.

The second is a naming problem more than a missing capability. Re-running `build` already
re-renders everything — `build_payload` re-resolves every anchor through `drift_report` and
`rollback_preview` on each run, and the overwrite guard in `write_dashboard` deliberately lets a
file carrying the `aio-payload` marker be replaced without `--force`. What no command does is
refresh the *ledger*: `scan` prints a `baselines[]` entry to stdout and writes nothing, so
bringing a baseline up to date is a copy-paste. `update` names the three things a reader might
mean by "refresh" and makes the one that was missing possible.

## 2. `build --open`

After a successful write, `build` opens `out` in the default browser through
`webbrowser.open(out.as_uri())`. `webbrowser` is standard library, so the bundle stays
stdlib-only.

Three properties, in the order they matter:

- **It never opens a build that failed.** The call sits after `write_dashboard` returns, on the
  success path only. A ledger `verify` rejects (exit `2`) or a write refusal (exit `1`) opens
  nothing.
- **A failed open does not fail the build.** `webbrowser.open` returns `False` when it finds no
  browser, and raises on some platforms. Both become one note on stderr and the exit code stays
  `0`. The file was written; that was the command's job. Turning a successful build into a
  failure because a courtesy did not land would make `--open` unusable in any environment
  without a display, which includes every CI runner this tool is meant to run in.
- **The note goes to stderr.** `scan_command`'s docstring already fixes the contract for this
  bundle: stdout carries the machine-readable answer and nothing else. `build` prints no stdout
  payload today, but the discipline is the bundle's, not the command's.

The opener is reached through the module attribute (`build._open_url`), not a direct import, so a
test replaces it exactly the way `rollback` replaces `classify_target`. No test launches a
browser.

There is no `--browser` flag. Choosing a specific browser was considered and cut: the default
browser is the right answer on a desktop, and `webbrowser.get(name)` fails in enough
platform-specific ways that supporting it means supporting its failures.

## 3. `update`

```text
python dashboard.py update <ledger> [all|ledger|anchors] [--open] [--id BASE-YYYY-NNN]
                                    [--client NAME] [--out PATH] [--lang CODE]
                                    [--project PATH] [--adapter PATH] [--user-config PATH]
                                    [--force]
```

`what` is a positional with `nargs="?"`, `choices=("all", "ledger", "anchors")` and
`default="anchors"`. Two consequences are the reason for that shape: `update <ledger>` with no
further argument does the read-only thing, and `update -h` lists the three words without any
help text being written twice.

| `what` | Reads | Writes | Meaning |
|---|---|---|---|
| `anchors` | the ledger, the environment | the dashboard | re-render; the anchors are re-resolved because every build re-resolves them |
| `ledger` | the environment | the ledger | capture the environment into a new `baselines[]` entry |
| `all` | both | both | `ledger`, then `anchors` |

Exit codes match the family: `0` clean, `1` findings or an I/O refusal, `2` a tool error or a
ledger `verify` would reject. The `verify` gate runs **before any write**, for both `ledger` and
`anchors` — a ledger nothing vouched for is not a ledger this command appends to.

`anchors` delegates to `build_command` with the flags it was given. This is deliberate
duplication of an entry point, not of an implementation, and it is the one place this design
puts two doors on one question. It is accepted because `anchors` exists to give `all` a second
half and to name what the other two words are not; without it, `update all` would be a
compound whose parts have no names.

`ledger` calls `scan(...)`, which returns `(entry, messages, exit_code)` — the seam is already
there. It then appends `entry` to `baselines[]`, raises `sequences.BASE` to at least one past
the number it just spent, sets `updated` to the capture date, and writes the document atomically
through the same temp-file-then-`os.replace` path `chain_command` uses. `messages` goes to
stderr in order, as `scan_command` sends it.

A `scan` that reports findings (`exit_code` `1`) **still appends**. The findings describe the
environment that was captured, not a defect in the capture, and an entry recording an
incomplete environment is the honest record of an incomplete environment — refusing to write it
would leave the ledger claiming the older, cleaner state is still current. The exit code
becomes `1` so a caller can tell, and `all` still proceeds to the render, which is where those
findings become visible.

**The chain is untouched.** `chain._records` reads `ledger["records"]`, and a baseline is not a
record. Appending one changes no digest, so there is no reseal step and `verify --expect-head`
keeps passing against a head recorded before the update. This was checked rather than assumed;
an earlier draft of this design wrongly required a reseal.

stdout carries one JSON object:

```json
{"updated": "all", "baseline_id": "BASE-2026-001", "minted": "local", "dashboard": "..."}
```

`dashboard` is `null` when `what` is `ledger`; `baseline_id` and `minted` are `null` when `what`
is `anchors`.

## 4. Minting the baseline identifier

`--id` is optional. When omitted, `update` mints the next identifier itself: the year from the
capture date, and the number from `sequences.BASE` raised past every `BASE` number the document
already spends in `baselines[]` and `records[]`.

**This narrows a documented rule and the narrowing is the point of this section.**
`references/LEDGER.md` says the global ledger is the only ID authority, that a project ledger
requests its next identifier from it, and that a locally minted identifier carries a `-P` suffix
with `pending_id_reconciliation: true`. Automatic minting was chosen anyway, with the trade-off
stated: a refresh that requires a round trip to another document to name its own output is a
refresh nobody runs.

Three things keep the narrowing honest:

- **The provisional path is not used.** A `-P` baseline would be worse than a plain one, not
  better: `validate.py` checks `pending_id_reconciliation` on records only, so a provisional
  baseline would pass `verify` carrying no reconciliation marker — a silent lie in place of a
  visible liberty.
- **It is visible.** Every locally minted identifier produces a note on stderr naming it as
  locally minted, and `minted: "local"` appears on stdout. An `--id` the caller supplied reports
  `minted: "given"`.
- **It is recorded.** `LEDGER.md` gains a paragraph in Identifiers stating the exception for
  baselines minted by `update`, and this spec is the ADR it points at. Amending the rule is
  cheaper than leaving a command that quietly breaks it.

The residual risk is collision: if the global ledger later issues the same `BASE` number to
another document, a verified set holding both has two entries with one identifier. `verify`
catches that at set level, which is the layer that can see both. It is not prevented here.

## 5. `/dashboard`

The plugin ships no `commands/` directory; this adds the first, with one file,
`commands/dashboard.md`. It is a thin wrapper, not a second implementation: it resolves the
ledger (`.agent-audit/ledger.json` under the project root unless told otherwise), runs
`dashboard.py update` with the word the user passed, and reports what the script printed.

`/dashboard` with no argument runs `anchors --open`. Writing to the ledger requires
`/dashboard ledger` or `/dashboard all` typed explicitly, which is the same line the README
draws at section "Analysis and deliberation are read-only": a persistent change needs an
unambiguous instruction, and a bare command name is not one.

## 6. What this does not do

- No interactive prompt. The bundle has no `input(`, `isatty` or `stdin` read anywhere, and a
  prompt would hang the CI use this tool is shaped for. "The options appear when you pass no
  option" is served by argparse's own `choices` rendering.
- No `--browser`, per section 2.
- No new resolver and no second path-safety layer: `anchors` is `build_command`.
- No change to `scan`, which keeps writing nothing. `update ledger` is the writer; `scan` stays
  the read-only capture it is documented to be.
- No version bump and no packaging change on its own.

## 7. Acceptance

- `--open` opens exactly on the success path, never on exit `1` or `2`; a raising or `False`
  opener leaves the exit code `0` and puts one note on stderr; the opener is replaced in every
  test.
- `update` with no `what` behaves as `anchors`; `-h` lists the three choices; an unknown word
  exits `2` naming them.
- `update anchors` leaves the ledger's bytes byte-identical.
- `update ledger` appends exactly one `baselines[]` entry, raises `sequences.BASE` past it,
  leaves `records[]` and every chain digest untouched, and `verify --expect-head` still passes
  against a head captured before the run.
- A ledger `verify` would reject exits `2` with nothing written, for all three words.
- A `scan` reporting findings still appends its entry, and the run exits `1`.
- A minted identifier reports `minted: "local"` on stdout and names itself on stderr; a supplied
  `--id` reports `minted: "given"`.
- `update all` performs the append before the render, so the new baseline appears in the page it
  writes.
- The full suites stay green: dashboard, packaging, evals. README, `LEDGER.md` and CHANGELOG
  updated; the ten version pins stay consistent.
