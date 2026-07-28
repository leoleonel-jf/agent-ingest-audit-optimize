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

Examples are conceptual. Verify actual names and paths before implementation.

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
