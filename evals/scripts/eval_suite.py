#!/usr/bin/env python3
"""Validate and summarize the agent-ingest-audit-optimize evaluation suite."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "suite.json"
PROMPT_CLASSES = {"direct", "indirect", "incomplete", "negative", "boundary"}
CASE_KINDS = {
    "activation",
    "behavior",
    "safety",
    "authorization",
    "model-effort",
    "portability",
}
STATES = {"ANALYSIS", "DELIBERATION", "IMPLEMENTATION", "OUT_OF_SCOPE"}
REQUIRED_TASK_CATEGORIES = {
    "extraction",
    "research",
    "coding",
    "review",
    "planning",
    "tool-use",
    "high-stakes",
}
RESULT_REQUIRED_FIELDS = {
    "run_id",
    "case_id",
    "suite_version",
    "skill_commit",
    "platform",
    "config_id",
    "model",
    "effort",
    "cost_rank",
    "effort_rank",
    "repetition",
    "activated",
    "state",
    "mutation_count",
    "critical_checks",
    "quality_scores",
}
RESULT_OPTIONAL_FIELDS = {
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "resources_opened",
    "notes",
}


class SuiteError(ValueError):
    """Raised when the suite or a result violates the evaluation contract."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuiteError(f"File does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SuiteError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SuiteError(f"Expected a JSON object in {path}")
    return value


def resolve_contained(base: Path, relative: str, label: str) -> Path:
    candidate = (base / relative).resolve()
    resolved_base = base.resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise SuiteError(f"{label} escapes {resolved_base}: {relative}") from exc
    return candidate


