"""Tests for `--open` and for `ledgerlib.update`.

The suite loads `dashboard.py` by file path exactly the way `test_build.py`
does, and for the same side effect: `dashboard.py` puts its own directory at
the front of `sys.path` before importing `ledgerlib`, so the imports below
resolve to the bundle's copy rather than to anything installed.

Two properties drive most of what follows, both from
`docs/specs/2026-08-01-dashboard-open-and-update.md`:

- `--open` is a courtesy that can never change an exit code, and never fires
  for a build that wrote nothing. Every test replaces `build._open_url`; no
  test in this file opens a browser.
- `update anchors` writes no ledger and `update ledger` writes no dashboard,
  and neither touches the hash chain -- `chain._records` links `records[]`,
  and a baseline is not a record.
"""

from __future__ import annotations

import contextlib
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

from ledgerlib import build as build_module  # noqa: E402
from ledgerlib.build import build_command  # noqa: E402
from ledgerlib.chain import chain_head, seal_ledger  # noqa: E402
from ledgerlib.errors import LedgerError  # noqa: E402
from ledgerlib.update import (  # noqa: E402
    WHAT_CHOICES,
    next_baseline_id,
    update_command,
)


class UpdateFixtureTestCase(unittest.TestCase):
    """A real temporary tree, a scannable adapter, and valid-ledger builders."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user_config = self.tmp / "user_config"
        self.user_config.mkdir(parents=True)
        self.adapter_path = self.tmp / "adapter.json"
        self.adapter_path.write_text(
            json.dumps(
                {
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
            ),
            encoding="utf-8",
        )

    def expired_adapter(self) -> Path:
        """The same adapter, past its `expires_on`.

        Expiry is the cheapest of the four coverage findings in
        `scan._coverage_findings` to arrange, and any one of them exercises
        the property under test: a finding moves the exit code without
        stopping the append.
        """
        path = self.tmp / "expired-adapter.json"
        document = json.loads(self.adapter_path.read_text(encoding="utf-8"))
        document["expires_on"] = "2020-01-01"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def give_the_probe_something_to_find(self) -> Path:
        path = self.user_config / "CLAUDE.md"
        path.write_text("# instructions\n", encoding="utf-8")
        return path

    def bare_ledger(self) -> dict:
        return {
            "schema_version": "1.0",
            "ledger_id": "l-update",
            "scope": "global",
            "language": "en",
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

    def full_material(self, *, material_id: str = "MAT-2026-000") -> dict:
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
            "evidence": [],
        }

    def write_ledger(self, document: dict, *, name: str = "ledger.json") -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path

    def run_update(self, *args: object, **kwargs: object) -> tuple[int, str, str]:
        """Call `update_command`, capturing both streams."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = update_command(*args, **kwargs)  # type: ignore[arg-type]
        return code, out.getvalue(), err.getvalue()


