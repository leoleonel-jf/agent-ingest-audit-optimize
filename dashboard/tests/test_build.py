"""Tests for `ledgerlib.build`: the escaping serializer and payload assembly.

The suite loads `dashboard.py` by file path exactly the way `test_drift.py`
and `test_rollback.py` do, for the same side effect: `dashboard.py` inserts
its own directory at the front of `sys.path` before importing `ledgerlib`, so
the imports below resolve to the bundle's copy rather than to anything
installed.

`serialize_payload` is tested first and separately, because it is the
security core (design spec `docs/specs/2026-07-31-dashboard-build.md`
section 1.1): the property under test is global -- `assertNotIn("<",
serialized)` -- not a search for particular tag names, so one ledger value
containing a raw `</script><script>` payload is enough to exercise it.

`build_payload`'s fixtures are schema-valid ledgers, following
`RollbackCliTestCase` in test_rollback.py rather than the minimal documents
`test_drift.py` uses for classification-only fixtures: `build_payload`
validates the ledger it is given (`validate_ledger`, reused rather than
reimplemented, exactly as `drift_command` and `rollback_preview_command`
do), so every fixture here must be a document the validator accepts whole.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
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

from ledgerlib import drift as drift_module  # noqa: E402
from ledgerlib import rollback as rollback_module  # noqa: E402
from ledgerlib.build import build_payload, serialize_payload  # noqa: E402
from ledgerlib.constants import TOOL_VERSION  # noqa: E402
from ledgerlib.errors import LedgerError  # noqa: E402


class SerializePayloadTests(unittest.TestCase):
    """Design spec section 1.1's escaping contract, one property per test."""

    def test_no_literal_less_than_survives_serialization(self) -> None:
        payload = {"title": "</script><script>alert(1)</script>"}
        serialized = serialize_payload(payload)
        self.assertNotIn("<", serialized)

    def test_the_escaped_form_round_trips_through_json_loads(self) -> None:
        original = "</script><script>alert(1)</script>"
        serialized = serialize_payload({"title": original})
        restored = json.loads(serialized)
        self.assertEqual(restored["title"], original)

    def test_line_and_paragraph_separators_are_escaped(self) -> None:
        value = "line" + chr(0x2028) + "break" + chr(0x2029) + "end"
        serialized = serialize_payload({"title": value})
        self.assertNotIn(chr(0x2028), serialized)
        self.assertNotIn(chr(0x2029), serialized)
        self.assertIn("\\u2028", serialized)
        self.assertIn("\\u2029", serialized)
        restored = json.loads(serialized)
        self.assertEqual(restored["title"], value)

    def test_output_is_deterministic_across_two_calls(self) -> None:
        payload = {"b": 1, "a": {"z": 1, "y": 2}, "c": [3, 2, 1]}
        first = serialize_payload(payload)
        second = serialize_payload(payload)
        self.assertEqual(first, second)

    def test_output_uses_sorted_keys_and_compact_separators(self) -> None:
        serialized = serialize_payload({"b": 1, "a": 2})
        self.assertEqual(serialized, '{"a":2,"b":1}')

    def test_a_lone_surrogate_survives_serialization_as_utf8(self) -> None:
        ledger_value = json.loads('{"t": "\\ud800"}')["t"]
        serialized = serialize_payload({"title": ledger_value})
        # The whole point of the fix: this must not raise UnicodeEncodeError.
        serialized.encode("utf-8")
        self.assertNotIn("<", serialized)
        restored = json.loads(serialized)
        self.assertEqual(restored["title"], ledger_value)

    def test_backslash_then_less_than_has_no_literal_less_than_and_round_trips(
        self,
    ) -> None:
        value = chr(92) + "<"
        serialized = serialize_payload({"title": value})
        self.assertNotIn("<", serialized)
        restored = json.loads(serialized)
        self.assertEqual(restored["title"], value)


