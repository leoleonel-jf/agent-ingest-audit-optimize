"""Tests for `ledgerlib.drift`: the five-state classification and the report.

The suite loads `dashboard.py` by file path exactly the way `test_scan.py`
does, for the same side effect: `dashboard.py` inserts its own directory at
the front of `sys.path` before importing `ledgerlib`, so the imports below
resolve to the bundle's copy rather than to anything installed.

Two rules from the spec are pinned by name here because each is the kind of
mistake a later refactor makes silently: a recorded absence that holds is
`IN_PLACE` while a file appearing where none was is `DRIFTED` (the not_present
rows of spec 3.2), and a run target whose `before_digest` equals its
`after_digest` is `IN_PLACE`, never `REVERTED` -- `after` is checked first
because the tie means the change is intact.

Classification purity is asserted by running one fixture through
`drift_report` twice, with and without `resolution` data in the adapter
document: the reports must be identical once each row's `resolution`
annotation -- the one key that legitimately reads the declaration, and the
one Task 4 adds -- is removed. States, reasons, summary, messages, and exit
code must be byte-identical; only the annotation may differ.
"""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "scripts"
    / "dashboard.py"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib.constants import DRIFT_STATES  # noqa: E402
from ledgerlib.errors import PATH_SAFETY_REASONS  # noqa: E402
from ledgerlib import drift as drift_module  # noqa: E402
from ledgerlib.drift import (  # noqa: E402
    classify_item,
    classify_target,
    drift_command,
    drift_report,
    resolved_path,
)
from ledgerlib.paths import resolve_anchored  # noqa: E402


class DriftTestCase(unittest.TestCase):
    """A real temporary tree, following `ProbeTestCase` in test_scan.py.

    Nothing is mocked that can be built: the classifier's whole job is to
    compare recorded digests against a real filesystem, so the fixtures are
    real files whose digests the tests compute independently.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user_config = self.tmp / "user_config"
        self.user_config.mkdir(parents=True)
        # Resolved and absolute, exactly as `resolve_anchor_roots` returns
        # them. The keys are BARE anchor names.
        self.roots: dict[str, Path] = {"USER_CONFIG": self.user_config}

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def digest_of(self, path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def item(self, **overrides: object) -> dict:
        base: dict = {
            "kind": "instruction-file",
            "name": "CLAUDE.md",
            "anchor": "$USER_CONFIG/CLAUDE.md",
            "digest": None,
            "attributes": {},
            "origin": "pre-existing",
            "state": "present",
        }
        base.update(overrides)
        return base

    def target(self, **overrides: object) -> dict:
        base: dict = {
            "anchor": "$USER_CONFIG/settings.json",
            "kind": "mcp-server",
            "before_digest": "sha256:" + "0" * 64,
            "after_digest": "sha256:" + "1" * 64,
            "reversible": True,
            "residual_effect": None,
        }
        base.update(overrides)
        return base


class DriftStatesTests(unittest.TestCase):
    def test_drift_states_is_exactly_the_five_state_set(self) -> None:
        self.assertEqual(
            DRIFT_STATES,
            {"IN_PLACE", "DRIFTED", "REVERTED", "MISSING", "UNVERIFIABLE"},
        )


class BaselineItemTests(DriftTestCase):
    """One test per row of spec 3.2's baseline-item table."""

    def test_a_present_item_whose_digest_matches_is_in_place(self) -> None:
        target = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        state, reason = classify_item(
            self.item(digest=self.digest_of(target)), self.roots
        )
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_present_item_whose_digest_differs_is_drifted(self) -> None:
        target = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        recorded = self.digest_of(target)
        self.write(target, "# memory, edited outside the tool\n")
        state, reason = classify_item(self.item(digest=recorded), self.roots)
        self.assertEqual((state, reason), ("DRIFTED", None))

    def test_a_present_item_whose_file_is_gone_is_missing(self) -> None:
        state, reason = classify_item(
            self.item(digest="sha256:" + "a" * 64), self.roots
        )
        self.assertEqual((state, reason), ("MISSING", None))

    def test_a_recorded_absence_that_holds_is_in_place(self) -> None:
        state, reason = classify_item(
            self.item(state="not_present", digest=None), self.roots
        )
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_file_appearing_where_none_was_recorded_is_drifted(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "configuration from outside\n")
        state, reason = classify_item(
            self.item(state="not_present", digest=None), self.roots
        )
        self.assertEqual(state, "DRIFTED")
        self.assertEqual(reason, "appeared")

    def test_an_absent_glob_pattern_with_no_match_now_is_in_place(self) -> None:
        # A glob probe that matched nothing records the pattern itself as the
        # item's anchor; re-checking that absence means re-matching, not
        # stat-ing a path with a literal `*` in it.
        item = self.item(
            state="not_present",
            digest=None,
            kind="skill",
            name="$USER_CONFIG/skills/*/SKILL.md",
            anchor="$USER_CONFIG/skills/*/SKILL.md",
        )
        state, reason = classify_item(item, self.roots)
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_an_absent_glob_pattern_with_a_match_now_is_drifted(self) -> None:
        self.write(self.user_config / "skills" / "new" / "SKILL.md", "arrived\n")
        item = self.item(
            state="not_present",
            digest=None,
            kind="skill",
            name="$USER_CONFIG/skills/*/SKILL.md",
            anchor="$USER_CONFIG/skills/*/SKILL.md",
        )
        state, reason = classify_item(item, self.roots)
        self.assertEqual(state, "DRIFTED")
        self.assertEqual(reason, "appeared")

    def test_a_present_item_with_a_null_digest_is_unverifiable_with_a_reason(
        self,
    ) -> None:
        # The file is readable NOW; what cannot be verified is the recorded
        # side -- scan could not read it then, so there is nothing to compare.
        self.write(self.user_config / "CLAUDE.md", "readable now\n")
        state, reason = classify_item(self.item(digest=None), self.roots)
        self.assertEqual((state, reason), ("UNVERIFIABLE", "digest_not_recorded"))

    def test_an_unreadable_file_now_is_unverifiable_with_a_reason_not_a_crash(
        self,
    ) -> None:
        target = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        recorded = self.digest_of(target)
        with mock.patch.object(
            drift_module,
            "file_digest",
            side_effect=OSError("Permission denied"),
        ):
            state, reason = classify_item(self.item(digest=recorded), self.roots)
        self.assertEqual((state, reason), ("UNVERIFIABLE", "unreadable"))

    def test_every_item_under_an_unresolvable_anchor_is_unverifiable(self) -> None:
        # `$SYSTEM_CONFIG` on Windows: `resolve_anchor_roots` omits an anchor
        # with no existing root, so the stored form names an anchor the roots
        # mapping does not hold. Present and not_present alike: an absence
        # under a tree nothing can look at is not a verified absence.
        for recorded_state, digest in (
            ("present", "sha256:" + "a" * 64),
            ("not_present", None),
        ):
            with self.subTest(recorded_state=recorded_state):
                item = self.item(
                    state=recorded_state,
                    digest=digest,
                    anchor="$SYSTEM_CONFIG/config.toml",
                )
                state, reason = classify_item(item, self.roots)
                self.assertEqual(state, "UNVERIFIABLE")
                self.assertIn(reason, PATH_SAFETY_REASONS)

    def test_a_malformed_item_is_unverifiable_never_a_crash(self) -> None:
        for bad in (None, "text", 7, ["list"], {"state": "weird"}, {}):
            with self.subTest(bad=bad):
                state, reason = classify_item(bad, self.roots)
                self.assertEqual(state, "UNVERIFIABLE")
                self.assertIsNotNone(reason)

    def test_every_state_returned_is_a_member_of_drift_states(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "x\n")
        items = [
            self.item(digest=self.digest_of(self.user_config / "CLAUDE.md")),
            self.item(digest="sha256:" + "b" * 64),
            self.item(state="not_present", digest=None),
            self.item(digest=None),
            self.item(anchor="$NOWHERE/x", digest="sha256:" + "c" * 64),
        ]
        for item in items:
            state, _ = classify_item(item, self.roots)
            self.assertIn(state, DRIFT_STATES)


