"""Tests for `ledgerlib.scan`: redaction, probing, parsing, and assembly.

The suite loads `dashboard.py` by file path exactly the way
`test_dashboard.py` and `test_adapters.py` do. That import has a side effect
this module depends on: `dashboard.py` inserts its own directory at the front
of `sys.path` before importing `ledgerlib`, so `from ledgerlib import scan`
below resolves to the bundle's copy rather than to anything installed.

Every assertion about what does *not* leak is made against
`json.dumps(result)` rather than against the returned object, because the
serialised form is what actually leaves the process.
"""

from __future__ import annotations

import builtins
import contextlib
import datetime
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat as stat_module
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "scripts"
    / "dashboard.py"
)
ADAPTERS_DIR = (
    REPO_ROOT / "skills" / "agent-ingest-audit-optimize" / "assets" / "adapters"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib.constants import (  # noqa: E402
    BASELINE_ITEM_STATES,
    RECORD_ID,
    REQUIRED_BASELINE_FIELDS,
    REQUIRED_BASELINE_ITEM_FIELDS,
)
from ledgerlib.adapters import validate_adapter  # noqa: E402
from ledgerlib.errors import LedgerError, PATH_SAFETY_REASONS  # noqa: E402
from ledgerlib.paths import check_glob  # noqa: E402
from ledgerlib import scan as scan_module  # noqa: E402
from ledgerlib.scan import (  # noqa: E402
    BASELINE_PREFIX,
    PARSE_ERRORS,
    SCAN_REASONS,
    redact,
    run_probe,
    scan,
    scan_command,
)
from ledgerlib.validate import validate_baseline  # noqa: E402
from ledgerlib.verify import verify  # noqa: E402


DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_digest(value: object) -> str:
    """Recompute the documented digest independently of the implementation."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def markers(value: object) -> list[dict]:
    """Every redaction marker anywhere in `value`, in walk order."""
    found: list[dict] = []
    if isinstance(value, dict):
        if set(value) == {"redacted", "digest"} and value.get("redacted") is True:
            return [value]
        for item in value.values():
            found.extend(markers(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(markers(item))
    return found


class MarkerShapeTests(unittest.TestCase):
    def test_matching_key_value_is_replaced_by_a_marker(self) -> None:
        result = redact({"token": "s3cr3t"}, ["*token*"])
        self.assertEqual(
            result,
            {"token": {"redacted": True, "digest": canonical_digest("s3cr3t")}},
        )

    def test_marker_carries_only_redacted_and_digest(self) -> None:
        result = redact({"token": "s3cr3t"}, ["*token*"])
        self.assertEqual(set(result["token"]), {"redacted", "digest"})
        self.assertIs(result["token"]["redacted"], True)
        self.assertRegex(result["token"]["digest"], DIGEST)

    def test_sibling_keys_are_untouched(self) -> None:
        result = redact({"token": "s3cr3t", "name": "ok"}, ["*token*"])
        self.assertEqual(result["name"], "ok")


class PatternMatchingTests(unittest.TestCase):
    def test_uppercase_key_matches_lowercase_pattern(self) -> None:
        result = redact({"API_TOKEN": "s3cr3t"}, ["*token*"])
        self.assertRegex(result["API_TOKEN"]["digest"], DIGEST)

    def test_lowercase_key_matches_uppercase_pattern(self) -> None:
        result = redact({"api_token": "s3cr3t"}, ["*TOKEN*"])
        self.assertRegex(result["api_token"]["digest"], DIGEST)

    def test_literal_pattern_matches_the_exact_key(self) -> None:
        result = redact({"env": {"A": 1}}, ["env"])
        self.assertRegex(result["env"]["digest"], DIGEST)

    def test_literal_pattern_does_not_match_a_longer_key(self) -> None:
        result = redact({"environment": "production"}, ["env"])
        self.assertEqual(result, {"environment": "production"})

    def test_literal_pattern_does_not_match_a_prefixed_key(self) -> None:
        result = redact({"my_env": "production"}, ["env"])
        self.assertEqual(result, {"my_env": "production"})

    def test_any_pattern_in_the_list_matches(self) -> None:
        result = redact({"password": "p"}, ["*token*", "*password*"])
        self.assertRegex(result["password"]["digest"], DIGEST)

    def test_empty_pattern_list_changes_nothing(self) -> None:
        document = {"token": "s3cr3t", "env": {"KEY": "v"}, "list": [{"secret": 1}]}
        self.assertEqual(redact(document, []), document)


class RecursionTests(unittest.TestCase):
    def test_a_secret_three_objects_deep_is_redacted(self) -> None:
        document = {"a": {"b": {"c": {"api_token": "s3cr3t"}}}}
        result = redact(document, ["*token*"])
        self.assertEqual(
            result,
            {
                "a": {
                    "b": {
                        "c": {
                            "api_token": {
                                "redacted": True,
                                "digest": canonical_digest("s3cr3t"),
                            }
                        }
                    }
                }
            },
        )

    def test_objects_inside_arrays_are_redacted(self) -> None:
        document = {"servers": [{"name": "a"}, {"name": "b", "token": "s3cr3t"}]}
        result = redact(document, ["*token*"])
        self.assertEqual(result["servers"][0], {"name": "a"})
        self.assertRegex(result["servers"][1]["token"]["digest"], DIGEST)
        self.assertEqual(result["servers"][1]["name"], "b")

    def test_recursion_stops_at_the_match(self) -> None:
        result = redact({"env": {"A": {"B": "s"}}}, ["env"])
        self.assertEqual(
            result,
            {
                "env": {
                    "redacted": True,
                    "digest": canonical_digest({"A": {"B": "s"}}),
                }
            },
        )
        self.assertEqual(len(markers(result)), 1)
        dumped = json.dumps(result)
        self.assertNotIn('"A"', dumped)
        self.assertNotIn('"B"', dumped)

    def test_a_nested_match_below_a_match_is_never_walked(self) -> None:
        document = {"env": {"deeper": {"token": "PLAINTEXT-b7f21c"}}}
        result = redact(document, ["env", "*token*"])
        self.assertEqual(len(markers(result)), 1)
        self.assertNotIn("PLAINTEXT-b7f21c", json.dumps(result))
        self.assertNotIn('"deeper"', json.dumps(result))


class NonStringValueTests(unittest.TestCase):
    def test_a_number_redacts(self) -> None:
        result = redact({"token": 1234567}, ["*token*"])
        self.assertEqual(
            result["token"], {"redacted": True, "digest": canonical_digest(1234567)}
        )

    def test_a_list_redacts(self) -> None:
        result = redact({"token": ["a", "b"]}, ["*token*"])
        self.assertEqual(
            result["token"],
            {"redacted": True, "digest": canonical_digest(["a", "b"])},
        )

    def test_an_object_redacts(self) -> None:
        result = redact({"token": {"k": "v"}}, ["*token*"])
        self.assertEqual(
            result["token"],
            {"redacted": True, "digest": canonical_digest({"k": "v"})},
        )

    def test_null_and_boolean_redact(self) -> None:
        result = redact({"token": None, "secret": False}, ["*token*", "*secret*"])
        self.assertEqual(
            result["token"], {"redacted": True, "digest": canonical_digest(None)}
        )
        self.assertEqual(
            result["secret"], {"redacted": True, "digest": canonical_digest(False)}
        )


class DigestTests(unittest.TestCase):
    def test_digest_is_stable_for_equal_values(self) -> None:
        first = redact({"token": {"b": 2, "a": 1}}, ["*token*"])
        second = redact({"token": {"a": 1, "b": 2}}, ["*token*"])
        self.assertEqual(first["token"]["digest"], second["token"]["digest"])

    def test_digest_differs_for_different_values(self) -> None:
        first = redact({"token": "s3cr3t"}, ["*token*"])
        second = redact({"token": "s3cr3u"}, ["*token*"])
        self.assertNotEqual(first["token"]["digest"], second["token"]["digest"])

    def test_digest_matches_the_documented_canonical_encoding(self) -> None:
        value = {"b": [2, {"z": 1, "a": 0}], "a": "é"}
        result = redact({"token": value}, ["*token*"])
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        expected = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.assertEqual(result["token"]["digest"], expected)

    def test_digest_distinguishes_a_number_from_its_string(self) -> None:
        first = redact({"token": 1}, ["*token*"])
        second = redact({"token": "1"}, ["*token*"])
        self.assertNotEqual(first["token"]["digest"], second["token"]["digest"])


class NonSerialisableValueTests(unittest.TestCase):
    """A `toml` probe yields `datetime` objects, which `json.dumps` refuses.

    The deliberate choice: redaction never raises. A value the canonical
    encoder cannot handle is digested over its `repr()` instead, so the value
    is still replaced by a marker and still never copied.
    """

    def test_a_datetime_value_redacts_without_raising(self) -> None:
        moment = datetime.datetime(2026, 7, 30, 12, 0, 0)
        result = redact({"token": moment}, ["*token*"])
        self.assertIs(result["token"]["redacted"], True)
        self.assertRegex(result["token"]["digest"], DIGEST)

    def test_a_non_serialisable_digest_is_stable_and_discriminating(self) -> None:
        one = redact({"token": datetime.date(2026, 7, 30)}, ["*token*"])
        same = redact({"token": datetime.date(2026, 7, 30)}, ["*token*"])
        other = redact({"token": datetime.date(2026, 7, 31)}, ["*token*"])
        self.assertEqual(one["token"]["digest"], same["token"]["digest"])
        self.assertNotEqual(one["token"]["digest"], other["token"]["digest"])

    def test_a_non_serialisable_value_nested_under_a_match_redacts(self) -> None:
        value = {"when": datetime.date(2026, 7, 30), "who": "me"}
        result = redact({"token": value}, ["*token*"])
        self.assertRegex(result["token"]["digest"], DIGEST)
        self.assertNotIn("me", json.dumps(result))

    def test_a_self_referential_value_redacts_without_raising(self) -> None:
        loop: dict = {"self": None}
        loop["self"] = loop
        result = redact({"token": loop}, ["*token*"])
        self.assertRegex(result["token"]["digest"], DIGEST)

    def test_a_non_serialisable_value_under_no_match_passes_through(self) -> None:
        moment = datetime.date(2026, 7, 30)
        result = redact({"when": moment}, ["*token*"])
        self.assertIs(result["when"], moment)


class PassThroughTests(unittest.TestCase):
    def test_a_non_matching_structure_passes_through_unchanged(self) -> None:
        document = {
            "name": "claude-code",
            "servers": [{"command": "npx", "args": ["-y", "pkg"]}],
            "count": 3,
            "on": True,
            "missing": None,
        }
        self.assertEqual(redact(document, ["*token*", "env"]), document)

    def test_the_input_is_not_mutated(self) -> None:
        document = {"a": {"token": "s3cr3t"}}
        redact(document, ["*token*"])
        self.assertEqual(document, {"a": {"token": "s3cr3t"}})

    def test_the_result_is_a_copy(self) -> None:
        document = {"a": {"b": 1}}
        result = redact(document, ["*token*"])
        self.assertEqual(result, document)
        self.assertIsNot(result, document)
        self.assertIsNot(result["a"], document["a"])

    def test_a_bare_scalar_has_no_key_and_passes_through(self) -> None:
        self.assertEqual(redact("s3cr3t", ["*"]), "s3cr3t")

    def test_a_top_level_array_is_walked(self) -> None:
        result = redact([{"token": "s3cr3t"}], ["*token*"])
        self.assertRegex(result[0]["token"]["digest"], DIGEST)


class SerialisedOutputTests(unittest.TestCase):
    """The serialised form is what leaves the process; assert on that."""

    def test_plaintext_appears_nowhere_in_the_serialised_result(self) -> None:
        plaintext = "PLAINTEXT-4d91ac6e"
        document = {
            "mcpServers": {
                "one": {
                    "command": "npx",
                    "env": {"API_TOKEN": plaintext},
                },
                "two": {"headers": {"Authorization": plaintext}},
            },
            "nested": [[{"deep": {"secret_key": plaintext}}]],
        }
        result = redact(document, ["env", "*authorization*", "*secret*"])
        self.assertNotIn(plaintext, json.dumps(result))

    def test_a_plaintext_value_of_a_non_string_type_does_not_survive(self) -> None:
        document = {"token": [999888777, {"inner": 999888777}]}
        result = redact(document, ["*token*"])
        self.assertNotIn("999888777", json.dumps(result))


class ProbeTestCase(unittest.TestCase):
    """A real temporary tree. Nothing here is mocked that can be built.

    The tree is deliberately two anchors deep on disk -- an anchor root and a
    sibling directory outside it -- because every interesting question this
    task answers is about the boundary between them.
    """

    def setUp(self) -> None:
        # `mkdtemp` rather than `TemporaryDirectory` so cleanup can be
        # `ignore_errors=True`: the unreadable-file test deliberately makes a
        # file the owner cannot open, and a cleanup that raises would turn a
        # passing test into an error.
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user_config = self.tmp / "user_config"
        self.skills = self.user_config / "skills"
        self.skills.mkdir(parents=True)
        # Resolved and absolute, exactly as `resolve_anchor_roots` returns
        # them, so `anchor_path` and `resolve_anchored` receive what they
        # expect. The keys are BARE anchor names.
        self.roots: dict[str, Path] = {"USER_CONFIG": self.user_config}

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def digest_of(self, path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class PathProbeTests(ProbeTestCase):
    def test_an_existing_file_yields_one_present_item(self) -> None:
        target = self.write(self.user_config / "CLAUDE.md", "# memory\n")
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["state"], "present")
        self.assertEqual(item["kind"], "instruction-file")
        self.assertEqual(item["anchor"], "$USER_CONFIG/CLAUDE.md")
        self.assertEqual(item["digest"], self.digest_of(target))
        self.assertRegex(item["digest"], DIGEST)

    def test_the_digest_is_taken_from_the_files_bytes(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "one\n")
        first = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        )[0]["digest"]
        self.write(self.user_config / "CLAUDE.md", "two\n")
        second = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        )[0]["digest"]
        self.assertNotEqual(first, second)

    def test_a_missing_file_yields_exactly_one_not_present_item(self) -> None:
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/ABSENT.md"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["anchor"], "$USER_CONFIG/ABSENT.md")

    def test_no_file_content_reaches_the_item(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "PLAINTEXT-1f4c9b\n")
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        )
        self.assertNotIn("PLAINTEXT-1f4c9b", json.dumps(items))

    def test_the_anchored_form_is_stored_not_an_absolute_path(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "x\n")
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        )
        self.assertNotIn(str(self.tmp), json.dumps(items))
        self.assertIs(items[0].get("portable"), True)


class GlobProbeTests(ProbeTestCase):
    def test_a_glob_matching_three_files_yields_three_items(self) -> None:
        for name in ("a.md", "b.md", "c.md"):
            self.write(self.user_config / "notes" / name, name)
        items = run_probe(
            {"kind": "instruction-file", "glob": "$USER_CONFIG/notes/*.md"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 3)
        self.assertTrue(all(item["state"] == "present" for item in items))
        self.assertTrue(all(DIGEST.match(item["digest"]) for item in items))

    def test_matches_are_ordered_by_their_anchored_path(self) -> None:
        # Mixed case on purpose. `sorted()` orders by code point (every
        # capitalised name first); a case-insensitive directory index -- which
        # is what NTFS hands back from `scandir` -- orders them alphabetically
        # regardless of case. The two orders differ, so a test that passes here
        # cannot be passing on the filesystem's incidental order.
        names = ["Zeta.md", "alpha.md", "Beta.md", "gamma.md", "Delta.md", "epsilon.md"]
        for name in names:
            self.write(self.user_config / "notes" / name, name)
        items = run_probe(
            {"kind": "instruction-file", "glob": "$USER_CONFIG/notes/*.md"},
            self.roots,
            [],
        )
        anchors = [item["anchor"] for item in items]
        self.assertEqual(
            anchors, [f"$USER_CONFIG/notes/{name}" for name in sorted(names)]
        )
        self.assertNotEqual(anchors, [f"$USER_CONFIG/notes/{n}" for n in names])

    def test_a_glob_matching_nothing_yields_one_not_present_item(self) -> None:
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIsNone(items[0]["digest"])

    def test_an_empty_glob_names_the_probe_so_the_baseline_says_what_was_absent(
        self,
    ) -> None:
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        self.assertIn("$USER_CONFIG/skills/*/SKILL.md", items[0]["name"])

    def test_a_recursive_glob_finds_nested_matches(self) -> None:
        self.write(self.user_config / "a" / "b" / "AGENTS.md", "one")
        self.write(self.user_config / "AGENTS.md", "two")
        items = run_probe(
            {"kind": "instruction-file", "glob": "$USER_CONFIG/**/AGENTS.md"},
            self.roots,
            [],
        )
        self.assertEqual(
            [item["anchor"] for item in items],
            ["$USER_CONFIG/AGENTS.md", "$USER_CONFIG/a/b/AGENTS.md"],
        )


class UnresolvedAnchorTests(ProbeTestCase):
    def test_a_probe_under_an_unresolved_anchor_yields_one_not_present_item(
        self,
    ) -> None:
        items = run_probe(
            {"kind": "skill", "glob": "$MISSING_ANCHOR/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIsNone(items[0]["digest"])

    def test_a_path_probe_under_an_unresolved_anchor_does_not_raise(self) -> None:
        items = run_probe(
            {"kind": "mcp-server", "path": "$MISSING_ANCHOR/settings.json"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")

    def test_a_probe_whose_target_is_not_an_anchor_reference_does_not_raise(
        self,
    ) -> None:
        items = run_probe({"kind": "skill", "glob": "skills/*/SKILL.md"}, self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")


class DigestUnavailableTests(ProbeTestCase):
    def test_a_directory_match_is_present_with_a_null_digest_and_a_reason(self) -> None:
        (self.skills / "one").mkdir()
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*"}, self.roots, []
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["attributes"]["reason"], "directory")

    def test_an_unreadable_file_is_present_with_a_null_digest_and_a_reason(
        self,
    ) -> None:
        target = self.write(self.user_config / "settings.json", "{}\n")
        self._make_unreadable(target)
        items = run_probe(
            {"kind": "mcp-server", "path": "$USER_CONFIG/settings.json"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["attributes"]["reason"], "unreadable")

    def _make_unreadable(self, target: Path) -> None:
        """Remove read permission, or skip saying why the platform cannot."""

        def readable() -> bool:
            try:
                target.read_bytes()
            except OSError:
                return False
            return True

        try:
            os.chmod(target, 0o000)
            self.addCleanup(_restore_mode, target)
        except OSError as exc:
            self.skipTest(f"platform {sys.platform}: chmod failed: {exc}")
        if not readable():
            return
        if os.name == "nt":
            user = os.environ.get("USERNAME")
            if user:
                completed = subprocess.run(
                    ["icacls", str(target), "/deny", f"{user}:(R)"],
                    capture_output=True,
                    text=True,
                )
                if completed.returncode == 0:
                    self.addCleanup(_restore_acl, target, user)
                if not readable():
                    return
            self.skipTest(
                f"platform {sys.platform}: a file's owner keeps READ_CONTROL and "
                "FILE_READ_DATA through chmod, and an icacls deny ACE could not "
                "be made to stick, so an unreadable file cannot be built here"
            )
        self.skipTest(
            f"platform {sys.platform}: chmod 000 did not make the file "
            "unreadable (the test is likely running as root)"
        )


def _restore_mode(target: Path) -> None:
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def _restore_acl(target: Path, user: str) -> None:
    try:
        subprocess.run(
            ["icacls", str(target), "/remove:d", user],
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


class EscapeTests(ProbeTestCase):
    """`check_glob` ran at load time. This is what the filesystem holds now."""

    def link_out_of_the_anchor(self, link: Path, target: Path) -> str:
        """Point `link` (inside the anchor) at `target` (outside it)."""
        try:
            os.symlink(target, link, target_is_directory=True)
            return "symlink"
        except (OSError, NotImplementedError, AttributeError) as exc:
            first = exc
        if os.name == "nt":
            # A directory junction needs no elevation and no Developer Mode,
            # and `resolve_anchored`'s prefix rule is written to catch it --
            # so it is tried before giving up, not instead of the symlink.
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
            )
            if completed.returncode == 0 and link.is_dir():
                return "junction"
            self.skipTest(
                f"platform {sys.platform}: creating a directory symlink needs "
                f"Developer Mode or elevation ({first}), and the 'mklink /J' "
                f"fallback failed: "
                f"{(completed.stdout + completed.stderr).strip()!r}"
            )
        self.skipTest(
            f"platform {sys.platform}: cannot create a directory symlink: {first}"
        )

    def build_escape(self) -> None:
        outside = self.tmp / "outside"
        outside.mkdir()
        self.write(outside / "SKILL.md", "PLAINTEXT-OUTSIDE-9a3f\n")
        self.write(self.skills / "real" / "SKILL.md", "inside\n")
        self.write(self.user_config / "CLAUDE.md", "# memory\n")
        self.kind_of_link = self.link_out_of_the_anchor(self.skills / "evil", outside)

    def test_a_match_behind_a_link_out_of_the_anchor_is_refused(self) -> None:
        self.build_escape()
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        refused = [item for item in items if item["state"] == "not_present"]
        self.assertEqual(len(refused), 1, items)
        self.assertIn(refused[0]["attributes"].get("reason"), PATH_SAFETY_REASONS)
        self.assertIsNone(refused[0]["digest"])

    def test_the_content_behind_the_link_never_reaches_the_output(self) -> None:
        self.build_escape()
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        self.assertNotIn("PLAINTEXT-OUTSIDE-9a3f", json.dumps(items))

    def test_the_sibling_match_inside_the_anchor_is_still_produced(self) -> None:
        self.build_escape()
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        present = [item for item in items if item["state"] == "present"]
        self.assertEqual(len(present), 1, items)
        self.assertEqual(present[0]["anchor"], "$USER_CONFIG/skills/real/SKILL.md")

    def test_the_other_probes_in_the_same_scan_still_produce_their_items(self) -> None:
        self.build_escape()
        probes = [
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            {"kind": "mcp-server", "path": "$USER_CONFIG/settings.json"},
        ]
        produced = [run_probe(probe, self.roots, []) for probe in probes]
        self.assertEqual([len(items) for items in produced], [2, 1, 1])
        self.assertEqual(produced[1][0]["state"], "present")
        self.assertRegex(produced[1][0]["digest"], DIGEST)
        self.assertEqual(produced[2][0]["state"], "not_present")


class ItemShapeTests(ProbeTestCase):
    def test_every_item_carries_the_required_fields(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "x\n")
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        ) + run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )
        for item in items:
            self.assertLessEqual(REQUIRED_BASELINE_ITEM_FIELDS, set(item))
            self.assertIn(item["state"], BASELINE_ITEM_STATES)
            self.assertIsInstance(item["attributes"], dict)

    def test_origin_is_pre_existing_for_every_item(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "x\n")
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        ) + run_probe({"kind": "skill", "glob": "$USER_CONFIG/nope/*"}, self.roots, [])
        self.assertEqual({item["origin"] for item in items}, {"pre-existing"})

    def test_the_probes_scope_is_copied_into_attributes(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "x\n")
        item = run_probe(
            {
                "kind": "instruction-file",
                "scope": "user",
                "path": "$USER_CONFIG/CLAUDE.md",
            },
            self.roots,
            [],
        )[0]
        self.assertEqual(item["attributes"]["scope"], "user")

    def test_a_scope_is_copied_onto_a_not_present_item_too(self) -> None:
        item = run_probe(
            {"kind": "skill", "scope": "project", "glob": "$USER_CONFIG/nope/*"},
            self.roots,
            [],
        )[0]
        self.assertEqual(item["attributes"]["scope"], "project")

    def test_a_probe_without_a_scope_carries_no_scope_attribute(self) -> None:
        self.write(self.user_config / "CLAUDE.md", "x\n")
        item = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/CLAUDE.md"},
            self.roots,
            [],
        )[0]
        self.assertNotIn("scope", item["attributes"])

    def test_a_probe_without_parse_yields_the_whole_file_item(self) -> None:
        target = self.write(
            self.user_config / "settings.json", '{"mcpServers": {"a": {}}}\n'
        )
        items = run_probe(
            {"kind": "mcp-server", "path": "$USER_CONFIG/settings.json"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["digest"], self.digest_of(target))
        self.assertNotIn("value", items[0]["attributes"])


class NeverRaisesTests(ProbeTestCase):
    def test_a_probe_with_neither_glob_nor_path_yields_one_item(self) -> None:
        items = run_probe({"kind": "skill"}, self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")

    def test_a_probe_whose_target_is_not_a_string_yields_one_item(self) -> None:
        items = run_probe({"kind": "skill", "glob": 7}, self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")

    def test_an_empty_roots_mapping_yields_one_item(self) -> None:
        items = run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"}, {}, []
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")

    def test_a_target_carrying_a_nul_byte_yields_one_item(self) -> None:
        items = run_probe(
            {"kind": "skill", "path": "$USER_CONFIG/sk\0ill.md"}, self.roots, []
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")

    def test_a_reserved_device_name_yields_one_not_present_item(self) -> None:
        items = run_probe(
            {"kind": "instruction-file", "path": "$USER_CONFIG/NUL"}, self.roots, []
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertEqual(
            items[0]["attributes"]["reason"], "path_reserved_device_name"
        )


class ParseJsonTests(ProbeTestCase):
    """`parse: "json"` -- one item per key at the pointed-to location."""

    THREE_SERVERS = json.dumps(
        {
            "mcpServers": {
                "gamma": {"command": "npx"},
                "alpha": {"command": "uvx"},
                "beta": {"command": "node"},
            },
            "other": {"ignored": True},
        }
    )

    def probe(self, **extra: object) -> dict:
        probe = {
            "kind": "mcp-server",
            "path": "$USER_CONFIG/settings.json",
            "parse": "json",
        }
        probe.update(extra)
        return probe

    def test_a_pointer_over_three_servers_yields_one_item_per_key(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertEqual(len(items), 3)
        self.assertEqual(
            [item["name"] for item in items], ["alpha", "beta", "gamma"]
        )
        self.assertTrue(all(item["state"] == "present" for item in items))

    def test_the_pointed_to_location_is_the_only_one_enumerated(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertNotIn("other", [item["name"] for item in items])

    def test_every_parsed_item_carries_the_files_byte_digest(self) -> None:
        target = self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertEqual(
            {item["digest"] for item in items}, {self.digest_of(target)}
        )

    def test_every_parsed_item_keeps_the_files_anchored_form(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertEqual(
            {item["anchor"] for item in items}, {"$USER_CONFIG/settings.json"}
        )

    def test_the_parsed_value_lands_in_the_items_attributes(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        by_name = {item["name"]: item for item in items}
        self.assertEqual(
            by_name["alpha"]["attributes"]["value"], {"command": "uvx"}
        )

    def test_the_probes_scope_survives_parsing(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(
            self.probe(pointer="/mcpServers", scope="user"), self.roots, []
        )
        self.assertEqual(
            {item["attributes"]["scope"] for item in items}, {"user"}
        )

    def test_a_pointer_that_does_not_resolve_yields_one_not_present_item(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/nowhere"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIsNone(items[0]["digest"])

    def test_an_unresolved_pointer_names_a_reason_from_the_closed_set(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/nowhere"), self.roots, [])
        self.assertEqual(items[0]["attributes"]["reason"], "pointer_unresolved")
        self.assertIn("pointer_unresolved", SCAN_REASONS)

    def test_an_unresolved_pointer_says_what_was_absent(self) -> None:
        self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(pointer="/nowhere"), self.roots, [])
        self.assertIn("/nowhere", items[0]["name"])

    def test_a_pointer_through_a_scalar_does_not_resolve(self) -> None:
        self.write(self.user_config / "settings.json", '{"a": 1}')
        items = run_probe(self.probe(pointer="/a/b"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["attributes"]["reason"], "pointer_unresolved")

    def test_a_pointer_omitted_yields_one_item_for_the_whole_document(self) -> None:
        target = self.write(self.user_config / "settings.json", self.THREE_SERVERS)
        items = run_probe(self.probe(), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertEqual(items[0]["digest"], self.digest_of(target))
        self.assertEqual(
            items[0]["attributes"]["value"], json.loads(self.THREE_SERVERS)
        )

    def test_a_pointer_may_index_an_array(self) -> None:
        self.write(
            self.user_config / "settings.json",
            json.dumps({"servers": [{"a": 1}, {"b": 2}]}),
        )
        items = run_probe(self.probe(pointer="/servers/1"), self.roots, [])
        self.assertEqual([item["name"] for item in items], ["b"])

    def test_an_empty_object_at_the_pointer_yields_one_not_present_item(self) -> None:
        self.write(self.user_config / "settings.json", '{"mcpServers": {}}')
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertEqual(items[0]["attributes"]["reason"], "no_match")

    def test_a_non_mapping_at_the_pointer_yields_one_item_for_the_value(self) -> None:
        self.write(self.user_config / "settings.json", '{"servers": ["a", "b"]}')
        items = run_probe(self.probe(pointer="/servers"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertEqual(items[0]["attributes"]["value"], ["a", "b"])

    def test_an_empty_key_falls_back_to_the_files_name(self) -> None:
        self.write(self.user_config / "settings.json", '{"mcpServers": {"": {}}}')
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["name"].strip())


class PointerEscapeTests(ProbeTestCase):
    """RFC 6901: `~1` is `/` and `~0` is `~`, unescaped in that order."""

    def probe(self, pointer: str) -> dict:
        return {
            "kind": "mcp-server",
            "path": "$USER_CONFIG/settings.json",
            "parse": "json",
            "pointer": pointer,
        }

    def test_tilde_one_means_a_slash(self) -> None:
        self.write(
            self.user_config / "settings.json", json.dumps({"a/b": {"inner": {}}})
        )
        items = run_probe(self.probe("/a~1b"), self.roots, [])
        self.assertEqual([item["name"] for item in items], ["inner"])

    def test_tilde_zero_means_a_tilde(self) -> None:
        self.write(
            self.user_config / "settings.json", json.dumps({"a~b": {"inner": {}}})
        )
        items = run_probe(self.probe("/a~0b"), self.roots, [])
        self.assertEqual([item["name"] for item in items], ["inner"])

    def test_tilde_one_is_unescaped_before_tilde_zero(self) -> None:
        # `~01` must come back as the literal `~1`, never as `/`. Unescaping
        # `~0` first would turn `~01` into `~1` and then into `/`, resolving
        # the wrong key -- or, here, no key at all.
        self.write(
            self.user_config / "settings.json",
            json.dumps({"~1": {"right": {}}, "/": {"wrong": {}}}),
        )
        items = run_probe(self.probe("/~01"), self.roots, [])
        self.assertEqual([item["name"] for item in items], ["right"])

    def test_an_unescaped_slash_is_a_separator_not_a_key(self) -> None:
        self.write(
            self.user_config / "settings.json", json.dumps({"a/b": {"inner": {}}})
        )
        items = run_probe(self.probe("/a/b"), self.roots, [])
        self.assertEqual(items[0]["attributes"]["reason"], "pointer_unresolved")


class ParseErrorTests(ProbeTestCase):
    """A malformed file is `present` and says so with a stable string."""

    MALFORMED = '{"mcpServers": {"a": }\n'

    def probe(self) -> dict:
        return {
            "kind": "mcp-server",
            "path": "$USER_CONFIG/settings.json",
            "parse": "json",
            "pointer": "/mcpServers",
        }

    def test_a_malformed_file_yields_one_present_item(self) -> None:
        self.write(self.user_config / "settings.json", self.MALFORMED)
        items = run_probe(self.probe(), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")

    def test_a_malformed_file_keeps_its_digest(self) -> None:
        target = self.write(self.user_config / "settings.json", self.MALFORMED)
        items = run_probe(self.probe(), self.roots, [])
        self.assertEqual(items[0]["digest"], self.digest_of(target))

    def test_the_parse_error_is_the_exact_documented_constant(self) -> None:
        self.write(self.user_config / "settings.json", self.MALFORMED)
        items = run_probe(self.probe(), self.roots, [])
        self.assertEqual(items[0]["attributes"]["parse_error"], "malformed_json")
        self.assertIn("malformed_json", PARSE_ERRORS)

    def test_the_parse_error_does_not_carry_the_exceptions_own_text(self) -> None:
        # The interpreter's own message varies by version -- 3.13 rewrote
        # every `json` decoder message -- so a baseline carrying it diffs
        # against itself across machines.
        self.write(self.user_config / "settings.json", self.MALFORMED)
        items = run_probe(self.probe(), self.roots, [])
        try:
            json.loads(self.MALFORMED)
        except ValueError as exc:
            message = str(exc)
        else:  # pragma: no cover - the fixture is malformed by construction
            self.fail("the fixture parsed")
        dumped = json.dumps(items)
        self.assertNotIn(message, dumped)
        for fragment in ("Expecting", "line 1", "char ", "column"):
            self.assertNotIn(fragment, dumped)

    def test_a_malformed_file_carries_no_parsed_value(self) -> None:
        self.write(self.user_config / "settings.json", self.MALFORMED)
        items = run_probe(self.probe(), self.roots, [])
        self.assertNotIn("value", items[0]["attributes"])

    def test_no_file_content_reaches_a_malformed_items_output(self) -> None:
        self.write(
            self.user_config / "settings.json", '{"a": "PLAINTEXT-3b19de" '
        )
        items = run_probe(self.probe(), self.roots, [])
        self.assertNotIn("PLAINTEXT-3b19de", json.dumps(items))

    def test_undecodable_bytes_are_a_parse_error_not_a_crash(self) -> None:
        target = self.user_config / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\xff\xfe\x00garbage")
        items = run_probe(self.probe(), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertIn(items[0]["attributes"]["parse_error"], PARSE_ERRORS)


class RedactionThroughParseTests(ProbeTestCase):
    """Task 6 wired through: nothing parsed reaches an item unredacted."""

    PLAINTEXT = "PLAINTEXT-7c2e91af"

    def probe(self, **extra: object) -> dict:
        probe = {
            "kind": "mcp-server",
            "path": "$USER_CONFIG/settings.json",
            "parse": "json",
        }
        probe.update(extra)
        return probe

    def write_document(self, document: object) -> None:
        self.write(self.user_config / "settings.json", json.dumps(document))

    def test_the_plaintext_appears_nowhere_in_the_serialised_items(self) -> None:
        self.write_document(
            {
                "mcpServers": {
                    "one": {"command": "npx", "env": {"API_TOKEN": self.PLAINTEXT}},
                    "two": {"headers": {"Authorization": self.PLAINTEXT}},
                }
            }
        )
        items = run_probe(
            self.probe(pointer="/mcpServers"),
            self.roots,
            ["env", "*authorization*"],
        )
        self.assertEqual(len(items), 2)
        self.assertNotIn(self.PLAINTEXT, json.dumps(items))

    def test_a_marker_replaces_what_was_removed(self) -> None:
        self.write_document(
            {"mcpServers": {"one": {"env": {"API_TOKEN": self.PLAINTEXT}}}}
        )
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, ["env"])
        found = markers(items[0]["attributes"]["value"])
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0]["digest"], DIGEST)

    def test_a_sensitive_key_at_the_pointed_location_itself_is_redacted(self) -> None:
        self.write_document({"mcpServers": {"api_token": self.PLAINTEXT}})
        items = run_probe(
            self.probe(pointer="/mcpServers"), self.roots, ["*token*"]
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "api_token")
        self.assertNotIn(self.PLAINTEXT, json.dumps(items))
        self.assertEqual(len(markers(items[0]["attributes"]["value"])), 1)

    def test_the_whole_document_form_is_redacted_too(self) -> None:
        self.write_document({"env": {"API_TOKEN": self.PLAINTEXT}})
        items = run_probe(self.probe(), self.roots, ["env"])
        self.assertNotIn(self.PLAINTEXT, json.dumps(items))

    def test_a_pointer_into_a_redacted_subtree_never_enumerates_it(self) -> None:
        self.write_document({"env": {"API_TOKEN": self.PLAINTEXT}})
        items = run_probe(self.probe(pointer="/env"), self.roots, ["env"])
        self.assertNotIn(self.PLAINTEXT, json.dumps(items))
        self.assertNotIn("API_TOKEN", json.dumps(items))

    def test_no_patterns_means_no_redaction(self) -> None:
        self.write_document({"mcpServers": {"one": {"command": "npx"}}})
        items = run_probe(self.probe(pointer="/mcpServers"), self.roots, [])
        self.assertEqual(items[0]["attributes"]["value"], {"command": "npx"})


TOML_THREE_SERVERS = """
[mcp_servers.gamma]
command = "npx"

[mcp_servers.alpha]
command = "uvx"

[mcp_servers.beta]
command = "node"
"""


@unittest.skipIf(
    scan_module.tomllib is None,
    "tomllib is absent below Python 3.11; the degradation suite covers that path",
)
class ParseTomlTests(ProbeTestCase):
    """`parse: "toml"` behaves identically through `tomllib`."""

    def probe(self, **extra: object) -> dict:
        probe = {
            "kind": "mcp-server",
            "path": "$USER_CONFIG/config.toml",
            "parse": "toml",
        }
        probe.update(extra)
        return probe

    def test_a_pointer_over_three_tables_yields_one_item_per_key(self) -> None:
        self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        self.assertEqual([item["name"] for item in items], ["alpha", "beta", "gamma"])

    def test_the_digest_is_still_the_files_bytes(self) -> None:
        target = self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        self.assertEqual({item["digest"] for item in items}, {self.digest_of(target)})

    def test_the_parsed_value_lands_in_attributes(self) -> None:
        self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        by_name = {item["name"]: item for item in items}
        self.assertEqual(by_name["alpha"]["attributes"]["value"], {"command": "uvx"})

    def test_a_pointer_omitted_yields_one_item_for_the_whole_document(self) -> None:
        self.write(self.user_config / "config.toml", 'model = "o3"\n')
        items = run_probe(self.probe(), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["attributes"]["value"], {"model": "o3"})

    def test_a_pointer_that_does_not_resolve_yields_one_not_present_item(self) -> None:
        self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        items = run_probe(self.probe(pointer="/nowhere"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertEqual(items[0]["attributes"]["reason"], "pointer_unresolved")

    def test_a_malformed_file_is_present_with_a_stable_parse_error(self) -> None:
        self.write(self.user_config / "config.toml", "this is not = = toml\n")
        items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertEqual(items[0]["attributes"]["parse_error"], "malformed_toml")
        self.assertIn("malformed_toml", PARSE_ERRORS)

    def test_values_are_redacted(self) -> None:
        self.write(
            self.user_config / "config.toml",
            '[mcp_servers.one.env]\nAPI_TOKEN = "PLAINTEXT-5ad0c1"\n',
        )
        items = run_probe(
            self.probe(pointer="/mcp_servers"), self.roots, ["env"]
        )
        self.assertNotIn("PLAINTEXT-5ad0c1", json.dumps(items))

    def test_a_toml_date_survives_serialisation(self) -> None:
        # `tomllib` yields `datetime.date`, which `json.dumps` refuses. The
        # entry is emitted as JSON, so a value that cannot be serialised would
        # crash the command rather than the parse.
        self.write(self.user_config / "config.toml", "[a]\nwhen = 2026-07-30\n")
        items = run_probe(self.probe(pointer="/a"), self.roots, [])
        self.assertEqual(len(items), 1)
        json.dumps(items)


class TomllibDegradationTests(ProbeTestCase):
    """Design spec section 14: not a crash, and not a pretence of emptiness.

    `tomllib` arrived in Python 3.11 and the bundle supports 3.10. The module
    binds `None` when the import fails and branches on the binding, so this
    test patches the binding rather than requiring an old interpreter -- a
    test that can only run on an interpreter the developer does not have is a
    test that never runs.
    """

    def probe(self, **extra: object) -> dict:
        probe = {
            "kind": "mcp-server",
            "path": "$USER_CONFIG/config.toml",
            "parse": "toml",
        }
        probe.update(extra)
        return probe

    def test_a_toml_probe_yields_one_present_item_with_its_digest(self) -> None:
        target = self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        with mock.patch.object(scan_module, "tomllib", None):
            items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertEqual(items[0]["digest"], self.digest_of(target))

    def test_the_item_says_the_parser_was_unavailable(self) -> None:
        self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        with mock.patch.object(scan_module, "tomllib", None):
            items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        self.assertEqual(items[0]["attributes"]["parse_unavailable"], "toml")

    def test_no_parsed_keys_are_produced(self) -> None:
        self.write(self.user_config / "config.toml", TOML_THREE_SERVERS)
        with mock.patch.object(scan_module, "tomllib", None):
            items = run_probe(self.probe(pointer="/mcp_servers"), self.roots, [])
        self.assertNotIn("value", items[0]["attributes"])
        self.assertNotIn("parse_error", items[0]["attributes"])
        self.assertNotIn("alpha", json.dumps(items))

    def test_no_file_content_reaches_the_item(self) -> None:
        self.write(self.user_config / "config.toml", 'a = "PLAINTEXT-91c40b"\n')
        with mock.patch.object(scan_module, "tomllib", None):
            items = run_probe(self.probe(), self.roots, [])
        self.assertNotIn("PLAINTEXT-91c40b", json.dumps(items))

    def test_a_json_probe_is_unaffected(self) -> None:
        self.write(
            self.user_config / "settings.json", '{"mcpServers": {"alpha": {}}}'
        )
        with mock.patch.object(scan_module, "tomllib", None):
            items = run_probe(
                {
                    "kind": "mcp-server",
                    "path": "$USER_CONFIG/settings.json",
                    "parse": "json",
                    "pointer": "/mcpServers",
                },
                self.roots,
                [],
            )
        self.assertEqual([item["name"] for item in items], ["alpha"])


class ParsedItemAgreementTests(ProbeTestCase):
    """Parsed items are baseline items and must satisfy the same validator."""

    def produce_items(self) -> list[dict]:
        self.write(
            self.user_config / "settings.json",
            json.dumps(
                {
                    "mcpServers": {
                        "alpha": {"command": "npx", "env": {"T": "PLAINTEXT-0f1"}},
                        "beta": {"command": "uvx"},
                    }
                }
            ),
        )
        self.write(self.user_config / "broken.json", "{")
        probes = [
            {
                "kind": "mcp-server",
                "scope": "user",
                "path": "$USER_CONFIG/settings.json",
                "parse": "json",
                "pointer": "/mcpServers",
            },
            {
                "kind": "mcp-server",
                "scope": "user",
                "path": "$USER_CONFIG/settings.json",
                "parse": "json",
                "pointer": "/absent",
            },
            {
                "kind": "mcp-server",
                "scope": "user",
                "path": "$USER_CONFIG/broken.json",
                "parse": "json",
            },
            {
                "kind": "mcp-server",
                "scope": "user",
                "path": "$USER_CONFIG/gone.json",
                "parse": "json",
                "pointer": "/mcpServers",
            },
        ]
        items: list[dict] = []
        for probe in probes:
            items.extend(run_probe(probe, self.roots, ["env"]))
        return items

    def test_the_parsed_items_pass_validate_baseline(self) -> None:
        items = self.produce_items()
        self.assertGreaterEqual(len(items), 5)
        entry = {
            "id": "BASE-2026-000",
            "captured_on": "2026-07-30",
            "client": "claude-code",
            "adapter_version": 1,
            "items": items,
        }
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])

    def test_the_parsed_entry_survives_a_json_round_trip(self) -> None:
        entry = {
            "id": "BASE-2026-000",
            "captured_on": "2026-07-30",
            "client": "claude-code",
            "adapter_version": 1,
            "items": self.produce_items(),
        }
        restored = json.loads(json.dumps(entry))
        self.assertEqual(validate_baseline(restored, 0, source="scan"), [])
        self.assertNotIn("PLAINTEXT-0f1", json.dumps(restored))


class BaselineAgreementTests(ProbeTestCase):
    """The items must satisfy the validator schema 0.2.3 shipped."""

    def produce_items(self) -> list[dict]:
        self.write(self.user_config / "CLAUDE.md", "# memory\n")
        self.write(self.skills / "one" / "SKILL.md", "a\n")
        self.write(self.skills / "two" / "SKILL.md", "b\n")
        (self.user_config / "empty").mkdir()
        probes = [
            {"kind": "instruction-file", "scope": "user", "path": "$USER_CONFIG/CLAUDE.md"},
            {"kind": "skill", "scope": "user", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            {"kind": "instruction-file", "scope": "user", "path": "$USER_CONFIG/GONE.md"},
            {"kind": "hook", "scope": "user", "glob": "$USER_CONFIG/hooks/*.js"},
            {"kind": "command", "scope": "user", "glob": "$USER_CONFIG/empty"},
            {"kind": "agent", "scope": "managed", "glob": "$NOT_RESOLVED/agents/*.md"},
        ]
        items: list[dict] = []
        for probe in probes:
            items.extend(run_probe(probe, self.roots, []))
        return items

    def test_the_items_pass_validate_baseline_with_zero_findings(self) -> None:
        items = self.produce_items()
        self.assertGreaterEqual(len(items), 6)
        entry = {
            "id": "BASE-2026-000",
            "captured_on": "2026-07-30",
            "client": "claude-code",
            "adapter_version": 1,
            "items": items,
        }
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])

    def test_the_entry_survives_a_json_round_trip(self) -> None:
        entry = {
            "id": "BASE-2026-000",
            "captured_on": "2026-07-30",
            "client": "claude-code",
            "adapter_version": 1,
            "items": self.produce_items(),
        }
        restored = json.loads(json.dumps(entry))
        self.assertEqual(validate_baseline(restored, 0, source="scan"), [])


def minimal_ledger() -> dict:
    """The smallest ledger `verify` accepts.

    Built the way `test_dashboard.py` builds its fixtures, and deliberately
    duplicated rather than imported: importing across test modules would make
    this suite fail for a reason that lives in another file, and the whole
    point of the acceptance test below is that a `scan` entry drops into a
    ledger nobody edited to accommodate it.
    """
    return {
        "schema_version": "1.0",
        "ledger_id": "l-000000",
        "scope": "global",
        "language": "en",
        "client": "claude-code",
        "adapter_version": 1,
        "created": "2026-07-29",
        "updated": "2026-07-30",
        "id_authority": True,
        "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 1},
        "known_projects": [],
        "records": [],
        "baselines": [],
        "backlog": [],
    }


class ScanTestCase(unittest.TestCase):
    """A whole fake machine: an adapter directory, a user config, a project.

    Anchor candidates are written as absolute paths into the temporary tree
    rather than as `$env:` names, so every test here is hermetic against the
    real environment: nothing this suite runs can be steered by whatever
    `CLAUDE_CONFIG_DIR` happens to hold on the machine running it.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bundled = self.tmp / "adapters"
        self.bundled.mkdir()
        self.user_config = self.tmp / "user_config"
        self.skills = self.user_config / "skills"
        self.skills.mkdir(parents=True)
        self.project = self.tmp / "project"
        self.project.mkdir()

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def adapter_document(self, **overrides: object) -> dict:
        document: dict = {
            "adapter_version": 3,
            "client": "test-client",
            "expires_on": "2099-01-01",
            "anchors": {
                "$USER_CONFIG": [str(self.user_config)],
                "$PROJECT": ["."],
            },
            "probes": [
                {
                    "kind": "instruction-file",
                    "scope": "user",
                    "path": "$USER_CONFIG/CLAUDE.md",
                },
                {
                    "kind": "skill",
                    "scope": "user",
                    "glob": "$USER_CONFIG/skills/*/SKILL.md",
                },
                {
                    "kind": "mcp-server",
                    "scope": "user",
                    "path": "$USER_CONFIG/settings.json",
                    "parse": "json",
                    "pointer": "/mcpServers",
                },
                {"kind": "hook", "scope": "project", "glob": "$PROJECT/hooks/*.js"},
                {
                    "kind": "agent",
                    "scope": "managed",
                    "path": "$USER_CONFIG/ABSENT.md",
                },
            ],
            "sensitive_key_patterns": ["env", "*token*"],
        }
        document.update(overrides)
        return document

    def write_adapter(self, name: str = "test-client.json", **overrides: object) -> Path:
        path = self.bundled / name
        path.write_text(
            json.dumps(self.adapter_document(**overrides)), encoding="utf-8"
        )
        return path

    def populate(self) -> None:
        """A machine with something on it, including a secret to not leak."""
        self.write(self.user_config / "CLAUDE.md", "# memory\n")
        self.write(self.skills / "one" / "SKILL.md", "a\n")
        self.write(self.skills / "two" / "SKILL.md", "b\n")
        self.write(
            self.user_config / "settings.json",
            json.dumps(
                {
                    "mcpServers": {
                        "alpha": {"command": "npx", "env": {"T": "PLAINTEXT-51ce"}},
                        "beta": {"command": "uvx"},
                    }
                }
            ),
        )
        self.write(self.project / "hooks" / "guard.js", "// guard\n")

    def do_scan(self, **kwargs: object) -> tuple[dict, list[str], int]:
        """Call `scan` with hermetic defaults, overridable per test."""
        if "adapter" not in kwargs:
            kwargs["adapter"] = self.write_adapter()
        arguments: dict = {
            "identifier": "BASE-2026-000",
            "client": None,
            "user_config": None,
            "project": self.project,
            "bundled": self.bundled,
            "environ": {},
            "captured_on": "2026-07-30",
        }
        arguments.update(kwargs)
        return scan(**arguments)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        """Drive `dashboard.main` the way a shell would, capturing both streams.

        Every CLI assertion in this module goes through `main`, never through
        `scan` directly. A previous release of this repository shipped a
        feature whose argparse wiring could be deleted without a single test
        noticing, because every test called the inner function.
        """
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def cli_arguments(self, adapter: Path | None = None) -> list[str]:
        return [
            "scan",
            "--id",
            "BASE-2026-000",
            "--adapter",
            str(adapter if adapter is not None else self.write_adapter()),
            "--project",
            str(self.project),
        ]


class ScanEntryTests(ScanTestCase):
    """The five fields design spec section 7.5 requires, and nothing else."""

    def test_the_entry_has_every_required_baseline_field(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        self.assertEqual(REQUIRED_BASELINE_FIELDS - set(entry), set())

    def test_the_entry_carries_no_field_beyond_the_required_five(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        self.assertEqual(set(entry), set(REQUIRED_BASELINE_FIELDS))

    def test_the_id_is_the_one_the_caller_allocated(self) -> None:
        entry, _, _ = self.do_scan(identifier="BASE-2026-042")
        self.assertEqual(entry["id"], "BASE-2026-042")

    def test_captured_on_comes_from_the_injected_parameter(self) -> None:
        entry, _, _ = self.do_scan(captured_on="2019-03-04")
        self.assertEqual(entry["captured_on"], "2019-03-04")

    def test_captured_on_defaults_to_today(self) -> None:
        entry, _, _ = self.do_scan(captured_on=None)
        self.assertEqual(entry["captured_on"], datetime.date.today().isoformat())

    def test_a_captured_on_that_is_not_a_date_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            self.do_scan(captured_on="yesterday")

    def test_client_and_adapter_version_come_from_the_adapter(self) -> None:
        entry, _, _ = self.do_scan()
        self.assertEqual(entry["client"], "test-client")
        self.assertEqual(entry["adapter_version"], 3)

    def test_every_probe_contributes_at_least_one_item(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        probes = self.adapter_document()["probes"]
        self.assertGreaterEqual(len(entry["items"]), len(probes))

    def test_a_probe_matching_nothing_is_still_recorded(self) -> None:
        entry, _, _ = self.do_scan()
        absent = [item for item in entry["items"] if item["state"] == "not_present"]
        self.assertTrue(absent)
        self.assertIn("ABSENT.md", json.dumps(absent))

    def test_an_adapter_with_no_probes_yields_an_empty_items_array(self) -> None:
        entry, _, _ = self.do_scan(adapter=self.write_adapter(probes=[]))
        self.assertEqual(entry["items"], [])

    def test_a_secret_in_a_parsed_file_never_reaches_the_entry(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        self.assertNotIn("PLAINTEXT-51ce", json.dumps(entry))


class ScanVerifyAcceptanceTests(ScanTestCase):
    """The acceptance criterion: the emitted entry is a valid ledger entry.

    This is what ties this release to the schema 0.2.3 shipped. It runs the
    real `verify` over a real file on disk rather than calling
    `validate_baseline` directly, because the command is what a user runs and
    the command is where a serialisation failure would surface.
    """

    def emit(self) -> dict:
        self.populate()
        entry, _, _ = self.do_scan()
        return entry

    def test_the_emitted_entry_verifies_clean_inside_a_ledger(self) -> None:
        ledger = minimal_ledger()
        ledger["baselines"] = [self.emit()]
        path = self.tmp / "ledger.json"
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verify([path])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("1 ledger(s) validated", out.getvalue())

    def test_the_emitted_entry_passes_validate_baseline(self) -> None:
        self.assertEqual(validate_baseline(self.emit(), 0, source="scan"), [])

    def test_the_entry_verifies_after_a_json_round_trip(self) -> None:
        restored = json.loads(json.dumps(self.emit(), indent=2))
        self.assertEqual(validate_baseline(restored, 0, source="scan"), [])

    def test_an_expired_scans_entry_still_verifies(self) -> None:
        self.populate()
        entry, _, code = self.do_scan(
            adapter=self.write_adapter(expires_on="2026-07-29")
        )
        self.assertEqual(code, 1)
        ledger = minimal_ledger()
        ledger["baselines"] = [entry]
        path = self.tmp / "ledger.json"
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(verify([path]), 0, err.getvalue())


class ScanItemTests(ScanTestCase):
    def test_every_item_origin_is_pre_existing(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        self.assertTrue(entry["items"])
        for item in entry["items"]:
            self.assertEqual(item["origin"], "pre-existing")

    def test_every_item_carries_its_probes_scope(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        self.assertTrue(entry["items"])
        for item in entry["items"]:
            self.assertIn("scope", item["attributes"], item)
            self.assertIn(item["attributes"]["scope"], {"user", "project", "managed"})

    def test_a_scope_survives_onto_a_not_present_item(self) -> None:
        entry, _, _ = self.do_scan()
        absent = [item for item in entry["items"] if item["state"] == "not_present"]
        self.assertTrue(absent)
        for item in absent:
            self.assertIn("scope", item["attributes"], item)

    def test_every_item_state_is_from_the_closed_set(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        for item in entry["items"]:
            self.assertIn(item["state"], BASELINE_ITEM_STATES)

    def test_project_scoped_items_are_anchored_at_the_named_project(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan()
        hooks = [item for item in entry["items"] if item["kind"] == "hook"]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["anchor"], "$PROJECT/hooks/guard.js")


class ScanExpiryTests(ScanTestCase):
    """An adapter past its expiry is a finding, never an error.

    An adapter whose paths have quietly gone stale produces a baseline that
    looks clean, and a silently clean baseline is the worst output this tool
    can produce. So the run continues and says so, rather than refusing and
    leaving the operator with nothing.
    """

    def expired(self, **overrides: object) -> tuple[dict, list[str], int]:
        self.populate()
        return self.do_scan(adapter=self.write_adapter(expires_on="2026-07-29", **overrides))

    def test_an_expired_adapter_produces_a_finding(self) -> None:
        _, findings, _ = self.expired()
        self.assertTrue(
            any("expired" in finding for finding in findings), findings
        )

    def test_the_expiry_finding_names_the_date_and_the_client(self) -> None:
        _, findings, _ = self.expired()
        expiry = next(finding for finding in findings if "expired" in finding)
        self.assertIn("'2026-07-29'", expiry)
        self.assertIn("'test-client'", expiry)

    def test_an_expired_adapter_still_emits_a_baseline(self) -> None:
        entry, _, _ = self.expired()
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])
        self.assertTrue(entry["items"])

    def test_an_expired_adapter_exits_one(self) -> None:
        _, _, code = self.expired()
        self.assertEqual(code, 1)

    def test_an_unexpired_adapter_produces_no_expiry_finding(self) -> None:
        self.populate()
        _, findings, code = self.do_scan()
        self.assertFalse(
            [finding for finding in findings if "expired" in finding], findings
        )
        self.assertEqual(code, 0)

    def test_an_adapter_expiring_on_the_day_of_the_scan_is_not_expired(self) -> None:
        self.populate()
        _, findings, code = self.do_scan(
            adapter=self.write_adapter(expires_on="2026-07-30"),
            captured_on="2026-07-30",
        )
        self.assertFalse(
            [finding for finding in findings if "expired" in finding], findings
        )
        self.assertEqual(code, 0)

    def test_expiry_is_judged_against_the_injected_date_not_the_clock(self) -> None:
        self.populate()
        _, findings, code = self.do_scan(
            adapter=self.write_adapter(expires_on="2099-01-01"),
            captured_on="2099-06-01",
        )
        self.assertTrue(any("expired" in finding for finding in findings), findings)
        self.assertEqual(code, 1)


class ScanUnresolvedAnchorTests(ScanTestCase):
    """An anchor no candidate resolves is the other way a baseline lies.

    Not settled by the spec, which names only expiry. Recorded as a finding on
    the same grounds: every probe beneath an unresolved anchor is `not_present`
    whether the client is absent or the tool merely looked in the wrong place,
    and those two must not be reported identically.
    """

    def unresolved(self) -> tuple[dict, list[str], int]:
        adapter = self.write_adapter(
            anchors={
                "$USER_CONFIG": [str(self.tmp / "nowhere")],
                "$PROJECT": ["."],
            }
        )
        return self.do_scan(adapter=adapter)

    def test_an_unresolved_anchor_produces_a_finding(self) -> None:
        _, findings, code = self.unresolved()
        self.assertTrue(
            any("unresolved" in finding for finding in findings), findings
        )
        self.assertEqual(code, 1)

    def test_an_unresolved_anchor_still_emits_a_baseline(self) -> None:
        entry, _, _ = self.unresolved()
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])
        self.assertTrue(entry["items"])

    def test_every_probe_under_an_unresolved_anchor_is_not_present(self) -> None:
        entry, _, _ = self.unresolved()
        under = [
            item for item in entry["items"] if item["anchor"].startswith("$USER_CONFIG")
        ]
        self.assertTrue(under)
        for item in under:
            self.assertEqual(item["state"], "not_present")
            self.assertEqual(item["attributes"]["reason"], "unresolved_anchor")


class UnresolvedAnchorFindingScopeTests(ScanTestCase):
    """Only `$USER_CONFIG` unresolved is a finding; the rest are just recorded.

    docs/validation/scan-dogfood-0.2.5.md finding 9. `codex.json` declares
    `$SYSTEM_CONFIG` as `/etc/codex`, which no Windows host can ever have, so
    the finding fired on every run forever and taught the operator to ignore
    the exit code. The item on each probe is the honest record; the finding is
    reserved for the one anchor whose absence makes the whole baseline vacuous.
    """

    SYSTEM_CONFIG = Path("/etc/codex")

    def with_system_config(self) -> tuple[dict, list[str], int]:
        """`$USER_CONFIG` resolves; a second anchor does not."""
        adapter = self.write_adapter(
            anchors={
                "$USER_CONFIG": [str(self.user_config)],
                "$PROJECT": ["."],
                "$SYSTEM_CONFIG": [str(self.tmp / "no-such-system-root")],
            },
            probes=[
                {
                    "kind": "instruction-file",
                    "scope": "user",
                    "path": "$USER_CONFIG/CLAUDE.md",
                },
                {
                    "kind": "instruction-file",
                    "scope": "system",
                    "path": "$SYSTEM_CONFIG/AGENTS.md",
                },
            ],
        )
        self.populate()
        return self.do_scan(adapter=adapter)

    def test_an_unresolved_anchor_that_is_not_user_config_is_no_finding(self) -> None:
        _, findings, code = self.with_system_config()
        self.assertFalse(
            [finding for finding in findings if "unresolved" in finding], findings
        )
        self.assertEqual(code, 0)

    def test_its_probes_are_still_recorded_not_present(self) -> None:
        """No finding is not the same as no record."""
        entry, _, _ = self.with_system_config()
        under = [
            item
            for item in entry["items"]
            if item["anchor"].startswith("$SYSTEM_CONFIG")
        ]
        self.assertTrue(under)
        for item in under:
            self.assertEqual(item["state"], "not_present")
            self.assertEqual(item["attributes"]["reason"], "unresolved_anchor")

    def test_an_unresolved_user_config_is_still_a_finding(self) -> None:
        adapter = self.write_adapter(
            anchors={
                "$USER_CONFIG": [str(self.tmp / "nowhere")],
                "$PROJECT": ["."],
                "$SYSTEM_CONFIG": [str(self.tmp / "no-such-system-root")],
            }
        )
        _, findings, code = self.do_scan(adapter=adapter)
        unresolved = [finding for finding in findings if "unresolved" in finding]
        self.assertTrue(unresolved, findings)
        self.assertEqual(code, 1)
        self.assertIn("USER_CONFIG", unresolved[0])

    def test_the_shipped_codex_adapter_does_not_fire_on_a_host_without_etc_codex(
        self,
    ) -> None:
        """The case that shipped broken, asserted against the real adapter.

        A fixture would have passed the whole time. What was wrong was
        `codex.json`'s `$SYSTEM_CONFIG` meeting a host that has no `/etc`, and
        only the bundled file states that pairing.
        """
        if self.SYSTEM_CONFIG.is_dir():
            self.skipTest(f"{self.SYSTEM_CONFIG} exists on this host")
        home = self.tmp / "home"
        (home / ".codex").mkdir(parents=True)
        with mock.patch.dict(
            os.environ, {"HOME": str(home), "USERPROFILE": str(home)}
        ):
            _, findings, code = self.do_scan(
                adapter=None,
                client="codex",
                bundled=ADAPTERS_DIR,
                environ={},
            )
        self.assertFalse(
            [finding for finding in findings if "unresolved" in finding], findings
        )
        self.assertEqual(code, 0)


class ScanFallbackSelectionTests(ScanTestCase):
    """Falling back to `generic` is a coverage failure, not a quiet outcome.

    docs/validation/scan-dogfood-0.2.5.md finding 1: on a machine with two
    supported clients installed, the plan's own `scan --id BASE-2026-000`
    selected `generic`, emitted `"items": []`, printed the reason to stderr,
    and exited `0`. The exit code is the one thing a script reads, and it said
    the machine was clean when nothing had been looked at.
    """

    def write_client(self, client: str, user_config: Path) -> Path:
        path = self.bundled / f"{client}.json"
        path.write_text(
            json.dumps(
                self.adapter_document(
                    client=client,
                    anchors={
                        "$USER_CONFIG": [str(user_config)],
                        "$PROJECT": ["."],
                    },
                )
            ),
            encoding="utf-8",
        )
        return path

    def write_generic(self) -> Path:
        path = self.bundled / "generic.json"
        path.write_text(
            json.dumps(
                {
                    "adapter_version": 1,
                    "client": "generic",
                    "expires_on": "2099-01-01",
                    "anchors": {"$PROJECT": ["."]},
                    "probes": [],
                    "sensitive_key_patterns": [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def detected(self, *clients: str) -> tuple[dict, list[str], int]:
        """A machine where each named client's `$USER_CONFIG` exists."""
        self.write_generic()
        for client in ("alpha", "beta"):
            root = self.tmp / f"{client}-home"
            if client in clients:
                root.mkdir()
            self.write_client(client, root)
        return self.do_scan(adapter=None)

    def fallback_findings(self, messages: list[str]) -> list[str]:
        """The finding, told apart from the selection note beside it.

        `scan` returns notes and findings in one list. Matching on "generic"
        would match the note too -- including the note for `--client generic`,
        which is the case that must produce nothing -- so the filter is a
        phrase only the finding uses.
        """
        return [message for message in messages if "fell back" in message]

    def test_ambiguous_detection_is_a_finding_and_exits_one(self) -> None:
        entry, findings, code = self.detected("alpha", "beta")
        self.assertEqual(entry["client"], "generic")
        self.assertTrue(self.fallback_findings(findings), findings)
        self.assertEqual(code, 1)

    def test_the_ambiguous_finding_names_both_candidates_and_points_at_client(
        self,
    ) -> None:
        _, findings, _ = self.detected("alpha", "beta")
        finding = self.fallback_findings(findings)[0]
        self.assertIn("alpha", finding)
        self.assertIn("beta", finding)
        self.assertIn("--client", finding)

    def test_the_empty_baseline_is_still_emitted(self) -> None:
        entry, _, _ = self.detected("alpha", "beta")
        self.assertEqual(entry["items"], [])
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])

    def test_detecting_nothing_is_a_finding_and_exits_one(self) -> None:
        entry, findings, code = self.detected()
        self.assertEqual(entry["client"], "generic")
        self.assertTrue(self.fallback_findings(findings), findings)
        self.assertEqual(code, 1)

    def test_generic_asked_for_by_name_is_no_finding_and_exits_zero(self) -> None:
        """The operator chose an adapter that probes nothing. That is an
        answer, not a failure, and it must not move the exit code."""
        self.write_generic()
        for client in ("alpha", "beta"):
            root = self.tmp / f"{client}-home"
            root.mkdir()
            self.write_client(client, root)
        entry, findings, code = self.do_scan(adapter=None, client="generic")
        self.assertEqual(entry["client"], "generic")
        self.assertFalse(self.fallback_findings(findings), findings)
        self.assertEqual(code, 0)

    def test_a_detected_client_is_no_finding(self) -> None:
        entry, findings, code = self.detected("alpha")
        self.assertEqual(entry["client"], "alpha")
        self.assertFalse(self.fallback_findings(findings), findings)
        self.assertEqual(code, 0)


class ScanIdentifierTests(ScanTestCase):
    """`--id` is checked, not allocated.

    Identifier allocation is a ledger concern with rules about sequences,
    provisional suffixes, and cross-scope collision. `scan` does not get a
    second, private implementation of it; it checks the shape and refuses.
    """

    def test_a_well_formed_baseline_id_is_accepted(self) -> None:
        entry, _, _ = self.do_scan(identifier="BASE-2026-999")
        self.assertEqual(entry["id"], "BASE-2026-999")

    def test_a_provisional_baseline_id_is_accepted(self) -> None:
        entry, _, _ = self.do_scan(identifier="BASE-2026-001-P")
        self.assertEqual(entry["id"], "BASE-2026-001-P")

    def test_a_malformed_id_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            self.do_scan(identifier="NOPE")

    def test_the_malformed_id_message_names_the_pattern(self) -> None:
        with self.assertRaises(LedgerError) as caught:
            self.do_scan(identifier="NOPE")
        self.assertIn(RECORD_ID.pattern, str(caught.exception))

    def test_a_right_shape_wrong_prefix_id_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError) as caught:
            self.do_scan(identifier="RUN-2026-001")
        self.assertIn(BASELINE_PREFIX, str(caught.exception))

    def test_an_empty_id_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            self.do_scan(identifier="")

    def test_the_id_is_checked_before_anything_is_read(self) -> None:
        # A bad id must not cost a directory walk. The adapter path below does
        # not exist, so reaching the loader at all would raise a different
        # error than the one asserted.
        with self.assertRaises(LedgerError) as caught:
            self.do_scan(identifier="NOPE", adapter=self.tmp / "no-such-adapter.json")
        self.assertIn(RECORD_ID.pattern, str(caught.exception))


class ScanCliTests(ScanTestCase):
    """Everything here goes through `dashboard.main`, never through `scan`."""

    def test_the_subcommand_is_wired_into_main(self) -> None:
        self.populate()
        code, stdout, _ = self.run_cli(*self.cli_arguments())
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["client"], "test-client")

    def test_the_entry_is_written_to_stdout_as_indented_json(self) -> None:
        self.populate()
        _, stdout, _ = self.run_cli(*self.cli_arguments())
        entry = json.loads(stdout)
        self.assertEqual(stdout.rstrip("\n"), json.dumps(entry, indent=2))

    def test_stdout_holds_the_entry_and_nothing_else(self) -> None:
        """A caller must be able to pipe stdout straight into a JSON reader."""
        self.populate()
        _, stdout, stderr = self.run_cli(*self.cli_arguments())
        entry = json.loads(stdout)
        self.assertEqual(set(entry), set(REQUIRED_BASELINE_FIELDS))
        self.assertNotIn("selected adapter", stdout)
        self.assertIn("selected adapter", stderr)

    def test_selection_notes_reach_stderr(self) -> None:
        self.populate()
        _, _, stderr = self.run_cli(*self.cli_arguments())
        self.assertIn("selected adapter", stderr)
        self.assertIn("test-client", stderr)

    def test_selection_notes_are_not_inside_the_entrys_items(self) -> None:
        self.populate()
        _, stdout, _ = self.run_cli(*self.cli_arguments())
        self.assertNotIn("selected adapter", json.dumps(json.loads(stdout)["items"]))

    def test_findings_reach_stderr_and_the_entry_still_reaches_stdout(self) -> None:
        self.populate()
        adapter = self.write_adapter(expires_on="2026-07-29")
        code, stdout, stderr = self.run_cli(*self.cli_arguments(adapter))
        self.assertEqual(code, 1)
        self.assertIn("expired", stderr)
        self.assertNotIn("expired", stdout)
        self.assertEqual(validate_baseline(json.loads(stdout), 0, source="cli"), [])

    def test_a_missing_id_exits_two(self) -> None:
        code, stdout, stderr = self.run_cli(
            "scan", "--adapter", str(self.write_adapter()), "--project", str(self.project)
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        # Asserting on the *reason* and not only on the code: without this,
        # the test would pass just as happily against a parser that has no
        # `scan` subcommand at all, since argparse answers an unknown
        # subcommand with exit 2 as well.
        self.assertIn("--id", stderr)

    def test_a_malformed_id_exits_two_naming_the_pattern(self) -> None:
        arguments = self.cli_arguments()
        arguments[arguments.index("BASE-2026-000")] = "NOPE"
        code, stdout, stderr = self.run_cli(*arguments)
        self.assertEqual(code, 2)
        self.assertIn(RECORD_ID.pattern, stderr)
        self.assertEqual(stdout, "")

    def test_a_right_shape_wrong_prefix_id_exits_two(self) -> None:
        arguments = self.cli_arguments()
        arguments[arguments.index("BASE-2026-000")] = "RUN-2026-001"
        code, stdout, stderr = self.run_cli(*arguments)
        self.assertEqual(code, 2)
        self.assertIn(BASELINE_PREFIX, stderr)
        self.assertEqual(stdout, "")

    def test_an_unknown_client_exits_two(self) -> None:
        self.write_adapter()
        code, stdout, stderr = self.run_cli(
            "scan",
            "--id",
            "BASE-2026-000",
            "--client",
            "no-such-client",
            "--project",
            str(self.project),
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("no-such-client", stderr)

    def test_an_unreadable_adapter_exits_two(self) -> None:
        missing = self.tmp / "no-such-adapter.json"
        code, stdout, stderr = self.run_cli(
            "scan",
            "--id",
            "BASE-2026-000",
            "--adapter",
            str(missing),
            "--project",
            str(self.project),
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn(missing.name, stderr)

    def test_the_client_flag_selects_a_bundled_adapter(self) -> None:
        """Against the real bundled directory: there is no `--bundled` flag.

        `generic` is chosen deliberately -- it probes nothing, so this test
        exercises the selection path without reading the machine's real
        configuration into a unit test.
        """
        code, stdout, stderr = self.run_cli(
            "scan",
            "--id",
            "BASE-2026-000",
            "--client",
            "generic",
            "--project",
            str(self.project),
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["client"], "generic")
        self.assertEqual(json.loads(stdout)["items"], [])

    def test_verify_still_dispatches(self) -> None:
        ledger = minimal_ledger()
        path = self.tmp / "ledger.json"
        path.write_text(json.dumps(ledger), encoding="utf-8")
        code, stdout, _ = self.run_cli("verify", str(path))
        self.assertEqual(code, 0)
        self.assertIn("1 ledger(s) validated", stdout)

    def test_scan_is_re_exported_from_dashboard(self) -> None:
        self.assertIs(dashboard.scan, scan_module.scan)
        self.assertIs(dashboard.scan_command, scan_module.scan_command)


class ScanSubprocessTests(ScanTestCase):
    """The real thing: a separate process, a real pipe, a real exit code."""

    def invoke(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "scan",
                "--id",
                "BASE-2026-000",
                "--adapter",
                str(self.write_adapter()),
                "--project",
                str(self.project),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_stdout_is_parseable_json_on_its_own(self) -> None:
        self.populate()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads(result.stdout)
        self.assertEqual(set(entry), set(REQUIRED_BASELINE_FIELDS))

    def test_nothing_but_the_entry_is_written_to_stdout(self) -> None:
        self.populate()
        result = self.invoke()
        self.assertEqual(
            result.stdout.rstrip("\n"), json.dumps(json.loads(result.stdout), indent=2)
        )
        self.assertNotEqual(result.stderr.strip(), "")

    def test_a_secret_does_not_survive_the_pipe(self) -> None:
        self.populate()
        result = self.invoke()
        self.assertNotIn("PLAINTEXT-51ce", result.stdout)
        self.assertNotIn("PLAINTEXT-51ce", result.stderr)


class ScanWritesNothingTests(ScanTestCase):
    """`scan` is read-only, and the guard is a patch rather than a chmod.

    A read-only tree is not portable -- Windows honours neither a POSIX mode
    nor a directory-level deny for the owner reliably -- and it reports a
    generic permission error rather than naming which call tried to write.
    These patches fail loudly and say what was attempted.
    """

    def arm(self) -> None:
        real_path_open = Path.open
        real_open = builtins.open

        def guarded_path_open(this, mode="r", *args, **kwargs):
            if isinstance(mode, str) and set(mode) & set("wxa+"):
                raise AssertionError(f"scan opened {this} with mode {mode!r}")
            return real_path_open(this, mode, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            if isinstance(mode, str) and set(mode) & set("wxa+"):
                raise AssertionError(f"scan opened {file!r} with mode {mode!r}")
            return real_open(file, mode, *args, **kwargs)

        def refuse(name):
            def guard(this, *args, **kwargs):
                raise AssertionError(f"scan called Path.{name} on {this}")

            return guard

        patches = [
            mock.patch.object(Path, "open", guarded_path_open),
            mock.patch.object(Path, "write_text", refuse("write_text")),
            mock.patch.object(Path, "write_bytes", refuse("write_bytes")),
            mock.patch.object(Path, "mkdir", refuse("mkdir")),
            mock.patch.object(Path, "touch", refuse("touch")),
            mock.patch.object(builtins, "open", guarded_open),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_guard_is_actually_armed(self) -> None:
        """Without this, a broken patch makes every test below pass silently."""
        self.arm()
        with self.assertRaises(AssertionError):
            (self.tmp / "written.txt").write_text("no", encoding="utf-8")
        with self.assertRaises(AssertionError):
            (self.tmp / "made").mkdir()
        with self.assertRaises(AssertionError):
            open(self.tmp / "opened.txt", "w").close()

    def test_a_full_scan_completes_with_every_write_api_failing_loudly(self) -> None:
        self.populate()
        adapter = self.write_adapter()
        self.arm()
        entry, _, code = self.do_scan(adapter=adapter)
        self.assertEqual(code, 0)
        self.assertTrue(entry["items"])

    def test_the_cli_writes_nothing_either(self) -> None:
        self.populate()
        arguments = self.cli_arguments()
        self.arm()
        code, stdout, _ = self.run_cli(*arguments)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout)["items"])

    def test_reading_still_works_under_the_guard(self) -> None:
        self.populate()
        adapter = self.write_adapter()
        self.arm()
        entry, _, _ = self.do_scan(adapter=adapter)
        present = [item for item in entry["items"] if item["state"] == "present"]
        self.assertTrue(present)
        self.assertTrue(any(item["digest"] for item in present))


class MultiAnchorEscapeTests(EscapeTests):
    """The shipped shape: several anchors, so a second can launder a path.

    `EscapeTests` builds a `roots` mapping holding exactly one anchor, which is
    the single configuration in which a match carried out of the probe's own
    anchor cannot land inside another one. `claude-code.json` declares three --
    `$USER_CONFIG`, `$HOME` (`~`), and `$PROJECT` -- and `$HOME` contains
    everything. Here `$HOME` is the whole temporary tree, so the directory the
    junction points at is inside it, and "is this inside *some* anchor" answers
    yes for a path the probe never named.

    Inheriting the single-anchor class is deliberate twice over: every
    assertion it makes must still hold with a second anchor present, and the
    two tests it already owns run again here against the mapping that has the
    hole in it.
    """

    def setUp(self) -> None:
        super().setUp()
        self.roots = {"USER_CONFIG": self.user_config, "HOME": self.tmp}

    def probe_the_skills(self) -> list[dict]:
        self.build_escape()
        return run_probe(
            {"kind": "skill", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
            self.roots,
            [],
        )

    def test_a_match_laundered_into_a_second_anchor_is_still_refused(self) -> None:
        items = self.probe_the_skills()
        refused = [item for item in items if item["state"] == "not_present"]
        self.assertEqual(len(refused), 1, items)
        self.assertIn(refused[0]["attributes"].get("reason"), PATH_SAFETY_REASONS)
        self.assertIsNone(refused[0]["digest"])

    def test_nothing_under_an_anchor_the_probe_never_named_is_read(self) -> None:
        """The refusal still records `$HOME/...` -- that is what it refused.

        What must not exist is a *present* item there: an anchor the probe
        never named may label a path in a refusal, and may never be the reason
        one was opened.
        """
        items = self.probe_the_skills()
        laundered = [
            item
            for item in items
            if item["anchor"].startswith("$HOME") and item["state"] == "present"
        ]
        self.assertEqual(laundered, [], items)
        self.assertTrue(
            all(
                item["digest"] is None
                for item in items
                if item["anchor"].startswith("$HOME")
            ),
            items,
        )

    def test_a_path_probe_is_held_to_its_own_anchor_too(self) -> None:
        """Not only globs. A literal `path` through the same junction escapes."""
        self.build_escape()
        items = run_probe(
            {"kind": "skill", "path": "$USER_CONFIG/skills/evil/SKILL.md"},
            self.roots,
            [],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertNotIn("PLAINTEXT-OUTSIDE-9a3f", json.dumps(items))


class GlobFailureTests(ProbeTestCase):
    """A glob `check_glob` accepts that `Path.glob` refuses at expansion.

    `Path.glob` raises `NotImplementedError` ("Non-relative patterns are
    unsupported") for a tail that is not relative. That is a `RuntimeError`
    subclass, so it is none of `OSError`, `ValueError`, `IndexError`, or
    `RecursionError`, and `scan_command` catches only `LedgerError`: before
    this it left `run_probe` as a traceback on a probe a user `local.json`
    could carry.
    """

    NON_RELATIVE = "$USER_CONFIG//Windows/*.ini"
    DRIVE_RELATIVE = "$USER_CONFIG/C:/Windows/*.ini"

    def adapter_with(self, pattern: str) -> dict:
        return {
            "adapter_version": 1,
            "client": "local",
            "expires_on": "2099-01-01",
            "anchors": {"$USER_CONFIG": ["~"]},
            "probes": [{"kind": "skill", "glob": pattern}],
            "sensitive_key_patterns": ["*token*"],
        }

    def test_the_pattern_is_one_the_load_time_checks_accept(self) -> None:
        """The premise. If either check refused it, `run_probe` never sees it."""
        check_glob(self.NON_RELATIVE)
        self.assertEqual(
            validate_adapter(self.adapter_with(self.NON_RELATIVE), source="local.json"),
            [],
        )

    def test_a_non_relative_glob_tail_is_one_glob_failed_item(self) -> None:
        items = run_probe(
            {"kind": "skill", "glob": self.NON_RELATIVE}, self.roots, []
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["attributes"]["reason"], "glob_failed")
        self.assertIn("glob_failed", SCAN_REASONS)

    def test_a_drive_relative_glob_tail_does_not_raise_either(self) -> None:
        # Only Windows treats `C:/...` as non-relative; on POSIX it is an
        # ordinary directory name that simply matches nothing. Both answers are
        # one item, which is the contract being asserted.
        items = run_probe(
            {"kind": "skill", "glob": self.DRIVE_RELATIVE}, self.roots, []
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIn(items[0]["attributes"]["reason"], SCAN_REASONS)


class ScanReasonCoverageTests(ProbeTestCase):
    """The reasons no test named. An unnamed reason is an untested branch."""

    def test_a_probe_with_no_target_records_malformed_probe(self) -> None:
        items = run_probe({"kind": "skill"}, self.roots, [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["attributes"]["reason"], "malformed_probe")
        self.assertIn("malformed_probe", SCAN_REASONS)

    def test_a_probe_whose_target_is_not_a_string_records_malformed_probe(
        self,
    ) -> None:
        items = run_probe({"kind": "skill", "glob": 7}, self.roots, [])
        self.assertEqual(items[0]["attributes"]["reason"], "malformed_probe")

    def test_a_stat_that_fails_after_the_path_check_records_inaccessible(self) -> None:
        """`inaccessible` is only reachable through a race, so inject the race.

        `resolve_anchored` ends by calling `Path.stat()` on the very path
        `_probe_one` is about to `os.stat`, and turns any failure into a
        `PathSafetyError`. A file that cannot be stat'ed at all is therefore
        refused by the path layer and never reaches `_probe_one`'s own
        `except`. What does reach it is the TOCTOU window between the two
        calls -- a file whose permissions change in between -- and that is
        exactly what is armed here: stat succeeds for the path layer and fails
        immediately afterwards.
        """
        target = self.write(self.user_config / "settings.json", "{}\n")
        real_stat = os.stat
        real_resolve_anchored = scan_module.resolve_anchored
        armed: dict[str, bool] = {"on": False}

        def arm(*arguments: object, **keywords: object) -> object:
            result = real_resolve_anchored(*arguments, **keywords)
            armed["on"] = True
            return result

        def stat_after_the_check(path, *arguments, **keywords):
            if armed["on"] and Path(path) == target:
                raise PermissionError(13, "Permission denied")
            return real_stat(path, *arguments, **keywords)

        with mock.patch.object(scan_module, "resolve_anchored", arm), \
                mock.patch.object(scan_module.os, "stat", stat_after_the_check):
            items = run_probe(
                {"kind": "mcp-server", "path": "$USER_CONFIG/settings.json"},
                self.roots,
                [],
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "not_present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["attributes"]["reason"], "inaccessible")
        self.assertIn("inaccessible", SCAN_REASONS)


class NonRegularFileTests(ProbeTestCase):
    """Only a regular file is digested. `file_digest` does a whole read.

    `claude-code.json` probes `$USER_CONFIG/agents/*`, which matches any name.
    A FIFO created under it makes `read_bytes()`'s `open()` block until a
    writer appears -- forever, for a scan nobody is feeding. A directory was
    already excluded before this; nothing else was.
    """

    def stat_as(self, target: Path, mode: int):
        """Report `target` with `mode`'s file type, everything else untouched."""
        real_stat = os.stat

        def stat_with_mode(path, *arguments, **keywords):
            info = real_stat(path, *arguments, **keywords)
            if Path(path) == target:
                fields = list(info)
                fields[0] = mode
                return os.stat_result(fields)
            return info

        return mock.patch.object(scan_module.os, "stat", stat_with_mode)

    def test_a_non_regular_file_is_present_with_a_reason_and_no_digest(self) -> None:
        target = self.write(
            self.user_config / "agents" / "pipe", "PLAINTEXT-FIFO-4c1d\n"
        )
        with self.stat_as(target, stat_module.S_IFIFO | 0o600):
            items = run_probe(
                {"kind": "agent", "glob": "$USER_CONFIG/agents/*"}, self.roots, []
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["attributes"]["reason"], "not_regular_file")
        self.assertIn("not_regular_file", SCAN_REASONS)
        self.assertNotIn("PLAINTEXT-FIFO-4c1d", json.dumps(items))

    def test_a_regular_file_beside_it_is_still_digested(self) -> None:
        target = self.write(self.user_config / "agents" / "pipe", "x\n")
        ordinary = self.write(self.user_config / "agents" / "real.md", "# agent\n")
        with self.stat_as(target, stat_module.S_IFIFO | 0o600):
            items = run_probe(
                {"kind": "agent", "glob": "$USER_CONFIG/agents/*"}, self.roots, []
            )
        digested = [item for item in items if item["digest"] is not None]
        self.assertEqual(len(digested), 1, items)
        self.assertEqual(digested[0]["digest"], self.digest_of(ordinary))

    @unittest.skipUnless(
        hasattr(os, "mkfifo"), "platform has no os.mkfifo; a FIFO cannot be built"
    )
    def test_a_real_fifo_is_recorded_without_blocking_on_a_read(self) -> None:
        import signal

        fifo = self.user_config / "agents" / "pipe"
        fifo.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(fifo)

        def give_up(signum: int, frame: object) -> None:
            raise AssertionError("run_probe blocked opening a FIFO")

        previous = signal.signal(signal.SIGALRM, give_up)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        signal.alarm(10)
        self.addCleanup(signal.alarm, 0)
        items = run_probe(
            {"kind": "agent", "glob": "$USER_CONFIG/agents/*"}, self.roots, []
        )
        signal.alarm(0)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "present")
        self.assertIsNone(items[0]["digest"])
        self.assertEqual(items[0]["attributes"]["reason"], "not_regular_file")


class SensitivePatternCoverageTests(ScanTestCase):
    """An adapter that parses documents with no patterns redacts nothing.

    `redact` with an empty pattern list is the identity function, so every
    value a `parse` probe reads is copied into the baseline verbatim. That is
    a legitimate configuration for an adapter that parses nothing -- and
    `generic.json` is exactly that -- so it is a finding rather than a refusal,
    and it is conditioned on a probe actually carrying `parse`.
    """

    NO_PARSE_PROBES = [
        {"kind": "instruction-file", "scope": "user", "path": "$USER_CONFIG/CLAUDE.md"},
        {"kind": "skill", "scope": "user", "glob": "$USER_CONFIG/skills/*/SKILL.md"},
    ]

    def unredacted(self) -> list[str]:
        self.populate()
        _, findings, self.code = self.do_scan(
            adapter=self.write_adapter(sensitive_key_patterns=[])
        )
        return [
            finding for finding in findings if "sensitive_key_patterns" in finding
        ]

    def test_a_parsing_adapter_with_no_patterns_is_a_finding(self) -> None:
        self.assertTrue(self.unredacted())
        self.assertEqual(self.code, 1)

    def test_the_finding_names_the_client_and_says_what_to_add(self) -> None:
        finding = self.unredacted()[0]
        self.assertIn("'test-client'", finding)
        self.assertIn("parse", finding)
        self.assertIn("*token*", finding)

    def test_the_baseline_is_still_emitted(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan(
            adapter=self.write_adapter(sensitive_key_patterns=[])
        )
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])
        self.assertTrue(entry["items"])

    def test_an_adapter_with_patterns_produces_no_such_finding(self) -> None:
        self.populate()
        _, findings, code = self.do_scan()
        self.assertFalse(
            [f for f in findings if "sensitive_key_patterns" in f], findings
        )
        self.assertEqual(code, 0)

    def test_no_parse_probe_and_no_patterns_is_no_finding(self) -> None:
        self.populate()
        _, findings, code = self.do_scan(
            adapter=self.write_adapter(
                probes=self.NO_PARSE_PROBES, sensitive_key_patterns=[]
            )
        )
        self.assertFalse(
            [f for f in findings if "sensitive_key_patterns" in f], findings
        )
        self.assertEqual(code, 0)

    def test_the_bundled_generic_adapter_stays_clean(self) -> None:
        """`generic.json` ships `[]` patterns and `[]` probes, and must not fire."""
        _, findings, code = self.do_scan(adapter=ADAPTERS_DIR / "generic.json")
        self.assertFalse(
            [f for f in findings if "sensitive_key_patterns" in f], findings
        )
        self.assertEqual(code, 0)

    def test_every_bundled_adapter_stays_clean(self) -> None:
        for path in sorted(ADAPTERS_DIR.glob("*.json")):
            with self.subTest(adapter=path.name):
                _, findings, _ = self.do_scan(adapter=path)
                self.assertFalse(
                    [f for f in findings if "sensitive_key_patterns" in f], findings
                )


class EnvAnchorScanTests(ScanTestCase):
    """A `$env:` anchor candidate drives a whole scan, not just resolution.

    `$env:CLAUDE_CONFIG_DIR` is the first candidate `claude-code.json` names
    and the one the research says relocates everything. Until this, it was
    proven only at `resolve_anchor_roots`; the `scan -> resolve_anchor_roots
    (environ=...)` wiring was not exercised end to end, so a scan could have
    read the default tree while the tests passed.
    """

    def setUp(self) -> None:
        super().setUp()
        self.relocated = self.tmp / "relocated"
        self.write(self.relocated / "CLAUDE.md", "# relocated memory\n")
        self.write(self.relocated / "skills" / "one" / "SKILL.md", "relocated\n")

    def env_adapter(self, **overrides: object) -> Path:
        return self.write_adapter(
            anchors={"$USER_CONFIG": ["$env:CLAUDE_CONFIG_DIR"], "$PROJECT": ["."]},
            **overrides,
        )

    def digest_of(self, path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def memory_item(self, entry: dict) -> dict:
        found = [
            item
            for item in entry["items"]
            if item["anchor"] == "$USER_CONFIG/CLAUDE.md"
        ]
        self.assertEqual(len(found), 1, entry["items"])
        return found[0]

    def test_the_scan_reads_the_tree_the_environment_variable_names(self) -> None:
        self.populate()  # a *different* CLAUDE.md in the default user_config
        entry, _, code = self.do_scan(
            adapter=self.env_adapter(),
            environ={"CLAUDE_CONFIG_DIR": str(self.relocated)},
        )
        item = self.memory_item(entry)
        self.assertEqual(item["state"], "present")
        self.assertEqual(item["digest"], self.digest_of(self.relocated / "CLAUDE.md"))
        self.assertNotEqual(
            item["digest"], self.digest_of(self.user_config / "CLAUDE.md")
        )
        self.assertEqual(code, 0)

    def test_a_glob_beneath_the_env_anchor_expands_in_that_tree(self) -> None:
        self.populate()
        entry, _, _ = self.do_scan(
            adapter=self.env_adapter(),
            environ={"CLAUDE_CONFIG_DIR": str(self.relocated)},
        )
        skills = [item for item in entry["items"] if item["kind"] == "skill"]
        self.assertEqual(
            [item["anchor"] for item in skills],
            ["$USER_CONFIG/skills/one/SKILL.md"],
        )

    def test_the_same_adapter_with_the_variable_unset_resolves_nothing(self) -> None:
        """The control: without the variable the anchor is unresolved."""
        entry, findings, code = self.do_scan(adapter=self.env_adapter(), environ={})
        self.assertTrue([f for f in findings if "unresolved" in f], findings)
        self.assertEqual(code, 1)
        self.assertEqual(
            self.memory_item(entry)["attributes"]["reason"], "unresolved_anchor"
        )

    def test_the_cli_passes_the_process_environment_through(self) -> None:
        """`scan_command` takes no `environ`; it must reach `os.environ`."""
        self.populate()
        adapter = self.env_adapter()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.relocated)}):
            code, stdout, stderr = self.run_cli(*self.cli_arguments(adapter))
        self.assertEqual(code, 0, stderr)
        item = self.memory_item(json.loads(stdout))
        self.assertEqual(item["digest"], self.digest_of(self.relocated / "CLAUDE.md"))


class ScanNeverTracebacksTests(ScanTestCase):
    """Probe data reaches `scan` from a user `local.json`; none of it may raise."""

    HOSTILE_PROBES = [
        {"kind": "skill", "scope": "user", "glob": "$USER_CONFIG//Windows/*.ini"},
        {"kind": "skill", "scope": "user", "glob": "$USER_CONFIG/C:/Windows/*.ini"},
    ]

    def test_a_glob_the_expander_refuses_does_not_escape_scan(self) -> None:
        self.populate()
        entry, _, code = self.do_scan(
            adapter=self.write_adapter(probes=self.HOSTILE_PROBES)
        )
        self.assertEqual(len(entry["items"]), 2)
        self.assertEqual(validate_baseline(entry, 0, source="scan"), [])
        self.assertEqual(code, 0)

    def test_the_cli_exits_zero_rather_than_tracebacking(self) -> None:
        self.populate()
        adapter = self.write_adapter(probes=self.HOSTILE_PROBES)
        code, stdout, stderr = self.run_cli(*self.cli_arguments(adapter))
        self.assertEqual(code, 0, stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(len(json.loads(stdout)["items"]), 2)


if __name__ == "__main__":
    unittest.main()
