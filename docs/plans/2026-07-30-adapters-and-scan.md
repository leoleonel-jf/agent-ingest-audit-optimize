# Adapters and `scan` (0.2.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `dashboard.py` into modules without changing a line of behaviour, then build the adapter format, the three client adapters, and a read-only `scan` on top of the anchor and path-safety layer 0.2.3 shipped. Release 0.2.5.

**Architecture:** `assets/scripts/dashboard.py` stays the entry point and becomes CLI wiring plus re-exports. Everything else moves into `assets/scripts/ledgerlib/`. Two new modules join it: `adapters.py` (load, validate, resolve anchor roots, select a client) and `scan.py` (probe, digest, parse, redact, emit). `scan` writes nothing but stdout.

**Tech Stack:** Python 3.10+, standard library only. `unittest`. `tomllib` is used when present (3.11+) and degraded around when absent.

**Spec:** `docs/specs/2026-07-30-adapters-and-scan.md`
**Design spec sections implemented:** §9 in full, §7.5 (`baselines[]` production), §13.6 (enforcement at a real caller), §14 (degradation).

## Global Constraints

- No third-party dependency. Standard library only.
- Tests are `unittest`, discovered with `python -m unittest discover -s <dir>/tests`. No pytest.
- `scan` is read-only. It opens files, hashes them, parses two formats. It never writes a file, never creates a directory, and never executes anything a configuration file names.
- No anchor root ships in code. Roots come from adapter data and the environment, and every one of them is resolved before use.
- Every path a probe yields is re-checked with `resolve_anchored` before it is opened. Glob expansion is not trusted.
- A sensitive value never enters an item's attributes, not even briefly. Redaction happens at the point the value is read, not on the way out.
- Every finding message interpolating adapter or file content uses `!r`.
- Every new schema rule needs a matching runtime check, and an agreement test that fails in **both** directions.
- **Every task ends in an ablation step.** Delete the code the task added, run the suite, name the test that fails, restore. A test that passes with its target deleted guards nothing. Report the verbatim output.
- `.claude-plugin/plugin.json` → `version` is the single source of truth. Target `0.2.5`. Tags lightweight.
- This repository's own ledger is untracked and must never be staged.

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `.../assets/scripts/dashboard.py` | CLI wiring, `main`, re-exports | Modify |
| `.../assets/scripts/ledgerlib/__init__.py` | Package marker, nothing else | Create |
| `.../assets/scripts/ledgerlib/errors.py` | `LedgerError`, `PathSafetyError`, `PATH_SAFETY_REASONS` | Create |
| `.../assets/scripts/ledgerlib/constants.py` | Schema constants, regexes, closed enums | Create |
| `.../assets/scripts/ledgerlib/paths.py` | `load_json`, `file_digest`, anchoring, resolution, `check_glob` | Create |
| `.../assets/scripts/ledgerlib/validate.py` | Every `validate_*`, `validate_collection` | Create |
| `.../assets/scripts/ledgerlib/verify.py` | `verify` | Create |
| `.../assets/scripts/ledgerlib/adapters.py` | Adapter load, validation, anchor roots, client selection | Create |
| `.../assets/scripts/ledgerlib/scan.py` | Probing, digests, parsing, redaction, entry assembly | Create |
| `.../assets/schemas/adapter.schema.json` | The adapter format | Create |
| `.../assets/adapters/claude-code.json`, `codex.json`, `generic.json` | The three adapters | Create |
| `.../references/LEDGER.md` | Document `scan`, the adapter format, the unknown-client flow | Modify |
| `.../SKILL.md` | The unknown-client workflow | Modify |
| `dashboard/tests/test_dashboard.py` | Existing suite — **unmodified by Task 1** | Modify from Task 3 on |
| `dashboard/tests/test_adapters.py`, `test_scan.py` | New suites | Create |
| `packaging/tests/test_package_plugin.py` | The bundle ships `ledgerlib/` and `adapters/` | Modify |
| `README.md`, `PRIVACY.md`, `CHANGELOG.md`, version pins, `docs/releases/v0.2.5.md` | The release | Modify / Create |

---

### Task 1: The module split — provably inert

**Files:** Create `ledgerlib/` and its six modules; rewrite `dashboard.py`. **Do not touch `dashboard/tests/test_dashboard.py`.**