class PointerRecheckTests(DriftTestCase):
    """Recorded in-file absences re-resolve the pointer, not the file.

    The dogfood run that motivated these: three `pointer_unresolved` items
    were reported `DRIFTED`/`appeared` minutes after their scan because the
    classifier tested the file's existence -- and the file had existed at
    scan time too, or there would have been no document to walk.
    """

    def pointer_item(self, **attribute_overrides: object) -> dict:
        attributes: dict = {
            "scope": "user",
            "reason": "pointer_unresolved",
            "pointer": "/env",
            "parse": "json",
        }
        attributes.update(attribute_overrides)
        return self.item(
            kind="env-var-name",
            name="settings.json/env",
            anchor="$USER_CONFIG/settings.json",
            state="not_present",
            digest=None,
            attributes=attributes,
        )

    def test_a_pointer_still_absent_in_an_existing_file_is_in_place(self) -> None:
        self.write(self.user_config / "settings.json", '{"model": "opus"}\n')
        state, reason = classify_item(self.pointer_item(), self.roots)
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_pointer_that_now_resolves_is_drifted_appeared(self) -> None:
        self.write(
            self.user_config / "settings.json",
            '{"model": "opus", "env": {"HTTP_PROXY": "http://proxy"}}\n',
        )
        state, reason = classify_item(self.pointer_item(), self.roots)
        self.assertEqual((state, reason), ("DRIFTED", "appeared"))

    def test_a_pointer_resolving_to_an_empty_mapping_is_in_place(self) -> None:
        # `scan` records an empty mapping as `not_present`/`no_match`, so an
        # empty mapping now is the same recorded absence, still holding.
        self.write(self.user_config / "settings.json", '{"env": {}}\n')
        state, reason = classify_item(self.pointer_item(), self.roots)
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_recorded_no_match_that_now_has_keys_is_drifted(self) -> None:
        self.write(
            self.user_config / "settings.json", '{"env": {"NEW": "value"}}\n'
        )
        state, reason = classify_item(
            self.pointer_item(reason="no_match"), self.roots
        )
        self.assertEqual((state, reason), ("DRIFTED", "appeared"))

    def test_a_baseline_without_the_recorded_pointer_is_unverifiable(self) -> None:
        # 0.2.5 baselines predate the recorded pointer: nothing to re-resolve,
        # and neither IN_PLACE nor DRIFTED would be a verified answer.
        self.write(self.user_config / "settings.json", '{"model": "opus"}\n')
        item = self.pointer_item()
        del item["attributes"]["pointer"]
        del item["attributes"]["parse"]
        state, reason = classify_item(item, self.roots)
        self.assertEqual((state, reason), ("UNVERIFIABLE", "pointer_unrecorded"))

    def test_a_file_that_no_longer_parses_is_unverifiable(self) -> None:
        self.write(self.user_config / "settings.json", "{not json any more\n")
        state, reason = classify_item(self.pointer_item(), self.roots)
        self.assertEqual((state, reason), ("UNVERIFIABLE", "unparseable"))

    def test_the_recheck_walks_the_redacted_document(self) -> None:
        # `scan` redacts before the pointer walks, so a pointer aimed inside
        # a redacted subtree recorded `pointer_unresolved` even though the
        # raw document had the key. The recheck must mirror that -- with the
        # same patterns -- or an absence that never stopped holding would be
        # reported as configuration arriving.
        self.write(
            self.user_config / "settings.json",
            '{"env": {"TOKEN": "value-that-must-stay-unread"}}\n',
        )
        item = self.pointer_item(pointer="/env/TOKEN")
        state, reason = classify_item(item, self.roots, patterns=("env",))
        self.assertEqual((state, reason), ("IN_PLACE", None))
        # Without the patterns the same pointer resolves: the parity above is
        # the redaction, not an accident of the fixture.
        state, reason = classify_item(item, self.roots)
        self.assertEqual((state, reason), ("DRIFTED", "appeared"))

    def test_a_pointer_recheck_with_the_file_gone_is_in_place(self) -> None:
        # No file at all certainly holds an in-file absence.
        state, reason = classify_item(self.pointer_item(), self.roots)
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_no_match_without_a_pointer_is_a_file_level_absence(self) -> None:
        # `no_match` is also what a literal, wildcard-free glob records when
        # it matches nothing -- the dogfood's `$PROJECT/CLAUDE.md`. With no
        # recorded pointer there is no in-file location, and the file
        # appearing IS the drift.
        self.write(self.user_config / "settings.json", '{"model": "opus"}\n')
        item = self.pointer_item(reason="no_match")
        del item["attributes"]["pointer"]
        del item["attributes"]["parse"]
        state, reason = classify_item(item, self.roots)
        self.assertEqual((state, reason), ("DRIFTED", "appeared"))


