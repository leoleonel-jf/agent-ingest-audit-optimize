"""Tests for `ledgerlib.rollback`: the four sets and the health indicator.

The suite loads `dashboard.py` by file path exactly the way `test_drift.py`
does, for the same side effect: `dashboard.py` inserts its own directory at
the front of `sys.path` before importing `ledgerlib`, so the imports below
resolve to the bundle's copy rather than to anything installed.

Two reuse rules are pinned here by patching, because "same code, not similar
code" is a claim about call graphs and only a patch can observe one:
`rollback_preview` classifies run targets through `drift.classify_target` --
patching that one name changes `drift` and `rollback-preview` together -- and
it recomputes the backup digest through the `file_digest` binding `verify`
itself calls, so patching `ledgerlib.verify.file_digest` once changes both
commands' behaviour in the same `with` block.

The set rules worth stating in prose, because each is the kind a refactor
breaks silently: the report always carries all four sets, empty ones as `[]`;
`will_be_restored` requires a verified backup, so under `BROKEN` it is empty
while the other sets still populate from target states; and `BROKEN` is
checked first but short-circuits nothing -- the sets are still computed and
reported beside the indicator.
"""

from __future__ import annotations

import builtins
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import shutil
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
TEMPLATE_PATH = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "templates"
    / "dashboard.html"
)
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib.constants import ROLLBACK_INDICATORS  # noqa: E402
from ledgerlib.errors import LedgerError  # noqa: E402
from ledgerlib import drift as drift_module  # noqa: E402
from ledgerlib import rollback as rollback_module  # noqa: E402
from ledgerlib import verify as verify_module  # noqa: E402
from ledgerlib.drift import drift_report  # noqa: E402
from ledgerlib.rollback import (  # noqa: E402
    rollback_preview,
    rollback_preview_command,
)
from ledgerlib.verify import verify  # noqa: E402


RUN_ID = "RUN-2026-000"
SETS = (
    "will_be_restored",
    "will_not_change",
    "cannot_be_restored",
    "residual_effects",
)


