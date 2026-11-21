# The four high findings of the 2026-11-20 review

Status: approved 2026-11-21 (Leo: "Altos numa release"; implementation authorized the same day)
Target version: 0.13.0, one release for the four
Source: the independent review of 2026-11-20 (Codex) and its 12-PR plan, reviewed by Odin in
`#agent-board` on 2026-11-21. Both live in the main checkout's ignored `.agent-audit/`.

Each section is one pull request into `release/0.13.0`. The release pull request into `main`
carries the changelog entry, the version bump and the release document.

## 1. Two writers lose a baseline (finding 1)

**Problem.** `update ledger` reads the ledger (`update.py`, before the scan), scans, and replaces
the file; `chain --seal` reads, seals, and replaces it. The replace is atomic, but two writers whose
windows overlap each replace the file with a document built from the same old read: both exit `0`
and the first writer's change is gone. Reproduced with two processes, IDs `BASE-2026-000` and
`BASE-2026-001`: only one survived.

**Change.** `ledgerlib/locking.py`: `ledger_lock(ledger)` holds an operating-system lock on a
sidecar, `<ledger>.lock` (`msvcrt.locking` on Windows, `fcntl.flock` elsewhere; `flock` and not
`lockf`, because POSIX record locks do not exclude a second descriptor of the same process). The
sidecar carries the lock because Windows refuses `os.replace` onto a locked file. `update ledger`,
`update all` and `chain --seal` take it before they read and release it after they write;
`update anchors` and `chain --head` take none. A writer waits up to 30 seconds, then exits `2`
having read and written nothing, and can be run again. The operating system drops the lock when the
holder exits, cleanly or not. The sidecar stays in place: deleting it would let a third writer lock
a fresh file while a second still waits on the old one.

**Not covered, said in `references/LEDGER_INTEGRITY.md`.** A record written by editing the JSON
directly, which is how the Skill writes a review's record, does not take the lock. Closing that
needs a `record` command (handoff item 9), out of this release.

**Tests.** `dashboard/tests/test_ledger_lock.py`, seven tests, every writer a separate
interpreter. Writer A is held inside its window (between read and write) by an instrumented scan
while writer B starts. Before the change: five failed for the defect (both IDs did not survive;
writer B and the seal finished inside A's window; the timeout did not exist), one could not run its
retry, and the independent-ledgers control passed. Ablations: without the lock in `update`, four
named tests fail; without it in `chain --seal`, the seal test fails.

## 2. The rollback preview promises a target the backup does not hold (finding 2)

To be filled by its pull request.

## 3. Sealing a partial chain breaks it (findings 3 and 14)

To be filled by its pull request.

## 4. Minimization trusts a marker it did not create (finding 4)

To be filled by its pull request.
