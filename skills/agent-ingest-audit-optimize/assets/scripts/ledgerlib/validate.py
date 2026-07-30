"""Every validator: one per ledger section, plus the cross-document checks."""

from __future__ import annotations

from ledgerlib.constants import (
    ARRAY_FIELDS,
    BACKLOG_CLASSIFICATIONS,
    BASELINE_ITEM_KINDS,
    BASELINE_ITEM_STATES,
    CLASSIFICATIONS,
    DATE,
    DIGEST,
    EVIDENCE_FIELDS,
    LEDGER_SCOPES,
    LINK_FIELDS,
    PROJECT_STATUSES,
    PROVISIONAL_ID,
    RECORD_ID,
    RECORD_SCOPES,
    RECORD_STATUSES,
    RECORD_TYPES,
    REQUIRED_BACKLOG_FIELDS,
    REQUIRED_BASELINE_FIELDS,
    REQUIRED_BASELINE_ITEM_FIELDS,
    REQUIRED_LEDGER_FIELDS,
    REQUIRED_PROJECT_FIELDS,
    REQUIRED_RECORD_FIELDS,
    REQUIRED_RUN_FIELDS,
    REQUIRED_TARGET_FIELDS,
    ROLLBACK_TEST_STATES,
    RUN_RESULTS,
    SCHEMA_VERSION,
    SEQUENCE_PREFIXES,
    TERMINAL_CLASSIFICATIONS,
)
from ledgerlib.paths import _path_key


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

    # ARRAY_FIELDS is ("known_projects", "records", "baselines", "backlog"):
    # every one of the four has an explicit elif arm below, so there is no
    # fifth case left for a trailing `else` to ever handle.
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
        elif field == "baselines":
            for index, entry in enumerate(data[field]):
                findings.extend(validate_baseline(entry, index, source=source))

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
            if "portable" in target and type(target["portable"]) is not bool:
                findings.append(f"{place} portable must be a boolean")

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
    elif "targets" not in reported:
        # Every target's shape is checked; the array's coverage cannot be.
        # Nothing in a ledger says how many files a run was supposed to touch,
        # so a RUN can name three targets for a fourteen-file change and pass.
        # The record must say so in the field built for exactly that admission.
        findings.append(
            f"{label} self_reported must name 'targets': verify checks each "
            "target's shape and can never check that the array covers what the "
            "run changed"
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

    if "pending_id_reconciliation" in record and type(record["pending_id_reconciliation"]) is not bool:
        findings.append(f"{label} pending_id_reconciliation must be a boolean")

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


def validate_baseline(entry: dict, index: int, *, source: str) -> list[str]:
    label = f"{source}: baselines[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be an object"]
    missing = REQUIRED_BASELINE_FIELDS - set(entry)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]

    findings: list[str] = []
    identifier = entry["id"]
    if (
        not isinstance(identifier, str)
        or not RECORD_ID.fullmatch(identifier)
        or _prefix_and_number(identifier)[0] != "BASE"
    ):
        findings.append(f"{label} has an invalid id: {identifier!r}")
    else:
        label = f"{source}: {identifier}"

    captured_on = entry["captured_on"]
    if not isinstance(captured_on, str) or not DATE.fullmatch(captured_on):
        findings.append(f"{label} captured_on must match YYYY-MM-DD")

    if not isinstance(entry["client"], str) or not entry["client"].strip():
        findings.append(f"{label} client must be a non-empty string")

    if type(entry["adapter_version"]) is not int or entry["adapter_version"] < 1:
        findings.append(f"{label} adapter_version must be an integer of at least 1")

    items = entry["items"]
    if not isinstance(items, list):
        findings.append(f"{label} items must be an array")
    else:
        for position, item in enumerate(items):
            place = f"{label} items[{position}]"
            if not isinstance(item, dict):
                findings.append(f"{place} must be an object")
                continue
            absent = REQUIRED_BASELINE_ITEM_FIELDS - set(item)
            if absent:
                findings.append(f"{place} missing fields: {sorted(absent)}")
                continue

            if not isinstance(item["kind"], str) or item["kind"] not in BASELINE_ITEM_KINDS:
                findings.append(f"{place} has an invalid kind: {item['kind']!r}")
            if not isinstance(item["name"], str) or not item["name"].strip():
                findings.append(f"{place} name must be a non-empty string")
            if not isinstance(item["anchor"], str) or not item["anchor"].strip():
                findings.append(f"{place} anchor must be a non-empty string")

            digest = item["digest"]
            if digest is not None and (
                not isinstance(digest, str) or not DIGEST.fullmatch(digest)
            ):
                findings.append(f"{place} digest must be a sha256 digest or null")

            if not isinstance(item["attributes"], dict):
                findings.append(f"{place} attributes must be an object")

            origin = item["origin"]
            if not (
                origin == "pre-existing"
                or (
                    isinstance(origin, str)
                    and RECORD_ID.fullmatch(origin)
                    and _prefix_and_number(origin)[0] == "PROP"
                )
            ):
                findings.append(f"{place} has an invalid origin: {origin!r}")

            if not isinstance(item["state"], str) or item["state"] not in BASELINE_ITEM_STATES:
                findings.append(f"{place} has an invalid state: {item['state']!r}")

            if "portable" in item and type(item["portable"]) is not bool:
                findings.append(f"{place} portable must be a boolean")

    return findings


