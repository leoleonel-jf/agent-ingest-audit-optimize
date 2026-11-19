# Client Configuration Paths: re-verification for the 0.7.0 adapters

Verified: 2026-11-19
Expires: 2027-02-17 (90-day house convention for time-sensitive evidence)
Supersedes: `2026-07-30-client-configuration-paths.md`, which expired on 2026-10-28
Purpose: the evidence `claude-code.json`, `codex.json` and `generic.json` are written against in 0.7.0.

Every path the adapters declare was reopened in the vendor's documentation on 2026-11-19, and so
was every location the review of 2026-11-18 listed as read by a client and not probed. Each row
below names the page and the kind of evidence. Nothing here was carried over from July unread.

## How to read the evidence column

| Mark | Meaning |
|---|---|
| **V** | Verbatim text of the vendor's documentation, read on 2026-11-19 |
| **S** | Vendor documentation, but the fetch returned a model-written summary of that part of the page, not its raw text. Weaker than V |
| **C** | The client's own source on its `main` branch, read on 2026-11-19, no commit pinned. Says what the code does, not what the vendor promises |
| **D** | Confirmed on a live Windows installation, by file and key names only |

Claude Code pages are under `https://code.claude.com/docs/en/` and were fetched as markdown (the
page name plus `.md`). None shows a "last updated" date. Codex pages are under
`https://learn.chatgpt.com/docs/`; every `https://developers.openai.com/codex/...` URL now answers
with a 308 redirect to that host. The Codex plugin page is
`https://developers.openai.com/plugins/build/plugins.md`. The Codex source files are
`codex-rs/ext/skills/src/host_roots.rs` and `codex-rs/config/src/loader/mod.rs` in
`github.com/openai/codex`.

## 1. What changed since July

**Claude Code reads `AGENTS.md`.** July's first finding was that it does not. Since v2.1.277 it
does, by default only when the working directory and its parents hold no `CLAUDE.md`,
`.claude/CLAUDE.md` or `CLAUDE.local.md`. The condition also depends on a setting and on the
session, so the existence of the file does not prove it was loaded.

**The Claude Code state file is relocatable.** `.claude.json` follows `CLAUDE_CONFIG_DIR`. July
treated it as fixed at `~/.claude.json`.

**`settings.local.json` is a project file only.** The adapter probed it under the user root since
0.2.5 because a live machine had one there. That copy is the project-local file of sessions
started in the home directory.

**Codex skills with one name do not override each other.** The adapter declared an override order
for them. The documentation now says both can appear.

**Codex has a Windows system directory.** `%ProgramData%\OpenAI\Codex` holds `hooks.json` by
documentation, and `config.toml` and `requirements.toml` by source. The adapter had no Windows
candidate for the system layer, so the layer was skipped there as not applicable.

**Managed MCP, managed skills and managed subagents have documented locations in Claude Code.**
July recorded managed MCP as having no primary source.

## 2. Claude Code

### Declared paths

| Path | Verdict | Evidence |
|---|---|---|
| `managed-settings.json` in `/Library/Application Support/ClaudeCode`, `/etc/claude-code`, `C:\Program Files\ClaudeCode` | holds | V `managed-settings` |
| `managed-settings.d/*.json` beside it, merged alphabetically after the main file | holds | V `managed-settings`: "next to `managed-settings.json` in the same system directory" |
| `C:\ProgramData\ClaudeCode\managed-settings.json` as a file the client does not read | holds; the page no longer names the version that stopped | V `managed-settings`: "doesn't read the legacy Windows path" |
| `~/.claude/settings.json` | holds | V `settings` |
| `~/.claude/settings.local.json` | **not documented; probe removed** | V `claude-directory`: "`settings.local.json` \| Project only" |
| `~/.claude/CLAUDE.md` | holds | V `memory` |
| `~/.claude/rules/*.md` | holds; recursion is stated for project rules only | V `memory` |
| `~/.claude/skills/<name>/SKILL.md` | holds | V `skills` |
| `~/.claude/agents/`, `~/.claude/commands/` | holds; subagent directories are scanned recursively | V `sub-agents`, `claude-directory` |
| `~/.claude/plugins/installed_plugins.json`, `known_marketplaces.json` | holds; the plugins root moves with `CLAUDE_CODE_PLUGIN_CACHE_DIR` | V `plugins/loading` |
| `~/.claude.json`, user-scope MCP servers | **moved: under `CLAUDE_CONFIG_DIR` when set**. The page names the file and not the key; top-level `mcpServers` is D | V `claude-directory`: "The same applies to `.claude.json`"; V `mcp`; D |
| `./CLAUDE.md`, `./.claude/CLAUDE.md`, `./CLAUDE.local.md` | holds | V `memory` |
| `./.claude/rules/**/*.md` | holds | V `memory`: "discovered recursively" |
| `./.claude/skills/<name>/SKILL.md` | holds | V `skills` |
| `./.claude/settings.json`, `./.claude/settings.local.json` | holds | V `settings`, `claude-directory` |
| `./.mcp.json`, top-level `mcpServers` | holds | V `mcp` |

