# A minimal CI

Status: approved 2026-11-18 (review decisions in `docs/reviews/2026-11-18-revisao-do-plugin.md`)
Target version: none; repository tooling only, nothing shipped changes
Phase: second increment of the 2026-11 review

## 1. The problem

Nothing ran on a push. Two consequences are on record: `main` stayed red for three weeks after
2026-10-29 without anyone being told, and 0.6.0 went straight to `main` after five pull requests
had merged with no changelog entry. The suites were run by hand, on Windows only, by whoever
remembered.

## 2. The change

Two workflows, and tests that pin what they must keep doing.

### 2.1 `.github/workflows/tests.yml`: the gate

On every pull request and every push to `main`, on `ubuntu-latest` and `windows-latest`, with
Python 3.10 and 3.13:

- `python -m unittest discover -s dashboard/tests`
- `python -m unittest discover -s packaging/tests` (version consistency lives here)
- `python -m unittest discover -s evals/tests`
- `python evals/scripts/eval_suite.py validate`

Both systems because 0.2.4 fixed a POSIX-only defect that Windows-only runs could not see. 3.10
because it is the packager's stated minimum; 3.13 because it is what the suites have been run on.
The gate never reads the calendar.

### 2.2 `.github/workflows/evidence-freshness.yml`: the calendar

Weekly, and on demand: `python packaging/scripts/check_evidence_freshness.py --margin-days 14`.
It fails when bundled evidence has expired or will within 14 days. It is red today, correctly,
until the adapters are re-verified.

### 2.3 `packaging/tests/test_ci_workflows.py`

A workflow can lose a step as quietly as a release can lose a changelog entry, and a gate that
stopped running a suite still shows green. These tests read the two files as text (no YAML
dependency) and fail when a suite step is missing, a `*/tests` directory exists with no step,
either system is dropped, the pull-request or `main` trigger is removed, a step is allowed to
fail, the gate starts reading the calendar, or the scheduled check loses its schedule or gains a
pinned date.

## 3. Guards and their ablations

| Removed from the workflow | Test that failed |
|---|---|
| the `evals/tests` step | `test_every_suite_and_the_validator_are_steps`, `test_every_suite_on_disk_is_run` |
| `windows-latest` | `test_it_runs_on_both_systems` |
| the `pull_request` trigger | `test_it_runs_on_pull_requests_and_on_main` |
| strictness (`\|\| true` on a step) | `test_no_step_is_allowed_to_fail` |
| the schedule | `test_it_runs_the_check_on_a_schedule` |
| the moving date (`--today` added) | `test_it_does_not_pin_the_date` |

## 4. What this does not do

- It does not stop a direct push to `main`. That takes a branch protection rule with these checks
  required, which is a repository setting and the owner's decision.
- It does not run `claude plugin validate`. That needs the Claude Code CLI on the runner, and
  whether it runs unauthenticated was not verified. It stays a manual step before a release.
- It does not run model-backed evaluations. Each is a paid model call; they stay manual.
- Python 3.9, which `README.md` states as the tool's minimum, is not in the matrix. The claim is
  untested and is recorded here as open.

## 5. What the first run found

The first run on GitHub (2026-11-19) passed on Python 3.10 and failed on 3.13, on both systems,
in one test: `test_symlink_loop_is_refused_instead_of_leaking_runtime_error` expected the reason
`resolve_failed` and got `path_inspect_failed`.

Cause: Python 3.13 changed non-strict `Path.resolve()`. A symlink loop no longer raises there, so
`ledgerlib/paths.py:_resolve_or_raise` returns a path and the loop is refused one step later, when
the path is inspected. The safety property holds on every interpreter: the path is refused with
`PathSafetyError`. Only the reason string differs.

It was invisible before because the suites were run on Windows without the privilege to create a
symlink, where this test skips.

What this increment does: the test pins each interpreter's actual reason (`resolve_failed` before
3.13, `path_inspect_failed` from 3.13), so a third outcome still fails.

What stays open: `paths.py` documents that a caller "need not learn a second key" for a symlink
loop, and on 3.13 that is no longer true. Restoring one reason on every interpreter changes
shipped code and gets its own increment.
