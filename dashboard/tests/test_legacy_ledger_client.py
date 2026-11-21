"""Tests for a ledger whose top-level `client` is not an adapter name.

Ledgers written before adapters existed (July 2026, schema 1.0) recorded the
client as free text, for example "Codex Desktop / Codex CLI". `drift`,
`rollback-preview` and `lock` used that value as an adapter name and stopped
with "unknown client", so a ledger the validator accepts could not be checked
at all. Found on 2026-11-20 by a review run in Codex.

The rule these tests pin: a client read from a ledger is data, not something a
person typed. When it is an adapter name, nothing changes. When it is not, the
text is searched for the client names the index holds: exactly one found
selects that adapter with a note; none or several fall back to detection with a
note, never to a guess between two. An explicit `--client` stays strict: a
wrong name typed by a person is still a typo and still a tool error.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "plugin-reviewer"
    / "assets"
    / "scripts"
    / "dashboard.py"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib import adapters  # noqa: E402
from ledgerlib.drift import drift_report  # noqa: E402
from ledgerlib.errors import LedgerError  # noqa: E402
from ledgerlib.rollback import rollback_preview  # noqa: E402

LEGACY_CODEX = "Codex Desktop / Codex CLI"


class LegacyClientTestCase(unittest.TestCase):
    """A private bundled directory: `generic`, `codex` and `claude-code`.

    `codex` and `claude-code` anchor `$USER_CONFIG` at directories that do not
    exist, so detection on its own finds nothing and falls back to `generic`.
    A test that ends on `codex` therefore got there from the ledger's text,
    never from detection.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bundled = self.tmp / "bundled"
        self.bundled.mkdir()
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.user_config = self.tmp / "user_config"
        self.write_adapter("generic.json", self.document("generic"))
        self.write_adapter(
            "codex.json", self.document("codex", user_config=self.user_config)
        )
        self.write_adapter(
            "claude-code.json",
            self.document("claude-code", user_config=self.tmp / "no-such-claude"),
        )

    def document(self, client: str, *, user_config: Path | None = None) -> dict:
        data = {
            "adapter_version": 1,
            "client": client,
            "expires_on": "2099-01-01",
            "anchors": {"$PROJECT": ["."]},
            "probes": [],
            "sensitive_key_patterns": [],
        }
        if user_config is not None:
            data["anchors"] = {"$USER_CONFIG": [str(user_config)], "$PROJECT": ["."]}
        return data

    def write_adapter(self, name: str, data: dict) -> Path:
        path = self.bundled / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def select(self, **overrides) -> dict:
        arguments = {
            "client": None,
            "adapter": None,
            "user_config": None,
            "bundled": self.bundled,
            "environ": {},
            "project": self.project,
        }
        arguments.update(overrides)
        return adapters.select_adapter_detail(**arguments)


class LedgerClientSelectionTests(LegacyClientTestCase):
    def test_a_ledger_client_that_is_an_adapter_name_selects_it_as_before(self) -> None:
        selection = self.select(ledger_client="codex")
        self.assertEqual(selection["client"], "codex")
        self.assertEqual(selection["reason"], adapters.SELECTED_BY_CLIENT_NAME)

    def test_free_text_naming_one_client_selects_that_adapter_with_a_note(self) -> None:
        selection = self.select(ledger_client=LEGACY_CODEX)
        self.assertEqual(selection["client"], "codex")
        self.assertEqual(selection["reason"], adapters.SELECTED_BY_CLIENT_NAME)
        note = "\n".join(selection["notes"])
        self.assertIn(repr(LEGACY_CODEX), note)
        self.assertIn("is not an adapter name", note)

    def test_a_hyphenated_client_name_matches_its_spaced_form(self) -> None:
        selection = self.select(ledger_client="Claude Code (desktop app)")
        self.assertEqual(selection["client"], "claude-code")

    def test_a_name_inside_a_longer_word_does_not_count(self) -> None:
        selection = self.select(ledger_client="Codexify Studio")
        self.assertEqual(selection["client"], "generic")
        self.assertIn(repr("Codexify Studio"), "\n".join(selection["notes"]))

    def test_free_text_naming_two_clients_falls_back_to_detection(self) -> None:
        selection = self.select(ledger_client="Claude Code and Codex")
        self.assertEqual(selection["client"], "generic")
        self.assertIn(selection["reason"], adapters.FALLBACK_SELECTION_REASONS)
        note = "\n".join(selection["notes"])
        self.assertIn(repr("claude-code"), note)
        self.assertIn(repr("codex"), note)

    def test_free_text_naming_no_client_falls_back_to_detection(self) -> None:
        selection = self.select(ledger_client="My own agent")
        self.assertEqual(selection["client"], "generic")
        self.assertIn(repr("My own agent"), "\n".join(selection["notes"]))

    def test_an_explicit_client_stays_strict(self) -> None:
        with self.assertRaises(LedgerError):
            self.select(client=LEGACY_CODEX)

    def test_an_explicit_client_wins_over_the_ledger_client(self) -> None:
        selection = self.select(client="claude-code", ledger_client=LEGACY_CODEX)
        self.assertEqual(selection["client"], "claude-code")

    def test_an_explicit_adapter_wins_over_the_ledger_client(self) -> None:
        selection = self.select(
            adapter=self.bundled / "claude-code.json", ledger_client=LEGACY_CODEX
        )
        self.assertEqual(selection["client"], "claude-code")


