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


if __name__ == "__main__":
    unittest.main()
