from __future__ import annotations

import importlib.util
import json
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
        # `records` now carries its own schema (validate_record), so an empty
        # dict is no longer a valid element there — it is exercised via
        # RecordEntryTests / test_records_are_validated_through_the_ledger
        # instead. known_projects/baselines/backlog have no per-item schema
        # yet (later tasks own those), so empty dicts remain valid for them.
        data = minimal_ledger()
        data["known_projects"] = [{}]
        data["baselines"] = [{}]
        data["backlog"] = [{}, {}, {}]
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
            self.assertEqual(dashboard.verify([path]), 2)

    def test_verify_returns_two_for_string_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            path.write_text(json.dumps("nope"), encoding="utf-8")
            self.assertEqual(dashboard.verify([path]), 2)

    def test_verify_returns_zero_for_a_valid_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = write_ledger(Path(temp), minimal_ledger())
            self.assertEqual(dashboard.verify([path]), 0)

    def test_verify_returns_one_for_an_invalid_ledger(self) -> None:
        data = minimal_ledger()
        del data["records"]
        with tempfile.TemporaryDirectory() as temp:
            path = write_ledger(Path(temp), data)
            self.assertEqual(dashboard.verify([path]), 1)

    def test_verify_returns_two_for_unreadable_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(dashboard.verify([path]), 2)

    def test_verify_returns_two_for_a_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(dashboard.verify([Path(temp) / "absent.json"]), 2)

    def test_verify_returns_two_for_a_directory_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(dashboard.verify([Path(temp)]), 2)


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
            set(self.record_schema["properties"]["result"]["enum"]),
            dashboard.RUN_RESULTS,
        )

    def test_schema_rollback_tested_enum_matches_runtime_validator(self) -> None:
        rollback_schema = self.record_schema["properties"]["rollback"]
        self.assertEqual(
            set(rollback_schema["properties"]["tested"]["enum"]),
            dashboard.ROLLBACK_TEST_STATES,
        )

    def test_schema_target_required_matches_runtime_validator(self) -> None:
        target_schema = self.record_schema["properties"]["targets"]["items"]
        self.assertEqual(
            set(target_schema["required"]), dashboard.REQUIRED_TARGET_FIELDS
        )

    def test_schema_proposal_pattern_matches_record_id_pattern(self) -> None:
        self.assertEqual(
            self.record_schema["properties"]["proposal"]["pattern"],
            dashboard.RECORD_ID.pattern,
        )

    def test_schema_digest_pattern_matches_runtime_validator(self) -> None:
        target_schema = self.record_schema["properties"]["targets"]["items"]
        for field in ("before_digest", "after_digest"):
            self.assertEqual(
                target_schema["properties"][field]["pattern"], dashboard.DIGEST.pattern
            )
        self.assertEqual(
            self.record_schema["properties"]["backup"]["properties"]["digest"][
                "pattern"
            ],
            dashboard.DIGEST.pattern,
        )


if __name__ == "__main__":
    unittest.main()
