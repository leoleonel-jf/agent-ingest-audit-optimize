from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_evidence_freshness.py"
SPEC = importlib.util.spec_from_file_location("check_evidence_freshness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
freshness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freshness)

REPO_ROOT = Path(__file__).resolve().parents[2]


class EvidenceFreshnessTests(unittest.TestCase):
    """Every date here is injected: nothing in this module reads the clock.

    That is the point of the script under test. The suites used to fail on the
    calendar because three tests ran the bundled adapters against today's date;
    the question "has bundled evidence gone stale" now has one owner, and that
    owner takes the date as an argument.
    """

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def write(self, relative: str, document: object) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        return path

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = freshness.main(["--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_fresh_evidence_exits_zero(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        code, stdout, _ = self.run_main("--today", "2026-08-01", "--margin-days", "14")
        self.assertEqual(code, 0, stdout)
        self.assertIn("fresh", stdout)

    def test_expired_evidence_exits_one_and_names_the_file(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        code, stdout, _ = self.run_main("--today", "2026-10-29", "--margin-days", "0")
        self.assertEqual(code, 1, stdout)
        self.assertIn("expired", stdout)
        self.assertIn("skills/s/assets/adapters/a.json", stdout)

    def test_the_expiry_date_itself_is_not_expired(self) -> None:
        """`scan` reports expiry when `captured_on > expires_on`; this agrees."""
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        code, stdout, _ = self.run_main("--today", "2026-10-28", "--margin-days", "0")
        self.assertEqual(code, 0, stdout)

    def test_evidence_inside_the_margin_exits_one_as_expiring(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        code, stdout, _ = self.run_main("--today", "2026-10-20", "--margin-days", "14")
        self.assertEqual(code, 1, stdout)
        self.assertIn("expiring", stdout)
        self.assertNotIn("expired", stdout)

    def test_the_margin_boundary_is_the_day_it_would_expire(self) -> None:
        """Fourteen days before the expiry date is fresh; thirteen is expiring."""
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        code, stdout, _ = self.run_main("--today", "2026-10-14", "--margin-days", "14")
        self.assertEqual(code, 0, stdout)
        code, stdout, _ = self.run_main("--today", "2026-10-15", "--margin-days", "14")
        self.assertEqual(code, 1, stdout)
        self.assertIn("expiring", stdout)

    def test_one_stale_file_among_fresh_ones_still_fails(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2027-06-01"})
        self.write("skills/s/assets/compliance/b.json", {"expires_on": "2026-01-31"})
        code, stdout, _ = self.run_main("--today", "2026-08-01", "--margin-days", "14")
        self.assertEqual(code, 1, stdout)
        self.assertIn("skills/s/assets/compliance/b.json", stdout)

    def test_a_malformed_date_is_a_tool_error_not_a_pass(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "next spring"})
        code, _, stderr = self.run_main("--today", "2026-08-01")
        self.assertEqual(code, 2)
        self.assertIn("expires_on", stderr)

    def test_a_malformed_today_is_a_tool_error(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        code, _, stderr = self.run_main("--today", "01/08/2026")
        self.assertEqual(code, 2)
        self.assertIn("--today", stderr)

    def test_a_tree_with_no_dated_evidence_is_a_tool_error(self) -> None:
        """A check that looked at nothing must not report that all is well."""
        self.write("skills/s/assets/schemas/x.schema.json", {"properties": {"expires_on": {}}})
        code, _, stderr = self.run_main("--today", "2026-08-01")
        self.assertEqual(code, 2)
        self.assertIn("no dated evidence", stderr)

    def test_json_without_a_top_level_expiry_is_not_evidence(self) -> None:
        self.write("skills/s/assets/adapters/a.json", {"expires_on": "2026-10-28"})
        self.write("skills/s/assets/schemas/x.schema.json", {"properties": {"expires_on": {}}})
        code, stdout, _ = self.run_main("--today", "2026-08-01")
        self.assertEqual(code, 0, stdout)
        self.assertNotIn("x.schema.json", stdout)

    def test_the_repository_ships_dated_evidence_and_the_check_finds_it(self) -> None:
        """Against the real tree, on a date before any of it existed.

        Pinned to a past date so this never depends on the calendar. What it
        guards is discovery: every bundled adapter must be among the files the
        check weighs, or a green run would mean nothing was looked at.
        """
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = freshness.main(["--root", str(REPO_ROOT), "--today", "2026-01-01"])
        self.assertEqual(code, 0, out.getvalue())
        adapters = sorted((REPO_ROOT / "skills").glob("*/assets/adapters/*.json"))
        self.assertGreaterEqual(len(adapters), 3)
        for adapter in adapters:
            self.assertIn(adapter.relative_to(REPO_ROOT).as_posix(), out.getvalue())


if __name__ == "__main__":
    unittest.main()
