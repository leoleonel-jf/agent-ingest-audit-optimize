# Operational Workflow

## 1. Triage

Determine:

- the user's objective and requested output;
- the operating state: analysis, deliberation, or implementation;
- the material type and accessibility;
- the target agent products and environments;
- the potential scope: session, project, workspace, user, organization, or fleet;
- whether current external research is required;
- whether any proposed action needs additional authority.

## 2. Acquire material

Use the best available representation without overstating completeness:

- for video, gather metadata, transcript or captions, description, and linked sources;
- for articles and documentation, identify publication and update dates;
- for repositories, inspect the relevant revision, release, issue, or pull request;
- for local files, preserve the source and record its path or stable identifier;
- for pasted text or ideas, distinguish the user's statements from cited facts.

Record what could not be accessed. Never reconstruct missing content as fact.

## 3. Build a claim inventory

Split the material into independently testable items:

- factual claims;
- configuration guidance;
- commands and code;
- architecture or workflow recommendations;
- product or model comparisons;
- security and permission advice;
- claimed benefits, costs, and limitations.

Preserve enough context to avoid changing the original meaning.

## 4. Verify

For each claim:

1. identify the relevant product, version, date, and environment;
2. find current first-party evidence whenever possible;
3. compare the source claim with that evidence;
4. label the result as supported, partly supported, contradicted, obsolete, unverifiable, or opinion;
5. explain any inference separately from sourced fact;
6. record source dates when recency affects the result.

If official sources disagree, describe the conflict and avoid false certainty.

## 5. Inspect the environment

When access exists, inspect in read-only mode before proposing changes:

- applicable instruction hierarchy;
- user, workspace, and project configuration;
- installed Skills, plugins, extensions, tools, and connectors;
- local overrides and duplicate names;
- model and effort settings;
- permission, sandbox, and approval policies;
- existing backups, records, tests, and uncommitted work.

Redact secrets and avoid commands that mutate state during analysis.

## 6. Classify and prioritize

Classify every recommendation using the vocabulary in `SKILL.md`.

Score when useful:

| Criterion | Question |
|---|---|
| Benefit | How much measurable value could this add? |
| Reach | How many relevant tasks or environments benefit? |
| Impact | How large is the behavioral or operational change? |
| Complexity | How difficult is adoption and maintenance? |
| Risk | What can fail, leak, regress, or surprise users? |
| Reversibility | Can the previous state be restored reliably? |
| Compatibility | Does it coexist with supported platforms and overrides? |
| Evidence | How current and authoritative is the support? |
| Priority | How soon should this be addressed? |

Do not turn rejected, obsolete, already implemented, or weakly evidenced findings into implementation proposals.

## 7. Propose

Create a proposal that defines:

- the problem or opportunity;
- the exact change and intended scope;
- affected components and explicit exclusions;
- evidence and alternatives;
- dependencies and compatibility;
- expected benefits and measurement;
- risks and mitigations;
- tests and success criteria;
- backup and rollback.

Keep proposals independently implementable. Present no more than three in one decision round unless the user asks for more.

## 8. Plan without changing state

For the selected proposal, specify:

- preconditions and current state;
- files, services, products, and users affected;
- exact sequence of reversible steps;
- backup and restore locations;
- configuration merge rules;
- test matrix and failure thresholds;
- stop conditions;
- unavoidable human or external actions.

Do not implement while the user is still choosing or refining the plan.

## 9. Implement one authorized proposal

After unambiguous authorization:

1. verify that the proposal and authorization still match;
2. check for state drift and unrelated work;
3. create and verify backups;
4. apply the smallest reversible change;
5. preserve unrelated configuration and avoid duplicate keys or identifiers;
6. validate after each risky boundary;
7. record commands, files, deviations, and outcomes;
8. stop if a stop condition from `SKILL.md` occurs.

Do not bundle another proposal into the run.

## 10. Validate

Test in proportion to scope:

- structural and syntax validation;
- discovery or loading in a fresh session when applicable;
- explicit invocation;
- implicit invocation;
- negative triggering on an unrelated task;
- representative existing and new projects;
- local override and duplicate-name behavior;
- representative task categories for model or effort changes;
- rollback feasibility.

Distinguish:

- **VALIDATED**: all critical criteria passed with direct evidence;
- **VALIDATED WITH CAVEATS**: safe and useful, but a named environment or fresh-session check remains;
- **NOT VALIDATED**: critical evidence is missing or a required test failed.

## 11. Close the run

Report:

- previous and final state;
- backups and recovery locations;
- created, changed, moved, or removed resources;
- executed tests and evidence;
- pending fresh-session or human checks;
- residual risks;
- exact rollback procedure;
- next proposal, if any, without implementing it.
