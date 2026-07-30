# Closing the Dogfood Findings (0.2.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five findings the 0.2.1 ledger dogfood produced, plus four minors carried from the same review, and ship 0.2.2.

**Architecture:** Four of the five findings become new checks in `assets/scripts/dashboard.py`. Three of them live in `validate_collection`, the cross-ledger pass that already correlates a verified set: a digest comparison against files the user named, a sequence check for the ID-authority ledger against every record in the set, and a backlog back-reference check that reuses the existing dangling-link suppression. The fourth is a one-line requirement in `validate_run`. The fifth finding is documentation. `references/LEDGER.md` is then brought into agreement with all of it.

**Tech Stack:** Python 3.10+, standard library only. `unittest`, discovered with `python -m unittest discover`.

**Spec:** `docs/specs/2026-07-30-close-dogfood-findings.md`
**Findings being closed:** `docs/validation/ledger-dogfood-0.2.1.md`

## Global Constraints

- No third-party dependency. Standard library only.
- Tests are `unittest`, discovered with `python -m unittest discover -s <dir>/tests`. No pytest.
- `verify` must never open a filesystem path read out of ledger content. Ledger content is attacker-influenced by design, and spec §13.6 (filesystem path safety) is deferred. Comparisons happen only against files the user named on the command line.
- Every finding message that interpolates ledger content uses `!r`, matching every existing check. A crafted value must not be able to emit raw escape sequences.
- Every new schema rule must have a matching runtime check, and the existing test asserting schema and runtime agree must keep passing.
- `.claude-plugin/plugin.json` → `version` is the single source of truth. Target version `0.2.2`. Tags are lightweight.
- Neither ledger is ever committed. This repository's own ledger is updated on disk, never staged.
- Do not edit any closed plan under `docs/plans/` other than this one.

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py` | The four new checks | Modify |
| `skills/agent-ingest-audit-optimize/assets/schemas/ledger.schema.json` | Structural rules that became enforceable | Modify |
| `skills/agent-ingest-audit-optimize/references/LEDGER.md` | Bring the contract into agreement with the code | Modify |
| `dashboard/tests/test_dashboard.py` | A test per new check, both directions | Modify |
| `packaging/tests/test_version_consistency.py` | Two carried minors | Modify |
| `packaging/tests/test_package_plugin.py` | The evaluation-case-count guard | Modify |
| `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json`, `README.md`, `docs/SUBMISSION.md`, `CHANGELOG.md` | 0.2.2 bump | Modify |
| `docs/releases/v0.2.2.md` | Release document | Create |
| `.agent-audit/ledger.json` | This repository's own RUN record, to satisfy the new rule (untracked) | Modify |

---

### Task 1: A digest pointer is checked against what it points at

Closes finding 1.

**Files:**
- Modify: `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`
- Test: `dashboard/tests/test_dashboard.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `file_digest(path: Path) -> str` and `_path_key(value: str) -> str`; `validate_collection` gains a keyword-only parameter `digests: dict[str, str] | None = None`. Tasks 2 and 3 add further checks to the same function and must not disturb this signature.

- [ ] **Step 1: Write the failing tests**

Add to `dashboard/tests/test_dashboard.py`, in the class that holds the other cross-ledger tests, matching its style for building temporary ledgers:

