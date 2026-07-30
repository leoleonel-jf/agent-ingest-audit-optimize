"""Tests for `ledgerlib.adapters`: the adapter format and its anchor roots.

The suite loads `dashboard.py` by file path exactly the way
`test_dashboard.py` does. That import has a side effect this module depends
on: `dashboard.py` inserts its own directory at the front of `sys.path`
before importing `ledgerlib`, so `from ledgerlib import adapters` below
resolves to the bundle's copy rather than to anything installed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = (
    REPO_ROOT / "skills" / "agent-ingest-audit-optimize" / "assets" / "scripts"
)
SCRIPT = SCRIPTS / "dashboard.py"
ADAPTER_SCHEMA = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "schemas"
    / "adapter.schema.json"
)
ADAPTERS_DIR = (
    REPO_ROOT / "skills" / "agent-ingest-audit-optimize" / "assets" / "adapters"
)
RESEARCH = (
    REPO_ROOT / "docs" / "research" / "2026-07-30-client-configuration-paths.md"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib import adapters, constants  # noqa: E402
from ledgerlib.errors import LedgerError  # noqa: E402
from ledgerlib.paths import anchor_path, resolve_anchored  # noqa: E402


def minimal_adapter() -> dict:
    return {
        "adapter_version": 1,
        "client": "claude-code",
        "expires_on": "2026-10-28",
        "anchors": {
            "$USER_CONFIG": ["$env:CLAUDE_CONFIG_DIR", "~/.claude"],
            "$PROJECT": ["."],
        },
        "probes": [
            {
                "kind": "instruction-file",
                "scope": "user",
                "glob": "$USER_CONFIG/CLAUDE.md",
            }
        ],
        "sensitive_key_patterns": ["*token*", "env"],
    }


def with_probe(probe: dict) -> dict:
    data = minimal_adapter()
    data["probes"] = [probe]
    return data


class AdapterDocumentTests(unittest.TestCase):
    """One test per field rule in spec section 3.2, each on its own message."""

    def findings(self, data: dict) -> list[str]:
        return adapters.validate_adapter(data, source="test")

    def test_minimal_adapter_has_no_findings(self) -> None:
        self.assertEqual(self.findings(minimal_adapter()), [])

    def test_adapter_must_be_an_object(self) -> None:
        self.assertEqual(
            adapters.validate_adapter([], source="test"),
            ["test: adapter must be a JSON object"],
        )

    def test_adapter_version_missing(self) -> None:
        data = minimal_adapter()
        del data["adapter_version"]
        self.assertEqual(
            self.findings(data), ["test: missing fields: ['adapter_version']"]
        )

    def test_adapter_version_non_integer(self) -> None:
        data = minimal_adapter()
        data["adapter_version"] = "1"
        self.assertEqual(
            self.findings(data),
            ["test: adapter_version must be an integer of at least 1"],
        )

    def test_adapter_version_zero(self) -> None:
        data = minimal_adapter()
        data["adapter_version"] = 0
        self.assertEqual(
            self.findings(data),
            ["test: adapter_version must be an integer of at least 1"],
        )

    def test_client_missing(self) -> None:
        data = minimal_adapter()
        del data["client"]
        self.assertEqual(self.findings(data), ["test: missing fields: ['client']"])

    def test_client_empty(self) -> None:
        data = minimal_adapter()
        data["client"] = ""
        self.assertEqual(self.findings(data), ["test: client must be a non-empty string"])

    def test_client_uppercase(self) -> None:
        data = minimal_adapter()
        data["client"] = "Claude-Code"
        self.assertEqual(
            self.findings(data), ["test: client must match [a-z0-9-]+: 'Claude-Code'"]
        )

    def test_client_containing_a_space(self) -> None:
        data = minimal_adapter()
        data["client"] = "claude code"
        self.assertEqual(
            self.findings(data), ["test: client must match [a-z0-9-]+: 'claude code'"]
        )

    def test_expires_on_missing(self) -> None:
        data = minimal_adapter()
        del data["expires_on"]
        self.assertEqual(self.findings(data), ["test: missing fields: ['expires_on']"])

    def test_expires_on_malformed(self) -> None:
        data = minimal_adapter()
        data["expires_on"] = "28-10-2026"
        self.assertEqual(self.findings(data), ["test: expires_on must match YYYY-MM-DD"])

    def test_anchors_not_an_object(self) -> None:
        data = minimal_adapter()
        data["anchors"] = ["$USER_CONFIG"]
        self.assertEqual(self.findings(data), ["test: anchors must be an object"])

    def test_anchor_name_without_a_dollar(self) -> None:
        data = minimal_adapter()
        data["anchors"] = {"USER_CONFIG": ["~/.claude"]}
        self.assertEqual(
            self.findings(data),
            ["test: anchors has an invalid anchor name: 'USER_CONFIG'"],
        )

    def test_anchor_candidate_list_empty(self) -> None:
        data = minimal_adapter()
        data["anchors"] = {"$USER_CONFIG": []}
        self.assertEqual(
            self.findings(data),
            ["test: anchors.$USER_CONFIG must be a non-empty array of candidates"],
        )

    def test_anchor_candidate_not_a_string(self) -> None:
        data = minimal_adapter()
        data["anchors"] = {"$USER_CONFIG": [3]}
        self.assertEqual(
            self.findings(data),
            ["test: anchors.$USER_CONFIG[0] must be a non-empty string: 3"],
        )

    def test_probes_not_an_array(self) -> None:
        data = minimal_adapter()
        data["probes"] = {}
        self.assertEqual(self.findings(data), ["test: probes must be an array"])

    def test_probes_may_be_empty(self) -> None:
        data = minimal_adapter()
        data["probes"] = []
        self.assertEqual(self.findings(data), [])

    def test_probe_not_an_object(self) -> None:
        data = minimal_adapter()
        data["probes"] = ["$USER_CONFIG/CLAUDE.md"]
        self.assertEqual(self.findings(data), ["test: probes[0] must be an object"])

    def test_probe_missing_kind(self) -> None:
        data = with_probe({"glob": "$USER_CONFIG/CLAUDE.md"})
        self.assertEqual(self.findings(data), ["test: probes[0] missing fields: ['kind']"])

    def test_probe_with_an_unknown_field(self) -> None:
        data = with_probe({"kind": "skill", "glob": "$USER_CONFIG/x", "note": "hi"})
        self.assertEqual(
            self.findings(data), ["test: probes[0] has unknown fields: ['note']"]
        )

    def test_probe_with_neither_glob_nor_path(self) -> None:
        data = with_probe({"kind": "skill"})
        self.assertEqual(
            self.findings(data),
            ["test: probes[0] must have exactly one of glob or path: it has neither"],
        )

    def test_probe_with_both_glob_and_path(self) -> None:
        data = with_probe(
            {
                "kind": "skill",
                "glob": "$USER_CONFIG/skills/*/SKILL.md",
                "path": "$USER_CONFIG/settings.json",
            }
        )
        self.assertEqual(
            self.findings(data),
            ["test: probes[0] must have exactly one of glob or path: it has both"],
        )

    def test_probe_kind_outside_the_closed_enum(self) -> None:
        data = with_probe({"kind": "nonsense", "glob": "$USER_CONFIG/x"})
        self.assertEqual(
            self.findings(data), ["test: probes[0] has an invalid kind: 'nonsense'"]
        )

    def test_probe_kind_enum_is_the_baseline_item_enum(self) -> None:
        """Every kind the ledger accepts is a kind a probe may declare."""
        for kind in sorted(constants.BASELINE_ITEM_KINDS):
            with self.subTest(kind=kind):
                data = with_probe({"kind": kind, "glob": "$USER_CONFIG/x"})
                self.assertEqual(self.findings(data), [])

    def test_parse_outside_json_and_toml(self) -> None:
        data = with_probe(
            {"kind": "mcp-server", "path": "$USER_CONFIG/config.yaml", "parse": "yaml"}
        )
        self.assertEqual(
            self.findings(data), ["test: probes[0] has an invalid parse: 'yaml'"]
        )

    def test_parse_given_with_glob_instead_of_path(self) -> None:
        data = with_probe(
            {"kind": "mcp-server", "glob": "$USER_CONFIG/*.json", "parse": "json"}
        )
        self.assertEqual(
            self.findings(data), ["test: probes[0] parse requires path, not glob"]
        )

    def test_pointer_without_parse(self) -> None:
        data = with_probe(
            {
                "kind": "mcp-server",
                "path": "$USER_CONFIG/settings.json",
                "pointer": "/mcpServers",
            }
        )
        self.assertEqual(self.findings(data), ["test: probes[0] pointer requires parse"])

    def test_pointer_not_starting_with_a_slash(self) -> None:
        data = with_probe(
            {
                "kind": "mcp-server",
                "path": "$USER_CONFIG/settings.json",
                "parse": "json",
                "pointer": "mcpServers",
            }
        )
        self.assertEqual(
            self.findings(data),
            ["test: probes[0] pointer must start with '/': 'mcpServers'"],
        )

    def test_scope_present_but_empty(self) -> None:
        data = with_probe({"kind": "skill", "scope": "", "glob": "$USER_CONFIG/x"})
        self.assertEqual(
            self.findings(data), ["test: probes[0] scope must be a non-empty string: ''"]
        )

    def test_sensitive_key_patterns_missing(self) -> None:
        data = minimal_adapter()
        del data["sensitive_key_patterns"]
        self.assertEqual(
            self.findings(data), ["test: missing fields: ['sensitive_key_patterns']"]
        )

    def test_sensitive_key_patterns_not_an_array(self) -> None:
        data = minimal_adapter()
        data["sensitive_key_patterns"] = "*token*"
        self.assertEqual(
            self.findings(data), ["test: sensitive_key_patterns must be an array"]
        )

    def test_sensitive_key_patterns_containing_a_non_string(self) -> None:
        data = minimal_adapter()
        data["sensitive_key_patterns"] = [3]
        self.assertEqual(
            self.findings(data),
            ["test: sensitive_key_patterns[0] must be a non-empty string: 3"],
        )

    def test_sensitive_key_patterns_may_be_empty(self) -> None:
        data = minimal_adapter()
        data["sensitive_key_patterns"] = []
        self.assertEqual(self.findings(data), [])

    def test_unknown_top_level_field(self) -> None:
        data = minimal_adapter()
        data["probe"] = []
        self.assertEqual(self.findings(data), ["test: unknown fields: ['probe']"])


class AdapterPathSafetyAtLoadTests(unittest.TestCase):
    """`check_glob` runs at load, before any probe could expand."""

    def findings(self, data: dict) -> list[str]:
        return adapters.validate_adapter(data, source="test")

    def test_glob_with_a_dotdot_segment_is_refused_naming_the_reason(self) -> None:
        pattern = "$USER_CONFIG/../secrets/*.json"
        found = self.findings(with_probe({"kind": "skill", "glob": pattern}))
        self.assertEqual(len(found), 1, found)
        self.assertTrue(
            found[0].startswith("test: probes[0] glob is refused by check_glob"), found[0]
        )
        self.assertIn("glob_dotdot_segment", found[0])
        self.assertIn(repr(pattern), found[0])

    def test_path_with_a_dotdot_segment_is_refused_naming_the_reason(self) -> None:
        pattern = "$USER_CONFIG/../.ssh/id_ed25519"
        found = self.findings(with_probe({"kind": "skill", "path": pattern}))
        self.assertEqual(len(found), 1, found)
        self.assertTrue(
            found[0].startswith("test: probes[0] path is refused by check_glob"), found[0]
        )
        self.assertIn("glob_dotdot_segment", found[0])
        self.assertIn(repr(pattern), found[0])

    def test_posix_absolute_glob_is_refused(self) -> None:
        pattern = "/etc/*.conf"
        found = self.findings(with_probe({"kind": "skill", "glob": pattern}))
        self.assertEqual(len(found), 1, found)
        self.assertIn("glob_absolute", found[0])
        self.assertIn(repr(pattern), found[0])

    def test_windows_absolute_path_is_refused(self) -> None:
        pattern = "C:/Users/someone/.claude/settings.json"
        found = self.findings(with_probe({"kind": "skill", "path": pattern}))
        self.assertEqual(len(found), 1, found)
        self.assertIn("glob_absolute", found[0])
        self.assertIn(repr(pattern), found[0])

    def test_a_refused_glob_is_refused_by_load_adapter_too(self) -> None:
        data = with_probe({"kind": "skill", "glob": "$USER_CONFIG/../x"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(LedgerError) as caught:
                adapters.load_adapter(path)
        self.assertIn("glob_dotdot_segment", str(caught.exception))


class LoadAdapterTests(unittest.TestCase):
    def test_a_valid_adapter_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.json"
            path.write_text(json.dumps(minimal_adapter()), encoding="utf-8")
            self.assertEqual(adapters.load_adapter(path), minimal_adapter())

    def test_an_invalid_adapter_raises_joining_every_finding(self) -> None:
        data = minimal_adapter()
        data["client"] = ""
        data["expires_on"] = "nope"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(LedgerError) as caught:
                adapters.load_adapter(path)
        message = str(caught.exception)
        self.assertIn("client must be a non-empty string", message)
        self.assertIn("expires_on must match YYYY-MM-DD", message)

    def test_the_source_of_a_finding_is_the_file(self) -> None:
        data = minimal_adapter()
        data["client"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(LedgerError) as caught:
                adapters.load_adapter(path)
            self.assertIn(str(path), str(caught.exception))

    def test_a_missing_file_raises_a_ledger_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LedgerError):
                adapters.load_adapter(Path(tmp) / "absent.json")


class SchemaAgreementTests(unittest.TestCase):
    """The `.json` file is documentation; the validator is what runs.

    Nothing in the bundle reads `adapter.schema.json` at runtime -- there is
    no JSON Schema library and there never will be one. These tests are the
    only thing standing between the documented format and the enforced one,
    so every one of them compares two sets for equality and therefore fails
    in both directions: a rule added to the schema alone, and a rule added to
    the validator alone.
    """

    def setUp(self) -> None:
        self.schema = json.loads(ADAPTER_SCHEMA.read_text(encoding="utf-8"))
        self.probe = self.schema["definitions"]["probe"]

    def test_schema_kind_enum_equals_baseline_item_kinds(self) -> None:
        self.assertEqual(
            set(self.probe["properties"]["kind"]["enum"]),
            set(constants.BASELINE_ITEM_KINDS),
        )

    def test_schema_required_equals_the_validator_required_fields(self) -> None:
        self.assertEqual(
            set(self.schema["required"]), set(adapters.REQUIRED_ADAPTER_FIELDS)
        )

    def test_schema_properties_equal_the_validator_known_fields(self) -> None:
        self.assertEqual(
            set(self.schema["properties"]), set(adapters.REQUIRED_ADAPTER_FIELDS)
        )

    def test_schema_probe_required_equals_the_validator_required_probe_fields(
        self,
    ) -> None:
        self.assertEqual(
            set(self.probe["required"]), set(adapters.REQUIRED_PROBE_FIELDS)
        )

    def test_schema_probe_properties_equal_the_validator_known_probe_fields(
        self,
    ) -> None:
        self.assertEqual(set(self.probe["properties"]), set(adapters.PROBE_FIELDS))

    def test_schema_parse_enum_equals_the_validator_parse_formats(self) -> None:
        self.assertEqual(
            set(self.probe["properties"]["parse"]["enum"]), set(adapters.PARSE_FORMATS)
        )


class AnchorRootTests(unittest.TestCase):
    """`resolve_anchor_roots`: `$env:`, `~`, and the first candidate that exists."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.project = self.root / "project"
        self.project.mkdir()
        # `expanduser` reads the process environment by construction; there is
        # no parameter for it. Patched per test rather than mutated globally.
        self.home_env = mock.patch.dict(
            os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        )
        self.home_env.start()
        self.addCleanup(self.home_env.stop)

    def resolve(self, candidates: list[str], environ: dict[str, str] | None = None):
        adapter = minimal_adapter()
        adapter["anchors"] = {"$USER_CONFIG": candidates}
        return adapters.resolve_anchor_roots(
            adapter, project=self.project, environ=environ or {}
        )

    def test_env_candidate_wins_over_a_default_that_also_exists(self) -> None:
        relocated = self.root / "relocated"
        relocated.mkdir()
        roots, unresolved = self.resolve(
            ["$env:CLAUDE_CONFIG_DIR", "~/.claude"],
            {"CLAUDE_CONFIG_DIR": str(relocated)},
        )
        self.assertEqual(roots, {"USER_CONFIG": relocated})
        self.assertEqual(unresolved, [])

    def test_env_candidate_naming_a_missing_directory_falls_through(self) -> None:
        """The failure the research warns about: scanning a tree nobody uses.

        A naive implementation stops at the first `$env:` candidate that is
        *set* rather than the first that *resolves*, scans a directory that
        does not exist, finds nothing, and reports a clean baseline for a
        configuration it never looked at.
        """
        roots, unresolved = self.resolve(
            ["$env:CLAUDE_CONFIG_DIR", "~/.claude"],
            {"CLAUDE_CONFIG_DIR": str(self.root / "does-not-exist")},
        )
        self.assertEqual(roots, {"USER_CONFIG": (self.home / ".claude").resolve()})
        self.assertEqual(unresolved, [])

    def test_env_candidate_set_to_the_empty_string_is_treated_as_unset(self) -> None:
        roots, unresolved = self.resolve(
            ["$env:CLAUDE_CONFIG_DIR", "~/.claude"], {"CLAUDE_CONFIG_DIR": ""}
        )
        self.assertEqual(roots, {"USER_CONFIG": (self.home / ".claude").resolve()})
        self.assertEqual(unresolved, [])

    def test_env_candidate_unset_is_skipped(self) -> None:
        roots, unresolved = self.resolve(["$env:CODEX_HOME", "~/.claude"], {})
        self.assertEqual(roots, {"USER_CONFIG": (self.home / ".claude").resolve()})
        self.assertEqual(unresolved, [])

    def test_the_process_environment_is_never_read(self) -> None:
        """`environ` is a parameter; a set variable outside it must not win."""
        relocated = self.root / "relocated"
        relocated.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(relocated)}):
            roots, unresolved = self.resolve(["$env:CLAUDE_CONFIG_DIR"], {})
        self.assertEqual(roots, {})
        self.assertEqual(unresolved, ["USER_CONFIG"])

    def test_a_tilde_candidate_expands_against_the_home_directory(self) -> None:
        roots, _ = self.resolve(["~/.claude"])
        self.assertEqual(roots["USER_CONFIG"], (self.home / ".claude").resolve())

    def test_dot_resolves_against_the_project_argument_not_the_cwd(self) -> None:
        adapter = minimal_adapter()
        adapter["anchors"] = {"$PROJECT": ["."]}
        roots, unresolved = adapters.resolve_anchor_roots(
            adapter, project=self.project, environ={}
        )
        self.assertEqual(roots, {"PROJECT": self.project})
        self.assertNotEqual(self.project, Path.cwd().resolve())
        self.assertEqual(unresolved, [])

    def test_a_relative_candidate_resolves_under_the_project(self) -> None:
        (self.project / ".claude").mkdir()
        roots, _ = self.resolve([".claude"])
        self.assertEqual(roots["USER_CONFIG"], (self.project / ".claude").resolve())

    def test_no_candidate_resolving_leaves_the_anchor_unresolved(self) -> None:
        roots, unresolved = self.resolve(
            ["$env:NOPE", str(self.root / "absent")], {}
        )
        self.assertEqual(roots, {})
        self.assertEqual(unresolved, ["USER_CONFIG"])
        self.assertNotIn("USER_CONFIG", roots)

    def test_a_candidate_that_is_a_file_does_not_qualify(self) -> None:
        a_file = self.root / "a-file"
        a_file.write_text("not a directory", encoding="utf-8")
        directory = self.root / "a-directory"
        directory.mkdir()
        roots, unresolved = self.resolve([str(a_file), str(directory)], {})
        self.assertEqual(roots, {"USER_CONFIG": directory})
        self.assertEqual(unresolved, [])

    def test_a_file_only_anchor_is_unresolved(self) -> None:
        a_file = self.root / "a-file"
        a_file.write_text("not a directory", encoding="utf-8")
        roots, unresolved = self.resolve([str(a_file)], {})
        self.assertEqual(roots, {})
        self.assertEqual(unresolved, ["USER_CONFIG"])

    def test_returned_roots_are_absolute_and_resolved(self) -> None:
        roots, _ = self.resolve(["~/.claude"])
        root = roots["USER_CONFIG"]
        self.assertTrue(root.is_absolute())
        self.assertEqual(root, root.resolve())

    def test_returned_roots_are_keyed_the_way_the_path_layer_expects(self) -> None:
        """`anchor_path` and `resolve_anchored` reject a `$` in a root key."""
        roots, _ = self.resolve(["~/.claude"])
        self.assertEqual(sorted(roots), ["USER_CONFIG"])
        target = self.home / ".claude" / "CLAUDE.md"
        target.write_text("hello", encoding="utf-8")
        stored, portable = anchor_path(target, roots)
        self.assertEqual(stored, "$USER_CONFIG/CLAUDE.md")
        self.assertTrue(portable)
        self.assertEqual(resolve_anchored(stored, roots), target.resolve())

    def test_every_anchor_in_the_adapter_is_accounted_for(self) -> None:
        adapter = minimal_adapter()
        adapter["anchors"] = {
            "$USER_CONFIG": ["~/.claude"],
            "$PROJECT": ["."],
            "$NOWHERE": [str(self.root / "absent")],
        }
        roots, unresolved = adapters.resolve_anchor_roots(
            adapter, project=self.project, environ={}
        )
        self.assertEqual(sorted(roots) + unresolved, ["PROJECT", "USER_CONFIG", "NOWHERE"])

    def test_an_adapter_without_anchors_resolves_to_nothing(self) -> None:
        roots, unresolved = adapters.resolve_anchor_roots(
            {"anchors": {}}, project=self.project, environ={}
        )
        self.assertEqual((roots, unresolved), ({}, []))


