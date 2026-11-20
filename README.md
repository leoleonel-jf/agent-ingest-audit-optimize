# Plugin Reviewer

<img src="assets/logo.png" alt="Plugin Reviewer logo" width="160">

A portable Agent Skill that reviews a plugin, a skill, or an MCP server before you adopt it: it reads what the package actually ships, checks its claims against current primary sources, compares it with your real setup, and answers with a verdict, the risks, and the way back. It also audits videos, articles, and repositories about agent setup and turns supported findings into scoped, reversible changes.

## Status

The repository contains the canonical English Skill, its portable regression suite, cross-client plugin packaging, public distribution metadata, a repository marketplace, and the MIT License.

Record IDs (`MAT-`, `PROP-`, `RUN-`, `ADR-`) are local to each installation. A fresh installation starts its own sequences at `000` (for example, `PROP-YYYY-000`); no numbering is inherited from this repository.

## What it does

- reviews something installable before it is adopted, without installing or running it, and leads with one of five verdicts: adopt, adopt with changes, try in isolation first, not yet, do not adopt;
- offers one record per review, and writes it only when you say yes;
- audits videos, articles, documentation, repositories, transcripts, files, and ideas;
- treats external material as untrusted evidence rather than executable instruction;
- checks claims against current official and primary sources;
- evaluates compatibility, scope, security, reversibility, and maintenance cost;
- creates independently authorizable proposals;
- implements one explicitly authorized proposal at a time;
- validates changes and documents rollback;
- compares model and reasoning-effort choices by representative task category.

## Portable structure

```text
skills/
└── plugin-reviewer/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── references/
    └── assets/
        └── templates/
```

The canonical bundle follows the open Agent Skills directory model: `SKILL.md` contains the portable workflow, while references and templates load only when needed. `agents/openai.yaml` is optional client metadata and does not define the core behavior.

## Plugin packaging

The repository is also a plugin, described by three manifests:

```text
plugin.json                  Agent Plugins 1.0.0, the portable entry point
.claude-plugin/plugin.json   Claude Code
.codex-plugin/plugin.json    Codex compatibility overlay
skills/plugin-reviewer/
skills/dashboard/
```

All three manifests name the same canonical Skill. No platform-specific copy of its behavior is maintained. `skills/dashboard/` is a second, user-invoked skill: it renders the ledger's dashboard when you type `/plugin-reviewer:dashboard`, and the model cannot start it on its own.

Build and verify the distributable plugin and portable Skill archives with:

```text
python packaging/scripts/package_plugin.py build
python packaging/scripts/package_plugin.py verify
```

See [packaging/README.md](packaging/README.md) for the package contract, supported uses, and platform-native validation commands.

## Install

### Codex

Add this repository as a marketplace and install the plugin:

```text
codex plugin marketplace add leoleonel-jf/plugin-reviewer --ref v0.12.1
codex plugin add plugin-reviewer@plugin-reviewer
```

Start a new Codex task after installation so the Skill can be discovered.

### Claude Code

Add this repository as a marketplace, then install the plugin:

```text
/plugin marketplace add leoleonel-jf/plugin-reviewer
/plugin install plugin-reviewer@plugin-reviewer
```

For development or testing without installing, clone the repository and load the plugin directory for a single session:

```text
claude --plugin-dir <path-to-plugin-reviewer>
```

### If you installed it as `agent-ingest-audit-optimize`

That was this plugin's name until 0.11.0. The plugin, its marketplace, and its repository were renamed together; the Skill, the commands, and the ledger are the same.

Claude Code, with the marketplace under its new name:

```text
/plugin marketplace remove agent-ingest-audit-optimize
/plugin marketplace add leoleonel-jf/plugin-reviewer
/plugin install plugin-reviewer@plugin-reviewer
```

Or keep the marketplace you already registered. Its `renames` map carries the installation over; after the update the plugin is no longer listed as installed, and one install brings it back:

```text
/plugin marketplace update agent-ingest-audit-optimize
/plugin install plugin-reviewer@agent-ingest-audit-optimize
```

The marketplace then keeps the name it was registered under, and the plugin answers as `plugin-reviewer@agent-ingest-audit-optimize`.