```python
    def test_stale_last_digest_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project.json"
            project.write_text(json.dumps(self.project_ledger()), encoding="utf-8")
            global_data = self.global_ledger()
            global_data["known_projects"] = [
                {
                    "project_root": str(root),
                    "ledger_path": str(project),
                    "last_seen": "2026-07-30",
                    "last_digest": "sha256:" + "0" * 64,
                    "status": "OK",
                }
            ]
            global_path = root / "global.json"
            global_path.write_text(json.dumps(global_data), encoding="utf-8")

            findings = dashboard.validate_collection(
                [
                    (str(global_path), json.loads(global_path.read_text(encoding="utf-8"))),
                    (str(project), json.loads(project.read_text(encoding="utf-8"))),
                ],
                digests={
                    dashboard._path_key(str(global_path)): dashboard.file_digest(global_path),
                    dashboard._path_key(str(project)): dashboard.file_digest(project),
                },
            )

            self.assertTrue(any("last_digest" in finding for finding in findings))

    def test_matching_last_digest_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project.json"
            project.write_text(json.dumps(self.project_ledger()), encoding="utf-8")
            global_data = self.global_ledger()
            global_data["known_projects"] = [
                {
                    "project_root": str(root),
                    "ledger_path": str(project),
                    "last_seen": "2026-07-30",
                    "last_digest": dashboard.file_digest(project),
                    "status": "OK",
                }
            ]
            global_path = root / "global.json"
            global_path.write_text(json.dumps(global_data), encoding="utf-8")

            findings = dashboard.validate_collection(
                [
                    (str(global_path), json.loads(global_path.read_text(encoding="utf-8"))),
                    (str(project), json.loads(project.read_text(encoding="utf-8"))),
                ],
                digests={
                    dashboard._path_key(str(global_path)): dashboard.file_digest(global_path),
                    dashboard._path_key(str(project)): dashboard.file_digest(project),
                },
            )

            self.assertFalse(any("last_digest" in finding for finding in findings))

    def test_digest_for_a_ledger_outside_the_set_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            global_data = self.global_ledger()
            global_data["known_projects"] = [
                {
                    "project_root": str(root),
                    "ledger_path": str(root / "absent.json"),
                    "last_seen": "2026-07-30",
                    "last_digest": "sha256:" + "0" * 64,
                    "status": "OK",
                }
            ]
            global_path = root / "global.json"
            global_path.write_text(json.dumps(global_data), encoding="utf-8")

            findings = dashboard.validate_collection(
                [(str(global_path), global_data)],
                digests={
                    dashboard._path_key(str(global_path)): dashboard.file_digest(global_path)
                },
            )

            self.assertFalse(any("last_digest" in finding for finding in findings))
```

If the test class has no `project_ledger()` / `global_ledger()` helpers, use whatever the existing cross-ledger tests use to build a minimal valid ledger, and keep the same approach. Do not invent a second helper style.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m unittest discover -s dashboard/tests -v
```

Expected: the three new tests error on `dashboard.file_digest` / `dashboard._path_key` not existing, or fail on the assertion. Every pre-existing test still passes.

- [ ] **Step 3: Write the implementation**

In `dashboard.py`, add `hashlib` and `os` to the imports, in alphabetical position among the existing standard-library imports.

Add these helpers next to `load_json`:

```python
def file_digest(path: Path) -> str:
    """Hash a ledger's final on-disk bytes.

    The digest recorded in `known_projects[].last_digest` describes the file as
    written, so it must be taken from the bytes on disk: a trailing newline or a
    line-ending difference changes the hash of an otherwise identical document.
    """
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _path_key(value: str) -> str:
    """Normalize a path for comparison without touching the filesystem.

    `ledger_path` is ledger content, and ledger content is attacker-influenced.
    This normalizes textually — never resolving, never opening — so comparing a
    ledger's stored path against the paths the user named cannot be steered into
    reading somewhere else.
    """
    return os.path.normcase(os.path.normpath(value))
```

Change `validate_collection`'s signature to:

```python
def validate_collection(
    documents: list[tuple[str, dict]],
    *,
    complete: bool = True,
    digests: dict[str, str] | None = None,
) -> list[str]:
```

Immediately before the `if len(authorities) > 1:` block at the end, add:

```python
    if digests:
        for source, data in documents:
            projects = data.get("known_projects") if isinstance(data, dict) else None
            if not isinstance(projects, list):
                continue
            for index, entry in enumerate(projects):
                if not isinstance(entry, dict):
                    continue
                ledger_path = entry.get("ledger_path")
                declared = entry.get("last_digest")
                if not isinstance(ledger_path, str) or not isinstance(declared, str):
                    continue
                # A path that was not passed on the command line is not
                # comparable. Silence here means "not checked", never "correct".
                actual = digests.get(_path_key(ledger_path))
                if actual is None or actual == declared:
                    continue
                findings.append(
                    f"{source}: known_projects[{index}] last_digest {declared!r} "
                    f"does not match {ledger_path!r}, which hashes to {actual!r}"
                )
