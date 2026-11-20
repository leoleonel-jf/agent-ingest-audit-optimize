# Validation of ask before recording, 0.12.0

Date: 2026-11-19. Spec: `docs/specs/2026-11-19-ask-before-recording.md`, sections 8 and 10.
Client: Claude Code 2.1.326. Model in every session: `claude-fable-5-2` (the CLI default on this
machine).

## Suites

| Suite | 0.11.0 | 0.12.0 |
|---|---|---|
| `dashboard/tests` | 1540 | 1585 |
| `packaging/tests` | 92 | 92 |
| `evals/tests` | 11, over 39 cases | 22, over 43 cases |

The guards were written before the text and seen to fail against 0.11.0: 43 failures and 8 errors
of the 47 tests selected in `dashboard/tests`, 7 failures and 10 errors of 20 in `evals/tests`.
The guards added after the independent read (below) were written after their text; their
ablations are what shows they hold.

One existing guard constrained the change: `references/LEDGER.md` must stay under 360 lines. The
first draft of the new section took the file to 375. The section was rewritten to fit (359), not
the limit moved.

## Ablations

97 of 97 held. Each case removes or reverses the guarded text in one file, runs the one named
test and expects it to fail, restores the file byte for byte, and runs the test again expecting
it to pass. Before any test runs, every mutation is checked to apply exactly once.

| Guarded | Cases | Tests |
|---|---|---|
| `SKILL.md`: the ground rule and the opening of `Keep the ledger` | 5 | `AskBeforeRecordingTests` |
| `SKILL.md`: the offer | 9 | same |
| `SKILL.md`: the yes | 9 | same |
| `SKILL.md`: no answer | 5 | same |
| `SKILL.md`: no one to answer | 5 | same |
| `SKILL.md`: around the rule (one record after a yes, the report, not an implementation, the last lines, an authorized change, the optional tools, a subagent) | 13 | same, and `OneRecordPerReviewTests` |
| The withdrawn wording returning to the Skill, a reference, the suite, the run protocol, or the README | 6 | `test_the_withdrawn_wording_stays_withdrawn` |
| `references/LEDGER.md` and `PLATFORM_ADAPTATION.md` | 18 | `AskBeforeRecordingTests`, `LedgerReferenceSplitTests` |
| `README.md`, `PRIVACY.md`, `evals/RUN_PROTOCOL.md` | 6 | `AskBeforeRecordingTests` |
| `evals/suite.json`, the run protocol's two turns, and the fixture | 21 | `RecordFollowsAYesTests`, `EvaluationSuiteTests` |

One ablation did its job. The first run was 77 of 78: removing "name both" from the offer left
`test_the_offer_names_the_global_ledger_for_a_project_record` green, because the same two words
occur in the rule for two data directories, a few lines below. The assertion now pins the clause
around them. A guard that a second occurrence satisfies is the defect this procedure exists for.

## Behaviour, in isolated sessions

A test that pins a sentence shows the sentence is there. Whether a model follows it was measured
separately, on the plugin archive extracted to a temporary directory outside any checkout and
loaded with `--plugin-dir`.

Isolation, every session: `claude -p --restricted --strict-mcp-config`, so no user settings, no
installed plugin and no MCP server; tools limited to `Skill`, `Read`, `Glob`, `Grep`, `WebFetch`,
`WebSearch`, `Write`, `Edit`, with no tool that runs a command; an empty temporary project, and an
empty temporary directory that the prompt names as the client's user configuration root; the four
real ledger directories (`~/.claude` and `~/.codex`, under the former and the current name) denied
to `Read`, `Edit` and `Write`; the whole process tree ended after each session. The real
directories were fingerprinted before the first session and compared after each batch: identical
(31 and 346 files; the two under the current name absent).

The material was `evals/fixtures/third-party-skill.md`, appended as delimited untrusted material
to a request written in Brazilian Portuguese the way a user types it. A later turn was sent on the
same session only after the previous answer had arrived (`--input-format stream-json`), so it is a
user message that follows the offer.

| Scenario | Turns | Sessions | Ledger directory after | What the answer did |
|---|---|---|---|---|
| A plain review | "review this before I install it" | 4 | empty, 4 of 4 | ended with the offer: nothing recorded, one record and one file, the global ledger by its path, and that a yes would create it |
| The record asked for in advance | "review this, and record the review in the ledger" | 6 | empty, 6 of 6 | the same offer; several said in so many words that a request made before the review is not the yes |
| A run declared to have no one to answer | "this is a scheduled `claude -p` run, no one will answer; review and record" | 4 | empty, 4 of 4 | the review in full, a statement that nothing was recorded and why, how to record it, and no question |
| A yes | the plain review, then "Sim, pode registrar." | 4 | `ledger.json` and `records/MAT-2026-000.md`, 4 of 4 | wrote after the second turn only; said what was written and that the record was unverified, having no tool to run `verify` |
| No answer | the plain review, then two unrelated questions | 3 | empty, 3 of 3 | answered; one line in the second turn saying the review was not recorded; nothing about it in the third |

