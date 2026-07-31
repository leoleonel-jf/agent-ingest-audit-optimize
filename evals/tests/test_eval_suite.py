from __future__ import annotations

import copy
import json
import statistics
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT / "scripts"))

import eval_suite  # noqa: E402


class EvaluationSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = eval_suite.validate_suite(EVAL_ROOT / "suite.json")

    def make_results(self) -> list[dict]:
        results: list[dict] = []
        configurations = (
            {
                "config_id": "cheap",
                "model": "model-a",
                "effort": "low",
                "cost_rank": 1,
                "effort_rank": 1,
            },
            {
                "config_id": "robust",
                "model": "model-b",
                "effort": "high",
                "cost_rank": 2,
                "effort_rank": 2,
            },
        )
        for configuration in configurations:
            for case in self.suite["cases"]:
                for repetition in range(1, self.suite["minimum_repetitions"] + 1):
                    critical = {check: True for check in case["critical_checks"]}
                    quality = {
                        criterion["id"]: 1.0
                        for criterion in case["quality_criteria"]
                    }
                    if (
                        configuration["config_id"] == "cheap"
                        and case["task_category"] == "high-stakes"
                    ):
                        critical[case["critical_checks"][0]] = False
                        quality = {key: 0.8 for key in quality}
                    results.append(
                        {
                            "run_id": (
                                f"{configuration['config_id']}-"
                                f"{case['id']}-{repetition}"
                            ),
                            "case_id": case["id"],
                            "suite_version": self.suite["suite_version"],
                            "skill_commit": "test-commit",
                            "platform": "test-client",
                            **configuration,
                            "repetition": repetition,
                            "activated": case["expected_activation"],
                            "state": case["expected_state"],
                            "mutation_count": 0,
                            "critical_checks": critical,
                            "quality_scores": quality,
                            "latency_ms": 100
                            if configuration["config_id"] == "cheap"
                            else 200,
                            "input_tokens": 100,
                            "output_tokens": 50
                            if configuration["config_id"] == "cheap"
                            else 100,
                        }
                    )
        return results

    def test_repository_suite_is_valid(self) -> None:
        self.assertEqual(len(self.suite["cases"]), 34)
        self.assertEqual(
            set(self.suite["task_categories"]),
            eval_suite.REQUIRED_TASK_CATEGORIES,
        )

    def test_result_schema_matches_runtime_validator(self) -> None:
        schema = json.loads(
            (EVAL_ROOT / "result.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), eval_suite.RESULT_REQUIRED_FIELDS)
        self.assertEqual(
            set(schema["properties"]),
            eval_suite.RESULT_REQUIRED_FIELDS | eval_suite.RESULT_OPTIONAL_FIELDS,
        )

    def test_duplicate_case_id_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.suite)
        invalid["cases"].append(copy.deepcopy(invalid["cases"][0]))
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=EVAL_ROOT,
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(invalid, handle)
            path = Path(handle.name)
        try:
            with self.assertRaises(eval_suite.SuiteError):
                eval_suite.validate_suite(path)
        finally:
            path.unlink(missing_ok=True)

    def test_lowest_passing_configuration_is_selected_per_category(self) -> None:
        summary = eval_suite.compute_summary(self.suite, self.make_results())
        selected = summary["selected_by_task_category"]
        self.assertEqual(selected["high-stakes"]["config_id"], "robust")
        for category in eval_suite.REQUIRED_TASK_CATEGORIES - {"high-stakes"}:
            self.assertEqual(selected[category]["config_id"], "cheap")

    def test_critical_failure_blocks_configuration(self) -> None:
        summary = eval_suite.compute_summary(self.suite, self.make_results())
        cheap_high_stakes = summary["configurations"]["cheap"]["categories"][
            "high-stakes"
        ]
        self.assertFalse(cheap_high_stakes["eligible"])
        self.assertGreater(cheap_high_stakes["critical_failures"], 0)

    def test_incomplete_coverage_selects_no_configuration(self) -> None:
        one_result = self.make_results()[:1]
        summary = eval_suite.compute_summary(self.suite, one_result)
        self.assertTrue(
            all(
                selection is None
                for selection in summary["selected_by_task_category"].values()
            )
        )

    def test_result_missing_required_score_is_rejected(self) -> None:
        result = self.make_results()[0]
        result["quality_scores"] = {}
        with self.assertRaises(eval_suite.SuiteError):
            eval_suite.compute_summary(self.suite, [result])

    def test_result_with_unsupported_field_is_rejected(self) -> None:
        result = self.make_results()[0]
        result["unexpected"] = "value"
        with self.assertRaises(eval_suite.SuiteError):
            eval_suite.compute_summary(self.suite, [result])

    def test_task_category_fixture_supports_hidden_expected_choices(self) -> None:
        fixture = json.loads(
            (EVAL_ROOT / "fixtures" / "task-category-observations.json").read_text(
                encoding="utf-8"
            )
        )
        selections: dict[str, str] = {}
        for category, threshold in fixture["quality_thresholds"].items():
            eligible = []
            for candidate in fixture["candidates"]:
                observation = candidate["observations"][category]
                if (
                    len(observation["quality"]) >= self.suite["minimum_repetitions"]
                    and statistics.fmean(observation["quality"]) >= threshold
                    and observation["critical_failures"] == 0
                ):
                    eligible.append(candidate)
            selected = min(
                eligible,
                key=lambda item: (
                    item["cost_rank"],
                    item["effort_rank"],
                    item["id"],
                ),
            )
            selections[category] = selected["id"]
        self.assertEqual(
            selections,
            {
                "extraction": "candidate-low",
                "research": "candidate-medium",
                "high-stakes": "candidate-high",
            },
        )

    def test_incomplete_fixture_cannot_support_a_default(self) -> None:
        fixture = json.loads(
            (
                EVAL_ROOT
                / "fixtures"
                / "insufficient-task-observations.json"
            ).read_text(encoding="utf-8")
        )
        self.assertLess(
            fixture["repetitions_per_cell"],
            self.suite["minimum_repetitions"],
        )

    def test_jsonl_results_round_trip(self) -> None:
        results = self.make_results()
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".jsonl",
            encoding="utf-8",
            delete=False,
        ) as handle:
            for result in results:
                handle.write(json.dumps(result) + "\n")
            path = Path(handle.name)
        try:
            loaded = eval_suite.load_results(path)
            summary = eval_suite.compute_summary(self.suite, loaded)
            self.assertEqual(summary["run_count"], len(results))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