def _prefix_and_number(identifier: str) -> tuple[str, int]:
    # identifier is RECORD_ID-valid and has already passed RECORD_ID.fullmatch(),
    # e.g., "PROP-2026-001" or "PROP-2026-001-P"
    parts = identifier.split("-")
    prefix = parts[0]
    number = int(parts[2])  # Skip year (parts[1]), use number (parts[2])
    return prefix, number


def validate_collection(
    documents: list[tuple[str, dict]],
    *,
    complete: bool = True,
    digests: dict[str, str] | None = None,
) -> list[str]:
    # complete=False skips link checks to avoid false dangling-link findings.
    findings: list[str] = []
    seen: dict[str, str] = {}
    declared: set[str] = set()
    authorities: list[str] = []
    all_records: list[tuple[str, dict]] = []
    # Highest number seen per prefix across the whole verified set, with the
    # identifier and the ledger that holds it, so the authority check below can
    # name where the id was actually spent.
    spent: dict[str, tuple[int, str, str]] = {}
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
            current_spent = spent.get(prefix)
            if current_spent is None or number > current_spent[0]:
                spent[prefix] = (number, identifier, source)

        # A baseline is just another identifier holder: its `id` competes for
        # the same BASE sequence slot a record's id would, so it feeds the
        # same per-document floor and authority-wide coverage below.
        baselines = data.get("baselines") if isinstance(data, dict) else None
        baselines = baselines if isinstance(baselines, list) else []
        for baseline in baselines:
            if not isinstance(baseline, dict):
                continue
            identifier = baseline.get("id")
            if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                continue
            prefix, number = _prefix_and_number(identifier)
            current = highest.get(prefix)
            if current is None or number > current[0]:
                highest[prefix] = (number, identifier)
            current_spent = spent.get(prefix)
            if current_spent is None or number > current_spent[0]:
                spent[prefix] = (number, identifier, source)

        sequences = data.get("sequences") if isinstance(data, dict) else None
        if isinstance(sequences, dict):
            for prefix, (number, highest_identifier) in highest.items():
                allocated = sequences.get(prefix)
                if type(allocated) is int and allocated < number + 1:
                    findings.append(
                        f"{source}: sequences.{prefix} is {allocated} but "
                        f"{highest_identifier} is already allocated"
                    )

    # The global ledger is the sole ID authority, and normally holds no records
    # of its own: every project-scoped record routes to a project ledger. So the
    # per-document rule above never relates the authority's allocation counter to
    # the ids it actually issued. Fold in the whole set.
    for source, data in documents:
        if not isinstance(data, dict) or data.get("id_authority") is not True:
            continue
        sequences = data.get("sequences")
        if not isinstance(sequences, dict):
            continue
        for prefix, (number, identifier, holder) in spent.items():
            if holder == source:
                continue  # the per-document rule already covers this one
            allocated = sequences.get(prefix)
            if type(allocated) is int and allocated < number + 1:
                findings.append(
                    f"{source}: sequences.{prefix} is {allocated} but the ID "
                    f"authority must cover {identifier}, allocated in {holder}"
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
                            f"{source}: {record.get('id')!r} links to an "
                            f"unknown record: {target!r}"
                        )

        # A backlog entry's id is a back-reference to the record whose evidence
        # produced the finding, not a unique key: one material routinely yields
        # several backlog entries, so duplicates are correct here. What is
        # checkable is that the record exists. Suppressed with the link checks
        # when the set is partial, for the same reason: the record may live in
        # the ledger that could not be read.
        for source, data in documents:
            backlog = data.get("backlog") if isinstance(data, dict) else None
            if not isinstance(backlog, list):
                continue
            for index, entry in enumerate(backlog):
                if not isinstance(entry, dict):
                    continue
                identifier = entry.get("id")
                if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                    continue  # validate_backlog_entry already reported the shape
                if identifier not in declared:
                    findings.append(
                        f"{source}: backlog[{index}] id {identifier!r} references "
                        "a record that exists in no verified ledger"
                    )

    if digests:
        for source, data in documents:
            projects = data.get("known_projects") if isinstance(data, dict) else None
            if not isinstance(projects, list):
                continue
            for index, entry in enumerate(projects):
                if not isinstance(entry, dict):
                    continue
                ledger_path = entry.get("ledger_path")
                recorded = entry.get("last_digest")
                if not isinstance(ledger_path, str) or not isinstance(recorded, str):
                    continue
                # A path that was not passed on the command line is not
                # comparable. Silence here means "not checked", never "correct".
                actual = digests.get(_path_key(ledger_path))
                if actual is None or actual == recorded:
                    continue
                findings.append(
                    f"{source}: known_projects[{index}] last_digest {recorded!r} "
                    f"does not match {ledger_path!r}, which hashes to {actual!r}"
                )

    if len(authorities) > 1:
        findings.append(
            f"More than one ledger claims ID authority: {sorted(authorities)}"
        )

    return findings
