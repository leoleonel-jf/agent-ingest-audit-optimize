"""Tests for `ledgerlib.compliance`: mappings, predicates, and the report.

The rule that governs this whole module is asserted before anything else:
**the tool never claims compliance.** It inventories evidence. Compliance is an
auditor's judgement about a whole system, and a tool that declared it would be
lying about its own competence -- the same error the SELF-REPORTED marker
already exists to prevent on the dashboard. `NoComplianceClaimTests` greps the
source and the rendered report for the claim word, so the discipline survives a
refactor that nobody re-reads this docstring during.

The second rule is structural: a mapping is content, and content never becomes
code. The predicate is a closed data structure read by our own evaluator; no
string from a mapping file is executed, `eval`'d, or interpolated into
anything. `PredicateSafetyTests` pins that with hostile mapping values.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "skills" / "agent-ingest-audit-optimize"
SCRIPT = BUNDLE / "assets" / "scripts" / "dashboard.py"
MAPPINGS = BUNDLE / "assets" / "compliance"
SOURCE = BUNDLE / "assets" / "scripts" / "ledgerlib" / "compliance.py"

SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib.compliance import (  # noqa: E402
    EVIDENCE_ABSENT,
    EVIDENCE_PARTIAL,
    EVIDENCE_PRESENT,
    EVIDENCE_STATES,
    compliance_report,
    evaluate_control,
    load_mapping,
)
from ledgerlib.errors import LedgerError  # noqa: E402


def run_record(identifier: str, **overrides: object) -> dict:
    base: dict = {
        "id": identifier,
        "type": "RUN",
        "title": "a run",
        "status": "VALIDATED",
        "classification": "ADOPT LOCALLY",
        "scope": "project",
        "created": "2026-07-30",
        "updated": "2026-07-30",
        "file": f"records/{identifier}.md",
        "links": {"materials": [], "runs": [], "adrs": []},
        "evidence": [],
        "proposal": "PROP-2026-000",
        "authorization": {"quote": "implemente a PROP-2026-000", "recorded_on": "2026-07-30"},
        "result": "VALIDATED",
        "targets": [],
        "backup": None,
        "rollback": {"tested": "NOT_TESTED"},
        "self_reported": ["targets"],
    }
    base.update(overrides)
    return base


def ledger(records: list | None = None, **overrides: object) -> dict:
    document: dict = {
        "schema_version": "1.0",
        "ledger_id": "l-compliance",
        "scope": "global",
        "language": "en",
        "client": "claude-code",
        "adapter_version": 1,
        "created": "2026-01-02",
        "updated": "2026-07-30",
        "id_authority": True,
        "sequences": {"MAT": 0, "PROP": 1, "RUN": 1, "ADR": 0, "BASE": 0},
        "known_projects": [],
        "records": records if records is not None else [run_record("RUN-2026-000")],
        "baselines": [],
        "backlog": [],
    }
    document.update(overrides)
    return document


class MappingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def mapping_document(self, **overrides: object) -> dict:
        document: dict = {
            "mapping_version": 1,
            "framework": "test-framework",
            "title": "A Test Framework",
            "expires_on": "2099-01-01",
            "source": "https://example.invalid/spec",
            "verified_on": "2026-07-31",
            "retention_days": 180,
            "controls": [
                {
                    "id": "c-1",
                    "title": "Events are recorded",
                    "requires": {"collection": "records", "min_count": 1},
                    "note": "Each dated record is one recorded event.",
                }
            ],
        }
        document.update(overrides)
        return document

    def write_mapping(self, **overrides: object) -> Path:
        path = self.tmp / "test-framework.json"
        path.write_text(
            json.dumps(self.mapping_document(**overrides)), encoding="utf-8"
        )
        return path


class MappingLoadingTests(MappingTestCase):
    def test_a_valid_mapping_loads(self) -> None:
        document = load_mapping(self.write_mapping(), today="2026-07-31")
        self.assertEqual(document["framework"], "test-framework")

    def test_an_expired_mapping_is_a_tool_error(self) -> None:
        """Regulatory text moves. A mapping past its verification window is
        worse than none, because it reads as current."""
        with self.assertRaises(LedgerError) as caught:
            load_mapping(
                self.write_mapping(expires_on="2026-01-01"), today="2026-07-31"
            )
        self.assertIn("expired", str(caught.exception).lower())

    def test_a_missing_field_is_a_tool_error(self) -> None:
        for field in ("source", "verified_on", "controls", "framework"):
            with self.subTest(field=field):
                document = self.mapping_document()
                del document[field]
                path = self.tmp / "broken.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(LedgerError):
                    load_mapping(path, today="2026-07-31")

    def test_an_unreadable_mapping_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            load_mapping(self.tmp / "absent.json", today="2026-07-31")

    def test_a_control_without_a_requires_block_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            load_mapping(
                self.write_mapping(controls=[{"id": "c-1", "title": "x"}]),
                today="2026-07-31",
            )


class PredicateTests(unittest.TestCase):
    def evaluate(self, requires: dict, document: dict | None = None) -> dict:
        control = {"id": "c-1", "title": "a control", "requires": requires}
        return evaluate_control(control, document if document is not None else ledger())

    def test_min_count_met_is_present(self) -> None:
        result = self.evaluate({"collection": "records", "min_count": 1})
        self.assertEqual(result["state"], EVIDENCE_PRESENT)

    def test_min_count_of_zero_items_is_absent(self) -> None:
        result = self.evaluate(
            {"collection": "records", "min_count": 1}, ledger(records=[])
        )
        self.assertEqual(result["state"], EVIDENCE_ABSENT)

    def test_some_but_not_enough_is_partial(self) -> None:
        result = self.evaluate({"collection": "records", "min_count": 3})
        self.assertEqual(result["state"], EVIDENCE_PARTIAL)

    def test_where_filters_before_counting(self) -> None:
        document = ledger(
            records=[
                run_record("RUN-2026-000"),
                dict(run_record("MAT-2026-000"), type="MATERIAL"),
            ]
        )
        result = self.evaluate(
            {"collection": "records", "where": {"type": "RUN"}, "min_count": 2},
            document,
        )
        self.assertEqual(result["state"], EVIDENCE_PARTIAL)
        self.assertEqual(result["matched"], 1)

    def test_every_satisfied_is_present(self) -> None:
        result = self.evaluate(
            {
                "collection": "records",
                "where": {"type": "RUN"},
                "every": {"field": "authorization.quote", "non_empty": True},
            }
        )
        self.assertEqual(result["state"], EVIDENCE_PRESENT)

    def test_every_violated_by_one_of_two_is_partial_and_names_it(self) -> None:
        """The case the whole feature exists for: a run with no recorded
        authorization is a missing human-oversight artifact, and the report
        must say WHICH run."""
        document = ledger(
            records=[
                run_record("RUN-2026-000"),
                run_record("RUN-2026-001", authorization={"quote": "", "recorded_on": "x"}),
            ]
        )
        result = self.evaluate(
            {
                "collection": "records",
                "where": {"type": "RUN"},
                "every": {"field": "authorization.quote", "non_empty": True},
            },
            document,
        )
        self.assertEqual(result["state"], EVIDENCE_PARTIAL)
        self.assertEqual(result["failing"], ["RUN-2026-001"])

    def test_every_violated_by_all_is_absent(self) -> None:
        document = ledger(
            records=[run_record("RUN-2026-000", authorization={"quote": ""})]
        )
        result = self.evaluate(
            {
                "collection": "records",
                "where": {"type": "RUN"},
                "every": {"field": "authorization.quote", "non_empty": True},
            },
            document,
        )
        self.assertEqual(result["state"], EVIDENCE_ABSENT)

    def test_every_over_an_empty_set_is_absent_never_vacuously_present(self) -> None:
        """"All zero runs carry authorization" is true and worthless. A
        control with nothing to evidence is ABSENT, not satisfied."""
        result = self.evaluate(
            {
                "collection": "records",
                "where": {"type": "RUN"},
                "every": {"field": "authorization.quote", "non_empty": True},
            },
            ledger(records=[]),
        )
        self.assertEqual(result["state"], EVIDENCE_ABSENT)

    def test_a_dotted_field_path_walks_nested_objects(self) -> None:
        result = self.evaluate(
            {
                "collection": "records",
                "every": {"field": "rollback.tested", "non_empty": True},
            }
        )
        self.assertEqual(result["state"], EVIDENCE_PRESENT)

    def test_an_unknown_collection_is_absent_with_a_reason(self) -> None:
        result = self.evaluate({"collection": "nope", "min_count": 1})
        self.assertEqual(result["state"], EVIDENCE_ABSENT)
        self.assertEqual(result["reason"], "unknown_collection")

    def test_a_missing_field_never_raises(self) -> None:
        result = self.evaluate(
            {"collection": "records", "every": {"field": "a.b.c", "non_empty": True}}
        )
        self.assertEqual(result["state"], EVIDENCE_ABSENT)

    def test_a_malformed_collection_entry_never_raises(self) -> None:
        result = self.evaluate(
            {"collection": "records", "min_count": 1}, ledger(records=["nope", 7])
        )
        self.assertIn(result["state"], EVIDENCE_STATES)

    def test_every_emitted_state_is_in_the_closed_vocabulary(self) -> None:
        for requires in (
            {"collection": "records", "min_count": 1},
            {"collection": "records", "min_count": 99},
            {"collection": "nope"},
            {},
        ):
            with self.subTest(requires=requires):
                self.assertIn(self.evaluate(requires)["state"], EVIDENCE_STATES)


class PredicateSafetyTests(unittest.TestCase):
    """A mapping is content. Content never becomes code."""

    def test_hostile_strings_in_a_mapping_are_treated_as_data(self) -> None:
        for hostile in (
            "__import__('os').system('echo pwned')",
            "{{ 7*7 }}",
            "${jndi:ldap://x}",
            "'; DROP TABLE records; --",
        ):
            with self.subTest(hostile=hostile):
                control = {
                    "id": hostile,
                    "title": hostile,
                    "requires": {
                        "collection": hostile,
                        "where": {hostile: hostile},
                        "every": {"field": hostile, "non_empty": True},
                    },
                }
                result = evaluate_control(control, ledger())
                self.assertIn(result["state"], EVIDENCE_STATES)

    def test_the_evaluator_source_calls_no_dynamic_execution(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        for forbidden in ("eval(", "exec(", "__import__", "compile(", "subprocess"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class ShippedMappingTests(unittest.TestCase):
    def mappings(self) -> list[Path]:
        return sorted(MAPPINGS.glob("*.json"))

    def test_the_two_frameworks_ship(self) -> None:
        self.assertEqual(
            [path.stem for path in self.mappings()], ["eu-ai-act", "iso-42001"]
        )

    def test_every_shipped_mapping_loads(self) -> None:
        for path in self.mappings():
            with self.subTest(mapping=path.name):
                load_mapping(path, today="2026-07-31")

    def test_the_eu_ai_act_mapping_covers_the_four_articles(self) -> None:
        document = load_mapping(MAPPINGS / "eu-ai-act.json", today="2026-07-31")
        self.assertEqual(
            sorted(control["id"] for control in document["controls"]),
            ["art-11", "art-12", "art-13", "art-19"],
        )

    def test_the_iso_mapping_covers_the_four_controls(self) -> None:
        document = load_mapping(MAPPINGS / "iso-42001.json", today="2026-07-31")
        self.assertEqual(
            sorted(control["id"] for control in document["controls"]),
            ["A.6.2.6", "A.7.3", "A.8.1", "cl-8.4"],
        )

    def test_every_control_carries_a_source_and_a_note(self) -> None:
        """A control the reader cannot trace back to its text is one they
        cannot check."""
        for path in self.mappings():
            document = load_mapping(path, today="2026-07-31")
            self.assertTrue(document["source"].startswith("https://"))
            for control in document["controls"]:
                with self.subTest(mapping=path.name, control=control["id"]):
                    self.assertTrue(control.get("note"))


class ReportTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def report(self, document: dict | None = None, framework: str = "eu-ai-act"):
        return compliance_report(
            document if document is not None else ledger(),
            framework=framework,
            bundled=MAPPINGS,
            today="2026-07-31",
        )


class ReportTests(ReportTestCase):
    def test_the_report_names_the_framework_and_every_control(self) -> None:
        result, _messages, _code = self.report()
        self.assertEqual(result["framework"], "eu-ai-act")
        self.assertEqual(len(result["controls"]), 4)

    def test_a_run_without_authorization_is_absent_and_named(self) -> None:
        document = ledger(
            records=[run_record("RUN-2026-000", authorization={"quote": ""})]
        )
        result, _messages, code = self.report(document)
        art13 = [c for c in result["controls"] if c["id"] == "art-13"][0]
        self.assertEqual(art13["state"], EVIDENCE_ABSENT)
        self.assertEqual(code, 1)

    def test_a_complete_ledger_exits_zero(self) -> None:
        result, _messages, code = self.report()
        self.assertNotIn(
            EVIDENCE_ABSENT, [control["state"] for control in result["controls"]]
        )
        self.assertEqual(code, 0)

    def test_an_unknown_framework_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            self.report(framework="not-a-framework")

    def test_the_report_reports_retention_without_enforcing_it(self) -> None:
        result, _messages, _code = self.report()
        retention = result["retention"]
        self.assertEqual(retention["required_days"], 180)
        self.assertEqual(retention["oldest_record"], "2026-07-30")

    def test_the_caveat_rides_on_every_report(self) -> None:
        result, _messages, _code = self.report()
        self.assertIn("not", result["caveat"].lower())
        self.assertIn("auditor", result["caveat"].lower())


class NoComplianceClaimTests(ReportTestCase):
    """The rule that governs the increment, asserted mechanically."""

    def test_the_word_compliant_appears_nowhere_in_a_report(self) -> None:
        result, messages, _code = self.report()
        blob = json.dumps(result, ensure_ascii=False) + " ".join(messages)
        self.assertNotIn("compliant", blob.lower())

    def test_the_word_compliant_appears_in_no_shipped_mapping(self) -> None:
        for path in sorted(MAPPINGS.glob("*.json")):
            with self.subTest(mapping=path.name):
                self.assertNotIn(
                    "compliant", path.read_text(encoding="utf-8").lower()
                )

    def test_the_three_states_are_the_only_verdicts(self) -> None:
        self.assertEqual(
            EVIDENCE_STATES,
            frozenset({"EVIDENCE_PRESENT", "EVIDENCE_PARTIAL", "EVIDENCE_ABSENT"}),
        )

    def test_no_code_path_deletes_a_record(self) -> None:
        """Retention is reported, never applied. An audit tool that deleted
        records on its own would be a contradiction in terms."""
        source = SOURCE.read_text(encoding="utf-8")
        for forbidden in ("unlink", "rmtree", "os.remove", ".pop(", "del "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class ComplianceCliTests(ReportTestCase):
    def write_ledger(self, document: dict | None = None) -> Path:
        path = self.tmp / "ledger.json"
        path.write_text(
            json.dumps(document if document is not None else ledger(), indent=2),
            encoding="utf-8",
        )
        return path

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_the_report_goes_to_stdout_as_json_alone(self) -> None:
        path = self.write_ledger()
        code, out, _err = self.run_cli(
            "compliance", str(path), "--framework", "eu-ai-act"
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["framework"], "eu-ai-act")

    def test_an_unknown_framework_exits_two(self) -> None:
        path = self.write_ledger()
        code, _out, err = self.run_cli(
            "compliance", str(path), "--framework", "nope"
        )
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_a_missing_control_exits_one(self) -> None:
        path = self.write_ledger(
            ledger(records=[run_record("RUN-2026-000", authorization={"quote": ""})])
        )
        code, _out, _err = self.run_cli(
            "compliance", str(path), "--framework", "eu-ai-act"
        )
        self.assertEqual(code, 1)

    def test_out_writes_the_report_and_a_copy_of_each_cited_record(self) -> None:
        path = self.write_ledger()
        pack = self.tmp / "pack"
        code, _out, _err = self.run_cli(
            "compliance", str(path), "--framework", "eu-ai-act", "--out", str(pack)
        )
        self.assertEqual(code, 0)
        names = sorted(child.name for child in pack.iterdir())
        self.assertIn("report.json", names)
        self.assertIn("RUN-2026-000.json", names)
        self.assertIn("digests.json", names)

    def test_out_refuses_a_non_empty_directory_without_force(self) -> None:
        path = self.write_ledger()
        pack = self.tmp / "pack"
        pack.mkdir()
        (pack / "keepme.txt").write_text("mine\n", encoding="utf-8")
        code, _out, err = self.run_cli(
            "compliance", str(path), "--framework", "eu-ai-act", "--out", str(pack)
        )
        self.assertEqual(code, 2)
        self.assertIn("keepme.txt", (pack / "keepme.txt").name)
        self.assertTrue((pack / "keepme.txt").exists())
        self.assertIn("--force", err)

    def test_the_pack_records_a_digest_for_every_copied_file(self) -> None:
        path = self.write_ledger()
        pack = self.tmp / "pack"
        self.run_cli(
            "compliance", str(path), "--framework", "eu-ai-act", "--out", str(pack)
        )
        digests = json.loads((pack / "digests.json").read_text(encoding="utf-8"))
        copied = {
            child.name for child in pack.iterdir() if child.name != "digests.json"
        }
        self.assertEqual(set(digests), copied)
        for value in digests.values():
            self.assertTrue(value.startswith("sha256:"))

    def test_the_caveat_reaches_stderr_even_with_out(self) -> None:
        path = self.write_ledger()
        pack = self.tmp / "pack"
        _code, _out, err = self.run_cli(
            "compliance", str(path), "--framework", "eu-ai-act", "--out", str(pack)
        )
        self.assertIn("auditor", err.lower())


if __name__ == "__main__":
    unittest.main()