**Interfaces:**
- Produces: `dashboard.py` re-exporting every public name it exports today. Tasks 3 and later import from `ledgerlib.*` directly.

- [ ] **Step 1: Record the surface before touching anything**

Capture the names the current module exposes and the suite's current result:

```bash
python -c "import importlib.util,pathlib,json; s=pathlib.Path('skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py'); m=importlib.util.module_from_spec(importlib.util.spec_from_file_location('d',s)); importlib.util.spec_from_file_location('d',s).loader.exec_module(m); print(json.dumps(sorted(n for n in dir(m) if not n.startswith('__'))))"
python -m unittest discover -s dashboard/tests
```

Keep both outputs. They are the acceptance evidence for this task.

- [ ] **Step 2: Move code, do not rewrite it**

Cut and paste. No renames, no signature changes, no "while I am here" cleanups — a behavioural change hidden in a 1,200-line move is the one thing this task must not produce. Module boundaries are in the spec's §3.1 table.

Import direction is strictly one-way, and a cycle means a boundary is wrong:

```text
errors  <-  constants  <-  paths  <-  validate  <-  verify
                                  \-  adapters  <-  scan
```

- [ ] **Step 3: Make `dashboard.py` importable as a loose file**

The suite loads the script by path through `importlib.util`, which does **not** put the script's directory on `sys.path`. Before importing `ledgerlib`:

```python
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
```

Guarded against duplicate insertion, because the suite loads the module more than once in a process. Then re-export every name from Step 1's list, explicitly — `from ledgerlib.paths import anchor_path, check_glob, ...` — not a star import. A star import silently stops re-exporting a name the day someone adds an `__all__`.

- [ ] **Step 4: Run the suite with the test file unmodified**

```bash
python -m unittest discover -s dashboard/tests -v
python -m unittest discover -s packaging/tests -v
python -m unittest discover -s evals/tests -v
```

Re-run the Step 1 name dump and diff it against the saved output. **Zero differences.** A missing name is a broken re-export; an added name is a leaked import (`from pathlib import Path` re-exporting `Path` is expected — record which additions are imports and keep the list stable).

- [ ] **Step 5: Ablate**

Delete the `sys.path` insertion from `dashboard.py`. Run `python -m unittest discover -s dashboard/tests`. The suite must fail with `ModuleNotFoundError: No module named 'ledgerlib'`. Restore. Report the verbatim failure — this is the one guard that keeps the bundle runnable as a loose script.

- [ ] **Step 6: Confirm the script still runs as a script**

```bash
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify --help
```

Both entry paths matter: `python dashboard.py` and import-by-path. Verify both.

---

### Task 2: The bundle ships its modules

**Files:** `packaging/scripts/package_plugin.py` if it enumerates files; `packaging/tests/test_package_plugin.py`.

A zip carrying `dashboard.py` without `ledgerlib/` installs cleanly and fails on first use. That failure is invisible to every test that runs from the repository.

- [ ] **Step 1: Write the failing test**

In `packaging/tests/test_package_plugin.py`, build both archives and assert each contains `ledgerlib/__init__.py`, `ledgerlib/scan.py`, and — after Task 5 — `assets/adapters/generic.json`. Assert on the archive's own namelist, not the source tree.

Then the stronger test: extract the plugin zip to a temporary directory and run its `dashboard.py verify` against a known-good ledger fixture as a subprocess, asserting exit `0`. That is the only test that proves the bundle is *runnable* rather than merely *complete*.

- [ ] **Step 2: Run it, confirm it fails** if the packager filters by extension or enumerates names.

- [ ] **Step 3: Fix the packager** if needed. Prefer including the directory tree over listing files; a list is a thing to forget to update.

- [ ] **Step 4: Run the suite.**

- [ ] **Step 5: Ablate**

Make the packager skip `ledgerlib/`. The extract-and-run test must fail. Restore, report verbatim.

---

### Task 3: `adapter.schema.json` and the loader

**Files:** Create `assets/schemas/adapter.schema.json`; create `ledgerlib/adapters.py`; create `dashboard/tests/test_adapters.py`.

**Interfaces:**
- Produces: `load_adapter(path: Path) -> dict` — reads, validates, raises `LedgerError` with a finding-shaped message on the first failure; `validate_adapter(data: dict, *, source: str) -> list[str]` — returns findings, following the shape of `validate_ledger`.

