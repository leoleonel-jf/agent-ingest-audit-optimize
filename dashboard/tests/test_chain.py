"""Tests for `ledgerlib.chain`: canonicalization, the chain, and sealing.

The suite loads `dashboard.py` by file path exactly the way `test_drift.py`
does, for the same side effect: `dashboard.py` inserts its own directory at the
front of `sys.path` before importing `ledgerlib`.

Two properties carry the whole feature and are asserted by name rather than
implied. First, canonicalization is *one* function: `serialize_payload` and
`record_digest` must reach the same bytes for the same object, or a payload
and a digest could describe the same record differently. Second, the chain is
tamper-EVIDENT and not tamper-proof: editing, deleting and reordering are all
detected, and recomputing the whole chain is NOT -- which is why
`--expect-head` exists and why a test pins that limit rather than leaving it as
a docstring claim.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
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

from ledgerlib.build import serialize_payload  # noqa: E402
from ledgerlib.chain import (  # noqa: E402
    CHAIN_REASONS,
    canonical_bytes,
    canonical_text,
    chain_head,
    record_digest,
    seal_ledger,
    verify_chain,
)


def record(identifier: str, **overrides: object) -> dict:
    base: dict = {
        "id": identifier,
        "type": "MATERIAL",
        "title": "a material",
        "status": "ANALYZED",
        "classification": "MONITOR",
        "scope": "project",
        "created": "2026-07-30",
        "updated": "2026-07-30",
        "file": f"records/{identifier}.md",
        "links": {"materials": [], "runs": [], "adrs": []},
        "evidence": [],
    }
    base.update(overrides)
    return base


class CanonicalizationTests(unittest.TestCase):
    def test_key_order_in_the_input_does_not_change_the_bytes(self) -> None:
        first = {"b": 1, "a": {"z": 1, "y": 2}}
        second = {"a": {"y": 2, "z": 1}, "b": 1}
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_two_calls_on_one_object_agree(self) -> None:
        value = {"a": [1, 2, {"c": None}], "b": "x"}
        self.assertEqual(canonical_bytes(value), canonical_bytes(value))

    def test_output_is_compact_and_sorted(self) -> None:
        self.assertEqual(canonical_text({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_non_ascii_survives_without_escaping(self) -> None:
        self.assertEqual(canonical_text({"t": "Execução"}), '{"t":"Execução"}')

    def test_a_lone_surrogate_does_not_raise(self) -> None:
        """The trap `serialize_payload` already closed, closed here too: a
        ledger string can hold a lone surrogate, and hashing must not be the
        one operation that dies on it."""
        value = json.loads('{"t": "\\ud800"}')
        canonical_bytes(value).decode("utf-8")

    def test_serialize_payload_is_built_on_this_canonicalization(self) -> None:
        """One canonicalization in the repository, asserted rather than
        promised: `serialize_payload` is this text plus its HTML-embedding
        escapes, so a payload and a digest can never disagree about the same
        object. The `<` replacement is the only difference, and it belongs to
        embedding, not to hashing."""
        value = {"title": "a <b> c", "n": 1}
        self.assertEqual(
            serialize_payload(value),
            canonical_text(value).replace("<", "\\u003c"),
        )


class RecordDigestTests(unittest.TestCase):
    def test_the_digest_is_sha256_of_the_canonical_bytes(self) -> None:
        entry = record("MAT-2026-000")
        expected = "sha256:" + hashlib.sha256(canonical_bytes(entry)).hexdigest()
        self.assertEqual(record_digest(entry), expected)

    def test_chain_digest_is_excluded_from_its_own_hash(self) -> None:
        entry = record("MAT-2026-000", chain={"index": 0, "previous": None})
        before = record_digest(entry)
        entry["chain"]["digest"] = before
        self.assertEqual(record_digest(entry), before)

    def test_index_and_previous_are_inside_the_hash(self) -> None:
        """What binds a record to its POSITION. Without them a record could be
        lifted from one slot to another with its digest still matching."""
        first = record("MAT-2026-000", chain={"index": 0, "previous": None})
        moved = record("MAT-2026-000", chain={"index": 1, "previous": None})
        repointed = record(
            "MAT-2026-000", chain={"index": 0, "previous": "sha256:" + "0" * 64}
        )
        self.assertNotEqual(record_digest(first), record_digest(moved))
        self.assertNotEqual(record_digest(first), record_digest(repointed))

    def test_editing_any_field_changes_the_digest(self) -> None:
        entry = record("MAT-2026-000")
        for field, value in (
            ("title", "a different material"),
            ("status", "DECIDED"),
            ("created", "2026-07-31"),
        ):
            with self.subTest(field=field):
                edited = dict(entry, **{field: value})
                self.assertNotEqual(record_digest(entry), record_digest(edited))


class ChainTestCase(unittest.TestCase):
    def sealed(self, count: int = 3) -> dict:
        ledger = {
            "schema_version": "1.0",
            "records": [record(f"MAT-2026-{n:03d}") for n in range(count)],
        }
        seal_ledger(ledger)
        return ledger


class VerifyChainTests(ChainTestCase):
    def test_a_sealed_chain_verifies_clean(self) -> None:
        rows, verdict = verify_chain(self.sealed())
        self.assertEqual(verdict, "INTACT")
        self.assertEqual([row["reason"] for row in rows], [None, None, None])

    def test_editing_one_record_breaks_exactly_that_record(self) -> None:
        ledger = self.sealed()
        ledger["records"][1]["title"] = "tampered"
        rows, verdict = verify_chain(ledger)
        self.assertEqual(verdict, "BROKEN")
        self.assertEqual(rows[1]["reason"], "digest_mismatch")
        self.assertIsNone(rows[0]["reason"])

    def test_deleting_a_record_from_the_middle_breaks_the_next_one(self) -> None:
        """Reported as `index_gap`, which is the sharper diagnosis: the
        surviving record claims index 2 where 1 was expected, and that names
        the missing slot. `previous_mismatch` is also true of this ledger, but
        it only says the link is wrong, not that something was removed."""
        ledger = self.sealed()
        del ledger["records"][1]
        rows, verdict = verify_chain(ledger)
        self.assertEqual(verdict, "BROKEN")
        self.assertEqual(rows[1]["reason"], "index_gap")

    def test_a_repointed_previous_alone_is_named_previous_mismatch(self) -> None:
        """Indices intact, link rewritten: the case that isolates the second
        check from the first."""
        ledger = self.sealed()
        entry = ledger["records"][2]
        entry["chain"]["previous"] = "sha256:" + "0" * 64
        entry["chain"]["digest"] = record_digest(entry)
        rows, verdict = verify_chain(ledger)
        self.assertEqual(verdict, "BROKEN")
        self.assertEqual(rows[2]["reason"], "previous_mismatch")

    def test_reordering_two_records_breaks_the_chain(self) -> None:
        ledger = self.sealed()
        records = ledger["records"]
        records[0], records[1] = records[1], records[0]
        _rows, verdict = verify_chain(ledger)
        self.assertEqual(verdict, "BROKEN")

    def test_an_index_gap_is_named_as_one(self) -> None:
        ledger = self.sealed()
        ledger["records"][2]["chain"]["index"] = 7
        ledger["records"][2]["chain"]["digest"] = record_digest(ledger["records"][2])
        rows, verdict = verify_chain(ledger)
        self.assertEqual(verdict, "BROKEN")
        self.assertEqual(rows[2]["reason"], "index_gap")

    def test_every_reason_belongs_to_the_closed_vocabulary(self) -> None:
        ledger = self.sealed()
        ledger["records"][1]["title"] = "tampered"
        del ledger["records"][2]["chain"]
        rows, _verdict = verify_chain(ledger)
        for row in rows:
            with self.subTest(row=row):
                self.assertIn(row["reason"], CHAIN_REASONS | {None})

    def test_recomputing_the_whole_chain_is_NOT_detected(self) -> None:
        """The limit the threat table states, pinned as a test.

        Someone with write access can edit a record and re-seal from scratch,
        and nothing inside the file can tell. Claiming otherwise would be the
        one lie this feature must not tell -- which is why `chain_head` exists
        and why the head is meant to be stored somewhere else.
        """
        ledger = self.sealed()
        original_head = chain_head(ledger)
        ledger["records"][1]["title"] = "tampered"
        for entry in ledger["records"]:
            entry.pop("chain", None)
        seal_ledger(ledger)
        _rows, verdict = verify_chain(ledger)
        self.assertEqual(verdict, "INTACT")
        # ...and this is what catches it instead.
        self.assertNotEqual(chain_head(ledger), original_head)


class UnchainedCompatibilityTests(ChainTestCase):
    def test_a_record_with_no_chain_is_unchained_not_invalid(self) -> None:
        ledger = {"schema_version": "1.0", "records": [record("MAT-2026-000")]}
        rows, verdict = verify_chain(ledger)
        self.assertEqual(rows[0]["reason"], "unchained")
        self.assertEqual(verdict, "UNCHAINED")

    def test_a_partially_sealed_ledger_verifies_from_the_first_chained_record(
        self,
    ) -> None:
        """The normal state right after migration: old records carry nothing,
        new ones carry a chain, and the chain over the new ones is sound."""
        ledger = {
            "schema_version": "1.0",
            "records": [record(f"MAT-2026-{n:03d}") for n in range(4)],
        }
        seal_ledger(ledger, start=2)
        rows, verdict = verify_chain(ledger)
        self.assertEqual([row["reason"] for row in rows[:2]], ["unchained"] * 2)
        self.assertEqual([row["reason"] for row in rows[2:]], [None, None])
        self.assertEqual(verdict, "PARTIAL")
        self.assertIsNone(ledger["records"][2]["chain"]["previous"])
        self.assertEqual(ledger["records"][2]["chain"]["index"], 0)

    def test_an_empty_records_array_is_unchained_never_a_crash(self) -> None:
        rows, verdict = verify_chain({"schema_version": "1.0", "records": []})
        self.assertEqual(rows, [])
        self.assertEqual(verdict, "UNCHAINED")

    def test_a_malformed_chain_object_is_a_finding_never_a_crash(self) -> None:
        ledger = {
            "schema_version": "1.0",
            "records": [record("MAT-2026-000", chain="nope")],
        }
        rows, verdict = verify_chain(ledger)
        self.assertEqual(rows[0]["reason"], "unchained")
        self.assertEqual(verdict, "UNCHAINED")

    def test_records_that_is_not_an_array_does_not_crash(self) -> None:
        rows, verdict = verify_chain({"records": "nope"})
        self.assertEqual(rows, [])
        self.assertEqual(verdict, "UNCHAINED")


class SealTests(ChainTestCase):
    def test_sealing_is_idempotent(self) -> None:
        ledger = self.sealed()
        before = copy.deepcopy(ledger)
        seal_ledger(ledger)
        self.assertEqual(ledger, before)

    def test_sealing_leaves_an_intact_chain(self) -> None:
        _rows, verdict = verify_chain(self.sealed(5))
        self.assertEqual(verdict, "INTACT")

    def test_the_head_is_the_last_records_digest(self) -> None:
        ledger = self.sealed()
        self.assertEqual(chain_head(ledger), ledger["records"][-1]["chain"]["digest"])

    def test_the_head_of_an_unchained_ledger_is_none(self) -> None:
        self.assertIsNone(chain_head({"records": [record("MAT-2026-000")]}))


class ChainCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def valid_ledger(self, records: list | None = None) -> dict:
        return {
            "schema_version": "1.0",
            "ledger_id": "l-chain",
            "scope": "global",
            "language": "en",
            "client": "claude-code",
            "adapter_version": 1,
            "created": "2026-07-29",
            "updated": "2026-07-30",
            "id_authority": True,
            "sequences": {"MAT": 1, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0},
            "known_projects": [],
            "records": records if records is not None else [record("MAT-2026-000")],
            "baselines": [],
            "backlog": [],
        }

    def write(self, document: dict, *, newline: str = "\n") -> Path:
        path = self.tmp / "ledger.json"
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline=newline,
        )
        return path

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


class ChainCommandTests(ChainCliTestCase):
    def test_head_prints_only_the_digest(self) -> None:
        """Only the digest, so the value pipes into a commit message or a tag
        without a second processing step."""
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        code, out, _err = self.run_cli("chain", str(path), "--head")
        self.assertEqual(code, 0)
        self.assertRegex(out.strip(), r"^sha256:[0-9a-f]{64}$")

    def test_head_of_an_unchained_ledger_explains_itself_on_stderr(self) -> None:
        path = self.write(self.valid_ledger())
        code, out, err = self.run_cli("chain", str(path), "--head")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")
        self.assertIn("unchained", err.lower())

    def test_seal_writes_the_chain_and_prints_the_head(self) -> None:
        path = self.write(self.valid_ledger())
        code, out, _err = self.run_cli("chain", str(path), "--seal")
        self.assertEqual(code, 0)
        sealed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(sealed["records"][0]["chain"]["index"], 0)
        self.assertIn(sealed["records"][0]["chain"]["digest"], out)

    def test_seal_refuses_a_ledger_that_does_not_validate(self) -> None:
        broken = self.valid_ledger()
        del broken["sequences"]
        path = self.write(broken)
        before = path.read_bytes()
        code, _out, err = self.run_cli("chain", str(path), "--seal")
        self.assertEqual(code, 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(err.strip())

    def test_seal_refuses_to_seal_over_a_broken_chain(self) -> None:
        """Sealing over tampering would erase the evidence -- which is the one
        thing this command must never do."""
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["records"][0]["title"] = "tampered"
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        before = path.read_bytes()
        code, _out, err = self.run_cli("chain", str(path), "--seal")
        self.assertEqual(code, 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("digest_mismatch", err)

    def test_seal_is_byte_idempotent(self) -> None:
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        first = path.read_bytes()
        self.run_cli("chain", str(path), "--seal")
        self.assertEqual(path.read_bytes(), first)

    def test_seal_preserves_crlf_line_endings(self) -> None:
        """The live ledger is CRLF. A seal that normalized line endings would
        rewrite every line of a governance file to change three."""
        path = self.write(self.valid_ledger(), newline="\r\n")
        self.run_cli("chain", str(path), "--seal")
        raw = path.read_bytes()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertGreater(raw.count(b"\r\n"), 5)

    def test_seal_preserves_lf_line_endings(self) -> None:
        path = self.write(self.valid_ledger(), newline="\n")
        self.run_cli("chain", str(path), "--seal")
        self.assertNotIn(b"\r\n", path.read_bytes())

    def test_seal_writes_exactly_one_file(self) -> None:
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        self.assertEqual(
            sorted(child.name for child in self.tmp.iterdir()), ["ledger.json"]
        )


class VerifyChainCliTests(ChainCliTestCase):
    def test_chain_flag_reports_a_broken_chain_and_moves_the_exit_code(self) -> None:
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["records"][0]["title"] = "tampered"
        self.write(document)
        code, _out, err = self.run_cli("verify", str(path), "--chain")
        self.assertEqual(code, 1)
        self.assertIn("digest_mismatch", err)

    def test_without_the_flag_an_unchained_ledger_is_silent_and_clean(self) -> None:
        """Every ledger written before this feature must keep verifying clean,
        or the tool would invalidate the records it exists to preserve."""
        path = self.write(self.valid_ledger())
        code, _out, err = self.run_cli("verify", str(path))
        self.assertEqual(code, 0)
        self.assertNotIn("unchained", err.lower())

    def test_with_the_flag_an_unchained_ledger_is_a_finding(self) -> None:
        path = self.write(self.valid_ledger())
        code, _out, err = self.run_cli("verify", str(path), "--chain")
        self.assertEqual(code, 1)
        self.assertIn("unchained", err.lower())

    def test_expect_head_detects_a_wholly_recomputed_chain(self) -> None:
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        _code, out, _err = self.run_cli("chain", str(path), "--head")
        recorded_head = out.strip()

        document = json.loads(path.read_text(encoding="utf-8"))
        document["records"][0]["title"] = "tampered"
        for entry in document["records"]:
            entry.pop("chain", None)
        self.write(document)
        self.run_cli("chain", str(path), "--seal")

        code, _out, err = self.run_cli(
            "verify", str(path), "--chain", "--expect-head", recorded_head
        )
        self.assertEqual(code, 1)
        self.assertIn("head", err.lower())

    def test_expect_head_passes_on_an_untouched_ledger(self) -> None:
        path = self.write(self.valid_ledger())
        self.run_cli("chain", str(path), "--seal")
        _code, out, _err = self.run_cli("chain", str(path), "--head")
        code, _out, _err = self.run_cli(
            "verify", str(path), "--chain", "--expect-head", out.strip()
        )
        self.assertEqual(code, 0)

    def test_expect_head_without_chain_is_a_usage_error(self) -> None:
        path = self.write(self.valid_ledger())
        code, _out, _err = self.run_cli(
            "verify", str(path), "--expect-head", "sha256:" + "0" * 64
        )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
