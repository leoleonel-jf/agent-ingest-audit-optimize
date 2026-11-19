# Rename to `plugin-reviewer`

Status: approved 2026-11-19 (the owner's four answers, section 2)
Target version: 0.11.0
Phase: eighth and last increment of the 2026-11 review

## 1. The problem

Since 0.10.0 the plugin leads with one request: review a plugin, a skill, or an MCP server before
adopting it. Its name still describes the pipeline it started as, `agent-ingest-audit-optimize`,
and nobody types that. The owner chose `plugin-reviewer` on 2026-11-18. This increment is the
rename and nothing else: no command, no ledger rule, and no behavior of the Skill changes.

A rename is not a search and replace. The identifier is an install key in two clients, a directory
the packager derives archive names from, a path inside a second skill, a directory on every
user's machine, and a word in sixteen release documents that must keep saying what was true when
they were written.

Everything about the clients below was re-read on 2026-11-19 in the vendors' documentation, and
what the documentation leaves open was tried against the clients themselves and is recorded in
`docs/validation/rename-0.11.0.md`.

## 2. What was decided

Asked on 2026-11-19, one decision at a time, with the measurement next to each: the repository had
0 stars, 0 forks, 0 watchers, and one page view in fourteen days, and no release asset had been
downloaded more than six times.

1. Rename the plugin and publish it as 0.11.0 once CI is green.
2. Rename the GitHub repository to `leoleonel-jf/plugin-reviewer`. Done the same day; GitHub
   redirects the old name. The local folder is not renamed.
3. Rename the marketplace too. The install id becomes `plugin-reviewer@plugin-reviewer`.
4. Leave the July directory submission alone until the release exists; its status is read
   afterwards and decided with that fact.

## 3. What changes its name

| Where | Before | After |
|---|---|---|
| `name` in `plugin.json`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` | `agent-ingest-audit-optimize` | `plugin-reviewer` |
| `name` in `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`, and each one's plugin entry | `agent-ingest-audit-optimize` | `plugin-reviewer` |
| Display name (manifests, marketplaces, `agents/openai.yaml`, README, legal pages, schema titles, logo title) | Agent Ingest, Audit & Optimize | Plugin Reviewer |
| The canonical Skill's directory and front matter `name` | `skills/agent-ingest-audit-optimize/` | `skills/plugin-reviewer/` |
| Invocation in Claude Code | `/agent-ingest-audit-optimize:agent-ingest-audit-optimize`, `/agent-ingest-audit-optimize:dashboard` | `/plugin-reviewer:plugin-reviewer`, `/plugin-reviewer:dashboard` |
| Invocation in Codex (`agents/openai.yaml`, eval prompts) | `$agent-ingest-audit-optimize` | `$plugin-reviewer` |
| Path inside `skills/dashboard/SKILL.md` | `${CLAUDE_PLUGIN_ROOT}/skills/agent-ingest-audit-optimize/...` | `${CLAUDE_PLUGIN_ROOT}/skills/plugin-reviewer/...` |
| Release archives | `agent-ingest-audit-optimize-<version>-{plugin,skill}.zip` | `plugin-reviewer-<version>-{plugin,skill}.zip` |
| Repository URL in manifests, marketplaces, legal pages, schema `$id` | `github.com/leoleonel-jf/agent-ingest-audit-optimize` | `github.com/leoleonel-jf/plugin-reviewer` |
| `suite_id` and `skill_path` in `evals/suite.json` | `agent-ingest-audit-optimize` | `plugin-reviewer` |
| Data directory for a new installation | `<user-config>/agent-ingest-audit-optimize/` | `<user-config>/plugin-reviewer/` |

The Skill's directory, its front matter `name`, and the three manifests move together because
three things require it: the Agent Skills specification (the `name` equals the directory), the
packager (`SKILL.md` front matter name must match the plugin manifests), and the second skill,
which reaches its sibling by path.

The schema `$id` is an identifier that nothing in the tool dereferences; it follows the repository
so that the old name does not survive in a shipped file for no reason.

## 4. What does not change

- **History.** Earlier CHANGELOG entries, `docs/releases/v0.1.0.md` to `v0.10.0.md`, and earlier
  specs, plans, validations, reviews, research, and prompts keep the name they were written
  under. Their install commands still work through GitHub's redirect, and
  `test_release_checksums.py` rebuilds each old tag with the packager committed at that tag, so
  their archive names stay what they were.
- **The ledger.** Its schema version, fields, record identifiers, labels, and every command. A
  ledger written by 0.10.0 verifies under 0.11.0 and the reverse. `ledger_id` values are the
  user's and are not touched.
- **A data directory that already exists.** Section 6.
- **The local checkout folder**, and anything installed on a machine. The release changes a
  repository; a user's installation changes when that user updates it.

## 5. People who already installed it

### Claude Code

The documentation (`plugins/publish`, `plugins/host-marketplace`, read 2026-11-19):

- "Never change a published plugin's `name`. After a rename, users who already installed it lose
  the plugin, because their install is recorded under the old name. A `renames` entry in your
  marketplace file migrates them instead."
- "Map each former name to its current name, or to `null` when the plugin is gone." "Treat
  `renames` as append-only history."
- For a marketplace added from a git repository: "a renamed plugin reports `Plugin "<name>" not
  cached at <path>` until the user runs `/plugin install code-formatter@your-marketplace` once in
  a session."
- "Claude Code identifies a marketplace by its `name`", and "Each user registers one marketplace
  per `name`". No page describes a migration for a marketplace whose own `name` changes. The
  `renames` map covers plugins, not marketplaces.

So `.claude-plugin/marketplace.json` gains

```json
"renames": { "agent-ingest-audit-optimize": "plugin-reviewer" }
```

which is the documented mechanism and stays in the file as history. Decision 3 changes the
marketplace's own name as well, and for that the documentation offers nothing: the supported path
for an existing installation is to remove the old marketplace and add the new one. What a client
actually does when a registered marketplace comes back from an update under another name was
tried on an isolated configuration directory, and the release document states the steps that
worked there, not the ones the map would have made sufficient.

The owner accepted that cost because, by the measurement in section 2, the only known
installation is his own.

### Codex

OpenAI's documentation (`developers.openai.com/plugins/build/plugins`, read 2026-11-19) calls the
plugin `name` a "stable" identifier, uses it in the configuration key `plugin@marketplace` and in
the cache path, and describes no rename mechanism at all. The path is the same: remove the
marketplace, add it again, install under the new name.

### Both

The invocation name changes with the plugin (section 3). Anything a user wrote that calls
`/agent-ingest-audit-optimize:dashboard` or `$agent-ingest-audit-optimize` has to be edited by
that user. The CHANGELOG and the release document say so first.

## 6. The data directory on a user's machine

The Skill keeps its global ledger, `records/`, `backups/`, and a user adapter under
`<user-config>/agent-ingest-audit-optimize/`. That is a convention the Skill's text states; the
tool takes a ledger path as an argument and knows the directory name in exactly one place, the
user adapter lookup in `ledgerlib/adapters.py`.

The rule from 0.11.0:

1. A new installation uses `<user-config>/plugin-reviewer/`.
2. A machine that already has `<user-config>/agent-ingest-audit-optimize/` keeps using it where it
   is. The Skill reads and writes it as before. It never moves it, copies it, or creates the new
   directory beside it, because two directories that both claim to be the ID authority is the
   defect the ledger's design exists to prevent.
3. When both exist, the Skill stops, names both, and asks which one is the ledger. It then uses
   the one the user names and leaves the other untouched. It never merges them on its own.
4. Moving the old directory to the new name is the user's to ask for, and it is not always
   harmless. `verify`, `verify --chain`, and `chain --head` read the ledger document only and
   answer the same before and after. A run whose `backup.path` points into the directory does
   not: the path is anchored and names the directory, so after the move it resolves to nothing
   and `rollback-preview` reports the run `BROKEN`; rewriting the path in a sealed ledger breaks
   the chain. The Skill says to read every `backup.path` before a move. The first draft of this
   section called the move "the whole migration", on the strength of two real ledgers in which no
   record names the directory; an independent read of the change found the general claim false,
   and `MovedDataDirectoryTests` now holds the behaviour.

The tool follows the same rule for user adapters. `--user-config` is searched in
`plugin-reviewer/adapters/` and in `agent-ingest-audit-optimize/adapters/`. Both are user
adapters, so the existing refusal holds across them: one client declared in both directories is
an error naming both files, never a silent choice. An adapter read from the earlier directory
adds a note that says so, and a different note when both directories hold adapters. The former
name left as a link to the renamed directory is one directory and is read once; read twice, every
adapter in it would be refused as a duplicate of itself. The message for an unknown client names
the directory in use: the former one when `--user-config` holds it and not the current one, so
that following the message never creates the second directory.

No `migrate` command is added. A directory rename needs no tool, and a command that moved a
user's ledger would be one more thing able to damage it.

## 7. The repository

Renamed on GitHub on 2026-11-19 by the owner's decision, before any file changed, so that old
URLs redirect while the new ones already resolve. `origin` in the checkout points at the new name.
`.agents/plugins/marketplace.json` pins `ref: v0.11.0` at the new URL, which is why the merge and
the tag go out together, as in every release since 0.2.1.

## 8. Guards

Each is a test, and each is proved by ablation: delete what it guards, watch that test fail,
restore.

| Guard | Test |
|---|---|
| The marketplace carries a `renames` entry from the former name to a name in `plugins` | `packaging/tests/test_rename.py` |
| Both marketplaces and all three manifests use one name, and it is not the former one | same |
| The former identifier appears in a tracked file outside history only where a listed reason puts it there | same |
| The former display name appears nowhere outside history | same |
| A user adapter in the directory's former name is still read, with a note that reaches stderr | `dashboard/tests/test_adapters.py` |
| One client declared under both directory names is refused | same |
| The former name linked to the current directory is read once | same |
| The unknown-client message names the directory in use | same |
| The Skill states the data directory rule: new name, the former one kept in place, both is a stop, and what follows the answer | `dashboard/tests/test_dashboard.py` |
| The ledger reference states the same rule in its Layout section, and what a move breaks | same |
| A backup inside the directory stops resolving after a move | `dashboard/tests/test_rollback.py` |
| README, CHANGELOG and the release document give, in the part written for an existing installation, the steps it needs, and say what was tried and what was not | `packaging/tests/test_rename.py` |

"History" in the third and fourth rows is a fixed list of paths: `CHANGELOG.md`, `docs/releases/`,
`docs/specs/`, `docs/plans/`, `docs/validation/`, `docs/reviews/`, `docs/research/`, and
`docs/prompts/`. This release adds to two of them, and those additions name the former identifier
because a user has to type it. A separate test holds the former display name out of the 0.11.0
CHANGELOG entry and out of `docs/releases/v0.11.0.md`.

## 9. Validation

Against the built archive extracted outside any checkout, as `packaging/README.md` describes:

- `claude plugin validate --strict` on the extracted plugin, and `claude plugin validate` on a
  marketplace root carrying the `renames` map;
- Codex with an empty `CODEX_HOME`: add a marketplace pointing at the extracted plugin and install
  it under the new name;
- the upgrade of an existing installation, on an isolated Claude Code configuration directory:
  install 0.10.0 from a local git marketplace, move that marketplace to 0.11.0, and record what the
  client reports and which commands restore a working installation;
- the data directory move on copies (section 6);
- a fingerprint of the two real global data directories before the first test and after the last.

Activation was measured for 0.10.0 on the description, which this increment does not change. It is
measured again only if a session can be isolated the way the 2026-11-19 incident requires.

## 10. Out of scope

- Moving the owner's real data directories, updating the copy of the plugin installed on his
  machine, and the directory submission: each needs its own decision.
- A `record` command, a write lock for the ledger, and whether a review should write to the global
  ledger without being asked: open since 0.10.0, unchanged here.
- Branch protection for `main`.