### Resolution

| Kind | Verdict | Evidence |
|---|---|---|
| Settings: managed, command line, project local, shared project, user | holds | V `settings`: "Settings precedence, highest first" |
| Permission lists merge across scopes | holds | V `settings`: "combines the lists instead of picking one" |
| Skills: enterprise over personal over project | holds | V `skills` |
| Subagents: managed, `--agents`, project, user, plugin | new; the kind was undeclared | V `sub-agents`, priority table |
| MCP: local, project, user, plugin, connectors; the whole entry wins, no field merge | holds | V `mcp` |
| `managed-mcp.json` deployed: only its servers load | new | V `managed-mcp`: "Claude Code loads only these MCP servers" |
| Instruction files are concatenated in load order | holds | V `memory` |

### Read by the client and now probed

| Path | Evidence |
|---|---|
| Managed `CLAUDE.md` in the three managed directories | V `memory`, locations table |
| `managed-mcp.json` in the three managed directories, top-level `mcpServers` | V `managed-mcp` |
| `.claude/skills/<name>/SKILL.md` in the managed settings directory | V `skills`, "Enterprise" row |
| `.claude/agents/` in the managed settings directory | V `sub-agents`: "inside the managed settings directory" |
| `./.claude/agents/` | V `sub-agents` |
| `./.claude/commands/` | V `claude-directory`; V `skills`: "`.claude/commands/` files keep working" |
| `./AGENTS.md`, `./.claude/AGENTS.md` | V `memory`: "every `AGENTS.md` and `.claude/AGENTS.md` in your working directory and the directories above it" |

`AGENTS.md` in full, because the adapter can only record that the file exists: Claude Code reads it
"only when you have no `CLAUDE.md` in your working directory or above it" (V `memory`); reading it
"requires Claude Code v2.1.277 or later"; a setting can make the client read both files, only
`CLAUDE.md`, or only managed instructions; sessions before v2.1.281 on some providers read
`CLAUDE.md` only. `AGENTS.local.md`, `AGENTS.override.md` and anything under `.agents/` are not
read.

### Read by the client and still not probed

| Location | Why not |
|---|---|
| Local-scope MCP servers, `projects/<project path>/mcpServers` in `.claude.json` (V `mcp`, D) | Keyed by an absolute project path. A probe pointer is fixed text and cannot name it |
| `Settings` value under `HKLM\SOFTWARE\Policies\ClaudeCode` and `HKCU\...` (V `managed-settings`) | The format reads files. A registry value is not one |
| macOS preference domain `com.anthropic.claudecode` (V `managed-settings`) | Same |
| Server-managed settings, cached at `~/.claude/remote-settings.json` (V `claude-directory`, `server-managed-settings`) | A cache of remote policy, not the policy. Left for a deliberate decision |
| `managedMcpServers`, `claudeMd`, and other keys inside managed settings | Already inside files the adapter hashes whole; no per-key probe |
| Nested `<subdir>/.claude/skills/`, parent-directory skills, `--add-dir` directories (V `skills`) | Depend on where the session starts and what it touches |
| `~/.claude/skills/synced/` (V `skills`) | Downloaded from the account and overwritten by sync; matched today by the user skills glob as one more directory only if it holds a `SKILL.md` directly |
| `plugins/known_marketplaces_claudeai.json`, `flagged-plugins.json`, `plugins/synced/` (V `plugins/loading`) | Not needed to say which plugins are installed |
| `output-styles/`, `workflows/`, `agent-memory/`, `keybindings.json`, `themes/`, `projects/<project>/memory/` (V `claude-directory`) | No baseline kind fits them. Adding a kind is a format change, out of scope here |
| Nested subagent directories below `agents/` | The glob is one level deep. Recursion is documented (V `sub-agents`); widening the glob renames existing items and was left for a change of its own |

### Machine-readable enumeration

Still none for effective configuration. `claude mcp list` has no documented JSON flag (V `mcp`,
read in full). `claude plugin list --json` is mentioned (V `plugins/loading`).

## 3. Codex

### Declared paths

