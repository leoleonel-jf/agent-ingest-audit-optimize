#!/usr/bin/env python3
"""Validate the agent-ingest-audit-optimize governance ledger.

`verify` validates one or more ledgers. `scan` reads one client's
configuration and emits a single `baselines[]` entry on stdout. `drift`
re-resolves a ledger's recorded anchors and classifies every baseline item
and run target against the environment now. Both are read-only and write no
file anywhere. Rollback preview and dashboard rendering arrive in later
phases.
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
from ledgerlib.drift import (  # noqa: E402
    DRIFT_REASONS,
    classify_item,
    classify_target,
    drift_command,
    drift_report,
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

    arguments = parser.parse_args(argv)

    if arguments.command == "verify":
        return verify(arguments.paths)

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


if __name__ == "__main__":
    sys.exit(main())