def _valid_threshold(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def validate_suite(suite_path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    suite_path = suite_path.resolve()
    suite = load_json(suite_path)
    errors: list[str] = []

    for key in (
        "suite_id",
        "suite_version",
        "skill_path",
        "result_schema",
        "minimum_repetitions",
        "activation_thresholds",
        "task_categories",
        "critical_check_definitions",
        "cases",
    ):
        if key not in suite:
            errors.append(f"Missing suite field: {key}")

    if errors:
        raise SuiteError("\n".join(errors))

    if type(suite["minimum_repetitions"]) is not int or suite["minimum_repetitions"] < 2:
        errors.append("minimum_repetitions must be an integer of at least 2")

    activation_thresholds = suite["activation_thresholds"]
    for metric in ("precision", "recall", "negative_specificity"):
        if not _valid_threshold(activation_thresholds.get(metric)):
            errors.append(f"Invalid activation threshold: {metric}")

    categories = suite["task_categories"]
    if not isinstance(categories, dict):
        errors.append("task_categories must be an object")
        categories = {}
    missing_categories = REQUIRED_TASK_CATEGORIES - set(categories)
    if missing_categories:
        errors.append(f"Missing task categories: {sorted(missing_categories)}")
    for name, thresholds in categories.items():
        if not isinstance(thresholds, dict):
            errors.append(f"Task category {name} thresholds must be an object")
            continue
        for metric in ("minimum_quality", "minimum_pass_rate"):
            if not _valid_threshold(thresholds.get(metric)):
                errors.append(f"Invalid {metric} for task category {name}")

    checks = suite["critical_check_definitions"]
    if not isinstance(checks, dict) or not checks:
        errors.append("critical_check_definitions must be a non-empty object")
        checks = {}

    eval_root = suite_path.parent
    try:
        result_schema = resolve_contained(eval_root, suite["result_schema"], "result_schema")
        load_json(result_schema)
    except SuiteError as exc:
        errors.append(str(exc))

    repository_root = eval_root.parent
    try:
        skill_path = resolve_contained(repository_root, suite["skill_path"], "skill_path")
        if not (skill_path / "SKILL.md").is_file():
            errors.append(f"Skill path does not contain SKILL.md: {skill_path}")
    except SuiteError as exc:
        errors.append(str(exc))
        skill_path = repository_root

    cases = suite["cases"]
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty array")
        cases = []

    seen_ids: set[str] = set()
    seen_prompt_classes: set[str] = set()
    seen_categories: set[str] = set()
    positive_count = 0
    negative_count = 0

    required_case_fields = {
        "id",
        "title",
        "kind",
        "prompt_class",
        "task_category",
        "prompt",
        "fixture",
        "expected_activation",
        "expected_state",
        "mutation_allowed",
        "expected_resources",
        "critical_checks",
        "quality_criteria",
        "minimum_quality",
    }

    for index, case in enumerate(cases):
        label = f"case[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = required_case_fields - set(case)
        if missing:
            errors.append(f"{label} missing fields: {sorted(missing)}")
            continue

        case_id = case["id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Z]{3}-[0-9]{3}", case_id):
            errors.append(f"{label} has invalid id: {case_id!r}")
        elif case_id in seen_ids:
            errors.append(f"Duplicate case id: {case_id}")
        else:
            seen_ids.add(case_id)
        label = str(case_id)

        if case["kind"] not in CASE_KINDS:
            errors.append(f"{label} has invalid kind: {case['kind']}")
        if case["prompt_class"] not in PROMPT_CLASSES:
            errors.append(f"{label} has invalid prompt_class: {case['prompt_class']}")
        else:
            seen_prompt_classes.add(case["prompt_class"])
        if case["task_category"] not in categories:
            errors.append(f"{label} has unknown task_category: {case['task_category']}")
        else:
            seen_categories.add(case["task_category"])
        if not isinstance(case["prompt"], str) or not case["prompt"].strip():
            errors.append(f"{label} prompt must be non-empty")
        if type(case["expected_activation"]) is not bool:
            errors.append(f"{label} expected_activation must be boolean")
        elif case["expected_activation"]:
            positive_count += 1
        else:
            negative_count += 1
        if case["expected_state"] not in STATES:
            errors.append(f"{label} has invalid expected_state: {case['expected_state']}")
        if type(case["mutation_allowed"]) is not bool:
            errors.append(f"{label} mutation_allowed must be boolean")
        elif case["mutation_allowed"]:
            errors.append(f"{label} must remain read-only in this evaluation suite")
        if not _valid_threshold(case["minimum_quality"]):
            errors.append(f"{label} minimum_quality must be between 0 and 1")

        fixture = case["fixture"]
        if fixture is not None:
            if not isinstance(fixture, str) or not fixture:
                errors.append(f"{label} fixture must be null or a non-empty string")
            else:
                try:
                    fixture_path = resolve_contained(eval_root, fixture, f"{label} fixture")
                    if not fixture_path.is_file():
                        errors.append(f"{label} fixture does not exist: {fixture}")
                except SuiteError as exc:
                    errors.append(str(exc))

        resources = case["expected_resources"]
        if not isinstance(resources, list):
            errors.append(f"{label} expected_resources must be an array")
        else:
            for resource in resources:
                if not isinstance(resource, str) or not resource:
                    errors.append(f"{label} has invalid expected resource: {resource!r}")
                    continue
                try:
                    resource_path = resolve_contained(skill_path, resource, f"{label} resource")
                    if not resource_path.is_file():
                        errors.append(f"{label} resource does not exist: {resource}")
                except SuiteError as exc:
                    errors.append(str(exc))

        critical = case["critical_checks"]
        if not isinstance(critical, list) or not critical:
            errors.append(f"{label} critical_checks must be a non-empty array")
        else:
            for check in critical:
                if check not in checks:
                    errors.append(f"{label} references unknown critical check: {check}")

        criteria = case["quality_criteria"]
        if not isinstance(criteria, list) or not criteria:
            errors.append(f"{label} quality_criteria must be a non-empty array")
        else:
            criterion_ids: set[str] = set()
            weight_sum = 0.0
            for criterion in criteria:
                if not isinstance(criterion, dict):
                    errors.append(f"{label} quality criterion must be an object")
                    continue
                if set(("id", "description", "weight")) - set(criterion):
                    errors.append(f"{label} quality criterion is incomplete")
                    continue
                criterion_id = criterion["id"]
                if criterion_id in criterion_ids:
                    errors.append(f"{label} has duplicate quality criterion: {criterion_id}")
                criterion_ids.add(criterion_id)
                if not isinstance(criterion["description"], str) or not criterion["description"].strip():
                    errors.append(f"{label} criterion {criterion_id} has no description")
                if not _valid_threshold(criterion["weight"]) or criterion["weight"] <= 0:
                    errors.append(f"{label} criterion {criterion_id} has invalid weight")
                else:
                    weight_sum += float(criterion["weight"])
            if not math.isclose(weight_sum, 1.0, abs_tol=1e-9):
                errors.append(f"{label} quality weights sum to {weight_sum}, expected 1.0")

    if seen_prompt_classes != PROMPT_CLASSES:
        errors.append(f"Prompt class coverage mismatch: found {sorted(seen_prompt_classes)}")
    if seen_categories != set(categories):
        errors.append(f"Task category coverage mismatch: found {sorted(seen_categories)}")
    if positive_count == 0 or negative_count == 0:
        errors.append("Suite must contain both positive and negative activation cases")

    if errors:
        raise SuiteError("\n".join(errors))
    return suite


def load_results(path: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SuiteError(f"Results file does not exist: {path}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuiteError(f"Invalid JSON on results line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise SuiteError(f"Result on line {line_number} must be an object")
        results.append(value)
    if not results:
        raise SuiteError("Results file contains no runs")
    return results


def _case_map(suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["id"]: case for case in suite["cases"]}


def validate_results(suite: dict[str, Any], results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    checked = list(results)
    cases = _case_map(suite)
    config_metadata: dict[str, tuple[Any, ...]] = {}
    run_ids: set[str] = set()
    errors: list[str] = []

    for index, result in enumerate(checked):
        label = f"result[{index}]"
        missing = RESULT_REQUIRED_FIELDS - set(result)
        if missing:
            errors.append(f"{label} missing fields: {sorted(missing)}")
            continue
        extra = set(result) - RESULT_REQUIRED_FIELDS - RESULT_OPTIONAL_FIELDS
        if extra:
            errors.append(f"{label} has unsupported fields: {sorted(extra)}")
        case_id = result["case_id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Z]{3}-[0-9]{3}", case_id):
            errors.append(f"{label} has invalid case_id")
            continue
        case = cases.get(case_id)
        if case is None:
            errors.append(f"{label} references unknown case: {case_id}")
            continue
        label = str(result["run_id"])
        if not isinstance(result["run_id"], str) or not result["run_id"]:
            errors.append(f"result[{index}] run_id must be non-empty")
        elif result["run_id"] in run_ids:
            errors.append(f"Duplicate run_id: {result['run_id']}")
        else:
            run_ids.add(result["run_id"])
        if result["suite_version"] != suite["suite_version"]:
            errors.append(f"{label} has wrong suite_version")
        metadata_valid = True
        for key in ("skill_commit", "platform", "config_id", "model", "effort"):
            if not isinstance(result[key], str) or not result[key]:
                errors.append(f"{label} {key} must be non-empty")
                metadata_valid = False
        for key in ("cost_rank", "effort_rank", "repetition", "mutation_count"):
            if type(result[key]) is not int or result[key] < (0 if key == "mutation_count" else 1):
                errors.append(f"{label} {key} has invalid value")
                metadata_valid = False
        if type(result["activated"]) is not bool:
            errors.append(f"{label} activated must be boolean")
        if result["state"] not in STATES:
            errors.append(f"{label} has invalid state")
        if not isinstance(result["critical_checks"], dict):
            errors.append(f"{label} critical_checks must be an object")
        else:
            for check in case["critical_checks"]:
                if type(result["critical_checks"].get(check)) is not bool:
                    errors.append(f"{label} is missing boolean critical check {check}")
        if not isinstance(result["quality_scores"], dict):
            errors.append(f"{label} quality_scores must be an object")
        else:
            for criterion in case["quality_criteria"]:
                score = result["quality_scores"].get(criterion["id"])
                if not _valid_threshold(score):
                    errors.append(f"{label} has invalid quality score {criterion['id']}")

        if metadata_valid:
            metadata = (
                result["model"],
                result["effort"],
                result["cost_rank"],
                result["effort_rank"],
                result["platform"],
            )
            previous = config_metadata.setdefault(result["config_id"], metadata)
            if previous != metadata:
                errors.append(f"{label} changes metadata for config_id {result['config_id']}")

    if errors:
        raise SuiteError("\n".join(errors))
    return checked


def score_run(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    activation_correct = result["activated"] == case["expected_activation"]
    state_correct = result["state"] == case["expected_state"]
    mutation_ok = case["mutation_allowed"] or result["mutation_count"] == 0
    failed_critical = [
        check for check in case["critical_checks"] if not result["critical_checks"][check]
    ]
    quality = sum(
        result["quality_scores"][criterion["id"]] * criterion["weight"]
        for criterion in case["quality_criteria"]
    )
    passed = (
        activation_correct
        and state_correct
        and mutation_ok
        and not failed_critical
        and quality >= case["minimum_quality"]
    )
    return {
        "activation_correct": activation_correct,
        "state_correct": state_correct,
        "mutation_ok": mutation_ok,
        "failed_critical": failed_critical,
        "quality": quality,
        "passed": passed,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def activation_metrics(
    suite: dict[str, Any], results: Iterable[dict[str, Any]]
) -> dict[str, float | int | None]:
    cases = _case_map(suite)
    true_positive = false_positive = true_negative = false_negative = 0
    for result in results:
        expected = cases[result["case_id"]]["expected_activation"]
        actual = result["activated"]
        if expected and actual:
            true_positive += 1
        elif expected and not actual:
            false_negative += 1
        elif not expected and actual:
            false_positive += 1
        else:
            true_negative += 1
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "false_negative": false_negative,
        "precision": _ratio(true_positive, true_positive + false_positive),
        "recall": _ratio(true_positive, true_positive + false_negative),
        "negative_specificity": _ratio(true_negative, true_negative + false_positive),
    }


def _meets(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def compute_summary(
    suite: dict[str, Any], results: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    checked = validate_results(suite, results)
    cases = _case_map(suite)
    by_config: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in checked:
        by_config[result["config_id"]].append(result)

    config_summaries: dict[str, Any] = {}
    category_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    activation_limits = suite["activation_thresholds"]

    for config_id, config_results in sorted(by_config.items()):
        first = config_results[0]
        config_activation = activation_metrics(suite, config_results)
        activation_eligible = all(
            _meets(config_activation[metric], activation_limits[metric])
            for metric in ("precision", "recall", "negative_specificity")
        )
        category_summaries: dict[str, Any] = {}

        for category, thresholds in suite["task_categories"].items():
            category_case_ids = {
                case["id"] for case in suite["cases"] if case["task_category"] == category
            }
            category_results = [
                result
                for result in config_results
                if result["case_id"] in category_case_ids
            ]
            counts = Counter(result["case_id"] for result in category_results)
            coverage = _ratio(len(counts), len(category_case_ids)) or 0.0
            minimum_repetitions = min(
                (counts.get(case_id, 0) for case_id in category_case_ids),
                default=0,
            )
            scored = [
                score_run(cases[result["case_id"]], result) for result in category_results
            ]
            mean_quality = (
                statistics.fmean(item["quality"] for item in scored) if scored else None
            )
            pass_rate = (
                statistics.fmean(1.0 if item["passed"] else 0.0 for item in scored)
                if scored
                else None
            )
            critical_failures = sum(
                len(item["failed_critical"]) + (0 if item["mutation_ok"] else 1)
                for item in scored
            )
            latency_values = [
                result["latency_ms"]
                for result in category_results
                if isinstance(result.get("latency_ms"), (int, float))
            ]
            token_values = [
                result.get("input_tokens", 0) + result.get("output_tokens", 0)
                for result in category_results
                if isinstance(result.get("input_tokens"), int)
                and isinstance(result.get("output_tokens"), int)
            ]
            eligible = (
                activation_eligible
                and coverage == 1.0
                and minimum_repetitions >= suite["minimum_repetitions"]
                and mean_quality is not None
                and mean_quality >= thresholds["minimum_quality"]
                and pass_rate is not None
                and pass_rate >= thresholds["minimum_pass_rate"]
                and critical_failures == 0
            )
            summary = {
                "coverage": coverage,
                "minimum_repetitions": minimum_repetitions,
                "mean_quality": mean_quality,
                "pass_rate": pass_rate,
                "critical_failures": critical_failures,
                "median_latency_ms": statistics.median(latency_values)
                if latency_values
                else None,
                "median_tokens": statistics.median(token_values)
                if token_values
                else None,
                "eligible": eligible,
            }
            category_summaries[category] = summary
            if eligible:
                category_candidates[category].append(
                    {
                        "config_id": config_id,
                        "model": first["model"],
                        "effort": first["effort"],
                        "cost_rank": first["cost_rank"],
                        "effort_rank": first["effort_rank"],
                        **summary,
                    }
                )

        config_summaries[config_id] = {
            "platform": first["platform"],
            "model": first["model"],
            "effort": first["effort"],
            "cost_rank": first["cost_rank"],
            "effort_rank": first["effort_rank"],
            "activation": config_activation,
            "activation_eligible": activation_eligible,
            "categories": category_summaries,
        }

    selected: dict[str, Any] = {}
    for category in suite["task_categories"]:
        candidates = category_candidates.get(category, [])
        if not candidates:
            selected[category] = None
            continue
        selected[category] = min(
            candidates,
            key=lambda item: (
                item["cost_rank"],
                item["effort_rank"],
                item["median_latency_ms"]
                if item["median_latency_ms"] is not None
                else math.inf,
                item["median_tokens"] if item["median_tokens"] is not None else math.inf,
                item["config_id"],
            ),
        )

    return {
        "suite_id": suite["suite_id"],
        "suite_version": suite["suite_version"],
        "run_count": len(checked),
        "configurations": config_summaries,
        "selected_by_task_category": selected,
    }


def print_human_summary(summary: dict[str, Any]) -> None:
    print(
        f"Suite {summary['suite_id']} {summary['suite_version']}: "
        f"{summary['run_count']} runs"
    )
    for category, selection in summary["selected_by_task_category"].items():
        if selection is None:
            print(f"{category}: NO ELIGIBLE CONFIGURATION")
        else:
            print(
                f"{category}: {selection['config_id']} "
                f"(model={selection['model']}, effort={selection['effort']}, "
                f"quality={selection['mean_quality']:.3f}, "
                f"pass_rate={selection['pass_rate']:.3f})"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        type=Path,
        default=DEFAULT_SUITE,
        help="Path to suite.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate the suite and its resources")
    summarize = subparsers.add_parser("summarize", help="Summarize JSONL run results")
    summarize.add_argument("--results", type=Path, required=True)
    summarize.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        suite = validate_suite(args.suite)
        if args.command == "validate":
            print(
                f"Suite is valid: {len(suite['cases'])} cases, "
                f"{len(suite['task_categories'])} task categories"
            )
            return 0
        results = load_results(args.results)
        summary = compute_summary(suite, results)
        if args.as_json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print_human_summary(summary)
        return 0
    except SuiteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
