# Plugin formats: a root manifest, `/dashboard` as a skill, directory limits

Status: approved 2026-11-18 (review decisions in `docs/reviews/2026-11-18-revisao-do-plugin.md`)
Target version: 0.9.0
Phase: sixth increment of the 2026-11 review

## 1. The problem

The plugin's packaging was written in July against formats that have since moved. Four things
are out of date, and one of them is a defect a user meets on first use.

Everything below was re-read in the vendors' documentation on 2026-11-19, and the two things the
documentation leaves open were tried against the clients themselves: Claude Code 2.1.326 and
codex-cli 0.146.0.

## 2. `/dashboard` only works inside this repository

`commands/dashboard.md` runs `python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`,
a path relative to the repository root. From any other project the file does not exist. 0.6.1
began shipping the command in the plugin archive, with the same path.

Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` in the body of a plugin's skills, commands and
agents, and its documentation calls `commands/` "the older format" that "skills supersede".

So the command becomes a skill:

- `commands/dashboard.md` moves to `skills/dashboard/SKILL.md`. In a plugin, a skill directory
  named `dashboard` is invoked as `/agent-ingest-audit-optimize:dashboard`, the name the command
  already had.
- The script is invoked through `${CLAUDE_PLUGIN_ROOT}`. The body also says where the script is
  relative to the skill's own directory, for a client that does not expand the variable.
- `disable-model-invocation: true`, and `allow_implicit_invocation: false` in the skill's
  `agents/openai.yaml`. As a command it ran only when a person typed it; as a skill it would
  otherwise be offered to the model on every turn, and two of its three words write to a ledger.
  0.8.0 took the dashboard out of what the agent does unasked, and this keeps it out.
- `commands/` is removed. Nothing else lived there.

`SKILL.md` of the main skill named `dashboard.py` eight times without once saying where it is.
It now does: `assets/scripts/dashboard.py`, inside the skill's directory.

## 3. A root `plugin.json`

The Agent Plugins specification, version 1.0.0, requires the manifest "at `plugin.json` in the
plugin root" and allows exactly ten top-level fields. Client-specific data goes under `extensions`,
keyed by a reverse-domain namespace. OpenAI's documentation calls the root file "the portable entry
point" and keeps `.codex-plugin/plugin.json` "as a compatibility fallback".

- A root `plugin.json` is added with `$schema`, `name`, `version`, `description`, `author`,
  `homepage`, `repository`, `license`, `keywords` and `extensions`.
- OpenAI's interface fields go in `extensions.com.openai.interface`.
- `.codex-plugin/plugin.json` stays. OpenAI states that when `extensions.com.openai` is present it
  "replaces the entire `.codex-plugin/plugin.json` overlay", with no merge. Two copies that can
  silently disagree are therefore a hazard, and a test holds the two interface objects equal.
- `.claude-plugin/plugin.json` stays the Claude Code manifest: its documentation names no other
  location. It gains `displayName` and `keywords`, both documented optional fields.
- All three manifests carry one name and one version. The packager refuses to build otherwise,
  and the version-consistency suite gains the third file.

Claude Code's documentation does not mention a root `plugin.json` at all. Whether the extra file
disturbs it is settled by running `claude plugin validate --strict` on the extracted archive.

## 4. The OpenAI directory's limits

The submission page limits `displayName` and `shortDescription` to 30 characters each. The shipped
`shortDescription` has 49. It is shortened, and `supportURL`, which the page requires and the
manifest lacked, is added. A test holds every stated limit: both 30-character fields,
`longDescription` at 4,000, at most three `defaultPrompt` entries of at most 128 characters, and
the four URLs as HTTPS.

These limits were read from a summarised fetch of the page, not its raw text. They are tested
because being under a limit that turns out to be looser costs nothing.

## 5. What does not change

- `codex plugin add <plugin>@<marketplace>` in the README. The hosted documentation lists only the
  `marketplace` subcommands, and the review flagged the line as possibly stale. `codex plugin
  --help` on 0.146.0 lists `add` ("Install a plugin from a configured marketplace snapshot"), and
  the command installed the extracted archive in a trial. The line is right.
- The two marketplace files. Codex also reads `.claude-plugin/marketplace.json` as a legacy
  location. Neither file ships in the archive; both describe the repository.
- The eval suite's layout. `claude plugin eval` expects another one; converting is not part of
  this increment.
- No icon is added to `agents/openai.yaml`: the logo lives outside the skill directory, and the
  portable Skill archive could not carry it.

## 6. Tests

- The root manifest: the canonical `$schema`, no field outside the permitted ten, a name inside
  the specification's grammar, namespaces as objects.
- Agreement: name, version and description across the three manifests; the interface object
  across the two OpenAI locations.
- The directory limits of section 4.
- The dashboard skill: its frontmatter, the `${CLAUDE_PLUGIN_ROOT}` invocation, no
  repository-relative invocation left, and the invocation's path existing inside the built
  archive once the variable is replaced by the archive's root.
- The packager: the plugin archive ships `plugin.json` and every file under `skills/`; the
  portable Skill archive still holds exactly one skill.
- Each new guard is ablated.

## 7. Validation outside the repository

Done on the built archive, extracted to a directory that is not a checkout:

- `claude plugin validate --strict` passes and lists both skills.
- A headless Claude Code session with `--plugin-dir` shows the dashboard skill's body with the
  variable expanded to the extraction directory.
- `codex plugin marketplace add`, `codex plugin list` and `codex plugin add`, with `CODEX_HOME`
  pointing at an empty temporary directory, install the plugin at the version the root manifest
  declares.
- `dashboard.py` runs from the installed copy with another directory as the working directory.
