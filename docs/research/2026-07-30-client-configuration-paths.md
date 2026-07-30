# Client Configuration Paths — Research for the 0.2.5 Adapters

Verified: 2026-07-30
Expires: 2026-10-28 (90-day house convention for time-sensitive evidence)
Purpose: the input `adapter.schema.json` and the three client adapters are written against in 0.2.5.

Design spec §9 says "Codex adapter paths are researched and verified against current first-party
documentation during phase 0.3.0 and are not asserted by this document", and §18 routes that
question to 0.3.0. This is that research. It unblocks the Codex adapter.

Feature availability and vendor paths are time-sensitive by the rule in `references/LEDGER.md`,
which is why this document carries an expiry rather than reading as settled fact.

## 1. Four findings that change the adapter design

These are not path lists. Each one would produce a wrong adapter if assumed away.

**Claude Code does not read `AGENTS.md`.** Its own documentation states it reads `CLAUDE.md`, not
`AGENTS.md`, and recommends an import or a symlink if you keep both. An adapter that probes
`AGENTS.md` for Claude Code would report an inert file as live configuration.

**Skill precedence is inverted relative to settings precedence in Claude Code.** Settings resolve
managed → local → project → user. Skills resolve enterprise → personal → project. Reusing one
resolver for both is a correctness bug, not a simplification.

**Both clients' roots are relocatable.** `CLAUDE_CONFIG_DIR` moves everything under the Claude Code
user root; `CODEX_HOME` does the same for Codex, and Codex fails at startup if the directory does
not exist. An adapter that hardcodes the default root scans the wrong tree and reports a clean
baseline for an environment it never looked at.

**`~/.claude.json` is application state, not a settings file.** Permissions, hooks, and `env` placed
there are ignored by Claude Code. Drift detection on those keys would be measuring something that
has no effect.

## 2. Claude Code

### Configuration

| Level | Path | Holds |
|---|---|---|
| User | `<user-root>/settings.json` | permissions, hooks, env, model, enabled plugins |
| User | `<user-root>/CLAUDE.md` | instructions for every project |
| User | `<user-root>/rules/*.md` | user-level rules |
| User | `<user-root>/skills/<name>/SKILL.md` | personal skills |
| User | `<user-root>/agents/`, `commands/`, `workflows/`, `output-styles/` | extensions |
| User | `<home>/.claude.json` | application state, and MCP servers at local and user scope |
| Project | `./CLAUDE.md` or `./.claude/CLAUDE.md` | project instructions |
| Project | `./CLAUDE.local.md` | personal project instructions, gitignored |
| Project | `./.claude/settings.json` | team settings, committed |
| Project | `./.claude/settings.local.json` | personal overrides, gitignored |
| Project | `./.claude/rules/**/*.md` | path-scoped rules |
| Project | `./.mcp.json` | project MCP servers — at the repository root, **not** inside `.claude/` |
| Managed | platform-specific policy directory | enterprise policy, plus Windows registry policy keys |

`<user-root>` is `~/.claude` unless `CLAUDE_CONFIG_DIR` says otherwise.

### Precedence

Settings: managed policy → CLI arguments → project local → project → user. Permission rules **merge**
across scopes rather than overriding.

`CLAUDE.md` is not precedence at all — the files are concatenated, managed → user → project
root-down, with the file closest to the working directory read last.

Skills: enterprise → personal → project. Note the inversion against settings.

MCP: local → project → user. The whole server entry from the winning source is used; fields are not
merged.

### Plugins and skills

Plugins installed from a marketplace are **copied into a cache directory** under the user root, not
used in place. Registry state lives in `installed_plugins.json` and `known_marketplaces.json` beside
it. Enabled state is a key in `settings.json` at any scope and survives reinstall.

### Files that can carry secrets

The credentials file (OAuth tokens, on platforms that do not use the OS keychain); `~/.claude.json`
(MCP `env` values and `headers`); project `.mcp.json` (same); any settings file's `env` block. Also
transcripts, session files, and memory directories, which can contain pasted secrets.

Three settings keys name **shell commands that mint secrets** — an API-key helper, an auth-refresh
command, and an MCP headers helper. A scanner must never execute them. Hash bytes, record key names.

### Machine-readable enumeration

None. There is no command that dumps effective configuration as JSON, and no `config` subcommand.
The closest are a diagnostics command and per-subsystem listings, all human-readable. An adapter must
parse the layers itself.

## 3. Codex

### Configuration

