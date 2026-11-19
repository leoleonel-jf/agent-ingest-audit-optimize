# Plan: ask before recording

Spec: `docs/specs/2026-11-19-ask-before-recording.md`

Baseline on 2026-11-19, clean tree at `29fb4c8` (0.11.0): dashboard 1540 passing, packaging 92
passing, evals 11 passing over 39 cases.

1. Write the guards first.
   - `dashboard/tests/test_dashboard.py`, a new `AskBeforeRecordingTests`: the ground rule; the
     four parts of the rule in `Keep the ledger` (the offer, the yes, no answer, no one to answer);
     the answer ending with the offer; the authorization of a change as the yes for its records; a
     subagent not taking the yes; the reference section `A record needs a yes` and what it lists;
     the README and `PRIVACY.md` statements; the withdrawn wording staying withdrawn.
   - The tests that pinned the old text follow it: `OneRecordPerReviewTests`, the section table of
     `LedgerReferenceSplitTests`.
   - `evals/tests/test_eval_suite.py`: 43 cases; the new check exists and is used by every case
     that touches the record; no definition exempts the ledger from the mutation check.
   See them fail against the 0.11.0 text.
2. Rewrite `SKILL.md` (spec section 6), then `references/LEDGER.md` and
   `references/PLATFORM_ADAPTATION.md`.
3. `README.md`, `PRIVACY.md`, `evals/RUN_PROTOCOL.md`.
4. `evals/suite.json`: the two definitions, the new check, `LDG-001` and `LDG-002`, the four new
   cases, and the fixture `evals/fixtures/planted-record-consent.md`.
5. Ablate every new or rewritten guard once: mutate the guarded text, see the named test fail,
   restore, see it pass.
6. Version 0.12.0: the three manifests, both marketplaces, `README.md`, `docs/SUBMISSION.md`
   (version and case count), `ledgerlib/constants.py`, `CHANGELOG.md`.
7. Build the archives, run `verify`, write `docs/releases/v0.12.0.md` with the checksums.
8. Measure behaviour on the extracted archive in isolated sessions (spec section 10), with the two
   real ledger directories fingerprinted before and compared after.
9. An independent read of the change against the owner's decisions. Fix what it finds, each with
   a test and its ablation, rebuild, and repeat step 8 on the final archive.
10. `docs/validation/ask-before-recording-0.12.0.md`: suites, ablations, the sessions, the
    independent read, and what was not measured.
11. The three suites and the suite validator once more; open the pull request; wait for the four
    checks. Merge, tag and release wait for the owner's yes.
