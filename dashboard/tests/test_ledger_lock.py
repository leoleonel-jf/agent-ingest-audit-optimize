"""Two writers on one ledger, in two real processes.

`update ledger` reads the ledger, scans, and replaces the file; `chain --seal`
reads, seals, and replaces it. The replace is atomic, so a reader never sees
half a file, but without a lock the last writer silently discards whatever
the first one wrote between its read and its replace. These tests hold
writer A inside that window, start writer B, and check what survives.

The writers are separate interpreters on purpose. A lock that only excludes
threads of one process, or one that a second file descriptor in the same
process can take again, would pass a thread-based version of these tests and
still lose data between two sessions. Each child loads `dashboard.py` by path,
the same way the rest of the suite does, and only writer A is instrumented:
its scan announces itself through a file and waits for a release file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "plugin-reviewer"
    / "assets"
    / "scripts"
    / "dashboard.py"
)

CHILD = textwrap.dedent(
    """
    import importlib.util, json, sys, time
    from pathlib import Path

    config = json.loads(sys.argv[1])
    spec = importlib.util.spec_from_file_location("dashboard", config["script"])
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)

    from ledgerlib import update
    from ledgerlib.chain import chain_command

    if config.get("timeout") is not None:
        from ledgerlib import locking
        locking.LOCK_TIMEOUT_SECONDS = config["timeout"]

    if config.get("hold"):
        original = update.scan_detail

        def held(**kwargs):
            Path(config["inside"]).write_text("inside", encoding="utf-8")
            while not Path(config["release"]).exists():
                time.sleep(0.02)
            if config.get("crash"):
                raise RuntimeError("writer A failed inside the window")
            return original(**kwargs)

        update.scan_detail = held

    if config["command"] == "update":
        code = update.update_command(
            Path(config["ledger"]),
            "ledger",
            identifier=config["id"],
            adapter=Path(config["adapter"]),
            today="2026-08-01",
        )
    else:
        code = chain_command(ledger=Path(config["ledger"]), head=False, seal=True)
    sys.exit(code)
    """
)


class LedgerLockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user_config = self.tmp / "user_config"
        self.user_config.mkdir()
        (self.user_config / "CLAUDE.md").write_text("# instructions\n", encoding="utf-8")
        self.adapter = self.tmp / "adapter.json"
        self.adapter.write_text(
            json.dumps(
                {
                    "adapter_version": 1,
                    "client": "testclient",
                    "expires_on": "2099-01-01",
                    "anchors": {"$USER_CONFIG": [str(self.user_config)]},
                    "probes": [
                        {
                            "kind": "instruction-file",
                            "scope": "user",
                            "path": "$USER_CONFIG/CLAUDE.md",
                        }
                    ],
                    "sensitive_key_patterns": [],
                }
            ),
            encoding="utf-8",
        )
        self.child = self.tmp / "child.py"
        self.child.write_text(CHILD, encoding="utf-8")
        self.inside = self.tmp / "a-inside"
        self.release = self.tmp / "a-release"
        self.processes: list[subprocess.Popen] = []
        self.addCleanup(self._reap)

    def _reap(self) -> None:
        self.release.write_text("go", encoding="utf-8")
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def ledger(self, name: str = "ledger.json", *, material: bool = False) -> Path:
        document = {
            "schema_version": "1.0",
            "ledger_id": "l-lock",
            "scope": "global",
            "language": "en",
            "client": "testclient",
            "adapter_version": 1,
            "created": "2026-07-29",
            "updated": "2026-07-30",
            "id_authority": True,
            "sequences": {"MAT": 1 if material else 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0},
            "known_projects": [],
            "records": [],
            "baselines": [],
            "backlog": [],
        }
        if material:
            document["records"].append(
                {
                    "id": "MAT-2026-000",
                    "type": "MATERIAL",
                    "title": "a material",
                    "status": "ANALYZED",
                    "classification": "MONITOR",
                    "scope": "project",
                    "created": "2026-07-30",
                    "updated": "2026-07-30",
                    "file": "records/MAT-2026-000.md",
                    "links": {"materials": [], "runs": [], "adrs": []},
                    "evidence": [],
                }
            )
        path = self.tmp / name
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return path

    def start(self, ledger: Path, *, command: str = "update", identifier: str | None = None,
              hold: bool = False, crash: bool = False, timeout: float | None = None,
              ) -> subprocess.Popen:
        config = {
            "script": str(SCRIPT),
            "ledger": str(ledger),
            "adapter": str(self.adapter),
            "command": command,
            "id": identifier,
            "hold": hold,
            "crash": crash,
            "timeout": timeout,
            "inside": str(self.inside),
            "release": str(self.release),
        }
        process = subprocess.Popen(
            [sys.executable, "-I", str(self.child), json.dumps(config)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.processes.append(process)
        return process

    def wait_inside(self, process: subprocess.Popen) -> None:
        deadline = time.monotonic() + 30
        while not self.inside.exists():
            if process.poll() is not None:
                _, err = process.communicate()
                self.fail(f"writer A exited before its scan: {err}")
            if time.monotonic() > deadline:
                self.fail("writer A never reached its scan")
            time.sleep(0.02)

    def finish(self, process: subprocess.Popen) -> tuple[int, str]:
        _, err = process.communicate(timeout=60)
        return process.returncode, err

    def baseline_ids(self, ledger: Path) -> list[str]:
        document = json.loads(ledger.read_text(encoding="utf-8"))
        return [entry["id"] for entry in document["baselines"]]

    def test_concurrent_updates_preserve_both_baselines(self) -> None:
        ledger = self.ledger()
        writer_a = self.start(ledger, identifier="BASE-2026-000", hold=True)
        self.wait_inside(writer_a)
        writer_b = self.start(ledger, identifier="BASE-2026-001")
        time.sleep(1.0)
        self.assertIsNone(
            writer_b.poll(), "writer B finished while writer A was inside its window"
        )
        self.release.write_text("go", encoding="utf-8")
        code_a, err_a = self.finish(writer_a)
        code_b, err_b = self.finish(writer_b)
        self.assertEqual((code_a, code_b), (0, 0), err_a + err_b)
        self.assertEqual(sorted(self.baseline_ids(ledger)), ["BASE-2026-000", "BASE-2026-001"])
        document = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertEqual(document["sequences"]["BASE"], 2)

    def test_two_minted_updates_take_two_numbers(self) -> None:
        ledger = self.ledger()
        writer_a = self.start(ledger, hold=True)
        self.wait_inside(writer_a)
        writer_b = self.start(ledger)
        time.sleep(0.5)
        self.release.write_text("go", encoding="utf-8")
        self.assertEqual(self.finish(writer_a)[0], 0)
        self.assertEqual(self.finish(writer_b)[0], 0)
        self.assertEqual(sorted(self.baseline_ids(ledger)), ["BASE-2026-000", "BASE-2026-001"])

    def test_a_seal_during_an_update_is_not_discarded(self) -> None:
        ledger = self.ledger(material=True)
        writer_a = self.start(ledger, identifier="BASE-2026-000", hold=True)
        self.wait_inside(writer_a)
        sealer = self.start(ledger, command="seal")
        time.sleep(1.0)
        self.assertIsNone(sealer.poll(), "the seal finished inside writer A's window")
        self.release.write_text("go", encoding="utf-8")
        self.assertEqual(self.finish(writer_a)[0], 0)
        code, err = self.finish(sealer)
        self.assertEqual(code, 0, err)
        document = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertEqual([entry["id"] for entry in document["baselines"]], ["BASE-2026-000"])
        self.assertIn("chain", document["records"][0])

    def test_independent_ledgers_do_not_wait_for_each_other(self) -> None:
        first = self.ledger("first.json")
        second = self.ledger("second.json")
        writer_a = self.start(first, identifier="BASE-2026-000", hold=True)
        self.wait_inside(writer_a)
        writer_b = self.start(second, identifier="BASE-2026-000")
        code_b, err_b = self.finish(writer_b)
        self.assertEqual(code_b, 0, err_b)
        self.assertIsNone(writer_a.poll())
        self.assertEqual(self.baseline_ids(second), ["BASE-2026-000"])

    def test_a_writer_that_fails_inside_the_window_releases_the_lock(self) -> None:
        ledger = self.ledger()
        before = ledger.read_bytes()
        writer_a = self.start(ledger, identifier="BASE-2026-000", hold=True, crash=True)
        self.wait_inside(writer_a)
        self.release.write_text("go", encoding="utf-8")
        self.assertNotEqual(self.finish(writer_a)[0], 0)
        self.assertEqual(ledger.read_bytes(), before)
        writer_b = self.start(ledger, identifier="BASE-2026-001", timeout=5)
        code_b, err_b = self.finish(writer_b)
        self.assertEqual(code_b, 0, err_b)
        self.assertEqual(self.baseline_ids(ledger), ["BASE-2026-001"])

    def test_a_killed_writer_releases_the_lock(self) -> None:
        ledger = self.ledger()
        writer_a = self.start(ledger, identifier="BASE-2026-000", hold=True)
        self.wait_inside(writer_a)
        writer_a.kill()
        writer_a.communicate()
        writer_b = self.start(ledger, identifier="BASE-2026-001", timeout=5)
        code_b, err_b = self.finish(writer_b)
        self.assertEqual(code_b, 0, err_b)
        self.assertEqual(self.baseline_ids(ledger), ["BASE-2026-001"])

    def test_a_writer_that_times_out_writes_nothing_and_can_retry(self) -> None:
        ledger = self.ledger()
        writer_a = self.start(ledger, identifier="BASE-2026-000", hold=True)
        self.wait_inside(writer_a)
        writer_b = self.start(ledger, identifier="BASE-2026-001", timeout=0.3)
        code_b, err_b = self.finish(writer_b)
        self.assertEqual(code_b, 2)
        self.assertIn("lock", err_b.lower())
        self.assertEqual(self.baseline_ids(ledger), [])
        self.release.write_text("go", encoding="utf-8")
        self.assertEqual(self.finish(writer_a)[0], 0)
        retry = self.start(ledger, identifier="BASE-2026-001", timeout=5)
        self.assertEqual(self.finish(retry)[0], 0)
        self.assertEqual(sorted(self.baseline_ids(ledger)), ["BASE-2026-000", "BASE-2026-001"])


if __name__ == "__main__":
    unittest.main()