class RunTargetTests(DriftTestCase):
    """Design spec section 10's table, literally, plus the tie rule."""

    def test_a_target_matching_after_digest_is_in_place(self) -> None:
        target = self.write(self.user_config / "settings.json", "{}\n")
        state, reason = classify_target(
            self.target(after_digest=self.digest_of(target)), self.roots
        )
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_target_matching_before_digest_is_reverted(self) -> None:
        target = self.write(self.user_config / "settings.json", "{}\n")
        state, reason = classify_target(
            self.target(before_digest=self.digest_of(target)), self.roots
        )
        self.assertEqual((state, reason), ("REVERTED", None))

    def test_a_target_matching_neither_digest_is_drifted(self) -> None:
        self.write(self.user_config / "settings.json", "modified externally\n")
        state, reason = classify_target(self.target(), self.roots)
        self.assertEqual((state, reason), ("DRIFTED", None))

    def test_a_target_whose_path_is_gone_is_missing(self) -> None:
        state, reason = classify_target(self.target(), self.roots)
        self.assertEqual((state, reason), ("MISSING", None))

    def test_a_target_with_no_digest_recorded_is_unverifiable(self) -> None:
        self.write(self.user_config / "settings.json", "{}\n")
        state, reason = classify_target(
            self.target(before_digest=None, after_digest=None), self.roots
        )
        self.assertEqual((state, reason), ("UNVERIFIABLE", "digest_not_recorded"))

    def test_a_tie_between_before_and_after_is_in_place_not_reverted(self) -> None:
        # `before_digest == after_digest` and the file still matches: `after`
        # is checked first, so the tie says the change is intact -- calling it
        # REVERTED would report a rollback nobody performed.
        target = self.write(self.user_config / "settings.json", "{}\n")
        digest = self.digest_of(target)
        state, reason = classify_target(
            self.target(before_digest=digest, after_digest=digest), self.roots
        )
        self.assertEqual((state, reason), ("IN_PLACE", None))

    def test_a_target_under_an_unresolvable_anchor_is_unverifiable(self) -> None:
        state, reason = classify_target(
            self.target(anchor="$SYSTEM_CONFIG/config.toml"), self.roots
        )
        self.assertEqual(state, "UNVERIFIABLE")
        self.assertIn(reason, PATH_SAFETY_REASONS)

    def test_an_unreadable_target_is_unverifiable_not_a_crash(self) -> None:
        target = self.write(self.user_config / "settings.json", "{}\n")
        recorded = self.digest_of(target)
        with mock.patch.object(
            drift_module,
            "file_digest",
            side_effect=OSError("Permission denied"),
        ):
            state, reason = classify_target(
                self.target(after_digest=recorded), self.roots
            )
        self.assertEqual((state, reason), ("UNVERIFIABLE", "unreadable"))

    def test_a_malformed_target_is_unverifiable_never_a_crash(self) -> None:
        for bad in (None, "text", 7, ["list"]):
            with self.subTest(bad=bad):
                state, reason = classify_target(bad, self.roots)
                self.assertEqual(state, "UNVERIFIABLE")
                self.assertIsNotNone(reason)


class DriftReportTestCase(DriftTestCase):
    """Fixtures for `drift_report`: a private adapter file and a ledger dict.

    The adapter is written to the temporary tree and named explicitly, so no
    test here depends on the bundled adapter files -- which another increment
    edits -- and no test reads this machine's real configuration.
    """

    def setUp(self) -> None:
        super().setUp()
        self.adapter_path = self.tmp / "adapter.json"
        self.adapter_path.write_text(
            json.dumps(self.adapter_document()), encoding="utf-8"
        )

    def adapter_document(self) -> dict:
        return {
            "adapter_version": 1,
            "client": "testclient",
            "expires_on": "2099-01-01",
            "anchors": {"$USER_CONFIG": [str(self.user_config)]},
            "probes": [
                {
                    "kind": "instruction-file",
                    "scope": "user",
                    "path": "$USER_CONFIG/CLAUDE.md",
                }
            ],
            "sensitive_key_patterns": [],
        }

    def ledger(
        self,
        items: list | None = None,
        targets: list | None = None,
        records: list | None = None,
    ) -> dict:
        document: dict = {
            "schema_version": "1.0",
            "client": "testclient",
            "baselines": [],
            "records": records if records is not None else [],
        }
        if items is not None:
            document["baselines"] = [
                {
                    "id": "BASE-2026-001",
                    "captured_on": "2026-07-30",
                    "client": "testclient",
                    "adapter_version": 1,
                    "items": items,
                }
            ]
        if targets is not None:
            document["records"].append(
                {"id": "RUN-2026-000", "type": "RUN", "targets": targets}
            )
        return document

    def report(self, ledger: dict):
        return drift_report(
            ledger, adapter=self.adapter_path, project=self.tmp, environ={}
        )


