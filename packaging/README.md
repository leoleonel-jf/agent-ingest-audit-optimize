# Packaging

This repository produces two distribution artifacts from one canonical Skill:

| Artifact | Contents | Intended use |
| --- | --- | --- |
| `agent-ingest-audit-optimize-<version>-plugin.zip` | Codex and Claude plugin manifests, the shared `skills/` tree, and the root README | Plugin installation or local plugin validation |
| `agent-ingest-audit-optimize-<version>-skill.zip` | One top-level `agent-ingest-audit-optimize/` Skill directory | Agent Skills clients and Claude API Skill upload |

The plugin manifests are thin platform adapters. They do not duplicate or override the behavior in `skills/agent-ingest-audit-optimize/SKILL.md`.

## Build

Python 3.10 or newer is sufficient; the packager uses only the standard library.

```text
python packaging/scripts/package_plugin.py build
```

Generated artifacts and `SHA256SUMS` are written to `dist/`. The directory is intentionally ignored by Git because archives are release outputs, not source files.

Builds are deterministic: unchanged source files produce byte-identical archives and checksums.

## Verify

```text
python packaging/scripts/package_plugin.py verify
```

Verification checks:

- manifest names and versions agree;
- the canonical Skill name matches its directory;
- required files are present;
- symlinks and unsafe archive paths are rejected;
- plugin archives contain only the manifests, README, and shared Skill;
- Skill archives contain exactly one top-level Skill directory;
- generated SHA-256 checksums match.

Platform-native validation can also be run from the repository root:

```text
python C:\Users\leole\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
claude plugin validate --strict .
```

The first path is a local Codex development-tool path and may differ on another machine.

## Local use

- **Codex:** validate the repository as a plugin; publishing or installing it through a marketplace is a separate release decision.
- **Claude Code:** load the repository during development with `claude --plugin-dir <repository-path>`.
- **Claude API:** upload the generated `-skill.zip` using the Skills API.
- **Other Agent Skills clients:** install the canonical directory under `skills/` or use the generated Skill archive according to the client's documentation.

No marketplace entry, public release, global installation, or license declaration is created by this packaging workflow.
