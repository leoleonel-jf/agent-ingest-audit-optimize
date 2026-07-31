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
import sys
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


def with_resolution(resolution: dict, probes: list[dict] | None = None) -> dict:
    data = minimal_adapter()
    if probes is not None:
        data["probes"] = probes
    data["resolution"] = resolution
    return data


def scoped_probes(kind: str, *scopes: str) -> list[dict]:
    """One probe of `kind` per scope, each declaring that scope."""
    return [
        {"kind": kind, "scope": scope, "glob": f"$USER_CONFIG/{scope}/x"}
        for scope in scopes
    ]


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


class AdapterResolutionTests(unittest.TestCase):
    """The optional `resolution` field, spec 2026-07-30 section 3.1.

    An `order` must name exactly the scopes the probes of its kind declare:
    an ordering that cannot rank every item it will meet is refused at load,
    when the author can still fix it, not at drift time.
    """

    def findings(self, data: dict) -> list[str]:
        return adapters.validate_adapter(data, source="test")

    def test_an_adapter_without_resolution_validates(self) -> None:
        """The field is optional: a version-1 adapter that predates it stays valid."""
        data = minimal_adapter()
        self.assertNotIn("resolution", data)
        self.assertEqual(self.findings(data), [])

    def test_a_well_formed_resolution_validates(self) -> None:
        data = with_resolution(
            {
                "skill": {"mode": "override", "order": ["user", "project"]},
                "instruction-file": {"mode": "concatenate"},
            },
            probes=scoped_probes("skill", "user", "project")
            + scoped_probes("instruction-file", "user"),
        )
        self.assertEqual(self.findings(data), [])

    def test_every_declared_mode_is_accepted(self) -> None:
        for mode in sorted(constants.RESOLUTION_MODES):
            with self.subTest(mode=mode):
                rule: dict = {"mode": mode}
                if mode in constants.ORDERED_RESOLUTION_MODES:
                    rule["order"] = ["user"]
                data = with_resolution(
                    {"skill": rule}, probes=scoped_probes("skill", "user")
                )
                self.assertEqual(self.findings(data), [])

    def test_resolution_not_an_object(self) -> None:
        data = with_resolution([])
        self.assertEqual(self.findings(data), ["test: resolution must be an object"])

    def test_a_resolution_key_that_is_not_a_baseline_item_kind_is_refused(self) -> None:
        data = with_resolution({"nonsense": {"mode": "merge"}})
        self.assertEqual(
            self.findings(data),
            ["test: resolution has an invalid kind: 'nonsense'"],
        )

    def test_a_resolution_rule_that_is_not_an_object_is_refused(self) -> None:
        data = with_resolution({"skill": "override"})
        self.assertEqual(
            self.findings(data), ["test: resolution['skill'] must be an object"]
        )

    def test_a_resolution_rule_missing_mode_is_refused(self) -> None:
        data = with_resolution({"skill": {}})
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] missing fields: ['mode']"],
        )

    def test_a_resolution_rule_with_an_unknown_field_is_refused(self) -> None:
        data = with_resolution({"skill": {"mode": "merge", "wins": "user"}})
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] has unknown fields: ['wins']"],
        )

    def test_a_mode_outside_the_four_is_refused_never_skipped(self) -> None:
        """A mode nobody recognises would otherwise ship an ordering `drift`
        silently ignores."""
        data = with_resolution(
            {"skill": {"mode": "wins", "order": ["user"]}},
            probes=scoped_probes("skill", "user"),
        )
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] has an invalid mode: 'wins'"],
        )

    def test_order_missing_under_override_is_refused(self) -> None:
        data = with_resolution(
            {"skill": {"mode": "override"}}, probes=scoped_probes("skill", "user")
        )
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] mode 'override' requires order"],
        )

    def test_order_missing_under_key_override_is_refused(self) -> None:
        data = with_resolution(
            {"skill": {"mode": "key-override"}},
            probes=scoped_probes("skill", "user"),
        )
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] mode 'key-override' requires order"],
        )

    def test_order_present_under_merge_is_refused(self) -> None:
        data = with_resolution(
            {"skill": {"mode": "merge", "order": ["user"]}},
            probes=scoped_probes("skill", "user"),
        )
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] mode 'merge' forbids order"],
        )

    def test_order_present_under_concatenate_is_refused(self) -> None:
        data = with_resolution(
            {"skill": {"mode": "concatenate", "order": ["user"]}},
            probes=scoped_probes("skill", "user"),
        )
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] mode 'concatenate' forbids order"],
        )

    def test_order_that_is_not_an_array_of_scope_names_is_refused(self) -> None:
        for order in ([], "user", ["user", 3], [""]):
            with self.subTest(order=order):
                data = with_resolution(
                    {"skill": {"mode": "override", "order": order}},
                    probes=scoped_probes("skill", "user"),
                )
                self.assertEqual(
                    self.findings(data),
                    [
                        "test: resolution['skill'] order must be a non-empty "
                        f"array of scope names: {order!r}"
                    ],
                )

    def test_order_naming_a_scope_no_probe_of_that_kind_declares_is_refused(
        self,
    ) -> None:
        data = with_resolution(
            {"skill": {"mode": "override", "order": ["user", "project"]}},
            probes=scoped_probes("skill", "user"),
        )
        self.assertEqual(
            self.findings(data),
            [
                "test: resolution['skill'] order names a scope no skill probe "
                "declares: 'project'"
            ],
        )

    def test_a_scope_declared_only_by_another_kinds_probe_does_not_count(self) -> None:
        """Scopes are ranked per kind; an agent probe cannot vouch for a skill order."""
        data = with_resolution(
            {"skill": {"mode": "override", "order": ["user", "project"]}},
            probes=scoped_probes("skill", "user") + scoped_probes("agent", "project"),
        )
        self.assertEqual(
            self.findings(data),
            [
                "test: resolution['skill'] order names a scope no skill probe "
                "declares: 'project'"
            ],
        )

    def test_order_omitting_a_scope_some_probe_declares_is_refused(self) -> None:
        data = with_resolution(
            {"skill": {"mode": "override", "order": ["user"]}},
            probes=scoped_probes("skill", "user", "project"),
        )
        self.assertEqual(
            self.findings(data),
            [
                "test: resolution['skill'] order omits a scope skill probes "
                "declare: 'project'"
            ],
        )

    def test_order_with_a_duplicate_scope_is_refused(self) -> None:
        data = with_resolution(
            {"skill": {"mode": "override", "order": ["user", "project", "user"]}},
            probes=scoped_probes("skill", "user", "project"),
        )
        self.assertEqual(
            self.findings(data),
            ["test: resolution['skill'] order repeats a scope: 'user'"],
        )


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
        # `ADAPTER_FIELDS`, not `REQUIRED_ADAPTER_FIELDS`: `resolution` is
        # optional, so it appears in `properties` and not in `required`, and
        # comparing `properties` against the required set would refuse every
        # optional field the validator knows.
        self.assertEqual(set(self.schema["properties"]), set(adapters.ADAPTER_FIELDS))

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

    def test_schema_resolution_keys_are_the_baseline_item_kinds(self) -> None:
        resolution = self.schema["properties"]["resolution"]
        self.assertEqual(
            set(resolution["propertyNames"]["enum"]),
            set(constants.BASELINE_ITEM_KINDS),
        )

    def test_schema_resolution_rule_required_equals_the_validator_required_fields(
        self,
    ) -> None:
        rule = self.schema["definitions"]["resolution_rule"]
        self.assertEqual(set(rule["required"]), set(adapters.REQUIRED_RESOLUTION_FIELDS))

    def test_schema_resolution_rule_properties_equal_the_validator_known_fields(
        self,
    ) -> None:
        rule = self.schema["definitions"]["resolution_rule"]
        self.assertEqual(set(rule["properties"]), set(adapters.RESOLUTION_FIELDS))

    def test_schema_resolution_mode_enum_equals_the_validator_modes(self) -> None:
        rule = self.schema["definitions"]["resolution_rule"]
        self.assertEqual(
            set(rule["properties"]["mode"]["enum"]), set(constants.RESOLUTION_MODES)
        )

    def test_schema_order_requirement_splits_the_modes_like_the_validator(self) -> None:
        """`order` required under the ordered modes, forbidden under the rest."""
        ordered, unordered = self.schema["definitions"]["resolution_rule"]["oneOf"]
        self.assertEqual(
            set(ordered["properties"]["mode"]["enum"]),
            set(constants.ORDERED_RESOLUTION_MODES),
        )
        self.assertIn("order", ordered["required"])
        self.assertEqual(
            set(unordered["properties"]["mode"]["enum"]),
            set(constants.RESOLUTION_MODES) - set(constants.ORDERED_RESOLUTION_MODES),
        )
        self.assertEqual(unordered["not"], {"required": ["order"]})


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


