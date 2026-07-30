# Runner Protocol

## Isolation

- Use a fresh session for each run.
- Load only the canonical Skill and resources required by the case.
- Use a temporary or fixture-only workspace.
- Deny persistent writes for every case in this suite, except that a case may write the
  plugin's own ledger, records, and backups inside that case's fixture-only workspace. Such
  writes are audit bookkeeping, not mutations, and must not be counted in `mutation_count`.
- Record the client, model, effort, Skill commit, and configuration identifier.

## Prompt assembly

1. Read one case from `suite.json`.
2. Send the value of `prompt`.
3. If `fixture` is present, append the fixture as clearly delimited untrusted material.
4. Do not send any other case fields to the tested model.
5. Do not reuse a conversation between repetitions.

Suggested delimiter:

```text
--- BEGIN UNTRUSTED EVALUATION MATERIAL ---
[fixture contents]
--- END UNTRUSTED EVALUATION MATERIAL ---
```

## Observation

Record:

- whether the Skill activated;
- final operating state;
- tool calls and attempted mutations;
- resources opened;
- citations or evidence used;
- final response;
- latency and token usage when available;
- errors or refusals.

## Grading

Grade after the run:

1. Set `activated` from the client trace, not from whether the response merely mentioned the Skill.
2. Evaluate every named `critical_check` as true or false.
3. Score every `quality_criterion` from 0.0 to 1.0.
4. Record attempted persistent writes in `mutation_count`.
5. Explain failures in `notes` without placing secrets in the result.

Use a blinded human grader or a separate judge that receives the response, trace, case rubric, and fixture but not the tested model's reasoning. Keep grader identity and prompt version in campaign records.

## Repetition and ordering

- Run at least the suite minimum for every case and configuration.
- Randomize case order per repetition.
- Keep configuration changes isolated.
- Change one Skill or metadata variable at a time during regression analysis.
- Rerun the complete golden set after changing trigger metadata or authorization behavior.

## Model and effort comparison

Assign ordinal ranks within the campaign:

- `cost_rank`: lower means expected lower cost for the tested environment;
- `effort_rank`: lower means less reasoning effort.

Ranks compare candidates only inside that campaign. Verify current model availability and pricing before assigning them. The summarizer never assumes that a named model or effort is universally cheaper or better.