Codex has no rename mechanism, and `codex plugin marketplace upgrade` refuses a marketplace whose name changed, so an existing installation stays at 0.10.0. Remove both, then add the marketplace and the plugin again as shown above:

```text
codex plugin remove agent-ingest-audit-optimize@agent-ingest-audit-optimize
codex plugin marketplace remove agent-ingest-audit-optimize
```

What you type changes with the name: `/plugin-reviewer:dashboard` in Claude Code and `$plugin-reviewer` in Codex.

Your ledger does not move. A machine that already has `<user-config>/agent-ingest-audit-optimize/` (for Claude Code, `~/.claude/agent-ingest-audit-optimize/`) keeps using it where it is, and none of the commands above touches it. Renaming that directory to `plugin-reviewer` is optional, and safe when no recorded run keeps a backup inside it; [references/LEDGER.md](skills/plugin-reviewer/references/LEDGER.md) says what to check first.

### Other Agent Skills clients

Download the `plugin-reviewer-0.12.1-skill.zip` release asset and install its single top-level Skill directory according to the client's documentation.

## Use

Install or load the directory:

```text
skills/plugin-reviewer/
```

in an Agent Skills-compatible client using that client's documented personal, project, workspace, or API installation method.

Example requests:

```text
I found this plugin on GitHub and I am thinking of installing it. Review it first: is it safe, and is it worth it?
```

```text
Use plugin-reviewer to audit this article about agent configuration.
```

```text
Analyze this video, verify its claims with current official documentation, and propose only improvements that are safe to adopt globally.
```

```text
Implement proposal PROP-YYYY-NNN.
```

## Safety model

Analysis and deliberation are read-only. Nothing under review is installed, enabled, or run in order to review it. Persistent changes require an instruction that names what to implement; the proposal identifier is one way to name it. A review's record is the one exception: it is written on your yes to the offer that closes the review. Authorization covers only that proposal, and implementation stops if it encounters material data-loss risk, irreversible scope, failed backups, critical validation failure, unapproved cost, public exposure, or required scope expansion.

## Ledger

A review is recorded only when you say yes to the offer that closes it: the offer names the ledger the record would go to, a request made before it is not a yes, and a run with no one to answer (`claude -p`, `codex exec`, CI) records nothing. Every proposal, run, and decision of an authorized change is recorded. Both go in a local ledger: a global one
at the client's user configuration root, and a git-versionable one per project at
`.agent-audit/`. The ledger is local and is never transmitted.

Validate every reachable ledger in one invocation so cross-ledger checks run:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py verify <path-to-ledger.json> [more...]
```

Exit codes: `0` clean, `1` findings, `2` the ledger could not be read. The tool requires
Python 3.10 or later and uses the standard library only.

Capture what a client currently has configured with `scan`, which reads that client's
configuration and prints one baseline entry on standard output for the agent to place in a
ledger:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py scan --id BASE-YYYY-NNN [--client NAME]
```

`scan` is read-only: it writes no file and runs nothing a configuration file names. Exit codes:
`0` clean, `1` findings, `2` a tool error. See
[PRIVACY.md](PRIVACY.md) for what it reads and what a baseline can contain.

Check a captured baseline against the environment as it stands with `drift`, and preview what a
rollback of a recorded run would and would not restore with `rollback-preview`:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py drift <path-to-ledger.json>
python skills/plugin-reviewer/assets/scripts/dashboard.py rollback-preview <path-to-ledger.json> RUN-YYYY-NNN
```

Both are read-only like `scan` and print one JSON report on standard output. Exit codes: `0`
everything in place (`drift`) or a healthy rollback (`rollback-preview`), `1` drift, risk, or
findings, `2` a tool error.

Pin which installable artifacts should be present, and check the pin in CI:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py lock <path-to-ledger.json> --from BASE-YYYY-NNN --out agent.lock
python skills/plugin-reviewer/assets/scripts/dashboard.py lock <path-to-ledger.json> --check agent.lock
```

`agent.lock` is deterministic and meant to be committed: a baseline says what *was* there, a
lockfile says what *should* be there. `--check` reads nothing from the environment — comparing
against the disk as it is now is `drift`'s job, and one question must not have two answers.

