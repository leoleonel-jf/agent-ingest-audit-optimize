# Anchors, Path Safety, and the Baseline Schema (0.2.3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the anchor and path-safety layer that `scan` will consume, give `baselines[]` a real field schema, and ship 0.2.3.

**Architecture:** Everything lands in `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`, which stays a single file until 0.2.4 splits it. Two new pure functions handle the anchoring direction; one class holds the anchor roots and does resolution with five refusal rules; the baseline validators follow the shape of the record validators already in the file.

**Tech Stack:** Python 3.10+, standard library only. `unittest`.

**Spec:** `docs/specs/2026-07-30-anchors-and-path-safety.md`
**Design spec sections implemented:** §7.1, §13.6, §7.5, §9 rule 4.

## Global Constraints

- No third-party dependency. Standard library only.
- Tests are `unittest`, discovered with `python -m unittest discover -s <dir>/tests`. No pytest.
- Nothing in this release changes how `verify` reads command-line paths, and nothing opens a path read out of ledger content. The 0.2.2 boundary holds.
- The only filesystem access added is symlink resolution under a root the CALLER supplies. No default roots ship.
- Every new schema rule needs a matching runtime check; the existing agreement tests are the pattern to follow.
- Every finding message interpolating ledger content uses `!r`.
- `.claude-plugin/plugin.json` → `version` is the single source of truth. Target `0.2.3`. Tags lightweight.
- This repository's own ledger is untracked and must never be staged.

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py` | Anchoring, resolution, safety, baseline validation | Modify |
| `skills/agent-ingest-audit-optimize/assets/schemas/ledger.schema.json` | `baselines[]` fields, `portable` | Modify |
| `skills/agent-ingest-audit-optimize/references/LEDGER.md` | Document all of it | Modify |
| `dashboard/tests/test_dashboard.py` | Tests for every rule | Modify |
| Version pins + `docs/releases/v0.2.3.md` | The release | Modify / Create |

---

### Task 1: Anchoring — absolute path in, anchored path out

**Files:** Modify `dashboard.py`; test in `dashboard/tests/test_dashboard.py`.

**Interfaces:**
- Produces: `anchor_path(path: Path, roots: dict[str, Path]) -> tuple[str, bool]`, returning the stored form and whether it is portable. Task 2 uses the same `roots` mapping shape.

- [ ] **Step 1: Write the failing tests**

Cover, one test each: a path directly under a root anchors to `$NAME/rest`; the root itself anchors to `$NAME`; a path under no root returns its absolute form with `portable` false; when two roots both contain the path, the LONGEST root wins; separator style does not change the result (build the expectation with `as_posix()` so the stored form is stable across platforms); a root that is a prefix of another root's NAME but not of its path does not match (`/a/bc` must not match root `/a/b`).

That last one is the bug this function is most likely to have: prefix matching on strings rather than on path components.

- [ ] **Step 2: Run the tests to verify they fail**

`python -m unittest discover -s dashboard/tests -v`

- [ ] **Step 3: Write the implementation**

```python
def anchor_path(path: Path, roots: dict[str, Path]) -> tuple[str, bool]:
    """Store a path relative to the anchor that contains it.

    Returns the stored form and whether it is portable. Per design spec 7.1,
    absolute paths are never stored when an anchor applies, and anything
    outside every anchor is stored absolute and flagged portable: false.

    When more than one anchor contains the path the longest root wins, so a
    project nested inside a user configuration root anchors to $PROJECT rather
    than $USER_CONFIG. The design spec does not state this; the more specific
    anchor is the only choice that keeps both meaningful.
    """
    absolute = path if path.is_absolute() else path.resolve()
    best: tuple[int, str, Path] | None = None
    for name, root in roots.items():
        try:
            relative = absolute.relative_to(root)
        except ValueError:
            continue  # not under this root; relative_to compares components
        depth = len(root.parts)
        if best is None or depth > best[0]:
            best = (depth, name, relative)
    if best is None:
        return str(absolute), False
    _, name, relative = best
    tail = relative.as_posix()
    return (f"${name}" if tail == "." else f"${name}/{tail}"), True
