from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "scripts"
    / "dashboard.py"
)
SCHEMA = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "schemas"
    / "ledger.schema.json"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


def _capture_verify(paths: list[Path]) -> tuple[int, str, str]:
    """Call verify() and capture stdout/stderr. Returns (exit_code, stdout, stderr)."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        exit_code = dashboard.verify(paths)
    return exit_code, stdout_buf.getvalue(), stderr_buf.getvalue()


def minimal_ledger() -> dict:
    return {
        "schema_version": "1.0",
        "ledger_id": "l-000000",
        "scope": "global",
        "language": "en",
        "client": "claude-code",
        "adapter_version": 1,
        "created": "2026-07-29",
        "updated": "2026-07-29",
        "id_authority": True,
        "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0},
        "known_projects": [],
        "records": [],
        "baselines": [],
        "backlog": [],
    }


def write_ledger(directory: Path, data: dict) -> Path:
    path = directory / "ledger.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class LedgerDocumentTests(unittest.TestCase):
    def test_minimal_ledger_has_no_findings(self) -> None:
        self.assertEqual(dashboard.validate_ledger(minimal_ledger(), source="test"), [])

    def test_missing_top_level_field_is_reported(self) -> None:
        data = minimal_ledger()
        del data["sequences"]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("sequences" in finding for finding in findings))

    def test_unknown_schema_version_is_reported(self) -> None:
        data = minimal_ledger()
        data["schema_version"] = "9.9"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("schema_version" in finding for finding in findings))

    def test_schema_required_matches_runtime_validator(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), dashboard.REQUIRED_LEDGER_FIELDS)

    def test_empty_ledger_id_is_reported(self) -> None:
        data = minimal_ledger()
        data["ledger_id"] = ""
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("ledger_id" in finding for finding in findings))

    def test_short_language_is_reported(self) -> None:
        data = minimal_ledger()
        data["language"] = "e"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("language" in finding for finding in findings))

    def test_empty_client_is_reported(self) -> None:
        data = minimal_ledger()
        data["client"] = ""
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("client" in finding for finding in findings))

    def test_non_integer_adapter_version_is_reported(self) -> None:
        data = minimal_ledger()
        data["adapter_version"] = "nope"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("adapter_version" in finding for finding in findings))

    def test_adapter_version_below_minimum_is_reported(self) -> None:
        data = minimal_ledger()
        data["adapter_version"] = 0
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("adapter_version" in finding for finding in findings))

    def test_boolean_adapter_version_is_reported(self) -> None:
        data = minimal_ledger()
        data["adapter_version"] = True
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("adapter_version" in finding for finding in findings))

    def test_malformed_created_date_is_reported(self) -> None:
        data = minimal_ledger()
        data["created"] = "not-a-date"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("created must match YYYY-MM-DD" in finding for finding in findings))

    def test_malformed_updated_date_is_reported(self) -> None:
        data = minimal_ledger()
        data["updated"] = "07/29/2026"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("updated must match YYYY-MM-DD" in finding for finding in findings))

    def test_unexpected_key_in_sequences_is_reported(self) -> None:
        data = minimal_ledger()
        data["sequences"]["FOO"] = 1
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("FOO" in finding for finding in findings))

    def test_unknown_top_level_field_is_reported(self) -> None:
        data = minimal_ledger()
        data["unexpected_field"] = "value"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("unexpected_field" in finding for finding in findings))

    def test_invalid_scope_is_reported(self) -> None:
        data = minimal_ledger()
        data["scope"] = "invalid"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("scope" in finding for finding in findings))

    def test_non_boolean_id_authority_is_reported(self) -> None:
        data = minimal_ledger()
        data["id_authority"] = "yes"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("id_authority" in finding for finding in findings))

    def test_non_object_sequences_is_reported(self) -> None:
        data = minimal_ledger()
        data["sequences"] = [0, 0, 0, 0, 0]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("sequences" in finding for finding in findings))

    def test_non_integer_sequence_value_is_reported(self) -> None:
        data = minimal_ledger()
        data["sequences"]["MAT"] = "not-an-int"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("sequences.MAT" in finding for finding in findings))

    def test_negative_sequence_value_is_reported(self) -> None:
        data = minimal_ledger()
        data["sequences"]["PROP"] = -1
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("sequences.PROP" in finding for finding in findings))

    def test_non_array_known_projects_is_reported(self) -> None:
        data = minimal_ledger()
        data["known_projects"] = "not-an-array"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("known_projects" in finding for finding in findings))

    def test_non_array_records_is_reported(self) -> None:
        data = minimal_ledger()
        data["records"] = "not-an-array"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("records" in finding for finding in findings))

    def test_non_array_baselines_is_reported(self) -> None:
        data = minimal_ledger()
        data["baselines"] = "not-an-array"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("baselines" in finding for finding in findings))

    def test_non_array_backlog_is_reported(self) -> None:
        data = minimal_ledger()
        data["backlog"] = "not-an-array"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("backlog" in finding for finding in findings))

    def test_project_ledger_with_id_authority_true_is_reported(self) -> None:
        data = minimal_ledger()
        data["scope"] = "project"
        data["id_authority"] = True
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("authority" in finding for finding in findings))

    def test_global_ledger_with_id_authority_false_is_reported(self) -> None:
        data = minimal_ledger()
        data["scope"] = "global"
        data["id_authority"] = False
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("authority" in finding for finding in findings))

    def test_valid_project_ledger_has_no_findings(self) -> None:
        data = minimal_ledger()
        data["scope"] = "project"
        data["id_authority"] = False
        findings = dashboard.validate_ledger(data, source="test")
        self.assertEqual(findings, [])

    def test_date_with_trailing_newline_is_reported(self) -> None:
        data = minimal_ledger()
        data["created"] = "2026-07-29\n"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("created" in finding for finding in findings))

    def test_missing_sequence_prefix_key_is_reported(self) -> None:
        data = minimal_ledger()
        del data["sequences"]["MAT"]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("MAT" in finding for finding in findings))

    def test_non_dict_element_in_records_is_reported(self) -> None:
        data = minimal_ledger()
        data["records"] = ["oops"]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(
            any("records[0]" in finding for finding in findings)
        )

    def test_non_dict_element_in_known_projects_is_reported(self) -> None:
        data = minimal_ledger()
        data["known_projects"] = [123]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(
            any("known_projects[0]" in finding for finding in findings)
        )

    def test_non_dict_element_in_baselines_is_reported(self) -> None:
        data = minimal_ledger()
        data["baselines"] = [True]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(
            any("baselines[0]" in finding for finding in findings)
        )

    def test_non_dict_element_in_backlog_is_reported(self) -> None:
        data = minimal_ledger()
        data["backlog"] = [None]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(
            any("backlog[0]" in finding for finding in findings)
        )

    def test_valid_empty_dicts_in_arrays_have_no_findings(self) -> None:
        # `records` carries its own schema (validate_record), and `backlog` /
        # `known_projects` now carry theirs too (validate_backlog_entry /
        # validate_known_project) — an empty dict is no longer a valid
        # element for any of them. Only `baselines` has no per-item schema
        # yet (a later task owns that), so an empty dict remains valid there.
        data = minimal_ledger()
        data["baselines"] = [{}]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertEqual(findings, [])

    def test_missing_required_and_unknown_field_reported(self) -> None:
        data = minimal_ledger()
        del data["records"]
        data["unexpected_field"] = "value"
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("records" in finding for finding in findings))
        self.assertTrue(any("unexpected_field" in finding for finding in findings))

    def test_integer_ledger_id_is_reported(self) -> None:
        data = minimal_ledger()
        data["ledger_id"] = 12345
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("ledger_id" in finding for finding in findings))

    def test_integer_language_is_reported(self) -> None:
        data = minimal_ledger()
        data["language"] = 42
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("language" in finding for finding in findings))

    def test_integer_client_is_reported(self) -> None:
        data = minimal_ledger()
        data["client"] = 999
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("client" in finding for finding in findings))

    def test_verify_returns_two_for_array_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            exit_code, stdout, stderr = _capture_verify([path])
            self.assertEqual(exit_code, 2)
            self.assertIn("JSON object", stderr)

    def test_verify_returns_two_for_string_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            path.write_text(json.dumps("nope"), encoding="utf-8")
            exit_code, stdout, stderr = _capture_verify([path])
            self.assertEqual(exit_code, 2)
            self.assertIn("JSON object", stderr)

    def test_verify_returns_zero_for_a_valid_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_ledger(Path(temp), minimal_ledger())
            exit_code, stdout, stderr = _capture_verify([path])
            self.assertEqual(exit_code, 0)
            self.assertIn("1 ledger(s) validated", stdout)

    def test_verify_returns_one_for_an_invalid_ledger(self) -> None:
        data = minimal_ledger()
        del data["records"]
        with tempfile.TemporaryDirectory() as temp:
            path = write_ledger(Path(temp), data)
            exit_code, stdout, stderr = _capture_verify([path])
            self.assertEqual(exit_code, 1)
            self.assertIn("records", stderr)
            self.assertIn("finding(s)", stderr)

    def test_verify_returns_two_for_unreadable_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            path.write_text("{not json", encoding="utf-8")
            exit_code, stdout, stderr = _capture_verify([path])
            self.assertEqual(exit_code, 2)
            self.assertIn("Unreadable ledger", stderr)

    def test_verify_returns_two_for_a_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            exit_code, stdout, stderr = _capture_verify([Path(temp) / "absent.json"])
            self.assertEqual(exit_code, 2)
            self.assertIn("absent.json", stderr)

    def test_verify_returns_two_for_a_directory_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            exit_code, stdout, stderr = _capture_verify([Path(temp)])
            self.assertEqual(exit_code, 2)
            self.assertTrue(stderr, "Directory path should produce error output")

    def test_verify_returns_two_for_deeply_nested_json(self) -> None:
        # json.loads on pathologically nested JSON raises RecursionError,
        # not one of the exception types load_json originally caught. That
        # must surface as exit code 2 (tool error), not a code 1 finding or
        # an uncaught traceback.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            depth = 100_000
            path.write_text(("[" * depth) + ("]" * depth), encoding="utf-8")
            exit_code, stdout, stderr = _capture_verify([path])
            self.assertEqual(exit_code, 2)

    def test_list_scope_produces_finding_not_crash(self) -> None:
        # scope is checked with a set-membership test; an unhashable value
        # (a list, straight from untrusted ledger content) must not raise.
        data = minimal_ledger()
        data["scope"] = []
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("invalid scope" in finding for finding in findings))

    def test_boolean_sequence_value_is_reported(self) -> None:
        data = minimal_ledger()
        data["sequences"]["MAT"] = True
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("sequences.MAT" in finding for finding in findings))


def minimal_record() -> dict:
    return {
        "id": "PROP-2026-000",
        "type": "PROPOSAL",
        "title": "Adopt a stricter permission rule",
        "status": "PROPOSED",
        "classification": "ADOPT GLOBALLY",
        "scope": "user-global",
        "created": "2026-07-29",
        "updated": "2026-07-29",
        "file": "records/PROP-2026-000.md",
        "links": {"materials": [], "runs": [], "adrs": []},
        "evidence": [
            {
                "source": "https://example.invalid/docs",
                "kind": "official-docs",
                "verified_on": "2026-07-20",
                "time_sensitive": False,
            }
        ],
    }


class RecordEntryTests(unittest.TestCase):
    def check(self, record: dict) -> list[str]:
        return dashboard.validate_record(record, 0, source="test")

    def test_minimal_record_has_no_findings(self) -> None:
        self.assertEqual(self.check(minimal_record()), [])

    def test_provisional_id_is_accepted(self) -> None:
        record = minimal_record()
        record["id"] = "PROP-2026-000-P"
        self.assertEqual(self.check(record), [])

    def test_non_boolean_pending_id_reconciliation_is_reported(self) -> None:
        record = minimal_record()
        record["pending_id_reconciliation"] = "not-a-boolean"
        self.assertTrue(
            any(
                "pending_id_reconciliation" in finding
                for finding in self.check(record)
            )
        )

    def test_boolean_pending_id_reconciliation_is_accepted(self) -> None:
        record = minimal_record()
        record["pending_id_reconciliation"] = True
        self.assertEqual(self.check(record), [])

    def test_malformed_id_is_reported(self) -> None:
        record = minimal_record()
        record["id"] = "PROP-26-0"
        self.assertTrue(any("records[0] has an invalid id:" in finding for finding in self.check(record)))

    def test_unknown_type_is_reported(self) -> None:
        record = minimal_record()
        record["type"] = "NOTE"
        self.assertTrue(
            any(
                "PROP-2026-000 has an invalid type" in finding
                for finding in self.check(record)
            )
        )

    def test_unknown_status_is_reported(self) -> None:
        record = minimal_record()
        record["status"] = "DONE"
        self.assertTrue(
            any(
                "PROP-2026-000 has an invalid status" in finding
                for finding in self.check(record)
            )
        )

    def test_unknown_classification_is_reported(self) -> None:
        record = minimal_record()
        record["classification"] = "ADOPT EVERYWHERE"
        self.assertTrue(
            any("has an invalid classification" in finding for finding in self.check(record))
        )

    def test_unknown_scope_is_reported(self) -> None:
        record = minimal_record()
        record["scope"] = "galaxy"
        self.assertTrue(
            any(
                "PROP-2026-000 has an invalid scope" in finding
                for finding in self.check(record)
            )
        )

    def test_empty_title_is_reported(self) -> None:
        record = minimal_record()
        record["title"] = ""
        self.assertTrue(
            any(
                "PROP-2026-000 title must be a non-empty string" in finding
                for finding in self.check(record)
            )
        )

    def test_empty_file_is_reported(self) -> None:
        record = minimal_record()
        record["file"] = "   "
        self.assertTrue(
            any(
                "PROP-2026-000 file must be a non-empty string" in finding
                for finding in self.check(record)
            )
        )

    def test_malformed_created_date_is_reported(self) -> None:
        record = minimal_record()
        record["created"] = "07/29/2026"
        self.assertTrue(any("created must match YYYY-MM-DD" in finding for finding in self.check(record)))

    def test_malformed_updated_date_is_reported(self) -> None:
        record = minimal_record()
        record["updated"] = "not-a-date"
        self.assertTrue(any("updated must match YYYY-MM-DD" in finding for finding in self.check(record)))

    def test_non_object_links_is_reported(self) -> None:
        record = minimal_record()
        record["links"] = ["not-an-object"]
        self.assertTrue(
            any(
                "PROP-2026-000 links must be an object" in finding
                for finding in self.check(record)
            )
        )

    def test_link_target_must_be_a_record_id(self) -> None:
        record = minimal_record()
        record["links"]["materials"] = ["not-an-id"]
        self.assertTrue(any("links.materials" in finding for finding in self.check(record)))

    def test_links_field_must_be_an_array(self) -> None:
        record = minimal_record()
        record["links"]["runs"] = "PROP-2026-000"
        self.assertTrue(
            any(
                "links.runs must be an array" in finding
                for finding in self.check(record)
            )
        )

    def test_materials_link_must_be_an_array(self) -> None:
        record = minimal_record()
        record["links"]["materials"] = "PROP-2026-000"
        self.assertTrue(
            any(
                "links.materials must be an array" in finding
                for finding in self.check(record)
            )
        )

    def test_runs_link_target_must_be_a_record_id(self) -> None:
        record = minimal_record()
        record["links"]["runs"] = ["not-an-id"]
        self.assertTrue(any("links.runs" in finding for finding in self.check(record)))

    def test_adrs_link_must_be_an_array(self) -> None:
        record = minimal_record()
        record["links"]["adrs"] = "ADR-2026-000"
        self.assertTrue(
            any(
                "links.adrs must be an array" in finding
                for finding in self.check(record)
            )
        )

    def test_adrs_link_target_must_be_a_record_id(self) -> None:
        record = minimal_record()
        record["links"]["adrs"] = ["not-an-id"]
        self.assertTrue(any("links.adrs" in finding for finding in self.check(record)))

    def test_non_array_evidence_is_reported(self) -> None:
        record = minimal_record()
        record["evidence"] = {"source": "x"}
        self.assertTrue(
            any(
                "PROP-2026-000 evidence must be an array" in finding
                for finding in self.check(record)
            )
        )

    def test_non_object_evidence_item_is_reported(self) -> None:
        record = minimal_record()
        record["evidence"] = ["not-an-object"]
        self.assertTrue(
            any("evidence[0] must be an object" in finding for finding in self.check(record))
        )

    def test_evidence_item_missing_fields_is_reported(self) -> None:
        record = minimal_record()
        del record["evidence"][0]["kind"]
        self.assertTrue(
            any("evidence[0] missing fields" in finding for finding in self.check(record))
        )

    def test_non_boolean_time_sensitive_is_reported(self) -> None:
        record = minimal_record()
        record["evidence"][0]["time_sensitive"] = "yes"
        self.assertTrue(
            any(
                "evidence[0] time_sensitive must be a boolean" in finding
                for finding in self.check(record)
            )
        )

    def test_time_sensitive_evidence_requires_expiry(self) -> None:
        record = minimal_record()
        record["evidence"][0]["time_sensitive"] = True
        self.assertTrue(any("expires_on" in finding for finding in self.check(record)))

    def test_time_sensitive_evidence_with_expiry_is_accepted(self) -> None:
        record = minimal_record()
        record["evidence"][0]["time_sensitive"] = True
        record["evidence"][0]["expires_on"] = "2026-10-20"
        self.assertEqual(self.check(record), [])

    def test_non_string_expires_on_is_reported(self) -> None:
        record = minimal_record()
        record["evidence"][0]["time_sensitive"] = True
        record["evidence"][0]["expires_on"] = 20261020
        self.assertTrue(any("expires_on" in finding for finding in self.check(record)))

    def test_whitespace_only_expires_on_is_reported(self) -> None:
        record = minimal_record()
        record["evidence"][0]["time_sensitive"] = True
        record["evidence"][0]["expires_on"] = "   "
        self.assertTrue(any("expires_on" in finding for finding in self.check(record)))

    def test_missing_record_field_is_reported(self) -> None:
        record = minimal_record()
        del record["title"]
        self.assertTrue(
            any(
                "missing fields" in finding and "'title'" in finding
                for finding in self.check(record)
            )
        )

    def test_non_dict_record_returns_defensive_finding(self) -> None:
        findings = dashboard.validate_record("not-a-record", 0, source="test")
        self.assertEqual(findings, ["test: records[0] must be an object"])

    def test_list_type_produces_finding_not_crash(self) -> None:
        # type/status/classification/scope are each checked with a set-
        # membership test; an unhashable value (a list) must not raise.
        record = minimal_record()
        record["type"] = []
        self.assertTrue(any("invalid type" in finding for finding in self.check(record)))

    def test_list_status_produces_finding_not_crash(self) -> None:
        record = minimal_record()
        record["status"] = []
        self.assertTrue(any("invalid status" in finding for finding in self.check(record)))

    def test_list_classification_produces_finding_not_crash(self) -> None:
        record = minimal_record()
        record["classification"] = []
        self.assertTrue(
            any("invalid classification" in finding for finding in self.check(record))
        )

    def test_list_scope_produces_finding_not_crash(self) -> None:
        record = minimal_record()
        record["scope"] = []
        self.assertTrue(any("invalid scope" in finding for finding in self.check(record)))

    def test_records_are_validated_through_the_ledger(self) -> None:
        data = minimal_ledger()
        broken = minimal_record()
        broken["type"] = "NOTE"
        data["records"] = [broken]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("type" in finding for finding in findings))


class RecordSchemaAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.record_schema = schema["properties"]["records"]["items"]

    def test_schema_record_required_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["required"]), dashboard.REQUIRED_RECORD_FIELDS
        )

    def test_schema_record_type_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["properties"]["type"]["enum"]), dashboard.RECORD_TYPES
        )

    def test_schema_record_status_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["properties"]["status"]["enum"]),
            dashboard.RECORD_STATUSES,
        )

    def test_schema_record_classification_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["properties"]["classification"]["enum"]),
            dashboard.CLASSIFICATIONS,
        )

    def test_schema_record_scope_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["properties"]["scope"]["enum"]),
            dashboard.RECORD_SCOPES,
        )

    def test_schema_evidence_required_matches_runtime_validator(self) -> None:
        evidence_schema = self.record_schema["properties"]["evidence"]["items"]
        self.assertEqual(set(evidence_schema["required"]), dashboard.EVIDENCE_FIELDS)


def minimal_run() -> dict:
    record = minimal_record()
    record.update(
        {
            "id": "RUN-2026-000",
            "type": "RUN",
            "status": "VALIDATED",
            "classification": "ADOPT GLOBALLY",
            "file": "records/RUN-2026-000.md",
            "proposal": "PROP-2026-000",
            "authorization": {
                "quote": "Implement proposal PROP-2026-000",
                "recorded_on": "2026-07-29",
            },
            "result": "VALIDATED",
            "targets": [
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "kind": "json-key",
                    "key": "permissions.allow",
                    "before_digest": "sha256:" + "0" * 64,
                    "after_digest": "sha256:" + "1" * 64,
                    "reversible": True,
                    "residual_effect": None,
                }
            ],
            "backup": {
                "path": "backups/RUN-2026-000/",
                "digest": "sha256:" + "2" * 64,
                "verified": True,
            },
            "rollback": {
                "file": "records/RUN-2026-000.rollback.md",
                "tested": "NOT_TESTED",
            },
            "self_reported": ["tests"],
        }
    )
    return record


class RunEntryTests(unittest.TestCase):
    def check(self, record: dict) -> list[str]:
        return dashboard.validate_record(record, 0, source="test")

    def test_minimal_run_has_no_findings(self) -> None:
        self.assertEqual(self.check(minimal_run()), [])

    def test_run_requires_a_proposal_reference(self) -> None:
        record = minimal_run()
        del record["proposal"]
        self.assertTrue(any("proposal" in finding for finding in self.check(record)))

    def test_authorization_quote_must_be_present(self) -> None:
        record = minimal_run()
        record["authorization"]["quote"] = "   "
        self.assertTrue(any("quote" in finding for finding in self.check(record)))

    def test_target_digest_must_be_sha256(self) -> None:
        record = minimal_run()
        record["targets"][0]["after_digest"] = "md5:abc"
        self.assertTrue(any("digest" in finding for finding in self.check(record)))

    def test_irreversible_target_requires_a_residual_effect(self) -> None:
        record = minimal_run()
        record["targets"][0]["reversible"] = False
        record["targets"][0]["residual_effect"] = None
        self.assertTrue(
            any("residual_effect" in finding for finding in self.check(record))
        )

    def test_unknown_rollback_test_state_is_reported(self) -> None:
        record = minimal_run()
        record["rollback"]["tested"] = "MAYBE"
        self.assertTrue(any("tested" in finding for finding in self.check(record)))

    def test_self_reported_must_be_a_list_of_strings(self) -> None:
        record = minimal_run()
        record["self_reported"] = "tests"
        self.assertTrue(
            any("self_reported" in finding for finding in self.check(record))
        )

    def test_non_run_records_do_not_require_run_fields(self) -> None:
        self.assertEqual(self.check(minimal_record()), [])

    def test_malformed_proposal_reference_is_reported(self) -> None:
        record = minimal_run()
        record["proposal"] = "PROP-26-0"
        self.assertTrue(
            any("invalid proposal reference" in finding for finding in self.check(record))
        )

    def test_authorization_must_be_an_object(self) -> None:
        record = minimal_run()
        record["authorization"] = "not-an-object"
        self.assertTrue(
            any(
                "authorization must be an object" in finding
                for finding in self.check(record)
            )
        )

    def test_authorization_requires_recorded_on(self) -> None:
        record = minimal_run()
        del record["authorization"]["recorded_on"]
        self.assertTrue(any("recorded_on" in finding for finding in self.check(record)))

    def test_authorization_recorded_on_must_be_a_string(self) -> None:
        record = minimal_run()
        record["authorization"]["recorded_on"] = True
        self.assertTrue(any("recorded_on" in finding for finding in self.check(record)))

    def test_authorization_recorded_on_must_match_date_format(self) -> None:
        record = minimal_run()
        record["authorization"]["recorded_on"] = "07/29/2026"
        self.assertTrue(any("recorded_on" in finding for finding in self.check(record)))

    def test_non_run_record_with_run_only_field_produces_no_finding(self) -> None:
        record = minimal_record()
        record["backup"] = "not-an-object"
        self.assertEqual(dashboard.validate_record(record, 0, source="test"), [])

    def test_invalid_result_is_reported(self) -> None:
        record = minimal_run()
        record["result"] = "MAYBE"
        self.assertTrue(any("invalid result" in finding for finding in self.check(record)))

    def test_empty_targets_array_is_reported(self) -> None:
        record = minimal_run()
        record["targets"] = []
        self.assertTrue(
            any(
                "targets must be a non-empty array" in finding
                for finding in self.check(record)
            )
        )

    def test_non_object_target_is_reported(self) -> None:
        record = minimal_run()
        record["targets"][0] = "not-an-object"
        self.assertTrue(any("targets[0]" in finding for finding in self.check(record)))

    def test_target_missing_fields_is_reported(self) -> None:
        record = minimal_run()
        del record["targets"][0]["anchor"]
        self.assertTrue(
            any("targets[0] missing fields" in finding for finding in self.check(record))
        )

    def test_before_digest_must_be_sha256(self) -> None:
        record = minimal_run()
        record["targets"][0]["before_digest"] = "md5:abc"
        self.assertTrue(
            any("before_digest" in finding for finding in self.check(record))
        )

    def test_null_digests_are_accepted(self) -> None:
        record = minimal_run()
        record["targets"][0]["before_digest"] = None
        record["targets"][0]["after_digest"] = None
        self.assertEqual(self.check(record), [])

    def test_reversible_must_be_a_boolean(self) -> None:
        record = minimal_run()
        record["targets"][0]["reversible"] = "yes"
        self.assertTrue(
            any(
                "reversible must be a boolean" in finding
                for finding in self.check(record)
            )
        )

    def test_irreversible_target_with_residual_effect_is_accepted(self) -> None:
        record = minimal_run()
        record["targets"][0]["reversible"] = False
        record["targets"][0]["residual_effect"] = "permission entry remains until reviewed"
        self.assertEqual(self.check(record), [])

    def test_backup_must_be_an_object_or_null(self) -> None:
        record = minimal_run()
        record["backup"] = "not-an-object"
        self.assertTrue(
            any(
                "backup must be an object or null" in finding
                for finding in self.check(record)
            )
        )

    def test_null_backup_is_accepted(self) -> None:
        record = minimal_run()
        record["backup"] = None
        self.assertEqual(self.check(record), [])

    def test_backup_digest_must_be_sha256(self) -> None:
        record = minimal_run()
        record["backup"]["digest"] = "md5:abc"
        self.assertTrue(
            any("backup digest" in finding for finding in self.check(record))
        )

    def test_backup_verified_must_be_a_boolean(self) -> None:
        record = minimal_run()
        record["backup"]["verified"] = "yes"
        self.assertTrue(
            any(
                "backup verified must be a boolean" in finding
                for finding in self.check(record)
            )
        )

    def test_rollback_must_be_an_object(self) -> None:
        record = minimal_run()
        record["rollback"] = "not-an-object"
        self.assertTrue(
            any(
                "rollback must be an object" in finding for finding in self.check(record)
            )
        )

    def test_self_reported_item_must_be_a_string(self) -> None:
        record = minimal_run()
        record["self_reported"] = [123]
        self.assertTrue(
            any("self_reported" in finding for finding in self.check(record))
        )

    def test_list_result_produces_finding_not_crash(self) -> None:
        # result is checked with a set-membership test; an unhashable value
        # (a list) must not raise.
        record = minimal_run()
        record["result"] = []
        self.assertTrue(any("invalid result" in finding for finding in self.check(record)))

    def test_list_rollback_tested_produces_finding_not_crash(self) -> None:
        # rollback.tested is checked with a set-membership test; an
        # unhashable value (a list) must not raise.
        record = minimal_run()
        record["rollback"]["tested"] = []
        self.assertTrue(
            any(
                "rollback tested must be one of" in finding
                for finding in self.check(record)
            )
        )


class RunSchemaAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.record_schema = schema["properties"]["records"]["items"]

    def test_schema_run_required_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["then"]["required"]),
            dashboard.REQUIRED_RUN_FIELDS,
        )

    def test_schema_run_result_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.record_schema["then"]["properties"]["result"]["enum"]),
            dashboard.RUN_RESULTS,
        )

    def test_schema_rollback_tested_enum_matches_runtime_validator(self) -> None:
        rollback_schema = self.record_schema["then"]["properties"]["rollback"]
        self.assertEqual(
            set(rollback_schema["properties"]["tested"]["enum"]),
            dashboard.ROLLBACK_TEST_STATES,
        )

    def test_schema_target_required_matches_runtime_validator(self) -> None:
        target_schema = self.record_schema["then"]["properties"]["targets"]["items"]
        self.assertEqual(
            set(target_schema["required"]), dashboard.REQUIRED_TARGET_FIELDS
        )

    def test_schema_proposal_pattern_matches_record_id_pattern(self) -> None:
        self.assertEqual(
            self.record_schema["then"]["properties"]["proposal"]["pattern"],
            dashboard.RECORD_ID.pattern,
        )

    def test_schema_digest_pattern_matches_runtime_validator(self) -> None:
        target_schema = self.record_schema["then"]["properties"]["targets"]["items"]
        for field in ("before_digest", "after_digest"):
            self.assertEqual(
                target_schema["properties"][field]["pattern"], dashboard.DIGEST.pattern
            )
        self.assertEqual(
            self.record_schema["then"]["properties"]["backup"]["properties"][
                "digest"
            ]["pattern"],
            dashboard.DIGEST.pattern,
        )

    def test_schema_recorded_on_pattern_matches_date_regex(self) -> None:
        authorization_schema = self.record_schema["then"]["properties"]["authorization"]
        self.assertEqual(
            authorization_schema["properties"]["recorded_on"]["pattern"],
            dashboard.DATE.pattern,
        )

    def test_schema_residual_effect_falsy_enum_matches_expected_literals(self) -> None:
        target_schema = self.record_schema["then"]["properties"]["targets"]["items"]
        enum = target_schema["then"]["not"]["properties"]["residual_effect"]["enum"]
        expected = [None, "", False, 0, [], {}]
        # Python treats 0 == False and 1 == True, so a naive set()/`in`
        # comparison would not notice e.g. a duplicated `false` standing in
        # for the missing `0`. Comparing JSON text (via json.dumps with
        # sort_keys) instead gives each literal a distinct representation
        # ("false" vs "0" vs "null" vs '""' vs "[]" vs "{}"), so a schema
        # edit that drops or duplicates one of the six literals is caught.
        actual_json = sorted(json.dumps(value, sort_keys=True) for value in enum)
        expected_json = sorted(json.dumps(value, sort_keys=True) for value in expected)
        self.assertEqual(actual_json, expected_json)


def minimal_backlog_entry() -> dict:
    return {
        "id": "PROP-2026-001",
        "classification": "NEEDS MORE EVIDENCE",
        "reason": "The vendor has published no stable interface yet.",
        "revisit_trigger": "The client documents a stable hook API",
        "revisit_after": None,
    }


def minimal_known_project() -> dict:
    return {
        "project_root": "/home/user/project",
        "ledger_path": "/home/user/project/.agent-audit/ledger.json",
        "last_seen": "2026-07-29",
        "last_digest": "sha256:" + "3" * 64,
        "status": "OK",
    }


class BacklogTests(unittest.TestCase):
    def check(self, entry: dict) -> list[str]:
        return dashboard.validate_backlog_entry(entry, 0, source="test")

    def test_minimal_backlog_entry_has_no_findings(self) -> None:
        self.assertEqual(self.check(minimal_backlog_entry()), [])

    def test_revisit_after_alone_is_sufficient(self) -> None:
        entry = minimal_backlog_entry()
        entry["revisit_trigger"] = None
        entry["revisit_after"] = "2026-10-01"
        self.assertEqual(self.check(entry), [])

    def test_entry_without_any_revisit_condition_is_reported(self) -> None:
        entry = minimal_backlog_entry()
        entry["revisit_trigger"] = None
        entry["revisit_after"] = None
        self.assertTrue(any("revisit" in finding for finding in self.check(entry)))

    def test_terminal_classification_may_not_enter_the_backlog(self) -> None:
        entry = minimal_backlog_entry()
        entry["classification"] = "ALREADY IMPLEMENTED"
        self.assertTrue(any("terminal" in finding for finding in self.check(entry)))

    def test_reason_must_be_present(self) -> None:
        entry = minimal_backlog_entry()
        entry["reason"] = ""
        self.assertTrue(any("reason" in finding for finding in self.check(entry)))

    def test_revisit_after_must_match_date_format(self) -> None:
        # Extends the brief: revisit_after is a date field like every other
        # date in this ledger, so a malformed (but truthy) value must be
        # reported even though it alone satisfies the "has a revisit
        # condition" check.
        entry = minimal_backlog_entry()
        entry["revisit_trigger"] = None
        entry["revisit_after"] = "10/01/2026"
        self.assertTrue(
            any(
                "revisit_after must be null or match YYYY-MM-DD" in finding
                for finding in self.check(entry)
            )
        )

    def test_valid_backlog_classification_is_accepted(self) -> None:
        entry = minimal_backlog_entry()
        entry["classification"] = "RISK EXCEEDS BENEFIT"
        self.assertEqual(self.check(entry), [])

    def test_non_backlog_non_terminal_classification_is_reported(self) -> None:
        entry = minimal_backlog_entry()
        entry["classification"] = "ADOPT GLOBALLY"
        self.assertTrue(
            any("invalid classification" in finding for finding in self.check(entry))
        )

    def test_malformed_backlog_id_is_reported(self) -> None:
        entry = minimal_backlog_entry()
        entry["id"] = "PROP-26-1"
        self.assertTrue(
            any("backlog[0] has an invalid id" in finding for finding in self.check(entry))
        )

    def test_missing_backlog_field_is_reported(self) -> None:
        entry = minimal_backlog_entry()
        del entry["reason"]
        self.assertTrue(
            any(
                "missing fields" in finding and "'reason'" in finding
                for finding in self.check(entry)
            )
        )

    def test_non_dict_backlog_entry_returns_defensive_finding(self) -> None:
        findings = dashboard.validate_backlog_entry("not-an-entry", 0, source="test")
        self.assertEqual(findings, ["test: backlog[0] must be an object"])

    def test_list_classification_produces_finding_not_crash(self) -> None:
        # classification is checked with two set-membership tests
        # (terminal, then backlog-eligible); an unhashable value (a list)
        # must not raise.
        entry = minimal_backlog_entry()
        entry["classification"] = []
        self.assertTrue(
            any("invalid classification" in finding for finding in self.check(entry))
        )

    def test_non_string_revisit_trigger_is_reported(self) -> None:
        entry = minimal_backlog_entry()
        entry["revisit_trigger"] = 5
        self.assertTrue(
            any(
                "revisit_trigger must be null or a string" in finding
                for finding in self.check(entry)
            )
        )

    def test_list_revisit_trigger_is_reported(self) -> None:
        entry = minimal_backlog_entry()
        entry["revisit_trigger"] = ["x"]
        self.assertTrue(
            any(
                "revisit_trigger must be null or a string" in finding
                for finding in self.check(entry)
            )
        )


class KnownProjectTests(unittest.TestCase):
    def check(self, entry: dict) -> list[str]:
        return dashboard.validate_known_project(entry, 0, source="test")

    def test_minimal_known_project_has_no_findings(self) -> None:
        self.assertEqual(self.check(minimal_known_project()), [])

    def test_unknown_status_is_reported(self) -> None:
        entry = minimal_known_project()
        entry["status"] = "GONE"
        self.assertTrue(any("status" in finding for finding in self.check(entry)))

    def test_digest_must_be_sha256(self) -> None:
        entry = minimal_known_project()
        entry["last_digest"] = "sha1:abc"
        self.assertTrue(any("last_digest" in finding for finding in self.check(entry)))

    def test_last_seen_must_match_date_format(self) -> None:
        # Extends the brief: last_seen is a date field like every other date
        # in this ledger (created/updated/verified_on/recorded_on), so it
        # must follow the same YYYY-MM-DD pattern rather than only being
        # checked for non-blankness.
        entry = minimal_known_project()
        entry["last_seen"] = "07/29/2026"
        self.assertTrue(
            any(
                "last_seen must match YYYY-MM-DD" in finding
                for finding in self.check(entry)
            )
        )

    def test_empty_project_root_is_reported(self) -> None:
        entry = minimal_known_project()
        entry["project_root"] = "   "
        self.assertTrue(any("project_root" in finding for finding in self.check(entry)))

    def test_empty_ledger_path_is_reported(self) -> None:
        entry = minimal_known_project()
        entry["ledger_path"] = ""
        self.assertTrue(any("ledger_path" in finding for finding in self.check(entry)))

    def test_missing_known_project_field_is_reported(self) -> None:
        entry = minimal_known_project()
        del entry["status"]
        self.assertTrue(
            any(
                "missing fields" in finding and "'status'" in finding
                for finding in self.check(entry)
            )
        )

    def test_non_dict_known_project_returns_defensive_finding(self) -> None:
        findings = dashboard.validate_known_project(123, 0, source="test")
        self.assertEqual(findings, ["test: known_projects[0] must be an object"])

    def test_list_status_produces_finding_not_crash(self) -> None:
        # status is checked with a set-membership test; an unhashable value
        # (a list) must not raise.
        entry = minimal_known_project()
        entry["status"] = []
        self.assertTrue(any("invalid status" in finding for finding in self.check(entry)))

    def test_backlog_and_projects_are_validated_through_the_ledger(self) -> None:
        data = minimal_ledger()
        entry = minimal_backlog_entry()
        entry["revisit_trigger"] = None
        entry["revisit_after"] = None
        data["backlog"] = [entry]
        data["known_projects"] = [minimal_known_project()]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("revisit" in finding for finding in findings))


class BacklogSchemaAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.backlog_schema = schema["properties"]["backlog"]["items"]

    def test_schema_backlog_required_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.backlog_schema["required"]), dashboard.REQUIRED_BACKLOG_FIELDS
        )

    def test_schema_backlog_classification_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.backlog_schema["properties"]["classification"]["enum"]),
            dashboard.BACKLOG_CLASSIFICATIONS,
        )

    def test_schema_backlog_id_pattern_matches_record_id_pattern(self) -> None:
        self.assertEqual(
            self.backlog_schema["properties"]["id"]["pattern"],
            dashboard.RECORD_ID.pattern,
        )

    def test_schema_backlog_revisit_after_pattern_matches_date_regex(self) -> None:
        self.assertEqual(
            self.backlog_schema["properties"]["revisit_after"]["pattern"],
            dashboard.DATE.pattern,
        )

    def test_schema_backlog_revisit_falsy_enum_matches_expected_literals(self) -> None:
        # Same reasoning as the RUN target's residual_effect enum: compare
        # JSON text rather than a Python set/`in` check, since Python
        # conflates 0/False and 1/True.
        not_clause = self.backlog_schema["not"]["properties"]
        expected = [None, "", False, 0, [], {}]
        expected_json = sorted(json.dumps(value, sort_keys=True) for value in expected)
        for field in ("revisit_trigger", "revisit_after"):
            actual_json = sorted(
                json.dumps(value, sort_keys=True) for value in not_clause[field]["enum"]
            )
            self.assertEqual(actual_json, expected_json)


class KnownProjectSchemaAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.project_schema = schema["properties"]["known_projects"]["items"]

    def test_schema_known_project_required_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.project_schema["required"]), dashboard.REQUIRED_PROJECT_FIELDS
        )

    def test_schema_known_project_status_enum_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.project_schema["properties"]["status"]["enum"]),
            dashboard.PROJECT_STATUSES,
        )

    def test_schema_known_project_last_digest_pattern_matches_runtime_validator(self) -> None:
        self.assertEqual(
            self.project_schema["properties"]["last_digest"]["pattern"],
            dashboard.DIGEST.pattern,
        )

    def test_schema_known_project_last_seen_pattern_matches_date_regex(self) -> None:
        self.assertEqual(
            self.project_schema["properties"]["last_seen"]["pattern"],
            dashboard.DATE.pattern,
        )


class CrossLedgerIntegrityTests(unittest.TestCase):
    def project_ledger(self) -> dict:
        data = minimal_ledger()
        data["scope"] = "project"
        data["id_authority"] = False
        return data

    def test_duplicate_id_across_ledgers_is_reported(self) -> None:
        first = self.project_ledger()
        second = self.project_ledger()
        first["records"] = [minimal_record()]
        second["records"] = [minimal_record()]
        findings = dashboard.validate_collection(
            [("first", first), ("second", second)]
        )
        self.assertTrue(any("duplicate" in finding.lower() for finding in findings))

    def test_duplicate_id_within_one_ledger_is_reported(self) -> None:
        data = minimal_ledger()
        data["records"] = [minimal_record(), minimal_record()]
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(any("duplicate" in finding.lower() for finding in findings))

    def test_sequence_must_cover_the_highest_allocated_id(self) -> None:
        data = minimal_ledger()
        data["records"] = [minimal_record()]
        data["sequences"]["PROP"] = 0
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(any("sequences.PROP" in finding for finding in findings))

    def test_sequence_drift_finding_names_the_offending_record_not_the_last_one(
        self,
    ) -> None:
        # The record that actually sets the PROP high-water mark is first in
        # the array; a different-prefix record (whose own sequence is not
        # drifted) is last. Before the fix, the finding named whatever
        # `identifier` happened to hold when the `for record in records`
        # loop exited -- the *last* record processed, regardless of which
        # prefix's high-water mark triggered the drift.
        data = minimal_ledger()
        prop_record = minimal_record()
        prop_record["id"] = "PROP-2026-005"
        mat_record = minimal_record()
        mat_record["id"] = "MAT-2026-000"
        mat_record["type"] = "MATERIAL"
        data["records"] = [prop_record, mat_record]
        data["sequences"]["PROP"] = 0
        data["sequences"]["MAT"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(
            any("PROP-2026-005" in finding for finding in findings),
            f"expected a finding naming PROP-2026-005, got: {findings}",
        )
        self.assertFalse(
            any("MAT-2026-000" in finding for finding in findings),
            f"MAT-2026-000 must not be named in any finding, got: {findings}",
        )

    def test_matching_sequence_is_accepted(self) -> None:
        data = minimal_ledger()
        data["records"] = [minimal_record()]
        data["sequences"]["PROP"] = 1
        self.assertEqual(dashboard.validate_collection([("only", data)]), [])

    def test_provisional_id_requires_the_reconciliation_flag(self) -> None:
        data = self.project_ledger()
        record = minimal_record()
        record["id"] = "PROP-2026-000-P"
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(any("reconcil" in finding for finding in findings))

    def test_flagged_provisional_id_is_accepted(self) -> None:
        data = self.project_ledger()
        record = minimal_record()
        record["id"] = "PROP-2026-000-P"
        record["pending_id_reconciliation"] = True
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        self.assertEqual(dashboard.validate_collection([("only", data)]), [])

    def test_dangling_link_is_reported(self) -> None:
        data = minimal_ledger()
        data["records"] = [minimal_record()]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])
        data["records"][0]["links"]["runs"] = ["RUN-2026-009"]
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(any("RUN-2026-009" in finding for finding in findings))

    def test_dangling_link_finding_escapes_untrusted_content(self) -> None:
        # The link target (and, in principle, the record id) come straight
        # from ledger content, which is attacker-influenced by design. An
        # ANSI escape sequence in a dangling link target must not survive
        # raw into the printed finding.
        data = minimal_ledger()
        record = minimal_record()
        record["links"]["runs"] = ["\x1b[2J\x1b[3mRUN-2026-009"]
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(any("RUN-2026-009" in finding for finding in findings))
        self.assertFalse(any("\x1b" in finding for finding in findings))

    def test_more_than_one_id_authority_is_reported(self) -> None:
        findings = dashboard.validate_collection(
            [("a", minimal_ledger()), ("b", minimal_ledger())]
        )
        self.assertTrue(any("authority" in finding for finding in findings))

    def test_verify_reports_cross_ledger_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first_dir = root / "one"
            second_dir = root / "two"
            first_dir.mkdir()
            second_dir.mkdir()
            first = self.project_ledger()
            second = self.project_ledger()
            first["records"] = [minimal_record()]
            second["records"] = [minimal_record()]
            first["sequences"]["PROP"] = 1
            second["sequences"]["PROP"] = 1
            paths = [
                write_ledger(first_dir, first),
                write_ledger(second_dir, second),
            ]
            exit_code, stdout, stderr = _capture_verify(paths)
            self.assertEqual(exit_code, 1)
            self.assertIn("duplicate", stderr.lower())

    def test_stale_last_digest_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project.json"
            project.write_text(json.dumps(self.project_ledger()), encoding="utf-8")
            global_data = minimal_ledger()
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
            global_data = minimal_ledger()
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
            global_data = minimal_ledger()
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

    def test_verify_matches_relative_invocation_against_absolute_ledger_path(
        self,
    ) -> None:
        # verify() itself must exercise the digest wiring end to end: it
        # populates `digests`, passes it into validate_collection, and
        # registers each path under two keys (the path as given, and its
        # resolved form) so a ledger's stored absolute ledger_path still
        # matches an invocation that names the same file differently. Here
        # the project ledger is invoked via a relative path while the
        # global ledger's known_projects[0] records it by absolute path --
        # the match can only happen through the `path.resolve()` key.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_dir = root / "project"
            project_dir.mkdir()
            project_data = self.project_ledger()
            project_data["records"] = [minimal_record()]
            project_data["sequences"]["PROP"] = 1
            project_path = write_ledger(project_dir, project_data)

            global_data = minimal_ledger()
            global_data["known_projects"] = [
                {
                    "project_root": str(project_dir),
                    "ledger_path": str(project_path.resolve()),
                    "last_seen": "2026-07-30",
                    # Wrong but well-formed: the real digest is whatever
                    # write_ledger actually produced, never all-nines.
                    "last_digest": "sha256:" + "9" * 64,
                    "status": "OK",
                }
            ]
            global_path = write_ledger(root, global_data)

            relative_project_path = Path(os.path.relpath(project_path, Path.cwd()))
            exit_code, stdout, stderr = _capture_verify(
                [relative_project_path, global_path]
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("last_digest", stderr)


class CrossLedgerDefensiveParsingTests(unittest.TestCase):
    # validate_collection walks ids, sequence numbers, and link targets from
    # untrusted content; every value it indexes, splits, or int-converts
    # must be guarded rather than trusted to have the expected shape.

    def test_non_dict_document_is_ignored_not_crashed(self) -> None:
        findings = dashboard.validate_collection([("bad", "not-a-ledger")])
        self.assertEqual(findings, [])

    def test_non_list_records_field_is_ignored_not_crashed(self) -> None:
        data = minimal_ledger()
        data["records"] = "not-a-list"
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_dict_record_element_is_ignored_not_crashed(self) -> None:
        data = minimal_ledger()
        data["records"] = ["not-a-record"]
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_string_record_id_is_ignored_not_crashed(self) -> None:
        data = minimal_ledger()
        record = minimal_record()
        record["id"] = ["PROP-2026-000"]
        data["records"] = [record]
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_dict_links_field_is_ignored_not_crashed(self) -> None:
        data = minimal_ledger()
        record = minimal_record()
        record["links"] = ["not-a-dict"]
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_list_link_target_field_is_ignored_not_crashed(self) -> None:
        # A malformed links.runs of type int is not just "no findings": if it
        # were iterated naively (e.g. `value or []`), an int would raise
        # TypeError. A string would silently iterate its characters. Both
        # must be treated as "no targets" rather than crashing or reporting
        # bogus single-character dangling links.
        data = minimal_ledger()
        record = minimal_record()
        record["links"]["runs"] = 42
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_string_link_target_field_is_not_iterated_by_character(self) -> None:
        data = minimal_ledger()
        record = minimal_record()
        record["links"]["runs"] = "RUN-2026-000"
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_dict_sequences_field_is_ignored_not_crashed(self) -> None:
        data = minimal_ledger()
        data["records"] = [minimal_record()]
        data["sequences"] = "not-a-dict"
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_integer_sequence_value_is_ignored_not_crashed(self) -> None:
        data = minimal_ledger()
        data["records"] = [minimal_record()]
        data["sequences"]["PROP"] = "not-an-int"
        findings = dashboard.validate_collection([("only", data)])
        self.assertEqual(findings, [])

    def test_non_boolean_id_authority_is_ignored_not_crashed(self) -> None:
        # A second document gives this test teeth: a truthy-but-not-`True`
        # id_authority sits alongside one genuine authority. If the
        # authority check ever regressed from `is True` to a bare
        # truthiness test, the non-boolean value would be counted as a
        # second authority and this would (wrongly) produce a finding.
        first = minimal_ledger()
        first["id_authority"] = ["not-a-boolean"]
        second = minimal_ledger()
        second["scope"] = "project"
        second["id_authority"] = True
        findings = dashboard.validate_collection([("first", first), ("second", second)])
        self.assertEqual(findings, [])


class PartialSetHonestyTests(unittest.TestCase):
    def project_ledger(self) -> dict:
        data = minimal_ledger()
        data["scope"] = "project"
        data["id_authority"] = False
        return data

    def test_incomplete_collection_suppresses_dangling_link_check(self) -> None:
        data = minimal_ledger()
        record = minimal_record()
        record["links"]["runs"] = ["RUN-2026-009"]
        data["records"] = [record]
        data["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection([("only", data)], complete=False)
        self.assertEqual(findings, [])

    def test_incomplete_collection_still_reports_duplicate_ids(self) -> None:
        first = self.project_ledger()
        second = self.project_ledger()
        first["records"] = [minimal_record()]
        second["records"] = [minimal_record()]
        first["sequences"]["PROP"] = 1
        second["sequences"]["PROP"] = 1
        findings = dashboard.validate_collection(
            [("first", first), ("second", second)], complete=False
        )
        self.assertTrue(any("duplicate" in finding.lower() for finding in findings))

    def test_verify_partial_set_suppresses_dangling_link_finding(self) -> None:
        # A link target declared only in an unreachable ledger must not be
        # reported as dangling: that finding would be an artifact of the
        # incomplete set, not a real integrity problem.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            present_dir = root / "present"
            present_dir.mkdir()
            data = self.project_ledger()
            record = minimal_record()
            record["links"]["runs"] = ["RUN-2026-009"]
            data["records"] = [record]
            data["sequences"]["PROP"] = 1
            present_path = write_ledger(present_dir, data)
            missing_path = root / "missing" / "ledger.json"
            exit_code, stdout, stderr = _capture_verify([present_path, missing_path])
            self.assertEqual(exit_code, 2)
            self.assertNotIn("unknown record", stderr)

    def test_verify_prints_findings_from_readable_ledgers_before_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good_dir = root / "good"
            good_dir.mkdir()
            broken_data = minimal_ledger()
            del broken_data["records"]
            good_path = write_ledger(good_dir, broken_data)
            missing_path = root / "missing" / "ledger.json"
            exit_code, stdout, stderr = _capture_verify([good_path, missing_path])
            self.assertEqual(exit_code, 2)
            self.assertIn("missing fields", stderr)

    def test_verify_continues_past_an_early_unreadable_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing_path = root / "missing.json"
            good_dir = root / "good"
            good_dir.mkdir()
            broken_data = minimal_ledger()
            del broken_data["records"]
            good_path = write_ledger(good_dir, broken_data)
            exit_code, stdout, stderr = _capture_verify([missing_path, good_path])
            self.assertEqual(exit_code, 2)
            self.assertIn("missing fields", stderr)


class MainDispatchTests(unittest.TestCase):
    def test_main_dispatches_to_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_ledger(Path(temp), minimal_ledger())
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exit_code = dashboard.main(["verify", str(path)])
            self.assertEqual(exit_code, 0)
            self.assertIn("1 ledger(s) validated", stdout_buf.getvalue())


class ProvisionalIdSchemaAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.record_schema = schema["properties"]["records"]["items"]

    def test_schema_declares_pending_id_reconciliation_property(self) -> None:
        self.assertIn(
            "pending_id_reconciliation", self.record_schema["properties"]
        )

    def test_schema_provisional_id_pattern_matches_runtime_validator(self) -> None:
        clause = next(
            item
            for item in self.record_schema["allOf"]
            if "pending_id_reconciliation"
            in item.get("then", {}).get("required", [])
        )
        self.assertEqual(
            clause["if"]["properties"]["id"]["pattern"],
            dashboard.PROVISIONAL_ID.pattern,
        )

    def test_schema_requires_pending_id_reconciliation_for_provisional_ids(self) -> None:
        clause = next(
            item
            for item in self.record_schema["allOf"]
            if "pending_id_reconciliation"
            in item.get("then", {}).get("required", [])
        )
        self.assertEqual(clause["then"]["required"], ["pending_id_reconciliation"])
        self.assertIs(
            clause["then"]["properties"]["pending_id_reconciliation"]["const"], True
        )


REFERENCE = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "references"
    / "LEDGER.md"
)


class ReferenceTests(unittest.TestCase):
    # Each test below is driven from the validator's own constant sets
    # rather than a hardcoded list, so adding a value to dashboard.py
    # without documenting it in LEDGER.md fails here.

    def _assert_vocabulary_documented(
        self, vocabulary: set[str], reference_text: str, vocab_name: str
    ) -> None:
        """Assert that all vocabulary members appear in backtick-delimited format.

        Requires each vocabulary member to appear in backticks. Prevents false matches
        from bare prose (like 'project' in 'project root') and prevents drift between
        the validator constants and their documentation.
        """
        # Require all vocabulary values to appear in backtick-delimited format
        # This anchors the test on specific formatting, not bare prose mentions
        for value in vocabulary:
            backtick_form = f"`{value}`"
            self.assertIn(
                backtick_form,
                reference_text,
                f"Vocabulary member {value!r} not found in backtick-delimited "
                f"format in {vocab_name}. Add it to the documentation.",
            )

    def test_reference_documents_every_record_type(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.RECORD_TYPES, text, "RECORD_TYPES"
        )

    def test_reference_documents_every_record_status(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.RECORD_STATUSES, text, "RECORD_STATUSES"
        )

    def test_reference_documents_every_record_scope(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.RECORD_SCOPES, text, "RECORD_SCOPES"
        )

    def test_reference_documents_every_classification(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.CLASSIFICATIONS, text, "CLASSIFICATIONS"
        )

    def test_reference_documents_every_run_result(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.RUN_RESULTS, text, "RUN_RESULTS"
        )

    def test_reference_documents_every_rollback_test_state(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.ROLLBACK_TEST_STATES, text, "ROLLBACK_TEST_STATES"
        )

    def test_reference_documents_every_project_status(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self._assert_vocabulary_documented(
            dashboard.PROJECT_STATUSES, text, "PROJECT_STATUSES"
        )

    def test_reference_documents_the_verify_command(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        self.assertIn("dashboard.py verify", text)


SKILL = REPO_ROOT / "skills" / "agent-ingest-audit-optimize" / "SKILL.md"


class SkillDocumentTests(unittest.TestCase):
    def test_skill_links_to_the_ledger_reference(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("references/LEDGER.md", text)

    def test_skill_states_the_analysis_carve_out(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("never counts as implementing a proposal", text)

    def test_ledger_section_stays_within_the_context_budget(self) -> None:
        lines = SKILL.read_text(encoding="utf-8").splitlines()
        start = lines.index("## Keep the ledger")
        end = next(
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("## ")
        )
        self.assertLessEqual(end - start, 40)


PLATFORM = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "references"
    / "PLATFORM_ADAPTATION.md"
)


class DelegationPolicyTests(unittest.TestCase):
    def test_skill_states_the_delegation_rule(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Never delegate implementation", text)

    def test_skill_delegation_section_stays_small(self) -> None:
        lines = SKILL.read_text(encoding="utf-8").splitlines()
        start = lines.index("## Delegate to preserve context")
        end = next(
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("## ")
        )
        self.assertLessEqual(end - start, 14)

    def test_platform_reference_names_the_prohibitions(self) -> None:
        text = PLATFORM.read_text(encoding="utf-8")
        for phrase in (
            "single-writer sequence",
            "two authorized proposals",
            "authority to authorize",
            "Detect subagent support",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
