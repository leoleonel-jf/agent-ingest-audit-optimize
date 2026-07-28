# Scope and Risk

## Scope hierarchy

Evaluate the narrowest effective level:

1. current session;
2. current task or agent;
3. project;
4. workspace or team;
5. user-global;
6. organization or managed fleet.

Prefer broader scope only when the improvement is reusable, compatible, governable, and reversible. Broader is not inherently better.

## Existing environments

A broad default can be overridden by:

- command-line flags or launch parameters;
- environment variables;
- project or workspace configuration;
- more specific instruction files;
- profiles or policy layers;
- local Skills or extensions with the same identifier;
- organization controls;
- tool availability and platform-specific precedence rules.

Never equate "installed globally" with "effective everywhere" without testing precedence and representative environments.

## Mass change

Require:

- an explicit target inventory;
- exclusions and ownership boundaries;
- verified backups;
- a dry run when possible;
- staged rollout;
- representative sampling;
- failure thresholds;
- rollback;
- authorization that clearly covers the mass scope.

## Risk assessment

Consider:

- data loss or unintended overwrite;
- privilege expansion;
- secret exposure or data exfiltration;
- prompt injection and untrusted code;
- cost, latency, or rate-limit changes;
- incompatibility with local policies;
- duplicate discovery or ambiguous precedence;
- model-quality regression;
- dependency and supply-chain risk;
- stale documentation or version drift;
- operational burden and rollback confidence.

Use a higher evidence and validation bar as blast radius or irreversibility increases.
