# Plan: withholding parsed text, and shipping the whole plugin

Spec: `docs/specs/2026-11-19-withheld-text-and-complete-archive.md`

1. Confirm nothing reads `attributes.value`: grep `drift.py`, `lock.py`, `build.py`,
   `rollback.py` and the dashboard template.
2. Write the failing tests: `WithheldTextTests`, `TextNeverReachesAnItemTests` (the two
   reproductions against the shipped patterns), and the rewritten empty-pattern test.
3. Add `withhold_text` and call it after `redact` in `_parse_items`. Run the suite; update the
   five tests that pinned the old rule, each computing its expectation independently.
4. Add the end-to-end test in `test_update.py`: file, `scan`, appended baseline, rendered page,
   both streams.
5. Rewrite the passages of `PRIVACY.md`, `references/LEDGER.md` and the empty-pattern finding
   that described the old rule, and the documentation tests that pinned them.
6. Ablate the three guards in `scan.py`.
7. Write the two archive tests that start from the repository; see them fail on `commands/`.
8. Add `COMPONENT_ROOTS` to the packager.
9. Bump every version pin to 0.6.1, write the CHANGELOG entry and the release document, build,
   and record the checksums.
10. Run the three suites, on Python 3.13 and 3.10.

Result on 2026-11-19: dashboard 1452 passing, packaging 47 passing, evals 11 passing.