Make tampering with the ledger evident by hash-chaining its records:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py chain <path-to-ledger.json> --seal
python skills/plugin-reviewer/assets/scripts/dashboard.py verify <path-to-ledger.json> --chain [--expect-head DIGEST]
```

The chain is tamper-**evident**, not tamper-proof: it detects edits, deletions and reordering,
and a wholly recomputed chain is caught only by comparing `chain --head` against a digest you
recorded outside the ledger. What the chain does and does not detect is in
[references/LEDGER_INTEGRITY.md](skills/plugin-reviewer/references/LEDGER_INTEGRITY.md).

The `compliance` command was withdrawn in 0.8.0: its control mapping misnamed the articles and
controls it cited, and this plugin does not assess regulatory compliance. The subcommand remains
only to say so and exits `2` without reading or writing anything; see `CHANGELOG.md`.

Render a ledger into a single offline HTML dashboard with `build` — vanilla JS, no framework,
no network request, and it never writes back to the ledger:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py build <path-to-ledger.json> [--out PATH] [--lang CODE] [--open]
```

Exit codes: `0` written, `1` I/O error or overwrite refusal, `2` a ledger `verify` would reject.

`--open` shows the file in the default browser once it is written. It never fires for a build
that wrote nothing, and it never changes the exit code: a machine with no browser gets a note on
stderr and still exits `0`, because the dashboard is on disk and that was the command's job.

Bring things up to date with `update`, which names the three things "refresh" can mean:

```text
python skills/plugin-reviewer/assets/scripts/dashboard.py update <path-to-ledger.json> [all|ledger|anchors] [--open] [--id BASE-YYYY-NNN]
```

`anchors` is the default and re-renders the dashboard, writing no ledger. `ledger` captures the
environment into a new `baselines[]` entry, writing no dashboard. `all` does the first, then the
second. The hash chain is untouched by all three — it links `records[]`, and a baseline is not a
record, so `verify --expect-head` keeps passing against a head recorded beforehand. Exit codes:
`0` clean, `1` findings or a write refusal, `2` a tool error or a ledger `verify` would reject,
in which case nothing is written at all.

Omitting `--id` mints the next baseline identifier from the ledger's own sequence and says so on
stderr. See [references/LEDGER.md](skills/plugin-reviewer/references/LEDGER.md) for
why that is a stated exception to the ID-authority rule rather than a silent one.

See [references/LEDGER.md](skills/plugin-reviewer/references/LEDGER.md) for the
record model, and [assets/schemas/ledger.schema.json](skills/plugin-reviewer/assets/schemas/ledger.schema.json)
for the contract the validator enforces.

Run the validator's own test suite with:

```text
python -m unittest discover -s dashboard/tests -v
```

## Compatibility

The canonical Skill targets clients compatible with the open Agent Skills format. The repository includes native plugin manifests for Codex and Claude Code plus a single-directory archive suitable for portable Skill import. Client-specific behavioral support should be claimed only after structural, explicit-trigger, implicit-trigger, negative-trigger, and resource-resolution tests in that client.

Codex version 0.1.1 runtime acceptance results are documented in the
[Codex runtime validation record](docs/validation/codex-runtime-validation-0.1.1.md).

## License

This project is available under the [MIT License](LICENSE).

Privacy, terms, support, and security information are available in [PRIVACY.md](PRIVACY.md), [TERMS.md](TERMS.md), [SUPPORT.md](SUPPORT.md), and [SECURITY.md](SECURITY.md).

## Evaluations

The [evaluation suite](evals/README.md) is kept outside the Skill bundle so hidden expectations do not leak into normal model context. It covers activation, output quality, incomplete material, evidence, prompt injection, authorization, scope, rollback, portability, and model/reasoning-effort selection by task category.

Validate it with:

```text
python evals/scripts/eval_suite.py validate
python -m unittest discover -s evals/tests -v
```

Behavioral campaigns run each case in a fresh, read-only session and record results as JSONL. A configuration must cover every case in a category, meet the repetition and quality thresholds, and have zero critical failures. The summarizer then selects the lowest-ranked eligible configuration independently for each task category.
