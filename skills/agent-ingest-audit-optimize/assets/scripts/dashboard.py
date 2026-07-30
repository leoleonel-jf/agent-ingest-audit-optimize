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
PROVISIONAL_ID = re.compile(r"-P$")
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

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RESULTS = {
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "PARTIALLY VALIDATED",
    "NOT VALIDATED",
    "FAILED",
    "ROLLBACK COMPLETED",
}
ROLLBACK_TEST_STATES = {"NOT_TESTED", "PARTIAL", "PASSED", "FAILED"}
REQUIRED_RUN_FIELDS = {
    "proposal",
    "authorization",
    "result",
    "targets",
    "backup",
    "rollback",
    "self_reported",
}
REQUIRED_TARGET_FIELDS = {
    "anchor",
    "kind",
    "before_digest",
    "after_digest",
    "reversible",
    "residual_effect",
}

BACKLOG_CLASSIFICATIONS = {
    "REJECT",
    "NEEDS MORE EVIDENCE",
    "RISK EXCEEDS BENEFIT",
    "MONITOR",
    "TEST IN ISOLATION",
}
TERMINAL_CLASSIFICATIONS = {"OBSOLETE", "NOT APPLICABLE", "ALREADY IMPLEMENTED"}
REQUIRED_BACKLOG_FIELDS = {
    "id",
    "classification",
    "reason",
    "revisit_trigger",
    "revisit_after",
}
PROJECT_STATUSES = {"OK", "UNREACHABLE", "CHANGED_EXTERNALLY"}
REQUIRED_PROJECT_FIELDS = {
    "project_root",
    "ledger_path",
    "last_seen",
    "last_digest",
    "status",
}


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
    if not isinstance(data["ledger_id"], str) or len(data["ledger_id"]) < 1:
        findings.append(f"{source}: ledger_id must be a non-empty string")
    if not isinstance(data["scope"], str) or data["scope"] not in LEDGER_SCOPES:
        findings.append(f"{source}: invalid scope: {data['scope']!r}")
    if not isinstance(data["language"], str) or len(data["language"]) < 2:
        findings.append(f"{source}: language must be a string of at least 2 characters")
    if not isinstance(data["client"], str) or len(data["client"]) < 1:
        findings.append(f"{source}: client must be a non-empty string")
    # adapter_version deliberately uses `type(x) is not int` rather than
    # isinstance: bool is a subclass of int, so isinstance(True, int) is
    # True, which would let a boolean silently pass as a valid count.
    if type(data["adapter_version"]) is not int or data["adapter_version"] < 1:
        findings.append(f"{source}: adapter_version must be an integer of at least 1")
    for field in ("created", "updated"):
        value = data[field]
        if not isinstance(value, str) or not DATE.fullmatch(value):
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
        elif field == "backlog":
            for index, entry in enumerate(data[field]):
                findings.extend(validate_backlog_entry(entry, index, source=source))
        elif field == "known_projects":
            for index, entry in enumerate(data[field]):
                findings.extend(validate_known_project(entry, index, source=source))
        else:
            for index, element in enumerate(data[field]):
                if not isinstance(element, dict):
                    findings.append(
                        f"{source}: {field}[{index}] must be an object"
                    )

    return findings


