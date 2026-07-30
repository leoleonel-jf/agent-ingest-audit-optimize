# Ledger Dogfood — Release 0.2.1

- Date: 2026-07-30
- Plugin version: 0.2.1
- Status: **VALIDATED — with five findings scheduled, not fixed, in this release**

> This is a public record. It names no author-local record identifier: 0.1.2 removed those
> from public files precisely so that a fresh installation starts its own `MAT`/`PROP`/`RUN`/`ADR`
> sequence rather than inheriting one author's numbering. Records here are referred to only by
> type — "the MATERIAL record", "the RUN record" — never by id.

## Objective

0.2.0 shipped the ledger format and the `verify` command, but nothing had ever used either for
real work. Every prior run of `verify` was against test fixtures written to exercise a specific
check, not against a ledger someone actually kept while doing an audit. This release closed that
gap: it built a ledger pair from scratch, used it to record the analysis and execution of this
same release's own version-pin fix, ran `verify` clean, deliberately broke a ledger to confirm the
validator reacts to a real fault rather than staying quiet by default, and restored it. This
document is the only surviving public account of what that produced — the ledgers themselves are
untracked by design (they hold author-local identifiers and machine-local paths), so their content
does not outlive this machine's `.agent-audit/` and user-configuration directories.

## What was created

- Two ledgers: one at global scope, at this machine's user configuration root, which is this
  installation's ID authority; one at project scope, inside this repository, gitignored so it
  never reaches the remote.
- Four records in the project ledger, one of each type produced by an ordinary
  analyze-decide-execute-validate cycle: a MATERIAL record for the external documentation that
  triggered this release's work, a PROPOSAL record for the version-pin fix, an ADR record for the
  decision it rested on, and a RUN record for the authorized execution.
- Two backlog entries, both scheduling follow-up on findings that the MATERIAL record's evidence
  surfaced (an upstream re-clone inefficiency to monitor, and an unexecuted CI validation command
  to revisit once tooling is available).

## Verification — clean run

Command, run against both ledgers in one invocation so the cross-ledger checks execute
(`references/LEDGER.md` requires passing every reachable ledger together for exactly this reason):

```text
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify <global ledger path> <project ledger path>
```

Output:

```text
2 ledger(s) validated
exit=0
```

## Deliberate fault injection

A clean run alone proves nothing — it is also what a validator that does nothing would produce.
To confirm `verify` actually inspects content, the project ledger's `id_authority` field was
flipped from `false` to `true` after taking a byte-for-byte backup, making two ledgers
simultaneously claim ID authority, then `verify` was re-run, then the backup was restored and
`verify` was run a third time.

Corrupted run:

```text
.agent-audit\ledger.json: a project ledger must not be the ID authority
More than one ledger claims ID authority: ['.agent-audit\\ledger.json', '<global ledger path>']
2 finding(s)
exit=1
```

Both findings were the expected ones for this specific corruption: the project ledger flagged
directly for holding an authority flag it must never carry, and the cross-ledger check flagged
the resulting collision of two simultaneous authorities. Exit code `1`, with content describing
the exact fault — not a crash and not a silent pass.

Restore run, after copying the backup back over the corrupted file and confirming with `diff`
that the restored bytes were identical to the pre-corruption file:

```text
2 ledger(s) validated
exit=0
```

The cycle — clean, corrupted with findings, restored to clean — is the evidence that the validator
does something, not just that it ran.

## Findings

Five surfaced from actually using the format. None are fixed here: `verify` and its schema are out
of scope for this release. Each is written precisely enough to act on later.

### 1. A ledger's pointer to another ledger's digest is never checked against that ledger

The global ledger's `known_projects[].last_digest` is meant to record a sha256 digest of the
project ledger it names, computed from that project ledger's on-disk bytes. `verify` checks only
that the stored value has the right *shape* — `sha256:` followed by 64 hex characters — never that
it is actually the current hash of the file at the paired `ledger_path`. A wrong-but-well-formed
digest is therefore indistinguishable from a correct one to the validator.