- [ ] **Step 1: Write the failing tests**

One test per rule in the spec's §3.2 field table, each asserting the specific finding, not merely that some finding appeared:

`adapter_version` missing / non-integer / zero; `client` missing / empty / uppercase / containing a space; `expires_on` missing / not `YYYY-MM-DD`; `anchors` not an object / an anchor name without `$` / a candidate list that is empty / a candidate that is not a string; `probes` not an array / a probe that is not an object; a probe with neither `glob` nor `path`; a probe with **both**; a probe whose `kind` is outside the closed enum; `parse` outside `{json, toml}`; `parse` given with `glob` instead of `path`; `pointer` given without `parse`; `pointer` not starting with `/`; `sensitive_key_patterns` missing / not an array / containing a non-string; `scope` present but empty.

Two more that are the point of the whole task:

- a probe whose `glob` contains `..` is refused **at load**, and the message names `check_glob`'s reason;
- a probe whose `path` is absolute is refused at load.

And the agreement test, failing in both directions: the set of `kind` values the adapter schema accepts equals `constants.BASELINE_ITEM_KINDS`. Adding a kind to one file and not the other must fail, in either order. Import the enum in `adapters.py`; do not restate the ten strings.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation**

`validate_adapter` mirrors `validate_ledger`: collect findings, never raise on content. `load_adapter` raises `LedgerError` when `validate_adapter` returns findings, joining them, because a caller with a broken adapter has nothing to proceed with.

Validate the JSON Schema file and the runtime validator against each other in the same test module — the bundle has no JSON Schema library, so the `.json` file is documentation for humans and tools, and the runtime check is what actually runs. They drift the moment nothing compares them.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Delete the `check_glob` call from the loader. Name the test that fails. Restore. Then delete one field rule at random from `validate_adapter` and confirm its named test fails. Report both verbatim.

---

### Task 4: Anchor roots — `$env:`, `~`, first that exists

**Files:** `ledgerlib/adapters.py`; `dashboard/tests/test_adapters.py`.

**Interfaces:**
- Produces: `resolve_anchor_roots(adapter: dict, *, project: Path, environ: Mapping[str, str]) -> tuple[dict[str, Path], list[str]]` — the resolved roots and the names of anchors that resolved to nothing. `environ` is a parameter, not `os.environ` read inside, so tests do not mutate process state.

- [ ] **Step 1: Write the failing tests**

- `$env:CLAUDE_CONFIG_DIR` set to an existing directory wins over the `~` default that also exists;
- the same variable set to a **non-existent** directory falls through to the next candidate;
- the same variable set to an empty string is treated as unset;
- `~/x` expands against the home directory;
- `$PROJECT` with candidate `"."` resolves to the `project` argument, not to the process working directory;
- no candidate exists → the anchor is reported unresolved and is absent from the returned mapping;
- a candidate that exists but is a **file** does not resolve — an anchor root is a directory;
- the returned roots are absolute and resolved, so `anchor_path` and `resolve_anchored` receive what they expect.

The non-existent-`CLAUDE_CONFIG_DIR` case is the one a naive implementation gets wrong, and it is exactly the failure the research warns about: scanning the wrong tree and reporting it clean.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation.** Candidates are tried in order; `$env:NAME` reads `environ.get(NAME)` and skips a falsy value; a plain candidate is `Path(candidate).expanduser()`; `.` is resolved against `project`. A candidate qualifies only when `is_dir()` is true after resolution.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Make `$env:` candidates fall through unconditionally (ignore the variable). Name the test that fails. Restore, report verbatim.

---

### Task 5: The three adapters

**Files:** Create `assets/adapters/claude-code.json`, `codex.json`, `generic.json`; test in `dashboard/tests/test_adapters.py`.

**Source:** `docs/research/2026-07-30-client-configuration-paths.md` and nothing else. Do not add a path from memory. If the research does not list it, it does not ship.

- [ ] **Step 1: Write the failing tests**

