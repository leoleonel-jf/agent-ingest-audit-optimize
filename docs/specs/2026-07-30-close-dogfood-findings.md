# Closing the Dogfood Findings (0.2.2)

Status: approved 2026-07-30 under standing autonomy
Target version: 0.2.2

0.2.1 kept this repository's ledger by hand for the first time and produced five findings, all
recorded unfixed in `docs/validation/ledger-dogfood-0.2.1.md` because `verify` and its schema were
out of scope for that release. This release closes them, plus four minor items carried from the
same review pass.

## 1. Why now, before 0.3.0

0.3.0 adds `scan`, `drift`, and `rollback-preview` — three commands that all write to the ledger.
Every gap the dogfood found is a place where a wrong-but-well-formed value survives validation
indefinitely. Those gaps do not stay the same size when three more writers start using the format;
they get harder to find, because a stale digest or an understated `targets` array will no longer be
traceable to one author's hand-editing session.

The dogfood's own conclusion names the shape of the problem: three findings mean a wrong value can
sit in a ledger with no tool objecting, and one means the record type whose entire purpose is
describing a change can misdescribe it and still pass.

## 2. Compatibility

This release makes `verify` stricter. A ledger that validated clean under 0.2.1 may now produce
findings. That is the point, and it is stated plainly in `CHANGELOG.md` rather than buried: the
new checks describe conditions that were always wrong, only unobserved.

One change is a hard requirement rather than a detection: every RUN record must now name `targets`
in `self_reported` (§3.5). Existing RUN records will be flagged until updated. This repository's own
ledger is updated as part of this release.

## 3. The five findings

### 3.1 Finding 1 — a digest pointer is never checked against what it points at

`known_projects[].last_digest` is shape-checked and never compared to the file at the paired
`ledger_path`. It went stale twice during one release and `verify` reported clean both times.

**Fix.** `verify` computes the sha256 of every file it reads and passes those digests into the
cross-ledger pass. For each `known_projects` entry, if its `ledger_path` resolves to a path already
in the verified set, compare `last_digest` against that file's real digest and report a finding on
mismatch.

**The path this fix deliberately does not take.** It would be easy to make `verify` open the file
named by `ledger_path` and hash it. It must not. `ledger_path` is ledger content, and ledger content
is attacker-influenced by design — the same reasoning that made 0.2.0 escape untrusted values in
finding output. Opening an arbitrary path read out of a document is exactly the surface that spec
§13.6 (filesystem path safety) was deferred to constrain, and that constraint does not exist yet.
Comparing only against files the user named on the command line requires no new read, cannot be
steered by ledger content, and still catches the real case, because `references/LEDGER.md` already
requires passing every reachable ledger in one invocation.

**Consequence of that choice, stated rather than hidden.** When the named project ledger is not in
the invocation, nothing is checked and nothing is reported. Silence there means "not comparable",
not "correct". `references/LEDGER.md` gains a sentence saying so.

### 3.2 Finding 2 — the digest contract never says which bytes to hash

Documentation only. `references/LEDGER.md` gains an explicit rule: a digest is taken from the
referenced ledger's final on-disk bytes, after every other edit to it is complete — not from JSON
text held in an editor. Trailing-newline and line-ending differences change the hash of an otherwise
identical document.

The dogfood also noted there is no canonical formatter, so two authors writing the same content as
different bytes get different digests. That stays open: a canonical writer is a real feature, not a
documentation line, and it belongs with the 0.4.0 `build` work that will need one anyway. It is
recorded as such, not silently dropped.

### 3.3 Finding 3 — `sequences` is loose in the prose and blind across ledgers

Two distinct problems.

**(a) The prose overstates the check.** `references/LEDGER.md` calls `sequences` "the next free
number"; the validator enforces a floor — any value at or above one past the highest allocated
number passes, so `2` and `5` validate as cleanly as `1` for a ledger whose highest record is `-000`.
Documentation fix: describe the floor as what is enforced, and keep "next free" explicitly labelled
as the house convention it is.

**(b) The authority ledger's sequences are never related to where its ids get spent.** The sequence
check compares a ledger's `sequences` only against records in that same document. The global ledger
normally holds no records — every project-scoped record routes to the project ledger — so the one
ledger designated as sole ID authority is precisely the one whose allocation counter nothing
validates. Setting the global ledger's `sequences.MAT` to `0` while a sibling project ledger holds
`MAT-2026-000` produces a clean run.

**Fix.** In the cross-ledger pass, compute the highest number used per prefix across every record in
the whole verified set, and require each ledger that declares `id_authority: true` to carry
`sequences[prefix]` at or above that highest number plus one. Non-authority ledgers keep the existing
own-records rule unchanged: a project ledger is not made responsible for another project's
allocations.