def validate_run(record: dict, *, label: str) -> list[str]:
    findings: list[str] = []
    missing = REQUIRED_RUN_FIELDS - set(record)
    if missing:
        return [f"{label} is a RUN and is missing fields: {sorted(missing)}"]

    proposal = record["proposal"]
    if not isinstance(proposal, str) or not RECORD_ID.fullmatch(proposal):
        findings.append(f"{label} has an invalid proposal reference: {proposal!r}")

    authorization = record["authorization"]
    if not isinstance(authorization, dict):
        findings.append(f"{label} authorization must be an object")
    else:
        quote = authorization.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            findings.append(f"{label} authorization quote must be a non-empty string")
        recorded_on = authorization.get("recorded_on")
        if not isinstance(recorded_on, str) or not DATE.fullmatch(recorded_on):
            findings.append(f"{label} authorization.recorded_on must match YYYY-MM-DD")

    if not isinstance(record["result"], str) or record["result"] not in RUN_RESULTS:
        findings.append(f"{label} has an invalid result: {record['result']!r}")

    targets = record["targets"]
    if not isinstance(targets, list) or not targets:
        findings.append(f"{label} targets must be a non-empty array")
    else:
        for position, target in enumerate(targets):
            place = f"{label} targets[{position}]"
            if not isinstance(target, dict):
                findings.append(f"{place} must be an object")
                continue
            absent = REQUIRED_TARGET_FIELDS - set(target)
            if absent:
                findings.append(f"{place} missing fields: {sorted(absent)}")
                continue
            for field in ("before_digest", "after_digest"):
                value = target[field]
                if value is not None and (
                    not isinstance(value, str) or not DIGEST.fullmatch(value)
                ):
                    findings.append(f"{place} {field} must be a sha256 digest or null")
            if type(target["reversible"]) is not bool:
                findings.append(f"{place} reversible must be a boolean")
            elif not target["reversible"] and not target["residual_effect"]:
                findings.append(
                    f"{place} is not reversible and requires a residual_effect"
                )

    backup = record["backup"]
    if backup is not None:
        if not isinstance(backup, dict):
            findings.append(f"{label} backup must be an object or null")
        else:
            digest = backup.get("digest")
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                findings.append(f"{label} backup digest must be a sha256 digest")
            if type(backup.get("verified")) is not bool:
                findings.append(f"{label} backup verified must be a boolean")

    rollback = record["rollback"]
    if not isinstance(rollback, dict):
        findings.append(f"{label} rollback must be an object")
    elif (
        not isinstance(rollback.get("tested"), str)
        or rollback.get("tested") not in ROLLBACK_TEST_STATES
    ):
        findings.append(
            f"{label} rollback tested must be one of {sorted(ROLLBACK_TEST_STATES)}"
        )

    reported = record["self_reported"]
    if not isinstance(reported, list) or any(
        not isinstance(item, str) for item in reported
    ):
        findings.append(f"{label} self_reported must be an array of strings")

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

    if not isinstance(record["type"], str) or record["type"] not in RECORD_TYPES:
        findings.append(f"{label} has an invalid type: {record['type']!r}")
    if not isinstance(record["status"], str) or record["status"] not in RECORD_STATUSES:
        findings.append(f"{label} has an invalid status: {record['status']!r}")
    if (
        not isinstance(record["classification"], str)
        or record["classification"] not in CLASSIFICATIONS
    ):
        findings.append(
            f"{label} has an invalid classification: {record['classification']!r}"
        )
    if not isinstance(record["scope"], str) or record["scope"] not in RECORD_SCOPES:
        findings.append(f"{label} has an invalid scope: {record['scope']!r}")
    for field in ("title", "file"):
        if not isinstance(record[field], str) or not record[field].strip():
            findings.append(f"{label} {field} must be a non-empty string")
    for field in ("created", "updated"):
        value = record[field]
        if not isinstance(value, str) or not DATE.fullmatch(value):
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

    if record["type"] == "RUN":
        findings.extend(validate_run(record, label=label))

    return findings