class DriftReportTests(DriftReportTestCase):
    def test_a_clean_environment_is_all_in_place_and_exit_zero(self) -> None:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        settings = self.write(self.user_config / "settings.json", "{}\n")
        ledger = self.ledger(
            items=[self.item(digest=self.digest_of(memory))],
            targets=[self.target(after_digest=self.digest_of(settings))],
        )
        report, messages, code = self.report(ledger)
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["IN_PLACE"], 2)
        self.assertEqual(report["summary"]["DRIFTED"], 0)

    def test_a_drifted_item_moves_the_exit_code_to_one(self) -> None:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        recorded = self.digest_of(memory)
        self.write(memory, "# memory, edited outside\n")
        report, messages, code = self.report(self.ledger(items=[self.item(digest=recorded)]))
        self.assertEqual(code, 1)
        self.assertEqual(report["summary"]["DRIFTED"], 1)

    def test_the_summary_always_carries_all_five_states(self) -> None:
        report, _, _ = self.report(self.ledger(items=[]))
        self.assertEqual(set(report["summary"]), DRIFT_STATES)

    def test_baseline_rows_carry_the_classification_beside_the_item(self) -> None:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        report, _, _ = self.report(
            self.ledger(items=[self.item(digest=self.digest_of(memory))])
        )
        self.assertEqual(len(report["baselines"]), 1)
        block = report["baselines"][0]
        self.assertEqual(block["id"], "BASE-2026-001")
        row = block["items"][0]
        self.assertEqual(row["anchor"], "$USER_CONFIG/CLAUDE.md")
        self.assertEqual(row["state"], "IN_PLACE")
        self.assertIsNone(row["reason"])

    def test_run_targets_are_classified_and_non_run_records_are_not(self) -> None:
        settings = self.write(self.user_config / "settings.json", "{}\n")
        ledger = self.ledger(
            targets=[self.target(after_digest=self.digest_of(settings))],
            records=[{"id": "MAT-2026-000", "type": "MATERIAL"}],
        )
        report, _, code = self.report(ledger)
        self.assertEqual([run["id"] for run in report["runs"]], ["RUN-2026-000"])
        self.assertEqual(report["runs"][0]["targets"][0]["state"], "IN_PLACE")
        self.assertEqual(code, 0)

    def test_a_malformed_baselines_entry_is_a_finding_naming_it_with_repr(
        self,
    ) -> None:
        ledger = self.ledger()
        ledger["baselines"] = ["bogus"]
        report, messages, code = self.report(ledger)
        self.assertEqual(code, 1)
        self.assertTrue(any("'bogus'" in message for message in messages))
        self.assertEqual(report["baselines"], [])

    def test_a_run_whose_targets_is_not_an_array_is_a_finding(self) -> None:
        ledger = self.ledger(
            records=[{"id": "RUN-2026-001", "type": "RUN", "targets": "nope"}]
        )
        report, messages, code = self.report(ledger)
        self.assertEqual(code, 1)
        self.assertTrue(any("'RUN-2026-001'" in message for message in messages))

    def test_an_unresolvable_anchor_is_a_reported_state_never_an_error(self) -> None:
        item = self.item(
            anchor="$SYSTEM_CONFIG/config.toml", digest="sha256:" + "a" * 64
        )
        report, _, code = self.report(self.ledger(items=[item]))
        self.assertEqual(code, 1)
        row = report["baselines"][0]["items"][0]
        self.assertEqual(row["state"], "UNVERIFIABLE")
        self.assertIn(row["reason"], PATH_SAFETY_REASONS)

    def test_every_classified_anchor_is_re_resolved_through_resolve_anchored(
        self,
    ) -> None:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        settings = self.write(self.user_config / "settings.json", "{}\n")
        ledger = self.ledger(
            items=[self.item(digest=self.digest_of(memory))],
            targets=[self.target(after_digest=self.digest_of(settings))],
        )
        with mock.patch.object(
            drift_module,
            "resolve_anchored",
            wraps=drift_module.resolve_anchored,
        ) as spy:
            self.report(ledger)
        stored = [call.args[0] for call in spy.call_args_list]
        self.assertIn("$USER_CONFIG/CLAUDE.md", stored)
        self.assertIn("$USER_CONFIG/settings.json", stored)


class ResolutionPurityTests(DriftReportTestCase):
    """Classification never depends on `resolution` data, in either direction.

    The adapter document is fed to `drift_report` through a patched
    `select_adapter_detail` rather than through a file, so the assertion holds
    whether or not adapter validation accepts the `resolution` field yet.
    Task 4's annotation is the one part of the report that legitimately reads
    the declaration, so the comparison strips each row's `resolution` key and
    requires everything that remains -- states, reasons, summary, messages,
    exit code -- to be byte-identical.
    """

    RESOLUTION = {
        "skill": {"mode": "override", "order": ["user", "project"]},
        "instruction-file": {"mode": "concatenate"},
    }

    def selection(self, document: dict) -> dict:
        return {
            "document": document,
            "notes": [],
            "client": document["client"],
            "path": self.adapter_path,
            "reason": "client_name",
            "origin": "bundled",
            "candidates": [],
        }

    def test_classification_is_identical_with_and_without_resolution_data(
        self,
    ) -> None:
        # One fixture holding every interesting classification at once: a
        # matched item, a drifted item, a recorded absence, and a run target.
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        skill = self.write(self.user_config / "skills" / "s" / "SKILL.md", "v1\n")
        recorded_skill = self.digest_of(skill)
        self.write(skill, "v2, drifted\n")
        settings = self.write(self.user_config / "settings.json", "{}\n")
        ledger = self.ledger(
            items=[
                self.item(digest=self.digest_of(memory)),
                self.item(
                    kind="skill",
                    name="SKILL.md",
                    anchor="$USER_CONFIG/skills/s/SKILL.md",
                    digest=recorded_skill,
                ),
                self.item(
                    state="not_present",
                    digest=None,
                    anchor="$USER_CONFIG/AGENTS.md",
                    name="AGENTS.md",
                ),
            ],
            targets=[self.target(after_digest=self.digest_of(settings))],
        )

        outcomes = []
        annotated = {**self.adapter_document(), "resolution": self.RESOLUTION}
        for document in (self.adapter_document(), annotated):
            with mock.patch.object(
                drift_module,
                "select_adapter_detail",
                return_value=self.selection(document),
            ):
                outcomes.append(
                    drift_report(ledger, project=self.tmp, environ={})
                )

        def classification_only(outcome):
            # A deep copy through JSON, then the one key Task 4 owns removed:
            # everything else -- states, reasons, summary, messages, code --
            # must be byte-identical whether or not `resolution` was declared.
            report, messages, code = outcome
            stripped = json.loads(json.dumps(report))
            for block in stripped["baselines"]:
                for row in block["items"]:
                    row.pop("resolution", None)
            return stripped, messages, code

        self.assertEqual(
            classification_only(outcomes[0]), classification_only(outcomes[1])
        )
        # And the fixture is not vacuous: it holds more than one state.
        report, _, code = outcomes[0]
        self.assertEqual(code, 1)
        self.assertEqual(report["summary"]["IN_PLACE"], 3)
        self.assertEqual(report["summary"]["DRIFTED"], 1)