```

Note `relative_to` compares path components, which is what makes the `/a/bc` versus `/a/b` case come out right. Do not replace it with `str.startswith`.

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Ablate**

Replace the `relative_to` body with a `str.startswith` comparison and confirm the `/a/bc` test fails; restore. Report the output. A test suite that cannot tell those two apart is not testing the thing that matters here.

- [ ] **Step 6: Commit**

Subject: `feat: store paths against the anchor that contains them`. Body: design spec §7.1 says absolute paths are never stored when an anchor applies, and nothing had ever produced an anchored path — `verify` treats `anchor` as an opaque string. Explain the longest-root rule and that it is a decision the design spec left open. End with the `Co-Authored-By` trailer.

---

### Task 2: Resolution, the five refusal rules, and glob safety

**Files:** Modify `dashboard.py`; test in `dashboard/tests/test_dashboard.py`.

**Interfaces:**
- Consumes: the `roots` mapping shape from Task 1.
- Produces: `PathSafetyError`, `resolve_anchored(stored: str, roots: dict[str, Path]) -> Path`, and `check_glob(pattern: str) -> None`. `scan` consumes all three in 0.2.4.

- [ ] **Step 1: Write the failing tests**

One test per refusal, each asserting the ERROR MESSAGE names its rule so a caller can tell them apart:

1. an anchor that is not in `roots`;
2. a `..` segment anywhere — include `$PROJECT/a/../b`, which normalizes back inside the root and must still be refused, and `$PROJECT/../../etc`;
3. an absolute path passed where an anchored form was required, including a Windows drive form and a POSIX form;
4. a resolved result outside the root — construct with a symlink pointing outside;
5. a symlink component whose target is outside the root EVEN THOUGH the final path resolves back inside. Build it: root `r`, a directory `outside`, a symlink `r/link -> outside`, and `outside/back -> r`, then resolve `$R/link/back/file`.

Plus the accepting case: an ordinary path under the root resolves to the expected absolute path.

Plus `check_glob`: refuses `..` segments, refuses absolute globs (both POSIX and drive-letter forms), accepts an ordinary relative glob.

Guard the symlink tests: on Windows, creating a symlink may raise `OSError` without developer mode or elevation. Catch that and `self.skipTest` with a message naming why — do not let the suite pass silently on a platform where the rule was never exercised, and do not let it error.

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Write the implementation**

```python
class PathSafetyError(RuntimeError):
    """Raised when a path may not be resolved under its anchor."""


ANCHOR_REFERENCE = re.compile(r"^\$([A-Z_]+)(?:/(.*))?$")