class BundledAdapterTests(unittest.TestCase):
    """The three shipped adapters, against the research that produced them.

    Everything here that can be parametrised over `assets/adapters/` is,
    rather than over a hardcoded list of three names: a fourth adapter added
    later is then covered the day it lands instead of the day someone
    remembers to edit this file. The directory is globbed inside each test,
    not at import time, so the parametrisation is over what is on disk now.

    `expires_on` is compared against the date read out of the research
    document itself. Hardcoding `2026-10-28` here would create a second place
    to change when the research is refreshed, and the second place is the one
    that gets missed.
    """

    ALLOWED_SCOPES = {"user", "project", "managed", "system"}

    def adapter_paths(self) -> list[Path]:
        paths = sorted(ADAPTERS_DIR.glob("*.json"))
        # Without this the parametrised tests below pass vacuously the day
        # the directory goes missing from the bundle.
        self.assertTrue(paths, f"no adapters found in {ADAPTERS_DIR}")
        return paths

    def read_adapter(self, name: str) -> dict:
        return json.loads((ADAPTERS_DIR / name).read_text(encoding="utf-8"))

    def probe_pattern(self, probe: dict) -> str:
        """The one of `glob` or `path` a probe carries."""
        pattern = probe.get("glob", probe.get("path"))
        self.assertIsInstance(pattern, str, probe)
        return pattern

    def research_expiry(self) -> str:
        text = RESEARCH.read_text(encoding="utf-8")
        match = re.search(r"^Expires:\s*(\d{4}-\d{2}-\d{2})", text, re.MULTILINE)
        self.assertIsNotNone(match, f"no 'Expires: YYYY-MM-DD' line in {RESEARCH}")
        assert match is not None
        return match.group(1)

    def test_every_bundled_adapter_loads_and_validates(self) -> None:
        for path in self.adapter_paths():
            with self.subTest(adapter=path.name):
                data = adapters.load_adapter(path)
                self.assertIsInstance(data, dict)
                self.assertEqual(data["client"], path.stem)

    def test_every_bundled_adapter_expires_with_the_research(self) -> None:
        expiry = self.research_expiry()
        for path in self.adapter_paths():
            with self.subTest(adapter=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["expires_on"], expiry)

    def test_every_probe_declares_a_scope_from_the_research_levels(self) -> None:
        for path in self.adapter_paths():
            data = json.loads(path.read_text(encoding="utf-8"))
            for index, probe in enumerate(data["probes"]):
                with self.subTest(adapter=path.name, probe=index):
                    self.assertIn(probe.get("scope"), self.ALLOWED_SCOPES)

    def test_generic_probes_nothing(self) -> None:
        """Design spec section 9: the generic adapter's whole point."""
        self.assertEqual(self.read_adapter("generic.json")["probes"], [])

    def test_claude_code_never_probes_agents_md(self) -> None:
        """Research finding 1: Claude Code reads CLAUDE.md, not AGENTS.md.

        A probe here would record an inert file as live configuration.
        """
        for probe in self.read_adapter("claude-code.json")["probes"]:
            pattern = self.probe_pattern(probe)
            final = pattern.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            self.assertNotEqual(final.casefold(), "agents.md", pattern)

    def test_claude_code_user_config_begins_with_the_environment_variable(self) -> None:
        anchors = self.read_adapter("claude-code.json")["anchors"]
        self.assertEqual(anchors["$USER_CONFIG"][0], "$env:CLAUDE_CONFIG_DIR")

    def test_codex_user_config_begins_with_the_environment_variable(self) -> None:
        anchors = self.read_adapter("codex.json")["anchors"]
        self.assertEqual(anchors["$USER_CONFIG"][0], "$env:CODEX_HOME")

    def test_codex_probes_both_skills_roots(self) -> None:
        """Research section 6: documented and undocumented, probe both."""
        patterns = [
            self.probe_pattern(probe)
            for probe in self.read_adapter("codex.json")["probes"]
        ]
        self.assertTrue(
            any(p.startswith("$HOME/.agents/skills/") for p in patterns), patterns
        )
        self.assertTrue(
            any(p.startswith("$USER_CONFIG/skills/") for p in patterns), patterns
        )

    def test_every_adapter_but_generic_has_sensitive_key_patterns(self) -> None:
        """The research names MCP `env` blocks as secret-bearing in both clients."""
        for path in self.adapter_paths():
            if path.name == "generic.json":
                continue
            with self.subTest(adapter=path.name):
                patterns = json.loads(path.read_text(encoding="utf-8"))[
                    "sensitive_key_patterns"
                ]
                self.assertTrue(patterns, path.name)
                self.assertIn("env", patterns)