class ResolutionAnnotationTests(DriftReportTestCase):
    """Task 4: annotations are context beside a state, never part of one.

    Documents are fed through a patched `select_adapter_detail`, the way
    `ResolutionPurityTests` feeds them, so what is asserted is what
    `drift_report` does with a declaration -- not whether the declaration
    survives adapter validation, which `test_adapters.py` owns.

    The `key-override` tests are the load-bearing ones: the mode exists so an
    adapter can declare that per-item shadowing is not a well-formed question,
    and the overreach worth guarding against is `drift` computing a winner for
    it anyway.
    """

    ORDER = ["project", "user"]

    def pair(self) -> list[dict]:
        """Two `mcp-server` items named alpha, at scopes project and user."""
        project_file = self.write(self.user_config / "project.json", "{}\n")
        user_file = self.write(self.user_config / "user.json", "{}\n")
        return [
            self.item(
                kind="mcp-server",
                name="alpha",
                anchor="$USER_CONFIG/project.json",
                digest=self.digest_of(project_file),
                attributes={"scope": "project"},
            ),
            self.item(
                kind="mcp-server",
                name="alpha",
                anchor="$USER_CONFIG/user.json",
                digest=self.digest_of(user_file),
                attributes={"scope": "user"},
            ),
        ]

    def annotated(self, items: list[dict], resolution: dict | None):
        """The classified rows for `items` under `resolution`, plus the code."""
        document = self.adapter_document()
        if resolution is not None:
            document = {**document, "resolution": resolution}
        selection = {
            "document": document,
            "notes": [],
            "client": document["client"],
            "path": self.adapter_path,
            "reason": "client_name",
            "origin": "bundled",
            "candidates": [],
        }
        with mock.patch.object(
            drift_module, "select_adapter_detail", return_value=selection
        ):
            report, _, code = drift_report(
                self.ledger(items=items), project=self.tmp, environ={}
            )
        return report["baselines"][0]["items"], code

    def by_scope(self, rows: list[dict]) -> dict:
        return {row["scope"]: row for row in rows}

    def test_override_marks_the_earliest_scope_effective(self) -> None:
        rows, _ = self.annotated(
            self.pair(), {"mcp-server": {"mode": "override", "order": self.ORDER}}
        )
        self.assertEqual(
            self.by_scope(rows)["project"]["resolution"],
            {"mode": "override", "order": self.ORDER, "effective": True},
        )

    def test_override_marks_the_later_scope_shadowed_by_the_winner(self) -> None:
        rows, _ = self.annotated(
            self.pair(), {"mcp-server": {"mode": "override", "order": self.ORDER}}
        )
        self.assertEqual(
            self.by_scope(rows)["user"]["resolution"],
            {"mode": "override", "order": self.ORDER, "shadowed_by": "project"},
        )

    def test_key_override_carries_the_mode_and_the_chain(self) -> None:
        rows, _ = self.annotated(
            self.pair(),
            {"mcp-server": {"mode": "key-override", "order": self.ORDER}},
        )
        for row in rows:
            with self.subTest(scope=row["scope"]):
                self.assertEqual(
                    row["resolution"],
                    {"mode": "key-override", "order": self.ORDER},
                )

    def test_key_override_claims_no_winner(self) -> None:
        # Layers resolve per key inside parsed documents; item granularity
        # cannot rank whole files, so neither item is `effective` and neither
        # is shadowed -- computing a winner here is exactly the overreach the
        # mode exists to prevent.
        rows, _ = self.annotated(
            self.pair(),
            {"mcp-server": {"mode": "key-override", "order": self.ORDER}},
        )
        for row in rows:
            with self.subTest(scope=row["scope"]):
                self.assertNotIn("effective", row["resolution"])
                self.assertNotIn("shadowed_by", row["resolution"])

    def test_merge_and_concatenate_carry_the_mode_and_nothing_else(self) -> None:
        for mode in ("merge", "concatenate"):
            with self.subTest(mode=mode):
                rows, _ = self.annotated(
                    self.pair(), {"mcp-server": {"mode": mode}}
                )
                for row in rows:
                    self.assertEqual(row["resolution"], {"mode": mode})

    def test_a_kind_with_no_declaration_is_undeclared(self) -> None:
        rows, _ = self.annotated(
            self.pair(), {"instruction-file": {"mode": "concatenate"}}
        )
        for row in rows:
            with self.subTest(scope=row["scope"]):
                self.assertEqual(row["resolution"], "undeclared")

    def test_an_adapter_without_resolution_leaves_every_kind_undeclared(
        self,
    ) -> None:
        rows, _ = self.annotated(self.pair(), None)
        for row in rows:
            self.assertEqual(row["resolution"], "undeclared")

    def test_a_shadowed_item_that_drifted_is_still_drifted(self) -> None:
        # Shadowing is a fact about today's layering; drift is a fact about
        # the bytes. The reader deciding what to do is entitled to both.
        items = self.pair()
        self.write(self.user_config / "user.json", "edited outside the tool\n")
        rows, code = self.annotated(
            items, {"mcp-server": {"mode": "override", "order": self.ORDER}}
        )
        shadowed = self.by_scope(rows)["user"]
        self.assertEqual(shadowed["state"], "DRIFTED")
        self.assertEqual(shadowed["resolution"]["shadowed_by"], "project")
        self.assertEqual(code, 1)

    def test_an_item_unique_to_one_scope_gets_no_shadowing_annotation(
        self,
    ) -> None:
        solo_file = self.write(self.user_config / "solo.json", "{}\n")
        rows, _ = self.annotated(
            [
                self.item(
                    kind="mcp-server",
                    name="solo",
                    anchor="$USER_CONFIG/solo.json",
                    digest=self.digest_of(solo_file),
                    attributes={"scope": "user"},
                )
            ],
            {"mcp-server": {"mode": "override", "order": self.ORDER}},
        )
        self.assertEqual(
            rows[0]["resolution"], {"mode": "override", "order": self.ORDER}
        )

    def test_run_targets_carry_no_resolution_annotation(self) -> None:
        # Spec 3.2 scopes annotations to baseline items: a run target has no
        # scope to rank and no (kind, name) group to shadow within.
        settings = self.write(self.user_config / "settings.json", "{}\n")
        document = {
            **self.adapter_document(),
            "resolution": {"mcp-server": {"mode": "override", "order": self.ORDER}},
        }
        selection = {
            "document": document,
            "notes": [],
            "client": document["client"],
            "path": self.adapter_path,
            "reason": "client_name",
            "origin": "bundled",
            "candidates": [],
        }
        ledger = self.ledger(
            targets=[self.target(after_digest=self.digest_of(settings))]
        )
        with mock.patch.object(
            drift_module, "select_adapter_detail", return_value=selection
        ):
            report, _, _ = drift_report(ledger, project=self.tmp, environ={})
        self.assertNotIn("resolution", report["runs"][0]["targets"][0])

    def test_a_malformed_kind_is_undeclared_never_a_crash(self) -> None:
        # A list is unhashable: looking it up in the declaration map must not
        # raise, and the honest annotation for it is `undeclared`.
        rows, _ = self.annotated(
            [self.item(kind=["not", "a", "kind"], attributes={"scope": "user"})],
            {"mcp-server": {"mode": "override", "order": self.ORDER}},
        )
        self.assertEqual(rows[0]["resolution"], "undeclared")