```

In `verify`, compute the digests while reading and pass them through:

```python
def verify(paths: list[Path]) -> int:
    findings: list[str] = []
    documents: list[tuple[str, dict]] = []
    errors: list[str] = []
    digests: dict[str, str] = {}

    for path in paths:
        source = str(path)
        try:
            data = load_json(path)
            digest = file_digest(path)
        except LedgerError as exc:
            errors.append(str(exc))
            continue
        except OSError as exc:
            errors.append(f"Unreadable ledger: {path}: {exc}")
            continue
        # Register both the path as given and its resolved form, so a ledger
        # that stores an absolute path still matches a relative invocation.
        digests[_path_key(source)] = digest
        digests[_path_key(str(path.resolve()))] = digest
        findings.extend(validate_ledger(data, source=source))
        documents.append((source, data))

    findings.extend(
        validate_collection(documents, complete=not errors, digests=digests)
    )
```

Leave the rest of `verify` unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m unittest discover -s dashboard/tests
```

Expected: OK, with three more tests than before.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py dashboard/tests/test_dashboard.py
git commit -m "feat: compare a recorded ledger digest against the file it names

known_projects[].last_digest was shape-checked and never compared to anything.
During the 0.2.1 dogfood it went stale twice -- once when records were written
after the pointer was set, once after a review fix -- and verify reported clean
both times. Nothing distinguished a correct digest from a well-formed one.

The comparison uses only files the user named on the command line. Opening a
path read out of ledger content is the surface spec 13.6 was deferred to
constrain, and ledger content is attacker-influenced by design. A named ledger
absent from the invocation is not comparable, and stays silent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The ID authority's sequences cover every id actually spent

Closes finding 3(b).

**Files:**
- Modify: `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`
- Test: `dashboard/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `validate_collection` as Task 1 left it.
- Produces: no new public name. Task 3 adds to the same function.

- [ ] **Step 1: Write the failing tests**

```python
    def test_authority_sequences_must_cover_a_sibling_ledgers_records(self) -> None:
        authority = self.global_ledger()
        authority["sequences"]["MAT"] = 0
        project = self.project_ledger()
        project["records"] = [self.material_record("MAT-2026-000")]
        project["sequences"]["MAT"] = 1

        findings = dashboard.validate_collection(
            [("global.json", authority), ("project.json", project)]
        )

        self.assertTrue(
            any("sequences.MAT" in finding and "global.json" in finding for finding in findings)
        )

    def test_a_project_ledger_is_not_responsible_for_a_siblings_records(self) -> None:
        authority = self.global_ledger()
        authority["sequences"]["MAT"] = 6
        first = self.project_ledger()
        first["records"] = [self.material_record("MAT-2026-005")]
        first["sequences"]["MAT"] = 6
        second = self.project_ledger()
        second["records"] = [self.material_record("MAT-2026-000")]
        second["sequences"]["MAT"] = 1

        findings = dashboard.validate_collection(
            [("global.json", authority), ("a.json", first), ("b.json", second)]
        )

        self.assertFalse(any("sequences" in finding for finding in findings))
```

Use the existing helpers for building a ledger and a record. If the test class builds records inline rather than through a helper, build them inline the same way; the identifiers above are what matter.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m unittest discover -s dashboard/tests -v
```

Expected: `test_authority_sequences_must_cover_a_sibling_ledgers_records` fails — no finding is produced today. `test_a_project_ledger_is_not_responsible_for_a_siblings_records` should already pass; if it does not, stop and report, because the existing per-document rule is then not what this plan assumes.

- [ ] **Step 3: Write the implementation**

Inside `validate_collection`, the per-document loop already builds a local `highest` dict. Add a set-wide one. Before the `for source, data in documents:` loop, add:

```python
    # Highest number seen per prefix across the whole verified set, with the
    # identifier and the ledger that holds it, so the authority check below can
    # name where the id was actually spent.
    spent: dict[str, tuple[int, str, str]] = {}
```

Inside the `for record in records:` loop, immediately after the existing `highest[prefix] = (number, identifier)` block, add:

```python
            current_spent = spent.get(prefix)
            if current_spent is None or number > current_spent[0]:
                spent[prefix] = (number, identifier, source)
```

Then, after the per-document loop closes and before the `if complete:` block, add:

```python
    # The global ledger is the sole ID authority, and normally holds no records
    # of its own: every project-scoped record routes to a project ledger. So the
    # per-document rule above never relates the authority's allocation counter to
    # the ids it actually issued. Fold in the whole set.
    for source, data in documents:
        if not isinstance(data, dict) or data.get("id_authority") is not True:
            continue
        sequences = data.get("sequences")
        if not isinstance(sequences, dict):
            continue
        for prefix, (number, identifier, holder) in spent.items():
            if holder == source:
                continue  # the per-document rule already covers this one
            allocated = sequences.get(prefix)
            if type(allocated) is int and allocated < number + 1:
                findings.append(
                    f"{source}: sequences.{prefix} is {allocated} but the ID "
                    f"authority must cover {identifier}, allocated in {holder}"
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m unittest discover -s dashboard/tests
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py dashboard/tests/test_dashboard.py
git commit -m "feat: check the ID authority's sequences against the whole verified set

The sequence check compared a ledger's sequences only against records in that
same document. The global ledger normally holds none -- every project-scoped
record routes to a project ledger -- so the one ledger designated as sole ID
authority was precisely the one whose allocation counter nothing validated.
Setting its sequences.MAT to 0 while a sibling held MAT-2026-000 passed clean.

Non-authority ledgers keep the own-records rule: a project ledger is not made
responsible for another project's allocations.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: A backlog entry's id must name a record that exists

Closes finding 4.

**Files:**
- Modify: `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`
- Test: `dashboard/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `validate_collection` as Tasks 1 and 2 left it, including its `declared` set of record ids and its `complete` flag.
- Produces: no new public name.

- [ ] **Step 1: Write the failing tests**

```python
    def test_backlog_id_referencing_no_record_is_reported(self) -> None:
        ledger = self.project_ledger()
        ledger["records"] = [self.material_record("MAT-2026-000")]
        ledger["sequences"]["MAT"] = 1
        ledger["backlog"] = [
            {
                "id": "MAT-2026-777",
                "classification": "MONITOR",
                "reason": "refers to nothing",
                "revisit_trigger": "never",
                "revisit_after": None,
            }
        ]

        findings = dashboard.validate_collection([("project.json", ledger)])

        self.assertTrue(any("MAT-2026-777" in finding for finding in findings))

    def test_two_backlog_entries_may_share_one_id(self) -> None:
        ledger = self.project_ledger()
        ledger["records"] = [self.material_record("MAT-2026-000")]
        ledger["sequences"]["MAT"] = 1
        entry = {
            "id": "MAT-2026-000",
            "classification": "MONITOR",
            "reason": "one material can produce several findings",
            "revisit_trigger": "upstream fix",
            "revisit_after": None,
        }
        ledger["backlog"] = [dict(entry), dict(entry)]

        findings = dashboard.validate_collection([("project.json", ledger)])

        self.assertFalse(any("backlog" in finding for finding in findings))

    def test_backlog_back_references_are_suppressed_for_a_partial_set(self) -> None:
        ledger = self.project_ledger()
        ledger["backlog"] = [
            {
                "id": "MAT-2026-777",
                "classification": "MONITOR",
                "reason": "the record may live in the ledger that could not be read",
                "revisit_trigger": "never",
                "revisit_after": None,
            }
        ]

        findings = dashboard.validate_collection(
            [("project.json", ledger)], complete=False
        )

        self.assertFalse(any("MAT-2026-777" in finding for finding in findings))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m unittest discover -s dashboard/tests -v
```

Expected: the first test fails (no finding today). The second and third should already pass.

- [ ] **Step 3: Write the implementation**

Inside the existing `if complete:` block in `validate_collection`, after the link-checking loop, add:

```python
        # A backlog entry's id is a back-reference to the record whose evidence
        # produced the finding, not a unique key: one material routinely yields
        # several backlog entries, so duplicates are correct here. What is
        # checkable is that the record exists. Suppressed with the link checks
        # when the set is partial, for the same reason: the record may live in
        # the ledger that could not be read.
        for source, data in documents:
            backlog = data.get("backlog") if isinstance(data, dict) else None
            if not isinstance(backlog, list):
                continue
            for index, entry in enumerate(backlog):
                if not isinstance(entry, dict):
                    continue
                identifier = entry.get("id")
                if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                    continue  # validate_backlog_entry already reported the shape
                if identifier not in declared:
                    findings.append(
                        f"{source}: backlog[{index}] id {identifier!r} references "
                        "a record that exists in no verified ledger"
                    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m unittest discover -s dashboard/tests
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py dashboard/tests/test_dashboard.py
git commit -m "feat: check a backlog id resolves to a record that exists

The Backlog section required an id but never said what it referred to or
whether it had to be unique, and the duplicate-identifier check walked only
records, so the field's actual meaning could be learned only by reading the
validator. It is a back-reference to the record whose evidence produced the
finding -- deliberately not unique, since one material routinely yields several
entries -- and that is now both documented and half-enforced: uniqueness is not
required, existence is.

Suppressed alongside the link checks when the set is partial: the record may
live in the ledger that could not be read.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: A RUN record must admit that target coverage is self-reported

Closes finding 5. This is the finding the dogfood called the most serious.

**Files:**
- Modify: `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`
- Modify: `skills/agent-ingest-audit-optimize/assets/schemas/ledger.schema.json`
- Test: `dashboard/tests/test_dashboard.py`

**Interfaces:**
- Consumes: `validate_run` as it stands.
- Produces: a new rule every RUN record must satisfy, including the one in this repository's own ledger, which Task 7 updates.

- [ ] **Step 1: Write the failing tests**

```python
    def test_run_must_name_targets_in_self_reported(self) -> None:
        record = self.run_record()
        record["self_reported"] = ["backup", "result"]

        findings = dashboard.validate_run(record, label="RUN-2026-000")

        self.assertTrue(any("self_reported" in finding and "targets" in finding for finding in findings))

    def test_run_naming_targets_in_self_reported_is_accepted(self) -> None:
        record = self.run_record()
        record["self_reported"] = ["targets", "backup", "result"]

        findings = dashboard.validate_run(record, label="RUN-2026-000")

        self.assertFalse(any("self_reported" in finding for finding in findings))
```

Use the existing helper the RUN tests already use to build a valid RUN record. If every RUN test builds one inline, build it inline the same way, and make sure the baseline record is otherwise valid so the only finding under test is this one.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m unittest discover -s dashboard/tests -v
```

Expected: `test_run_must_name_targets_in_self_reported` fails. Several PRE-EXISTING RUN tests will also start failing later in Step 3 once the rule lands — that is expected and Step 4 handles it.

- [ ] **Step 3: Write the implementation**

In `validate_run`, replace the `self_reported` block with:

```python
    reported = record["self_reported"]
    if not isinstance(reported, list) or any(
        not isinstance(item, str) for item in reported
    ):
        findings.append(f"{label} self_reported must be an array of strings")
    elif "targets" not in reported:
        # Every target's shape is checked; the array's coverage cannot be.
        # Nothing in a ledger says how many files a run was supposed to touch,
        # so a RUN can name three targets for a fourteen-file change and pass.
        # The record must say so in the field built for exactly that admission.
        findings.append(
            f"{label} self_reported must name 'targets': verify checks each "
            "target's shape and can never check that the array covers what the "
            "run changed"
        )
```

In `ledger.schema.json`, find the RUN record's `self_reported` definition and add the structural half of the rule so schema and runtime agree:

```json
        "self_reported": {
          "type": "array",
          "items": { "type": "string" },
          "contains": { "const": "targets" }
        }
```

- [ ] **Step 4: Fix every pre-existing RUN fixture the new rule invalidates**

Run the suite and find each failing test whose RUN fixture omits `"targets"` from `self_reported`. Add it. Do NOT weaken the new rule to accommodate a fixture, and do not change what any of those tests actually assert — only make their baseline record valid under the new contract.

```bash
python -m unittest discover -s dashboard/tests -v
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m unittest discover -s dashboard/tests
```

Expected: OK. The test asserting schema and runtime checks agree must be among the passing ones — if it fails, the schema edit and the runtime edit disagree.

- [ ] **Step 6: Commit**

```bash
git add skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py skills/agent-ingest-audit-optimize/assets/schemas/ledger.schema.json dashboard/tests/test_dashboard.py
git commit -m "feat: require a RUN record to admit that target coverage is self-reported

A RUN record listed three targets for a release that changed fourteen files and
validated clean, because every target it did name was well-formed and nothing
tells the validator how many there should have been. A human review pass caught
it; no tool did. Of the five dogfood findings this is the one that matters most:
the record type whose entire purpose is describing a change could misdescribe it
and still pass in full.

This does not make coverage verifiable -- that knowledge lives outside the
ledger. It stops the record from being silent about it. self_reported already
exists for fields no tool can confirm, and targets was never listed there.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The contract catches up with the code

Closes finding 2 and finding 3(a), and documents Tasks 1, 3, and 4.

**Files:**
- Modify: `skills/agent-ingest-audit-optimize/references/LEDGER.md`
- Test: `dashboard/tests/test_dashboard.py`

**Interfaces:**
- Consumes: every rule Tasks 1-4 added.
- Produces: nothing later tasks read programmatically.

- [ ] **Step 1: Write the failing test**

`dashboard/tests/test_dashboard.py` already has a class asserting `LEDGER.md` documents the vocabulary the validator enforces. Add assertions there, in the same style, that the reference now states each new rule. Anchor on distinctive phrases rather than whole sentences, so ordinary editing does not break them:

```python
    def test_reference_documents_the_new_checks(self) -> None:
        text = LEDGER_REFERENCE.read_text(encoding="utf-8")
        for phrase in (
            "final on-disk bytes",
            "not comparable",
            "a floor",
            "back-reference",
            "self_reported",
        ):
            self.assertIn(phrase, text)
