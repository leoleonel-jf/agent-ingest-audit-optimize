"""The `verify` command: read every named ledger, validate it, report findings."""

from __future__ import annotations

import sys
from pathlib import Path

from ledgerlib.errors import LedgerError
from ledgerlib.paths import (
    load_json,
    file_digest,
    _path_key,
)
from ledgerlib.validate import (
    validate_ledger,
    validate_collection,
)


def verify(paths: list[Path]) -> int:
    findings: list[str] = []
    documents: list[tuple[str, dict]] = []
    errors: list[str] = []
    digests: dict[str, str] = {}

    for path in paths:
        source = str(path)
        try:
            # load_json and file_digest each open the file independently, so
            # in principle the digest could describe different bytes than
            # the parsed document if the file changes between the two reads.
            # Accepted: a local validator run by the ledger's owner over
            # their own files has no privilege boundary to defend, and the
            # realistic outcome of that microsecond window is a spurious
            # finding that a re-run clears.
            data = load_json(path)
            digest = file_digest(path)
        except LedgerError as exc:
            errors.append(str(exc))
            continue
        except OSError as exc:
            errors.append(f"Unreadable ledger: {path}: {exc}")
            continue
        # Register both the path as given and its resolved form, so a ledger
        # that stores an absolute path still matches a relative invocation.
        digests[_path_key(source)] = digest
        digests[_path_key(str(path.resolve()))] = digest
        findings.extend(validate_ledger(data, source=source))
        documents.append((source, data))

    findings.extend(
        validate_collection(documents, complete=not errors, digests=digests)
    )
    for line in (*findings, *errors):
        print(line, file=sys.stderr)

    if errors:
        return 2
    if findings:
        print(f"{len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"{len(paths)} ledger(s) validated")
    return 0
