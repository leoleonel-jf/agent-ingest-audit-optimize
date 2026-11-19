"""The 0.11.0 rename, held in place.

`docs/specs/2026-11-19-rename-plugin-reviewer.md`. A rename that is nine
tenths done installs under one name and documents another, and nothing else in
the suite would notice: every other test derives the name from a manifest and
is satisfied by whatever it finds there.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

CURRENT = "plugin-reviewer"
# Written in two pieces so this file does not have to list itself among the
# places the former names are allowed to appear whole.
FORMER = "agent-ingest-" + "audit-optimize"
FORMER_DISPLAY = re.compile("Agent " + "Ingest", re.IGNORECASE)
DISPLAY = "Plugin Reviewer"

ROOT_MANIFEST = REPO_ROOT / "plugin.json"
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASE = REPO_ROOT / "docs" / "releases" / "v0.11.0.md"

# Files that record what was true when they were written. They keep the name
# they were written under, and the rename does not reach into them.
HISTORY = (
    "CHANGELOG.md",
    "docs/releases/",
    "docs/specs/",
    "docs/plans/",
    "docs/validation/",
    "docs/reviews/",
    "docs/research/",
    "docs/prompts/",
)

# Everywhere else, the former identifier is present for a reason, and the
# reason is written next to the path. A path that stops containing it must
# leave this table, so the table cannot outlive what it describes.
FORMER_IDENTIFIER_ALLOWED = {
    ".claude-plugin/marketplace.json": "the `renames` map",
    "README.md": "the steps for an installation made under the former name",
    "docs/SUBMISSION.md": "the July submission was made under the former name",
    "skills/plugin-reviewer/SKILL.md": "the data directory rule",
    "skills/plugin-reviewer/references/LEDGER.md": "the data directory rule",
    "skills/plugin-reviewer/references/LEDGER_BASELINES.md": (
        "the user adapter directory under its former name"
    ),
    "skills/plugin-reviewer/assets/scripts/ledgerlib/adapters.py": (
        "the user adapter directory under its former name"
    ),
    "dashboard/tests/test_adapters.py": "tests of that lookup",
    "dashboard/tests/test_dashboard.py": "tests of the data directory rule",
    "dashboard/tests/test_rollback.py": "what a move does to a backup inside it",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_files() -> list[str]:
    """Tracked paths plus untracked ones git does not ignore.

    The second half matters while a change is being written: a new file that
    still carries the former name is caught before it is committed.
    """
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return sorted(
        line for line in result.stdout.splitlines() if (REPO_ROOT / line).is_file()
    )


def is_history(path: str) -> bool:
    return any(
        path == entry or (entry.endswith("/") and path.startswith(entry))
        for entry in HISTORY
    )


def text_of(path: str) -> str | None:
    try:
        return (REPO_ROOT / path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def newest_changelog_entry() -> str:
    return CHANGELOG.read_text(encoding="utf-8").split("\n## 0.10.0", 1)[0]


def section(text: str, start: str, end: str) -> str:
    """The text from `start` up to `end`; a missing marker is a failure."""
    if start not in text:
        raise AssertionError(f"no {start!r} in the document")
    rest = text.split(start, 1)[1]
    if end not in rest:
        raise AssertionError(f"no {end!r} after {start!r}")
    return rest.split(end, 1)[0]


def current_files() -> list[str]:
    this_file = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    return [
        path for path in tracked_files() if not is_history(path) and path != this_file
    ]


class OneNameTests(unittest.TestCase):
    def test_the_three_manifests_carry_the_current_name(self) -> None:
        for manifest in (ROOT_MANIFEST, CLAUDE_MANIFEST, CODEX_MANIFEST):
            with self.subTest(manifest=manifest.relative_to(REPO_ROOT).as_posix()):
                self.assertEqual(load(manifest)["name"], CURRENT)

    def test_both_marketplaces_and_their_entries_carry_the_current_name(self) -> None:
        for marketplace in (CLAUDE_MARKETPLACE, AGENTS_MARKETPLACE):
            data = load(marketplace)
            with self.subTest(marketplace=marketplace.relative_to(REPO_ROOT).as_posix()):
                self.assertEqual(data["name"], CURRENT)
                self.assertEqual([entry["name"] for entry in data["plugins"]], [CURRENT])

    def test_the_codex_marketplace_points_at_the_renamed_repository(self) -> None:
        source = load(AGENTS_MARKETPLACE)["plugins"][0]["source"]
        self.assertEqual(
            source["url"], f"https://github.com/leoleonel-jf/{CURRENT}.git"
        )

    def test_the_display_name_is_the_new_one_everywhere_it_is_declared(self) -> None:
        declared = {
            "plugin.json": load(ROOT_MANIFEST)["extensions"]["com.openai"]["interface"][
                "displayName"
            ],
            ".claude-plugin/plugin.json": load(CLAUDE_MANIFEST)["displayName"],
            ".codex-plugin/plugin.json": load(CODEX_MANIFEST)["interface"]["displayName"],
            ".agents/plugins/marketplace.json": load(AGENTS_MARKETPLACE)["interface"][
                "displayName"
            ],
        }
        for where, value in declared.items():
            with self.subTest(where=where):
                self.assertEqual(value, DISPLAY)

    def test_the_canonical_skill_lives_under_the_current_name(self) -> None:
        skill = REPO_ROOT / "skills" / CURRENT / "SKILL.md"
        self.assertTrue(skill.is_file(), skill)
        self.assertRegex(
            skill.read_text(encoding="utf-8"), rf"(?m)^name: {re.escape(CURRENT)}$"
        )

    def test_no_tracked_path_carries_the_former_name(self) -> None:
        self.assertEqual([path for path in tracked_files() if FORMER in path], [])


class RenamesMapTests(unittest.TestCase):
    """Claude Code follows `renames` from the oldest name to one in `plugins`.

    The documentation: "Map each former name to its current name", and
    `claude plugin validate` "rejects a chain that cycles or that ends anywhere
    other than `null` or a name in `plugins`".
    """

    def resolve(self, name: str, renames: dict, listed: set[str]) -> str | None:
        seen = set()
        while name in renames:
            self.assertNotIn(name, seen, "the renames chain cycles")
            seen.add(name)
            name = renames[name]
            if name is None:
                return None
        self.assertIn(name, listed, "the renames chain ends outside `plugins`")
        return name

    def test_the_former_name_resolves_to_the_listed_plugin(self) -> None:
        data = load(CLAUDE_MARKETPLACE)
        renames = data.get("renames")
        self.assertIsInstance(renames, dict, "marketplace.json has no `renames` map")
        self.assertIn(FORMER, renames)
        listed = {entry["name"] for entry in data["plugins"]}
        self.assertEqual(self.resolve(FORMER, renames, listed), CURRENT)

    def test_every_chain_in_the_map_resolves(self) -> None:
        data = load(CLAUDE_MARKETPLACE)
        listed = {entry["name"] for entry in data["plugins"]}
        for former in data.get("renames", {}):
            with self.subTest(former=former):
                self.resolve(former, data["renames"], listed)


class NothingLeftBehindTests(unittest.TestCase):
    def test_the_former_identifier_stays_only_where_a_reason_is_listed(self) -> None:
        found = sorted(
            path
            for path in current_files()
            if FORMER in (text_of(path) or "")
        )
        self.assertEqual(found, sorted(FORMER_IDENTIFIER_ALLOWED))

    def test_the_former_display_name_is_gone(self) -> None:
        found = sorted(
            path
            for path in current_files()
            if FORMER_DISPLAY.search(text_of(path) or "")
        )
        self.assertEqual(found, [])

    def test_the_former_display_name_is_not_in_what_this_release_wrote(self) -> None:
        """The two history files this release added to. They name the former
        identifier, which a user has to type; never the former display name."""
        written = {
            "CHANGELOG.md, 0.11.0": newest_changelog_entry(),
            "docs/releases/v0.11.0.md": RELEASE.read_text(encoding="utf-8"),
        }
        for where, text in written.items():
            with self.subTest(where=where):
                self.assertIsNone(FORMER_DISPLAY.search(text))

    def test_history_is_still_history(self) -> None:
        """The other half of the bargain: the rename did not rewrite it."""
        for path in ("docs/releases/v0.10.0.md", "docs/releases/v0.1.0.md"):
            with self.subTest(path=path):
                self.assertIn(FORMER, text_of(path) or "")
        older = CHANGELOG.read_text(encoding="utf-8").split("\n## 0.10.0", 1)[1]
        self.assertIn(FORMER, older)


class ExistingInstallationTests(unittest.TestCase):
    """What someone who installed under the former name has to type.

    The marketplace's own name changed with the plugin, and no client migrates
    that: the steps are remove, add, install. They are stated where a user
    looks, and a later edit that drops one of them fails here.
    """

    CLAUDE_STEPS = (
        f"/plugin marketplace remove {FORMER}",
        f"/plugin marketplace add leoleonel-jf/{CURRENT}",
        f"/plugin install {CURRENT}@{CURRENT}",
        # The shorter path, through the `renames` map, for someone who keeps
        # the marketplace registered under its former name.
        f"/plugin marketplace update {FORMER}",
        f"/plugin install {CURRENT}@{FORMER}",
    )
    CODEX_STEPS = (
        f"codex plugin remove {FORMER}@{FORMER}",
        f"codex plugin marketplace remove {FORMER}",
    )

    def documents(self) -> dict[str, str]:
        """Only the part of each document written for an existing
        installation. The ordinary install sections repeat two of these
        commands, and would satisfy the tests with the migration deleted."""
        return {
            "README.md": section(
                README.read_text(encoding="utf-8"),
                f"### If you installed it as `{FORMER}`",
                "### Other Agent Skills clients",
            ),
            "CHANGELOG.md, 0.11.0": section(
                newest_changelog_entry(), "**If you installed it as", "What changed:"
            ),
            "docs/releases/v0.11.0.md": section(
                RELEASE.read_text(encoding="utf-8"),
                f"## If you installed it as `{FORMER}`",
                "## Changes",
            ),
        }

    def test_the_claude_code_steps_are_stated(self) -> None:
        for where, text in self.documents().items():
            for step in self.CLAUDE_STEPS:
                with self.subTest(where=where, step=step):
                    self.assertIn(step, text)

    def test_the_codex_steps_are_stated(self) -> None:
        for where, text in self.documents().items():
            for step in self.CODEX_STEPS:
                with self.subTest(where=where, step=step):
                    self.assertIn(step, text)

    def test_the_changed_invocation_is_stated(self) -> None:
        for where, text in self.documents().items():
            with self.subTest(where=where):
                self.assertIn(f"/{CURRENT}:dashboard", text)
                self.assertIn(f"${CURRENT}", text)

    def test_the_data_directory_is_said_to_stay_where_it_is(self) -> None:
        for where, text in self.documents().items():
            with self.subTest(where=where):
                collapsed = " ".join(text.split())
                self.assertIn(f"<user-config>/{FORMER}/", collapsed)
                self.assertIn("keeps using it", collapsed)

    def test_nothing_calls_the_directory_move_the_whole_migration(self) -> None:
        """It is not, for a ledger whose run keeps a backup inside it."""
        for where, text in self.documents().items():
            with self.subTest(where=where):
                self.assertNotIn("whole migration", " ".join(text.split()))

    def test_what_was_tried_is_said_as_what_was_tried(self) -> None:
        """The trial drove `claude plugin` and `codex plugin` against a
        marketplace added by URL. The documents show `/plugin` commands and
        an `owner/repo` marketplace, and say that those were not tried."""
        for where in ("CHANGELOG.md, 0.11.0", "docs/releases/v0.11.0.md"):
            collapsed = " ".join(self.documents()[where].split())
            with self.subTest(where=where):
                self.assertIn("were not tried", collapsed)
                self.assertIn("added by URL", collapsed)


if __name__ == "__main__":
    unittest.main()
