# Validation of the rename, 0.11.0

Date: 2026-11-19. Spec: `docs/specs/2026-11-19-rename-plugin-reviewer.md`, section 9.
Clients: Claude Code 2.1.326, codex-cli 0.146.0.

Everything below ran outside any checkout. Client configuration was isolated in every trial: an
empty `CLAUDE_CONFIG_DIR` for Claude Code and an empty `CODEX_HOME` for Codex. The copy of the
plugin installed on the machine (0.6.0) was not loaded, updated, or removed.

## The archive

`plugin-reviewer-0.11.0-plugin.zip`, extracted to a temporary directory.

- `claude plugin validate --strict <extracted>`: `Validation passed`. It provides
  `plugin-reviewer:plugin-reviewer` and `plugin-reviewer:dashboard`.
- `claude plugin validate` on a marketplace root carrying the `renames` map: the marketplace
  manifest validates. The one warning is about `CLAUDE.md` at the root of the repository, a file
  the archive does not ship.
- The same root with the map's target changed to a name that is not listed: exit `1`,
  `renames.agent-ingest-audit-optimize: chain does not resolve (target-missing)`. The validator
  reads the map; it is not accepting it by ignoring it.
- Codex, with a local marketplace pointing at the extracted plugin: `codex plugin marketplace add`
  and `codex plugin add plugin-reviewer@plugin-reviewer` succeed, and `codex plugin list` reports
  `plugin-reviewer@plugin-reviewer  installed, enabled  0.11.0`. The cache holds both skills and
  the twelve reference files.

## An existing installation, Claude Code

A bare git repository served over HTTP on `127.0.0.1`: its first commit is tag `v0.10.0`, its
second is this release's tree. `claude plugin` commands, not a session.

| Step | What the client did |
|---|---|
| `marketplace add <url>`, at the first commit | `Successfully added marketplace: agent-ingest-audit-optimize` |
| `install agent-ingest-audit-optimize@agent-ingest-audit-optimize` | installed, `0.10.0`, enabled |
| second commit pushed, then `marketplace update` | `Successfully updated 2 marketplaces` |
| `marketplace list` | still `agent-ingest-audit-optimize`: the registration keeps the name it was added under, whatever the file now says |
| `list` | the first call still printed the `0.10.0` entry; from the second on, `No plugins installed` |
| settings after that | `enabledPlugins` holds `plugin-reviewer@agent-ingest-audit-optimize`: the `renames` map rewrote the key. `installed_plugins.json` is empty |
| `install plugin-reviewer@agent-ingest-audit-optimize` | installed, `0.11.0`, enabled |

So the map does what the documentation says and no more: the key moves, and the plugin is absent
until it is installed once under its new name. The marketplace's own new name never reaches a
machine that had it registered.

The other path, from that state:

| Step | What the client did |
|---|---|
| `marketplace remove agent-ingest-audit-optimize` | removed, and the plugin from it uninstalled |
| `marketplace add <url>` | `Successfully added marketplace: plugin-reviewer` |
| `install plugin-reviewer@plugin-reviewer` | installed, `0.11.0`, enabled; settings hold only the new keys |

`marketplace remove` says it "also deletes their saved options, secrets and data where it can". A
directory named `agent-ingest-audit-optimize/` and one named `plugin-reviewer/`, each holding a
placeholder `ledger.json`, were put in the isolated configuration root before a removal. Both were
intact after it: the ledger's directory is not the plugin data directory the client manages.

Not shown by this trial: the `/plugin` commands typed inside a session, a marketplace added as
`owner/repo` from GitHub instead of by URL, and the background auto-update.

## An existing installation, Codex

The same server, with a marketplace whose plugin entry is a local path inside the repository.

| Step | What the client did |
|---|---|
| `marketplace add <url>`, former names | `Added marketplace agent-ingest-audit-optimize` |
| `add agent-ingest-audit-optimize@agent-ingest-audit-optimize` | installed, `0.10.0` |
| commit with the current names pushed, then `marketplace upgrade` | exit `1`: `upgraded marketplace name plugin-reviewer does not match configured marketplace agent-ingest-audit-optimize` |
| `list` | the former plugin, still `installed, enabled`, `0.10.0` |
| `remove agent-ingest-audit-optimize@agent-ingest-audit-optimize`, `marketplace remove agent-ingest-audit-optimize` | both removed |
| `marketplace add <url>`, `add plugin-reviewer@plugin-reviewer` | installed, `0.11.0`; `config.toml` holds only the new keys |

