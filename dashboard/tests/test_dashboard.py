from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
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

# Loading `dashboard.py` above put the bundle's script directory on
# `sys.path`, so this resolves to the bundle's own copy. Imported here rather
# than reached through `dashboard`, which re-exports no adapter name: the
# documentation-agreement tests below compare `LEDGER.md` against the field
# sets the loader actually enforces.
from ledgerlib import adapters  # noqa: E402


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

    def test_empty_dict_in_baselines_is_reported(self) -> None:
        # `records`, `backlog`, `known_projects`, and now `baselines` all
        # carry their own field schema (validate_record /
        # validate_backlog_entry / validate_known_project /
        # validate_baseline) — an empty dict is a missing-fields finding for
        # every one of them; none of the four arrays accepts a bare `{}` any
        # longer.
        data = minimal_ledger()
        data["baselines"] = [{}]
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("baselines[0] missing fields" in finding for finding in findings))

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
            "self_reported": ["targets", "tests"],
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

    def test_run_must_name_targets_in_self_reported(self) -> None:
        record = minimal_run()
        record["self_reported"] = ["backup", "result"]
        findings = self.check(record)
        self.assertTrue(
            any(
                "self_reported" in finding and "targets" in finding
                for finding in findings
            )
        )

    def test_run_naming_targets_in_self_reported_is_accepted(self) -> None:
        record = minimal_run()
        record["self_reported"] = ["targets", "backup", "result"]
        findings = self.check(record)
        self.assertFalse(any("self_reported" in finding for finding in findings))

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

    def test_target_portable_absent_is_accepted(self) -> None:
        # portable is optional -- a RUN record written before this release
        # (including this repository's own) never carried it.
        record = minimal_run()
        self.assertNotIn("portable", record["targets"][0])
        self.assertEqual(self.check(record), [])

    def test_target_portable_non_boolean_is_reported(self) -> None:
        record = minimal_run()
        record["targets"][0]["portable"] = "yes"
        self.assertTrue(
            any("portable must be a boolean" in finding for finding in self.check(record))
        )

    def test_target_portable_boolean_is_accepted(self) -> None:
        record = minimal_run()
        record["targets"][0]["portable"] = False
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

    def test_schema_self_reported_contains_matches_runtime_validator(self) -> None:
        # There is no jsonschema library here (standard library only), so this
        # does not execute the schema's `contains` keyword directly. Instead
        # it reads the required value out of the schema and feeds it through
        # the real validate_run(), on both a record that satisfies it and one
        # that does not -- so a schema/runtime drift on the *value* (e.g. the
        # schema requiring "targets" while the runtime checks a different
        # string) is caught, not just a structural presence-of-key check.
        self_reported_schema = self.record_schema["then"]["properties"][
            "self_reported"
        ]
        required_value = self_reported_schema["contains"]["const"]

        satisfying = minimal_run()
        satisfying["self_reported"] = [required_value]
        self.assertEqual(
            dashboard.validate_run(satisfying, label="RUN-2026-000"), []
        )

        violating = minimal_run()
        violating["self_reported"] = ["something-else"]
        findings = dashboard.validate_run(violating, label="RUN-2026-000")
        self.assertTrue(any("self_reported" in finding for finding in findings))

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


def minimal_baseline_item() -> dict:
    return {
        "kind": "mcp-server",
        "name": "playwright",
        "anchor": "$USER_CONFIG/settings.json",
        "digest": "sha256:" + "4" * 64,
        "attributes": {"transport": "stdio"},
        "origin": "pre-existing",
        "state": "present",
    }