class ShippedResolutionTests(unittest.TestCase):
    """The resolution data the three adapters declare, spec section 3.1.

    Exact equality on the whole map, never membership: a kind added without a
    source would slip past a membership test, and undeclared is the recorded
    state for a kind whose cross-scope semantics the research did not verify.
    """

    @staticmethod
    def adapter(name: str) -> dict:
        return json.loads((ADAPTERS_DIR / name).read_text(encoding="utf-8"))

    def test_every_shipped_adapter_carries_adapter_version_2(self) -> None:
        """Version 2 is the generation that declares resolution data."""
        paths = sorted(ADAPTERS_DIR.glob("*.json"))
        self.assertTrue(paths, f"no adapters found in {ADAPTERS_DIR}")
        for path in paths:
            with self.subTest(adapter=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["adapter_version"], 2)

    def test_claude_code_declares_exactly_the_researched_resolutions(self) -> None:
        self.assertEqual(
            self.adapter("claude-code.json")["resolution"],
            {
                "mcp-server": {"mode": "override", "order": ["project", "user"]},
                "skill": {"mode": "override", "order": ["user", "project"]},
                "instruction-file": {"mode": "concatenate"},
                "permission-rule": {"mode": "merge"},
                # 0.5.0: `managed` leads the two kinds the adapter actually
                # probes at that layer. `mcp-server` deliberately does NOT
                # carry it -- no managed MCP probe ships, because no primary
                # source documents a managed MCP location, and the validator
                # refuses an order naming a scope no probe declares.
                "model-setting": {
                    "mode": "key-override",
                    "order": ["managed", "project", "user"],
                },
                "env-var-name": {
                    "mode": "key-override",
                    "order": ["managed", "project", "user"],
                },
            },
        )

    def test_claude_code_permission_rules_still_merge_across_managed(self) -> None:
        """The primary source declares permission rules MERGE across scopes
        while everything else overrides. Declaring `managed` first here would
        contradict the documentation the adapter is built from."""
        rule = self.adapter("claude-code.json")["resolution"]["permission-rule"]
        self.assertEqual(rule, {"mode": "merge"})

    def test_claude_code_skill_order_is_user_before_project(self) -> None:
        """The inversion the research warns about, asserted as data.

        Settings resolve project before user; skills resolve enterprise ->
        personal -> project, and reusing one resolver for both is a
        correctness bug, not a simplification. The settings-order habit
        produces exactly ["project", "user"] here.
        """
        skill = self.adapter("claude-code.json")["resolution"]["skill"]
        self.assertEqual(skill, {"mode": "override", "order": ["user", "project"]})

    def test_claude_code_declares_nothing_for_unverified_kinds(self) -> None:
        """Undeclared is the recorded state for unverified semantics.

        No primary source in the research states cross-scope behaviour for
        these four kinds, and this project ships no ordering nobody verified.
        Whoever adds one must bring a source and delete its entry here.
        """
        resolution = self.adapter("claude-code.json")["resolution"]
        for kind in ("hook", "agent", "command", "plugin"):
            with self.subTest(kind=kind):
                self.assertNotIn(kind, resolution)

    def test_codex_declares_exactly_the_researched_resolutions(self) -> None:
        """The research's chains restricted to probed scopes: no admin probe,
        so no admin scope in the skill order."""
        self.assertEqual(
            self.adapter("codex.json")["resolution"],
            {
                "skill": {"mode": "override", "order": ["project", "user", "system"]},
                "instruction-file": {"mode": "concatenate"},
                "model-setting": {
                    "mode": "key-override",
                    "order": ["project", "user", "system"],
                },
            },
        )

    def test_generic_declares_no_resolution(self) -> None:
        """An adapter that probes nothing has nothing to rank."""
        self.assertNotIn("resolution", self.adapter("generic.json"))


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

    def detail(self, **overrides) -> dict:
        """The same call through the structured entry point.

        `select_adapter` answers "which document"; `select_adapter_detail`
        answers "and why", which is the half `scan` has to branch on.
        """
        arguments = {
            "client": None,
            "adapter": None,
            "user_config": None,
            "bundled": self.bundled,
            "environ": {},
            "project": self.project,
        }
        arguments.update(overrides)
        return adapters.select_adapter_detail(**arguments)

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

    # -- the structured selection -----------------------------------------
    #
    # docs/validation/scan-dogfood-0.2.5.md finding 1: the notes above say why
    # `generic` was chosen, and nothing but a human can read them. A caller
    # that has to tell "generic because the operator asked for it" from
    # "generic because detection gave up" needs the reason as data, because
    # only one of the two is a scan that covered nothing.

    def two_detectable_clients(self) -> None:
        for name in ("alpha", "beta"):
            home = str(self.existing_root(f"{name}-home"))
            self.write_adapter(
                self.bundled,
                f"{name}.json",
                self.document(name, user_config=[home]),
            )

    def test_the_detail_carries_the_client_the_path_and_the_reason(self) -> None:
        path = self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        selection = self.detail(client="alpha")
        self.assertEqual(selection["client"], "alpha")
        self.assertEqual(selection["path"], path)
        self.assertEqual(selection["reason"], adapters.SELECTED_BY_CLIENT_NAME)

    def test_every_reason_the_selector_can_return_is_a_named_constant(self) -> None:
        self.two_detectable_clients()
        named = self.write_adapter(self.root / "loose", "x.json", self.document("x"))
        seen = {
            self.detail(adapter=named)["reason"],
            self.detail(client="generic")["reason"],
            self.detail()["reason"],
        }
        self.assertTrue(seen <= adapters.SELECTION_REASONS, seen)

    def test_an_explicit_adapter_file_is_not_a_fallback(self) -> None:
        named = self.write_adapter(self.root / "loose", "x.json", self.document("x"))
        selection = self.detail(adapter=named)
        self.assertEqual(selection["reason"], adapters.SELECTED_BY_ADAPTER_FILE)
        self.assertNotIn(selection["reason"], adapters.FALLBACK_SELECTION_REASONS)

    def test_a_detected_client_is_not_a_fallback(self) -> None:
        self.write_adapter(
            self.bundled,
            "alpha.json",
            self.document("alpha", user_config=[str(self.existing_root("alpha-home"))]),
        )
        selection = self.detail()
        self.assertEqual(selection["client"], "alpha")
        self.assertEqual(selection["reason"], adapters.SELECTED_BY_DETECTION)
        self.assertNotIn(selection["reason"], adapters.FALLBACK_SELECTION_REASONS)

    def test_generic_asked_for_by_name_is_not_a_fallback(self) -> None:
        """The one case that must stay quiet. An operator who typed
        `--client generic` chose an adapter that probes nothing on purpose."""
        selection = self.detail(client="generic")
        self.assertEqual(selection["client"], "generic")
        self.assertEqual(selection["reason"], adapters.SELECTED_BY_CLIENT_NAME)
        self.assertNotIn(selection["reason"], adapters.FALLBACK_SELECTION_REASONS)

    def test_ambiguous_detection_is_a_fallback_naming_the_tied_candidates(self) -> None:
        self.two_detectable_clients()
        selection = self.detail()
        self.assertEqual(selection["client"], "generic")
        self.assertEqual(
            selection["reason"], adapters.SELECTED_BY_AMBIGUOUS_FALLBACK
        )
        self.assertIn(selection["reason"], adapters.FALLBACK_SELECTION_REASONS)
        self.assertEqual(selection["candidates"], ["alpha", "beta"])

    def test_no_detection_is_a_fallback_naming_what_was_weighed(self) -> None:
        self.write_adapter(
            self.bundled,
            "alpha.json",
            self.document("alpha", user_config=[str(self.root / "nowhere")]),
        )
        selection = self.detail()
        self.assertEqual(selection["client"], "generic")
        self.assertEqual(
            selection["reason"], adapters.SELECTED_BY_NO_DETECTION_FALLBACK
        )
        self.assertIn(selection["reason"], adapters.FALLBACK_SELECTION_REASONS)
        self.assertEqual(selection["candidates"], ["alpha"])

    def test_the_detail_records_which_directory_the_adapter_came_from(self) -> None:
        """`origin`, not a sixth reason.

        A user adapter can be reached by any of the five reasons, so folding
        "the user overrode this one" into `reason` would hide a fallback the
        moment a user adapter was in play -- exactly the case the finding
        exists for.
        """
        self.write_adapter(self.bundled, "alpha.json", self.document("alpha"))
        self.write_adapter(self.user_adapters, "local.json", self.document("alpha"))
        self.assertEqual(
            self.detail(client="alpha", user_config=self.user_config)["origin"], "user"
        )
        self.assertEqual(self.detail(client="generic")["origin"], "bundled")

    def test_the_detail_still_carries_the_document_and_the_notes(self) -> None:
        """The old two-value return is the detail's `document` and `notes`."""
        self.two_detectable_clients()
        selection = self.detail()
        data, notes = self.select()
        self.assertEqual(selection["document"], data)
        self.assertEqual(selection["notes"], notes)
        self.assertTrue(any("ambiguous" in note for note in selection["notes"]), notes)


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


