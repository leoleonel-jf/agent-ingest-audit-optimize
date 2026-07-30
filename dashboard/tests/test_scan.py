"""Tests for `ledgerlib.scan`: redaction of sensitive values.

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

import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "scripts"
    / "dashboard.py"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib.constants import (  # noqa: E402
    BASELINE_ITEM_STATES,
    REQUIRED_BASELINE_ITEM_FIELDS,
)
from ledgerlib.errors import PATH_SAFETY_REASONS  # noqa: E402
from ledgerlib.scan import redact, run_probe  # noqa: E402
from ledgerlib.validate import validate_baseline  # noqa: E402


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

    def test_parse_and_pointer_are_ignored_and_yield_the_whole_file_item(self) -> None:
        target = self.write(
            self.user_config / "settings.json", '{"mcpServers": {"a": {}}}\n'
        )
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
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["digest"], self.digest_of(target))


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


if __name__ == "__main__":
    unittest.main()
