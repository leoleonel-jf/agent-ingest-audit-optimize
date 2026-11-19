# Adapters re-verified, and what `update` does with stale evidence

Status: approved 2026-11-18 (review decisions in `docs/reviews/2026-11-18-revisao-do-plugin.md`, finding 2)
Target version: 0.7.0
Phase: fourth increment of the 2026-11 review

## 1. The problem

The three bundled adapters expired on 2026-10-28. `scan` and `drift` have reported that as a
finding on every run since, which is the design. The date cannot simply move: `expires_on` says
"these paths were checked against the vendor's documentation", and nobody had checked since July.

Checking found that the adapters are not merely old. Two declared things are now wrong, and both
clients read files the adapters never look at. The full record, with a URL, a date and a quote per
path, is `docs/research/2026-11-19-client-configuration-paths.md`. This spec is what that record
changes in the shipped data.

A second question was left open by the review: when an adapter is stale, `update` still appends a
baseline and exits `1`. A caller cannot tell that exit `1` from any other, and a caller that must
not record a baseline taken with stale paths has no way to refuse one.

## 2. `claude-code.json`

Removed, because the documentation no longer supports it:

- The four probes of `$USER_CONFIG/settings.local.json`. `settings.local.json` is documented as a
  project file only. A file at `~/.claude/settings.local.json` is the project-local file of a
  session started in the home directory, and the project probes already cover that case.

Changed:

- The MCP probe moves from `$HOME/.claude.json` to `$APP_STATE/.claude.json`, where `$APP_STATE`
  resolves `CLAUDE_CONFIG_DIR` before `~`. The state file follows the variable; a scan that reads
  `~/.claude.json` on a relocated installation reads a file the client does not. `$HOME` is
  dropped: nothing else used it.

Added, each from a documented location the existing format can express:

| Probe | Kind | Scope |
|---|---|---|
| `$MANAGED_CONFIG/CLAUDE.md` | instruction-file | managed |
| `$MANAGED_CONFIG/managed-mcp.json`, `/mcpServers` | mcp-server | managed |
| `$MANAGED_CONFIG/.claude/skills/*/SKILL.md` | skill | managed |
| `$MANAGED_CONFIG/.claude/agents/*` | agent | managed |
| `$PROJECT/.claude/agents/*` | agent | project |
| `$PROJECT/.claude/commands/*` | command | project |
| `$PROJECT/AGENTS.md`, `$PROJECT/.claude/AGENTS.md` | instruction-file | project |

`AGENTS.md` reverses the first finding of the July research. Claude Code reads it since v2.1.277,
by default only when no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` exists in the
working directory or above it. The probe records that the file exists and what it hashes to. It
does not claim the file was loaded: `scan` computes no winner, and the condition depends on a
setting, a version and the session. Leaving it out would be the worse error, because a repository
with only an `AGENTS.md` would baseline as having no project instructions at all.

Resolution, restricted as always to scopes a probe declares:

- `skill`: `managed`, `user`, `project` ("Enterprise over personal, and personal over project").
- `agent`: `managed`, `project`, `user` (the documented priority table). New: this kind was
  undeclared.
- `mcp-server`: `managed`, `project`, `user`. The documented order is local, project, user, with
  a managed server above all of them.
- `hook`, `command`, `plugin` stay undeclared.

## 3. `codex.json`

Changed:

- `skill` resolution becomes `merge`. The documentation now says two skills with one name are not
  merged and both can appear; the shipped `override` order claimed a winner that does not exist.
- `$SYSTEM_CONFIG` gains a Windows candidate, `C:/ProgramData/OpenAI/Codex`. The hooks page
  documents that directory; `config.toml` and `requirements.toml` there are confirmed in the
  client's source.

Added:

| Probe | Kind | Scope |
|---|---|---|
| `hooks.json` under `$USER_CONFIG`, `$PROJECT/.codex`, `$SYSTEM_CONFIG` | hook | user, project, system |
| `rules/*.rules` under `$USER_CONFIG`, `$PROJECT/.codex` | permission-rule | user, project |
| `agents/*.toml` under `$USER_CONFIG`, `$PROJECT/.codex` | agent | user, project |
| `/mcp_servers` in the user and project `config.toml` | mcp-server | user, project |
| `/plugins` in the user and project `config.toml` | plugin | user, project |
| `$SYSTEM_CONFIG/requirements.toml` | permission-rule | managed |

Before this the Codex adapter had no probe for an MCP server, a hook or a plugin, although all
three live in files it already opened. None of the added kinds gets a resolution rule: no source
states how they resolve across layers, and undeclared is the recorded state for that.

## 4. `generic.json`

Unchanged. It has one anchor and no probes, so nothing in it can age.

## 5. What stays unprobed

Recorded in the research document rather than guessed at. The main ones: local-scope MCP servers
in `.claude.json` (keyed by project path, which a fixed pointer cannot name); registry and
macOS-preference policy for both clients; `managed-settings` delivered by a server; nested and
synced skills; `output-styles`, `workflows` and memory directories; Codex `managed_config.toml`
and `<repo>/.codex/skills`.

## 6. `update` and stale evidence

Two additions, and no change to what an exit code means.

**Findings as data.** `scan` already separates notes from findings internally. Each finding gets
a stable code, and `update` prints them in its JSON summary:

```json
"findings": [{"code": "adapter_expired", "message": "..."}]
```

The list is always present and is empty when nothing was found or nothing was scanned. Messages
on stderr are unchanged. `scan` keeps its three-value return; a second entry point carries the
structured form, so no existing caller changes.

**`--strict`.** With it, `update ledger` and `update all` scan first and, if the scan produced any
finding, write nothing: the ledger keeps its bytes, the dashboard is not rendered, the summary
says `"refused": "strict"` and the exit code is `1`. Without it, behaviour is exactly as before:
the baseline is appended and the exit code carries the finding. `--strict` has no effect on
`update anchors`, which never scans.

This is deliberately not "treat exit `1` as success". The default still appends because the
findings describe the environment captured, and refusing would leave the ledger asserting an
older state. `--strict` is for a caller that would rather have no baseline than one taken with
paths nobody has re-verified.

## 7. Tests

- `BundledAdapterTests` reads the expiry from the new research document and gains one test per
  changed claim: no user-level `settings.local.json`, the state file follows `CLAUDE_CONFIG_DIR`,
  `AGENTS.md` is probed, Codex has MCP, hook and plugin coverage.
- `ShippedResolutionTests` keeps exact equality on the whole map for both clients.
- `update`: findings in the summary, the stable code for an expired adapter, `--strict` refusing
  with the ledger byte-identical, `--strict` appending when the scan is clean.
- Each new guard is ablated: remove it, see a named test fail, restore.

## 8. Out of scope

No change to the adapter format or its schema. No probe for anything in section 5. `drift` keeps
its own expiry finding as it is.