Codex refuses the renamed marketplace instead of following it, so an existing installation keeps
working at 0.10.0 and never moves on its own. The published marketplace is added with `--ref`
naming a tag, which does not advance either.

An isolated `CODEX_HOME` does not hide a marketplace declared in the user's home directory: Codex
listed one. The trial wrote nothing there.

## Moving a data directory

On copies of two real global ledgers, one per client. Each command ran against the copy under the
former directory name and again after the directory was renamed to `plugin-reviewer`; outputs were
compared with the directory's own path normalised.

| Command | Ledger of 17 records, sealed | Ledger of 8 records, never sealed |
|---|---|---|
| `verify` | exit 0, identical | exit 0, identical |
| `verify --chain` | exit 0, identical | exit 1, identical |
| `chain --head` | same head | exit 1, identical |
| `build` | exit 0, identical | exit 0, identical |
| `rollback-preview`, every run | 5 runs, identical | 3 runs, identical |

The only fields that contain the former name are a project path under `known_projects` and one
`ledger_id`. Neither names the data directory, and no run in either copy keeps its backup inside
it. That is why these two moved cleanly, and it is not true of every ledger: a run whose
`backup.path` is anchored inside the directory previews `HEALTHY` before the move and `BROKEN`,
reason `missing`, after it. `MovedDataDirectoryTests` in `dashboard/tests/test_rollback.py` builds
that ledger and shows both halves.

## An independent read

Before the pull request, a reader that had not seen the work read the whole change against the
spec, read-only. It found one blocker and four things to correct, all corrected:

- the Skill, the reference, the README, the CHANGELOG and the release document called renaming the
  data directory "the whole migration". It is not, for the reason above. They now say when it is
  safe and what to read first;
- `references/LEDGER_BASELINES.md` named the new directory as where a user adapter goes, without
  the condition the Skill states, so following it would have created the second directory;
- the message for an unknown client did the same. It now names the directory in use;
- the former name left as a link to the renamed directory made every adapter in it a duplicate of
  itself, and `scan`, `drift`, `build` and `update` refused to run. Reproduced with a junction, now
  read once;
- the CHANGELOG and the release document said each path "was tried" while showing `/plugin`
  commands and an `owner/repo` marketplace. The trial drove `claude plugin` and `codex plugin`
  against a marketplace added by URL, and they now say so.

It also found the tests of the migration steps satisfied by the ordinary install sections, and
those tests now read only the part of each document written for an existing installation.

## The real data directories

The two real directories, and the two paths the new name would occupy, were fingerprinted (SHA-256
of every file) before the first trial and after the last. 31 files and 346 files, identical. The
new-name paths were absent before and after. The modification times of the user's
`installed_plugins.json`, `known_marketplaces.json`, and `settings.json` did not change.

## Activation

The description did not change; the name the Skill is listed under did, from
`agent-ingest-audit-optimize:agent-ingest-audit-optimize` to `plugin-reviewer:plugin-reviewer`, and
the explicit prompts of `evals/suite.json` now say `$plugin-reviewer`.

One fresh headless session per case against the extracted archive, with the isolation the
2026-11-19 incident requires: `--restricted`, `--strict-mcp-config`, no user settings, no other
plugin, no MCP server, only `Skill`, `Read`, `WebFetch` and `WebSearch`, stopped at the first
decisive signal, and the whole process tree ended. The same twenty-two prompts as run C of
`docs/validation/lean-skill-0.10.0.md`, once each.

| Build | Sessions | Correct | Positives | Negatives |
|---|---|---|---|---|
| 0.10.0, released archive (run C, two repetitions) | 44 | 44 | 26 of 26 | 18 of 18 |
| 0.11.0, this archive | 22 | 22 | 13 of 13 | 9 of 9 |

Every positive called `plugin-reviewer:plugin-reviewer` as its first tool use. The sessions
reported the model `claude-fable-5-2`, the CLI default on the machine that day; run C reported
Claude Opus 5.5, so the two rows are not the same model. One repetition is a check that the rename
broke nothing, not a measurement of a rate.

## Ablations

Forty-nine, one per guard in the spec's section 8 and per rule the new tests state. Each
removed or broke what the guard protects, ran the named test, saw it fail, restored the file, and
saw it pass again. All held.

## Not measured

- A review from end to end under the new name. No instruction of the Skill changed except where
  its data lives.
- Activation in Codex, and with a model other than the CLI default.
- The owner's own installation, which this release does not touch.
