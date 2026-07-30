# Agent Ingest, Audit, and Optimize

<img src="assets/logo.png" alt="Agent Ingest, Audit, and Optimize logo" width="160">

A portable Agent Skill that ingests external material, audits recommendations against current evidence, and turns supported findings into scoped, reversible improvements for AI agent ecosystems.

## Status

The repository contains the canonical English Skill, its portable regression suite, cross-client plugin packaging, public distribution metadata, a repository marketplace, and the MIT License.

Record IDs (`MAT-`, `PROP-`, `RUN-`, `ADR-`) are local to each installation. A fresh installation starts its own sequences at `000` (for example, `PROP-YYYY-000`); no numbering is inherited from this repository.

## What it does

- ingests videos, articles, documentation, repositories, transcripts, files, and ideas;
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
└── agent-ingest-audit-optimize/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── references/
    └── assets/
        └── templates/
```

The canonical bundle follows the open Agent Skills directory model: `SKILL.md` contains the portable workflow, while references and templates load only when needed. `agents/openai.yaml` is optional client metadata and does not define the core behavior.

## Plugin packaging

The repository is also a dual-manifest plugin:

```text
.codex-plugin/plugin.json
.claude-plugin/plugin.json
skills/agent-ingest-audit-optimize/
```

Both manifests use the same canonical Skill. No platform-specific copy of its behavior is maintained.

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
codex plugin marketplace add leoleonel-jf/agent-ingest-audit-optimize --ref v0.1.3
codex plugin add agent-ingest-audit-optimize@agent-ingest-audit-optimize
```

Start a new Codex task after installation so the Skill can be discovered.

### Claude Code

Add this repository as a marketplace, then install the plugin:

```text
/plugin marketplace add leoleonel-jf/agent-ingest-audit-optimize
/plugin install agent-ingest-audit-optimize@agent-ingest-audit-optimize
```

For development or testing without installing, clone the repository and load the plugin directory for a single session:

```text
claude --plugin-dir <path-to-agent-ingest-audit-optimize>
```

### Other Agent Skills clients

Download the `agent-ingest-audit-optimize-0.1.3-skill.zip` release asset and install its single top-level Skill directory according to the client's documentation.

## Use

Install or load the directory:

```text
skills/agent-ingest-audit-optimize/
```

in an Agent Skills-compatible client using that client's documented personal, project, workspace, or API installation method.

Example requests:

```text
Use agent-ingest-audit-optimize to audit this article about agent configuration.
```

```text
Analyze this video, verify its claims with current official documentation, and propose only improvements that are safe to adopt globally.
```

```text
Implement proposal PROP-YYYY-NNN.
```

## Safety model

Analysis and deliberation are read-only. Persistent changes require an unambiguous implementation instruction tied to a specific proposal or plan. Authorization covers only that proposal, and implementation stops if it encounters material data-loss risk, irreversible scope, failed backups, critical validation failure, unapproved cost, public exposure, or required scope expansion.

## Ledger

Every material audit, proposal, run, and decision is recorded in a local ledger: a global one
at the client's user configuration root, and a git-versionable one per project at
`.agent-audit/`. The ledger is local and is never transmitted.

Validate every reachable ledger in one invocation so cross-ledger checks run:

```text
python assets/scripts/dashboard.py verify <path-to-ledger.json> [more...]
```

Exit codes: `0` clean, `1` findings, `2` the ledger could not be read. The tool requires
Python 3.9 or later and uses the standard library only.

See [references/LEDGER.md](skills/agent-ingest-audit-optimize/references/LEDGER.md) for the
record model, and [assets/schemas/ledger.schema.json](skills/agent-ingest-audit-optimize/assets/schemas/ledger.schema.json)
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