def validate_backlog_entry(entry: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: backlog[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be an object"]
    missing = REQUIRED_BACKLOG_FIELDS - set(entry)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    findings: list[str] = []
    identifier = entry["id"]
    if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
        findings.append(f"{label} has an invalid id: {identifier!r}")
    else:
        label = f"{source}: backlog {identifier}"

    classification = entry["classification"]
    if not isinstance(classification, str):
        findings.append(f"{label} has an invalid classification: {classification!r}")
    elif classification in TERMINAL_CLASSIFICATIONS:
        findings.append(
            f"{label} uses the terminal classification {classification!r}, "
            "which never enters the backlog"
        )
    elif classification not in BACKLOG_CLASSIFICATIONS:
        findings.append(f"{label} has an invalid classification: {classification!r}")

    if not isinstance(entry["reason"], str) or not entry["reason"].strip():
        findings.append(f"{label} reason must be a non-empty string")

    # revisit_trigger mirrors the schema's `"type": ["string", "null"]`:
    # any other type (int, list, dict, ...) is a finding, independent of
    # the "at least one of trigger/date" rule below.
    revisit_trigger = entry["revisit_trigger"]
    if revisit_trigger is not None and not isinstance(revisit_trigger, str):
        findings.append(f"{label} revisit_trigger must be null or a string")

    # revisit_after is a date field like every other date in this ledger
    # (created, updated, verified_on, recorded_on): when present it must
    # match YYYY-MM-DD. Unlike those fields it is nullable — null means
    # "no date condition", which is legitimate as long as revisit_trigger
    # supplies the revisit condition instead.
    revisit_after = entry["revisit_after"]
    if revisit_after is not None and (
        not isinstance(revisit_after, str) or not DATE.fullmatch(revisit_after)
    ):
        findings.append(f"{label} revisit_after must be null or match YYYY-MM-DD")

    if not entry["revisit_trigger"] and not entry["revisit_after"]:
        findings.append(f"{label} requires a revisit_trigger or a revisit_after date")

    return findings


def validate_known_project(entry: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: known_projects[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be an object"]
    missing = REQUIRED_PROJECT_FIELDS - set(entry)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    findings: list[str] = []
    for field in ("project_root", "ledger_path"):
        if not isinstance(entry[field], str) or not entry[field].strip():
            findings.append(f"{label} {field} must be a non-empty string")

    # last_seen is a date field like created/updated/verified_on/recorded_on
    # elsewhere in this ledger, and unlike revisit_after it is not nullable.
    last_seen = entry["last_seen"]
    if not isinstance(last_seen, str) or not DATE.fullmatch(last_seen):
        findings.append(f"{label} last_seen must match YYYY-MM-DD")

    digest = entry["last_digest"]
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        findings.append(f"{label} last_digest must be a sha256 digest")
    if not isinstance(entry["status"], str) or entry["status"] not in PROJECT_STATUSES:
        findings.append(f"{label} has an invalid status: {entry['status']!r}")
    return findings


def _prefix_and_number(identifier: str) -> tuple[str, int]:
    # identifier is RECORD_ID-valid and has already passed RECORD_ID.fullmatch(),
    # e.g., "PROP-2026-001" or "PROP-2026-001-P"
    parts = identifier.split("-")
    prefix = parts[0]
    number = int(parts[2])  # Skip year (parts[1]), use number (parts[2])
    return prefix, number


def validate_collection(
    documents: list[tuple[str, dict]], *, complete: bool = True
) -> list[str]:
    # complete=False skips link checks to avoid false dangling-link findings.
    findings: list[str] = []
    seen: dict[str, str] = {}
    declared: set[str] = set()
    authorities: list[str] = []
    all_records: list[tuple[str, dict]] = []
    for source, data in documents:
        if isinstance(data, dict) and data.get("id_authority") is True:
            authorities.append(source)
        records = data.get("records") if isinstance(data, dict) else None
        # Maps prefix -> (highest number seen, identifier that set it), so
        # the sequence-drift finding below can name the record that
        # actually holds the high-water mark instead of whichever record
        # happened to be last in the `for record in records` loop.
        highest: dict[str, tuple[int, str]] = {}
        records = records if isinstance(records, list) else []
        for record in records:
            if not isinstance(record, dict):
                continue
            all_records.append((source, record))
            identifier = record.get("id")
            if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                continue
            if identifier in seen:
                findings.append(
                    f"Duplicate record id {identifier} in {source} and {seen[identifier]}"
                )
            else:
                seen[identifier] = source
            declared.add(identifier)
            reconciled = record.get("pending_id_reconciliation") is True
            if PROVISIONAL_ID.search(identifier) and not reconciled:
                findings.append(
                    f"{source}: {identifier} is provisional and requires "
                    "pending_id_reconciliation to be true"
                )
            prefix, number = _prefix_and_number(identifier)
            current = highest.get(prefix)
            if current is None or number > current[0]:
                highest[prefix] = (number, identifier)
        sequences = data.get("sequences") if isinstance(data, dict) else None
        if isinstance(sequences, dict):
            for prefix, (number, highest_identifier) in highest.items():
                allocated = sequences.get(prefix)
                if type(allocated) is int and allocated < number + 1:
                    findings.append(
                        f"{source}: sequences.{prefix} is {allocated} but "
                        f"{highest_identifier} is already allocated"
                    )

    if complete:
        for source, record in all_records:
            links = record.get("links")
            if not isinstance(links, dict):
                continue
            for field in LINK_FIELDS:
                targets = links.get(field)
                if not isinstance(targets, list):
                    continue
                for target in targets:
                    if isinstance(target, str) and target not in declared:
                        findings.append(
                            f"{source}: {record.get('id')} links to an "
                            f"unknown record: {target}"
                        )

    if len(authorities) > 1:
        findings.append(
            f"More than one ledger claims ID authority: {sorted(authorities)}"
        )

    return findings


def verify(paths: list[Path]) -> int:
    findings: list[str] = []
    documents: list[tuple[str, dict]] = []
    errors: list[str] = []

    for path in paths:
        source = str(path)
        try:
            data = load_json(path)
        except LedgerError as exc:
            errors.append(str(exc))
            continue
        findings.extend(validate_ledger(data, source=source))
        documents.append((source, data))

    findings.extend(validate_collection(documents, complete=not errors))
    for line in (*findings, *errors):
        print(line, file=sys.stderr)

    if errors:
        return 2
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

    if arguments.command == "verify":
        return verify(arguments.paths)


if __name__ == "__main__":
    sys.exit(main())
