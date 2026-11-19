# Plan: taking the calendar out of the test suites

Spec: `docs/specs/2026-11-19-suites-off-the-clock.md`

Baseline on 2026-11-18, clean tree at `5377df5`: dashboard 1434 tests with 1 failure, packaging 25
with 2 failures, evals 11 passing.

1. Write `packaging/tests/test_evidence_freshness.py` with every date injected. Run it and see it
   fail because the script does not exist.
2. Write `packaging/scripts/check_evidence_freshness.py` until those tests pass.
3. Change the three calendar-dependent tests to assert "clean apart from expiry", and add the
   test that a second finding is not excused.
4. Run the three suites. Expected: all green, with the adapters still expired.
5. Ablate each guard in the script: remove it, see a named test fail, restore from a copy.
6. Prove the non-expired path: move `generic.json` to a future date in a scratch edit, run the
   three tests, revert with `git checkout`.
7. Run the script with no arguments. Expected: exit `1`, three adapters named.
8. CHANGELOG entry under `Unreleased`; no version pin moves, because nothing shipped changes.

Result on 2026-11-19: dashboard 1435 passing, packaging 36 passing, evals 11 passing. Steps 5 to
7 behaved as expected; the ablation table is in the spec.