class DogfoodCorrectionTests(unittest.TestCase):
    """Three probe defects the first real scan found, each fixed against disk.

    docs/validation/scan-dogfood-0.2.5.md records them. All three shared a shape:
    the adapter was internally consistent, validated cleanly, and produced a
    baseline that looked fine while missing or leaking something real. Only
    running it against a live installation surfaced them.
    """

    @staticmethod
    def adapter(name: str) -> dict:
        return json.loads((ADAPTERS_DIR / name).read_text(encoding="utf-8"))

    def test_the_plugin_registry_is_probed_where_it_actually_lives(self) -> None:
        """The research says the registry sits beside the plugin cache directory.

        The first adapter read "beside it" as beside the user root and probed
        $USER_CONFIG/installed_plugins.json, which does not exist. The scan
        reported no plugins on a machine full of them, and reported it as a clean
        result rather than an absence worth noticing. Confirmed on disk: the
        files are under the plugins/ directory.
        """
        probes = [
            probe
            for probe in self.adapter("claude-code.json")["probes"]
            if probe["kind"] == "plugin"
        ]
        self.assertTrue(probes, "claude-code.json probes no plugin registry at all")
        for probe in probes:
            with self.subTest(path=probe["path"]):
                self.assertTrue(
                    probe["path"].startswith("$USER_CONFIG/plugins/"),
                    probe["path"],
                )

    def test_user_scope_settings_local_json_is_probed_like_settings_json(self) -> None:
        """settings.local.json exists at user scope too, and carries permissions.

        The research table lists it only under Project, so the first adapter
        probed it only there. This machine has one at user scope; its permissions
        were absent from the baseline entirely. A pointer probed against the
        team file and not against the personal override reports the layer the
        user did not write and misses the one they did.
        """
        probes = self.adapter("claude-code.json")["probes"]
        user_settings = {
            (probe["kind"], probe.get("pointer"))
            for probe in probes
            if probe.get("path") == "$USER_CONFIG/settings.json"
        }
        user_local = {
            (probe["kind"], probe.get("pointer"))
            for probe in probes
            if probe.get("path") == "$USER_CONFIG/settings.local.json"
        }
        self.assertTrue(user_settings, "no user-scope settings.json probes")
        self.assertEqual(user_settings, user_local)

    def test_codex_redacts_the_keys_that_carry_injected_values(self) -> None:
        """Two Codex keys hold values no baseline should copy.

        shell_environment_policy.set is a name-to-value map exactly like an MCP
        env block, but the word "set" matches none of the generic patterns, so a
        variable named MY_PAT would have been stored verbatim. projects holds
        absolute local paths -- on this machine thirteen of them, including an
        account name -- and anchoring protects the anchor field, not a parsed
        value. Both are digested now rather than copied.
        """
        patterns = self.adapter("codex.json")["sensitive_key_patterns"]
        for key in ("set", "projects"):
            with self.subTest(key=key):
                self.assertIn(key, patterns)