This was not a hypothetical risk raised for this document; it happened twice during this exercise.
The digest went stale once, immediately, when the project ledger's records were written after the
pointer had already been set. It went stale a second time after a later round of review fixes
changed the project ledger's bytes again. Both times `verify` kept returning a clean pass on the
stale value — nothing in its output distinguished "this digest is correct" from "this digest has
the right shape and nothing more." The only thing that kept it true was recomputing it by hand,
last, after every other edit to the referenced ledger was final.

### 2. The digest contract never says which bytes to hash

`references/LEDGER.md` documents the *shape* `last_digest` must have but not the *source* of the
bytes: that it must be a hash of the referenced ledger's final on-disk file, not of whatever JSON
text an author is holding in an editor buffer. That distinction matters more than it looks —
a trailing newline present or absent, or CRLF versus LF line endings, changes the hash of an
otherwise identical document. Compute the digest a step too early, or paste the same JSON through
an editor that normalizes line endings, and the digest is subtly wrong in a way that looks
completely normal and that finding 1 shows nothing will catch.

### 3. `sequences` is ambiguous, but not in the place the fault is easiest to imagine

`references/LEDGER.md`'s prose calls `sequences` "the next free number for each prefix." The code
`verify` actually runs is looser than that prose: for a ledger that holds a record itself, it
requires that ledger's `sequences` value for that record's prefix be no lower than one past the
highest number already used among that ledger's own records — a floor, not an equality. Any value
at or above that floor validates clean; only a value below it is flagged. Direct testing confirmed
this precisely: building a throwaway ledger holding a single record numbered `-000` and setting its
own `sequences` value for that prefix to `0`, `1`, `2`, and `5` in turn, `verify` failed only at
`0` — `1`, `2`, and `5` all validated cleanly. A `sequences` value does not have to equal "next
free" at all; it only has to be high enough. So `references/LEDGER.md`'s "next free number" is a
stricter house convention than anything the validator enforces: an author who leaves `sequences`
padded well ahead of what is actually allocated, by typo or by reserving room for ids they mean to
skip to, will never see a finding for it. The narrower fact is still real and worth keeping: for
the ledger that actually holds the records, `0` fails and anything `1` or higher passes — there is
a floor, just not the ceiling the prose implies.

There is a second, larger ambiguity one level up, in the global ledger — the ledger that is this
whole installation's sole ID authority, and the one `references/LEDGER.md` says every project should
request the next id from. Because the global ledger typically holds no records of its own (every
project-scoped record routes to the project ledger per the scope-routing table), and because
`verify`'s sequence check only ever compares a ledger's `sequences` against the records *in that
same ledger document*, the global ledger's `sequences` values are never cross-checked against the
records that actually consumed those ids in the sibling project ledger — even when both ledgers
are passed to `verify` together. Direct testing confirmed this: with the project ledger correctly
holding an allocated record and its own `sequences` bumped to `1`, setting the *global* ledger's
`sequences` for that same prefix to `0` still produced a clean `verify` run. In this exercise the
global ledger's `sequences` was kept in step with the project ledger's by hand, as a matter of
discipline, immediately after every project-ledger write — nothing enforces that it has to be.

Is this worth closing? Yes. The one ledger `references/LEDGER.md` designates as authoritative for
issuing the next id is exactly the one whose bookkeeping `verify` cannot relate back to where those
ids actually get spent. A validator that cross-checks id authority and duplicate identifiers
already correlates the ledgers in a set with each other; extending the sequence check to fold in
every reachable ledger's records, not just each document's own, would close this without changing
the format.

### 4. A backlog entry's `id` has no defined meaning, and nothing enforces uniqueness on it

`references/LEDGER.md`'s Backlog section requires `id`, `classification`, `reason`,
`revisit_trigger`, `revisit_after` on a backlog entry, but never states what `id` refers to or
whether it must be unique across entries. Reading `dashboard.py` directly confirms why this
matters: its duplicate-identifier check walks only each ledger's `records` array into a "seen"
dictionary; the function that validates a backlog entry checks that single entry's own shape and
never compares its `id` against any other entry's, in `backlog` or anywhere else.