| Level | Path | Holds |
|---|---|---|
| User | `<codex-home>/config.toml` | model, approvals, sandbox, MCP servers, providers, profiles |
| User | `<codex-home>/auth.json` | credentials, when the credential store is set to file |
| User | `<codex-home>/AGENTS.md`, `AGENTS.override.md` | global instructions |
| User | `<codex-home>/<profile>.config.toml` | profile overlay |
| User | `<home>/.agents/skills/` | user-scope skills — the **documented** search root |
| Project | `<repo>/.codex/config.toml` | project config, loaded only when the project is trusted |
| Project | `<repo>/AGENTS.md` plus one per directory down to the working directory | instructions |
| Project | `<cwd>/.agents/skills` and every parent to the repository root | project skills |
| System | `/etc/codex/config.toml`, `/etc/codex/skills` | Unix system scope |

`<codex-home>` is `~/.codex` unless `CODEX_HOME` says otherwise.

### Precedence

Config: CLI overrides → project `.codex/config.toml` closest to the working directory → profile →
user → system → defaults.

`AGENTS.md` is concatenated root-down; the closer file wins on conflict. At each level an override
file **replaces** that level rather than extending it. The chain is truncated at a byte limit, so a
more specific file can be dropped silently — worth surfacing in a baseline rather than hiding.

Skills: repository → user → admin → system.

### Files that can carry secrets

`auth.json` is the highest-risk file in either client — access and refresh tokens in plaintext when
the store is set to file. On other settings the credentials live in the OS keyring, keyed by the
configuration home, so different `CODEX_HOME` values are isolated credential stores.
`config.toml` can carry a literal bearer token, MCP `env` and headers, and command-backed auth.

Note one useful distinction: a provider's `env_key` holds a variable **name**, not a value. Recording
it is safe; the value lives in the process environment.

### Machine-readable enumeration

Better than Claude Code. A doctor command emits a redacted machine-readable support report, and MCP
listing and get commands accept a JSON flag. There is still no command that dumps merged effective
configuration, so the TOML layers must be parsed.

## 4. The generic fallback

Two genuine cross-vendor standards exist, and neither solves what a generic adapter needs.

**AGENTS.md** is a real vendor-neutral convention for instructions, stewarded under a foundation and
adopted broadly. But see finding 1: Claude Code is not among the clients that read it.

**Agent Skills** is a real cross-vendor standard for capabilities — a directory containing
`SKILL.md` with required `name` and `description` frontmatter. Its critical limit for this work: the
specification defines the skill directory's **internal layout only**. It does not say where on disk
skills live. A generic adapter can recognize a skill by finding `SKILL.md`; it cannot infer which
client loads it.

**The `.agents/` directory** is converging but unratified. `.agents/skills/` is the strongest signal,
being a documented Codex search root. Beyond skills there is no agreement — several competing
proposals define different structures for MCP configuration, hooks, and memories.

This supports the design spec's decision that the generic adapter "probes nothing" by default. A
defensible minimum, if we later want one: `AGENTS.md` walking up to the repository root, `SKILL.md`
under the `.agents/skills` roots, and `.mcp.json` at the repository root — recording everything else
as unknown rather than guessing a vendor.

## 5. What this means for `scan`

- Anchor roots must come from the environment variables when set, never from a hardcoded default.
  `$USER_CONFIG` is `CLAUDE_CONFIG_DIR` or `CODEX_HOME` before it is `~/.claude` or `~/.codex`.
- Precedence is per-subsystem, not per-client. The adapter format needs to express that settings and
  skills resolve differently within one client, or the baseline will misreport which file wins.
- Several probe targets are secret-bearing. The `sensitive_key_patterns` rule in design spec §9 is
  not optional decoration for these clients; it is the only thing standing between a baseline and a
  token.
- Three configuration keys in Claude Code name shell commands that produce secrets. `scan` is
  read-only by definition, and this is a concrete reason the definition matters.

## 6. Confidence

**Claude Code: high.** Every path and precedence rule came from the vendor's current documentation,
and the user-level layout was confirmed against a live installation. One gap: whether the MCP listing
command supports a JSON flag is unverified.

**Codex: medium.** Configuration, home, precedence, instruction chain, skill roots, and the JSON
commands all came from vendor documentation and were confirmed on disk. But the plugin install path
and the file recording enabled state are absent from primary documentation, the hosted docs carry no
version numbers, and a skills directory exists under the configuration home while being absent from
the documented search list. Treat that directory as real-but-undocumented and probe both.

**Generic: medium.** Both standards are verified primary sources, but neither pins skills to a disk
location, and the surrounding directory convention is genuinely unsettled.

## 7. A note on citing this

Vendor documentation for both clients moved during this research — previously published URLs now
redirect, and sub-paths were reorganized. Any adapter or document that hardcodes a documentation URL
is already at risk of going stale. Cite the vendor and the date, not the URL alone.