- every bundled adapter loads and validates — parametrised over the directory contents, so a fourth adapter added later is covered without editing the test;
- every bundled adapter's `expires_on` equals the research document's expiry, `2026-10-28`, asserted by reading the date out of the research document rather than hardcoding it in the test — one place to change when the research is refreshed;
- `generic.json` has an empty `probes` array;
- `claude-code.json` probes **no** path whose final component is `AGENTS.md` (research finding 1);
- `claude-code.json`'s `$USER_CONFIG` candidates begin with `$env:CLAUDE_CONFIG_DIR`; `codex.json`'s with `$env:CODEX_HOME`;
- `codex.json` probes both `~/.agents/skills` and the skills directory under the configuration home (research §6: documented and undocumented, probe both);
- every adapter's `sensitive_key_patterns` is non-empty except `generic.json`, and every one of them contains `env` — the research names MCP `env` blocks as secret-bearing in both clients.

- [ ] **Step 2: Run, confirm they fail** (the files do not exist yet).

- [ ] **Step 3: Write the adapters.** Claude Code from research §2's table; Codex from §3's. Give each probe a `scope` of `user`, `project`, `managed`, or `system` matching the level column. Skip `~/.claude.json` for permissions, hooks, and `env` — research finding 4 says those keys are ignored there, and a probe would measure something with no effect. Probe it for MCP servers only, where it does have effect.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Add an `AGENTS.md` probe to `claude-code.json`. Name the test that fails. Remove it. Then change one `expires_on` and confirm the research-agreement test fails. Restore, report both verbatim.

---

### Task 6: Redaction

**Files:** `ledgerlib/scan.py`; create `dashboard/tests/test_scan.py`.

**Interfaces:**
- Produces: `redact(value, patterns: Sequence[str]) -> object` — a copy of the value with matched keys' values replaced by `{"redacted": True, "digest": "sha256:…"}`.

This task comes before probing so that nothing can read a value into an item before redaction exists.

- [ ] **Step 1: Write the failing tests**

- a key matching `*token*` has its value replaced by a redaction marker;
- matching is **case-insensitive**: `API_TOKEN` matches `*token*`;
- the literal pattern `env` matches the key `env` exactly and does not match `environment`;
- redaction **recurses**: a secret three objects deep is redacted;
- recursion **stops at the match**: given `{"env": {"A": {"B": "s"}}}`, the output contains one marker and no trace of `A` or `B`;
- non-string values redact too — a number, a list, and an object each become a marker;
- the digest is stable for equal values and differs for different ones, computed over canonical JSON (`sort_keys=True`, `separators=(",", ":")`, UTF-8);
- a non-matching structure passes through **unchanged**, compared by equality;
- the plaintext appears nowhere in `json.dumps` of the result — assert on the serialised output, because that is what leaves the process.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation.** `fnmatch.fnmatchcase` against the lowercased key and lowercased pattern. On a match, do not descend.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Remove the recursion (redact only top-level keys). The nested test must fail. Restore. Then make redaction return the value unchanged for non-string types; the number/list/object test must fail. Restore, report both verbatim.

---

### Task 7: Probing — globs, digests, `not_present`, and the second safety check

**Files:** `ledgerlib/scan.py`; `dashboard/tests/test_scan.py`.

**Interfaces:**
- Produces: `run_probe(probe: dict, roots: dict[str, Path], patterns) -> list[dict]` — the baseline items one probe yields. Always at least one item.

- [ ] **Step 1: Write the failing tests**

Build a temporary tree and drive the real filesystem; mock nothing that can be built.

- a `path` probe on an existing file yields one `present` item with a `sha256:` digest and the anchored form in `anchor`;
- a `path` probe on a missing file yields exactly one item, `state: "not_present"`, `digest: null`;
- a `glob` probe matching three files yields three items, ordered deterministically (sorted by anchored path — an unordered baseline diffs against itself);
- a `glob` probe matching nothing yields exactly one `not_present` item, and the item's `name` identifies the probe so the baseline says *what* was absent;
- a probe under an **unresolved** anchor yields one `not_present` item and does not raise;
- a directory match is `present` with a `null` digest and a reason in `attributes`;
- an unreadable file is `present`, `null` digest, reason in `attributes` — skip on Windows if the permission cannot be made to stick, and say so in the skip message;
- **the escape test:** a symlink inside `$USER_CONFIG/skills/` pointing at a directory outside the anchor, with a matching file behind it. The item is `not_present`, its `attributes` carry the `PathSafetyError` reason, **and the other probes in the same scan still produce their items.** Skip on a platform that cannot create the link, naming the reason.

That last test is the one that justifies the task. `check_glob` ran at load time and says nothing about what the filesystem holds now.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation**

