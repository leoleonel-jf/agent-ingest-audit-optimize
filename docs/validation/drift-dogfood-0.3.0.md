# Dogfood: `drift` and `rollback-preview` on a real machine (0.3.0)

Date: 2026-07-30. Machine: the Windows 11 development machine, Claude Code client, the
repository's own project ledger at `.agent-audit/ledger.json` (untracked, never staged).
Every command below is quoted with its real exit code; every finding is either fixed in a
named commit or recorded with a reason.

## What was run

1. `scan --id BASE-2026-000 --project .` — no `--client`: **fell back to `generic`, exit 1**,
   with the finding naming `['claude-code', 'codex']` as the clients weighed. Correct: both
   roots exist on this machine, and detection never guesses. The finding's wording pointed
   straight at `--client`, which is what the fallback exists to do.
2. `scan --id BASE-2026-000 --client claude-code --project .` — exit 0, 115 items
   (96 `present`, 19 `not_present`). Eyeball plus a programmatic sweep before the entry
   touched the ledger: MCP `args` and `env` are redaction markers with digests, no
   sensitive-looking key survives unredacted, and the only high-entropy strings are two git
   commit SHAs in `installed_plugins.json`. **No sensitive value stored** — §16's first
   criterion, demonstrated end-to-end: the entry was written into `baselines[]` and
   `verify` exits 0.
3. `drift` immediately after — and the first real run earned its keep. See findings.
4. A controlled modification cycle, and `rollback-preview RUN-2026-000`.

## Findings

**1. Three `pointer_unresolved` items reported `DRIFTED`/`appeared` minutes after their scan.**
`settings.json/env`, `settings.local.json/hooks`, `settings.local.json/env` — all recorded
`not_present` because a JSON pointer did not resolve, all "appeared" because the classifier
tested the *file's* existence, and the file had existed at scan time too, or there would have
been no document to walk. An in-file absence cannot be re-verified from the file. Fixed in
`8f0c34e`: `scan` records `pointer` and `parse` on pointer-absent items; `drift` re-resolves
the same location the same way — parse, redact with the same adapter patterns, walk — and
emits only a state. The redaction mirror is load-bearing and has its own test: a pointer that
`scan` could not resolve through a redacted marker must stay unresolvable at drift time.
After re-capture, all 115 items classify `IN_PLACE`.

**2. A literal, wildcard-free glob's absence was swallowed by the pointer branch.** Found by
accident: this repository has no root `CLAUDE.md`, and creating one for the controlled test
returned `UNVERIFIABLE`/`pointer_unrecorded` instead of `DRIFTED`/`appeared`, because the
first fix keyed on the recorded *reason* (`no_match`) and `no_match` is also what a literal
glob records when it matches nothing. Fixed in `1c4fa01`: the recorded *pointer* marks an
in-file absence, not the reason. The controlled cycle then behaved exactly: create the file →
exactly one item flips to `DRIFTED`/`appeared`; delete it → zero non-`IN_PLACE` items.

**3. All 17 targets of RUN-2026-000 were `UNVERIFIABLE`/`path_malformed_anchor_reference`.**
The run was recorded in the 0.2.1 era with bare relative paths, before anchors existed.
`drift` refusing them is correct — they are not anchored forms and earn no dereference. The
ledger's owner migrated the data: each target prefixed with `$PROJECT/`, and the one anchor
embedding `#/plugins/0/source/ref` split into a file anchor plus a `key` field. `verify`
exits 0 on the migrated ledger. After migration: 11 targets `DRIFTED`, 6 `IN_PLACE` — the
truth; releases 0.2.2 through 0.2.5 modified those files after the run. §16's second
criterion ("an externally modified target is reported `DRIFTED`") is met by history itself.

**4. The preview reported 11 of the run's 17 targets.** `will_be_restored` requires a
verified backup and the backup is `null`; the six `IN_PLACE` targets then belonged to no set.
Intact and unrestorable is `cannot_be_restored`, carrying the backup's failure reason. Fixed
in the partition commit; the three target sets now provably partition a run's targets, with
a named test per clause. Re-run: 17 of 17 accounted for, indicator `BROKEN`, reason
`missing`, exit 1 — §16's fourth criterion on real data, not a fixture.

**5. The baseline was re-captured under its own ID.** BASE-2026-000 was replaced in place
after finding 1's fix so its pointer-absent items carry the recorded pointer. Same capture
session, never referenced by anything else; recorded here rather than silently.

## What this run could not exercise

- `REVERTED` on a real target — no run on this machine has been rolled back.
- The Codex adapter's `resolution` data against a real Codex ledger — no Codex ledger exists
  here yet; the claude-code data was exercised by the 115-item baseline.
- `parse_unavailable` — this interpreter has `tomllib`.

## Verdict

Every §16 acceptance criterion for 0.3.0 is demonstrated on this machine, on real data, with
the two classification defects and one completeness defect the dogfood surfaced fixed and
guarded by named tests before release. The commands never wrote a file: every mutation above
was performed by the ledger's owner, by hand, and `verify` gates each one.