| Path | Verdict | Evidence |
|---|---|---|
| `<codex-home>/config.toml` | holds | V `config-file/config-basic` |
| `<codex-home>/<profile>.config.toml` | holds, and is now the only profile mechanism | V `config-file/config-advanced`: "In Codex 0.134.0 and later, `--profile` no longer reads `[profiles.profile-name]`" |
| `<codex-home>/AGENTS.md`, `AGENTS.override.md` | holds; the override is read instead of the plain file | V `agent-configuration/agents-md` |
| `<repo>/AGENTS.md`, `AGENTS.override.md` from the project root down to the working directory | holds; 32 KiB default limit | V `agent-configuration/agents-md` |
| `~/.agents/skills`, `<cwd and parents>/.agents/skills`, `/etc/codex/skills` | holds | V `build-skills` |
| `<codex-home>/skills` | not in the documentation; still scanned, marked deprecated in source | C `host_roots.rs`: "Deprecated user skills location" |
| `<repo>/.codex/config.toml`, trusted projects only | holds | V `config-file/config-basic` |
| `/etc/codex/config.toml` | holds on Unix | S `config-file/config-basic`; C `loader/mod.rs` |
| Skill resolution as an override order | **wrong now; declared as `merge`** | V `build-skills`: "Codex doesn't merge them; both can appear in skill selectors" |
| Config: command line, project, profile, user, system | holds; a cloud-managed layer now sits between user and system | S `config-file/config-basic`; C `loader/mod.rs` |

`<codex-home>` is `~/.codex` unless `CODEX_HOME` says otherwise (V `config-file/config-advanced`).

### Read by the client and now probed

| Path | Evidence |
|---|---|
| `hooks.json` in `<codex-home>`, `<repo>/.codex/`, `/etc/codex/`, `%ProgramData%\OpenAI\Codex\` | V `hooks`, locations table |
| `rules/*.rules` under `<codex-home>` and `<repo>/.codex/` | V `agent-configuration/rules`: "scans `rules/` under every active config layer" |
| `agents/*.toml` under `<codex-home>` and `<repo>/.codex/` | V `agent-configuration/subagents` |
| `[mcp_servers.<name>]` in the user and project `config.toml` | V `extend/mcp` |
| `[plugins."<name>@<marketplace>"]` in the user and project `config.toml` | V `plugins/build/plugins.md` |
| `/etc/codex/requirements.toml`, `%ProgramData%\OpenAI\Codex\requirements.toml` | S `enterprise/managed-configuration`; C `loader/mod.rs` |
| `%ProgramData%\OpenAI\Codex\config.toml` and `skills` beneath it | C `loader/mod.rs` only. Probed because the anchor exists for `hooks.json`; treat an item there as real-but-undocumented |

The Windows directory is shipped as `C:/ProgramData/OpenAI/Codex`. The client resolves the
ProgramData known folder and falls back to that literal (C); an adapter candidate cannot expand an
environment variable inside a longer path, so a machine with ProgramData elsewhere needs a user
adapter.

`requirements.toml` is recorded as kind `permission-rule`, scope `managed`: it constrains which
approval policies, sandbox modes and commands are allowed. It is not a configuration layer and is
not ranked against one.

### Read by the client and still not probed

| Location | Why not |
|---|---|
| `[hooks]` inline in `config.toml` (V `hooks`) | The file is already hashed whole; a pointer probe can be added when a baseline needs hook-level items |
| `/etc/codex/managed_config.toml` (C), `~/.codex/managed_config.toml` on Windows (S, contradicted by C) | Legacy, and the two sources disagree about Windows |
| macOS preference domain `com.openai.codex` (S), registry value `RequirementsPath` under `HKLM\SOFTWARE\Policies\OpenAI\Codex` (C) | Not files |
| `<repo>/.codex/skills` (C) | Source only, and the mapping from layer to directory was not visible in what was read |
| `~/.codex/plugins/cache/`, marketplace files at `~/.agents/plugins/marketplace.json`, `<repo>/.agents/plugins/marketplace.json`, `<repo>/.claude-plugin/marketplace.json` (V `plugins/build/plugins.md`) | The page says the desktop app reads the marketplace files and does not say the CLI does. Enabled state is covered by the `/plugins` probe |
| System-layer `rules/` and `agents/` | Implied by "every active config layer", stated for no system path |
| `~/.codex/prompts/` | No page read mentions it, deprecated or otherwise |

### Machine-readable enumeration

`codex mcp list` is documented; a JSON flag is not stated on the pages read (V `extend/mcp`).

## 4. The generic fallback

Unchanged: one anchor, no probes, nothing that can age. Its date moves with the other two because
the three ship and expire together.

## 5. Confidence

**Claude Code: high.** Every declared path and every resolution rule has verbatim support from a
page read on the day. One key name, top-level `mcpServers` in `.claude.json`, rests on a live
installation, not the documentation.

**Codex: medium.** The paths added in 0.7.0 are verbatim, except `requirements.toml`, which rests
on a summarised fetch plus source. The system `config.toml` on Unix and the configuration
precedence rest on the same weaker pair. The hosted documentation carries no version numbers
beyond the two it names (0.134.0, 0.138.0), and several long pages were read from an offset that
skips their navigation.

**What would lower either:** a fetch that returns raw text where this one returned a summary and
disagrees with it. The rows marked S are the ones to reopen first.

## 6. A note on citing this

Unchanged from July, and proven again: the whole Codex documentation moved hosts between the two
verifications. Cite the vendor and the date, not the URL alone.
