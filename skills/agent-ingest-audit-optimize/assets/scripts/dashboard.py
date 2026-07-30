#!/usr/bin/env python3
"""Validate the agent-ingest-audit-optimize governance ledger.

Phase 0.2.0 implements the `verify` command only. Scanning, drift detection,
rollback preview, and dashboard rendering arrive in later phases.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SCHEMA_VERSION = "1.0"

REQUIRED_LEDGER_FIELDS = {
    "schema_version",
    "ledger_id",
    "scope",
    "language",
    "client",
    "adapter_version",
    "created",
    "updated",
    "id_authority",
    "sequences",
    "known_projects",
    "records",
    "baselines",
    "backlog",
}

SEQUENCE_PREFIXES = ("MAT", "PROP", "RUN", "ADR", "BASE")
LEDGER_SCOPES = {"global", "project"}
ARRAY_FIELDS = ("known_projects", "records", "baselines", "backlog")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LedgerError(RuntimeError):
    """Raised when a ledger cannot be read at all."""


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LedgerError(f"Missing ledger: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerError(f"Unreadable ledger: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LedgerError(f"Ledger must be a JSON object: {path}")
    return value


def validate_ledger(data: dict, *, source: str) -> list[str]:
    findings: list[str] = []
    missing = REQUIRED_LEDGER_FIELDS - set(data)
    if missing:
        findings.append(f"{source}: missing fields: {sorted(missing)}")
        return findings

    unknown = set(data) - REQUIRED_LEDGER_FIELDS
    if unknown:
        findings.append(f"{source}: unknown fields: {sorted(unknown)}")

    if data["schema_version"] != SCHEMA_VERSION:
        findings.append(
            f"{source}: unsupported schema_version: {data['schema_version']!r}"
        )
    if type(data["ledger_id"]) is not str or len(data["ledger_id"]) < 1:
        findings.append(f"{source}: ledger_id must be a non-empty string")
    if data["scope"] not in LEDGER_SCOPES:
        findings.append(f"{source}: invalid scope: {data['scope']!r}")
    if type(data["language"]) is not str or len(data["language"]) < 2:
        findings.append(f"{source}: language must be a string of at least 2 characters")
    if type(data["client"]) is not str or len(data["client"]) < 1:
        findings.append(f"{source}: client must be a non-empty string")
    if type(data["adapter_version"]) is not int or data["adapter_version"] < 1:
        findings.append(f"{source}: adapter_version must be an integer of at least 1")
    for field in ("created", "updated"):
        value = data[field]
        if type(value) is not str or not DATE.match(value):
            findings.append(f"{source}: {field} must match YYYY-MM-DD")
    if type(data["id_authority"]) is not bool:
        findings.append(f"{source}: id_authority must be a boolean")
    if data["scope"] == "global" and data.get("id_authority") is False:
        findings.append(f"{source}: the global ledger must be the ID authority")
    if data["scope"] == "project" and data.get("id_authority") is True:
        findings.append(f"{source}: a project ledger must not be the ID authority")

    sequences = data["sequences"]
    if not isinstance(sequences, dict):
        findings.append(f"{source}: sequences must be an object")
    else:
        for prefix in SEQUENCE_PREFIXES:
            value = sequences.get(prefix)
            if type(value) is not int or value < 0:
                findings.append(
                    f"{source}: sequences.{prefix} must be an integer of at least 0"
                )
        unexpected = set(sequences) - set(SEQUENCE_PREFIXES)
        if unexpected:
            findings.append(
                f"{source}: sequences has unexpected keys: {sorted(unexpected)}"
            )

    for field in ARRAY_FIELDS:
        if not isinstance(data[field], list):
            findings.append(f"{source}: {field} must be an array")

    return findings


def verify(paths: list[Path]) -> int:
    findings: list[str] = []
    for path in paths:
        try:
            data = load_json(path)
        except LedgerError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        findings.extend(validate_ledger(data, source=str(path)))
    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        print(f"{len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"{len(paths)} ledger(s) validated")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="validate one or more ledgers")
    verify_parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "verify":
            return verify(arguments.paths)
    except LedgerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
