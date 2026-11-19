"""The plugin's manifests and its second skill, against the formats they follow.

Spec `docs/specs/2026-11-19-plugin-formats.md`. Three manifests describe one
plugin to three readers: the root `plugin.json` (Agent Plugins 1.0.0), the
Claude Code manifest and the Codex compatibility overlay. Nothing in any
client compares them, so a field edited in one place is silently stale in the
others. These tests are that comparison, plus the limits a directory states
and the one thing a user meets first: `/dashboard` finding its script.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging" / "scripts"))

import package_plugin  # noqa: E402

ROOT_MANIFEST = REPO_ROOT / "plugin.json"
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
SKILLS_ROOT = REPO_ROOT / "skills"
DASHBOARD_SKILL = SKILLS_ROOT / "dashboard" / "SKILL.md"

# Agent Plugins 1.0.0, section 5.2: the schema is closed.
PERMITTED_ROOT_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
CANONICAL_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
# Section 5.5: 1 to 64 characters of `a-z`, `0-9`, `-` and `.`, alphanumeric at
# both ends, and neither `--` nor `..` anywhere.
PLUGIN_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
REVERSE_DOMAIN = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+$")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def frontmatter(path: Path) -> dict[str, str]:
    """The flat `key: value` pairs of a SKILL.md front matter block.

    Deliberately not a YAML parser: the bundle is standard library only, and
    every field these tests read is a one-line scalar.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"{path}: no front matter")
    block = text[4 : text.index("\n---\n", 4)]
    pairs: dict[str, str] = {}
    for line in block.splitlines():
        key, separator, value = line.partition(":")
        if separator and not line.startswith((" ", "\t")):
            pairs[key.strip()] = value.strip().strip('"')
    return pairs


class RootManifestTests(unittest.TestCase):
    """`plugin.json` at the root, as Agent Plugins 1.0.0 requires it."""

    def test_the_schema_is_the_canonical_identifier(self) -> None:
        self.assertEqual(load(ROOT_MANIFEST)["$schema"], CANONICAL_SCHEMA)

    def test_no_field_outside_the_closed_schema(self) -> None:
        self.assertEqual(sorted(set(load(ROOT_MANIFEST)) - PERMITTED_ROOT_FIELDS), [])

    def test_the_name_is_inside_the_specification_grammar(self) -> None:
        name = load(ROOT_MANIFEST)["name"]
        self.assertRegex(name, PLUGIN_NAME)
        self.assertNotIn("--", name)
        self.assertNotIn("..", name)

    def test_extension_namespaces_are_reverse_domain_objects(self) -> None:
        extensions = load(ROOT_MANIFEST)["extensions"]
        self.assertTrue(extensions, "no extension namespace at all")
        for namespace, value in extensions.items():
            with self.subTest(namespace=namespace):
                self.assertRegex(namespace, REVERSE_DOMAIN)
                self.assertIsInstance(value, dict)


class ManifestAgreementTests(unittest.TestCase):
    """One plugin, three manifests, and nothing but these tests comparing them."""

    def test_name_version_and_description_agree_everywhere(self) -> None:
        root = load(ROOT_MANIFEST)
        for field in ("name", "version", "description"):
            for path in (CLAUDE_MANIFEST, CODEX_MANIFEST):
                with self.subTest(field=field, manifest=path.parent.name):
                    self.assertEqual(load(path)[field], root[field])

    def test_the_two_openai_interface_objects_are_identical(self) -> None:
        """OpenAI reads `extensions.com.openai` INSTEAD of the overlay when it
        is present, never merged with it. A field corrected only in the
        overlay would therefore be corrected for nobody."""
        inline = load(ROOT_MANIFEST)["extensions"]["com.openai"]["interface"]
        overlay = load(CODEX_MANIFEST)["interface"]
        self.assertEqual(inline, overlay)

    def test_the_packager_refuses_a_root_manifest_that_disagrees(self) -> None:
        original = ROOT_MANIFEST.read_bytes()
        document = json.loads(original)
        document["version"] = "0.0.1"
        try:
            ROOT_MANIFEST.write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            with self.assertRaises(package_plugin.PackagingError):
                package_plugin.validate_sources()
        finally:
            ROOT_MANIFEST.write_bytes(original)


