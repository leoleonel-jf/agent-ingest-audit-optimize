# Plan: plugin formats

Spec: `docs/specs/2026-11-19-plugin-formats.md`

Baseline on 2026-11-19, clean tree at `86a9c8f` (0.8.0): dashboard 1449 passing, packaging 48
passing, evals 11 passing.

1. Reopen the Claude Code plugin pages, the Agent Plugins specification, and the OpenAI plugin
   and submission pages. Ask for verbatim text; mark what came back as a summary.
2. Try what the documentation leaves open against the clients: `codex plugin --help`, and the
   0.8.0 archive extracted outside the repository under `claude plugin validate --strict` and under
   `codex plugin marketplace add` and `add` with an empty `CODEX_HOME`. This is the baseline the
   change is measured against.
3. Write `packaging/tests/test_plugin_formats.py` and see it fail: 21 of 24 tests, for a manifest
   and a skill that do not exist yet.
4. Add the root `plugin.json`; shorten `shortDescription` and add `supportURL` in both OpenAI
   locations; add `displayName` and `keywords` to the Claude Code manifest.
5. Move `commands/dashboard.md` to `skills/dashboard/SKILL.md` with `git mv`, give it a `name`,
   `disable-model-invocation`, the `${CLAUDE_PLUGIN_ROOT}` invocation and the relative location;
   add its `agents/openai.yaml`.
6. Packager: read the root manifest, refuse on disagreement, ship it, ship every skill in the
   plugin archive and only the canonical one in the portable archive.
7. Say in the main `SKILL.md` where `dashboard.py` is.
8. Ablate each guard.
9. Version pins (now ten files), CHANGELOG, `docs/releases/v0.9.0.md`, build, checksums.
10. Validate the built archive outside the repository in both clients, and run `/dashboard` from
    the extracted plugin in a project that is not this one.

Result on 2026-11-19: dashboard 1449 passing, packaging 73 passing, evals 11 passing. Sixteen
ablations held.

Validation of the 0.9.0 archive, extracted to a temporary directory:

- Claude Code 2.1.326: `claude plugin validate --strict` passed and listed
  `agent-ingest-audit-optimize:agent-ingest-audit-optimize` and
  `agent-ingest-audit-optimize:dashboard`. The root `plugin.json` did not disturb it.
- codex-cli 0.146.0, `CODEX_HOME` set to an empty directory: `marketplace add`, `list` and
  `plugin add` succeeded; the plugin was cached under `.../agent-ingest-audit-optimize/0.9.0`,
  with both skills. `dashboard.py verify` ran from that installed copy with another directory as
  the working directory.
- `/agent-ingest-audit-optimize:dashboard anchors`, run headless with `--plugin-dir` in a
  temporary project holding only a minimal ledger: the skill
  loaded, the variable resolved to the extraction directory, `update anchors` exited `0` and
  wrote a 215 KB `dashboard.html` beside the ledger, which it left untouched.

One thing the Codex trial showed and this increment does not act on: with an empty `CODEX_HOME`,
`codex plugin list` still reads a personal marketplace from the home directory.