class SelectAdapterTests(unittest.TestCase):
    """`select_adapter`: precedence, detection, and the unknown-client flow.

    The bundled directory is built in a temporary tree rather than pointed at
    `assets/adapters/`, so these tests state the selection rules and not the
    current contents of the three shipped files.
    `RealBundledSelectionTests` below is the one that runs against the shipped
    directory, so a shipped adapter that stops being selectable is still
    caught.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.bundled = self.root / "bundled"
        self.bundled.mkdir()
        self.user_config = self.root / "user-config"
        self.user_adapters = (
            self.user_config / "agent-ingest-audit-optimize" / "adapters"
        )
        self.project = self.root / "project"
        self.project.mkdir()
        self.write_adapter(self.bundled, "generic.json", self.document("generic"))

    # -- fixtures ---------------------------------------------------------

    def document(self, client: str, *, user_config: list[str] | None = None) -> dict:
        data = {
            "adapter_version": 1,
            "client": client,
            "expires_on": "2026-10-28",
            "anchors": {"$PROJECT": ["."]},
            "probes": [],
            "sensitive_key_patterns": [],
        }
        if user_config is not None:
            data["anchors"] = {"$USER_CONFIG": user_config, "$PROJECT": ["."]}
        return data

    def write_adapter(self, directory: Path, name: str, data: dict) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def existing_root(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(exist_ok=True)
        return path

    def select(self, **overrides):
        arguments = {
            "client": None,
            "adapter": None,
            "user_config": None,
            "bundled": self.bundled,
            "environ": {},
            "project": self.project,
        }
        arguments.update(overrides)
        return adapters.select_adapter(**arguments)

    def globbed_directories(self) -> list[Path]:
        """Record every directory `Path.glob` is called on, delegating through.

        Used to prove a directory was never *read*, which no assertion about
        the returned adapter can establish on its own: an implementation that
        reads the user directory and then discards it would pass a
        behavioural test and still have opened a directory the user did not
        name.
        """
        calls: list[Path] = []
        original = Path.glob

        def recording(inner_self, pattern, *args, **kwargs):
            calls.append(inner_self)
            return original(inner_self, pattern, *args, **kwargs)

        patcher = mock.patch.object(Path, "glob", recording)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    # -- rule 1: `--adapter` wins over everything --------------------------

    def test_an_explicit_adapter_wins_over_client_and_over_detection(self) -> None:
        detectable = self.existing_root("alpha-home")
        self.write_adapter(
            self.bundled, "alpha.json", self.document("alpha", user_config=[str(detectable)])
        )
        named = self.write_adapter(
            self.root, "explicit.json", self.document("zeta")
        )
        data, notes = self.select(client="alpha", adapter=named)
        self.assertEqual(data["client"], "zeta")
        self.assertEqual(len(notes), 1, notes)
        self.assertIn(str(named), notes[0])
        self.assertIn("--adapter", notes[0])

    def test_an_explicit_adapter_is_validated_like_a_bundled_one(self) -> None:
        broken = self.document("zeta")
        broken["expires_on"] = "nope"
        broken["probes"] = [{"kind": "skill", "glob": "$USER_CONFIG/../x"}]
        named = self.write_adapter(self.root, "explicit.json", broken)
        with self.assertRaises(LedgerError) as caught:
            self.select(adapter=named)
        message = str(caught.exception)
        self.assertEqual(
            message, "\n".join(adapters.validate_adapter(broken, source=str(named)))
        )
        self.assertIn("expires_on must match YYYY-MM-DD", message)
        self.assertIn("glob_dotdot_segment", message)

    def test_an_explicit_adapter_reads_no_adapter_directory(self) -> None:
        named = self.write_adapter(self.root, "explicit.json", self.document("zeta"))
        calls = self.globbed_directories()
        self.select(adapter=named, user_config=self.user_config)
        self.assertNotIn(self.bundled, calls)
        self.assertNotIn(self.user_adapters, calls)
        # Proves the recorder observes what it claims to: the same call
        # without `--adapter` does glob the bundled directory.
        self.select()
        self.assertIn(self.bundled, calls)

    # -- rule 2: `--client` names one -------------------------------------

    def test_client_selects_the_bundled_adapter_of_that_name(self) -> None:
        path = self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        data, notes = self.select(client="alpha")
        self.assertEqual(data["client"], "alpha")
        self.assertTrue(
            any(str(path) in note and "--client" in note for note in notes), notes
        )

    def test_the_adapter_file_name_is_not_the_key_its_client_value_is(self) -> None:
        """Keyed by the document's `client`, not by the file's stem."""
        self.write_adapter(self.bundled, "misnamed.json", self.document("alpha"))
        data, _ = self.select(client="alpha")
        self.assertEqual(data["client"], "alpha")
        with self.assertRaises(LedgerError):
            self.select(client="misnamed")

    def test_an_unknown_client_is_a_tool_error_naming_the_clients_available(
        self,
    ) -> None:
        """An explicit wrong name is a typo, not an unknown client.

        Falling back to `generic.json` here would answer a question the user
        did not ask, and the baseline would record a scan of nothing under a
        name they never see.
        """
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        self.write_adapter(self.bundled, "beta.json", self.document("beta"))
        with self.assertRaises(LedgerError) as caught:
            self.select(client="clod-code")
        message = str(caught.exception)
        self.assertIn(repr("clod-code"), message)
        for available in ("alpha", "beta", "generic"):
            self.assertIn(repr(available), message)

    def test_an_unknown_client_never_falls_back_to_generic(self) -> None:
        with self.assertRaises(LedgerError):
            self.select(client="nope")

    def test_a_user_adapter_overrides_a_bundled_one_with_the_same_client(self) -> None:
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        override = self.document("alpha")
        override["sensitive_key_patterns"] = ["*token*"]
        path = self.write_adapter(self.user_adapters, "local.json", override)
        data, notes = self.select(client="alpha", user_config=self.user_config)
        self.assertEqual(data["sensitive_key_patterns"], ["*token*"])
        self.assertTrue(
            any(str(path) in note and "override" in note for note in notes), notes
        )

    def test_the_override_note_names_the_client_and_the_user_file(self) -> None:
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        path = self.write_adapter(self.user_adapters, "local.json", self.document("alpha"))
        _, notes = self.select(client="alpha", user_config=self.user_config)
        overrides = [note for note in notes if "override" in note]
        self.assertEqual(len(overrides), 1, notes)
        self.assertIn(str(path), overrides[0])
        self.assertIn(repr("alpha"), overrides[0])

    def test_a_user_adapter_introduces_a_client_the_bundle_does_not_ship(self) -> None:
        path = self.write_adapter(self.user_adapters, "local.json", self.document("zeta"))
        data, notes = self.select(client="zeta", user_config=self.user_config)
        self.assertEqual(data["client"], "zeta")
        self.assertTrue(any(str(path) in note for note in notes), notes)
        self.assertFalse([note for note in notes if "override" in note], notes)

    # -- rule 3: detection -------------------------------------------------

    def test_detection_selects_the_only_adapter_whose_user_config_resolves(self) -> None:
        present = self.existing_root("alpha-home")
        path = self.write_adapter(
            self.bundled, "alpha.json", self.document("alpha", user_config=[str(present)])
        )
        self.write_adapter(
            self.bundled,
            "beta.json",
            self.document("beta", user_config=[str(self.root / "absent")]),
        )
        data, notes = self.select()
        self.assertEqual(data["client"], "alpha")
        self.assertTrue(any(str(path) in note for note in notes), notes)

    def test_detection_reads_the_environ_argument_not_the_process_environment(
        self,
    ) -> None:
        present = self.existing_root("alpha-home")
        self.write_adapter(
            self.bundled,
            "alpha.json",
            self.document("alpha", user_config=["$env:ALPHA_HOME"]),
        )
        with mock.patch.dict(os.environ, {"ALPHA_HOME": str(present)}):
            data, _ = self.select()
        self.assertEqual(data["client"], "generic")
        data, _ = self.select(environ={"ALPHA_HOME": str(present)})
        self.assertEqual(data["client"], "alpha")

    def test_detection_resolves_relative_candidates_against_the_project(self) -> None:
        (self.project / ".alpha").mkdir()
        self.write_adapter(
            self.bundled, "alpha.json", self.document("alpha", user_config=[".alpha"])
        )
        data, _ = self.select()
        self.assertEqual(data["client"], "alpha")

    def test_two_matches_select_generic_and_the_note_names_both(self) -> None:
        """Detection never guesses between two plausible clients silently."""
        for name in ("alpha", "beta"):
            self.write_adapter(
                self.bundled,
                f"{name}.json",
                self.document(name, user_config=[str(self.existing_root(f"{name}-home"))]),
            )
        data, notes = self.select()
        self.assertEqual(data["client"], "generic")
        ambiguous = [note for note in notes if repr("alpha") in note]
        self.assertEqual(len(ambiguous), 1, notes)
        self.assertIn(repr("beta"), ambiguous[0])

    def test_no_match_selects_generic_and_the_note_says_why(self) -> None:
        self.write_adapter(
            self.bundled,
            "alpha.json",
            self.document("alpha", user_config=[str(self.root / "absent")]),
        )
        data, notes = self.select()
        self.assertEqual(data["client"], "generic")
        self.assertTrue(any("$USER_CONFIG" in note for note in notes), notes)
        self.assertTrue(any(repr("alpha") in note for note in notes), notes)

    def test_a_user_adapter_participates_in_detection(self) -> None:
        present = self.existing_root("zeta-home")
        self.write_adapter(
            self.user_adapters,
            "local.json",
            self.document("zeta", user_config=[str(present)]),
        )
        data, _ = self.select(user_config=self.user_config)
        self.assertEqual(data["client"], "zeta")

    def test_an_overridden_bundled_adapter_does_not_detect_on_its_own(self) -> None:
        """One client, one candidate: the override replaces, it does not add."""
        present = self.existing_root("alpha-home")
        self.write_adapter(
            self.bundled, "alpha.json", self.document("alpha", user_config=[str(present)])
        )
        self.write_adapter(
            self.user_adapters,
            "local.json",
            self.document("alpha", user_config=[str(present)]),
        )
        data, _ = self.select(user_config=self.user_config)
        self.assertEqual(data["client"], "alpha")

    # -- rule 4: an invalid user adapter is refused -----------------------

    def test_an_invalid_user_adapter_is_refused_with_the_same_findings(self) -> None:
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        broken = self.document("alpha")
        broken["expires_on"] = "nope"
        broken["probes"] = [{"kind": "skill", "glob": "$USER_CONFIG/../x"}]
        path = self.write_adapter(self.user_adapters, "local.json", broken)
        with self.assertRaises(LedgerError) as caught:
            self.select(client="alpha", user_config=self.user_config)
        message = str(caught.exception)
        self.assertEqual(
            message, "\n".join(adapters.validate_adapter(broken, source=str(path)))
        )
        self.assertIn("expires_on must match YYYY-MM-DD", message)
        self.assertIn("glob_dotdot_segment", message)
        self.assertIn(str(path), message)

    def test_an_invalid_user_adapter_does_not_fall_back_to_the_bundled_file(
        self,
    ) -> None:
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        broken = self.document("alpha")
        broken["expires_on"] = "nope"
        self.write_adapter(self.user_adapters, "local.json", broken)
        with self.assertRaises(LedgerError):
            self.select(client="alpha", user_config=self.user_config)
        with self.assertRaises(LedgerError):
            self.select(user_config=self.user_config)

    def test_an_unparsable_user_adapter_is_refused(self) -> None:
        self.user_adapters.mkdir(parents=True)
        (self.user_adapters / "local.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(LedgerError):
            self.select(client="generic", user_config=self.user_config)

    # -- rule 5: `user_config=None` never reads the directory --------------

    def test_user_config_none_never_reads_the_user_adapter_directory(self) -> None:
        """Proved by the directory not being opened, not by the result alone.

        The user adapter written here *would* win if it were read: it
        declares the same client as the bundled file and differs from it in a
        field the assertion can see.
        """
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        would_win = self.document("alpha")
        would_win["sensitive_key_patterns"] = ["*token*"]
        path = self.write_adapter(self.user_adapters, "local.json", would_win)

        calls = self.globbed_directories()
        data, notes = self.select(client="alpha")

        self.assertEqual(data["sensitive_key_patterns"], [])
        for note in notes:
            self.assertNotIn(str(path), note)
            self.assertNotIn(str(self.user_adapters), note)
            self.assertNotIn("override", note)
        self.assertNotIn(self.user_adapters, calls)
        self.assertNotIn(self.user_config, calls)
        # Asserted as equality rather than as two absences, so that a
        # `user_config=None` defaulted to *any* other directory -- the home
        # directory being the tempting one -- fails here too. Not vacuous
        # either way: the recorder did see the directory that was read.
        self.assertEqual(calls, [self.bundled])

    def test_user_config_none_is_recorded_as_a_note(self) -> None:
        data, notes = self.select(client="generic")
        self.assertEqual(data["client"], "generic")
        self.assertTrue(any("user adapters" in note for note in notes), notes)

    def test_a_missing_user_adapter_directory_is_not_an_error(self) -> None:
        """`--user-config` may name a root that has no adapters directory."""
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        self.user_config.mkdir()
        data, _ = self.select(client="alpha", user_config=self.user_config)
        self.assertEqual(data["client"], "alpha")

    # -- shape and tool errors --------------------------------------------

    def test_notes_are_plain_strings(self) -> None:
        _, notes = self.select()
        self.assertTrue(notes)
        for note in notes:
            self.assertIsInstance(note, str)

    def test_an_empty_bundled_directory_is_a_tool_error(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(LedgerError) as caught:
            self.select(bundled=empty)
        self.assertIn(str(empty), str(caught.exception))

    def test_a_bundle_without_generic_is_a_tool_error_when_detection_falls_back(
        self,
    ) -> None:
        (self.bundled / "generic.json").unlink()
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        with self.assertRaises(LedgerError) as caught:
            self.select()
        self.assertIn(repr("generic"), str(caught.exception))

    def test_two_adapters_declaring_the_same_client_is_a_tool_error(self) -> None:
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        self.write_adapter(self.bundled, "alpha-copy.json", self.document("alpha"))
        with self.assertRaises(LedgerError) as caught:
            self.select(client="alpha")
        self.assertIn(repr("alpha"), str(caught.exception))


class RealBundledSelectionTests(unittest.TestCase):
    """Selection against the directory the bundle actually ships.

    `SelectAdapterTests` builds its own bundled tree so the rules are stated
    independently of the shipped files. This class exists so a shipped
    adapter that stops being selectable -- renamed, given a `client` that no
    longer matches, or made invalid -- fails here rather than on a user's
    machine.
    """

    def select(self, **overrides):
        arguments = {
            "client": None,
            "adapter": None,
            "user_config": None,
            "bundled": ADAPTERS_DIR,
            "environ": {},
            "project": REPO_ROOT,
        }
        arguments.update(overrides)
        return adapters.select_adapter(**arguments)

    def test_every_shipped_adapter_is_selectable_by_its_client_name(self) -> None:
        paths = sorted(ADAPTERS_DIR.glob("*.json"))
        self.assertTrue(paths, f"no adapters found in {ADAPTERS_DIR}")
        for path in paths:
            client = json.loads(path.read_text(encoding="utf-8"))["client"]
            with self.subTest(adapter=path.name):
                data, notes = self.select(client=client)
                self.assertEqual(data["client"], client)
                self.assertTrue(any(str(path) in note for note in notes), notes)

    def test_an_unknown_client_names_every_shipped_client(self) -> None:
        with self.assertRaises(LedgerError) as caught:
            self.select(client="not-a-client")
        message = str(caught.exception)
        for path in sorted(ADAPTERS_DIR.glob("*.json")):
            client = json.loads(path.read_text(encoding="utf-8"))["client"]
            self.assertIn(repr(client), message)

    def test_no_probe_walks_a_whole_anchor_recursively(self) -> None:
        """A ** may not sit directly under an anchor.

        Two things break at once when it does. The walk is unbounded -- measured
        at ~37 microseconds per directory entry, so a probe of $PROJECT/**
        against a JavaScript repository's node_modules costs seconds, and the
        Codex adapter shipped two of them. And the result is wrong: Codex reads
        the AGENTS.md chain from the repository root down to the working
        directory, so an AGENTS.md sitting in an unrelated subdirectory is a
        file it would never load, recorded as if it were live configuration --
        the same defect as probing a file the client does not read at all.

        A recursive wildcard under a fixed directory the client owns, such as
        $PROJECT/.claude/rules/**/*.md, is bounded by that directory and stays.
        """
        for path in sorted(ADAPTERS_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for index, probe in enumerate(data["probes"]):
                pattern = probe.get("glob") or probe.get("path") or ""
                segments = pattern.split("/")
                with self.subTest(adapter=path.name, probe=index):
                    self.assertNotEqual(
                        segments[1:2],
                        ["**"],
                        f"{path.name} probes[{index}] walks a whole anchor: {pattern!r}",
                    )

    def test_detection_against_an_empty_machine_selects_generic(self) -> None:
        """No anchor candidate resolves under a tree with nothing in it."""
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp).resolve()
            with mock.patch.dict(
                os.environ, {"HOME": str(empty), "USERPROFILE": str(empty)}
            ):
                data, notes = self.select(project=empty)
        self.assertEqual(data["client"], "generic")
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