class DirectoryLimitTests(unittest.TestCase):
    """The limits the OpenAI directory states for a submission."""

    def interface(self) -> dict:
        return load(CODEX_MANIFEST)["interface"]

    def test_display_name_and_short_description_fit_thirty_characters(self) -> None:
        for field in ("displayName", "shortDescription"):
            with self.subTest(field=field):
                value = self.interface()[field]
                self.assertTrue(value)
                self.assertLessEqual(len(value), 30, value)

    def test_long_description_fits_four_thousand_characters(self) -> None:
        self.assertLessEqual(len(self.interface()["longDescription"]), 4000)

    def test_at_most_three_default_prompts_of_at_most_128_characters(self) -> None:
        prompts = self.interface()["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertLessEqual(len(prompt), 128)

    def test_the_four_urls_are_present_and_https(self) -> None:
        for field in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
            with self.subTest(field=field):
                value = self.interface().get(field)
                self.assertIsInstance(value, str, f"{field} is missing")
                self.assertTrue(value.startswith("https://"), value)
                self.assertLessEqual(len(value), 1024)

    def test_the_icons_exist(self) -> None:
        for field in ("logo", "composerIcon"):
            with self.subTest(field=field):
                self.assertTrue((REPO_ROOT / self.interface()[field]).is_file())


class DashboardSkillTests(unittest.TestCase):
    """`/dashboard` as a plugin skill that finds its script from anywhere."""

    def plugin_name(self) -> str:
        return load(ROOT_MANIFEST)["name"]

    def invocation(self) -> str:
        return (
            "${CLAUDE_PLUGIN_ROOT}/skills/"
            + self.plugin_name()
            + "/assets/scripts/dashboard.py"
        )

    def test_no_command_file_is_left(self) -> None:
        """Files, not the directory: git does not track an empty one, so a
        leftover `commands/` in a working tree ships nothing and means nothing.
        A file in it would be a second `/dashboard` under the same name."""
        leftovers = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "commands").rglob("*")
            if path.is_file()
        ]
        self.assertEqual(leftovers, [])

    def test_the_skill_keeps_the_command_name(self) -> None:
        """In a plugin a skill is invoked as `/<plugin>:<directory>`, and a
        front matter `name` replaces the directory. Both must say `dashboard`
        or the name people already type stops working."""
        self.assertEqual(DASHBOARD_SKILL.parent.name, "dashboard")
        self.assertEqual(frontmatter(DASHBOARD_SKILL)["name"], "dashboard")

    def test_the_skill_keeps_its_description_and_argument_hint(self) -> None:
        fields = frontmatter(DASHBOARD_SKILL)
        self.assertTrue(fields.get("description"))
        self.assertIn("all|ledger|anchors", fields.get("argument-hint", ""))

    def test_the_model_cannot_invoke_it_unasked(self) -> None:
        """Two of its three words append to a ledger. As a command it ran
        only when typed; a skill is offered to the model unless it says no."""
        self.assertEqual(frontmatter(DASHBOARD_SKILL).get("disable-model-invocation"), "true")
        policy = (DASHBOARD_SKILL.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(policy, r"(?m)^\s+allow_implicit_invocation:\s*false\s*$")

    def test_the_script_is_invoked_through_the_plugin_root(self) -> None:
        self.assertIn(self.invocation(), DASHBOARD_SKILL.read_text(encoding="utf-8"))

    def test_no_repository_relative_invocation_is_left(self) -> None:
        """The defect this increment exists for: `python skills/...` resolves
        only when the working directory is this repository."""
        text = DASHBOARD_SKILL.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"python\s+skills/")
        self.assertNotRegex(text, r"python\s+\"?\.?/?skills/")

    def test_the_skill_says_where_the_script_is_without_the_variable(self) -> None:
        text = " ".join(DASHBOARD_SKILL.read_text(encoding="utf-8").split())
        self.assertIn(
            "../" + self.plugin_name() + "/assets/scripts/dashboard.py", text
        )

    def test_the_invocation_resolves_inside_the_built_archive(self) -> None:
        """Replace the variable with where the archive was extracted and the
        path must name a file, and that file must run from another directory."""
        with tempfile.TemporaryDirectory() as temp:
            plugin_archive, _, _ = package_plugin.build(Path(temp) / "dist")
            root = Path(temp) / "installed"
            with zipfile.ZipFile(plugin_archive) as archive:
                archive.extractall(root)
            script = Path(self.invocation().replace("${CLAUDE_PLUGIN_ROOT}", str(root)))
            self.assertTrue(script.is_file(), script)
            elsewhere = Path(temp) / "another-project"
            elsewhere.mkdir()
            result = subprocess.run(
                [sys.executable, str(script), "update", "--help"],
                cwd=elsewhere,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--strict", result.stdout)

    def test_the_main_skill_says_where_dashboard_py_is(self) -> None:
        text = (SKILLS_ROOT / self.plugin_name() / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`assets/scripts/dashboard.py`", text)


class ArchiveFormatTests(unittest.TestCase):
    def names(self) -> tuple[list[str], list[str]]:
        with tempfile.TemporaryDirectory() as temp:
            plugin_archive, skill_archive, _ = package_plugin.build(Path(temp))
            with zipfile.ZipFile(plugin_archive) as archive:
                plugin = archive.namelist()
            with zipfile.ZipFile(skill_archive) as archive:
                skill = archive.namelist()
        return plugin, skill

    def test_the_plugin_archive_ships_the_root_manifest(self) -> None:
        plugin, _ = self.names()
        self.assertIn("plugin.json", plugin)

    def test_the_plugin_archive_ships_every_file_under_skills(self) -> None:
        plugin, _ = self.names()
        offered = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in SKILLS_ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in (".pyc", ".pyo", ".pyd")
        )
        self.assertIn("skills/dashboard/SKILL.md", offered)
        self.assertEqual(sorted(set(offered) - set(plugin)), [])

    def test_the_portable_skill_archive_still_holds_one_skill(self) -> None:
        """The dashboard skill needs its sibling's script, so it is a plugin
        component and not part of the portable bundle."""
        _, skill = self.names()
        self.assertEqual({name.split("/", 1)[0] for name in skill}, {load(ROOT_MANIFEST)["name"]})
        self.assertFalse([name for name in skill if "dashboard/SKILL.md" in name])


if __name__ == "__main__":
    unittest.main()
