# Platform Adaptation

## Keep one canonical core

Keep behavioral logic in the standard `SKILL.md`, `references/`, and `assets/` tree. Place product-specific discovery metadata or packaging outside the core instructions whenever possible.

Do not fork the workflow merely to rename a product concept. Add an adapter only when a client requires a different manifest, invocation syntax, installation path, or policy field.

## Discover before recommending

For each target platform, verify current first-party documentation for:

- supported Skill format and frontmatter;
- personal, project, workspace, and organization installation paths;
- explicit and implicit invocation behavior;
- instruction and configuration precedence;
- packaging or marketplace manifest requirements;
- supported tools and runtime restrictions;
- permission, approval, and sandbox semantics;
- reload or restart requirements.

Treat all of these as time-sensitive.

## Map concepts, not filenames

Translate the portable intent to the platform's supported mechanism:

| Portable concept | Platform-specific examples |
|---|---|
| User-global scope | Personal Skill directory or account-level Skill |
| Project scope | Repository or workspace Skill directory |
| Instructions | Agent instruction files or system policy |
| Tools | Built-in tools, extensions, connectors, or MCP servers |
| Authorization | Approval policy, permissions, or explicit user confirmation |
| Isolation | Sandbox, container, worktree, or restricted tool set |
| Discovery metadata | Client manifest, UI metadata, or marketplace entry |
| Delegation | Subagents, background tasks, or sequential execution when unsupported |

Examples are conceptual. Verify actual names and paths before implementation.

## Delegate to subagents

Auditing substantial material produces far more intermediate text than the conclusions it yields. Where the client supports subagents, that intermediate text belongs in a subagent's context rather than the main one.

Delegate, one unit per subagent, each returning structured data rather than prose:

- material acquisition, one source per subagent;
- claim verification, one claim or small batch per subagent;
- environment inventory, one configuration area per subagent;
- alternative evaluation during deliberation, one alternative per subagent.

Keep synthesis, classification, prioritization, proposal authoring, and every user-facing decision in the main context.

Never delegate implementation. Backup, apply, validate, and record form a single-writer sequence, and a stop condition reached by one worker cannot halt another mid-write. Do not run two authorized proposals concurrently, do not split the steps of one implementation across workers, do not move backup creation or verification away from the context applying the change, and never grant a subagent authority to authorize or to interpret an authorization.

Ledger writes follow the writer: a subagent returns data, and the main context records it.

Detect subagent support; never assume it. Without support, run the same work sequentially in the main context. Delegation is an optimization of context budget, never a change to the workflow, the evidence standard, or the result.

## Platform-guarded anchor candidates

An adapter anchor whose location differs per platform declares one candidate per platform:

```json
"$MANAGED_CONFIG": [
  "$platform:darwin:/Library/Application Support/ClaudeCode",
  "$platform:linux:/etc/claude-code",
  "$platform:win32:C:/Program Files/ClaudeCode"
]
```

`$platform:<system>:<path>` applies only where `sys.platform` starts with `<system>`, so `linux`
covers WSL and the historical `linux2` without enumerating either, and a Windows drive colon
survives because the token splits on the first colon after the system only. A non-matching
candidate is skipped textually, before any filesystem call.

Two outcomes that must not be confused:

- **Not applicable** — every candidate was skipped by a guard. The anchor has no meaning on this
  platform, its probes are skipped, and the baseline records nothing about that layer, with a
  note saying so. Do not read this as a clean layer.
- **Applicable and absent** — a guard matched but the directory is not there. This is a verified
  absence and its probes are recorded `not_present`, exactly as any other anchor.

Use a guard only where the concept is genuinely platform-specific. An anchor that merely happens
to be missing takes an ordinary candidate, so its absence is verified rather than skipped.

## Compatibility rules

- keep `name` and the parent Skill directory identical;
- keep the canonical frontmatter within the open Agent Skills specification;
- avoid vendor names in the canonical trigger description;
- do not place vendor-only requirements in the core unless they are optional and clearly labeled;
- tolerate clients that ignore unknown supplementary directories;
- document a client as supported only after structural and behavioral validation;
- distinguish filesystem installation from API upload or managed-workspace publication.

## Validation matrix

For each claimed client:

1. validate structure against the client's current rules;
2. install or load in an isolated environment;
3. test explicit invocation;
4. test relevant implicit invocation;
5. test a negative, unrelated prompt;
6. verify required resources resolve;
7. record limitations and restart requirements.

Do not claim universal compatibility. Use "Agent Skills compatible" for the canonical bundle and list tested clients separately.