class BuildTestCase(unittest.TestCase):
    """A real temporary tree and schema-valid-ledger fixture builders.

    Follows `RollbackCliTestCase` in test_rollback.py: `full_run` and
    `known_project` produce documents `validate_ledger` accepts whole, not
    the minimal fixtures `test_drift.py`'s `DriftReportTestCase` builds for
    classification-only tests.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user_config = self.tmp / "user_config"
        self.user_config.mkdir(parents=True)
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

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def digest_of(self, path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def bare_ledger(self, *, language: str = "en") -> dict:
        return {
            "schema_version": "1.0",
            "ledger_id": "l-build",
            "scope": "global",
            "language": language,
            "client": "testclient",
            "adapter_version": 1,
            "created": "2026-07-29",
            "updated": "2026-07-30",
            "id_authority": True,
            "sequences": {"MAT": 1, "PROP": 1, "RUN": 1, "ADR": 0, "BASE": 0},
            "known_projects": [],
            "records": [],
            "baselines": [],
            "backlog": [],
        }

    def valid_ledger(
        self,
        *,
        records: list | None = None,
        known_projects: list | None = None,
        language: str = "en",
    ) -> dict:
        ledger = self.bare_ledger(language=language)
        if records is not None:
            ledger["records"] = records
        if known_projects is not None:
            ledger["known_projects"] = known_projects
        return ledger

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

    def full_run(
        self,
        targets: list,
        backup: object,
        *,
        run_id: str = "RUN-2026-000",
        evidence: list | None = None,
    ) -> dict:
        """A RUN record `validate_ledger` accepts whole."""
        return {
            "id": run_id,
            "type": "RUN",
            "title": "a validated run",
            "status": "VALIDATED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-30",
            "updated": "2026-07-30",
            "file": f"records/{run_id}.md",
            "links": {"materials": [], "runs": [], "adrs": []},
            "evidence": evidence if evidence is not None else [],
            "proposal": "PROP-2026-000",
            "authorization": {
                "quote": "Implement proposal PROP-2026-000",
                "recorded_on": "2026-07-30",
            },
            "result": "VALIDATED",
            "targets": targets,
            "backup": backup,
            "rollback": {"tested": "NOT_TESTED"},
            "self_reported": ["targets"],
        }

    def full_material(
        self, *, material_id: str = "MAT-2026-000", evidence: list | None = None
    ) -> dict:
        """A MATERIAL record `validate_ledger` accepts whole."""
        return {
            "id": material_id,
            "type": "MATERIAL",
            "title": "a material",
            "status": "ANALYZED",
            "classification": "MONITOR",
            "scope": "project",
            "created": "2026-07-30",
            "updated": "2026-07-30",
            "file": f"records/{material_id}.md",
            "links": {"materials": [], "runs": [], "adrs": []},
            "evidence": evidence if evidence is not None else [],
        }

    def known_project(self, *, project_root: str, status: str = "OK") -> dict:
        return {
            "project_root": project_root,
            "ledger_path": str(Path(project_root) / "ledger.json"),
            "last_seen": "2026-07-30",
            "last_digest": "sha256:" + "a" * 64,
            "status": status,
        }

    def verified_backup(self, run_id: str = "RUN-2026-000") -> dict:
        backup_file = self.write(
            self.user_config / "backups" / f"{run_id}.bak", "backup bytes\n"
        )
        return {
            "path": f"$USER_CONFIG/backups/{run_id}.bak",
            "digest": self.digest_of(backup_file),
            "verified": True,
        }

    def build(self, ledger: dict, **overrides: object):
        overrides.setdefault("adapter", self.adapter_path)
        overrides.setdefault("project", self.tmp)
        overrides.setdefault("lang", None)
        return build_payload(ledger, ledger_source="ledger.json", **overrides)


class BuildPayloadEnvelopeTests(BuildTestCase):
    def test_payload_schema_mode_and_ledger_are_set(self) -> None:
        ledger = self.valid_ledger()
        ledger_before = copy.deepcopy(ledger)
        payload, _ = self.build(ledger)
        self.assertEqual(payload["payload_schema"], 1)
        self.assertEqual(payload["mode"], "built")
        self.assertEqual(payload["ledger"], ledger)
        self.assertEqual(payload["tool_version"], TOOL_VERSION)
        # `build_payload` may hold the same ledger object rather than a copy;
        # this pins that it never mutates it along the way.
        self.assertEqual(ledger, ledger_before)


class BuildPayloadDriftReuseTests(BuildTestCase):
    def test_computed_drift_is_exactly_drift_reports_report(self) -> None:
        sentinel_report = {"sentinel": True}
        with mock.patch.object(
            drift_module,
            "drift_report",
            return_value=(sentinel_report, [], 0),
        ) as spy:
            payload, _ = self.build(self.valid_ledger(), today="2026-07-31")
        spy.assert_called_once()
        self.assertIs(payload["computed"]["drift"], sentinel_report)

    def test_a_drift_ledger_error_lands_as_computed_drift_error(self) -> None:
        with mock.patch.object(
            drift_module,
            "drift_report",
            side_effect=LedgerError("no adapter for client 'testclient'"),
        ):
            payload, _ = self.build(self.valid_ledger())
        self.assertEqual(
            payload["computed"]["drift"],
            {"error": "no adapter for client 'testclient'"},
        )
        self.assertEqual(payload["mode"], "built")


class BuildPayloadPreviewsTests(BuildTestCase):
    def test_previews_holds_one_entry_per_run_naming_a_backup(self) -> None:
        settings = self.write(self.user_config / "settings.json", "after\n")
        run_with_backup = self.full_run(
            [self.target(after_digest=self.digest_of(settings))],
            self.verified_backup(),
        )
        run_without_backup = self.full_run(
            [self.target()], None, run_id="RUN-2026-001"
        )
        ledger = self.valid_ledger(records=[run_with_backup, run_without_backup])
        payload, _ = self.build(ledger)
        self.assertIn("RUN-2026-000", payload["computed"]["previews"])
        self.assertNotIn("RUN-2026-001", payload["computed"]["previews"])
        self.assertEqual(
            payload["computed"]["previews"]["RUN-2026-000"]["run"], "RUN-2026-000"
        )

    def test_a_preview_ledger_error_lands_as_error_and_build_continues(self) -> None:
        run = self.full_run([self.target()], self.verified_backup())
        ledger = self.valid_ledger(records=[run])
        with mock.patch.object(
            rollback_module,
            "rollback_preview",
            side_effect=LedgerError("no record with id 'RUN-2026-000' exists"),
        ):
            payload, _ = self.build(ledger)
        self.assertEqual(
            payload["computed"]["previews"]["RUN-2026-000"],
            {"error": "no record with id 'RUN-2026-000' exists"},
        )
        self.assertEqual(payload["mode"], "built")


class BuildPayloadExpiredEvidenceTests(BuildTestCase):
    def test_expired_evidence_lists_entries_with_expires_on_before_today(
        self,
    ) -> None:
        material = self.full_material(
            evidence=[
                {
                    "source": "https://example.com/old",
                    "kind": "article",
                    "verified_on": "2026-01-01",
                    "time_sensitive": True,
                    "expires_on": "2026-06-01",
                },
                {
                    "source": "https://example.com/fresh",
                    "kind": "article",
                    "verified_on": "2026-07-01",
                    "time_sensitive": True,
                    "expires_on": "2099-01-01",
                },
            ]
        )
        ledger = self.valid_ledger(records=[material])
        payload, _ = self.build(ledger, today="2026-07-31")
        self.assertEqual(
            payload["computed"]["expired_evidence"],
            [
                {
                    "record": "MAT-2026-000",
                    "source": "https://example.com/old",
                    "expires_on": "2026-06-01",
                }
            ],
        )


class BuildPayloadUnreachableProjectsTests(BuildTestCase):
    def test_unreachable_projects_lists_roots_that_no_longer_exist(self) -> None:
        present = self.tmp / "present-project"
        present.mkdir()
        gone = self.tmp / "gone-project"
        known_projects = [
            self.known_project(project_root=str(present)),
            self.known_project(project_root=str(gone)),
        ]
        ledger = self.valid_ledger(known_projects=known_projects)
        payload, _ = self.build(ledger)
        self.assertEqual(
            payload["computed"]["unreachable_projects"], [str(gone)]
        )


class BuildPayloadValidationTests(BuildTestCase):
    def test_a_schema_invalid_ledger_raises_naming_the_first_finding(self) -> None:
        ledger = self.valid_ledger()
        del ledger["sequences"]
        with self.assertRaises(LedgerError) as ctx:
            self.build(ledger)
        self.assertIn("sequences", str(ctx.exception))

    def test_nothing_is_computed_for_an_invalid_ledger(self) -> None:
        ledger = self.valid_ledger()
        del ledger["sequences"]
        with mock.patch.object(drift_module, "drift_report") as spy:
            with self.assertRaises(LedgerError):
                self.build(ledger)
        spy.assert_not_called()


class BuildPayloadLanguageTests(BuildTestCase):
    def test_lang_lands_verbatim_when_given(self) -> None:
        payload, messages = self.build(self.valid_ledger(), lang="pt-BR")
        self.assertEqual(payload["lang"], "pt-BR")
        self.assertFalse(any("unsupported language" in m for m in messages))

    def test_lang_falls_back_to_ledger_language_when_not_given(self) -> None:
        payload, _ = self.build(self.valid_ledger(language="pt-BR"))
        self.assertEqual(payload["lang"], "pt-BR")

    def test_an_unknown_lang_argument_falls_back_to_en_with_a_message(self) -> None:
        payload, messages = self.build(self.valid_ledger(), lang="fr")
        self.assertEqual(payload["lang"], "en")
        self.assertTrue(
            any("fr" in message and "en" in message for message in messages),
            messages,
        )

    def test_an_unknown_ledger_language_falls_back_to_en_with_a_message(
        self,
    ) -> None:
        payload, messages = self.build(self.valid_ledger(language="fr"))
        self.assertEqual(payload["lang"], "en")
        self.assertTrue(
            any("fr" in message and "en" in message for message in messages),
            messages,
        )


class BuildPayloadGeneratedAtTests(BuildTestCase):
    def test_generated_at_is_iso8601_utc_pinned_to_today(self) -> None:
        payload, _ = self.build(self.valid_ledger(), today="2026-07-31")
        generated_at = payload["generated_at"]
        self.assertTrue(generated_at.startswith("2026-07-31T"), generated_at)
        self.assertTrue(generated_at.endswith("Z"), generated_at)

    def test_an_unparseable_today_raises_ledger_error(self) -> None:
        with self.assertRaises(LedgerError) as ctx:
            self.build(self.valid_ledger(), today="garbage")
        self.assertEqual(
            str(ctx.exception), "--today must be YYYY-MM-DD: 'garbage'"
        )


class BuildPayloadMessageDedupeTests(BuildTestCase):
    def test_repeated_adapter_selection_notes_appear_once(self) -> None:
        settings = self.write(self.user_config / "settings.json", "after\n")
        run_one = self.full_run(
            [self.target(after_digest=self.digest_of(settings))],
            self.verified_backup("RUN-2026-000"),
            run_id="RUN-2026-000",
        )
        run_two = self.full_run(
            [self.target(after_digest=self.digest_of(settings))],
            self.verified_backup("RUN-2026-001"),
            run_id="RUN-2026-001",
        )
        ledger = self.valid_ledger(records=[run_one, run_two])
        _, messages = self.build(ledger)
        expected_note = (
            f"selected adapter {self.adapter_path} for client 'testclient': "
            "named by --adapter"
        )
        # drift_report plus two rollback_preview calls would each surface
        # this exact note without dedupe -- it must survive only once.
        self.assertEqual(messages.count(expected_note), 1, messages)


if __name__ == "__main__":
    unittest.main()
