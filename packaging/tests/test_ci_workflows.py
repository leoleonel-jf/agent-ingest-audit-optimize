from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def run_lines(path: Path) -> list[str]:
    """The command of every single-line `run:` step, in order.

    Read as text on purpose: the suites are standard library only, and a YAML
    parser would be the first dependency. Comments are dropped first, so a
    command that survives only in a comment does not count as a step.
    """
    commands: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*(?:- )?run:\s*(\S.*)", line.split(" #", 1)[0].rstrip())
        if match:
            commands.append(match.group(1))
    return commands


class TestsWorkflow(unittest.TestCase):
    """`tests.yml` is the gate; these pin what it must keep gating.

    0.6.0 went straight to `main` and five pull requests before it merged with
    no changelog entry, because nothing ran on a push. A workflow can lose a
    step as quietly as that, and a gate that stopped running a suite still
    shows green.
    """

    def setUp(self) -> None:
        self.path = WORKFLOWS / "tests.yml"
        self.text = self.path.read_text(encoding="utf-8")
        self.commands = run_lines(self.path)

    def test_every_suite_and_the_validator_are_steps(self) -> None:
        for command in (
            "python -m unittest discover -s dashboard/tests",
            "python -m unittest discover -s packaging/tests",
            "python -m unittest discover -s evals/tests",
            "python evals/scripts/eval_suite.py validate",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.commands)

    def test_every_suite_on_disk_is_run(self) -> None:
        """A fourth `*/tests` directory must not be added without a step."""
        on_disk = {path.parent.parent.name + "/tests" for path in REPO_ROOT.glob("*/tests/test_*.py")}
        self.assertGreaterEqual(len(on_disk), 3)
        for suite in sorted(on_disk):
            with self.subTest(suite=suite):
                self.assertIn(f"python -m unittest discover -s {suite}", self.commands)

    def test_it_runs_on_both_systems(self) -> None:
        self.assertRegex(self.text, r"(?m)^\s*os: \[[^\]]*ubuntu-latest[^\]]*\]")
        self.assertRegex(self.text, r"(?m)^\s*os: \[[^\]]*windows-latest[^\]]*\]")

    def test_it_runs_on_pull_requests_and_on_main(self) -> None:
        self.assertRegex(self.text, r"(?m)^  pull_request:")
        self.assertRegex(self.text, r"(?m)^  push:\n    branches: \[main\]")

    def test_no_step_is_allowed_to_fail(self) -> None:
        self.assertNotIn("continue-on-error", self.text)
        for command in self.commands:
            with self.subTest(command=command):
                self.assertNotIn("|| true", command)

    def test_the_gate_does_not_read_the_calendar(self) -> None:
        """Freshness belongs to the scheduled workflow, or `main` goes red on a date."""
        self.assertFalse([command for command in self.commands if "check_evidence_freshness" in command])


class EvidenceFreshnessWorkflow(unittest.TestCase):
    def setUp(self) -> None:
        self.path = WORKFLOWS / "evidence-freshness.yml"
        self.text = self.path.read_text(encoding="utf-8")
        self.commands = run_lines(self.path)

    def test_it_runs_the_check_on_a_schedule(self) -> None:
        self.assertRegex(self.text, r"(?m)^  schedule:\n    - cron: ")
        self.assertTrue([command for command in self.commands if "check_evidence_freshness.py" in command])

    def test_it_does_not_pin_the_date(self) -> None:
        """`--today` here would freeze the one check meant to follow the clock."""
        for command in self.commands:
            with self.subTest(command=command):
                self.assertNotIn("--today", command)

    def test_it_is_allowed_to_fail(self) -> None:
        self.assertNotIn("continue-on-error", self.text)


if __name__ == "__main__":
    unittest.main()
