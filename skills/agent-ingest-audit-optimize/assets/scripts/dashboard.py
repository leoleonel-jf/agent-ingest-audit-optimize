#!/usr/bin/env python3
"""Validate the agent-ingest-audit-optimize governance ledger.

`verify` is the only command implemented. Scanning, drift detection, rollback
preview, and dashboard rendering arrive in later phases.
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
    arguments = parser.parse_args(argv)

    if arguments.command == "verify":
        return verify(arguments.paths)


if __name__ == "__main__":
    sys.exit(main())
