from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_plugin.py"
SPEC = importlib.util.spec_from_file_location("package_plugin", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
package_plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_plugin)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_NAME = "agent-ingest-audit-optimize"
SKILL_DIR = REPO_ROOT / "skills" / SKILL_NAME
SCRIPTS_DIR = SKILL_DIR / "assets" / "scripts"

# Files whose bytes are line-ending sensitive. Derived from the extension, not
# sniffed from content: a guess that reads bytes would let a new text format in
# silently the day someone adds one.
TEXT_SUFFIXES = (".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_script_relative_paths() -> list[str]:
    """Every shipping ``*.py`` under the Skill's scripts directory, walked.

    Derived from the source tree rather than a hardcoded list, so a module
    added by a later task is covered without editing this file.

    Compiled bytecode is excluded by this module's own rule, not by asking the
    packager: a walk that borrows the packager's exclusion predicate agrees with
    the packager by construction and can never catch it dropping a directory.
    """
    return sorted(
        path.relative_to(SKILL_DIR).as_posix()
        for path in SCRIPTS_DIR.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )


def minimal_ledger() -> dict:
    """The smallest ledger `verify` accepts. Shape copied from the dashboard suite."""
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

    def test_archives_ship_every_script_module_in_the_source_tree(self) -> None:
        relative_paths = source_script_relative_paths()
        self.assertIn("assets/scripts/dashboard.py", relative_paths)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plugin_archive, skill_archive, _ = package_plugin.build(output)
            with zipfile.ZipFile(plugin_archive) as archive:
                plugin_names = set(archive.namelist())
            with zipfile.ZipFile(skill_archive) as archive:
                skill_names = set(archive.namelist())

        missing_from_plugin = [
            relative
            for relative in relative_paths
            if f"skills/{SKILL_NAME}/{relative}" not in plugin_names
        ]
        missing_from_skill = [
            relative
            for relative in relative_paths
            if f"{SKILL_NAME}/{relative}" not in skill_names
        ]
        self.assertEqual(missing_from_plugin, [], "plugin archive is missing script modules")
        self.assertEqual(missing_from_skill, [], "Skill archive is missing script modules")

    def _assert_extracted_dashboard_verifies(self, archive_path: Path, script_prefix: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            extracted = root / "extracted"
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extracted)

            dashboard = extracted / script_prefix / "assets" / "scripts" / "dashboard.py"
            self.assertTrue(dashboard.is_file(), f"archive did not ship {script_prefix}/assets/scripts/dashboard.py")

            ledger = elsewhere / "ledger.json"
            ledger.write_text(json.dumps(minimal_ledger()), encoding="utf-8")

            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            # cwd is an empty scratch directory, not the repository: nothing the
            # repository ships can satisfy an import for this subprocess.
            completed = subprocess.run(
                [sys.executable, str(dashboard), "verify", str(ledger)],
                cwd=elsewhere,
                env=environment,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            completed.returncode,
            0,
            f"extracted dashboard.py failed:\nstdout: {completed.stdout}\nstderr: {completed.stderr}",
        )

    def test_extracted_plugin_archive_runs_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plugin_archive, _, _ = package_plugin.build(Path(temp))
            self._assert_extracted_dashboard_verifies(plugin_archive, f"skills/{SKILL_NAME}")

    def test_extracted_skill_archive_runs_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, skill_archive, _ = package_plugin.build(Path(temp))
            self._assert_extracted_dashboard_verifies(skill_archive, SKILL_NAME)

    def test_archived_text_files_have_no_carriage_returns(self) -> None:
        offenders: list[str] = []
        with tempfile.TemporaryDirectory() as temp:
            plugin_archive, skill_archive, _ = package_plugin.build(Path(temp))
            for archive_path in (plugin_archive, skill_archive):
                with zipfile.ZipFile(archive_path) as archive:
                    for name in archive.namelist():
                        if not name.endswith(TEXT_SUFFIXES):
                            continue
                        if b"\r\n" in archive.read(name):
                            offenders.append(f"{archive_path.name}:{name}")

        self.assertEqual(
            offenders,
            [],
            "CRLF in an archived text file breaks the reproducible-build property",
        )

    def test_submission_states_the_real_evaluation_case_count(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        suite = json.loads((repo_root / "evals" / "suite.json").read_text(encoding="utf-8"))
        submission = (repo_root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
        stated = re.findall(r"(\d+)-case evaluation suite", submission)

        self.assertEqual(len(stated), 1, "expected exactly one case-count claim")
        self.assertEqual(int(stated[0]), len(suite["cases"]))


if __name__ == "__main__":
    unittest.main()