Expand the glob under the resolved root with `Path.glob`. For every result — expanded or literal — call `resolve_anchored` on the anchored form before opening it, and catch `PathSafetyError` per item. Digest with the existing `file_digest`.

Reuse `anchor_path` for the stored form. Do not build it with string concatenation; the longest-anchor rule is already implemented once.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Delete the `resolve_anchored` call and open the expanded path directly. The escape test must fail. Restore, report verbatim. Then delete the `not_present` branch for an empty glob; that test must fail. Restore.

---

### Task 8: Parsing — `json`, `toml`, `pointer`, and honest degradation

**Files:** `ledgerlib/scan.py`; `dashboard/tests/test_scan.py`.

- [ ] **Step 1: Write the failing tests**

- `parse: "json"` with `pointer: "/mcpServers"` over a file with three servers yields three items, one per key, `name` being the key;
- a `pointer` that does not resolve yields one `not_present` item, not an error;
- `pointer` omitted yields one item for the whole document;
- a malformed JSON file yields one `present` item with `attributes.parse_error` — a stable string, not the exception's text, which varies by interpreter version;
- values under a `sensitive_key_patterns` match in the parsed document are redacted (Task 6 wired through);
- `parse: "toml"` over a `config.toml` yields the same shapes;
- **degradation:** with `tomllib` unavailable — patch the module reference, do not require an old interpreter — a `toml` probe yields one `present` item with its digest and `attributes.parse_unavailable == "toml"`, and no parsed keys;
- an RFC 6901 escape (`~1` for `/`, `~0` for `~`) in a pointer resolves correctly.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation.** Import `tomllib` inside a `try`, binding `None` on failure, and branch on the binding — not on `sys.version_info`, which the test cannot control.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Make the missing-`tomllib` branch raise instead of degrading. The degradation test must fail. Restore. Then remove redaction from the parsed-document path and confirm the redaction-through-parse test fails. Restore, report both verbatim.

---

### Task 9: Client selection and the unknown-client flow

**Files:** `ledgerlib/adapters.py`; `dashboard/tests/test_adapters.py`.

**Interfaces:**
- Produces: `select_adapter(*, client: str | None, adapter: Path | None, user_config: Path | None, bundled: Path, environ, project) -> tuple[dict, list[str]]` — the chosen adapter and the notes explaining the choice.

- [ ] **Step 1: Write the failing tests**

- `--adapter FILE` wins over everything and is validated like any other;
- `--client claude-code` selects the bundled file; an unknown `--client` exits as a tool error naming the clients available, rather than silently falling back — an explicit wrong name is a typo, not an unknown client;
- with no `--client`, exactly one adapter whose `$USER_CONFIG` resolves is selected;
- with two resolving, `generic.json` is selected **and a note names both candidates**;
- with none resolving, `generic.json` is selected and a note says so;
- a user adapter at `<user-config>/agent-ingest-audit-optimize/adapters/local.json` whose `client` equals a bundled adapter's **wins**, and a note records the override with the file's path;
- an invalid user adapter is refused with the same findings as an invalid bundled one, and does **not** silently fall back to the bundled file — a broken override is a thing to fix, not to route around;
- `user_config` unset means the user-adapter directory is never read: assert with a directory that would match, proving it was not opened.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation.** Notes are plain strings; the caller prints them and the baseline records them.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Reverse the precedence so bundled beats user. Name the test that fails. Restore. Then make `user_config=None` default to the home directory; the never-read test must fail. Restore, report both verbatim.

---

### Task 10: `scan` — assembly, expiry, and the CLI

**Files:** `ledgerlib/scan.py`; `dashboard.py`; `dashboard/tests/test_scan.py`.

**Interfaces:**
- Produces: `scan(...) -> tuple[dict, list[str], int]` — the baseline entry, the findings, and the exit code; and the `scan` subcommand.

- [ ] **Step 1: Write the failing tests**