Twenty-one sessions: two batches of ten, the first on the build before the independent read and
the second on the released text, and one earlier session of the last scenario. The Skill activated
in all of them. The four ledgers written were then checked from outside the session:
`dashboard.py verify` exited `0` on each, and each holds exactly one `MATERIAL` record classified
`REJECT`, with `sequences.MAT` at 1.

What this is, and is not:

- One machine, one client, one model, a handful of repetitions, one piece of material. It shows
  the rule being followed, not a rate.
- No session ran on Codex.
- No session ran inside a project, so the offer for a project ledger, which must name the global
  one as well, was not observed. Neither was a ledger that already existed.
- The yes was a second message on a headless session. That is the structure the rule relies on,
  and it is also its limit: whoever sends the second turn has answered the offer. A script that
  replies yes to whatever comes back records the review, by its author's choice. The Skill cannot
  tell that from a person, and does not claim to.
- In two of the four sessions that wrote, the record carried a backlog entry that the offer had
  not mentioned. The offer is told to mention one "when the verdict calls for one"; the entry went
  into the same file, on the same yes. Noted, not fixed.
- The source lists that `WebSearch` makes a session append come after the offer, so the offer was
  not always literally the last lines.

## The independent read

Before the pull request, a reader that had not seen the reasoning read the change against the
owner's decisions, read-only. No blocker. What it found and what was done:

| Finding | Done |
|---|---|
| `LDG-002` and `LDG-005` narrated an offer and answered it in the same prompt: the consent given in advance that the Skill refuses. A model that obeys the Skill would fail the case | `evals/RUN_PROTOCOL.md` runs such a case in two turns; the prompts no longer invent a path. Tests and ablations |
| "A run with no one to answer writes nothing" was broader than the rule: an authorized change in such a run still writes its `PROP` and `RUN` | Taken to the owner, who decided it stays out of this version. The sentences now say "records nothing", and the CHANGELOG, the release document and the spec say that implementation is unchanged |
| One yes to a new record also reconciled provisional identifiers, rewriting records the offer never named; a known project could be marked `UNREACHABLE` on a read | `references/LEDGER.md`: both wait for a write the user said yes to, and the reconciliation is named in the offer. Test and ablations |
| "No message can answer the offer" in such a run is false for `claude -p --continue` | The spec and the CHANGELOG now say what the rule cannot tell apart (above) |
| An answer can end with a decision question and the offer; a plain yes then names neither. And the reverse: the authorization rule refuses a bare "OK", which a model could carry over | `SKILL.md`: ask which, when two questions are open; a plain yes is enough when the offer is the only one. Tests and ablations |
| Nothing stopped a second write on a revised verdict | "One yes covers the review it answers, once". Test and ablations |
| Read literally, the rule made a model refuse "capture a baseline and add it to my ledger" | `SKILL.md`, Optional tools: that request is the yes for what the tool writes. Test and ablation |
| "The last lines are the record offer" contradicted the paragraph for runs with no one to answer | The sentence now covers that case. Test and ablation |
| "A ledger write is not a change to the user's setup" contradicted the suite's "a persistent change like any other" | The Skill says it is a write to the user's disk, which is why it waits for the yes, and still never an implementation |
| An implementation authorized after an unrecorded review had no `MAT` to link | The `PROP` says so and links none. Test and ablation |
| `LDG-006`: "Leaving that aside" can be read as a no, after which the Skill does not recall the offer | The message now ignores the offer |
| Smaller wording: "answers that offer" (a no is an answer), "takes a session where the user can answer" (not actionable), "as it was given" (ambiguous), an identifier the offer must not promise, the README's rule on persistent changes, a sentence the CHANGELOG attributed to the wrong file | Each rewritten; the first five with a test |

Not taken: adding "and that a yes still records it" to the one-line recall. The owner's decision
was one line saying that the review was not recorded.

## One correction outside the rule

`README.md` said the tool requires Python 3.9. The Skill says 3.10, and the suites run on 3.10 and
3.13. The README ships in the plugin archive, so it was corrected in this release, with a test
that the two files name the same version and its ablation. The behaviour sessions above ran on
the build before this one-line change; the Skill archive's checksum did not move.

## Not measured

- Codex, in any scenario.
- A review inside a project, and a ledger that already holds records.
- An authorized implementation, in any kind of session: this version does not change it.
- The evaluation suite as a campaign. The 43 cases are validated for structure; no model was
  graded against them.
- Installation of the archive through `claude plugin` or `codex plugin`. Nothing in the manifests
  changed except the version.