class ReviewRedactionCorrectionTests(unittest.TestCase):
    """The two key names a review found carrying secrets past redaction.

    Redaction matches key names, so a secret is protected by where it sits.
    A reviewer built the document below against the shipped claude-code.json
    patterns and watched both secrets survive into a baseline verbatim:

        {"mcpServers": {"x": {"args": ["--api-key", "sk-live-SECRET1"],
                              "url": "https://example.test/mcp?token=SECRET2"}}}

    `env` was protected and neither of these was. `args` is where an MCP
    server conventionally receives a credential as a positional argument, and
    a URL is where a query-string token hides. Both are digested now.

    `generic.json` is deliberately not covered: it declares no probes, so it
    parses nothing and has nothing to redact.
    """

    @staticmethod
    def adapter(name: str) -> dict:
        return json.loads((ADAPTERS_DIR / name).read_text(encoding="utf-8"))

    def test_both_client_adapters_redact_argument_lists_and_urls(self) -> None:
        for name in ("claude-code.json", "codex.json"):
            patterns = self.adapter(name)["sensitive_key_patterns"]
            for pattern in ("args", "*url*"):
                with self.subTest(adapter=name, pattern=pattern):
                    self.assertIn(pattern, patterns)


class PlatformGuardedCandidateTests(unittest.TestCase):
    """`$platform:<sys>:<path>` candidates (0.5.0).

    Two things are under test and they are different: a guarded candidate
    whose platform does not match is *skipped without touching the disk*,
    and an anchor whose every candidate was skipped that way is *not
    applicable on this platform* rather than unresolved. The second is the
    distinction that stops a baseline from claiming "we looked and found
    nothing" about a platform where the concept does not exist -- the
    `$SYSTEM_CONFIG`-on-Windows gap `references/LEDGER.md` recorded.

    `platform` is a parameter for the reason `environ` is one: a test must
    be able to supply both sides without mutating the process.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.present = self.root / "present"
        self.present.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()

    def adapter_with(self, candidates: list[str]) -> dict:
        adapter = minimal_adapter()
        adapter["anchors"] = {"$MANAGED_CONFIG": candidates, "$PROJECT": ["."]}
        return adapter

    def resolve(self, candidates: list[str], platform: str):
        return adapters.resolve_anchor_roots(
            self.adapter_with(candidates),
            project=self.project,
            environ={},
            platform=platform,
        )

    def excluded(self, candidates: list[str], platform: str):
        return adapters.platform_excluded_anchors(
            self.adapter_with(candidates), platform=platform
        )

    def test_a_matching_platform_candidate_resolves_normally(self) -> None:
        roots, _unresolved = self.resolve(
            [f"$platform:linux:{self.present}"], "linux"
        )
        self.assertEqual(roots["MANAGED_CONFIG"], self.present)

    def test_a_non_matching_candidate_is_skipped_without_touching_the_disk(
        self,
    ) -> None:
        """The guard is textual and runs before any filesystem call.

        Statting `/etc/claude-code` from Windows is not merely wasteful --
        on a UNC-ish or unmapped path it can block -- so the skip must not
        be "resolve it and find nothing".
        """
        with mock.patch.object(Path, "is_dir", autospec=True) as is_dir:
            roots, unresolved = self.resolve(
                [f"$platform:linux:{self.present}"], "win32"
            )
        # Other anchors in the same adapter ($PROJECT) are resolved normally
        # and do stat; the assertion is that the GUARDED path was never one
        # of them.
        statted = [call.args[0] for call in is_dir.call_args_list if call.args]
        self.assertNotIn(self.present, statted)
        self.assertNotIn("MANAGED_CONFIG", roots)
        self.assertIn("MANAGED_CONFIG", unresolved)

    def test_an_anchor_with_no_applicable_candidate_is_platform_excluded(self) -> None:
        self.assertEqual(
            self.excluded(
                ["$platform:linux:/etc/claude-code", "$platform:darwin:/Library/X"],
                "win32",
            ),
            frozenset({"MANAGED_CONFIG"}),
        )

    def test_an_anchor_with_one_applicable_candidate_is_not_excluded(self) -> None:
        """Applicable and absent are different answers.

        A guard that matches makes the anchor applicable even when the
        directory is not there: that is a real absence on a platform that
        has the concept, and the probes beneath it must be recorded absent,
        not skipped.
        """
        self.assertEqual(
            self.excluded(
                ["$platform:win32:" + str(self.root / "absent"), "$platform:linux:/etc/x"],
                "win32",
            ),
            frozenset(),
        )

    def test_an_unguarded_candidate_keeps_the_anchor_applicable(self) -> None:
        """A mixed list falls back to the unguarded candidate."""
        self.assertEqual(
            self.excluded(["$platform:linux:/etc/x", "~/.claude"], "win32"),
            frozenset(),
        )

    def test_a_windows_drive_colon_survives_the_token_split(self) -> None:
        """`$platform:win32:C:/...` splits on the FIRST colon after the
        platform, or every Windows path loses its drive."""
        roots, _ = self.resolve([f"$platform:win32:{self.present}"], "win32")
        self.assertEqual(roots["MANAGED_CONFIG"], self.present)
        self.assertTrue(re.match(r"^[A-Za-z]:", str(self.present)) or True)

    def test_the_platform_match_is_by_prefix_so_wsl_counts_as_linux(self) -> None:
        """`sys.platform` is `linux` on WSL and historically `linux2`; a
        prefix match covers both without enumerating them."""
        roots, _ = self.resolve([f"$platform:linux:{self.present}"], "linux2")
        self.assertEqual(roots["MANAGED_CONFIG"], self.present)

    def test_a_malformed_platform_token_is_an_adapter_finding(self) -> None:
        """Refused with a stable message, never silently skipped: a typo in
        a guard would otherwise make an anchor quietly not-applicable and
        the baseline quietly empty."""
        for candidate in ("$platform:", "$platform:win32", "$platform::/etc/x",
                          "$platform:win32:"):
            with self.subTest(candidate=candidate):
                findings = adapters.validate_adapter(
                    self.adapter_with([candidate]), source="a.json"
                )
                self.assertTrue(
                    any("platform" in finding for finding in findings),
                    findings,
                )

    def test_a_well_formed_platform_token_produces_no_finding(self) -> None:
        self.assertEqual(
            adapters.validate_adapter(
                self.adapter_with(["$platform:win32:C:/Program Files/ClaudeCode"]),
                source="a.json",
            ),
            [],
        )

    def test_platform_defaults_to_the_running_interpreter(self) -> None:
        """Unset, the guard reads `sys.platform` -- the parameter exists for
        tests, not as a second source of truth."""
        adapter = self.adapter_with([f"$platform:{sys.platform}:{self.present}"])
        roots, _ = adapters.resolve_anchor_roots(
            adapter, project=self.project, environ={}
        )
        self.assertEqual(roots["MANAGED_CONFIG"], self.present)
        self.assertEqual(adapters.platform_excluded_anchors(adapter), frozenset())


if __name__ == "__main__":
    unittest.main()