class RollbackTestCase(unittest.TestCase):
    """A real temporary tree, following `DriftReportTestCase` in test_drift.py.

    The adapter is written to the temporary tree and named explicitly, so no
    test here depends on the bundled adapter files and no test reads this
    machine's real configuration. Backups are real files whose digests the
    tests compute independently, because backup verification's whole job is to
    compare a recorded digest against real bytes.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.user_config = self.tmp / "user_config"
        self.user_config.mkdir(parents=True)
        self.adapter_path = self.tmp / "adapter.json"
        self.adapter_path.write_text(
            json.dumps(self.adapter_document()), encoding="utf-8"
        )

    def adapter_document(self) -> dict:
        return {
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

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def digest_of(self, path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def target(self, **overrides: object) -> dict:
        base: dict = {
            "anchor": "$USER_CONFIG/settings.json",
            "kind": "mcp-server",
            "before_digest": "sha256:" + "0" * 64,
            "after_digest": "sha256:" + "1" * 64,
            "reversible": True,
            "residual_effect": None,
        }
        base.update(overrides)
        return base

    # Each state helper writes its own file under a distinct name so one run
    # can hold several states at once without the fixtures colliding.

    def in_place_target(self, name: str = "settings.json", **overrides) -> dict:
        current = self.write(self.user_config / name, f"after {name}\n")
        return self.target(
            anchor=f"$USER_CONFIG/{name}",
            after_digest=self.digest_of(current),
            **overrides,
        )

    def reverted_target(self, name: str = "reverted.json", **overrides) -> dict:
        current = self.write(self.user_config / name, f"before {name}\n")
        return self.target(
            anchor=f"$USER_CONFIG/{name}",
            before_digest=self.digest_of(current),
            **overrides,
        )

    def drifted_target(self, name: str = "drifted.json", **overrides) -> dict:
        self.write(self.user_config / name, f"edited outside {name}\n")
        return self.target(anchor=f"$USER_CONFIG/{name}", **overrides)

    def missing_target(self, name: str = "gone.json", **overrides) -> dict:
        return self.target(anchor=f"$USER_CONFIG/{name}", **overrides)

    def unverifiable_target(self, name: str = "nodigest.json", **overrides) -> dict:
        self.write(self.user_config / name, f"present {name}\n")
        return self.target(
            anchor=f"$USER_CONFIG/{name}",
            before_digest=None,
            after_digest=None,
            **overrides,
        )

    def verified_backup(self) -> dict:
        backup_file = self.write(
            self.user_config / "backups" / f"{RUN_ID}.bak", "backup bytes\n"
        )
        return {
            "path": f"$USER_CONFIG/backups/{RUN_ID}.bak",
            "digest": self.digest_of(backup_file),
            "verified": True,
        }

    def run_record(self, targets: list, backup: object) -> dict:
        return {"id": RUN_ID, "type": "RUN", "targets": targets, "backup": backup}

    def ledger(self, records: list) -> dict:
        return {
            "schema_version": "1.0",
            "client": "testclient",
            "baselines": [],
            "records": records,
        }

    def preview(self, records: list, run_id: str = RUN_ID):
        return rollback_preview(
            self.ledger(records),
            run_id,
            adapter=self.adapter_path,
            project=self.tmp,
            environ={},
        )


class RollbackIndicatorsTests(unittest.TestCase):
    def test_rollback_indicators_is_exactly_the_three_value_set(self) -> None:
        self.assertEqual(ROLLBACK_INDICATORS, {"HEALTHY", "AT_RISK", "BROKEN"})


class FourSetsTests(RollbackTestCase):
    """The report always contains all four sets, empty ones as `[]`."""

    def test_the_report_always_contains_all_four_sets_empty_ones_as_lists(
        self,
    ) -> None:
        # One scenario per set: a run where every target set is empty but
        # that one. `residual_effects` cannot be populated alone -- a target
        # always lands in exactly one of the three target sets, which is the
        # partition the report owes its reader -- so its scenario pins the
        # residual beside the set its target occupies.
        scenarios = {
            "will_be_restored": self.run_record(
                [self.in_place_target()], self.verified_backup()
            ),
            "will_not_change": self.run_record(
                [self.reverted_target()], self.verified_backup()
            ),
            "cannot_be_restored": self.run_record(
                [self.drifted_target()], self.verified_backup()
            ),
        }
        for populated, record in scenarios.items():
            with self.subTest(populated=populated):
                report, _, _ = self.preview([record])
                for name in SETS:
                    self.assertIn(name, report)
                    if name == populated:
                        self.assertEqual(len(report[name]), 1, report)
                    else:
                        self.assertEqual(report[name], [], report)
        with self.subTest(populated="residual_effects"):
            report, _, _ = self.preview(
                [
                    self.run_record(
                        [
                            self.in_place_target(
                                "residual.json",
                                residual_effect="a dependency was installed",
                            )
                        ],
                        self.verified_backup(),
                    )
                ]
            )
            for name in SETS:
                self.assertIn(name, report)
            self.assertEqual(
                report["residual_effects"], ["a dependency was installed"]
            )
            self.assertEqual(len(report["will_be_restored"]), 1, report)
            self.assertEqual(report["will_not_change"], [], report)
            self.assertEqual(report["cannot_be_restored"], [], report)


class PreviewSetContractTests(RollbackTestCase):
    """M3: the four set-key names are a contract between this module and
    the shell template, and until now nothing pinned the two sides
    together -- only a human reading both files at once could have noticed
    a rename in either one.

    `dashboard.html` declares `var PREVIEW_SETS = [...]`, the literal list
    its Rollback renderer loops over to pull each set out of a live preview
    (`skills/agent-ingest-audit-optimize/assets/templates/dashboard.html`,
    `rollbackBlock`). This test extracts that array by regex, straight out
    of the shipped template source, and compares it against the actual keys
    a real `rollback_preview()` call returns -- not against a second
    hand-typed tuple that could itself drift from either side. `SETS`
    above is checked too, since it is what the rest of this suite already
    asserts against by name; if a rename slipped past both `PREVIEW_SETS`
    and `SETS` in the same change, this second comparison is what would
    still catch it, because it is computed from the live report both times.

    A rename on either side breaks this test, in different ways: renaming
    a key in `dashboard.html`'s `PREVIEW_SETS` makes the template's set
    disagree with the report's; renaming a key in `rollback_preview`'s
    `report` dict does the same from the other side. Both directions were
    exercised by hand while writing this test (see the report's M3
    transcript for both simulated renames and their failures) and reverted
    before landing.
    """

    NON_SET_KEYS = frozenset({"run", "indicator", "backup"})

    def template_preview_sets(self) -> tuple[str, ...]:
        text = TEMPLATE_PATH.read_text(encoding="utf-8")
        match = re.search(r"var PREVIEW_SETS = \[(.*?)\];", text, re.DOTALL)
        assert match is not None, (
            "dashboard.html no longer declares `var PREVIEW_SETS = [...]`"
        )
        return tuple(re.findall(r'"([^"]+)"', match.group(1)))

    def test_the_templates_preview_sets_are_exactly_the_reports_own_keys(
        self,
    ) -> None:
        template_sets = self.template_preview_sets()
        report, _, _ = self.preview(
            [self.run_record([self.in_place_target()], self.verified_backup())]
        )
        report_sets = set(report) - self.NON_SET_KEYS
        self.assertEqual(
            set(template_sets),
            report_sets,
            "the template's PREVIEW_SETS and rollback_preview's own report "
            "keys disagree -- one side was renamed without the other",
        )
        # No duplicates and no stowaways: the template's list is the report's
        # key set, not a superset or a subset of it.
        self.assertEqual(len(template_sets), len(report_sets))

    def test_the_templates_preview_sets_match_this_suites_own_sets_tuple(
        self,
    ) -> None:
        """`SETS` above is what every other case in this file asserts
        against by name. Comparing it here too means a rename that updated
        `PREVIEW_SETS` and the live report but missed `SETS` -- or the
        reverse -- still fails a test instead of quietly passing because
        the one comparison above happened to still line up.
        """
        self.assertEqual(set(self.template_preview_sets()), set(SETS))


class SetMembershipTests(RollbackTestCase):
    def test_a_target_in_place_with_a_verified_backup_is_will_be_restored(
        self,
    ) -> None:
        report, _, _ = self.preview(
            [self.run_record([self.in_place_target()], self.verified_backup())]
        )
        self.assertEqual(
            report["will_be_restored"],
            [
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "path": str(self.user_config / "settings.json"),
                    "kind": "mcp-server",
                    "state": "IN_PLACE",
                }
            ],
        )

    def test_a_reverted_target_is_will_not_change(self) -> None:
        report, _, _ = self.preview(
            [self.run_record([self.reverted_target()], self.verified_backup())]
        )
        self.assertEqual(
            report["will_not_change"],
            [
                {
                    "anchor": "$USER_CONFIG/reverted.json",
                    "path": str(self.user_config / "reverted.json"),
                    "kind": "mcp-server",
                    "state": "REVERTED",
                }
            ],
        )

    def test_drifted_missing_and_unverifiable_targets_are_cannot_be_restored(
        self,
    ) -> None:
        # Each entry carries its drift state as the reason (spec 3.3).
        cases = {
            "DRIFTED": self.drifted_target(),
            "MISSING": self.missing_target(),
            "UNVERIFIABLE": self.unverifiable_target(),
        }
        for state, target in cases.items():
            with self.subTest(state=state):
                report, _, _ = self.preview(
                    [self.run_record([target], self.verified_backup())]
                )
                self.assertEqual(len(report["cannot_be_restored"]), 1)
                row = report["cannot_be_restored"][0]
                self.assertEqual(row["state"], state)
                self.assertEqual(row["reason"], state)
                self.assertEqual(report["will_be_restored"], [])

    def test_every_non_null_residual_effect_appears_verbatim(self) -> None:
        record = self.run_record(
            [
                self.in_place_target(
                    "a.json", residual_effect="installed the foo package globally"
                ),
                self.in_place_target("b.json"),
                self.drifted_target(
                    "c.json", residual_effect="published an artifact to the registry"
                ),
            ],
            self.verified_backup(),
        )
        report, _, _ = self.preview([record])
        self.assertEqual(
            report["residual_effects"],
            [
                "installed the foo package globally",
                "published an artifact to the registry",
            ],
        )


class IndicatorTests(RollbackTestCase):
    def test_a_missing_backup_yields_broken_and_exit_one(self) -> None:
        # The section 16 acceptance criterion, as a named test: no recorded
        # backup means nothing can be trusted to restore anything.
        report, _, code = self.preview(
            [self.run_record([self.in_place_target()], None)]
        )
        self.assertEqual(report["indicator"], "BROKEN")
        self.assertEqual(code, 1)

    def test_a_backup_whose_path_does_not_exist_is_broken(self) -> None:
        backup = {
            "path": "$USER_CONFIG/backups/absent.bak",
            "digest": "sha256:" + "a" * 64,
            "verified": True,
        }
        report, _, code = self.preview(
            [self.run_record([self.in_place_target()], backup)]
        )
        self.assertEqual(report["indicator"], "BROKEN")
        self.assertEqual(report["backup"]["reason"], "missing")
        self.assertEqual(code, 1)

    def test_a_backup_whose_digest_mismatches_is_broken(self) -> None:
        backup = self.verified_backup()
        backup["digest"] = "sha256:" + "b" * 64
        report, _, code = self.preview(
            [self.run_record([self.in_place_target()], backup)]
        )
        self.assertEqual(report["indicator"], "BROKEN")
        self.assertEqual(report["backup"]["reason"], "digest_mismatch")
        self.assertEqual(code, 1)

    def test_a_verified_backup_with_a_drifted_target_is_at_risk(self) -> None:
        report, _, code = self.preview(
            [
                self.run_record(
                    [self.in_place_target(), self.drifted_target()],
                    self.verified_backup(),
                )
            ]
        )
        self.assertEqual(report["indicator"], "AT_RISK")
        self.assertEqual(code, 1)

    def test_a_verified_backup_with_a_residual_effect_is_at_risk(self) -> None:
        report, _, code = self.preview(
            [
                self.run_record(
                    [
                        self.in_place_target(
                            residual_effect="created an external account"
                        )
                    ],
                    self.verified_backup(),
                )
            ]
        )
        self.assertEqual(report["indicator"], "AT_RISK")
        self.assertEqual(code, 1)

    def test_a_verified_backup_all_in_place_no_residuals_is_healthy_exit_zero(
        self,
    ) -> None:
        report, _, code = self.preview(
            [
                self.run_record(
                    [self.in_place_target("a.json"), self.in_place_target("b.json")],
                    self.verified_backup(),
                )
            ]
        )
        self.assertEqual(report["indicator"], "HEALTHY")
        self.assertEqual(code, 0)

    def test_a_missing_target_under_a_verified_backup_is_at_risk_not_healthy(
        self,
    ) -> None:
        # The literal indicator table covers neither state: the backup
        # verifies, nothing DRIFTED, no residuals -- yet a target is gone, so
        # the run is not HEALTHY (that requires every target IN_PLACE) and the
        # target sits in cannot_be_restored. A rollback that cannot restore
        # everything is at risk, which is spec 3.3's cannot_be_restored
        # rationale, so AT_RISK is the honest resolution.
        report, _, code = self.preview(
            [
                self.run_record(
                    [self.in_place_target(), self.missing_target()],
                    self.verified_backup(),
                )
            ]
        )
        self.assertEqual(report["indicator"], "AT_RISK")
        self.assertEqual(code, 1)
        self.assertEqual(report["cannot_be_restored"][0]["reason"], "MISSING")

    def test_broken_does_not_short_circuit_the_sets(self) -> None:
        # BROKEN is checked first, and that is all it is: the sets are still
        # computed and reported beside the indicator. `will_be_restored`
        # empties -- restoring requires the backup nothing verified -- and
        # its intact targets move to `cannot_be_restored` rather than
        # vanishing from the report.
        report, _, code = self.preview(
            [
                self.run_record(
                    [
                        self.reverted_target(),
                        self.drifted_target(),
                        self.in_place_target(
                            residual_effect="wrote to an external cache"
                        ),
                    ],
                    None,
                )
            ]
        )
        self.assertEqual(report["indicator"], "BROKEN")
        self.assertEqual(code, 1)
        self.assertEqual(len(report["will_not_change"]), 1)
        self.assertEqual(len(report["cannot_be_restored"]), 2)
        self.assertEqual(
            report["residual_effects"], ["wrote to an external cache"]
        )
        self.assertEqual(report["will_be_restored"], [])

    def test_an_intact_target_without_a_backup_is_not_restorable(self) -> None:
        # The first real preview dropped 6 of a run's 17 targets: IN_PLACE,
        # backup missing -- no set claimed them. Intact and unrestorable is
        # `cannot_be_restored`, carrying the backup's reason rather than a
        # drift state, because the backup is what cannot be restored *from*.
        report, _, _ = self.preview(
            [self.run_record([self.in_place_target()], None)]
        )
        self.assertEqual(len(report["cannot_be_restored"]), 1)
        row = report["cannot_be_restored"][0]
        self.assertEqual(row["state"], "IN_PLACE")
        self.assertEqual(row["reason"], "missing")

    def test_the_sets_partition_every_target(self) -> None:
        # Four targets, four fates, backup missing: every target appears in
        # exactly one of the three target sets, whatever the backup did.
        report, _, _ = self.preview(
            [
                self.run_record(
                    [
                        self.in_place_target(),
                        self.reverted_target(),
                        self.drifted_target(),
                        self.unverifiable_target(),
                    ],
                    None,
                )
            ]
        )
        counted = (
            len(report["will_be_restored"])
            + len(report["will_not_change"])
            + len(report["cannot_be_restored"])
        )
        self.assertEqual(counted, 4)


class ToolErrorTests(RollbackTestCase):
    def test_an_unknown_run_id_raises_a_ledger_error_naming_the_id(self) -> None:
        with self.assertRaises(LedgerError) as caught:
            self.preview(
                [self.run_record([self.in_place_target()], self.verified_backup())],
                run_id="RUN-2026-999",
            )
        self.assertIn("'RUN-2026-999'", str(caught.exception))

    def test_an_id_naming_a_non_run_record_raises_naming_the_id(self) -> None:
        records = [
            {"id": "MAT-2026-000", "type": "MATERIAL"},
            self.run_record([self.in_place_target()], self.verified_backup()),
        ]
        with self.assertRaises(LedgerError) as caught:
            self.preview(records, run_id="MAT-2026-000")
        self.assertIn("'MAT-2026-000'", str(caught.exception))


class SharedMachineryTests(RollbackTestCase):
    """Same code, not similar code -- observed by patching one name once."""

    def test_classification_comes_from_drifts_classifier(self) -> None:
        # One patch of `drift.classify_target` changes both commands: the
        # proof that `rollback_preview` holds no second classifier.
        record = self.run_record([self.in_place_target()], self.verified_backup())
        ledger = self.ledger([record])

        report, _, _ = self.preview([record])
        self.assertEqual(report["indicator"], "HEALTHY")
        drift_before, _, _ = drift_report(
            ledger, adapter=self.adapter_path, project=self.tmp, environ={}
        )
        self.assertEqual(drift_before["runs"][0]["targets"][0]["state"], "IN_PLACE")

        with mock.patch.object(
            drift_module, "classify_target", return_value=("DRIFTED", None)
        ):
            patched_preview, _, _ = self.preview([record])
            patched_drift, _, _ = drift_report(
                ledger, adapter=self.adapter_path, project=self.tmp, environ={}
            )
        self.assertEqual(patched_preview["indicator"], "AT_RISK")
        self.assertEqual(
            patched_preview["cannot_be_restored"][0]["reason"], "DRIFTED"
        )
        self.assertEqual(
            patched_drift["runs"][0]["targets"][0]["state"], "DRIFTED"
        )

    def test_backup_verification_reuses_the_digest_recomputation_verify_uses(
        self,
    ) -> None:
        # `verify` recomputes digests through its own `file_digest` binding;
        # `rollback_preview` must call that same binding, so one patch of
        # `ledgerlib.verify.file_digest` changes both commands together.
        record = self.run_record([self.in_place_target()], self.verified_backup())

        project_ledger = self.tmp / "project-ledger.json"
        project_ledger.write_text(
            json.dumps(_bare_ledger("l-project", scope="project", authority=False)),
            encoding="utf-8",
        )
        global_document = _bare_ledger("l-global", scope="global", authority=True)
        global_document["known_projects"] = [
            {
                "project_root": str(self.tmp),
                "ledger_path": str(project_ledger),
                "last_seen": "2026-07-30",
                "last_digest": self.digest_of(project_ledger),
                "status": "OK",
            }
        ]
        global_ledger = self.tmp / "global-ledger.json"
        global_ledger.write_text(json.dumps(global_document), encoding="utf-8")

        def run_verify() -> int:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                return verify([global_ledger, project_ledger])

        self.assertEqual(run_verify(), 0)
        report, _, _ = self.preview([record])
        self.assertEqual(report["indicator"], "HEALTHY")

        with mock.patch.object(
            verify_module,
            "file_digest",
            side_effect=lambda path: "sha256:" + "f" * 64,
        ):
            self.assertEqual(run_verify(), 1)
            patched, _, _ = self.preview([record])
        self.assertEqual(patched["indicator"], "BROKEN")
        self.assertEqual(patched["backup"]["reason"], "digest_mismatch")


def _bare_ledger(ledger_id: str, *, scope: str, authority: bool) -> dict:
    return {
        "schema_version": "1.0",
        "ledger_id": ledger_id,
        "scope": scope,
        "language": "en",
        "client": "testclient",
        "adapter_version": 1,
        "created": "2026-07-29",
        "updated": "2026-07-30",
        "id_authority": authority,
        "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0},
        "known_projects": [],
        "records": [],
        "baselines": [],
        "backlog": [],
    }


class RollbackCliTestCase(RollbackTestCase):
    """A valid ledger on disk, and `dashboard.main` driven the way a shell
    would -- following `DriftCliTestCase` for the same reason: argparse wiring
    no test crosses is wiring that can be deleted without a test noticing."""

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = dashboard.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def full_run(self, targets: list, backup: object) -> dict:
        """A RUN record `validate_ledger` accepts whole, unlike `run_record`."""
        return {
            "id": RUN_ID,
            "type": "RUN",
            "title": "a validated run",
            "status": "VALIDATED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-30",
            "updated": "2026-07-30",
            "file": f"records/{RUN_ID}.md",
            "links": {"materials": [], "runs": [], "adrs": []},
            "evidence": [],
            "proposal": "PROP-2026-000",
            "authorization": {
                "quote": "Implement proposal PROP-2026-000",
                "recorded_on": "2026-07-30",
            },
            "result": "VALIDATED",
            "targets": targets,
            "backup": backup,
            "rollback": {"tested": "NOT_TESTED"},
            "self_reported": ["targets"],
        }

    def full_material(self) -> dict:
        return {
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

    def valid_ledger(self, records: list) -> dict:
        return {
            **_bare_ledger("l-rollback-cli", scope="global", authority=True),
            "sequences": {"MAT": 1, "PROP": 1, "RUN": 1, "ADR": 0, "BASE": 0},
            "records": records,
        }

    def write_ledger(self, document: dict) -> Path:
        path = self.tmp / "ledger.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def healthy_ledger(self) -> Path:
        return self.write_ledger(
            self.valid_ledger(
                [self.full_run([self.in_place_target()], self.verified_backup())]
            )
        )

    def rollback_arguments(
        self, ledger: Path, run_id: str = RUN_ID
    ) -> list[str]:
        return [
            "rollback-preview",
            str(ledger),
            run_id,
            "--adapter",
            str(self.adapter_path),
            "--project",
            str(self.tmp),
        ]


class RollbackCliTests(RollbackCliTestCase):
    def test_the_subcommand_is_wired_into_main(self) -> None:
        code, stdout, _ = self.run_cli(
            *self.rollback_arguments(self.healthy_ledger())
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["indicator"], "HEALTHY")

    def test_the_subcommand_reaches_rollback_preview_through_main(self) -> None:
        arguments = self.rollback_arguments(self.healthy_ledger())
        with mock.patch.object(
            rollback_module,
            "rollback_preview",
            wraps=rollback_module.rollback_preview,
        ) as spy:
            code, _, _ = self.run_cli(*arguments)
        self.assertEqual(code, 0)
        spy.assert_called_once()

    def test_stdout_holds_one_indented_json_report_and_nothing_else(self) -> None:
        _, stdout, stderr = self.run_cli(
            *self.rollback_arguments(self.healthy_ledger())
        )
        report = json.loads(stdout)
        self.assertEqual(stdout.rstrip("\n"), json.dumps(report, indent=2))
        for name in SETS:
            self.assertIn(name, report)
        self.assertNotIn("selected adapter", stdout)
        self.assertIn("selected adapter", stderr)

    def test_a_missing_backup_yields_broken_and_exit_one_through_the_cli(
        self,
    ) -> None:
        # Section 16's fixture shape: a ledger whose backup path does not
        # exist. The recorded digest and flag are well-formed -- what is
        # broken is the world, not the record.
        backup = {
            "path": "$USER_CONFIG/backups/deleted.bak",
            "digest": "sha256:" + "c" * 64,
            "verified": True,
        }
        ledger = self.write_ledger(
            self.valid_ledger([self.full_run([self.in_place_target()], backup)])
        )
        code, stdout, _ = self.run_cli(*self.rollback_arguments(ledger))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["indicator"], "BROKEN")

    def test_an_unknown_run_id_exits_two_naming_the_id(self) -> None:
        code, stdout, stderr = self.run_cli(
            *self.rollback_arguments(self.healthy_ledger(), run_id="RUN-2026-999")
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("'RUN-2026-999'", stderr)

    def test_an_id_naming_a_non_run_record_exits_two_naming_the_id(self) -> None:
        ledger = self.write_ledger(
            self.valid_ledger(
                [
                    self.full_material(),
                    self.full_run([self.in_place_target()], self.verified_backup()),
                ]
            )
        )
        code, stdout, stderr = self.run_cli(
            *self.rollback_arguments(ledger, run_id="MAT-2026-000")
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("'MAT-2026-000'", stderr)

    def test_a_missing_ledger_exits_two(self) -> None:
        missing = self.tmp / "no-such-ledger.json"
        code, stdout, stderr = self.run_cli(*self.rollback_arguments(missing))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn(missing.name, stderr)

    def test_an_invalid_ledger_exits_two_with_findings_on_stderr(self) -> None:
        document = self.valid_ledger(
            [self.full_run([self.in_place_target()], self.verified_backup())]
        )
        del document["sequences"]
        code, stdout, stderr = self.run_cli(
            *self.rollback_arguments(self.write_ledger(document))
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("sequences", stderr)

    def test_rollback_preview_is_re_exported_from_dashboard(self) -> None:
        self.assertIs(dashboard.rollback_preview, rollback_module.rollback_preview)
        self.assertIs(
            dashboard.rollback_preview_command,
            rollback_module.rollback_preview_command,
        )
        self.assertIs(dashboard.ROLLBACK_INDICATORS, ROLLBACK_INDICATORS)


class RollbackWritesNothingTests(RollbackCliTestCase):
    """`rollback-preview` is read-only, guarded the way
    `DriftWritesNothingTests` guards `drift`: every write API patched to fail
    loudly, naming what was attempted, because a read-only tree is not
    portable to Windows."""

    def arm(self) -> None:
        real_path_open = Path.open
        real_open = builtins.open

        def guarded_path_open(this, mode="r", *args, **kwargs):
            if isinstance(mode, str) and set(mode) & set("wxa+"):
                raise AssertionError(
                    f"rollback-preview opened {this} with mode {mode!r}"
                )
            return real_path_open(this, mode, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            if isinstance(mode, str) and set(mode) & set("wxa+"):
                raise AssertionError(
                    f"rollback-preview opened {file!r} with mode {mode!r}"
                )
            return real_open(file, mode, *args, **kwargs)

        def refuse(name):
            def guard(this, *args, **kwargs):
                raise AssertionError(f"rollback-preview called Path.{name} on {this}")

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
        """Without this, a broken patch makes the tests below pass silently."""
        self.arm()
        with self.assertRaises(AssertionError):
            (self.tmp / "written.txt").write_text("no", encoding="utf-8")
        with self.assertRaises(AssertionError):
            (self.tmp / "made").mkdir()
        with self.assertRaises(AssertionError):
            open(self.tmp / "opened.txt", "w").close()

    def test_the_cli_writes_nothing_and_exits_zero_on_a_healthy_fixture(
        self,
    ) -> None:
        arguments = self.rollback_arguments(self.healthy_ledger())
        self.arm()
        code, stdout, _ = self.run_cli(*arguments)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["indicator"], "HEALTHY")

    def test_the_direct_call_writes_nothing_either(self) -> None:
        ledger = self.healthy_ledger()
        self.arm()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rollback_preview_command(
                ledger=ledger,
                run_id=RUN_ID,
                adapter=self.adapter_path,
                project=self.tmp,
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["indicator"], "HEALTHY")


class ResolvedPathTests(RollbackTestCase):
    """0.5.0: every set row -- and the backup -- records its resolved path.

    Same key, same meaning, same producer as `drift_report`'s rows: the
    string `resolve_anchored` gives, or None where nothing resolves. The
    backup gets one too, because design spec section 12.2's Open offer names
    "the record, the backup, or the changed file", and the backup is a real
    file this preview just verified (or failed to).
    """

    def test_every_set_row_carries_the_resolved_path(self) -> None:
        record = self.run_record(
            [
                self.in_place_target(),
                self.reverted_target(),
                self.drifted_target(),
            ],
            self.verified_backup(),
        )
        report, _, _ = self.preview([record])
        self.assertEqual(
            report["will_be_restored"][0]["path"],
            str(self.user_config / "settings.json"),
        )
        self.assertEqual(
            report["will_not_change"][0]["path"],
            str(self.user_config / "reverted.json"),
        )
        self.assertEqual(
            report["cannot_be_restored"][0]["path"],
            str(self.user_config / "drifted.json"),
        )

    def test_a_missing_targets_row_still_carries_its_path(self) -> None:
        record = self.run_record([self.missing_target()], self.verified_backup())
        report, _, _ = self.preview([record])
        row = report["cannot_be_restored"][0]
        self.assertEqual(row["reason"], "MISSING")
        self.assertEqual(row["path"], str(self.user_config / "gone.json"))

    def test_an_unresolvable_targets_row_has_a_null_path(self) -> None:
        record = self.run_record(
            [self.target(anchor="$UNKNOWN/settings.json")], self.verified_backup()
        )
        report, _, _ = self.preview([record])
        self.assertIsNone(report["cannot_be_restored"][0]["path"])

    def test_the_backup_carries_its_resolved_path(self) -> None:
        record = self.run_record([self.in_place_target()], self.verified_backup())
        report, _, _ = self.preview([record])
        self.assertEqual(
            report["backup"]["path"],
            str(self.user_config / "backups" / f"{RUN_ID}.bak"),
        )

    def test_a_missing_backup_has_a_null_path(self) -> None:
        record = self.run_record([self.in_place_target()], None)
        report, _, _ = self.preview([record])
        self.assertIsNone(report["backup"]["path"])

    def test_an_unresolvable_backup_has_a_null_path(self) -> None:
        record = self.run_record(
            [self.in_place_target()],
            {"path": "$USER_CONFIG/../escape.bak", "digest": "sha256:" + "0" * 64},
        )
        report, _, _ = self.preview([record])
        self.assertEqual(report["indicator"], "BROKEN")
        self.assertIsNone(report["backup"]["path"])


if __name__ == "__main__":
    unittest.main()
