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
import re
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

from ledgerlib.scan import redact  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