In this exercise, two backlog entries share the same `id` — the identifier of the MATERIAL record
whose evidence produced both findings that were backlogged. A `verify` run over a ledger holding
both entries with the same id returns clean. Combined with the schema and the prose being silent
on the field's meaning, the only way to learn what it actually does was to read the validator's
source and confirm empirically with a live run: in practice, a backlog entry's `id` functions as a
back-reference to the record that produced the finding, not as a unique identifier of the backlog
entry itself. That is a reasonable convention, but it exists only because this exercise reverse-
engineered it from the code — nothing in the documentation states it, and nothing in the schema
would catch a future author using the field differently.

### 5. Nothing checks that a RUN record's `targets` actually cover what the run changed — and a human, not a tool, caught this one

`references/LEDGER.md` requires a RUN record's `targets` array to be non-empty and each entry to
carry a well-formed digest pair, but nothing anywhere — not the schema, not `verify` — checks that
the array's *coverage* matches the change set the run actually produced. A RUN record can name
three targets for a release that touched fourteen files, carry three correctly-formed digest
pairs, and pass `verify` without a single finding, because the validator has no way to know how
many files the run was supposed to touch in the first place.

That is exactly what happened here. The first draft of this release's RUN record listed three
targets. `git diff --name-status` against the prior tag showed fourteen files had actually
changed. `verify` validated the three-target version clean — it had no basis to object, since
every target it did see was well-formed. The gap was caught only by a human review pass that
compared the record's narrative and target list against the actual diff, not by any check the
tooling runs today. The record was corrected by hand to list all fourteen targets before this
release closed, but the mechanism that would have caught the original understatement automatically
does not exist yet. Of the five findings here, this is the one worth taking most seriously: a RUN
record's central job is describing what the run changed, and today it can misdescribe that and
still pass validation in full.

## Other friction, for completeness

Writing four records and two backlog entries by hand, keeping their prose in sync with the
ledger's structured fields, surfaced smaller points worth a line each, though none rose to the
level of the five above:

- Hand-editing a multi-record ledger's nested `targets`/`evidence`/`links` arrays in raw JSON is
  error-prone enough (trailing commas, quoting, Unicode escaping in non-English free text) that
  this exercise built and edited the ledger through short Python scripts rather than a text editor,
  specifically to avoid those mistakes.
- `references/LEDGER.md` doesn't state whether `updated` must change on a same-day second edit to
  a ledger already dated today — it didn't matter here because every edit landed on the same
  calendar day, but the rule is genuinely silent on repeated same-day mutations.
- There is no canonical formatter for a hand-written ledger. Two authors (or the same author on
  two occasions) producing the same content as different bytes — different indentation, different
  key order — will compute different digests for otherwise-identical documents, which matters
  directly for finding 2 above.

## Full check, clean

Run once more at the end of this release, over every suite the plugin ships:

```text
python -m unittest discover -s dashboard/tests
python -m unittest discover -s evals/tests
python -m unittest discover -s packaging/tests
python evals/scripts/eval_suite.py validate
python packaging/scripts/package_plugin.py verify
```

Observed:

- `dashboard/tests`: 203 tests, OK.
- `evals/tests`: 11 tests, OK.
- `packaging/tests`: 12 tests, OK.
- Evaluation suite: valid, 28 cases across 7 task categories.
- Packaging verification: `VALID`, resolved against the `dist` output path.

Every count matched what this release's plan predicted; nothing regressed.

## Conclusion

The ledger format and `verify` hold up for a first real, by-hand use: two ledgers were built,
four records and two backlog entries were written and cross-validated clean, and a deliberate
fault was shown to produce real findings and a non-zero exit rather than passing silently. That
same exercise also found five concrete gaps between what the format claims and what the validator
actually checks — three of them (findings 1, 3, and 4) mean a wrong-but-well-formed value can sit
in a ledger indefinitely with no tool ever objecting, and one (finding 5) means the record type
whose entire purpose is describing a change can understate that change and still validate clean.
All five are recorded here, unfixed, for a future release's schema or validator work to pick up.