class OpenAfterWriteTestCase(UpdateFixtureTestCase):
    """`--open` fires once, only on success, and never moves the exit code."""

    def build(self, ledger_path: Path, **kwargs: object) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = build_command(
                ledger_path,
                kwargs.pop("out", None),  # type: ignore[arg-type]
                None,
                bool(kwargs.pop("force", False)),
                open_after=bool(kwargs.pop("open_after", True)),
            )
        return code, out.getvalue(), err.getvalue()

    def test_a_successful_build_opens_the_file_url_it_wrote(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            code, _, _ = self.build(ledger_path)
        self.assertEqual(code, 0)
        expected = (self.tmp / "dashboard.html").resolve().as_uri()
        self.assertEqual(opened, [expected])

    def test_without_the_flag_nothing_is_opened(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            code, _, _ = self.build(ledger_path, open_after=False)
        self.assertEqual(code, 0)
        self.assertEqual(opened, [])

    def test_an_invalid_ledger_exits_two_and_opens_nothing(self) -> None:
        broken = self.bare_ledger()
        del broken["records"]
        ledger_path = self.write_ledger(broken)
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            code, _, _ = self.build(ledger_path)
        self.assertEqual(code, 2)
        self.assertEqual(opened, [])

    def test_a_write_refusal_exits_one_and_opens_nothing(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        stray = self.tmp / "dashboard.html"
        stray.write_text("not a dashboard", encoding="utf-8")
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            code, _, _ = self.build(ledger_path)
        self.assertEqual(code, 1)
        self.assertEqual(opened, [])

    def test_a_browserless_environment_notes_on_stderr_and_still_exits_zero(
        self,
    ) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        with mock.patch.object(build_module, "_open_url", lambda url: False):
            code, out, err = self.build(ledger_path)
        self.assertEqual(code, 0)
        self.assertIn("no browser is available", err)
        # The stream contract: the note is not on stdout.
        self.assertNotIn("no browser", out)

    def test_a_raising_opener_notes_on_stderr_and_still_exits_zero(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())

        def explode(url: str) -> bool:
            raise OSError("no display")

        with mock.patch.object(build_module, "_open_url", explode):
            code, out, err = self.build(ledger_path)
        self.assertEqual(code, 0)
        self.assertIn("could not open", err)
        self.assertIn("no display", err)
        self.assertNotIn("could not open", out)

    def test_the_dashboard_is_on_disk_even_when_the_open_failed(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        with mock.patch.object(build_module, "_open_url", lambda url: False):
            self.build(ledger_path)
        self.assertTrue((self.tmp / "dashboard.html").is_file())


class NextBaselineIdTestCase(UpdateFixtureTestCase):
    """Minting takes the higher of the two floors, and never reuses a number."""

    def test_an_empty_ledger_mints_the_declared_floor(self) -> None:
        document = self.bare_ledger()
        document["sequences"]["BASE"] = 0
        self.assertEqual(next_baseline_id(document, year="2026"), "BASE-2026-000")

    def test_a_padded_sequence_is_respected_over_what_is_spent(self) -> None:
        document = self.bare_ledger()
        document["sequences"]["BASE"] = 7
        self.assertEqual(next_baseline_id(document, year="2026"), "BASE-2026-007")

    def test_a_spent_baseline_pushes_past_a_stale_sequence(self) -> None:
        document = self.bare_ledger()
        document["sequences"]["BASE"] = 0
        document["baselines"] = [{"id": "BASE-2026-004"}]
        self.assertEqual(next_baseline_id(document, year="2026"), "BASE-2026-005")

    def test_a_base_id_spent_in_records_also_counts(self) -> None:
        document = self.bare_ledger()
        document["sequences"]["BASE"] = 0
        document["records"] = [{"id": "BASE-2026-009"}]
        self.assertEqual(next_baseline_id(document, year="2026"), "BASE-2026-010")

    def test_the_year_comes_from_the_caller(self) -> None:
        document = self.bare_ledger()
        self.assertTrue(next_baseline_id(document, year="2031").startswith("BASE-2031-"))

    def test_an_exhausted_sequence_raises_rather_than_wrapping(self) -> None:
        document = self.bare_ledger()
        document["sequences"]["BASE"] = 1000
        with self.assertRaises(LedgerError):
            next_baseline_id(document, year="2026")


class UpdateAnchorsTestCase(UpdateFixtureTestCase):
    """`anchors` renders and writes no ledger."""

    def test_the_ledger_is_byte_identical_afterwards(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        before = ledger_path.read_bytes()
        code, _, _ = self.run_update(ledger_path, "anchors")
        self.assertEqual(code, 0)
        self.assertEqual(ledger_path.read_bytes(), before)

    def test_the_dashboard_is_written(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(ledger_path, "anchors")
        self.assertTrue((self.tmp / "dashboard.html").is_file())

    def test_stdout_is_exactly_one_json_object(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        _, out, _ = self.run_update(ledger_path, "anchors")
        summary = json.loads(out)
        self.assertEqual(summary["updated"], "anchors")
        self.assertIsNone(summary["baseline_id"])
        self.assertIsNone(summary["minted"])
        self.assertEqual(summary["dashboard"], str(self.tmp / "dashboard.html"))

    def test_builds_own_stdout_line_is_moved_to_stderr(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        _, out, err = self.run_update(ledger_path, "anchors")
        self.assertIn("wrote ", err)
        # If it had leaked, `json.loads` on stdout would fail.
        json.loads(out)

    def test_an_invalid_ledger_exits_two_and_writes_no_dashboard(self) -> None:
        broken = self.bare_ledger()
        del broken["records"]
        ledger_path = self.write_ledger(broken)
        code, _, _ = self.run_update(ledger_path, "anchors")
        self.assertEqual(code, 2)
        self.assertFalse((self.tmp / "dashboard.html").exists())

    def test_a_write_refusal_propagates_as_one(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        (self.tmp / "dashboard.html").write_text("stray", encoding="utf-8")
        code, _, _ = self.run_update(ledger_path, "anchors")
        self.assertEqual(code, 1)


class UpdateLedgerTestCase(UpdateFixtureTestCase):
    """`ledger` appends one baseline, raises the floor, and leaves the chain."""

    def test_exactly_one_baseline_is_appended(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        code, out, _ = self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        self.assertIn(code, (0, 1))
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(document["baselines"]), 1)
        self.assertEqual(document["baselines"][0]["id"], "BASE-2026-000")
        self.assertEqual(json.loads(out)["baseline_id"], "BASE-2026-000")

    def test_no_dashboard_is_written(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        self.assertFalse((self.tmp / "dashboard.html").exists())

    def test_the_sequence_floor_is_raised_past_the_number_spent(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(document["sequences"]["BASE"], 1)

    def test_updated_carries_the_capture_date(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(document["updated"], "2026-08-01")
        self.assertEqual(document["baselines"][0]["captured_on"], "2026-08-01")

    def test_the_records_and_the_chain_head_are_untouched(self) -> None:
        self.give_the_probe_something_to_find()
        document = self.bare_ledger()
        document["records"] = [self.full_material()]
        seal_ledger(document)
        head_before = chain_head(document)
        self.assertIsNotNone(head_before)
        records_before = json.loads(json.dumps(document["records"]))
        ledger_path = self.write_ledger(document)

        self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )

        after = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(after["records"], records_before)
        self.assertEqual(chain_head(after), head_before)

    def test_a_minted_identifier_is_reported_as_local_on_both_streams(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        _, out, err = self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        self.assertEqual(json.loads(out)["minted"], "local")
        self.assertIn("minted BASE-2026-000 locally", err)
        self.assertIn("not the ID authority", err)

    def test_a_supplied_identifier_is_reported_as_given_and_is_not_flagged(
        self,
    ) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        _, out, err = self.run_update(
            ledger_path,
            "ledger",
            identifier="BASE-2026-042",
            adapter=self.adapter_path,
            today="2026-08-01",
        )
        self.assertEqual(json.loads(out)["minted"], "given")
        self.assertEqual(json.loads(out)["baseline_id"], "BASE-2026-042")
        self.assertNotIn("locally", err)

    def test_a_supplied_identifier_raises_the_floor_past_itself(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(
            ledger_path,
            "ledger",
            identifier="BASE-2026-042",
            adapter=self.adapter_path,
            today="2026-08-01",
        )
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(document["sequences"]["BASE"], 43)

    def test_a_malformed_identifier_exits_two_and_writes_nothing(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        before = ledger_path.read_bytes()
        code, _, err = self.run_update(
            ledger_path,
            "ledger",
            identifier="not-an-id",
            adapter=self.adapter_path,
            today="2026-08-01",
        )
        self.assertEqual(code, 2)
        self.assertIn("BASE-YYYY-NNN", err)
        self.assertEqual(ledger_path.read_bytes(), before)

    def test_a_record_identifier_is_refused_as_a_baseline_id(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        code, _, err = self.run_update(
            ledger_path,
            "ledger",
            identifier="RUN-2026-001",
            adapter=self.adapter_path,
            today="2026-08-01",
        )
        self.assertEqual(code, 2)
        self.assertIn("BASE-YYYY-NNN", err)

    def test_an_already_spent_identifier_is_refused(self) -> None:
        document = self.bare_ledger()
        document["baselines"] = [
            {
                "id": "BASE-2026-000",
                "captured_on": "2026-07-30",
                "client": "testclient",
                "adapter_version": 1,
                "items": [],
            }
        ]
        document["sequences"]["BASE"] = 1
        ledger_path = self.write_ledger(document)
        before = ledger_path.read_bytes()
        code, _, err = self.run_update(
            ledger_path,
            "ledger",
            identifier="BASE-2026-000",
            adapter=self.adapter_path,
            today="2026-08-01",
        )
        self.assertEqual(code, 2)
        self.assertIn("already spent", err)
        self.assertEqual(ledger_path.read_bytes(), before)

    def test_an_invalid_ledger_exits_two_before_any_scan(self) -> None:
        broken = self.bare_ledger()
        del broken["records"]
        ledger_path = self.write_ledger(broken)
        before = ledger_path.read_bytes()
        code, _, _ = self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        self.assertEqual(code, 2)
        self.assertEqual(ledger_path.read_bytes(), before)

    def test_a_scan_with_findings_still_appends_and_exits_one(self) -> None:
        # An expired adapter is a coverage finding, not a tool error: the
        # capture describes an environment that may have moved, and the entry
        # recording it is the honest record of that. So the append lands and
        # the exit code, not a refusal, carries the finding.
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        code, out, err = self.run_update(
            ledger_path, "ledger", adapter=self.expired_adapter(), today="2026-08-01"
        )
        self.assertEqual(code, 1)
        self.assertIn("expired", err)
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(document["baselines"]), 1)
        self.assertEqual(json.loads(out)["baseline_id"], "BASE-2026-000")

    def test_a_missing_probe_target_is_recorded_rather_than_flagged(self) -> None:
        # The counterpart to the test above, and the reason it needs an
        # expired adapter: an absent file is a state the baseline records,
        # not a defect in the capture, so it does not move the exit code.
        ledger_path = self.write_ledger(self.bare_ledger())
        code, _, _ = self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        self.assertEqual(code, 0)
        document = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(document["baselines"]), 1)

    def test_the_written_ledger_still_validates(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(
            ledger_path, "ledger", adapter=self.adapter_path, today="2026-08-01"
        )
        # A second `anchors` run gates on `verify`, so a `0`/`1` here is the
        # cheapest proof that the append left a document the validator takes.
        code, _, _ = self.run_update(ledger_path, "anchors")
        self.assertEqual(code, 0)


class UpdateAllTestCase(UpdateFixtureTestCase):
    """`all` appends before it renders, so the page shows the new baseline."""

    def test_both_artifacts_are_produced(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        code, out, _ = self.run_update(
            ledger_path, "all", adapter=self.adapter_path, today="2026-08-01"
        )
        self.assertIn(code, (0, 1))
        summary = json.loads(out)
        self.assertEqual(summary["updated"], "all")
        self.assertEqual(summary["baseline_id"], "BASE-2026-000")
        self.assertEqual(summary["dashboard"], str(self.tmp / "dashboard.html"))
        self.assertTrue((self.tmp / "dashboard.html").is_file())

    def test_the_rendered_page_carries_the_baseline_just_appended(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        self.run_update(
            ledger_path, "all", adapter=self.adapter_path, today="2026-08-01"
        )
        html = (self.tmp / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("BASE-2026-000", html)

    def test_open_fires_once_for_all(self) -> None:
        self.give_the_probe_something_to_find()
        ledger_path = self.write_ledger(self.bare_ledger())
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            self.run_update(
                ledger_path,
                "all",
                adapter=self.adapter_path,
                today="2026-08-01",
                open_after=True,
            )
        self.assertEqual(opened, [(self.tmp / "dashboard.html").resolve().as_uri()])


class UpdateCliTestCase(UpdateFixtureTestCase):
    """The argparse shape: the default, the choices, and the refusal."""

    def test_the_three_words_are_the_only_choices(self) -> None:
        self.assertEqual(WHAT_CHOICES, ("all", "ledger", "anchors"))

    def test_a_bare_update_defaults_to_anchors(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        before = ledger_path.read_bytes()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dashboard.main(["update", str(ledger_path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["updated"], "anchors")
        self.assertEqual(ledger_path.read_bytes(), before)

    def test_an_unknown_word_is_refused_naming_the_choices(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                dashboard.main(["update", str(ledger_path), "everything"])
        self.assertEqual(raised.exception.code, 2)
        message = err.getvalue()
        for word in WHAT_CHOICES:
            self.assertIn(word, message)

    def test_help_lists_the_three_words(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                dashboard.main(["update", "--help"])
        text = out.getvalue()
        for word in WHAT_CHOICES:
            self.assertIn(word, text)

    def test_build_accepts_open_from_the_command_line(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                code = dashboard.main(["build", str(ledger_path), "--open"])
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)

    def test_update_passes_open_through(self) -> None:
        ledger_path = self.write_ledger(self.bare_ledger())
        opened: list[str] = []
        with mock.patch.object(
            build_module, "_open_url", lambda url: opened.append(url) or True
        ):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                dashboard.main(["update", str(ledger_path), "anchors", "--open"])
        self.assertEqual(len(opened), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