class DriftFindingsTests(DriftReportTestCase):
    """Task 5's two report-level findings: expiry and adapter-version drift.

    Both are findings and neither stops classification: an operator holding a
    stale comparison still holds a comparison, and the exit code is what says
    not to trust it unexamined.
    """

    def in_place_ledger(self) -> dict:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        return self.ledger(items=[self.item(digest=self.digest_of(memory))])

    def test_an_adapter_past_expires_on_is_a_finding_and_still_classifies(
        self,
    ) -> None:
        # The fixture adapter expires 2099-01-01; run the check "later".
        report, messages, code = drift_report(
            self.in_place_ledger(),
            adapter=self.adapter_path,
            project=self.tmp,
            environ={},
            today="2099-06-01",
        )
        self.assertEqual(code, 1)
        self.assertTrue(any("expired" in message for message in messages), messages)
        self.assertEqual(report["baselines"][0]["items"][0]["state"], "IN_PLACE")
        self.assertEqual(report["summary"]["IN_PLACE"], 1)

    def test_an_unexpired_adapter_is_no_finding(self) -> None:
        report, messages, code = drift_report(
            self.in_place_ledger(),
            adapter=self.adapter_path,
            project=self.tmp,
            environ={},
            today="2026-07-30",
        )
        self.assertEqual(code, 0)
        self.assertFalse(any("expired" in message for message in messages), messages)

    def test_an_adapter_version_mismatch_is_a_finding_naming_the_entry(
        self,
    ) -> None:
        ledger = self.in_place_ledger()
        ledger["baselines"][0]["adapter_version"] = 7
        report, messages, code = self.report(ledger)
        self.assertEqual(code, 1)
        mismatches = [
            message
            for message in messages
            if "adapter_version" in message and "'BASE-2026-001'" in message
        ]
        self.assertTrue(mismatches, messages)
        # Still classified: the finding is about the comparison's provenance,
        # not a refusal to compare.
        self.assertEqual(report["baselines"][0]["items"][0]["state"], "IN_PLACE")

    def test_a_matching_adapter_version_is_no_finding(self) -> None:
        # The other direction of the same rule: version 1 against version 1.
        _, messages, code = self.report(self.in_place_ledger())
        self.assertEqual(code, 0)
        self.assertFalse(
            any("adapter_version" in message for message in messages), messages
        )


class DriftCliTestCase(DriftReportTestCase):
    """A valid ledger on disk, and `dashboard.main` driven the way a shell would.

    Every CLI assertion goes through `main`, never through `drift_report`
    directly, for the reason `test_scan.py` records: argparse wiring that no
    test crosses is wiring that can be deleted without a test noticing.
    """

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def valid_ledger(
        self, items: list | None = None, client: str = "testclient"
    ) -> dict:
        """A ledger `validate_ledger` accepts whole, unlike `self.ledger()`.

        The command validates before classifying, so CLI fixtures carry every
        required field; the in-process fixtures stay minimal because
        `drift_report` takes documents, not files.
        """
        document: dict = {
            "schema_version": "1.0",
            "ledger_id": "l-drift-cli",
            "scope": "global",
            "language": "en",
            "client": client,
            "adapter_version": 1,
            "created": "2026-07-29",
            "updated": "2026-07-30",
            "id_authority": True,
            "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 2},
            "known_projects": [],
            "records": [],
            "baselines": [],
            "backlog": [],
        }
        if items is not None:
            document["baselines"] = [
                {
                    "id": "BASE-2026-001",
                    "captured_on": "2026-07-30",
                    "client": client,
                    "adapter_version": 1,
                    "items": items,
                }
            ]
        return document

    def write_ledger(self, document: dict) -> Path:
        path = self.tmp / "ledger.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def clean_ledger(self) -> Path:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        return self.write_ledger(
            self.valid_ledger(items=[self.item(digest=self.digest_of(memory))])
        )

    def drift_arguments(self, ledger: Path) -> list[str]:
        return [
            "drift",
            str(ledger),
            "--adapter",
            str(self.adapter_path),
            "--project",
            str(self.tmp),
        ]


