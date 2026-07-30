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

RECORD_ID = re.compile(r"^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$")
RECORD_TYPES = {"MATERIAL", "PROPOSAL", "RUN", "ADR", "BASELINE"}
RECORD_STATUSES = {
    "ANALYZED",
    "PROPOSED",
    "DECIDED",
    "IMPLEMENTED",
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "NOT IMPLEMENTED",
    "PENDING",
    "ROLLBACK",
    "SUPERSEDED",
}
CLASSIFICATIONS = {
    "ADOPT GLOBALLY",
    "ADOPT AS A DEFAULT FOR NEW PROJECTS",
    "MIGRATE EXISTING PROJECTS",
    "ADOPT LOCALLY",
    "TEST IN ISOLATION",
    "ADAPT",
    "MONITOR",
    "REJECT",
    "OBSOLETE",
    "ALREADY IMPLEMENTED",
    "NOT APPLICABLE",
    "NEEDS MORE EVIDENCE",
    "RISK EXCEEDS BENEFIT",
}
RECORD_SCOPES = {
    "session",
    "project",
    "workspace",
    "user-global",
    "organization",
    "fleet",
}
LINK_FIELDS = ("materials", "runs", "adrs")
REQUIRED_RECORD_FIELDS = {
    "id",
    "type",
    "title",
    "status",
    "classification",
    "scope",
    "created",
    "updated",
    "file",
    "links",
    "evidence",
}
EVIDENCE_FIELDS = {"source", "kind", "verified_on", "time_sensitive"}


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
    unknown = set(data) - REQUIRED_LEDGER_FIELDS
    if missing:
        findings.append(f"{source}: missing fields: {sorted(missing)}")
    if unknown:
        findings.append(f"{source}: unknown fields: {sorted(unknown)}")
    if missing:
        return findings

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
        if type(value) is not str or not DATE.fullmatch(value):
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
        elif field == "records":
            for index, record in enumerate(data[field]):
                findings.extend(validate_record(record, index, source=source))
        else:
            for index, element in enumerate(data[field]):
                if not isinstance(element, dict):
                    findings.append(
                        f"{source}: {field}[{index}] must be an object"
                    )

    return findings


def validate_record(record: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: records[{index}]"
    findings: list[str] = []
    if not isinstance(record, dict):
        return [f"{label} must be an object"]

    missing = REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    identifier = record["id"]
    if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
        findings.append(f"{label} has an invalid id: {identifier!r}")
    else:
        label = f"{source}: {identifier}"

    if record["type"] not in RECORD_TYPES:
        findings.append(f"{label} has an invalid type: {record['type']!r}")
    if record["status"] not in RECORD_STATUSES:
        findings.append(f"{label} has an invalid status: {record['status']!r}")
    if record["classification"] not in CLASSIFICATIONS:
        findings.append(
            f"{label} has an invalid classification: {record['classification']!r}"
        )
    if record["scope"] not in RECORD_SCOPES:
        findings.append(f"{label} has an invalid scope: {record['scope']!r}")
    for field in ("title", "file"):
        if not isinstance(record[field], str) or not record[field].strip():
            findings.append(f"{label} {field} must be a non-empty string")
    for field in ("created", "updated"):
        value = record[field]
        if type(value) is not str or not DATE.fullmatch(value):
            findings.append(f"{label} {field} must match YYYY-MM-DD")

    links = record["links"]
    if not isinstance(links, dict):
        findings.append(f"{label} links must be an object")
    else:
        for field in LINK_FIELDS:
            targets = links.get(field, [])
            if not isinstance(targets, list):
                findings.append(f"{label} links.{field} must be an array")
                continue
            for target in targets:
                if not isinstance(target, str) or not RECORD_ID.fullmatch(target):
                    findings.append(f"{label} links.{field} has an invalid id: {target!r}")

    evidence = record["evidence"]
    if not isinstance(evidence, list):
        findings.append(f"{label} evidence must be an array")
    else:
        for position, item in enumerate(evidence):
            if not isinstance(item, dict):
                findings.append(f"{label} evidence[{position}] must be an object")
                continue
            absent = EVIDENCE_FIELDS - set(item)
            if absent:
                findings.append(
                    f"{label} evidence[{position}] missing fields: {sorted(absent)}"
                )
                continue
            if type(item["time_sensitive"]) is not bool:
                findings.append(
                    f"{label} evidence[{position}] time_sensitive must be a boolean"
                )
            elif item["time_sensitive"]:
                expires_on = item.get("expires_on")
                if not isinstance(expires_on, str) or not expires_on.strip():
                    findings.append(
                        f"{label} evidence[{position}] is time_sensitive and requires expires_on"
                    )

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


def main(argv: list[str] | None = None) -> int:
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
