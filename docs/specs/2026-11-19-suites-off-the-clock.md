# Taking the calendar out of the test suites

Status: approved 2026-11-18 (review decisions in `docs/reviews/2026-11-18-revisao-do-plugin.md`)
Target version: none; tests and maintainer tooling only, nothing shipped changes
Phase: first increment of the 2026-11 review

## 1. The problem

The three bundled adapters declare `"expires_on": "2026-10-28"`. `scan` treats a run dated after
that as a finding and exits `1`, which is the design: an adapter verified against vendor
documentation in July may no longer name the files the client reads.

Three tests ran `scan` against a bundled adapter and asserted exit `0`:

- `dashboard/tests/test_scan.py`, `test_the_client_flag_selects_a_bundled_adapter`
- `packaging/tests/test_package_plugin.py`, `test_extracted_plugin_archive_runs_scan`
- `packaging/tests/test_package_plugin.py`, `test_extracted_skill_archive_runs_scan`

None of them is about freshness. They test adapter selection and that the packaged script runs
from an extracted archive. On 2026-10-29 all three began to fail, and `main` has been red since,
with no code change.

Two questions were fused: "is the code right" and "has time passed". A suite that answers the
second cannot be trusted to answer the first.

## 2. What is not the fix

Moving `expires_on` forward. The date records when the paths were last verified. The review
re-verified them and found that `claude-code.json` and `codex.json` need edits before any renewal
is honest. That is its own increment. This one must leave the suites green while the adapters are
still, truthfully, expired.

Adding a date flag to `scan`. The CLI has none today, and a flag that lets a caller choose the
date a scan claims to have run on is new user-facing surface with its own questions. Not needed
to solve this.

## 3. The change

### 3.1 The three tests assert "clean apart from expiry"

Each accepts exit `0`, or exit `1` where the single finding is the adapter's own expiry. Every
stderr line must be one of the two selection notes or that finding, and the exit code must follow
from which. A second finding behind an expired adapter still fails the test, so tolerating expiry
does not become tolerating anything. `test_a_second_finding_is_not_excused_by_expiry` pins that.

Both states were exercised: the tests pass today, with the adapter expired, and pass with the
adapter's date moved to 2099 in a scratch edit that was then reverted.

### 3.2 One owner for the calendar: `packaging/scripts/check_evidence_freshness.py`

It finds every JSON document under `skills/` whose top level carries `expires_on` (today: three
adapters and two control mappings) and classifies each as `expired`, `expiring` or `fresh`.

- `--today YYYY-MM-DD` sets the date; the clock is used only when it is omitted.
- `--margin-days N` (default 14): evidence is `expiring` when it would be expired N days from
  the judged date.
- Exit `0` nothing stale, `1` something expired or expiring, `2` the check cannot be trusted: a
  malformed date, unreadable JSON, or no dated evidence found at all. A check that looked at
  nothing must not report that nothing is stale.
- Expiry is strict (`today > expires_on`), agreeing with `scan`.

It is not shipped in either archive. It is run on a schedule by CI (next increment) and before a
release. Its own tests inject every date.

## 4. What this deliberately leaves red

`python packaging/scripts/check_evidence_freshness.py` exits `1` today and names the three
adapters. That is correct, and it stays that way until the adapters are re-verified and edited.

## 5. Guards and their ablations

| Guard | Removed | Test that failed |
|---|---|---|
| expiry comparison | `if today > expires_on` | `test_expired_evidence_exits_one_and_names_the_file` |
| margin comparison | the `expiring` branch | `test_evidence_inside_the_margin_exits_one_as_expiring`, `test_the_margin_boundary_is_the_day_it_would_expire` |
| empty-tree refusal | `if not evidence` | `test_a_tree_with_no_dated_evidence_is_a_tool_error` |
| top-level-only rule | the `"expires_on" not in document` clause | `test_json_without_a_top_level_expiry_is_not_evidence` and two others |

## 6. Out of scope

Editing adapters, CI, how `update` reports an expired adapter to an installed user, and structured
warnings with a strict mode. Each is a later increment.
