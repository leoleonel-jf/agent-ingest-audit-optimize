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


if __name__ == "__main__":
    unittest.main()
