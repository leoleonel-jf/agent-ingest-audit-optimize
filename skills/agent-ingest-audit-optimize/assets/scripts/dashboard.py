#!/usr/bin/env python3
"""Validate the agent-ingest-audit-optimize governance ledger.

`verify` validates one or more ledgers. `scan` reads one client's
configuration and emits a single `baselines[]` entry on stdout. `drift`
re-resolves a ledger's recorded anchors and classifies every baseline item
and run target against the environment now. `rollback-preview` reports the
four sets and the health indicator for one RUN record. All four are
read-only and write no file anywhere. `build` renders the ledger into a
self-contained `dashboard.html`: it is the one command here that writes a
file, and it writes exactly one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

# The bundle runs as a loose script under an interpreter no installer
# configured, and the test suite loads this file by path through
# `importlib.util`, which does not put the script's directory on `sys.path`.
# Put it there before importing `ledgerlib`, guarded against duplicate
# insertion because the suite loads this module more than once in one process.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Re-exported for compatibility: `dashboard` is the name every caller and the
# test suite already imports, and it keeps exporting every public name it did
# before the split. Explicit, never `import *`: a star import silently stops
# re-exporting a name the day one of these modules grows an `__all__`.
from ledgerlib.constants import (  # noqa: E402
    ANCHOR_NAME,
    ANCHOR_REFERENCE,
    ARRAY_FIELDS,
    BACKLOG_CLASSIFICATIONS,
    BASELINE_ITEM_KINDS,
    BASELINE_ITEM_STATES,
    CLASSIFICATIONS,
    DATE,
    DEVICE_NAME,
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
    ROLLBACK_INDICATORS,
    ROLLBACK_TEST_STATES,
    RUN_RESULTS,
    SCHEMA_VERSION,
    SEQUENCE_PREFIXES,
    TERMINAL_CLASSIFICATIONS,
)
from ledgerlib.errors import (  # noqa: E402
    PATH_SAFETY_REASONS,
    LedgerError,
    PathSafetyError,
)
from ledgerlib.paths import (  # noqa: E402
    _is_within,
    _path_key,
    _refuse_if_hardlinked,
    _resolve_or_raise,
    _validate_anchor_names,
    anchor_path,
    check_glob,
    file_digest,
    load_json,
    resolve_anchored,
)
from ledgerlib.build import (  # noqa: E402
    TEMPLATE_PATH,
    build_command,
    build_payload,
    inject_payload,
    serialize_payload,
    write_dashboard,
)
from ledgerlib.chain import (  # noqa: E402
    CHAIN_REASONS,
    CHAIN_VERDICTS,
    canonical_bytes,
    canonical_text,
    chain_command,
    chain_head,
    record_digest,
    seal_ledger,
    verify_chain,
)
from ledgerlib.compliance import (  # noqa: E402
    CAVEAT,
    EVIDENCE_ABSENT,
    EVIDENCE_PARTIAL,
    EVIDENCE_PRESENT,
    EVIDENCE_REASONS,
    EVIDENCE_STATES,
    compliance_command,
    compliance_report,
    evaluate_control,
    load_mapping,
)
from ledgerlib.lock import (  # noqa: E402
    LOCK_DIFFERENCES,
    LOCK_VERSION,
    build_lock,
    check_lock,
    lock_command,
    lockable_kinds,
    render_lock,
)
from ledgerlib.drift import (  # noqa: E402
    DRIFT_REASONS,
    classify_item,
    classify_target,
    drift_command,
    drift_report,
    resolved_path,
)
from ledgerlib.rollback import (  # noqa: E402
    BACKUP_REASONS,
    rollback_preview,
    rollback_preview_command,
)
from ledgerlib.scan import (  # noqa: E402
    PARSE_ERRORS,
    SCAN_REASONS,
    redact,
    run_probe,
    scan,
    scan_command,
)
from ledgerlib.validate import (  # noqa: E402
    _prefix_and_number,
    validate_backlog_entry,
    validate_baseline,
    validate_collection,
    validate_known_project,
    validate_ledger,
    validate_record,
    validate_run,
)
from ledgerlib.verify import verify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="validate one or more ledgers")
    verify_parser.add_argument("paths", nargs="+", type=Path)
    # Opt-in, for compatibility: every ledger written before the chain shipped
    # is unchained, and reporting that by default would turn a clean run into
    # a finding for every existing user.
    verify_parser.add_argument(
        "--chain",
        action="store_true",
        help="also verify each ledger's hash chain (tamper-evidence)",
    )
    verify_parser.add_argument(
        "--expect-head",
        dest="expect_head",
        default=None,
        help="the chain head digest recorded outside the ledger; the only "
        "check that survives a wholly recomputed chain. Requires --chain",
    )

    chain_parser = subparsers.add_parser(
        "chain",
        help="report the hash chain's head, or seal unchained records "
        "(--seal writes one file)",
    )
    chain_parser.add_argument("ledger", type=Path, help="the ledger to chain")
    chain_mode = chain_parser.add_mutually_exclusive_group(required=True)
    chain_mode.add_argument(
        "--head",
        action="store_true",
        help="print the head digest and nothing else, to be recorded outside "
        "the ledger",
    )
    chain_mode.add_argument(
        "--seal",
        action="store_true",
        help="write the chain onto records that lack it; refuses an invalid "
        "ledger and refuses to seal over a broken chain",
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help="read a client's configuration and emit one baselines[] entry (read-only)",
    )
    # Required, and not defaulted. Identifier allocation is a ledger concern
    # with rules about sequences and cross-scope collision; `scan` does not get
    # a second, private implementation of it.
    scan_parser.add_argument(
        "--id",
        dest="identifier",
        required=True,
        help="the BASE identifier for the entry, allocated from the ID authority",
    )
    scan_parser.add_argument(
        "--client", default=None, help="the client to scan; detected when omitted"
    )
    scan_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project root $PROJECT anchors to; the working directory when omitted",
    )
    scan_parser.add_argument(
        "--adapter",
        type=Path,
        default=None,
        help="an adapter file to use, overriding selection entirely",
    )
    scan_parser.add_argument(
        "--user-config",
        dest="user_config",
        type=Path,
        default=None,
        help="the configuration root user adapters are read from; skipped when omitted",
    )

    drift_parser = subparsers.add_parser(
        "drift",
        help="re-resolve a ledger's anchors and classify every baseline item "
        "and run target against the environment now (read-only)",
    )
    drift_parser.add_argument("ledger", type=Path, help="the ledger to classify")
    # No --client flag, on purpose: the ledger already names its client --
    # per entry for baselines, at the top level for run targets -- and a flag
    # overriding recorded provenance would classify one client's files under
    # another client's anchors.
    drift_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project root $PROJECT anchors to; the working directory when omitted",
    )
    drift_parser.add_argument(
        "--adapter",
        type=Path,
        default=None,
        help="an adapter file to use, overriding selection entirely",
    )
    drift_parser.add_argument(
        "--user-config",
        dest="user_config",
        type=Path,
        default=None,
        help="the configuration root user adapters are read from; skipped when omitted",
    )

    rollback_parser = subparsers.add_parser(
        "rollback-preview",
        help="report the four sets and the health indicator for one RUN "
        "record (read-only)",
    )
    rollback_parser.add_argument("ledger", type=Path, help="the ledger holding the run")
    rollback_parser.add_argument(
        "run_id",
        metavar="RUN-ID",
        help="the RUN record whose rollback is previewed",
    )
    # No --client flag, for the reason `drift` has none: the ledger's own
    # top-level client is the provenance run targets carry, and a flag
    # overriding it would preview one client's rollback under another
    # client's anchors.
    rollback_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project root $PROJECT anchors to; the working directory when omitted",
    )
    rollback_parser.add_argument(
        "--adapter",
        type=Path,
        default=None,
        help="an adapter file to use, overriding selection entirely",
    )
    rollback_parser.add_argument(
        "--user-config",
        dest="user_config",
        type=Path,
        default=None,
        help="the configuration root user adapters are read from; skipped when omitted",
    )

    lock_parser = subparsers.add_parser(
        "lock",
        help="pin the installable artifacts a baseline recorded, or check a "
        "lockfile against it",
    )
    lock_parser.add_argument("ledger", type=Path, help="the ledger to read")
    lock_mode = lock_parser.add_mutually_exclusive_group(required=True)
    lock_mode.add_argument(
        "--from",
        dest="baseline_id",
        default=None,
        help="the BASE identifier to pin from",
    )
    lock_mode.add_argument(
        "--check",
        type=Path,
        default=None,
        help="an existing lockfile to compare against the baseline it names; "
        "reads no file from the environment",
    )
    lock_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="where to write the lockfile; stdout when omitted",
    )
    lock_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite --out even if it does not look like a lockfile",
    )
    lock_parser.add_argument("--adapter", type=Path, default=None)
    lock_parser.add_argument(
        "--user-config", dest="user_config", type=Path, default=None
    )
    lock_parser.add_argument("--project", type=Path, default=None)

    compliance_parser = subparsers.add_parser(
        "compliance",
        help="inventory a ledger's evidence against one framework's controls "
        "(read-only unless --out is given)",
    )
    compliance_parser.add_argument("ledger", type=Path, help="the ledger to inventory")
    compliance_parser.add_argument(
        "--framework",
        required=True,
        help="the framework mapping to evaluate against, by bare name",
    )
    compliance_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write an evidence pack here: the report, a copy of each cited "
        "record, and a digest for each file",
    )
    compliance_parser.add_argument(
        "--force",
        action="store_true",
        help="write the evidence pack into a directory that is not empty",
    )

    build_parser = subparsers.add_parser(
        "build",
        help="render a ledger into a self-contained dashboard.html (writes one file)",
    )
    build_parser.add_argument("ledger", type=Path, help="the ledger to render")
    build_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="where to write the dashboard; defaults to dashboard.html beside the ledger",
    )
    build_parser.add_argument(
        "--lang",
        default=None,
        help="override the dashboard language; falls back to ledger.language, then 'en'",
    )
    build_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite --out even if it does not look like a generated dashboard",
    )
    # Mirrors `drift`'s flags exactly, for the reason `drift_parser` already
    # gives: `build_payload` re-resolves the ledger's anchors through
    # `drift_report` and `rollback_preview`, the same anchor-resolution layer
    # `drift` and `rollback-preview` use, so it needs the same selectors.
    build_parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="the project root $PROJECT anchors to; the working directory when omitted",
    )
    build_parser.add_argument(
        "--adapter",
        type=Path,
        default=None,
        help="an adapter file to use, overriding selection entirely",
    )
    build_parser.add_argument(
        "--user-config",
        dest="user_config",
        type=Path,
        default=None,
        help="the configuration root user adapters are read from; skipped when omitted",
    )

    arguments = parser.parse_args(argv)

    if arguments.command == "verify":
        if arguments.expect_head is not None and not arguments.chain:
            parser.error("--expect-head requires --chain")
        return verify(
            arguments.paths,
            chain=arguments.chain,
            expect_head=arguments.expect_head,
        )

    if arguments.command == "chain":
        return chain_command(
            ledger=arguments.ledger,
            head=arguments.head,
            seal=arguments.seal,
        )

    if arguments.command == "scan":
        return scan_command(
            identifier=arguments.identifier,
            client=arguments.client,
            adapter=arguments.adapter,
            user_config=arguments.user_config,
            project=arguments.project,
        )

    if arguments.command == "drift":
        return drift_command(
            ledger=arguments.ledger,
            adapter=arguments.adapter,
            user_config=arguments.user_config,
            project=arguments.project,
        )

    if arguments.command == "rollback-preview":
        return rollback_preview_command(
            ledger=arguments.ledger,
            run_id=arguments.run_id,
            adapter=arguments.adapter,
            user_config=arguments.user_config,
            project=arguments.project,
        )

    if arguments.command == "lock":
        return lock_command(
            ledger=arguments.ledger,
            baseline_id=arguments.baseline_id,
            check=arguments.check,
            out=arguments.out,
            force=arguments.force,
            adapter=arguments.adapter,
            user_config=arguments.user_config,
            project=arguments.project,
        )

    if arguments.command == "compliance":
        return compliance_command(
            ledger=arguments.ledger,
            framework=arguments.framework,
            out=arguments.out,
            force=arguments.force,
        )

    if arguments.command == "build":
        return build_command(
            ledger=arguments.ledger,
            out=arguments.out,
            lang=arguments.lang,
            force=arguments.force,
            adapter=arguments.adapter,
            user_config=arguments.user_config,
            project=arguments.project,
        )


if __name__ == "__main__":
    sys.exit(main())
