"""Tests for `ledgerlib.lock`: turning a baseline into a pinned lockfile.

Two properties carry the feature and are asserted by name.

**Determinism is a requirement, not a quality.** A lockfile is meant to be
committed and read in a diff, so two runs over the same baseline must produce
identical bytes and the entry order must not depend on the order the baseline
happened to record things. `DeterminismTests` pins both, plus the absence of
anything machine-specific (no timestamp, no absolute path).

**`--check` never reads the environment.** Verifying against the disk as it is
now already has a command — `drift` — and one question with two answers is
worse than either. `CheckReadsNothingTests` proves it with a spy rather than
trusting the docstring.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "skills" / "agent-ingest-audit-optimize"
SCRIPT = BUNDLE / "assets" / "scripts" / "dashboard.py"

SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib import lock as lock_module  # noqa: E402
from ledgerlib import paths as paths_module  # noqa: E402
from ledgerlib.errors import LedgerError  # noqa: E402
from ledgerlib.lock import (  # noqa: E402
    LOCK_DIFFERENCES,
    LOCK_VERSION,
    build_lock,
    check_lock,
)

LOCKABLE_KINDS = frozenset(
    {"skill", "plugin", "mcp-server", "agent", "command", "hook"}
)


def item(kind: str, name: str, **overrides: object) -> dict:
    base: dict = {
        "kind": kind,
        "name": name,
        "anchor": f"$USER_CONFIG/{name}",
        "digest": "sha256:" + "a" * 64,
        "attributes": {"scope": "user"},
        "origin": "pre-existing",
        "state": "present",
        "portable": True,
    }
    base.update(overrides)
    return base


def ledger(items: list | None = None, **overrides: object) -> dict:
    document: dict = {
        "schema_version": "1.0",
        "ledger_id": "l-lock",
        "scope": "global",
        "language": "en",
        "client": "claude-code",
        "adapter_version": 2,
        "created": "2026-07-29",
        "updated": "2026-07-31",
        "id_authority": True,
        "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 1},
        "known_projects": [],
        "records": [],
        "baselines": [
            {
                "id": "BASE-2026-000",
                "captured_on": "2026-07-31",
                "client": "claude-code",
                "adapter_version": 2,
                "platform": "win32",
                "items": items if items is not None else [item("skill", "one")],
            }
        ],
        "backlog": [],
    }
    document.update(overrides)
    return document


class BuildLockTests(unittest.TestCase):
    def build(self, document: dict | None = None, **kwargs: object) -> dict:
        return build_lock(
            document if document is not None else ledger(),
            baseline_id=kwargs.pop("baseline_id", "BASE-2026-000"),
            lockable=kwargs.pop("lockable", LOCKABLE_KINDS),
        )

    def test_the_lock_carries_its_provenance(self) -> None:
        document = self.build()
        self.assertEqual(document["lock_version"], LOCK_VERSION)
        self.assertEqual(document["generated_from"], "BASE-2026-000")
        self.assertEqual(document["client"], "claude-code")
        self.assertEqual(document["adapter_version"], 2)
        self.assertEqual(document["platform"], "win32")

    def test_only_lockable_kinds_are_pinned(self) -> None:
        """Configuration that legitimately changes every day is left out. A
        lockfile that fails CI because somebody edited CLAUDE.md is one
        somebody switches off in the first week."""
        document = self.build(
            ledger(
                items=[
                    item("skill", "one"),
                    item("instruction-file", "CLAUDE.md"),
                    item("model-setting", "settings.json"),
                    item("mcp-server", "alpha"),
                ]
            )
        )
        self.assertEqual(
            sorted(entry["kind"] for entry in document["entries"]),
            ["mcp-server", "skill"],
        )

    def test_entries_are_ordered_independently_of_the_baseline(self) -> None:
        forward = self.build(
            ledger(items=[item("skill", "a"), item("skill", "b"), item("plugin", "c")])
        )
        backward = self.build(
            ledger(items=[item("plugin", "c"), item("skill", "b"), item("skill", "a")])
        )
        self.assertEqual(forward["entries"], backward["entries"])

    def test_an_unknown_baseline_is_a_tool_error(self) -> None:
        with self.assertRaises(LedgerError):
            self.build(baseline_id="BASE-2026-999")

    def test_a_malformed_item_is_skipped_never_a_crash(self) -> None:
        document = self.build(ledger(items=["nope", 7, item("skill", "one")]))
        self.assertEqual(len(document["entries"]), 1)

    def test_the_entry_records_scope_and_state_beside_the_digest(self) -> None:
        entry = self.build()["entries"][0]
        self.assertEqual(entry["scope"], "user")
        self.assertEqual(entry["state"], "present")
        self.assertTrue(entry["digest"].startswith("sha256:"))


class DeterminismTests(unittest.TestCase):
    def render(self, document: dict) -> str:
        return lock_module.render_lock(
            build_lock(document, baseline_id="BASE-2026-000", lockable=LOCKABLE_KINDS)
        )

    def test_two_renders_of_one_baseline_are_byte_identical(self) -> None:
        document = ledger(items=[item("skill", "a"), item("plugin", "b")])
        self.assertEqual(self.render(document), self.render(document))

    def test_input_order_does_not_change_the_bytes(self) -> None:
        first = self.render(ledger(items=[item("skill", "a"), item("plugin", "b")]))
        second = self.render(ledger(items=[item("plugin", "b"), item("skill", "a")]))
        self.assertEqual(first, second)

    def test_the_lock_carries_nothing_machine_specific(self) -> None:
        """No timestamp and no absolute path: either would make two identical
        environments produce different files, which is the whole point lost."""
        text = self.render(ledger())
        self.assertNotIn("captured_on", text)
        self.assertNotIn("generated_at", text)
        self.assertNotIn("C:\\", text)
        self.assertNotIn("/home/", text)
        self.assertNotIn("/Users/", text)


class CheckLockTests(unittest.TestCase):
    def lock_of(self, document: dict) -> dict:
        return build_lock(
            document, baseline_id="BASE-2026-000", lockable=LOCKABLE_KINDS
        )

    def check(self, locked: dict, document: dict):
        return check_lock(locked, document, lockable=LOCKABLE_KINDS)

    def test_an_unchanged_baseline_reports_nothing(self) -> None:
        document = ledger()
        rows, code = self.check(self.lock_of(document), document)
        self.assertEqual(rows, [])
        self.assertEqual(code, 0)

    def test_an_added_artifact_is_named_added(self) -> None:
        locked = self.lock_of(ledger())
        rows, code = self.check(
            locked, ledger(items=[item("skill", "one"), item("skill", "two")])
        )
        self.assertEqual([row["difference"] for row in rows], ["added"])
        self.assertIn("two", rows[0]["anchor"])
        self.assertEqual(code, 1)

    def test_a_removed_artifact_is_named_removed(self) -> None:
        locked = self.lock_of(
            ledger(items=[item("skill", "one"), item("skill", "two")])
        )
        rows, code = self.check(locked, ledger())
        self.assertEqual([row["difference"] for row in rows], ["removed"])
        self.assertEqual(code, 1)

    def test_a_different_digest_is_named_changed(self) -> None:
        locked = self.lock_of(ledger())
        rows, code = self.check(
            locked, ledger(items=[item("skill", "one", digest="sha256:" + "b" * 64)])
        )
        self.assertEqual([row["difference"] for row in rows], ["changed"])
        self.assertEqual(code, 1)

    def test_a_different_state_is_named_state_changed(self) -> None:
        locked = self.lock_of(ledger())
        rows, code = self.check(
            locked,
            ledger(items=[item("skill", "one", state="not_present", digest=None)]),
        )
        self.assertEqual([row["difference"] for row in rows], ["state_changed"])
        self.assertEqual(code, 1)

    def test_every_difference_is_in_the_closed_vocabulary(self) -> None:
        locked = self.lock_of(ledger(items=[item("skill", "one")]))
        rows, _code = self.check(
            locked,
            ledger(items=[item("skill", "two"), item("plugin", "three")]),
        )
        for row in rows:
            with self.subTest(row=row):
                self.assertIn(row["difference"], LOCK_DIFFERENCES)

    def test_a_different_client_is_an_explicit_finding(self) -> None:
        """Comparing one client's lock against another's baseline silently
        would report every entry as added and removed, burying the real
        problem in noise."""
        locked = self.lock_of(ledger())
        other = ledger()
        other["baselines"][0]["client"] = "codex"
        with self.assertRaises(LedgerError) as caught:
            self.check(locked, other)
        self.assertIn("client", str(caught.exception))

    def test_a_different_platform_is_an_explicit_finding(self) -> None:
        locked = self.lock_of(ledger())
        other = ledger()
        other["baselines"][0]["platform"] = "linux"
        with self.assertRaises(LedgerError) as caught:
            self.check(locked, other)
        self.assertIn("platform", str(caught.exception))

    def test_an_unknown_lock_version_is_a_tool_error(self) -> None:
        locked = dict(self.lock_of(ledger()), lock_version=99)
        with self.assertRaises(LedgerError):
            self.check(locked, ledger())


class CheckReadsNothingTests(unittest.TestCase):
    """`--check` compares two documents. It never touches the environment."""

    def test_check_resolves_no_anchor_and_opens_no_file(self) -> None:
        document = ledger()
        locked = build_lock(
            document, baseline_id="BASE-2026-000", lockable=LOCKABLE_KINDS
        )
        with mock.patch.object(
            paths_module, "resolve_anchored", side_effect=AssertionError("resolved!")
        ), mock.patch.object(
            paths_module, "file_digest", side_effect=AssertionError("hashed!")
        ):
            rows, code = check_lock(locked, document, lockable=LOCKABLE_KINDS)
        self.assertEqual((rows, code), ([], 0))


class LockCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ledger_path = self.tmp / "ledger.json"
        self.ledger_path.write_text(
            json.dumps(ledger(), indent=2), encoding="utf-8"
        )

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def write_lock(self) -> Path:
        out = self.tmp / "agent.lock"
        code, _o, _e = self.run_cli(
            "lock", str(self.ledger_path), "--from", "BASE-2026-000", "--out", str(out)
        )
        self.assertEqual(code, 0)
        return out


class LockCliTests(LockCliTestCase):
    def test_from_writes_a_lockfile(self) -> None:
        out = self.write_lock()
        document = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(document["generated_from"], "BASE-2026-000")

    def test_writing_twice_produces_identical_bytes(self) -> None:
        first = self.write_lock().read_bytes()
        second = self.write_lock().read_bytes()
        self.assertEqual(first, second)

    def test_check_against_an_unchanged_ledger_exits_zero(self) -> None:
        out = self.write_lock()
        code, _o, _e = self.run_cli(
            "lock", str(self.ledger_path), "--check", str(out)
        )
        self.assertEqual(code, 0)

    def test_check_against_a_changed_ledger_exits_one_and_names_it(self) -> None:
        out = self.write_lock()
        self.ledger_path.write_text(
            json.dumps(
                ledger(items=[item("skill", "one", digest="sha256:" + "b" * 64)]),
                indent=2,
            ),
            encoding="utf-8",
        )
        code, _o, err = self.run_cli(
            "lock", str(self.ledger_path), "--check", str(out)
        )
        self.assertEqual(code, 1)
        self.assertIn("changed", err)

    def test_from_and_check_together_is_a_usage_error(self) -> None:
        code, _o, _e = self.run_cli(
            "lock", str(self.ledger_path), "--from", "BASE-2026-000",
            "--check", str(self.tmp / "x.lock"),
        )
        self.assertEqual(code, 2)

    def test_neither_from_nor_check_is_a_usage_error(self) -> None:
        code, _o, _e = self.run_cli("lock", str(self.ledger_path))
        self.assertEqual(code, 2)

    def test_an_unreadable_lockfile_exits_two(self) -> None:
        code, _o, err = self.run_cli(
            "lock", str(self.ledger_path), "--check", str(self.tmp / "absent.lock")
        )
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_out_refuses_to_clobber_a_file_that_is_not_a_lock(self) -> None:
        stranger = self.tmp / "agent.lock"
        stranger.write_text("mine, not yours\n", encoding="utf-8")
        code, _o, err = self.run_cli(
            "lock", str(self.ledger_path), "--from", "BASE-2026-000",
            "--out", str(stranger),
        )
        self.assertEqual(code, 2)
        self.assertEqual(stranger.read_text(encoding="utf-8"), "mine, not yours\n")
        self.assertIn("--force", err)

    def test_force_overwrites_the_stranger(self) -> None:
        stranger = self.tmp / "agent.lock"
        stranger.write_text("mine, not yours\n", encoding="utf-8")
        code, _o, _e = self.run_cli(
            "lock", str(self.ledger_path), "--from", "BASE-2026-000",
            "--out", str(stranger), "--force",
        )
        self.assertEqual(code, 0)
        self.assertIn("lock_version", stranger.read_text(encoding="utf-8"))


class ShippedAdapterLockableTests(unittest.TestCase):
    """The lockable set is declared data, and is exactly the spec's list."""

    def adapter(self, name: str) -> dict:
        return json.loads(
            (BUNDLE / "assets" / "adapters" / name).read_text(encoding="utf-8")
        )

    def test_claude_code_marks_exactly_the_installable_kinds(self) -> None:
        kinds = {
            probe["kind"]
            for probe in self.adapter("claude-code.json")["probes"]
            if probe.get("lockable")
        }
        self.assertEqual(kinds, {"skill", "plugin", "mcp-server", "agent", "command", "hook"})

    def test_configuration_kinds_are_never_lockable(self) -> None:
        for name in ("claude-code.json", "codex.json"):
            with self.subTest(adapter=name):
                for probe in self.adapter(name)["probes"]:
                    if probe.get("lockable"):
                        self.assertNotIn(
                            probe["kind"],
                            {
                                "instruction-file",
                                "model-setting",
                                "permission-rule",
                                "env-var-name",
                            },
                        )


if __name__ == "__main__":
    unittest.main()