- the emitted entry has `id`, `captured_on` (today, injected as a parameter so the test is not time-dependent), `client`, `adapter_version`, `items`;
- **the entry validates:** place it into a minimal ledger, run `verify`, assert exit `0`. This is the acceptance criterion that ties the whole release to the schema 0.2.3 built;
- every item's `origin` is `pre-existing`;
- every item carries its probe's `scope` in `attributes`;
- `--id` missing → exit `2`; `--id NOPE` → exit `2` naming the pattern;
- an adapter past `expires_on` produces a **finding** and still emits a baseline, exit `1`;
- an adapter not past expiry produces none;
- selection notes appear in the findings stream, not in the entry's items;
- **`scan` writes nothing:** run it with the whole tree read-only, or with `Path.write_text`, `Path.open('w')`, `Path.mkdir`, and `open` in write modes patched to fail, and assert exit `0`. Prefer the patch: it works on every platform and names the violation.

- [ ] **Step 2: Run the tests to verify they fail.**

- [ ] **Step 3: Write the implementation.** Entry to stdout as JSON with `indent=2`; findings and notes to stderr. Exit codes match `verify`: `0` clean, `1` findings, `2` tool error.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Delete the expiry check. Name the test that fails. Restore. Then delete the `scan` subcommand's wiring from `main` while leaving `scan()` intact — the CLI test must fail. This one matters: a previous release shipped a feature whose wiring could be deleted without any test noticing, because every test called the inner function directly. Restore, report both verbatim.

- [ ] **Step 6: Run it against this machine**

```bash
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py scan --id BASE-2026-000
```

Read the output. Confirm by eye: no secret value anywhere, every path plausible, `not_present` where you expect it. Save it to `docs/validation/scan-dogfood-0.2.5.md` with the findings, what was wrong, and what was right. A command whose first real run happens after the release is not validated.

---

### Task 11: Documentation

**Files:** `references/LEDGER.md`, `SKILL.md`, `README.md`, `PRIVACY.md`; tests in `dashboard/tests/test_dashboard.py`.

- [ ] **Step 1: Write the failing documentation tests**

Choose anchor phrases that pre-existing text **cannot** already satisfy — a documentation test that passes against a deleted paragraph has shipped here before. Assert on a phrase unique to the new content, and verify uniqueness by grepping the file before writing the test.

- `LEDGER.md` documents `scan`, its arguments, its exit codes, and that it is read-only;
- `LEDGER.md` documents the adapter format field by field, and an agreement test asserts every field name in `validate_adapter` appears in `LEDGER.md` and vice versa — failing in both directions;
- `LEDGER.md` documents the unknown-client flow and the `local.json` path;
- `PRIVACY.md` states what `scan` reads, that values under sensitive patterns are stored only as digests, and that nothing is transmitted;
- `SKILL.md` carries the workflow: how the agent asks for paths, that it writes `local.json` only after the user confirms, and that it never invents a path.

- [ ] **Step 2: Run, confirm they fail.**

- [ ] **Step 3: Write the documentation.**

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Ablate**

Delete each documented paragraph in turn and confirm its own test fails. A test that survives its paragraph's deletion has found the phrase elsewhere: change the phrase, not the test's expectation. Report verbatim.

---

### Task 12: Release 0.2.5

**Files:** `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, `CHANGELOG.md`, `docs/releases/v0.2.5.md`, `dist/`.

- [ ] **Step 1: Full suite, all three directories, green.**

- [ ] **Step 2: This repository's own ledger still exits `0`.**

- [ ] **Step 3: Bump the version in all three pins.** The version-consistency test is the guard; run it.

- [ ] **Step 4: Write `CHANGELOG.md` and `docs/releases/v0.2.5.md`.** House style: what changed and *why it was wrong before*, not a feature list. Name the research document as the adapters' source and its expiry as their expiry.

- [ ] **Step 5: Build the archives, record the checksums.** `test_release_document_checksums_match_a_real_build` must go from skipped to passing once the release document exists.

- [ ] **Step 6: Merge, tag `v0.2.5`, publish.**

- [ ] **Step 7: Verify the published bundle installs and runs** — extract the published zip somewhere clean and run `scan --help` and `verify` against a fixture.

---

## Delegation

Per `docs/specs/2026-07-29-ledger-and-dashboard-design.md` §19 and this repository's own rule: delegate each task to a subagent, one task per agent, and require the verbatim ablation output in the report. Do **not** parallelise Task 1 with anything — it moves every line of code in the project, and a second writer against the same file is a merge conflict with extra steps.

Tasks 3 and 4 may run in parallel with 6. Tasks 7 and 8 are sequential on 6. Task 10 is sequential on everything. Task 12 is a single-writer sequence — backup, apply, validate, record — and stays in one context.
