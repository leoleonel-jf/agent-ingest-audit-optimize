"""Mapping ledger artifacts to regulatory controls -- as evidence, never as a claim.

The EU AI Act's high-risk obligations apply from 2026-08-02, and its operative
articles describe almost literally what this ledger already produces: dated
records of what was decided and done (art. 11), automatic event logging over
the lifetime (art. 12), documented human oversight (art. 13, and the
`authorization.quote` this tool records in the user's own words IS that
artifact), and log retention (art. 19). ISO/IEC 42001 Annex A maps onto the
same material. What was missing was the dictionary from record to control.

**The rule this module exists under.** It never claims compliance. It reports
whether an artifact corresponding to a control exists, and names the records
that are the evidence or the ones that are missing. The distinction is not
stylistic: compliance is an auditor's judgement about an entire system, and a
tool that declared it would be lying about its own competence -- exactly the
error the `SELF-REPORTED` marker already prevents on the dashboard. The
vocabulary has three values and none of them is "compliant".

**Mappings are declared data**, one file per framework, exactly as adapters
are. Adding a framework must never require changing this file. A mapping
carries `expires_on` because regulatory text moves and a stale mapping reads
as current, which is worse than none at all.

**A mapping is content, and content never becomes code.** The predicate is a
tiny closed structure -- `collection`, `where`, `min_count`, `every`, `field`,
`non_empty` -- evaluated by the code below. Nothing from a mapping file is
executed, evaluated, or interpolated. This is the same boundary the path-safety
layer defends for paths.

Nothing here deletes anything. Retention is reported against the framework's
window and never applied: an audit tool that pruned its own records on a
schedule would be a contradiction in terms.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from collections.abc import Mapping as MappingABC
from pathlib import Path

from ledgerlib.constants import DATE
from ledgerlib.errors import LedgerError
from ledgerlib.paths import load_json


EVIDENCE_PRESENT = "EVIDENCE_PRESENT"
EVIDENCE_PARTIAL = "EVIDENCE_PARTIAL"
EVIDENCE_ABSENT = "EVIDENCE_ABSENT"

EVIDENCE_STATES = frozenset({EVIDENCE_PRESENT, EVIDENCE_PARTIAL, EVIDENCE_ABSENT})

# The reasons this module attaches, following `DRIFT_REASONS`: a closed set of
# stable strings, never an exception's own text.
EVIDENCE_REASONS = frozenset(
    {
        "unknown_collection",
        "no_predicate",
        "nothing_to_evidence",
        "below_minimum",
        "field_missing_or_empty",
    }
)

# The collections a control may be written against. Closed on purpose: a
# mapping naming anything else is answered `unknown_collection` rather than
# reaching into arbitrary ledger structure.
COLLECTIONS = frozenset({"records", "baselines", "backlog", "known_projects"})

REQUIRED_MAPPING_FIELDS = frozenset(
    {
        "mapping_version",
        "framework",
        "title",
        "expires_on",
        "source",
        "verified_on",
        "controls",
    }
)

BUNDLED_MAPPINGS = Path(__file__).resolve().parent.parent.parent / "compliance"

CAVEAT = (
    "This report inventories evidence; it does not certify compliance. "
    "Whether each artifact is sufficient is the auditor's judgement."
)

CAVEAT_PT = (
    "Este relatório inventaria evidência; não certifica conformidade. "
    "A suficiência de cada artefato é julgamento do auditor."
)


def load_mapping(path: Path, *, today: str | None = None) -> dict:
    """Read and validate one framework mapping, or raise `LedgerError`.

    Validation mirrors `load_adapter`: findings are raised as one exception,
    because a caller holding a broken mapping has nothing to proceed with.
    An expired mapping is refused rather than warned about -- the whole point
    of a mapping is that somebody checked it against the text on a date, and
    once that date is behind the window the check no longer stands.
    """
    stamp = datetime.date.today().isoformat() if today is None else today
    document = load_json(path)

    missing = REQUIRED_MAPPING_FIELDS - set(document)
    if missing:
        raise LedgerError(f"{path}: mapping missing fields: {sorted(missing)}")

    expires_on = document["expires_on"]
    if not isinstance(expires_on, str) or not DATE.fullmatch(expires_on):
        raise LedgerError(f"{path}: expires_on must match YYYY-MM-DD")
    if stamp > expires_on:
        raise LedgerError(
            f"{path}: mapping expired on {expires_on!r} and this run is dated "
            f"{stamp!r}: its controls were checked against the published text "
            "before that date and may no longer describe it. Re-verify the "
            "mapping against the source before relying on it."
        )

    verified_on = document["verified_on"]
    if not isinstance(verified_on, str) or not DATE.fullmatch(verified_on):
        raise LedgerError(f"{path}: verified_on must match YYYY-MM-DD")
    if not isinstance(document["source"], str) or not document["source"]:
        raise LedgerError(f"{path}: source must be a non-empty string")

    controls = document["controls"]
    if not isinstance(controls, list) or not controls:
        raise LedgerError(f"{path}: controls must be a non-empty array")
    for index, control in enumerate(controls):
        if not isinstance(control, dict):
            raise LedgerError(f"{path}: controls[{index}] must be an object")
        for field in ("id", "title", "requires"):
            if field not in control:
                raise LedgerError(f"{path}: controls[{index}] missing {field!r}")
        if not isinstance(control["requires"], dict):
            raise LedgerError(f"{path}: controls[{index}] requires must be an object")

    return document


def _field(entry: object, path: object) -> object:
    """Walk a dotted field path. Anything unwalkable is `None`, never a raise.

    The path is a string from a mapping file, so it is split and looked up --
    never resolved through `getattr`, never formatted into anything.
    """
    if not isinstance(path, str) or not path:
        return None
    current: object = entry
    for part in path.split("."):
        if not isinstance(current, MappingABC):
            return None
        current = current.get(part)
    return current


def _non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _matches(entry: object, where: object) -> bool:
    if not isinstance(where, MappingABC):
        return True
    for key, expected in where.items():
        if _field(entry, key) != expected:
            return False
    return True


def _identifier(entry: object) -> str | None:
    value = _field(entry, "id")
    return value if isinstance(value, str) else None


def evaluate_control(control: MappingABC, ledger: MappingABC) -> dict:
    """One control against one ledger. Returns a row; never raises.

    Semantics, stated because a later refactor could invert them silently:

    - `min_count` -- `EVIDENCE_PRESENT` when enough entries match,
      `EVIDENCE_PARTIAL` when some do but not enough, `EVIDENCE_ABSENT` when
      none do.
    - `every` -- over the matched set. All pass is `EVIDENCE_PRESENT`, some
      pass is `EVIDENCE_PARTIAL` naming the failures, none pass is
      `EVIDENCE_ABSENT`.
    - An `every` over an EMPTY matched set is `EVIDENCE_ABSENT`, never
      present. "All zero runs recorded an authorization" is vacuously true and
      worth nothing; a control with nothing to evidence has no evidence.
    """
    requires = control.get("requires")
    row: dict = {
        "id": control.get("id"),
        "title": control.get("title"),
        "note": control.get("note"),
        "state": EVIDENCE_ABSENT,
        "reason": None,
        "matched": 0,
        "evidence": [],
        "failing": [],
    }
    if not isinstance(requires, MappingABC):
        row["reason"] = "no_predicate"
        return row

    collection = requires.get("collection")
    if collection not in COLLECTIONS:
        row["reason"] = "unknown_collection"
        return row

    entries = ledger.get(collection) if isinstance(ledger, MappingABC) else None
    entries = entries if isinstance(entries, list) else []
    matched = [entry for entry in entries if _matches(entry, requires.get("where"))]
    row["matched"] = len(matched)
    row["evidence"] = [
        identifier for identifier in (_identifier(entry) for entry in matched)
        if identifier is not None
    ]

    every = requires.get("every")
    if isinstance(every, MappingABC):
        failing = [
            entry for entry in matched
            if not _non_empty(_field(entry, every.get("field")))
        ]
        row["failing"] = [
            identifier for identifier in (_identifier(entry) for entry in failing)
            if identifier is not None
        ]
        if not matched:
            row["reason"] = "nothing_to_evidence"
            return row
        if not failing:
            row["state"] = EVIDENCE_PRESENT
            return row
        row["reason"] = "field_missing_or_empty"
        row["state"] = (
            EVIDENCE_ABSENT if len(failing) == len(matched) else EVIDENCE_PARTIAL
        )
        return row

    minimum = requires.get("min_count")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        if len(matched) >= minimum:
            row["state"] = EVIDENCE_PRESENT
            return row
        row["reason"] = "below_minimum" if matched else "nothing_to_evidence"
        row["state"] = EVIDENCE_PARTIAL if matched else EVIDENCE_ABSENT
        return row

    row["reason"] = "no_predicate"
    return row


def _oldest_record(ledger: MappingABC) -> str | None:
    records = ledger.get("records") if isinstance(ledger, MappingABC) else None
    dates = [
        entry.get("created")
        for entry in (records if isinstance(records, list) else [])
        if isinstance(entry, MappingABC) and isinstance(entry.get("created"), str)
    ]
    return min(dates) if dates else None


def compliance_report(
    ledger: dict,
    *,
    framework: str,
    bundled: Path | None = None,
    today: str | None = None,
    lang: str | None = None,
) -> tuple[dict, list[str], int]:
    """Inventory one ledger's evidence against one framework.

    Returns `(report, messages, code)` on `drift_report`'s contract: `0` when
    no control is `EVIDENCE_ABSENT`, `1` otherwise. A tool error -- an unknown,
    invalid or expired mapping -- is raised as `LedgerError`, and the command
    wrapper is the one place that turns it into `2`.
    """
    if not isinstance(ledger, dict):
        raise LedgerError("ledger must be a JSON object")

    root = BUNDLED_MAPPINGS if bundled is None else bundled
    stamp = datetime.date.today().isoformat() if today is None else today

    if not isinstance(framework, str) or "/" in framework or "\\" in framework:
        raise LedgerError(f"framework must be a bare name: {framework!r}")
    path = root / f"{framework}.json"
    if not path.is_file():
        available = sorted(child.stem for child in root.glob("*.json"))
        raise LedgerError(
            f"no mapping for framework {framework!r}; available: {available}"
        )

    mapping = load_mapping(path, today=stamp)
    controls = [evaluate_control(control, ledger) for control in mapping["controls"]]

    oldest = _oldest_record(ledger)
    required_days = mapping.get("retention_days")
    retention = {
        "required_days": required_days if isinstance(required_days, int) else None,
        "oldest_record": oldest,
        # Reported, never applied. Nothing in this module removes a record,
        # and a test asserts the absence of any deletion call.
        "note": "retention is reported, not enforced",
    }

    caveat = CAVEAT_PT if (lang or ledger.get("language")) == "pt-BR" else CAVEAT
    report = {
        "framework": mapping["framework"],
        "title": mapping["title"],
        "source": mapping["source"],
        "verified_on": mapping["verified_on"],
        "evaluated_on": stamp,
        "caveat": caveat,
        "controls": controls,
        "retention": retention,
    }

    messages = [caveat]
    absent = [row for row in controls if row["state"] == EVIDENCE_ABSENT]
    for row in absent:
        messages.append(
            f"{row['id']}: {EVIDENCE_ABSENT} ({row['reason']})"
            + (f" -- records: {row['failing']}" if row["failing"] else "")
        )
    return report, messages, 1 if absent else 0


def _write_pack(
    report: dict, ledger: dict, out: Path, *, force: bool
) -> dict[str, str]:
    """The evidence pack: the report, each cited record, and their digests.

    A directory an auditor can be handed without attaching the whole ledger.
    Refuses a non-empty directory unless forced, because `--out` pointed at
    the wrong path must not quietly mix this tool's output into somebody's
    files.
    """
    if out.exists() and any(out.iterdir()) and not force:
        raise LedgerError(
            f"refusing to write the evidence pack into {str(out)!r}: the "
            "directory is not empty; pass --force to write into it anyway"
        )
    out.mkdir(parents=True, exist_ok=True)

    cited: set[str] = set()
    for row in report["controls"]:
        cited.update(row.get("evidence") or [])
        cited.update(row.get("failing") or [])

    records = ledger.get("records")
    records = records if isinstance(records, list) else []
    by_id = {
        entry["id"]: entry
        for entry in records
        if isinstance(entry, MappingABC) and isinstance(entry.get("id"), str)
    }

    digests: dict[str, str] = {}

    def emit(name: str, payload: object) -> None:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        (out / name).write_text(text, encoding="utf-8")
        digests[name] = (
            "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        )

    emit("report.json", report)
    for identifier in sorted(cited):
        if identifier in by_id:
            # The identifier is ledger content, and `RECORD_ID` already
            # constrains it to `[A-Z]+-\d{4}-\d{3}`; the membership test above
            # is what keeps an arbitrary string from becoming a filename.
            emit(f"{identifier}.json", by_id[identifier])

    (out / "digests.json").write_text(
        json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return digests


def compliance_command(
    *,
    ledger: Path,
    framework: str,
    out: Path | None = None,
    force: bool = False,
) -> int:
    """`compliance` as a command: report to stdout, everything else to stderr.

    The split is `drift_command`'s contract, kept for the same reason: a caller
    pipes stdout straight into a JSON reader. Exit codes: `0` with no
    `EVIDENCE_ABSENT`, `1` with any, `2` on tool error.
    """
    try:
        document = load_json(ledger)
        report, messages, code = compliance_report(document, framework=framework)
        if out is not None:
            _write_pack(report, document, out, force=force)
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2

    for message in messages:
        print(message, file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return code
