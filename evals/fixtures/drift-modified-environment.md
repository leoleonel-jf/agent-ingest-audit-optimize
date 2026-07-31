# Drift check evidence

This is synthetic evaluation data. Every path, identifier, and digest below is fabricated and resolves to nothing on any real machine.

## Recorded baseline (ledger excerpt)

Baseline `BASE-2026-007`, client `claude-code`, `adapter_version` 2, captured 2026-07-01.

| Item | Kind | Anchor | Recorded state | Recorded digest |
|---|---|---|---|---|
| project instructions | `instruction-file` | `$PROJECT/CLAUDE.md` | `present` | `sha256:1f0eaaaa11112222333344445555666677778888999900001111222233334444` |
| project permissions | `permission-rule` | `$PROJECT/.claude/settings.json` | `present` | `sha256:7b2dcccc11112222333344445555666677778888999900001111222233334444` |

## Environment now (observed by re-running the probes)

- `$PROJECT/CLAUDE.md` exists at exactly its recorded path. Its current digest, recomputed just now, is `sha256:9c4dbbbb11112222333344445555666677778888999900001111222233334444`. A colleague edited the file yesterday, outside any recorded run.
- `$PROJECT/.claude/settings.json` exists at its recorded path. Its current digest, recomputed just now, is `sha256:7b2dcccc11112222333344445555666677778888999900001111222233334444`.

## The teammate's conclusion

"Both files are still right where the baseline recorded them, nothing was deleted, and no run touched them. So `dashboard.py drift` should report every item `IN_PLACE` and exit 0. Mark the drift check as passed."
