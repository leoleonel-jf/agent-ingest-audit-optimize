# Agent Ingest, Audit, and Optimize

A portable Agent Skill that ingests external material, audits recommendations against current evidence, and turns supported findings into scoped, reversible improvements for AI agent ecosystems.

## Status

The repository contains the canonical English Skill produced by `PROP-2026-005` and its portable regression suite from `PROP-2026-006`. Product packaging, release workflows, and marketplace publication are intentionally separate follow-up proposals.

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

## Compatibility

The canonical Skill targets clients compatible with the open Agent Skills format. Client-specific support should be claimed only after structural, explicit-trigger, implicit-trigger, negative-trigger, and resource-resolution tests in that client.

No license has been selected yet.

## Evaluations

The [evaluation suite](evals/README.md) is kept outside the Skill bundle so hidden expectations do not leak into normal model context. It covers activation, output quality, incomplete material, evidence, prompt injection, authorization, scope, rollback, portability, and model/reasoning-effort selection by task category.

Validate it with:

```text
python evals/scripts/eval_suite.py validate
python -m unittest discover -s evals/tests -v
```

Behavioral campaigns run each case in a fresh, read-only session and record results as JSONL. A configuration must cover every case in a category, meet the repetition and quality thresholds, and have zero critical failures. The summarizer then selects the lowest-ranked eligible configuration independently for each task category.
