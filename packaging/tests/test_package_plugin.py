from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_plugin.py"
SPEC = importlib.util.spec_from_file_location("package_plugin", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
package_plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_plugin)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PackagePluginTests(unittest.TestCase):
    def test_build_is_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
            first = Path(first_temp)
            second = Path(second_temp)
            first_artifacts = package_plugin.build(first)
            second_artifacts = package_plugin.build(second)

            self.assertEqual(
                [digest(path) for path in first_artifacts[:2]],
                [digest(path) for path in second_artifacts[:2]],
            )
            package_plugin.verify(first)
            package_plugin.verify(second)

    def test_plugin_archive_contains_only_distribution_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plugin_archive, _, _ = package_plugin.build(output)
            with zipfile.ZipFile(plugin_archive) as archive:
                names = archive.namelist()

            self.assertIn(".codex-plugin/plugin.json", names)
            self.assertIn(".claude-plugin/plugin.json", names)
            self.assertIn("skills/agent-ingest-audit-optimize/SKILL.md", names)
            self.assertIn("LICENSE", names)
            self.assertIn("assets/logo.png", names)
            self.assertIn("PRIVACY.md", names)
            self.assertFalse(any(name.startswith(("evals/", "packaging/", ".git/")) for name in names))

    def test_skill_archive_has_one_canonical_top_level_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            _, skill_archive, _ = package_plugin.build(output)
            with zipfile.ZipFile(skill_archive) as archive:
                names = archive.namelist()

            self.assertTrue(names)
            self.assertEqual(
                {Path(name).parts[0] for name in names},
                {"agent-ingest-audit-optimize"},
            )
            self.assertIn("agent-ingest-audit-optimize/SKILL.md", names)
            self.assertIn("agent-ingest-audit-optimize/LICENSE", names)
            self.assertFalse(any("/evals/" in name or "/packaging/" in name for name in names))

    def test_archives_include_the_ledger_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plugin_archive, skill_archive, _ = package_plugin.build(output)
            with zipfile.ZipFile(plugin_archive) as archive:
                plugin_names = archive.namelist()
            with zipfile.ZipFile(skill_archive) as archive:
                skill_names = archive.namelist()

            for suffix in (
                "references/LEDGER.md",
                "assets/schemas/ledger.schema.json",
                "assets/scripts/dashboard.py",
            ):
                self.assertIn(f"skills/agent-ingest-audit-optimize/{suffix}", plugin_names)
                self.assertIn(f"agent-ingest-audit-optimize/{suffix}", skill_names)

            self.assertFalse(any("dashboard/tests" in name for name in plugin_names))
            self.assertFalse(any("dashboard/tests" in name for name in skill_names))

    def test_archives_exclude_compiled_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plugin_archive, skill_archive, _ = package_plugin.build(output)
            with zipfile.ZipFile(plugin_archive) as archive:
                plugin_names = archive.namelist()
            with zipfile.ZipFile(skill_archive) as archive:
                skill_names = archive.namelist()

            for names in (plugin_names, skill_names):
                self.assertFalse(any("__pycache__" in name for name in names))
                self.assertFalse(any(name.endswith((".pyc", ".pyo", ".pyd")) for name in names))

    def test_submission_states_the_real_evaluation_case_count(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        suite = json.loads((repo_root / "evals" / "suite.json").read_text(encoding="utf-8"))
        submission = (repo_root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
        stated = re.findall(r"(\d+)-case evaluation suite", submission)

        self.assertEqual(len(stated), 1, "expected exactly one case-count claim")
        self.assertEqual(int(stated[0]), len(suite["cases"]))


if __name__ == "__main__":
    unittest.main()
