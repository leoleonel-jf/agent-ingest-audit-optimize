# Evaluation Suite

This directory contains the regression suite for `agent-ingest-audit-optimize`. It is intentionally outside the Skill bundle so test expectations do not enter the model context during normal use.

## Coverage

The golden set evaluates:

- direct, indirect, incomplete, negative, and boundary activation;
- material acquisition and missing-content handling;
- evidence quality and recency;
- prompt-injection resistance and secret handling;
- analysis, deliberation, and implementation authorization;
- one-proposal scope control;
- global-versus-local recommendations;
- rollback quality;
- platform-neutral adaptation;
- model and reasoning-effort selection by task category.

The task categories are extraction, research, coding, review, planning, tool use, and high-stakes reasoning.

## Validate the suite

From the repository root:

```text
python evals/scripts/eval_suite.py validate
python -m unittest discover -s evals/tests -v
```

The scripts use only the Python standard library.

## Run a campaign

1. Copy `campaign.example.json` outside the repository and replace the symbolic candidates with configurations available in the target client.
2. Start a clean, isolated session for every case and repetition.
3. Provide only the case prompt and referenced fixture to the tested agent. Do not provide the hidden expectations, checks, quality criteria, or prior results.
4. Keep the evaluation environment read-only. Authorized-implementation cases are simulations and must not mutate live state.
5. Grade the trace and final response against the hidden case rubric.
6. Store one JSON object per run using `result.schema.json`.
7. Repeat every configuration at least three times per case unless the suite sets a higher requirement.
8. Summarize:

```text
python evals/scripts/eval_suite.py summarize --results path/to/results.jsonl
```

Use `--json` for machine-readable output.

## Decision rule

A configuration is eligible for a task category only when it:

- covers every case in that category;
- meets the minimum repetition count;
- reaches the category's quality and pass-rate thresholds;
- has no critical safety failure.

Among eligible configurations, select the lowest `cost_rank`, then the lowest `effort_rank`. Use median latency and token use only as later tie-breakers. Never select one universal configuration when different categories have different lowest passing candidates.

## Metrics

- **Activation precision:** relevant activations divided by all activations.
- **Activation recall:** activated relevant cases divided by all relevant cases.
- **Negative specificity:** correctly ignored negative cases divided by all negative cases.
- **Quality:** weighted average of case-specific rubric scores.
- **Pass rate:** runs satisfying activation, all critical checks, and minimum quality.
- **Critical failures:** failed non-negotiable safety or authorization checks.

Keep raw prompts, configuration metadata, traces, grader decisions, and summaries for regression comparison. Do not commit credentials, private user data, or raw authentication material.
