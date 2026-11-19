# agent-ingest-audit-optimize

Plugin for Claude Code and Codex around one canonical Skill in `skills/agent-ingest-audit-optimize/`.
Python 3.10+, standard library only. Machine-specific notes go in `CLAUDE.local.md` (gitignored).

## Commands

- `python -m unittest discover -s dashboard/tests` - ledger, validator and dashboard suite (the large one, about 30 s)
- `python -m unittest discover -s packaging/tests` - packaging, version pins, release checksums
- `python -m unittest discover -s evals/tests` - eval suite structure
- `python evals/scripts/eval_suite.py validate` - prints the eval case count
- `python packaging/scripts/package_plugin.py build` / `verify` - deterministic archives into `dist/` (gitignored); `verify` fails without a prior `build`
- `python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py` - the ledger CLI (`verify`, `lock`, `build`, `update`, ...)

## Gotchas

- No CI: there is no `.github/`. Run all three suites locally before a PR; "checked in CI" describes a command, not a pipeline.
- `.agent-audit/` (ledger, dashboard, handoffs) is gitignored and exists only in the main checkout. From a worktree, read it by absolute path. Start from the newest `HANDOFF-*.md` there.
- A version bump has pins outside `packaging/tests/test_version_consistency.py`: `docs/releases/vX.Y.Z.md` and the eval case count written in prose in `docs/SUBMISSION.md`.
- After any source change, a rebuilt `dist/` has new checksums: update `docs/releases/vX.Y.Z.md` to match.
- `verify --lock` does not exist. The lockfile check is `lock <ledger> --check <lockfile>`; `verify` takes `--chain` and `--expect-head`.
- Prove every new guard by ablation: delete the guarded code, watch a named test fail, restore. Applies to documentation assertions too.
- A feature merged to `main` carries its CHANGELOG entry and version bump; do not let releases lag behind merges.
- Edit only this repository or its worktrees. Installed or marketplace copies of the plugin are overwritten on update.