```

Use whatever constant the existing tests use for the reference path rather than introducing a new one.

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m unittest discover -s dashboard/tests -v
```

- [ ] **Step 3: Write the reference updates**

In `references/LEDGER.md`:

**Under Identifiers**, replace the sentence describing the sequence check with:

```markdown
`verify` checks that a ledger's `sequences` value for a prefix is at least one past the highest
number that ledger's own records already use. It is a floor, not an equality: a value above it
passes too, so a padded `sequences` is never flagged. Keeping it at exactly the next free number is
a house convention, stricter than what is enforced.

The ledger that declares `id_authority: true` is additionally checked against every record in the
verified set, not just its own — it is the ledger that issued those identifiers, and it usually
holds no records itself.
```

**Under Known projects**, add:

```markdown
`last_digest` is the sha256 of the referenced ledger's **final on-disk bytes**, taken after every
other edit to that ledger is complete. Hash the file, not the JSON text in an editor: a trailing
newline or a line-ending difference changes the digest of an otherwise identical document.

When the referenced ledger is passed in the same `verify` invocation, its digest is recompared and
a mismatch is a finding. When it is not, nothing is checked — silence there means **not comparable**,
never "correct". `verify` deliberately does not open a path read out of ledger content.
```

**Under Backlog**, add:

```markdown
A backlog entry's `id` is a **back-reference** to the record whose evidence produced the finding,
not an identifier of the entry itself. It is deliberately not unique: one material routinely
produces several backlog entries, and two entries sharing an id is correct. `verify` checks that the
id resolves to a record declared somewhere in the verified set, and suppresses that check, like the
link checks, when any ledger in the set could not be read.
```

**Under Runs**, add:

```markdown
`self_reported` must name `targets`. `verify` checks every target's shape and can never check that
the array covers what the run actually changed — nothing in a ledger states how many files a run was
supposed to touch. A RUN record naming three targets for a fourteen-file change validates clean.
Listing `targets` in `self_reported` does not make coverage verifiable; it stops the record from
being silent about the one thing it cannot prove.
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m unittest discover -s dashboard/tests
```

- [ ] **Step 5: Commit**

```bash
git add skills/agent-ingest-audit-optimize/references/LEDGER.md dashboard/tests/test_dashboard.py
git commit -m "docs: bring the ledger contract into agreement with the validator

The dogfood found the reference describing sequences as \"the next free number\"
when the code enforces a floor, never saying which bytes a digest is taken from,
and never stating what a backlog id means -- that last one could only be learned
by reading the validator's source. State all three, plus the two rules this
release added and the deliberate silence when a referenced ledger is absent from
the invocation.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The four carried minors

**Files:**
- Modify: `packaging/tests/test_version_consistency.py`
- Modify: `packaging/tests/test_package_plugin.py`
- Modify: `skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py`

**Interfaces:**
- Consumes: nothing.
- Produces: two more packaging tests.

- [ ] **Step 1: Guard the marketplace entry count**

In `test_version_consistency.py`, both marketplace assertions index `plugins[0]` unconditionally. Assert the array holds exactly one entry first, so a second entry fails loudly instead of going silently unchecked:

```python
    def test_claude_marketplace_version_matches(self) -> None:
        plugins = load_json(CLAUDE_MARKETPLACE)["plugins"]
        self.assertEqual(len(plugins), 1, "a second entry would go unchecked")
        self.assertEqual(plugins[0]["version"], self.version)

    def test_agents_marketplace_ref_matches(self) -> None:
        plugins = load_json(AGENTS_MARKETPLACE)["plugins"]
        self.assertEqual(len(plugins), 1, "a second entry would go unchecked")
        self.assertEqual(plugins[0]["source"]["ref"], f"v{self.version}")