class LegacyLedgerCommandTests(LegacyClientTestCase):
    """The three commands that read the ledger's client, end to end."""

    def ledger_with_a_run(self) -> dict:
        current = self.user_config / "settings.json"
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_text("after\n", encoding="utf-8")
        backup = self.user_config / "backup.json"
        backup.write_text("before\n", encoding="utf-8")
        return {
            "schema_version": "1.0",
            "client": LEGACY_CODEX,
            "baselines": [],
            "records": [
                {
                    "id": "RUN-2026-000",
                    "type": "RUN",
                    "targets": [
                        {
                            "anchor": "$USER_CONFIG/settings.json",
                            "kind": "mcp-server",
                            # A created file, so the preview can be HEALTHY
                            # without a backup holding prior bytes (0.13.0).
                            "before_digest": None,
                            "after_digest": digest(current),
                            "reversible": True,
                            "residual_effect": None,
                        }
                    ],
                    "backup": {
                        "path": "$USER_CONFIG/backup.json",
                        "digest": digest(backup),
                    },
                }
            ],
        }

    def test_drift_classifies_run_targets_under_the_named_adapter(self) -> None:
        report, messages, _code = drift_report(
            self.ledger_with_a_run(),
            project=self.project,
            bundled=self.bundled,
            environ={},
            today="2026-11-20",
        )
        states = [row["state"] for run in report["runs"] for row in run["targets"]]
        self.assertEqual(states, ["IN_PLACE"])
        self.assertTrue(any(repr(LEGACY_CODEX) in m for m in messages), messages)

    def test_rollback_preview_reads_a_legacy_ledger(self) -> None:
        report, messages, code = rollback_preview(
            self.ledger_with_a_run(),
            "RUN-2026-000",
            project=self.project,
            bundled=self.bundled,
            environ={},
        )
        self.assertEqual(report["indicator"], "HEALTHY")
        self.assertEqual(code, 0)
        self.assertTrue(any(repr(LEGACY_CODEX) in m for m in messages), messages)

    def test_lock_reads_a_legacy_ledger(self) -> None:
        document = {
            "schema_version": "1.0",
            "ledger_id": "l-legacy",
            "scope": "global",
            "language": "en",
            "client": LEGACY_CODEX,
            "adapter_version": 2,
            "created": "2026-07-29",
            "updated": "2026-11-20",
            "id_authority": True,
            "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 1},
            "known_projects": [],
            "records": [],
            "baselines": [
                {
                    "id": "BASE-2026-000",
                    "captured_on": "2026-11-20",
                    "client": "codex",
                    "adapter_version": 2,
                    "platform": "win32",
                    "items": [
                        {
                            "kind": "skill",
                            "name": "one",
                            "anchor": "$USER_CONFIG/skills/one",
                            "digest": "sha256:" + "a" * 64,
                            "attributes": {"scope": "user"},
                            "origin": "pre-existing",
                            "state": "present",
                            "portable": True,
                        }
                    ],
                }
            ],
            "backlog": [],
        }
        ledger_path = self.tmp / "ledger.json"
        ledger_path.write_text(json.dumps(document), encoding="utf-8")
        out = self.tmp / "agent.lock"
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = dashboard.main(
                ["lock", str(ledger_path), "--from", "BASE-2026-000", "--out", str(out)]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertTrue(out.is_file())


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