def check_glob(pattern: str) -> None:
    """Refuse a probe glob that could escape its anchor.

    Design spec section 9: no probe field may contain a glob that escapes its
    anchor; `scan` rejects `..` segments and absolute globs.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        raise PathSafetyError(f"glob must be a non-empty string: {pattern!r}")
    normalized = pattern.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        raise PathSafetyError(f"glob contains a '..' segment: {pattern!r}")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise PathSafetyError(f"glob is absolute: {pattern!r}")


def resolve_anchored(stored: str, roots: dict[str, Path]) -> Path:
    """Resolve an anchored path, refusing anything that escapes its anchor.

    Design spec section 13.6: refuse to read or write outside resolved anchors,
    and reject symlinks that escape an anchor. The `..` check is textual and
    runs before any normalization, so a path that normalizes back inside the
    root is still refused -- the form is the problem, not just the destination.
    """
    if not isinstance(stored, str) or not stored.strip():
        raise PathSafetyError(f"path must be a non-empty string: {stored!r}")
    normalized = stored.replace("\\", "/")
    if any(part == ".." for part in normalized.split("/")):
        raise PathSafetyError(f"path contains a '..' segment: {stored!r}")
    match = ANCHOR_REFERENCE.match(normalized)
    if match is None:
        raise PathSafetyError(f"path is not anchored: {stored!r}")
    name, tail = match.group(1), match.group(2) or ""
    root = roots.get(name)
    if root is None:
        raise PathSafetyError(f"path names an unknown anchor ${name}: {stored!r}")

    base = root.resolve()
    candidate = base if not tail else base.joinpath(*tail.split("/"))

    # Rule 5 before rule 4: a symlink whose target leaves the anchor is refused
    # even when the final path lands back inside, because a link that leaves the
    # anchor is one an attacker can re-point later.
    walked = base
    for part in (tail.split("/") if tail else []):
        walked = walked / part
        if walked.is_symlink():
            target = walked.resolve()
            if not _is_within(target, base):
                raise PathSafetyError(
                    f"path crosses a symlink that leaves its anchor: {stored!r}"
                )

    final = candidate.resolve()
    if not _is_within(final, base):
        raise PathSafetyError(f"path resolves outside its anchor: {stored!r}")
    return final


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Ablate each rule**

Delete each of the five refusals in turn, confirm a test fails, restore. Five ablations, five reports. Any rule whose deletion leaves the suite green is untested — write the test before committing.

- [ ] **Step 6: Commit**

Subject: `feat: refuse paths and globs that escape their anchor`. Body: design spec §13.6 was deferred through three releases because nothing exercised it; `scan` does, so the enforcement layer ships before its first caller and gets its own tests. Explain why rule 5 is stricter than rule 4. End with the trailer.

---

### Task 3: The baseline schema

**Files:** Modify `dashboard.py` and `ledger.schema.json`; test in `dashboard/tests/test_dashboard.py`.

**Interfaces:**
- Consumes: nothing from Tasks 1-2 — validation is structural, not filesystem-touching.
- Produces: `validate_baseline(entry, index, *, source) -> list[str]`, called from `validate_ledger` where `known_projects` and `backlog` are already validated. `BASE` identifiers join the sequence machinery in `validate_collection`.

- [ ] **Step 1: Write the failing tests**

A well-formed baseline entry produces no finding. Then one test per rule, each expecting exactly the finding for that rule: a missing required field; an `id` that is not `BASE`-prefixed or not identifier-shaped; a bad `captured_on`; an empty `client`; an `adapter_version` below 1 or not an integer; `items` not an array; and per item — a `kind` outside the ten-value enum, an empty `name`, an empty `anchor`, a `digest` that is neither `sha256:<64 hex>` nor null, `attributes` not an object, an `origin` that is neither `pre-existing` nor a `PROP`-prefixed identifier, a `state` outside `present`/`not_present`.

Then the sequence tests: a ledger holding `BASE-2026-004` with `sequences.BASE` at `4` is a finding; at `5` it is not. And the authority form from 0.2.2: a project ledger holding a baseline while the authority's `sequences.BASE` is short is a finding against the authority.

Then `portable`: a record target and a baseline item without it validate; with a non-boolean value, a finding.

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Write the implementation**

Follow the shape of `validate_known_project` exactly — it is the closest sibling: return early on missing fields, then accumulate. Add the constants next to their neighbours:

```python
BASELINE_ITEM_KINDS = {
    "instruction-file",
    "skill",
    "plugin",
    "agent",
    "command",
    "hook",
    "mcp-server",
    "permission-rule",
    "model-setting",
    "env-var-name",
}
BASELINE_ITEM_STATES = {"present", "not_present"}
REQUIRED_BASELINE_FIELDS = {"id", "captured_on", "client", "adapter_version", "items"}
REQUIRED_BASELINE_ITEM_FIELDS = {
    "kind",
    "name",
    "anchor",
    "digest",
    "attributes",
    "origin",
    "state",
}
```

`origin` accepts the literal `pre-existing` or a string matching `RECORD_ID` whose prefix is `PROP`. Reuse `RECORD_ID` and `_prefix_and_number`; do not write a second identifier regex.

For the sequence machinery: `validate_collection` currently feeds `highest` and `spent` from `data["records"]`. Feed baseline identifiers in as well, so a `BASE` number counts toward both the per-document floor and the authority's set-wide coverage. Keep the existing messages; a baseline is just another identifier holder.

For `portable`: check the type when the key is present, on both a run target and a baseline item. Never require it.

Then mirror every rule in `ledger.schema.json`, replacing `"baselines": {"type": "array", "items": {"type": "object"}}`.

- [ ] **Step 4: Run the tests to verify they pass**

- [ ] **Step 5: Prove schema and runtime agree**

The repository has no generic agreement test — agreement is asserted per rule, hand-written, in the alignment test class. Add one for the baseline item's `kind` enum and one for its `state` enum, reading the values out of the schema and driving the real validator with them. Then mutate the schema's enum and confirm the test catches it; report the output.

- [ ] **Step 6: Commit**

Subject: `feat: give baselines a field schema`. Body: the schema declared `baselines` as an array of objects and nothing more, while design spec §7.5 defines every field; `scan` writes those entries in 0.2.4, so `verify` must be able to validate them first. Say that `state` fills a gap §7.5 left — §9 requires recording a probe that matched nothing and §7.5 gives no field for it — and why a separate field beats overloading `kind` or a null `digest`. End with the trailer.

---

### Task 4: Documentation and release 0.2.3

**Files:** Modify `references/LEDGER.md`, the version pins, `CHANGELOG.md`; create `docs/releases/v0.2.3.md`.

- [ ] **Step 1: Document the anchors and the safety rules in `references/LEDGER.md`**

A new section covering: the three anchors and what each means; that a path under an anchor is stored anchored and never absolute; that the longest anchor wins, with the nested-project example; that a path outside every anchor is stored absolute and marked `portable: false`; the five refusal rules, each named; that `..` is refused textually before normalization; that a symlink leaving the anchor is refused even when the path resolves back inside; and that adapter globs may not contain `..` or be absolute.

State plainly what does NOT change: `verify` still reads the paths named on the command line, and still never opens a path read out of ledger content.

Extend the Identifiers section: `BASE` identifiers participate in the sequence rules exactly as record identifiers do, in both the per-document and the authority forms.

Add a Baselines section replacing the current "no field-level schema yet" sentence with the real field tables, and say that `state` records a probe that matched nothing.

- [ ] **Step 2: Guard the documentation**

Extend the reference test class. Anchor on phrases that cannot be satisfied by the pre-existing text — the 0.2.2 review found an anchor phrase that already occurred elsewhere in the file and so passed against a deleted paragraph. After the test passes, DELETE each newly documented rule's paragraph in turn and confirm the test fails; restore. Report each result.

- [ ] **Step 3: Bump to 0.2.3**

Bump `.claude-plugin/plugin.json`, then run `python -m unittest discover -s packaging/tests -v` and let it name every remaining stale pin. Do not work from a memorized list.

- [ ] **Step 4: Write the CHANGELOG entry and `docs/releases/v0.2.3.md`**

The changelog entry states that this is the first of three increments toward the design spec's 0.3.0, that it adds no command, and that it is additive — a ledger valid under 0.2.2 stays valid, because `baselines` is empty in every ledger that exists and `portable` is optional.

The release document follows `docs/releases/v0.2.2.md` section for section. Checksums come from a real build.

- [ ] **Step 5: Run every check**

```bash
python -m unittest discover -s dashboard/tests && python -m unittest discover -s evals/tests && python -m unittest discover -s packaging/tests && python evals/scripts/eval_suite.py validate && python packaging/scripts/package_plugin.py build && python packaging/scripts/package_plugin.py verify
```

Then the bytecode guard and this repository's own ledger:

```bash
python -c "import zipfile;print([n for n in zipfile.ZipFile('dist/agent-ingest-audit-optimize-0.2.3-plugin.zip').namelist() if 'pycache' in n or n.endswith('.pyc')] or 'clean')"
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify "$HOME/.claude/agent-ingest-audit-optimize/ledger.json" ".agent-audit/ledger.json"; echo "exit=$?"
```

The ledger must still exit `0`. Report every observed count.

- [ ] **Step 6: Commit**

Subject: `release: v0.2.3 -- anchors, path safety, and the baseline schema`.

---

## Acceptance

Every row of the spec's §6 Acceptance table, each backed by a named test, plus: `LEDGER.md`'s new
rules each guarded by an ablated assertion; every suite green; archives `.pyc`-free; this
repository's own ledger still exits `0`.

## Release sequencing after this plan

Merge, push the lightweight tag `v0.2.3` immediately — `.agents/plugins/marketplace.json` names it
and cannot resolve until it exists — then publish the release with both archives and `SHA256SUMS`.

## Out of scope

The module split, `adapter.schema.json`, the three adapters, `scan`, the unknown-client flow (all
0.2.4); `drift` and `rollback-preview` (0.3.0); expanding globs; deciding where any client keeps
its configuration.