class DriftCliTests(DriftCliTestCase):
    def test_the_subcommand_is_wired_into_main(self) -> None:
        code, stdout, _ = self.run_cli(*self.drift_arguments(self.clean_ledger()))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["summary"]["IN_PLACE"], 1)

    def test_the_subcommand_reaches_drift_report_through_main(self) -> None:
        arguments = self.drift_arguments(self.clean_ledger())
        with mock.patch.object(
            drift_module, "drift_report", wraps=drift_module.drift_report
        ) as spy:
            code, _, _ = self.run_cli(*arguments)
        self.assertEqual(code, 0)
        spy.assert_called_once()

    def test_stdout_holds_one_indented_json_report_and_nothing_else(self) -> None:
        _, stdout, stderr = self.run_cli(*self.drift_arguments(self.clean_ledger()))
        report = json.loads(stdout)
        self.assertEqual(stdout.rstrip("\n"), json.dumps(report, indent=2))
        self.assertEqual(set(report), {"baselines", "runs", "summary"})
        self.assertNotIn("selected adapter", stdout)
        self.assertIn("selected adapter", stderr)

    def test_a_non_in_place_state_moves_the_exit_code_to_one(self) -> None:
        ledger = self.clean_ledger()
        self.write(self.user_config / "CLAUDE.md", "# memory, edited outside\n")
        code, stdout, _ = self.run_cli(*self.drift_arguments(ledger))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["summary"]["DRIFTED"], 1)

    def test_an_adapter_version_mismatch_is_a_finding_through_the_cli(self) -> None:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        document = self.valid_ledger(items=[self.item(digest=self.digest_of(memory))])
        document["baselines"][0]["adapter_version"] = 7
        code, stdout, stderr = self.run_cli(
            *self.drift_arguments(self.write_ledger(document))
        )
        self.assertEqual(code, 1)
        self.assertIn("adapter_version", stderr)
        # Everything is IN_PLACE; the finding alone moved the code.
        self.assertEqual(json.loads(stdout)["summary"]["IN_PLACE"], 1)

    def test_an_expired_adapter_is_a_finding_through_the_cli(self) -> None:
        ledger = self.clean_ledger()
        expired = self.tmp / "expired-adapter.json"
        expired.write_text(
            json.dumps({**self.adapter_document(), "expires_on": "2000-01-01"}),
            encoding="utf-8",
        )
        code, stdout, stderr = self.run_cli(
            "drift", str(ledger), "--adapter", str(expired), "--project", str(self.tmp)
        )
        self.assertEqual(code, 1)
        self.assertIn("expired", stderr)
        self.assertNotIn("expired", stdout)
        self.assertEqual(json.loads(stdout)["summary"]["IN_PLACE"], 1)

    def test_a_missing_ledger_exits_two(self) -> None:
        missing = self.tmp / "no-such-ledger.json"
        code, stdout, stderr = self.run_cli(*self.drift_arguments(missing))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn(missing.name, stderr)

    def test_an_unparseable_ledger_exits_two(self) -> None:
        broken = self.tmp / "ledger.json"
        broken.write_text("{{{", encoding="utf-8")
        code, stdout, _ = self.run_cli(*self.drift_arguments(broken))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")

    def test_an_invalid_ledger_exits_two_with_findings_on_stderr(self) -> None:
        document = self.valid_ledger(items=[self.item()])
        del document["sequences"]
        code, stdout, stderr = self.run_cli(
            *self.drift_arguments(self.write_ledger(document))
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("sequences", stderr)

    def test_an_invalid_adapter_exits_two(self) -> None:
        ledger = self.clean_ledger()
        invalid = self.tmp / "invalid-adapter.json"
        invalid.write_text(json.dumps({"nope": True}), encoding="utf-8")
        code, stdout, _ = self.run_cli(
            "drift", str(ledger), "--adapter", str(invalid), "--project", str(self.tmp)
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")

    def test_selection_by_the_ledgers_client_reuses_the_shared_machinery(
        self,
    ) -> None:
        # No --adapter: the ledger's own client drives `select_adapter`, and a
        # client no adapter declares is the same tool error `scan` raises for
        # an unknown --client -- asserted through the CLI, naming the client.
        document = self.valid_ledger(
            items=[self.item()], client="no-such-client-drift"
        )
        code, stdout, stderr = self.run_cli(
            "drift", str(self.write_ledger(document)), "--project", str(self.tmp)
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("no-such-client-drift", stderr)

    def test_a_user_adapter_overrides_selection_on_the_same_terms_as_scan(
        self,
    ) -> None:
        # `--user-config` reaches the same candidate index `scan` reads: a
        # user adapter declaring the ledger's client is selected over the
        # bundled directory, which holds no `testclient`.
        local = (
            self.user_config
            / "agent-ingest-audit-optimize"
            / "adapters"
            / "local.json"
        )
        local.parent.mkdir(parents=True)
        local.write_text(json.dumps(self.adapter_document()), encoding="utf-8")
        code, _, stderr = self.run_cli(
            "drift",
            str(self.clean_ledger()),
            "--project",
            str(self.tmp),
            "--user-config",
            str(self.user_config),
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("local.json", stderr)

    def test_drift_is_re_exported_from_dashboard(self) -> None:
        self.assertIs(dashboard.drift_report, drift_module.drift_report)
        self.assertIs(dashboard.drift_command, drift_module.drift_command)


class DriftWritesNothingTests(DriftCliTestCase):
    """`drift` is read-only, guarded the way `ScanWritesNothingTests` guards
    `scan`: every write API patched to fail loudly, naming what was attempted,
    because a read-only tree is not portable to Windows."""

    def arm(self) -> None:
        real_path_open = Path.open
        real_open = builtins.open

        def guarded_path_open(this, mode="r", *args, **kwargs):
            if isinstance(mode, str) and set(mode) & set("wxa+"):
                raise AssertionError(f"drift opened {this} with mode {mode!r}")
            return real_path_open(this, mode, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            if isinstance(mode, str) and set(mode) & set("wxa+"):
                raise AssertionError(f"drift opened {file!r} with mode {mode!r}")
            return real_open(file, mode, *args, **kwargs)

        def refuse(name):
            def guard(this, *args, **kwargs):
                raise AssertionError(f"drift called Path.{name} on {this}")

            return guard

        patches = [
            mock.patch.object(Path, "open", guarded_path_open),
            mock.patch.object(Path, "write_text", refuse("write_text")),
            mock.patch.object(Path, "write_bytes", refuse("write_bytes")),
            mock.patch.object(Path, "mkdir", refuse("mkdir")),
            mock.patch.object(Path, "touch", refuse("touch")),
            mock.patch.object(builtins, "open", guarded_open),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_guard_is_actually_armed(self) -> None:
        """Without this, a broken patch makes the test below pass silently."""
        self.arm()
        with self.assertRaises(AssertionError):
            (self.tmp / "written.txt").write_text("no", encoding="utf-8")
        with self.assertRaises(AssertionError):
            (self.tmp / "made").mkdir()
        with self.assertRaises(AssertionError):
            open(self.tmp / "opened.txt", "w").close()

    def test_the_cli_writes_nothing_and_exits_zero_on_a_clean_fixture(self) -> None:
        arguments = self.drift_arguments(self.clean_ledger())
        self.arm()
        code, stdout, _ = self.run_cli(*arguments)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["summary"]["IN_PLACE"], 1)

    def test_the_direct_call_writes_nothing_either(self) -> None:
        ledger = self.clean_ledger()
        self.arm()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = drift_command(
                ledger=ledger, adapter=self.adapter_path, project=self.tmp
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["summary"]["IN_PLACE"], 1)


class ManagedLayerDriftTests(DriftReportTestCase):
    """0.5.0: the managed layer classifies and annotates like any other.

    Two things worth pinning separately: policy appearing where a baseline
    verified none is `DRIFTED`/`appeared` -- which is the signal the legacy
    Windows path exists to raise, since a file there is policy the platform
    stopped reading but an administrator may still believe in -- and
    `managed` outranking `user` in the declared precedence chain.
    """

    def adapter_document(self) -> dict:
        document = super().adapter_document()
        document["anchors"] = dict(
            document["anchors"], **{"$MANAGED_CONFIG": [str(self.user_config)]}
        )
        document["probes"] = list(document["probes"]) + [
            {
                "kind": "model-setting",
                "scope": "managed",
                "path": "$MANAGED_CONFIG/managed-settings.json",
            },
            {
                "kind": "model-setting",
                "scope": "user",
                "path": "$USER_CONFIG/managed-settings.json",
            },
        ]
        # Only the two scopes this fixture actually probes: the adapter
        # validator refuses an order naming a scope no probe of that kind
        # declares, which is the same check that caught a wrong `managed`
        # entry on the shipped mcp-server rule.
        document["resolution"] = {
            "model-setting": {"mode": "override", "order": ["managed", "user"]}
        }
        return document

    def managed_item(self, **overrides: object) -> dict:
        return self.item(
            kind="model-setting",
            name="managed-settings.json",
            anchor="$MANAGED_CONFIG/managed-settings.json",
            attributes={"scope": "managed"},
            **overrides,
        )

    def test_policy_appearing_where_none_was_recorded_is_drifted(self) -> None:
        self.write(self.user_config / "managed-settings.json", '{"model":"x"}\n')
        item = self.managed_item(state="not_present", digest=None)
        report, _messages, code = self.report(self.ledger(items=[item]))
        row = report["baselines"][0]["items"][0]
        self.assertEqual((row["state"], row["reason"]), ("DRIFTED", "appeared"))
        self.assertEqual(code, 1)

    def test_managed_outranks_user_in_the_declared_precedence(self) -> None:
        managed = self.write(self.user_config / "managed-settings.json", "{}\n")
        items = [
            self.managed_item(digest=self.digest_of(managed)),
            self.item(
                kind="model-setting",
                name="managed-settings.json",
                anchor="$USER_CONFIG/managed-settings.json",
                attributes={"scope": "user"},
                digest=self.digest_of(managed),
            ),
        ]
        report, _messages, _code = self.report(self.ledger(items=items))
        rows = {row["scope"]: row["resolution"] for row in report["baselines"][0]["items"]}
        self.assertEqual(rows["managed"].get("effective"), True)
        self.assertEqual(rows["user"].get("shadowed_by"), "managed")


class ResolvedPathHelperTests(DriftTestCase):
    """`resolved_path`: the row-level answer to "which file was classified".

    The helper exists so the reports can say where a classification looked
    without growing a second resolver: a resolvable anchor's path IS
    `resolve_anchored`'s answer, stringified, and everything that has no
    single local file -- a pattern, a refusal, a non-string -- is None,
    which is what makes "no path, no Open link" a property of the reports
    rather than of the page that renders them.
    """

    def test_a_resolvable_anchor_is_resolve_anchoreds_answer_stringified(
        self,
    ) -> None:
        self.assertEqual(
            resolved_path("$USER_CONFIG/CLAUDE.md", self.roots),
            str(resolve_anchored("$USER_CONFIG/CLAUDE.md", self.roots)),
        )

    def test_a_missing_file_still_has_the_path_it_would_occupy(self) -> None:
        """Resolution is textual for a file that is not there: MISSING rows
        carry a path too, because "which file is gone" is exactly what the
        reader of that row asks next."""
        self.assertEqual(
            resolved_path("$USER_CONFIG/never/written.json", self.roots),
            str(self.user_config / "never" / "written.json"),
        )

    def test_a_glob_pattern_is_none(self) -> None:
        self.assertIsNone(
            resolved_path("$USER_CONFIG/plugins/*/manifest.json", self.roots)
        )

    def test_a_refused_anchor_is_none_never_a_raise(self) -> None:
        for stored in (
            "$USER_CONFIG/../escape.json",
            "$UNKNOWN/settings.json",
            "/etc/passwd",
        ):
            with self.subTest(stored=stored):
                self.assertIsNone(resolved_path(stored, self.roots))

    def test_a_non_string_anchor_is_none(self) -> None:
        for stored in (None, 7, ["$USER_CONFIG/CLAUDE.md"]):
            with self.subTest(stored=stored):
                self.assertIsNone(resolved_path(stored, self.roots))

    def test_the_dashboard_module_re_exports_the_helper(self) -> None:
        self.assertIs(dashboard.resolved_path, resolved_path)


class ResolvedPathReportTests(DriftReportTestCase):
    """0.5.0: every classified row records the path it classified.

    Design spec section 12.2 offers Open for "the changed file", and the
    0.4.0 shell narrowed it to known projects because these reports carried
    anchors only. Each row's `path` closes that gap; it is None exactly
    where no single local file exists to open.
    """

    def test_a_baseline_row_carries_the_resolved_absolute_path(self) -> None:
        memory = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        report, _, _ = self.report(
            self.ledger(items=[self.item(digest=self.digest_of(memory))])
        )
        self.assertEqual(
            report["baselines"][0]["items"][0]["path"], str(memory.resolve())
        )

    def test_a_missing_items_row_still_carries_its_path(self) -> None:
        report, _, _ = self.report(
            self.ledger(items=[self.item(digest="sha256:" + "a" * 64)])
        )
        row = report["baselines"][0]["items"][0]
        self.assertEqual(row["state"], "MISSING")
        self.assertEqual(row["path"], str(self.user_config / "CLAUDE.md"))

    def test_a_run_target_row_carries_the_resolved_absolute_path(self) -> None:
        settings = self.write(self.user_config / "settings.json", "{}\n")
        report, _, _ = self.report(
            self.ledger(targets=[self.target(after_digest=self.digest_of(settings))])
        )
        self.assertEqual(
            report["runs"][0]["targets"][0]["path"], str(settings.resolve())
        )

    def test_an_unresolvable_anchors_row_has_a_null_path(self) -> None:
        item = self.item(
            anchor="$SYSTEM_CONFIG/config.toml", digest="sha256:" + "a" * 64
        )
        report, _, _ = self.report(self.ledger(items=[item]))
        self.assertIsNone(report["baselines"][0]["items"][0]["path"])

    def test_an_absent_glob_patterns_row_has_a_null_path(self) -> None:
        item = self.item(
            state="not_present",
            digest=None,
            anchor="$USER_CONFIG/plugins/*/manifest.json",
        )
        report, _, _ = self.report(self.ledger(items=[item]))
        self.assertIsNone(report["baselines"][0]["items"][0]["path"])

    def test_a_malformed_items_row_has_a_null_path(self) -> None:
        report, _, _ = self.report(self.ledger(items=[42]))
        row = report["baselines"][0]["items"][0]
        self.assertEqual(row["state"], "UNVERIFIABLE")
        self.assertIsNone(row["path"])


if __name__ == "__main__":
    unittest.main()
