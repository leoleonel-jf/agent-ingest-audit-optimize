from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]

# These paths intentionally duplicate the ones in packaging/scripts/package_plugin.py
# rather than importing them. This module is the drift check; deriving its paths from
# the packager would let one path bug mask another.
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
README = REPO_ROOT / "README.md"
SUBMISSION = REPO_ROOT / "docs" / "SUBMISSION.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASES_DIR = REPO_ROOT / "docs" / "releases"

SEMVER = r"\d+\.\d+\.\d+"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def single_match(pattern: str, text: str, path: Path) -> str:
    """Return the one match for pattern, raising if the count is not exactly 1."""
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if not matches:
        raise AssertionError(f"{path.name}: no line matched {pattern!r}")
    if len(matches) > 1:
        raise AssertionError(
            f"{path.name}: expected exactly 1 match for {pattern!r}, found {len(matches)}"
        )
    return matches[0]


def first_match(pattern: str, text: str, path: Path) -> str:
    """Return the first match for pattern.

    Used only for CHANGELOG.md, which lists entries newest-first by
    convention -- so the first `## x.y.z` heading IS the current version.
    """
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if not matches:
        raise AssertionError(f"{path.name}: no line matched {pattern!r}")
    return matches[0]


class VersionConsistencyTests(unittest.TestCase):
    """Every version pin in the repository derives from one source of truth.

    The source of truth is .claude-plugin/plugin.json -> version. Each pin gets
    its own test method so a failure names the file that drifted.
    """

    def setUp(self) -> None:
        self.version = load_json(CLAUDE_MANIFEST)["version"]

    def test_source_of_truth_is_strict_semver(self) -> None:
        self.assertRegex(self.version, f"^{SEMVER}$")

    def test_codex_manifest_version_matches(self) -> None:
        self.assertEqual(load_json(CODEX_MANIFEST)["version"], self.version)

    def test_claude_marketplace_version_matches(self) -> None:
        plugins = load_json(CLAUDE_MARKETPLACE)["plugins"]
        self.assertEqual(len(plugins), 1, "a second entry would go unchecked")
        self.assertEqual(plugins[0]["version"], self.version)

    def test_agents_marketplace_ref_matches(self) -> None:
        plugins = load_json(AGENTS_MARKETPLACE)["plugins"]
        self.assertEqual(len(plugins), 1, "a second entry would go unchecked")
        self.assertEqual(plugins[0]["source"]["ref"], f"v{self.version}")

    def test_readme_codex_ref_matches(self) -> None:
        found = single_match(rf"--ref v({SEMVER})", read_text(README), README)
        self.assertEqual(found, self.version)

    def test_readme_skill_asset_name_matches(self) -> None:
        found = single_match(
            rf"agent-ingest-audit-optimize-({SEMVER})-skill\.zip",
            read_text(README),
            README,
        )
        self.assertEqual(found, self.version)

    def test_submission_listing_version_matches(self) -> None:
        found = single_match(
            rf"^- \*\*Version:\*\* ({SEMVER})$", read_text(SUBMISSION), SUBMISSION
        )
        self.assertEqual(found, self.version)

    def test_changelog_newest_entry_matches(self) -> None:
        found = first_match(rf"^## ({SEMVER})", read_text(CHANGELOG), CHANGELOG)
        self.assertEqual(found, self.version)

    def test_release_document_exists_and_ref_matches(self) -> None:
        release_doc = RELEASES_DIR / f"v{self.version}.md"
        if not release_doc.is_file():
            raise AssertionError(f"Missing release document: {release_doc}")
        found = single_match(
            rf"--ref v({SEMVER})", read_text(release_doc), release_doc
        )
        self.assertEqual(found, self.version)


if __name__ == "__main__":
    unittest.main()