```

- [ ] **Step 2: Record why the path constants are duplicated**

Two reviewers judged the duplication correct and one nearly "fixed" it. Add a comment above the path constants in `test_version_consistency.py` so the reasoning survives:

```python
# These paths intentionally duplicate the ones in packaging/scripts/package_plugin.py
# rather than importing them. This module is the drift check; deriving its paths from
# the packager would let one path bug mask another.
```

- [ ] **Step 3: Guard the evaluation-case count**

`docs/SUBMISSION.md` states a case count that was hand-corrected in 0.2.1 with nothing checking it. Add to `packaging/tests/test_package_plugin.py`, matching its style:

```python
    def test_submission_states_the_real_evaluation_case_count(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        suite = json.loads((repo_root / "evals" / "suite.json").read_text(encoding="utf-8"))
        submission = (repo_root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
        stated = re.findall(r"(\d+)-case evaluation suite", submission)

        self.assertEqual(len(stated), 1, "expected exactly one case-count claim")
        self.assertEqual(int(stated[0]), len(suite["cases"]))
```

Add `json` and `re` to that module's imports if they are not already there.

- [ ] **Step 4: Reword the docstring that goes stale every release**

`dashboard.py`'s module docstring names a version. Replace the second paragraph with wording that names the command set instead:

```python
"""Validate the agent-ingest-audit-optimize governance ledger.

`verify` is the only command implemented. Scanning, drift detection, rollback
preview, and dashboard rendering arrive in later phases.
"""
```

- [ ] **Step 5: Run every suite**

```bash
python -m unittest discover -s dashboard/tests && python -m unittest discover -s packaging/tests
```

Expected: both OK. The packaging suite gains one test.

- [ ] **Step 6: Commit**

```bash
git add packaging/tests skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py
git commit -m "test: guard the marketplace entry count and the stated case count

Both marketplace assertions indexed plugins[0] with no length check, so a second
entry would have gone unchecked rather than failing. The evaluation-case count in
docs/SUBMISSION.md was hand-corrected in 0.2.1 with nothing guarding it -- the
same 'nothing fails when it is wrong' this release's predecessor indicted, just
outside the version-pin contract.

Also records why this module duplicates the packager's path constants instead of
importing them, since that has now been questioned twice, and drops the version
number from dashboard.py's docstring so it stops going stale every release.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Release 0.2.2

**Files:**
- Modify: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json`, `README.md`, `docs/SUBMISSION.md`, `CHANGELOG.md`
- Create: `docs/releases/v0.2.2.md`
- Modify: `.agent-audit/ledger.json` (untracked)

**Interfaces:**
- Consumes: everything above.
- Produces: the released state.

- [ ] **Step 1: Make this repository's own ledger satisfy the new rule**

The RUN record in `.agent-audit/ledger.json` does not name `targets` in `self_reported`, so `verify` now flags this repository's own ledger. Add it. Nothing is staged — the ledger is untracked.

```bash
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify "$HOME/.claude/agent-ingest-audit-optimize/ledger.json" ".agent-audit/ledger.json"; echo "exit=$?"
```

Run this BEFORE editing, and record the finding it produces — that output is evidence the new rule fires on a real ledger rather than only on fixtures. Then add `"targets"` to the RUN record's `self_reported`, recompute the global ledger's `known_projects[0].last_digest` from the project ledger's final bytes, and re-run. Expected after: exit `0`.

If Task 1's digest check fires here, that is also real evidence — record it before fixing.

- [ ] **Step 2: Bump every pin to 0.2.2**

The version test enumerates them. Bump `.claude-plugin/plugin.json` first, then run the test and let it name anything still stale:

```bash
python -m unittest discover -s packaging/tests -v
```

Fix each pin it names until the suite is green. It covers the three manifests, the `.agents` ref, both README references, the SUBMISSION version line, the CHANGELOG heading, and the release document.

- [ ] **Step 3: Write the CHANGELOG entry**

Insert above `## 0.2.1 - 2026-07-30`:

```markdown
## 0.2.2 - 2026-07-30

- compares `known_projects[].last_digest` against the referenced ledger when that ledger is passed
  in the same invocation, closing a gap where a wrong-but-well-formed digest was indistinguishable
  from a correct one; the comparison never opens a path read out of ledger content, so it cannot be
  steered by a crafted `ledger_path`;
- checks the `id_authority` ledger's `sequences` against every record in the verified set rather
  than only its own, since the ledger designated as sole ID authority normally holds no records and
  was therefore the one ledger whose allocation counter nothing validated;
- defines a backlog entry's `id` as a back-reference to the record whose evidence produced the
  finding, deliberately not unique, and checks that it resolves to a record that exists;
- requires every RUN record to name `targets` in `self_reported`, because `verify` checks each
  target's shape and can never check that the array covers what the run changed;
- states in `references/LEDGER.md` that a digest is taken from the referenced ledger's final
  on-disk bytes, and that the sequence check is a floor rather than the equality the prose implied;
- guards the marketplace plugin-entry count and the evaluation-case count stated in
  `docs/SUBMISSION.md`, neither of which had a check.

**Compatibility:** a ledger that validated clean under 0.2.1 may now produce findings. The new
checks describe conditions that were always wrong and merely unobserved. One is a hard requirement
rather than a detection: add `"targets"` to every RUN record's `self_reported` array.
```

- [ ] **Step 4: Write `docs/releases/v0.2.2.md`**

Follow `docs/releases/v0.2.1.md` exactly: title, one-line release name ("Ledger validator release."), `## Changes` from the CHANGELOG entry, `## Assets`, `## Checksums`, `## Claude Code installation`, `## Codex installation`.

Checksums come from a build, never invented:

```bash
python packaging/scripts/package_plugin.py build && cat dist/SHA256SUMS
```

- [ ] **Step 5: Run every check**

```bash
python -m unittest discover -s dashboard/tests && python -m unittest discover -s evals/tests && python -m unittest discover -s packaging/tests && python evals/scripts/eval_suite.py validate && python packaging/scripts/package_plugin.py build && python packaging/scripts/package_plugin.py verify
```

Then confirm the archives carry no compiled bytecode, the guard 0.2.1 added:

```bash
python -c "import zipfile;print([n for n in zipfile.ZipFile('dist/agent-ingest-audit-optimize-0.2.2-plugin.zip').namelist() if 'pycache' in n or n.endswith('.pyc')] or 'clean')"
```

Report the observed counts rather than assuming them.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin .codex-plugin .agents README.md docs/SUBMISSION.md CHANGELOG.md docs/releases/v0.2.2.md
git commit -m "release: v0.2.2 -- close the five findings the dogfood produced

0.2.1 kept this repository's ledger by hand for the first time and found five
places where a wrong-but-well-formed value survived validation indefinitely.
They were recorded unfixed because verify was out of that release's scope. Close
them before 0.3.0, whose scan, drift, and rollback-preview all write to the
ledger: these gaps do not stay the same size once three more writers use the
format.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Acceptance

| Criterion | Evidence |
|---|---|
| A stale digest is caught | Task 1 Step 4 |
| A ledger outside the set produces no digest finding | Task 1 Step 4 |
| No path from ledger content is ever opened | `_path_key` normalizes textually; `file_digest` is called only on command-line paths |
| The authority's sequences are cross-checked | Task 2 Step 4 |
| A project ledger is not responsible for siblings | Task 2 Step 4 |
| A dangling backlog back-reference is caught | Task 3 Step 4 |
| Shared backlog ids stay legal | Task 3 Step 4 |
| Partial sets suppress the new back-reference check | Task 3 Step 4 |
| A RUN omitting `targets` from `self_reported` is caught | Task 4 Step 5 |
| Schema and runtime still agree | The existing agreement test passes in Task 4 Step 5 |
| The reference documents every new rule | Task 5 Step 4 |
| The new rule fires on a real ledger, not only fixtures | Task 7 Step 1 records the finding before fixing it |
| This repository's ledger complies | Task 7 Step 1 ends at exit `0` |
| Nothing regressed | Task 7 Step 5 — every suite green, archives `.pyc`-free |

## Release sequencing after this plan

Merge, then push the lightweight tag `v0.2.2` immediately — `.agents/plugins/marketplace.json` names it and cannot resolve until it exists — then publish the release with both archives and `SHA256SUMS`.

## Out of scope

A canonical ledger formatter; opening files named by ledger content; every 0.3.0 deliverable; splitting `dashboard.py` into a package.
