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

**Problem.** `rollback-preview` listed every `IN_PLACE` target as `will_be_restored` as soon as
the backup file's digest matched the recorded one, and called the run `HEALTHY` with exit `0`.
The digest proves the backup is the file recorded, not what it holds: the project's own fixture,
a backup holding only `backup bytes`, produced `HEALTHY`.

**Change.** A verified backup proves a target's recovery in exactly two cases the ledger can
show: the backup's digest equals the target's own `before_digest` (the backup is, byte for byte,
what the target held), or the target has no `before_digest` (the run created it; rolling back
deletes it). Any other `IN_PLACE` target under a verified backup goes to `cannot_be_restored`
with the reason `recovery_unverified`, a line on stderr names it, and the indicator is `AT_RISK`
(exit `1`). A missing or altered backup is `BROKEN` as before. No schema or ledger field
changes, and ledgers written before read as they did; what changes is the verdict on a run whose
backup bundles several files, which the format cannot tie to any one target. A per-target backup
format, and actually restoring, stay out of this release.

**Tests.** `BackupProvesRecoveryTests` and `BackupProvesRecoveryCliTests` in
`dashboard/tests/test_rollback.py`: the review's case (a backup of `backup bytes`), the positive
control (a backup holding the target's before-bytes is `HEALTHY`), one backup proving one of two
targets, a created file, a missing backup, an altered backup that would have proved, and the
command's exit and stderr. Four failed before the change. The shared fixture `in_place_target`
now describes a created file, so the older tests keep what they test; `test_build.py` and
`test_legacy_ledger_client.py` each needed the same one-field change. Ablations: without the
proof, three named tests fail; without the `AT_RISK` branch, two.

## 3. Sealing a partial chain breaks it (findings 3 and 14)

**Problem.** `verify_chain` counts indices over the sealed subsequence, so a record with no
`chain` may precede a sealed record of index 0 and the ledger verifies `PARTIAL`. `seal_ledger`
counted over every position: it gave that record index 0, the sealed record after it became an
`index_gap`, and `chain --seal` exited `0` with `sealed 1 record(s)`. Separately, `verify --chain`
reported findings per record, so a ledger with no records came back green.

**Change.** `chain --seal` seals a deep copy, verifies it, and writes only when the copy is
`INTACT`. Otherwise it names the unchained records that precede the chain, says nothing was
written, and exits `2`; the file and its head are untouched. Sealing a fresh ledger, extending an
intact chain with new records, and an idempotent second seal behave as before. `verify --chain`
on a ledger with no records adds the finding `chain UNCHAINED` and exits `1`; without `--chain`
the same ledger still passes. Moving those stranded records, or re-sealing from scratch (which
changes the head), stays the user's call; this release only stops the seal from breaking.

**Tests.** `SealNeverBreaksTheChainTests` and `VerifyChainOnAnEmptyLedgerTests` in
`dashboard/tests/test_chain.py`: the review's case under LF and CRLF, an unsealed record between
two sealed ones, a first seal, new records after an intact chain, a byte-identical second seal,
and the empty ledger with and without `--chain`. Three failed before the change. The seal runs
under the writer lock of section 1. Ablations: without the copy's verification, the legacy-prefix
test fails under both line endings; without the empty-ledger finding, its test fails.

## 4. Minimization trusts a marker it did not create (finding 4)

**Problem.** `withhold_text` replaces every string a configuration file holds with a marker,
`{"redacted": true, "digest": "sha256:..."}`, and leaves `redact`'s markers alone so it does not
digest a digest. It told a marker by its shape only. A file holding an object of that shape kept
its `digest` string as written. The review rated this plausible; the test below confirmed it: a
sentinel under `hooks` and a digest-looking sentinel under `permissions` both reached the
baseline, `ledger.json`, and the rendered page.

**Change.** `redact` and `withhold_text` build their markers as `_Marker`, a `dict` subclass that
serializes exactly like the plain object, and `withhold_text` passes through only that type.
Parsing JSON or TOML never yields it, so a file's marker-shaped object is walked like any other
and its `digest` string is digested. A format check on `digest` was rejected: it would stop a
plain sentinel and still copy a credential that already looks like a digest. Real markers stay
one level deep and strings are digested once. Baselines captured before 0.13.0 are not rewritten:
a ledger that already holds such text keeps it until those baselines are removed by hand.

**Tests.** `MarkerShapedInputTestCase` in `dashboard/tests/test_update.py` runs `update all`
from a file through the ledger, the page, and both streams, with a plain sentinel and a 64-hex
`sha256:` sentinel; `MarkersAreNotTransformedTwiceTestCase` holds the controls.
`test_an_existing_marker_is_left_exactly_as_it_is` in `test_scan.py` hand-built its marker, which
is exactly the input this change stops trusting, and now takes it from `redact`. Three failed
before the change. Ablations: checking shape instead of type fails three named tests; a `redact`
that builds plain dicts fails three others.
