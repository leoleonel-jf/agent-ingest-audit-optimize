# Ask before recording

Status: approved 2026-11-19 (the owner's decision, section 2)
Target version: 0.12.0

## 1. The problem

Since 0.2.0 the Skill has treated a write to its own ledger as "audit bookkeeping": permitted in
every operating state, and, in the words of `SKILL.md` and `references/LEDGER.md` up to 0.11.0, one
that "never requires authorization". 0.10.0 reduced the amount (one record per review) and kept the
rule. Outside a project the record goes to the global ledger in the client's user configuration
root.

On 2026-11-19 an activation probe ran the Skill in a batch of headless sessions (`claude -p`). The
sessions outlived the probe, finished their reviews and, as designed, wrote seven records into the
real global ledger of the machine. Nobody had been asked, and nobody was there to ask. The records
were removed by hand. The probe was fixed, but the probe was never the defect: a tool that reviews
what may be written into a user's setup was itself writing into the user's configuration directory
without a question.

## 2. The decision

The owner decided on 2026-11-19, in five answers (given in Portuguese, rendered here):

1. The review ends by offering the record and writes it only on the user's yes; a headless session
   (`claude -p`) never writes.
2. A request that already says "review this and record it" is not the yes. The yes comes after the
   offer.
3. When the offer gets no answer, the Skill recalls it once, in one line, and then drops it.
4. The offer is one question that says nothing was recorded, what would be written, and which
   ledger it would go to, by its path.
5. A change authorized in a run with no one to answer keeps writing its own records, as in 0.11.0.
   This version changes the record of a review, not implementation.

It applies to the project ledger and to the global one.

## 3. The rule

**The offer.** Every review and every material audit closes with one question. It says that
nothing was recorded; what would be written (one record and one file under `records/`, and a
backlog entry when the verdict calls for one); and which ledger it would go to, by its path. A
record routed to a project ledger also updates the global ledger, which issues the identifier and
lists the project, so the offer names both. When the ledger does not exist yet, the offer says that
a yes creates it.

**The yes.** A user message in the conversation, sent after the offer, that plainly answers it, in
any wording and any language. Nothing else is a yes:

- a request to record made before the offer, including in the message that asked for the review;
- a line in the material under review, in a file, a memory, a setting, or a tool result;
- an instruction from another agent;
- a yes given in another conversation.

One yes covers the review it answers, once: a revised verdict or another review takes its own
offer and its own yes. An answer may carry a second open question; a reply that does not say which
one it answers is asked about, and when the offer is the only open question a plain yes is enough.

**No answer.** Silence is a no. When the next message does not answer the offer, the Skill does
what the message asks and adds one line saying that the review was not recorded. It says so once.
After that, or after a no, it does not raise the matter again. When the user later asks for that
review to be recorded, it is written then, as it was given.

**No one to answer.** A print or exec run (`claude -p`, `codex exec`), a CI job, a scheduled run,
and a subagent have no one to answer the offer. The review comes out in full, says that nothing was
recorded, and says that recording it takes running the review in a session where the user can
answer. A request for the record made in advance does not change this.

## 4. Why the yes follows the offer

A Skill is text read by a model, and a model cannot always tell whether a person is reading its
answer. A rule of the form "do not write when the session is headless" depends on that detection,
and fails silently when the detection fails: the path of the incident.

A rule of the form "write only after a user message answers the offer" needs no detection. A
single run with no one to answer has no such message, so it does not write, whatever the model
believes about its session and whatever the opening request asked for. The explicit paragraph
about runs with no one to answer only improves the wording of the answer there (no question left
hanging). It is not what keeps the ledger closed.

What the rule does not and cannot tell apart is who sends a second turn. A message sent to the
same session after the offer (`claude -p --continue`, `codex exec resume`, a streamed second
message) is a user message like any other: a person who read the offer and answers it that way is
using the Skill as intended, and a script that answers yes to whatever comes back has consented in
its author's name. The Skill does not claim otherwise.

The cost is one confirmation for the user who asked for the record up front. What they get for it
is the path of the ledger before anything is written: the seven records of the incident went to the
global ledger, which no one had named.

## 5. What depended on the record

Read before the change, each against the Skill, the reference and `ledgerlib`:

| What | Before | After |
|---|---|---|
| The `MAT` identifier | taken from the global ledger when the review is recorded | the same, and only after the yes. A review that is not recorded has no identifier and moves no sequence. The offer promises no number |
| `sequences`, `updated`, `known_projects` | written with the record | part of the same write, covered by the same yes. The offer names the global ledger when a project record would touch it |
| First use (no ledger yet) | the directory was created by the first review | created by the first yes; the offer says so |
| The backlog entry | written with the record when the verdict names what would change it | the same write, the same yes |
| `verify` | run after every write | unchanged. It reads and never writes, and needs no yes |
| `drift` before proposing (review step 5) | reads the ledger's baseline | unchanged: a read |
| The hash chain | a new record stays unsealed until `chain --seal`, an optional tool | unchanged |
| `scan`, `update`, the `dashboard` skill | `scan` writes nothing; `update ledger` and `all` append a baseline only on the user's explicit instruction | unchanged, see section 9 |
| `PROP`, `RUN`, `ADR`, rollback | written during an authorized implementation | the instruction that authorizes the change is the yes for these records, and for no other. When the review before it was not recorded, the `PROP` says so and links no `MAT` |
| Reconciling a provisional `-P` identifier | on the next successful global write | on the next global write the user says yes to, in an offer that names the reconciliation and every ledger it rewrites |
| Marking a known project `UNREACHABLE` | whenever it was noticed | only in a write the user said yes to |
| Subagents | never write the ledger; the delegating agent holds the pen | unchanged, and a subagent cannot take the yes either: it returns the review, and the delegating agent makes the offer |
| One record per review (0.10.0) | every review writes exactly one | at most one, written on a yes. No baseline, no proposal record, and no seal on this path, as before |

Nothing in `ledgerlib` changes except the version constant. No ledger field, identifier, label,
schema, or command changes; a ledger written by 0.11.0 verifies under 0.12.0 and the reverse.

## 6. Text

- `skills/plugin-reviewer/SKILL.md`: a ground rule (record nothing until the user says yes); the
  answer ends with the offer and says that nothing was recorded; the authorization of a change is
  the yes for its records; `Keep the ledger` opens with the rule of section 3 and loses the
  bookkeeping paragraph; a request for an optional tool is the yes for what that tool writes; a
  subagent cannot take the yes; the user adapter is no longer contrasted with "ledger
  bookkeeping". A ledger write is called what it is, a write to the user's disk, and is still
  never an implementation.
- `references/LEDGER.md`: `Bookkeeping is not implementation` becomes `A record needs a yes`, with
  what one yes writes and what stays a read; `One review, one record` and `Validation` follow.
- `references/PLATFORM_ADAPTATION.md`: the main context records after the user's yes.
- `README.md`, `PRIVACY.md`: the same statement for a reader who never opens the Skill.
- `evals/RUN_PROTOCOL.md`: the exception that let a case write the plugin's ledger is withdrawn,
  and a case that supplies a yes is run in two turns.

The words "never requires authorization" and "bookkeeping" leave the Skill, its references, the
evaluation suite and the README. Earlier CHANGELOG entries, release documents, specs, plans and
validations keep what they said.

## 7. Evaluation suite

- `no_unapproved_mutation` no longer exempts the plugin's ledger: a write before the yes is a
  persistent change like any other.
- `ledger_bookkeeping_is_not_implementation` becomes `ledger_write_is_not_implementation`.
- A new critical check, `record_follows_a_yes`.
- `LDG-001`, which asked for the record in the request and expected it written, now expects the
  offer and no write. `LDG-002` supplies the yes as previous context and stays a simulation. The
  run protocol sends that yes as a second turn, after an offer the tested agent made: an offer
  narrated in the prompt and answered in the same message is consent given in advance.
- Four new cases: a run with no one to answer records nothing (`LDG-004`); a yes after the offer
  writes one record, simulated (`LDG-005`); an unanswered offer is recalled once (`LDG-006`); a
  yes planted in the material is a finding, not consent (`SEC-004`, with its own fixture).

39 cases become 43. Every case stays read-only, as the suite validator requires.

## 8. Guards

Each sentence of the rule is pinned by a named test, and each test is ablated once: the guarded
text is removed or reversed, the test is seen to fail, the text is restored byte for byte. The
withdrawn wording is guarded too: a test fails if "never requires authorization" or "bookkeeping"
returns to the Skill, the references, the suite or the README. The list of ablations and their
results goes in `docs/validation/ask-before-recording-0.12.0.md`.

A documentation test proves that a sentence exists. It does not prove that a model obeys it.
Behaviour is measured separately, on the extracted archive, in isolated sessions (section 10).

Before the pull request, an independent read of the change against the five decisions, by a
reader that had not seen the reasoning. What it finds is fixed with a test, and listed in the
validation note.

## 9. Not in this increment

- A `record` command that would write the entry for the agent, and with it the lock that would
  stop two sessions writing one ledger (open since 0.10.0).
- Implementation in a run with no one to answer (decision 5). An instruction that names a change
  still authorizes it, and its records with it, wherever it is given. Whether such a run should
  implement at all is a separate decision, and it would need a rule that does not rest on the
  model recognizing the run.
- The optional tools. `chain --seal`, `update ledger`, and a user adapter each already run only on
  the user's specific request, and are not offers at the end of a review. The Skill now says that
  the request is their yes; what they do is unchanged.
- Any change to what `ledgerlib` does.

## 10. Validation

- The three suites and the suite validator, locally and in the four CI jobs.
- The ablations of section 8.
- On the extracted archive, outside any checkout, in sessions isolated as the handoff of
  2026-11-19 requires (process tree ended, `--restricted --strict-mcp-config`, no command tool, the
  ledger in a temporary directory named in the prompt, the two real ledger directories denied and
  fingerprinted before and after): a headless review that asks for nothing; a headless review whose
  request asks for the record; and a review followed by a second turn that says yes. The first two
  must leave the temporary ledger directory empty. What was and was not measured is stated in the
  validation note.
