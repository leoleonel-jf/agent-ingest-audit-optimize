# Plan: rename to `plugin-reviewer`

Spec: `docs/specs/2026-11-19-rename-plugin-reviewer.md`

Baseline on 2026-11-19, clean tree at `0964531` (0.10.0): dashboard 1510 passing, packaging 74
passing, evals 11 passing over 39 cases.

1. Reopen the Claude Code pages on renaming and on hosting a marketplace, the page on updating a
   published plugin, and the OpenAI plugin pages. Ask for verbatim text; mark what came back as a
   summary.
2. Measure who the rename can break: stars, forks, traffic, and release downloads.
3. Ask the owner the four decisions, one at a time. Rename the GitHub repository first, so old
   URLs redirect while the work is in flight.
4. Fingerprint the two real global data directories. Copy them, move the copies to the new name,
   and compare `verify`, `verify --chain` and `chain --head` before and after.
5. Write `packaging/tests/test_rename.py` and the new cases in `dashboard/tests/test_adapters.py`
   and `test_dashboard.py`, and see them fail.
6. `git mv skills/agent-ingest-audit-optimize skills/plugin-reviewer`; front matter `name`;
   the path inside `skills/dashboard/SKILL.md`; `agents/openai.yaml`.
7. Three manifests and two marketplaces: name, display name, URLs, and the `renames` map.
8. `ledgerlib/adapters.py`: the new directory, the former one still read, a note, and the refusal
   across both.
9. The Skill and `references/LEDGER.md`, `LEDGER_BASELINES.md`: the data directory rule.
10. Tests that name the directory or the archives; `evals/suite.json`, its README and script.
11. README, `CLAUDE.md`, the four legal pages, `packaging/README.md`, `docs/SUBMISSION.md`, the
    schema `$id` and titles, the logo title.
12. Ablate each guard.
13. Version pins (ten files and `TOOL_VERSION`), CHANGELOG, `docs/releases/v0.11.0.md`, build,
    checksums.
14. Validate the built archive outside the repository in both clients; try the upgrade of an
    existing installation on an isolated configuration directory; fingerprint the real data
    directories again.
15. Independent read of the diff before the pull request.
16. Apply what that read found, with a test for each correction, and ablate again.

Result on 2026-11-19: dashboard 1540 passing, packaging 92 passing, evals 11 passing over 39 cases.
Forty-nine ablations held. The independent read found one blocker and four corrections, all
applied; `docs/validation/rename-0.11.0.md` lists them.
