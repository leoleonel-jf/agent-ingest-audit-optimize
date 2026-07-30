# Packaging

This repository produces two distribution artifacts from one canonical Skill:

| Artifact | Contents | Intended use |
| --- | --- | --- |
| `agent-ingest-audit-optimize-<version>-plugin.zip` | Plugin manifests, shared `skills/` tree, logo, license, and public documentation | Plugin installation or local plugin validation |
| `agent-ingest-audit-optimize-<version>-skill.zip` | One top-level `agent-ingest-audit-optimize/` Skill directory, including the MIT license | Agent Skills clients and Claude API Skill upload |

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
- plugin archives contain only the manifests, public documentation, logo, license, and shared Skill;
- Skill archives contain exactly one top-level Skill directory;
- generated SHA-256 checksums match.

Platform-native validation can also be run from the repository root:

```text
python C:\Users\leole\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
claude plugin validate --strict .
```

The first path is a local Codex development-tool path and may differ on another machine.

## Version pins

`.claude-plugin/plugin.json` → `version` is the single source of truth for the plugin version.
Six other places restate it, and `packaging/tests/test_version_consistency.py` is the
authoritative list — it fails when any of them drifts, naming the file that did:

| Pin | Form |
| --- | --- |
| `.codex-plugin/plugin.json` → `version` | the version |
| `.claude-plugin/marketplace.json` → `plugins[0].version` | the version |
| `.agents/plugins/marketplace.json` → `plugins[0].source.ref` | `v` + the version |
| `README.md` → the `--ref` argument | `v` + the version |
| `README.md` → the Skill asset filename | contains the version |
| `docs/SUBMISSION.md` → the `**Version:**` line | the version |
| `CHANGELOG.md` → the first `## x.y.z` heading | the version |

Run it with the rest of the packaging suite:

```text
python -m unittest discover -s packaging/tests
```

A release that adds a new pin extends that test in the same commit. Do not maintain a
per-release checklist; the omission of `.agents/`, `README.md`, and `docs/SUBMISSION.md` from
the 0.2.0 checklist is what left the four stale pins that 0.2.1 corrected.

`.agents/plugins/marketplace.json` is the OpenAI Codex marketplace manifest
(<https://developers.openai.com/plugins/build/plugins>). Its `ref` is a git ref that does not
advance on its own, so it must name a tag that exists: bump it in the release commit, then push
the tag immediately after the merge.

Tags are lightweight from `v0.2.1` onward. Codex compares `git ls-remote` output against the
cloned commit, and for an annotated tag those differ, so an annotated tag makes the marketplace
re-clone on every auto-upgrade pass.

## Local use

- **Codex:** validate the repository as a plugin; publishing or installing it through a marketplace is a separate release decision.
- **Claude Code:** load the repository during development with `claude --plugin-dir <repository-path>`.
- **Claude API:** upload the generated `-skill.zip` using the Skills API.
- **Other Agent Skills clients:** install the canonical directory under `skills/` or use the generated Skill archive according to the client's documentation.

The repository marketplace and public release are maintained separately from generated archives. Building a package does not install or publish it.