def minimal_baseline() -> dict:
    return {
        "id": "BASE-2026-000",
        "captured_on": "2026-07-29",
        "client": "claude-code",
        "adapter_version": 1,
        "items": [minimal_baseline_item()],
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


class BaselineEntryTests(unittest.TestCase):
    def check(self, entry: dict) -> list[str]:
        return dashboard.validate_baseline(entry, 0, source="test")

    def test_minimal_baseline_has_no_findings(self) -> None:
        self.assertEqual(self.check(minimal_baseline()), [])

    def test_non_dict_baseline_returns_defensive_finding(self) -> None:
        self.assertEqual(
            dashboard.validate_baseline(123, 0, source="test"),
            ["test: baselines[0] must be an object"],
        )

    def test_missing_baseline_field_is_reported(self) -> None:
        entry = minimal_baseline()
        del entry["client"]
        self.assertTrue(
            any(
                "missing fields" in finding and "'client'" in finding
                for finding in self.check(entry)
            )
        )

    def test_id_not_base_prefixed_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["id"] = "PROP-2026-000"
        self.assertTrue(any("invalid id" in finding for finding in self.check(entry)))

    def test_id_not_identifier_shaped_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["id"] = "BASE-26-0"
        self.assertTrue(any("invalid id" in finding for finding in self.check(entry)))

    def test_bad_captured_on_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["captured_on"] = "07/29/2026"
        self.assertTrue(
            any(
                "captured_on must match YYYY-MM-DD" in finding
                for finding in self.check(entry)
            )
        )

    def test_empty_client_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["client"] = "   "
        self.assertTrue(any("client" in finding for finding in self.check(entry)))

    def test_adapter_version_below_one_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["adapter_version"] = 0
        self.assertTrue(
            any("adapter_version" in finding for finding in self.check(entry))
        )

    def test_adapter_version_non_integer_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["adapter_version"] = "1"
        self.assertTrue(
            any("adapter_version" in finding for finding in self.check(entry))
        )

    def test_items_must_be_an_array(self) -> None:
        entry = minimal_baseline()
        entry["items"] = "not-a-list"
        self.assertTrue(
            any("items must be an array" in finding for finding in self.check(entry))
        )

    def test_non_dict_item_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"] = ["not-an-object"]
        self.assertTrue(
            any("items[0] must be an object" in finding for finding in self.check(entry))
        )

    def test_item_missing_fields_is_reported(self) -> None:
        entry = minimal_baseline()
        del entry["items"][0]["digest"]
        self.assertTrue(
            any(
                "items[0] missing fields" in finding and "'digest'" in finding
                for finding in self.check(entry)
            )
        )

    def test_item_kind_outside_enum_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["kind"] = "nonsense"
        self.assertTrue(
            any("invalid kind" in finding for finding in self.check(entry))
        )

    def test_item_empty_name_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["name"] = "   "
        self.assertTrue(any("name" in finding for finding in self.check(entry)))

    def test_item_empty_anchor_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["anchor"] = ""
        self.assertTrue(any("anchor" in finding for finding in self.check(entry)))

    def test_item_digest_neither_sha256_nor_null_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["digest"] = "md5:abc"
        self.assertTrue(
            any("digest must be a sha256 digest or null" in finding for finding in self.check(entry))
        )

    def test_item_null_digest_is_accepted(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["digest"] = None
        self.assertEqual(self.check(entry), [])

    def test_item_attributes_not_an_object_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["attributes"] = "not-an-object"
        self.assertTrue(
            any("attributes must be an object" in finding for finding in self.check(entry))
        )

    def test_item_origin_neither_pre_existing_nor_prop_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["origin"] = "nope"
        self.assertTrue(
            any("invalid origin" in finding for finding in self.check(entry))
        )

    def test_item_origin_wrong_prefix_identifier_is_reported(self) -> None:
        # An identifier-shaped origin is not automatically valid: only
        # pre-existing or a PROP- id counts.
        entry = minimal_baseline()
        entry["items"][0]["origin"] = "MAT-2026-000"
        self.assertTrue(
            any("invalid origin" in finding for finding in self.check(entry))
        )

    def test_item_origin_prop_identifier_is_accepted(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["origin"] = "PROP-2026-000"
        self.assertEqual(self.check(entry), [])

    def test_item_state_outside_enum_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["state"] = "matched"
        self.assertTrue(
            any("invalid state" in finding for finding in self.check(entry))
        )

    def test_item_not_present_state_is_accepted(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["state"] = "not_present"
        self.assertEqual(self.check(entry), [])

    def test_item_portable_absent_is_accepted(self) -> None:
        entry = minimal_baseline()
        self.assertNotIn("portable", entry["items"][0])
        self.assertEqual(self.check(entry), [])

    def test_item_portable_non_boolean_is_reported(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["portable"] = "yes"
        self.assertTrue(
            any("portable must be a boolean" in finding for finding in self.check(entry))
        )

    def test_item_portable_boolean_is_accepted(self) -> None:
        entry = minimal_baseline()
        entry["items"][0]["portable"] = False
        self.assertEqual(self.check(entry), [])

    def test_baselines_are_validated_through_the_ledger(self) -> None:
        data = minimal_ledger()
        entry = minimal_baseline()
        entry["items"][0]["kind"] = "nonsense"
        data["baselines"] = [entry]
        data["sequences"]["BASE"] = 1
        findings = dashboard.validate_ledger(data, source="test")
        self.assertTrue(any("invalid kind" in finding for finding in findings))


class BaselineSchemaAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.baseline_schema = schema["properties"]["baselines"]["items"]
        self.item_schema = self.baseline_schema["properties"]["items"]["items"]

    def test_schema_baseline_required_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.baseline_schema["required"]), dashboard.REQUIRED_BASELINE_FIELDS
        )

    def test_schema_baseline_item_required_matches_runtime_validator(self) -> None:
        self.assertEqual(
            set(self.item_schema["required"]), dashboard.REQUIRED_BASELINE_ITEM_FIELDS
        )

    def test_schema_baseline_item_kind_enum_matches_runtime_validator(self) -> None:
        schema_kinds = set(self.item_schema["properties"]["kind"]["enum"])
        self.assertEqual(schema_kinds, dashboard.BASELINE_ITEM_KINDS)
        # Drive the real validator with every value the schema declares, not
        # just compare the two sets as text: a well-formed item using each
        # schema-declared kind must not be rejected by the runtime validator.
        for kind in schema_kinds:
            item = minimal_baseline_item()
            item["kind"] = kind
            entry = minimal_baseline()
            entry["items"] = [item]
            findings = dashboard.validate_baseline(entry, 0, source="test")
            self.assertFalse(
                any("invalid kind" in finding for finding in findings),
                f"kind {kind!r} from the schema enum was rejected by the runtime validator",
            )

    def test_schema_baseline_item_state_enum_matches_runtime_validator(self) -> None:
        schema_states = set(self.item_schema["properties"]["state"]["enum"])
        self.assertEqual(schema_states, dashboard.BASELINE_ITEM_STATES)
        for state in schema_states:
            item = minimal_baseline_item()
            item["state"] = state
            entry = minimal_baseline()
            entry["items"] = [item]
            findings = dashboard.validate_baseline(entry, 0, source="test")
            self.assertFalse(
                any("invalid state" in finding for finding in findings),
                f"state {state!r} from the schema enum was rejected by the runtime validator",
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

    def test_baseline_id_above_sequence_is_reported(self) -> None:
        # A BASE identifier is just another identifier holder: sequences.BASE
        # must cover a baselines[] entry's id exactly as it covers a record's.
        data = minimal_ledger()
        baseline = minimal_baseline()
        baseline["id"] = "BASE-2026-004"
        data["baselines"] = [baseline]
        data["sequences"]["BASE"] = 4
        findings = dashboard.validate_collection([("only", data)])
        self.assertTrue(any("sequences.BASE" in finding for finding in findings))

    def test_baseline_id_within_sequence_is_accepted(self) -> None:
        data = minimal_ledger()
        baseline = minimal_baseline()
        baseline["id"] = "BASE-2026-004"
        data["baselines"] = [baseline]
        data["sequences"]["BASE"] = 5
        self.assertEqual(dashboard.validate_collection([("only", data)]), [])

    def test_authority_sequences_must_cover_a_siblings_baseline(self) -> None:
        authority = minimal_ledger()
        authority["sequences"]["BASE"] = 0
        project = self.project_ledger()
        baseline = minimal_baseline()
        baseline["id"] = "BASE-2026-000"
        project["baselines"] = [baseline]
        project["sequences"]["BASE"] = 1

        findings = dashboard.validate_collection(
            [("global.json", authority), ("project.json", project)]
        )

        self.assertTrue(
            any(
                "sequences.BASE" in finding and "global.json" in finding
                for finding in findings
            )
        )

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

    def test_backlog_id_referencing_no_record_is_reported(self) -> None:
        ledger = self.project_ledger()
        record = minimal_record()
        record["id"] = "MAT-2026-000"
        record["type"] = "MATERIAL"
        ledger["records"] = [record]
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
        record = minimal_record()
        record["id"] = "MAT-2026-000"
        record["type"] = "MATERIAL"
        ledger["records"] = [record]
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

    def test_authority_sequences_must_cover_a_sibling_ledgers_records(self) -> None:
        authority = minimal_ledger()
        authority["sequences"]["MAT"] = 0
        project = self.project_ledger()
        record = minimal_record()
        record["id"] = "MAT-2026-000"
        record["type"] = "MATERIAL"
        project["records"] = [record]
        project["sequences"]["MAT"] = 1

        findings = dashboard.validate_collection(
            [("global.json", authority), ("project.json", project)]
        )

        self.assertTrue(
            any("sequences.MAT" in finding and "global.json" in finding for finding in findings)
        )

    def test_a_project_ledger_is_not_responsible_for_a_siblings_records(self) -> None:
        authority = minimal_ledger()
        authority["sequences"]["MAT"] = 6
        first = self.project_ledger()
        first_record = minimal_record()
        first_record["id"] = "MAT-2026-005"
        first_record["type"] = "MATERIAL"
        first["records"] = [first_record]
        first["sequences"]["MAT"] = 6
        second = self.project_ledger()
        second_record = minimal_record()
        second_record["id"] = "MAT-2026-000"
        second_record["type"] = "MATERIAL"
        second["records"] = [second_record]
        second["sequences"]["MAT"] = 1

        findings = dashboard.validate_collection(
            [("global.json", authority), ("a.json", first), ("b.json", second)]
        )

        self.assertFalse(any("sequences" in finding for finding in findings))

    def test_authority_holding_the_highest_record_produces_one_finding_not_two(
        self,
    ) -> None:
        # Deleting `if holder == source: continue` from the authority check
        # would double-count this exact case: the per-document rule (the
        # first loop over `highest`) already reports a ledger's sequences
        # trailing its own highest record, and without the skip the
        # authority-scoped rule (the second loop over `spent`) reports the
        # same drift again under a second message, because here the
        # authority is also the ledger that holds the record.
        authority = minimal_ledger()
        record = minimal_record()
        record["id"] = "MAT-2026-005"
        record["type"] = "MATERIAL"
        authority["records"] = [record]
        authority["sequences"]["MAT"] = 0

        findings = dashboard.validate_collection([("global.json", authority)])

        matching = [finding for finding in findings if "MAT-2026-005" in finding]
        self.assertEqual(
            len(matching), 1, f"expected exactly one finding, got: {matching}"
        )

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

            try:
                relative_project_path = Path(
                    os.path.relpath(project_path, Path.cwd())
                )
            except ValueError:
                # On Windows, os.path.relpath raises ValueError when the two
                # paths are on different drives -- e.g. a checkout on C:\
                # with TEMP redirected to D:\. There is no relative path to
                # form in that case, so there is nothing this test can
                # exercise; skip rather than error.
                self.skipTest(
                    "no relative path exists between the checkout and TEMP "
                    "(different drives)"
                )
            exit_code, stdout, stderr = _capture_verify(
                [relative_project_path, global_path]
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("last_digest", stderr)

    def test_path_key_normalizes_separator_and_case(self) -> None:
        # _path_key's normalization is what lets a stored ledger_path
        # compare equal to an invocation path that names the same file with
        # different slashes or case -- but that is only true on Windows.
        # os.path.normcase lowercases and turns "/" into "\\" there; on
        # POSIX, normcase is the identity function and the filesystem is
        # case-sensitive, so a differently-cased ledger_path names a
        # DIFFERENT file and correctly does not match. Each platform is
        # asserted on its own correct behavior below, rather than skipping
        # POSIX outright.
        #
        # Replacing _path_key's body with `return value` leaves every other
        # digest test in this class green, because each one passes
        # str(path) verbatim on both sides; none of them differs the two
        # strings in spelling. This one does: the stored ledger_path uses
        # forward slashes and upper case, the invocation path is exactly
        # what write_ledger returned. On Windows, breaking _path_key this
        # way makes the assertions below fail (ablated: confirmed on this
        # machine). On POSIX, normcase is already the identity, so this
        # particular breakage does not change the (already-no-match)
        # outcome there -- POSIX's assertions are checking that
        # _path_key stays a no-op for case, not exercising this specific
        # regression.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sub = root / "sub"
            sub.mkdir()
            project_data = self.project_ledger()
            project_path = write_ledger(sub, project_data)

            mixed_path = str(project_path).replace(os.sep, "/").upper()
            self.assertNotEqual(mixed_path, str(project_path))

            global_data = minimal_ledger()
            global_data["known_projects"] = [
                {
                    "project_root": str(sub),
                    "ledger_path": mixed_path,
                    "last_seen": "2026-07-30",
                    # Wrong but well-formed, same as the other digest tests
                    # in this class: the point is that the comparison
                    # happens at all, which a mismatch finding proves.
                    "last_digest": "sha256:" + "9" * 64,
                    "status": "OK",
                }
            ]
            global_path = write_ledger(root, global_data)

            exit_code, stdout, stderr = _capture_verify([project_path, global_path])

            if os.name == "nt":
                # Same file, different spelling: normcase + normpath fold
                # them together, so the comparison happens and the
                # deliberately-wrong last_digest is caught.
                self.assertEqual(exit_code, 1)
                self.assertIn("last_digest", stderr)
            else:
                # Different case means a different file on a case-sensitive
                # filesystem. ledger_path names something that was never
                # passed on the command line, so it is not comparable --
                # "not checked", never "wrongly matched" -- and verify must
                # report a clean run.
                self.assertEqual(exit_code, 0)
                self.assertNotIn("last_digest", stderr)

    def test_verify_matches_relative_ledger_path_against_relative_invocation(
        self,
    ) -> None:
        # Deleting `digests[_path_key(source)] = digest` from verify()
        # leaves every existing digest test in this class green: they all
        # either use identical strings on both sides or depend on the
        # resolved-path key covered by
        # test_verify_matches_relative_invocation_against_absolute_ledger_path
        # above. Only the as-given key covers this case: a ledger_path
        # stored relative, matched by a relative invocation path, where the
        # resolved (absolute) key would never match the stored value.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_dir = root / "project"
            project_dir.mkdir()
            project_data = self.project_ledger()
            project_data["records"] = [minimal_record()]
            project_data["sequences"]["PROP"] = 1
            write_ledger(project_dir, project_data)

            relative_ledger_path = os.path.join("project", "ledger.json")
            global_data = minimal_ledger()
            # Matches the project ledger's PROP-2026-000 so the authority
            # sequence check stays quiet and stderr carries only the
            # last_digest finding this test is about.
            global_data["sequences"]["PROP"] = 1
            global_data["known_projects"] = [
                {
                    "project_root": str(project_dir),
                    "ledger_path": relative_ledger_path,
                    "last_seen": "2026-07-30",
                    "last_digest": "sha256:" + "9" * 64,
                    "status": "OK",
                }
            ]
            write_ledger(root, global_data)

            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                exit_code, stdout, stderr = _capture_verify(
                    [Path(relative_ledger_path), Path("ledger.json")]
                )
            finally:
                os.chdir(previous_cwd)

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

    def test_verify_partial_set_suppresses_backlog_back_reference_finding(self) -> None:
        # The unit-level test above
        # (test_backlog_back_references_are_suppressed_for_a_partial_set)
        # covers validate_collection(complete=False) directly. The plan's
        # acceptance criterion is end to end: verify() itself, with one
        # ledger genuinely unreadable, must both exit 2 and not report a
        # backlog id that resolves to no record in the readable set --
        # that record may live in the ledger that could not be read.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            present_dir = root / "present"
            present_dir.mkdir()
            data = self.project_ledger()
            data["backlog"] = [
                {
                    "id": "MAT-2026-777",
                    "classification": "MONITOR",
                    "reason": "the record may live in the ledger that could not be read",
                    "revisit_trigger": "never",
                    "revisit_after": None,
                }
            ]
            present_path = write_ledger(present_dir, data)
            missing_path = root / "missing" / "ledger.json"
            exit_code, stdout, stderr = _capture_verify([present_path, missing_path])
            self.assertEqual(exit_code, 2)
            self.assertNotIn("MAT-2026-777", stderr)

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

    def test_reference_documents_the_new_checks(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        for phrase in (
            "final on-disk bytes",
            "not comparable",
            "a floor",
            "back-reference",
            "does not make coverage verifiable",
        ):
            self.assertIn(phrase, text)

    def test_reference_states_the_sequences_floor_rule_not_its_negation(self) -> None:
        # test_reference_documents_the_new_checks above asserts "a floor"
        # as a bare substring, which the *negation* of the rule also
        # contains ("It is an equality, not a floor" still matches "a
        # floor"). Rewriting the documented rule into its opposite would
        # keep that test green. Pin the exact phrase order, both ways.
        text = REFERENCE.read_text(encoding="utf-8")
        self.assertIn("a floor, not an equality", text)
        self.assertNotIn("an equality, not a floor", text)

    @staticmethod
    def _normalized(text: str) -> str:
        # Prose in LEDGER.md wraps at ~90 characters, so a multi-word anchor
        # phrase can straddle a line break. Collapse all whitespace runs
        # (including newlines) to a single space before searching, so a test
        # is not accidentally satisfied -- or accidentally defeated -- by
        # where Markdown happened to wrap a line.
        return re.sub(r"\s+", " ", text)

    # The 0.2.2 review found an anchor phrase that already occurred
    # elsewhere in the file, so a test passed even against a deleted
    # paragraph. Every phrase below was checked, before being chosen, to
    # occur exactly once in LEDGER.md -- each test below anchors on text
    # that only the paragraph it guards can satisfy.

    def test_reference_documents_the_three_anchors(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        for phrase in ("$USER_CONFIG", "$PROJECT", "$PLUGIN", "user-level configuration root"):
            self.assertIn(phrase, text)

    def test_reference_documents_paths_stored_anchored_never_absolute(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("stored anchored, never absolute", text)

    def test_reference_documents_the_longest_anchor_wins(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("longest anchor wins", text)
        self.assertIn("keeps both anchors meaningful", text)

    def test_reference_documents_paths_outside_every_anchor(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("lies outside every anchor is stored absolute", text)
        self.assertIn("portable: false", text)

    def test_reference_documents_the_five_refusal_rules(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        for label in (
            "**unknown anchor**",
            "**`..` segment**",
            "**absolute path**",
            "**resolves outside the anchor**",
            "**symlink crosses the anchor boundary**",
        ):
            with self.subTest(label=label):
                self.assertIn(label, text)

    def test_reference_documents_the_dot_dot_refusal_timing(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("before any normalization", text)

    def test_reference_documents_symlink_rule_is_stricter_than_resolution_rule(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("deliberately stricter than rule 4", text)

    def test_reference_states_what_verify_does_not_change(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn(
            "it still never dereferences a path that arrived as ledger content", text
        )

    def test_reference_documents_adapter_glob_safety(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("escapes its anchor", text)

    def test_reference_documents_base_identifiers_join_sequence_rules(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("A baseline identifier is an identifier", text)

    def test_reference_documents_every_baseline_item_kind(self) -> None:
        # `_assert_vocabulary_documented` (used above for RECORD_TYPES etc.)
        # only checks that each value appears *somewhere* in backtick form.
        # That is too weak here: `env-var-name` is also named, legitimately,
        # in the very next paragraph explaining why `digest` may be null, so
        # deleting just the table's enum list would not be caught. Anchor on
        # the table's own enumeration phrase instead, verified unique above,
        # and cross-check its contents against the runtime set so the two
        # cannot silently drift apart.
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        listed = (
            "one of `instruction-file`, `skill`, `plugin`, `agent`, `command`, "
            "`hook`, `mcp-server`, `permission-rule`, `model-setting`, `env-var-name`"
        )
        self.assertIn(listed, text)
        documented = set(re.findall(r"`([\w-]+)`", listed))
        self.assertEqual(documented, dashboard.BASELINE_ITEM_KINDS)

    def test_reference_documents_every_baseline_item_state(self) -> None:
        # Same reasoning as the kind test above: `not_present` is also named
        # in the "state fills a gap" paragraph immediately below the table,
        # so a loose "appears somewhere" check would not catch the table
        # row's own enum being deleted. Anchor on the table's exact phrase.
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        listed = "`present` or `not_present`"
        self.assertIn(listed, text)
        documented = set(re.findall(r"`(\w+)`", listed))
        self.assertEqual(documented, dashboard.BASELINE_ITEM_STATES)

    def test_reference_documents_state_fills_a_spec_gap(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("records that a probe matched nothing", text)
        self.assertIn("already means something else", text)

    def test_reference_documents_portable_is_optional_everywhere(self) -> None:
        text = self._normalized(REFERENCE.read_text(encoding="utf-8"))
        self.assertIn("is never required", text)
        self.assertIn("none of which ever carried it", text)


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


ANCHOR_BASE = Path(tempfile.gettempdir()).resolve()


class AnchorPathTests(unittest.TestCase):
    def test_path_under_root_anchors_to_name_and_rest(self) -> None:
        root = ANCHOR_BASE / "project"
        path = root / "src" / "main.py"
        stored, portable = dashboard.anchor_path(path, {"PROJECT": root})
        self.assertEqual(stored, "$PROJECT/src/main.py")
        self.assertTrue(portable)

    def test_root_itself_anchors_to_bare_name(self) -> None:
        root = ANCHOR_BASE / "project"
        stored, portable = dashboard.anchor_path(root, {"PROJECT": root})
        self.assertEqual(stored, "$PROJECT")
        self.assertTrue(portable)

    def test_path_under_no_root_returns_absolute_and_not_portable(self) -> None:
        root = ANCHOR_BASE / "project"
        outside = ANCHOR_BASE / "elsewhere" / "file.txt"
        stored, portable = dashboard.anchor_path(outside, {"PROJECT": root})
        self.assertEqual(stored, str(outside))
        self.assertFalse(portable)

    def test_longest_matching_root_wins(self) -> None:
        user_config = ANCHOR_BASE / "config"
        project = user_config / "project"
        path = project / "file.txt"
        roots = {"USER_CONFIG": user_config, "PROJECT": project}
        stored, portable = dashboard.anchor_path(path, roots)
        self.assertEqual(stored, "$PROJECT/file.txt")
        self.assertTrue(portable)

    def test_separator_style_does_not_change_the_result(self) -> None:
        # The stored form is always forward-slash (as_posix()), regardless of
        # the platform's native separator, so the value is stable wherever the
        # ledger that holds it is later read.
        root = ANCHOR_BASE / "project"
        relative = Path("src") / "deep" / "main.py"
        path = root / relative
        stored, portable = dashboard.anchor_path(path, {"PROJECT": root})
        self.assertEqual(stored, f"$PROJECT/{relative.as_posix()}")
        self.assertTrue(portable)

    def test_root_that_is_a_name_prefix_but_not_a_path_prefix_does_not_match(self) -> None:
        # /a/bc must not match root /a/b: relative_to compares path
        # components, not string prefixes. A str.startswith comparison would
        # wrongly accept this.
        root_b = ANCHOR_BASE / "a" / "b"
        path_bc = ANCHOR_BASE / "a" / "bc" / "file.txt"
        stored, portable = dashboard.anchor_path(path_bc, {"ROOT": root_b})
        self.assertEqual(stored, str(path_bc))
        self.assertFalse(portable)

    def test_dotdot_escape_is_resolved_before_matching_and_stored_absolute(self) -> None:
        # C1 (CRITICAL): a fabricated '..' escape must not be matched against
        # a root just because the root's parts are a literal prefix of the
        # unresolved path. root/../outside/secret.txt actually points at
        # .../outside/secret.txt, which is NOT under root -- resolving first
        # (unconditionally, even though the input is already absolute) finds
        # that out and stores the honest absolute path, flagged not portable,
        # per design spec 7.1: "anything outside an anchor is stored absolute
        # and flagged portable: false".
        root = ANCHOR_BASE / "root"
        escaping = root / ".." / "outside" / "secret.txt"
        stored, portable = dashboard.anchor_path(escaping, {"R": root})
        self.assertEqual(stored, str(escaping.resolve()))
        self.assertNotIn("..", stored)
        self.assertFalse(portable)

    def test_rejects_malformed_root_names(self) -> None:
        # I2: a root name that does not match the ANCHOR_REFERENCE grammar
        # ([A-Z_]+) must be refused outright -- not silently accepted and
        # later produce a stored form resolve_anchored can never parse back.
        root = ANCHOR_BASE / "project"
        for bad_name in ("r", "R2", "USER_CONFIG2", "MY-ROOT", "", "A/B"):
            with self.subTest(bad_name=bad_name):
                with self.assertRaises(dashboard.PathSafetyError) as ctx:
                    dashboard.anchor_path(root / "file.txt", {bad_name: root})
                self.assertIn(repr(bad_name), str(ctx.exception))

    def test_tie_break_between_equal_depth_roots_is_deterministic_by_name(self) -> None:
        # M13: two different names for the identical root (so both match at
        # the same depth) must not pick a winner based on dict insertion
        # order. Sorting on the anchor name makes the result the same
        # regardless of which order the mapping was built in.
        root = ANCHOR_BASE / "project"
        path = root / "file.txt"
        stored_zzz_first, _ = dashboard.anchor_path(path, {"ZZZ": root, "AAA": root})
        stored_aaa_first, _ = dashboard.anchor_path(path, {"AAA": root, "ZZZ": root})
        self.assertEqual(stored_zzz_first, stored_aaa_first)
        self.assertEqual(stored_zzz_first, "$AAA/file.txt")

    def test_oserror_from_resolve_becomes_path_safety_error(self) -> None:
        # I2: anchor_path's own path.resolve() used to be a bare call, while
        # resolve_anchored routed the identical operation through
        # _resolve_or_raise. A trailing-dot/space segment following an
        # existing FILE component raises a raw NotADirectoryError
        # ([WinError 267]) from the filesystem -- verbatim the case
        # _resolve_or_raise's own docstring names. That must never escape
        # anchor_path as an OSError: callers of the anchor-safety layer
        # should only ever have to catch PathSafetyError.
        #
        # POSIX has no equivalent construct. Non-strict Path.resolve() (the
        # default, and what _resolve_or_raise calls) treats a FILE followed
        # by a trailing "..." component the same way it treats any other
        # non-symlink, non-existent tail: os.lstat succeeds on the file
        # component, pathlib never checks whether it is actually a
        # directory, and the bogus tail is appended without touching the
        # filesystem again -- no OSError at all, verified by reading
        # posixpath._joinrealpath directly (this sandbox is Windows-only, so
        # empirical POSIX execution is not available; the swallow-on-success
        # behavior in that function is unconditional and version-stable, not
        # inferred).
        #
        # A symlink loop looks like the obvious substitute (ELOOP is a real
        # POSIX errno), but it is not reliable either. Non-strict
        # pathlib.Path.resolve() adds a proactive final .stat() specifically
        # to surface loops that realpath() itself swallows, and its
        # check_eloop() helper deliberately turns a genuine ELOOP OSError
        # into a `RuntimeError`, not an `OSError` -- so it would never reach
        # _resolve_or_raise's `except OSError` either, and this test would
        # fail for a third, unrelated reason (an uncaught RuntimeError
        # instead of "PathSafetyError not raised"). No known POSIX
        # construct provokes an OSError from non-strict resolve(), so this
        # test is Windows-only, following the same skip idiom as
        # test_resolved_result_outside_root_is_refused and
        # test_junction_leaving_anchor_and_looping_back_is_refused above.
        if os.name != "nt":
            self.skipTest(
                "no POSIX construct reliably provokes an OSError from "
                "non-strict Path.resolve(): a trailing-dot/space segment "
                "after a file is silently accepted (no filesystem check), "
                "and a symlink loop is converted by pathlib itself into "
                "RuntimeError rather than OSError before _resolve_or_raise "
                "ever sees it"
            )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "f.txt").write_text("x", encoding="utf-8")
            bad = root / "f.txt" / "..."
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.anchor_path(bad, {"R": root})
            self.assertNotIsInstance(ctx.exception, OSError)
            self.assertEqual(ctx.exception.reason, "resolve_failed")


class ResolveAnchoredTests(unittest.TestCase):
    def test_unknown_anchor_is_refused(self) -> None:
        # Refusal 1: the anchor name is not in the roots mapping at all.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$UNKNOWN/file.txt", {"PROJECT": root})
        self.assertIn("unknown anchor", str(ctx.exception))

    def test_dotdot_segment_is_refused_even_though_it_normalizes_back_inside(self) -> None:
        # Refusal 2: the '..' check is textual and runs before normalization,
        # so $PROJECT/a/../b -- which lands back inside the root -- is still
        # refused. The form is the problem, not just the destination.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$PROJECT/a/../b", {"PROJECT": root})
        self.assertIn("'..' segment", str(ctx.exception))

    def test_dotdot_segment_climbing_above_the_anchor_is_refused(self) -> None:
        # Refusal 2, second form: '..' segments that climb above the anchor.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$PROJECT/../../etc", {"PROJECT": root})
        self.assertIn("'..' segment", str(ctx.exception))

    def test_posix_absolute_path_is_refused(self) -> None:
        # Refusal 3, POSIX form: an absolute path where an anchored form was
        # required. M7/M8: this has its own message, distinct from a
        # malformed-or-missing anchor reference, so a caller can tell rule 3
        # apart from a string that merely fails to parse as $NAME/....
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("/etc/passwd", {"PROJECT": root})
        self.assertIn("is absolute", str(ctx.exception))

    def test_windows_drive_absolute_path_is_refused(self) -> None:
        # Refusal 3, Windows drive form.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("C:/Windows/System32", {"PROJECT": root})
        self.assertIn("is absolute", str(ctx.exception))

    def test_resolved_result_outside_root_is_refused(self) -> None:
        # Refusal 4 is the final backstop: after every prefix has been
        # resolved and found within the anchor, the fully resolved path is
        # checked once more. In practice that backstop is now unreachable
        # whenever `tail` is non-empty, because refusal 5 (below) resolves
        # that very same last prefix -- identical to `candidate` -- on its
        # final loop iteration and raises first. This test's junction
        # (root/escape -> outside, holding secret.txt, with no path back
        # into the anchor) used to isolate refusal 4 from refusal 5, back
        # when refusal 5 asked whether a component IS a symlink:
        # Path.is_symlink() returns False for a junction, so refusal 5 used
        # to miss it and only refusal 4 fired. Refusal 5 now asks where each
        # prefix RESOLVES instead, so it catches this junction just as
        # readily as a symlink -- this is exactly the fix. What is still
        # verified here is that escaping through a junction (Windows,
        # elevation-free) is refused at all, and with the generalized
        # "crosses a link" message rather than refusal 4's message.
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            root = base / "r"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("x", encoding="utf-8")
            link = root / "escape"
            if os.name != "nt":
                self.skipTest(
                    "this scenario is exercised on Windows via a junction; "
                    "on other platforms an escaping symlink is created and "
                    "checked in test_symlink_leaving_anchor_is_refused_"
                    "even_if_final_path_returns_inside instead"
                )
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.skipTest(
                    f"cannot create a junction on this platform: {result.stderr.strip()}"
                )
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/escape/secret.txt", {"R": root})
            self.assertIn("crosses a link that leaves its anchor", str(ctx.exception))

    def test_symlink_leaving_anchor_is_refused_even_if_final_path_returns_inside(
        self,
    ) -> None:
        # Refusal 5, deliberately stricter than refusal 4: a symlink whose
        # own target leaves the anchor is refused even when the path it is
        # part of resolves back inside, because a link that leaves the
        # anchor is one an attacker can re-point later.
        #
        # root r, a directory outside, a symlink r/link -> outside, and
        # outside/back -> r; resolving $R/link/back/file must still refuse,
        # even though the final destination is back inside r.
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            root = base / "r"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "file.txt").write_text("x", encoding="utf-8")
            link = root / "link"
            back = outside / "back"
            try:
                os.symlink(outside, link, target_is_directory=True)
                os.symlink(root, back, target_is_directory=True)
            except OSError as exc:
                self.skipTest(
                    f"cannot create a symlink on this platform (needs developer "
                    f"mode or elevation on Windows): {exc}"
                )
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/link/back/file.txt", {"R": root})
            self.assertIn("crosses a link that leaves its anchor", str(ctx.exception))

    def test_junction_leaving_anchor_and_looping_back_is_refused(self) -> None:
        # The exact gap this fix closes, using a Windows junction instead of
        # a symlink so it runs without developer mode or elevation on this
        # machine: root r, a directory outside beside it, a junction
        # r/link -> outside, and a junction outside/back -> r. Resolving
        # $R/link/back/file must still refuse, even though the final
        # destination is back inside r.
        #
        # Before this fix neither rule caught this: refusal 5 asked whether
        # "link" IS a symlink (Path.is_symlink() says no for a junction), and
        # refusal 4 only looked at where the *whole* path ends up, which is
        # back inside r. Asking where each prefix resolves closes both holes
        # at once: the "link" prefix alone resolves to outside, which is
        # already outside the anchor, so it is refused before the "back"
        # segment is ever considered.
        if os.name != "nt":
            self.skipTest(
                "this test exercises the junction-specific escape; on other "
                "platforms the equivalent symlink escape is covered by "
                "test_symlink_leaving_anchor_is_refused_even_if_final_path_"
                "returns_inside"
            )
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            root = base / "root"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "file.txt").write_text("x", encoding="utf-8")
            link = root / "link"
            back = outside / "back"
            result_link = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
            )
            if result_link.returncode != 0:
                self.skipTest(
                    f"cannot create a junction on this platform: "
                    f"{result_link.stderr.strip()}"
                )
            result_back = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(back), str(root)],
                capture_output=True,
                text=True,
            )
            if result_back.returncode != 0:
                self.skipTest(
                    f"cannot create a junction on this platform: "
                    f"{result_back.stderr.strip()}"
                )
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/link/back/file.txt", {"R": root})
            self.assertIn("crosses a link that leaves its anchor", str(ctx.exception))

    def test_nonexistent_final_component_resolves_without_raising(self) -> None:
        # Path.resolve() is non-strict by default (Python 3.6+): a prefix
        # that does not exist yet must not be treated as an escape. Only
        # "src" exists on disk here; "new_file.py" does not, and that must
        # not raise -- it simply is not yet outside anything.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            sub = root / "src"
            sub.mkdir()
            resolved = dashboard.resolve_anchored(
                "$PROJECT/src/new_file.py", {"PROJECT": root}
            )
            self.assertEqual(resolved, (sub / "new_file.py").resolve())

    def test_ordinary_path_under_root_resolves_to_expected_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            sub = root / "src"
            sub.mkdir()
            target = sub / "main.py"
            target.write_text("x", encoding="utf-8")
            resolved = dashboard.resolve_anchored("$PROJECT/src/main.py", {"PROJECT": root})
            self.assertEqual(resolved, target.resolve())

    def test_rejects_malformed_root_names(self) -> None:
        # I2: every key in the roots mapping is validated, not only the one
        # the stored string happens to name -- a malformed key elsewhere in
        # the mapping is refused just as loudly.
        root = ANCHOR_BASE / "project"
        for bad_name in ("r", "R2", "USER_CONFIG2", "MY-ROOT", "", "A/B"):
            with self.subTest(bad_name=bad_name):
                with self.assertRaises(dashboard.PathSafetyError) as ctx:
                    dashboard.resolve_anchored(
                        "$PROJECT/file.txt", {bad_name: root, "PROJECT": root}
                    )
                self.assertIn(repr(bad_name), str(ctx.exception))

    def test_slash_containing_root_name_cannot_redirect_to_a_different_root(self) -> None:
        # I2's concrete exploit: roots {"A": rootA, "A/B": rootB}. Without
        # validation, "$A/B/decoy.txt" -- produced by anchor_path against the
        # "A/B" root -- is parsed by ANCHOR_REFERENCE as anchor "A" (which
        # only matches [A-Z_]+) with tail "B/decoy.txt", silently resolving
        # into rootA/B/decoy.txt instead of the rootB/decoy.txt the string
        # was meant to name. Validating every key up front refuses this
        # mapping outright, before any such confusion can happen.
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            root_a = base / "rootA"
            root_b = base / "rootB"
            root_a.mkdir()
            root_b.mkdir()
            roots = {"A": root_a, "A/B": root_b}
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$A/B/decoy.txt", roots)
            self.assertIn("A/B", str(ctx.exception))

    def test_dos_device_name_component_is_refused(self) -> None:
        # I3: a component that is a reserved Windows device name resolves
        # "inside" the anchor on Windows but does not behave like an
        # ordinary file (writes vanish, reads return empty, exists() lies).
        # Refused on every platform since a ledger written on Windows may be
        # validated on Linux.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/NUL", {"R": root})
        self.assertIn("device name", str(ctx.exception))

    def test_dos_device_name_with_extension_is_refused(self) -> None:
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/NUL.txt", {"R": root})
        self.assertIn("device name", str(ctx.exception))

    def test_dos_device_name_is_refused_case_insensitively(self) -> None:
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/nul", {"R": root})
        self.assertIn("device name", str(ctx.exception))

    def test_dos_device_name_as_a_mid_path_component_is_refused(self) -> None:
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/sub/con/file.txt", {"R": root})
        self.assertIn("device name", str(ctx.exception))

    def test_com_and_lpt_device_names_are_refused(self) -> None:
        root = ANCHOR_BASE / "project"
        for name in ("COM1", "COM9", "LPT1", "LPT9"):
            with self.subTest(name=name):
                with self.assertRaises(dashboard.PathSafetyError) as ctx:
                    dashboard.resolve_anchored(f"$R/{name}", {"R": root})
                self.assertIn("device name", str(ctx.exception))

    def test_device_shaped_but_not_reserved_names_are_accepted(self) -> None:
        # COM10/LPT10 are not reserved (only 1-9 are), and CONSOLE/NULL are
        # ordinary names that merely start with a reserved one -- none of
        # these may be refused.
        root = ANCHOR_BASE / "project"
        for name in ("COM10", "LPT10", "CONSOLE", "NULL"):
            with self.subTest(name=name):
                dashboard.resolve_anchored(f"$PROJECT/{name}", {"PROJECT": root})

    def test_alternate_data_stream_component_is_refused(self) -> None:
        # M12: a colon inside a path COMPONENT (after the anchor prefix is
        # stripped) opens an NTFS alternate data stream -- writing there is
        # invisible to a directory listing and leaves the visible file
        # unchanged.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/sub/in.txt:hidden", {"R": root})
        self.assertIn("':'", str(ctx.exception))

    def test_embedded_nul_byte_is_refused_with_its_own_reason(self) -> None:
        # I1: an embedded NUL byte survives every textual check above it (it
        # is not a '..' segment, not absolute, not an unknown anchor) and
        # used to reach _refuse_if_hardlinked's path.stat(), which raises a
        # bare ValueError -- "stat: embedded null character in path" -- that
        # is not an OSError and was not caught there. resolve_anchored must
        # refuse it directly, by its own named reason, before anything
        # touches the filesystem.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/a\x00b", {"R": root})
        self.assertNotIsInstance(ctx.exception, ValueError)
        self.assertIn("NUL byte", str(ctx.exception))
        self.assertEqual(ctx.exception.reason, "path_embedded_nul")

    def test_trailing_dot_space_segment_raising_oserror_becomes_path_safety_error(
        self,
    ) -> None:
        # I5: resolving "f.txt/. ." -- a trailing dot/space segment
        # following an existing FILE component -- raises a raw
        # NotADirectoryError ([WinError 267]) from the filesystem. That must
        # never escape resolve_anchored as an OSError: it must become a
        # PathSafetyError naming the path, so a caller like `scan` can
        # report it as a finding instead of aborting mid-walk.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "f.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/f.txt/. .", {"R": root})
            self.assertNotIsInstance(ctx.exception, OSError)
            self.assertIn("$R/f.txt/. .", str(ctx.exception))

    def test_trailing_dots_segment_raising_oserror_becomes_path_safety_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "f.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/f.txt/...", {"R": root})
            self.assertNotIsInstance(ctx.exception, OSError)

    def test_symlink_loop_is_refused_instead_of_leaking_runtime_error(self) -> None:
        # The exact defect this commit fixes, reproduced on Ubuntu 24.04 /
        # Python 3.12.3: root/a -> root/b and root/b -> root/a form a
        # symlink loop, and non-strict Path.resolve() detects that loop
        # itself -- in Python, not via the OS -- and raises a bare
        # RuntimeError ("Symlink loop from '<path>'"), not an OSError.
        # _resolve_or_raise's original `except OSError` let that sail
        # straight through uncaught. This is the same class of gap I1 and
        # I5 closed for a NUL byte and a trailing dot/space segment
        # respectively: a non-PathSafetyError escaping a layer whose whole
        # contract is that callers catch exactly one exception type, which
        # matters because scan (0.2.4) walks real client configuration
        # directories, where a symlink loop is entirely plausible, and must
        # report one finding and keep walking rather than abort.
        #
        # POSIX-only in practice: creating a symlink needs no elevation
        # there, but on Windows it needs developer mode or an elevated
        # process, so this follows the same try/except OSError skip idiom
        # as test_symlink_leaving_anchor_is_refused_even_if_final_path_
        # returns_inside above, rather than a hard os.name check -- on a
        # default, non-elevated Windows account (this sandbox included)
        # os.symlink itself is what raises and skips the test.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            link_a = root / "a"
            link_b = root / "b"
            try:
                os.symlink(link_b, link_a)
                os.symlink(link_a, link_b)
            except OSError as exc:
                self.skipTest(
                    f"cannot create a symlink on this platform (needs developer "
                    f"mode or elevation on Windows): {exc}"
                )
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/a", {"R": root})
            self.assertIn("$R/a", str(ctx.exception))
            self.assertEqual(ctx.exception.reason, "resolve_failed")

    def test_hardlinked_regular_file_is_refused(self) -> None:
        # I4: a hardlink has no symlink target for rules 4/5 to follow, so
        # neither can see it -- writing through root/hard.txt writes through
        # to whatever else the same file is linked from. os.link needs no
        # elevation on Windows (unlike os.symlink), so this runs here.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            original = root / "original.txt"
            original.write_text("x", encoding="utf-8")
            hard = root / "hard.txt"
            os.link(original, hard)
            with self.assertRaises(dashboard.PathSafetyError) as ctx:
                dashboard.resolve_anchored("$R/hard.txt", {"R": root})
            self.assertIn("hardlink", str(ctx.exception))

    def test_regular_file_with_a_single_link_is_accepted(self) -> None:
        # An ordinary file (nlink == 1) must not be refused -- only multiple
        # links are suspicious.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "solo.txt"
            target.write_text("x", encoding="utf-8")
            resolved = dashboard.resolve_anchored("$R/solo.txt", {"R": root})
            self.assertEqual(resolved, target.resolve())

    def test_malformed_anchor_reference_gets_its_own_message(self) -> None:
        # M7/M8: a string that is not absolute but still fails to parse as
        # $NAME/... must not share rule 3's "is absolute" message, nor the
        # old undifferentiated "not anchored" wording -- it is a different
        # problem (a malformed or missing anchor reference) and must be
        # distinguishable from both.
        root = ANCHOR_BASE / "project"
        roots = {"R": root, "PROJECT": root}
        forms = ["$r/x", "$R2/x", "${R}/x", "$", "relative/path.txt"]
        for form in forms:
            with self.subTest(form=form):
                with self.assertRaises(dashboard.PathSafetyError) as ctx:
                    dashboard.resolve_anchored(form, roots)
                message = str(ctx.exception)
                self.assertIn("valid anchor reference", message)
                self.assertNotIn("is absolute", message)
                self.assertNotIn("crosses a link", message)

    def test_trailing_dot_space_forms_never_report_the_link_rule(self) -> None:
        # M7/M8: whatever resolve_anchored decides about a trailing
        # dot/space segment -- accept it, or refuse it for some other
        # reason -- it must never claim a link was crossed, since none is
        # involved in any of these forms.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "f.txt").write_text("x", encoding="utf-8")
            forms = ["$R/...", "$R/. .", "$R/f.txt/...", "$R/f.txt/. ."]
            for form in forms:
                with self.subTest(form=form):
                    try:
                        dashboard.resolve_anchored(form, {"R": root})
                    except dashboard.PathSafetyError as exc:
                        self.assertNotIn("crosses a link", str(exc))

    def test_drive_component_mid_path_no_longer_reports_the_link_rule(self) -> None:
        # M7/M8's "$R/D:/x" case: before M12's colon check, joining a
        # component that looks like a drive letter reset pathlib's join and
        # the result resolved outside the anchor, misreported as "crosses a
        # link". The colon check now refuses this earlier and by its own
        # rule, so the link message must never appear here.
        root = ANCHOR_BASE / "project"
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.resolve_anchored("$R/D:/x", {"R": root})
        self.assertNotIn("crosses a link", str(ctx.exception))
        self.assertIn("':'", str(ctx.exception))

    def test_trailing_newline_no_longer_aliases_the_anchor_reference(self) -> None:
        # M10: ANCHOR_REFERENCE used '$', which matches just before a
        # trailing newline as well as at the true end of string, so
        # "$R/f.txt\n" parsed identically to "$R/f.txt" -- two different
        # stored strings resolving to the same anchor reference. '\Z'
        # requires the true end of the string, so the newline form must now
        # be refused instead of silently aliasing.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "f.txt"
            target.write_text("x", encoding="utf-8")
            resolved = dashboard.resolve_anchored("$R/f.txt", {"R": root})
            self.assertEqual(resolved, target.resolve())
            with self.assertRaises(dashboard.PathSafetyError):
                dashboard.resolve_anchored("$R/f.txt\n", {"R": root})


class RefuseIfHardlinkedTests(unittest.TestCase):
    def test_directory_is_never_refused_regardless_of_link_count(self) -> None:
        # I4 explicitly excludes directories: a directory's link count is an
        # ordinary filesystem property, not evidence of a hardlink escape.
        # Directories can't be hardlinked on this platform to produce a real
        # nlink > 1, so this patches stat() (scoped to this one path only,
        # falling through to the real stat() for everything else) to report
        # an implausibly high nlink and confirms the directory branch is
        # still never refused.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            sub = root / "sub"
            sub.mkdir()
            real_stat = sub.stat()
            fake_stat = os.stat_result(
                (
                    stat.S_IFDIR | 0o755,
                    real_stat.st_ino,
                    real_stat.st_dev,
                    5,
                    real_stat.st_uid,
                    real_stat.st_gid,
                    real_stat.st_size,
                    real_stat.st_atime_ns,
                    real_stat.st_mtime_ns,
                    real_stat.st_ctime_ns,
                )
            )
            original_stat = Path.stat

            def fake(self, *args, **kwargs):
                if self == sub:
                    return fake_stat
                return original_stat(self, *args, **kwargs)

            with mock.patch.object(Path, "stat", fake):
                dashboard._refuse_if_hardlinked(sub, "$R/sub")  # must not raise

    def test_nonexistent_path_is_not_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp).resolve() / "does-not-exist.txt"
            dashboard._refuse_if_hardlinked(missing, "$R/does-not-exist.txt")


class CheckGlobTests(unittest.TestCase):
    def test_dotdot_segment_is_refused(self) -> None:
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.check_glob("a/../b/*.py")
        self.assertIn("'..' segment", str(ctx.exception))

    def test_posix_absolute_glob_is_refused(self) -> None:
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.check_glob("/etc/*.conf")
        self.assertIn("absolute", str(ctx.exception))

    def test_drive_letter_absolute_glob_is_refused(self) -> None:
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.check_glob("C:/Windows/*.dll")
        self.assertIn("absolute", str(ctx.exception))

    def test_ordinary_relative_glob_is_accepted(self) -> None:
        dashboard.check_glob("src/**/*.py")  # must not raise

    def test_dot_and_space_variants_of_dotdot_are_refused(self) -> None:
        # M9: ntpath.realpath collapses a segment made entirely of dots
        # and/or spaces the same way it collapses "..", even though it
        # didn't traverse via this glob library on this build -- the two
        # normalizers disagreeing is exactly the wrong place to be relaxed.
        for pattern in ("...", ".. ", ". .", "a/.../b", "a/.. /b", "a/. ./b"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(dashboard.PathSafetyError) as ctx:
                    dashboard.check_glob(pattern)
                self.assertIn("'..' segment", str(ctx.exception))

    def test_bare_dot_segment_is_accepted(self) -> None:
        # A lone "." is an ordinary no-op segment, not an escape -- it must
        # not be swept up by the generalized dot/space check.
        dashboard.check_glob("./src/*.py")

    def test_nul_byte_is_refused(self) -> None:
        with self.assertRaises(dashboard.PathSafetyError) as ctx:
            dashboard.check_glob("src/*.py\0evil")
        self.assertIn("NUL byte", str(ctx.exception))


class PathSafetyReasonAlignmentTests(unittest.TestCase):
    """I3: the documented set of PathSafetyError refusal reasons must equal
    the enforced set, in both directions.

    references/LEDGER.md used to introduce its refusal list with "refusing
    with a distinct, named reason whenever:" and then name only five, while
    the code (resolve_anchored, anchor_path, and check_glob together) could
    raise PathSafetyError for at least nine. A test that merely checked that
    five bold labels were present did not — and could not — catch that drift;
    it would stay green even if a tenth undocumented reason were added
    tomorrow. This class is driven entirely from dashboard.PATH_SAFETY_REASONS
    and the machine-checked block in LEDGER.md, not from a hardcoded list, so
    adding a reason to the code without documenting it fails
    test_every_code_reason_is_documented, and documenting a reason the code
    can no longer raise fails test_no_documented_reason_is_stale.
    """

    REASON_KEY = re.compile(r"^[a-z][a-z_]*$")
    START_MARKER = "<!-- PATH_SAFETY_REASONS_START -->"
    END_MARKER = "<!-- PATH_SAFETY_REASONS_END -->"

    def _documented_reasons(self) -> set[str]:
        text = REFERENCE.read_text(encoding="utf-8")
        start = text.index(self.START_MARKER)
        end = text.index(self.END_MARKER)
        block = text[start:end]
        tokens = re.findall(r"`([^`]+)`", block)
        return {token for token in tokens if self.REASON_KEY.fullmatch(token)}

    def test_reason_block_markers_are_present(self) -> None:
        # Guards the two tests below against both markers being deleted
        # together, which would otherwise make an empty documented set
        # compare against an empty "missing" or "extra" set and pass for the
        # wrong reason.
        text = REFERENCE.read_text(encoding="utf-8")
        self.assertIn(self.START_MARKER, text)
        self.assertIn(self.END_MARKER, text)

    def test_every_code_reason_is_documented(self) -> None:
        documented = self._documented_reasons()
        missing = dashboard.PATH_SAFETY_REASONS - documented
        self.assertFalse(
            missing,
            f"PathSafetyError can raise {sorted(missing)}, which "
            "references/LEDGER.md's PATH_SAFETY_REASONS block does not name",
        )

    def test_no_documented_reason_is_stale(self) -> None:
        documented = self._documented_reasons()
        extra = documented - dashboard.PATH_SAFETY_REASONS
        self.assertFalse(
            extra,
            f"references/LEDGER.md documents {sorted(extra)} as a "
            "PathSafetyError reason, but no code in dashboard.py can raise it",
        )

    def test_documented_set_equals_the_runtime_set(self) -> None:
        self.assertEqual(self._documented_reasons(), dashboard.PATH_SAFETY_REASONS)


PRIVACY = REPO_ROOT / "PRIVACY.md"
README = REPO_ROOT / "README.md"


def _collapsed(path: Path) -> str:
    """A document with every whitespace run collapsed to one space.

    Prose in these files wraps, so a multi-word anchor phrase can straddle a
    line break; collapsing first means a test is neither satisfied nor
    defeated by where Markdown happened to wrap a line. The same helper
    `ReferenceTests._normalized` provides, hoisted to module scope because the
    classes below span four documents rather than one.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


# Every phrase asserted below was grepped against its target document before
# the test was written and occurs there exactly once, in the paragraph the
# test guards. This is not a formality: 0.2.2 shipped a documentation test
# that stayed green against a deleted paragraph because its anchor phrase
# already occurred elsewhere in the same file. A phrase that survives its
# paragraph's deletion is the wrong phrase, and the phrase is what changes.


class ScanDocumentationTests(unittest.TestCase):
    """references/LEDGER.md documents the `scan` command."""

    def test_reference_documents_the_scan_command_and_that_it_writes_nothing(
        self,
    ) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("dashboard.py scan --id BASE-2026-000", text)
        self.assertIn("it writes no file and creates no directory anywhere", text)
        self.assertIn(
            "recorded as a name and a digest like every other value", text
        )

    def test_reference_documents_every_scan_argument(self) -> None:
        text = _collapsed(REFERENCE)
        for phrase in (
            "the `BASE` identifier the emitted entry carries",
            "detected when omitted",
            "the root `$PROJECT` anchors to",
            "overriding selection entirely and validated like any other",
            "that directory is never read when omitted",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_reference_documents_why_id_is_required(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("does not get a second, private implementation of it", text)

    def test_reference_documents_where_the_emitted_entry_goes(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn(
            "append the emitted object to the target ledger's `baselines[]` array", text
        )

    def test_reference_documents_the_scan_exit_codes(self) -> None:
        # `Exit codes: 0 clean, 1 findings` alone would be satisfied by the
        # Validation section's line for `verify`, which predates this
        # paragraph. Anchor on the wording only scan's can carry.
        text = _collapsed(REFERENCE)
        self.assertIn("`0` clean, `1` findings, `2` a tool error", text)
        self.assertIn("The entry still reaches stdout at `1`", text)


class AdapterFormatDocumentationTests(unittest.TestCase):
    """references/LEDGER.md documents the adapter format field by field."""

    def test_reference_documents_the_anchor_candidate_rule(self) -> None:
        text = _collapsed(REFERENCE)
        for phrase in (
            "Anchor candidates are tried in order and the first that exists wins",
            "unset and empty are the same thing",
            "one that exists as a file does not",
            "every `$env:` candidate is written ahead of the default it overrides",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_reference_documents_the_two_extension_anchors(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("two anchors beyond the design spec's three", text)
        self.assertIn("cannot be written as a probe at all", text)
        self.assertIn("against the home directory itself rather than", text)

    def test_reference_documents_parse_and_pointer(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn(
            "one item per key, which is what turns one `settings.json`", text
        )
        self.assertIn("A pointer that does not resolve is one `not_present` item", text)

    def test_reference_documents_scope_as_recorded_not_resolved(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("`scope` is recorded and never resolved", text)

    def test_reference_documents_sensitive_key_patterns(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("matches the key `env` without matching `environment`", text)
        self.assertIn("Recursion stops at the match", text)

    def test_reference_documents_adapter_expiry(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("inherit its expiry", text)


class UnknownClientDocumentationTests(unittest.TestCase):
    """references/LEDGER.md documents detection and the user adapter."""

    def test_reference_documents_the_generic_fallback_as_a_finding(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn(
            "Reaching `generic` by falling back and asking for it by name", text
        )

    def test_reference_documents_the_user_adapter_path(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn(
            "<user-config>/agent-ingest-audit-optimize/adapters/local.json", text
        )
        self.assertIn("not defaulted to the home directory", text)

    def test_reference_documents_user_adapter_precedence_and_refusal(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn(
            "a user adapter beats a bundled one declaring the same client", text
        )
        self.assertIn("validated exactly as a bundled one is, and refused the same way", text)


class KnownGapDocumentationTests(unittest.TestCase):
    """references/LEDGER.md records what this release deliberately omits.

    Each of these came out of the adapter work or the first real run of
    `scan` (docs/validation/scan-dogfood-0.2.5.md). A gap nobody wrote down
    is indistinguishable from a gap nobody noticed, and the next release
    reads this file rather than that transcript.
    """

    def test_reference_records_the_credential_file_gap(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("an eleventh kind to record it under", text)

    def test_reference_records_the_hook_script_gap(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("only their registrations", text)

    def test_reference_records_the_managed_policy_gap(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("platform-specific policy directory", text)

    def test_reference_records_the_precedence_gap(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("Per-subsystem precedence is not expressible", text)

    def test_reference_records_the_system_config_gap(self) -> None:
        text = _collapsed(REFERENCE)
        self.assertIn("POSIX-only and cannot be declared optional", text)


class AdapterFieldAlignmentTests(unittest.TestCase):
    """The documented adapter fields must equal the enforced ones, both ways.

    Driven from `adapters.ADAPTER_FIELDS` and `adapters.PROBE_FIELDS` and
    from the machine-checked blocks in LEDGER.md, never from a list written
    out here: a field added to the loader without being documented fails one
    direction, and a field documented that the loader does not know fails the
    other. Following the pattern PathSafetyReasonAlignmentTests established,
    for the same reason -- a test that merely counts rows cannot catch drift.
    """

    ADAPTER_START = "<!-- ADAPTER_FIELDS_START -->"
    ADAPTER_END = "<!-- ADAPTER_FIELDS_END -->"
    PROBE_START = "<!-- PROBE_FIELDS_START -->"
    PROBE_END = "<!-- PROBE_FIELDS_END -->"

    # The first cell of a table row, and only that. A rule column names
    # `json`, `toml`, and `check_glob` in backticks too, and sweeping those
    # up would make the stale-field direction fail for text that documents
    # nothing.
    ROW_FIELD = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.MULTILINE)

    def _documented(self, start: str, end: str) -> set[str]:
        text = REFERENCE.read_text(encoding="utf-8")
        block = text[text.index(start) : text.index(end)]
        return set(self.ROW_FIELD.findall(block))

    def test_field_block_markers_are_present(self) -> None:
        # Without this, deleting both markers of a pair would raise a
        # ValueError from index() rather than reporting the drift -- and
        # deleting the table between them would compare two empty sets and
        # pass for the wrong reason.
        text = REFERENCE.read_text(encoding="utf-8")
        for marker in (
            self.ADAPTER_START,
            self.ADAPTER_END,
            self.PROBE_START,
            self.PROBE_END,
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_every_adapter_field_is_documented(self) -> None:
        documented = self._documented(self.ADAPTER_START, self.ADAPTER_END)
        missing = adapters.ADAPTER_FIELDS - documented
        self.assertFalse(
            missing,
            f"validate_adapter knows the top-level fields {sorted(missing)}, "
            "which references/LEDGER.md's adapter field table does not name",
        )

    def test_no_documented_adapter_field_is_stale(self) -> None:
        documented = self._documented(self.ADAPTER_START, self.ADAPTER_END)
        extra = documented - adapters.ADAPTER_FIELDS
        self.assertFalse(
            extra,
            f"references/LEDGER.md documents the top-level fields {sorted(extra)}, "
            "which validate_adapter does not know and would reject as unknown",
        )

    def test_every_probe_field_is_documented(self) -> None:
        documented = self._documented(self.PROBE_START, self.PROBE_END)
        missing = adapters.PROBE_FIELDS - documented
        self.assertFalse(
            missing,
            f"validate_adapter knows the probe fields {sorted(missing)}, which "
            "references/LEDGER.md's probe field table does not name",
        )

    def test_no_documented_probe_field_is_stale(self) -> None:
        documented = self._documented(self.PROBE_START, self.PROBE_END)
        extra = documented - adapters.PROBE_FIELDS
        self.assertFalse(
            extra,
            f"references/LEDGER.md documents the probe fields {sorted(extra)}, "
            "which validate_adapter does not know and would reject as unknown",
        )


class PrivacyDocumentTests(unittest.TestCase):
    """PRIVACY.md states what `scan` reads and what a baseline can hold."""

    def test_privacy_states_what_scan_reads(self) -> None:
        text = _collapsed(PRIVACY)
        self.assertIn("computes a SHA-256 digest of each file's bytes", text)

    def test_privacy_states_scan_executes_and_writes_nothing(self) -> None:
        text = _collapsed(PRIVACY)
        self.assertIn("It executes nothing", text)
        self.assertIn("It writes nothing at all", text)

    def test_privacy_states_sensitive_values_are_kept_only_as_digests(self) -> None:
        text = _collapsed(PRIVACY)
        self.assertIn("The key name is kept and the value is replaced by a digest", text)

    def test_privacy_states_other_parsed_values_are_copied_verbatim(self) -> None:
        # The point of the whole section, and the one thing a reader is most
        # likely to assume the opposite of: anchoring protects the recorded
        # location, never the parsed value.
        text = _collapsed(PRIVACY)
        self.assertIn("is copied into the baseline verbatim", text)
        self.assertIn("thirteen absolute local paths", text)
        self.assertIn(
            "apply to an item's recorded location, not to a parsed value", text
        )


class UnknownClientWorkflowTests(unittest.TestCase):
    """SKILL.md carries the workflow half of the unknown-client flow."""

    def test_skill_states_the_generic_fallback_is_not_a_clean_environment(self) -> None:
        text = _collapsed(SKILL)
        self.assertIn(
            "falls back to the `generic` adapter, which probes nothing", text
        )

    def test_skill_forbids_inventing_a_path(self) -> None:
        text = _collapsed(SKILL)
        self.assertIn("Never infer a path", text)

    def test_skill_requires_confirmation_before_writing_local_json(self) -> None:
        text = _collapsed(SKILL)
        self.assertIn(
            "<user-config>/agent-ingest-audit-optimize/adapters/local.json", text
        )
        self.assertIn("only after the user confirms it", text)

    def test_skill_states_a_broken_user_adapter_is_refused_not_routed_around(
        self,
    ) -> None:
        text = _collapsed(SKILL)
        self.assertIn("refused, not routed around", text)


class ReadmeScanTests(unittest.TestCase):
    def test_readme_documents_scan_beside_verify(self) -> None:
        text = _collapsed(README)
        self.assertIn("dashboard.py scan --id BASE-YYYY-NNN", text)
        self.assertIn(
            "writes no file and runs nothing a configuration file names", text
        )


if __name__ == "__main__":
    unittest.main()
