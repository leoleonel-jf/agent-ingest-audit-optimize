# Plan: a minimal CI

Spec: `docs/specs/2026-11-19-minimal-ci.md`

1. Run the three suites and the validator locally on Python 3.10 as well as 3.13, so the matrix
   is not the first time 3.10 is tried. Result: all green on both.
2. Write `tests.yml` and `evidence-freshness.yml`.
3. Write `packaging/tests/test_ci_workflows.py`; fix it until it passes against the workflows.
4. Ablate each guard: edit the workflow, see a named test fail, restore from a copy.
5. Run the packaging suite in full.
6. Open the pull request and read the first real run on both systems. A failure that only
   appears on Ubuntu is in scope to diagnose here; a fix that changes shipped code is not, and
   gets its own increment.
7. CHANGELOG entry under `Unreleased`.
