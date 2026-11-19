"""Tests for the withdrawn `compliance` command.

The command mapped ledger records to EU AI Act and ISO/IEC 42001 controls, and
the mapping misidentified the articles and controls it named. Correcting it
would mean owning a legal reading this project has no standing to maintain, so
0.8.0 withdrew it. What remains is a registered subcommand that still accepts
its old arguments and says so: an existing invocation must end in an
explanation, never in an argparse usage error, and it must not touch the
filesystem, because a refusal that wrote a file would not be a refusal.

The bundle tests are here too, since they guard the same withdrawal: the
mapping files and the reference document must stay gone, and nothing shipped
may link to a file that is no longer shipped.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "skills" / "plugin-reviewer"
SCRIPT = BUNDLE / "assets" / "scripts" / "dashboard.py"

SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class WithdrawnCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger = self.tmp / "ledger.json"
        self.ledger.write_text("{}", encoding="utf-8")

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_the_command_exits_two(self) -> None:
        code, _out, _err = self.run_cli(
            "compliance", str(self.ledger), "--framework", "eu-ai-act"
        )
        self.assertEqual(code, 2)

    def test_stderr_names_the_version_the_withdrawal_and_the_changelog(self) -> None:
        _code, _out, err = self.run_cli(
            "compliance", str(self.ledger), "--framework", "eu-ai-act"
        )
        self.assertIn("0.8.0", err)
        self.assertIn("withdrawn", err)
        self.assertIn("CHANGELOG.md", err)

    def test_stdout_is_empty(self) -> None:
        _code, out, _err = self.run_cli(
            "compliance", str(self.ledger), "--framework", "eu-ai-act"
        )
        self.assertEqual(out, "")

    def test_out_creates_nothing_even_with_force(self) -> None:
        for extra in ((), ("--force",)):
            with self.subTest(extra=extra):
                pack = self.tmp / "pack"
                code, _out, _err = self.run_cli(
                    "compliance",
                    str(self.ledger),
                    "--framework",
                    "eu-ai-act",
                    "--out",
                    str(pack),
                    *extra,
                )
                self.assertEqual(code, 2)
                self.assertFalse(pack.exists())

    def test_it_refuses_identically_when_the_ledger_does_not_exist(self) -> None:
        present = self.run_cli(
            "compliance", str(self.ledger), "--framework", "eu-ai-act"
        )
        absent = self.run_cli(
            "compliance", str(self.tmp / "missing.json"), "--framework", "eu-ai-act"
        )
        self.assertEqual(present, absent)

    def test_the_old_argument_forms_still_parse(self) -> None:
        code, out, err = self.run_cli(
            "compliance",
            str(self.ledger),
            "--framework",
            "iso-42001",
            "--out",
            str(self.tmp / "pack"),
            "--force",
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotIn("usage:", err)
        self.assertIn("withdrawn", err)


class WithdrawnBundleTests(unittest.TestCase):
    def test_no_mapping_file_remains(self) -> None:
        mappings = BUNDLE / "assets" / "compliance"
        remaining = [p for p in mappings.rglob("*") if p.is_file()] if mappings.exists() else []
        self.assertEqual(remaining, [])

    def test_the_reference_document_is_gone(self) -> None:
        self.assertFalse((BUNDLE / "references" / "COMPLIANCE.md").exists())

    def test_nothing_shipped_links_to_the_reference_document(self) -> None:
        link = re.compile(r"COMPLIANCE\.md")
        linking = [
            str(path.relative_to(BUNDLE))
            for path in BUNDLE.rglob("*.md")
            if link.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(linking, [])


if __name__ == "__main__":
    unittest.main()
