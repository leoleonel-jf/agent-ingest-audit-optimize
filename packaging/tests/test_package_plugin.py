from __future__ import annotations

import hashlib
import importlib.util
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
            self.assertFalse(any("/evals/" in name or "/packaging/" in name for name in names))


if __name__ == "__main__":
    unittest.main()
