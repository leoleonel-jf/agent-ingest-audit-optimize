"""The `verify` command: read every named ledger, validate it, report findings."""

from __future__ import annotations

import sys
from pathlib import Path

from ledgerlib.chain import INTACT, chain_head, verify_chain
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


def verify(
    paths: list[Path], *, chain: bool = False, expect_head: str | None = None
) -> int:
    """Validate every named ledger; optionally check its hash chain too.

    `chain` is opt-in, and that is a compatibility decision rather than a
    preference: every ledger written before the chain shipped is unchained,
    and reporting that by default would turn a clean run into a finding for
    every existing user. With the flag, `unchained` is a finding like any
    other -- the caller asked whether the chain holds, and "there is no chain"
    is the honest answer to that question.

    `expect_head` compares the chain's head against a digest the caller kept
    OUTSIDE the ledger. It is the only check here that survives an attacker
    who rewrote the whole file and re-sealed it, because it is the only input
    that did not come from the file.
    """
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

    if chain:
        for source, data in documents:
            rows, verdict = verify_chain(data)
            for row in rows:
                if row["reason"] is not None:
                    findings.append(
                        f"{source}: records[{row['position']}] "
                        f"{row['id']!r}: {row['reason']}"
                    )
            if expect_head is not None:
                head = chain_head(data)
                if head != expect_head:
                    findings.append(
                        f"{source}: chain head is {head!r} and {expect_head!r} "
                        "was expected: the chain was recomputed, or this is "
                        "not the ledger the head was recorded from"
                    )
            if verdict == INTACT and expect_head is None:
                print(f"{source}: chain {verdict}", file=sys.stderr)
    for line in (*findings, *errors):
        print(line, file=sys.stderr)

    if errors:
        return 2
    if findings:
        print(f"{len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"{len(paths)} ledger(s) validated")
    return 0