### 3.4 Finding 4 — a backlog entry's `id` has no defined meaning

The Backlog section requires `id` but never says what it refers to or whether it must be unique.
The duplicate-identifier check walks only `records`, so two entries sharing one id pass. The only
way to learn the field's actual role was to read the validator.

**Fix.** Name the convention and enforce the half of it that can be enforced.
`references/LEDGER.md` states that a backlog entry's `id` is a back-reference to the record whose
evidence produced the finding, that it is deliberately not unique across entries — several findings
routinely come from one material — and that `verify` checks it resolves to a record that exists.
`verify` reports a finding when a backlog `id` names no record declared anywhere in the verified set,
reusing the dangling-link machinery and its existing suppression when the set is partial.

### 3.5 Finding 5 — nothing checks a RUN's `targets` cover what the run changed

A RUN record listed three targets for a release that changed fourteen files and validated clean. A
human review pass caught it; no tool did.

**Fix, and the honest limit on it.** No validator can know what a run was supposed to touch — that
knowledge lives outside the ledger. What it can do is stop the record from being silent about it.
`self_reported` already exists for exactly this: "an array of strings naming the fields no tool can
confirm." `targets` coverage is the clearest possible member of that set and was never listed.

`verify` requires every RUN record to name `targets` in `self_reported`.
`references/LEDGER.md` states why: the validator checks every target's shape and can never check the
array's completeness, so a RUN record must admit that in the field built for admissions. This
converts an invisible gap into a machine-checked declaration. It does not make coverage verifiable,
and the documentation says so in those words.

## 4. The four carried minors

| Item | Resolution |
|---|---|
| `test_version_consistency.py` indexes `plugins[0]` in two marketplace assertions | Assert each marketplace file holds exactly one plugin entry before indexing, so a second entry fails loudly instead of going unchecked |
| The same file duplicates `REPO_ROOT` and manifest paths from `package_plugin.py` | Keep. Two reviewers judged it correct — importing them would let one path bug mask another. Add a comment saying so, so it is not "fixed" later |
| `dashboard.py`'s docstring says "Phase 0.2.0 implements the `verify` command only" | Reword so it names the command set rather than a version that goes stale every release |
| `docs/SUBMISSION.md`'s evaluation-case count has no guard | Add a test asserting the number in that line equals the case count in `evals/suite.json` |

## 5. Scope

In scope: the five findings, the four minors, `references/LEDGER.md`, `assets/schemas/ledger.schema.json`
where a rule becomes structural, tests for every new check, this repository's own ledger updated to
satisfy §3.5, and the 0.2.2 release.

Out of scope: a canonical ledger formatter (§3.2, deferred to the 0.4.0 `build` work); reading files
named by ledger content (§3.1, blocked on spec §13.6); every 0.3.0 deliverable; splitting
`dashboard.py` into a package, which remains a 0.3.0 item.

## 6. Acceptance

| Criterion | Evidence |
|---|---|
| A stale `last_digest` is caught | A test mutates a project ledger after its digest is recorded and expects a finding |
| A digest for a ledger outside the set is not flagged | A test passes only the global ledger and expects no digest finding |
| The authority ledger's sequences are cross-checked | A test sets the authority's `sequences` below a sibling's allocated record and expects a finding |
| A non-authority ledger is not made responsible for siblings | A test leaves a project ledger's sequences correct for its own records only and expects no finding |
| A dangling backlog back-reference is caught | A test points a backlog `id` at a record that exists nowhere and expects a finding |
| Two backlog entries may share an id | A test uses one id twice and expects no finding |
| A RUN without `targets` in `self_reported` is caught | A test omits it and expects a finding |
| Partial sets stay quiet | With one ledger unreadable, backlog back-reference checks are suppressed like link checks, exit `2` |
| The docs match the code | `references/LEDGER.md` describes the floor, the digest source, the backlog id, and the `self_reported` requirement |
| The repository's own ledger complies | `verify` over both ledgers exits `0` under the new rules |
| Nothing regressed | Every suite green; version pins consistent; `dist` verified |

## 7. Risk

The `self_reported` requirement in §3.5 is the only change that invalidates previously-valid data.
It is deliberate and small — one string in one array — but any user with an existing RUN record will
see a finding on their next run. The changelog entry states the exact remedy rather than only the
rule.

The digest comparison in §3.1 could produce a false alarm if a user passes a stale copy of a project
ledger from a different location whose resolved path happens to match. This is the same class of
mistake as passing the wrong file to any validator, and the finding text names both the path and the
two digests so the cause is legible.
