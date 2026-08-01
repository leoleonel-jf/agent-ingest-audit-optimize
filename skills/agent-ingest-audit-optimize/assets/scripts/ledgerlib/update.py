"""`update`: bring the ledger up to date, or the dashboard, or both.

Three words name the three things a reader can mean by "refresh", and the
table in the design spec (`docs/specs/2026-08-01-dashboard-open-and-update.md`
section 3) is the contract:

- `anchors` re-renders the page. It writes the dashboard and never the
  ledger. Every build re-resolves every anchor anyway -- `build_payload`
  calls `drift_report` and `rollback_preview` on each run -- so there is
  nothing else for this word to do, and it delegates to `build_command`
  wholesale.
- `ledger` captures the environment into a new `baselines[]` entry. It writes
  the ledger and never the dashboard.
- `all` does the first, then the second, in that order: the render must see
  the entry that was just appended.

The chain is untouched by any of them. `chain._records` links `records[]`,
and a baseline is not a record, so appending one changes no digest and
`verify --expect-head` keeps passing against a head captured beforehand.
"""

from __future__ import annotations

import datetime
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from ledgerlib import build as build_module
from ledgerlib.chain import _detect_format, _write_atomically
from ledgerlib.constants import RECORD_ID
from ledgerlib.errors import LedgerError
from ledgerlib.paths import _path_key, file_digest, load_json
from ledgerlib.scan import scan
from ledgerlib.validate import _prefix_and_number, validate_collection, validate_ledger

WHAT_CHOICES = ("all", "ledger", "anchors")


def _spent_base_numbers(document: object) -> list[int]:
    """Every `BASE` number this document already spends, in either holder.

    `baselines[]` and `records[]` compete for one `BASE` sequence slot --
    `validate_collection` feeds both into the same high-water mark -- so a
    mint that looked at only one of them could hand out a number the other
    already holds.
    """
    numbers: list[int] = []
    if not isinstance(document, dict):
        return numbers
    for holder in ("baselines", "records"):
        items = document.get(holder)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            identifier = item.get("id")
            if not isinstance(identifier, str) or not RECORD_ID.fullmatch(identifier):
                continue
            prefix, number = _prefix_and_number(identifier)
            if prefix == "BASE":
                numbers.append(number)
    return numbers


def next_baseline_id(document: object, *, year: str) -> str:
    """Mint the next `BASE` identifier this document can spend.

    The number is the higher of two floors: one past everything already
    spent, and the `sequences.BASE` value the document declares. Taking the
    maximum is what keeps a padded `sequences` meaningful -- `verify` treats
    it as a floor rather than an equality precisely so an operator can
    reserve a range, and a mint that ignored it would spend inside the
    reservation.

    This is the liberty section 4 of the design spec takes, and takes
    knowingly: `references/LEDGER.md` makes the global ledger the only ID
    authority, and this mints locally instead. The caller is required to say
    so on stderr; see `update_command`.
    """
    spent = _spent_base_numbers(document)
    floor = 0
    if isinstance(document, dict):
        sequences = document.get("sequences")
        if isinstance(sequences, dict):
            declared = sequences.get("BASE")
            # `bool` is an `int` in Python, and a `true` here would otherwise
            # be read as the floor 1.
            if isinstance(declared, int) and not isinstance(declared, bool):
                floor = declared
    number = max([floor, *(spent_number + 1 for spent_number in spent)])
    if number > 999:
        raise LedgerError(
            f"cannot mint a BASE identifier for {year}: the three-digit "
            "sequence is exhausted (999 spent)"
        )
    return f"BASE-{year}-{number:03d}"


def _raise_sequence_floor(document: dict, number: int) -> None:
    """Keep `sequences.BASE` at least one past the number just spent."""
    sequences = document.get("sequences")
    if not isinstance(sequences, dict):
        sequences = {}
        document["sequences"] = sequences
    current = sequences.get("BASE")
    current = current if isinstance(current, int) and not isinstance(current, bool) else 0
    sequences["BASE"] = max(current, number + 1)


def _gate(ledger: Path, document: object) -> list[str]:
    """`verify`'s two checks, the pair `build_command` runs before it builds.

    Run before any write, for every word: a ledger nothing vouched for is not
    a ledger this command appends to, and it is not one it renders either.
    """
    source = str(ledger)
    findings = validate_ledger(document, source=source)
    try:
        digest = file_digest(ledger)
    except (LedgerError, OSError):
        return findings
    digests = {
        _path_key(source): digest,
        _path_key(str(ledger.resolve())): digest,
    }
    findings.extend(
        validate_collection([(source, document)], complete=True, digests=digests)
    )
    return findings


def _append_baseline(
    ledger: Path,
    document: dict,
    *,
    identifier: str | None,
    client: str | None,
    adapter: Path | None,
    user_config: Path | None,
    project: Path | None,
    captured_on: str,
) -> tuple[str, str, int]:
    """Scan, append, raise the floor, write. Returns `(id, minted, code)`.

    `minted` is `"given"` when the caller supplied `--id` and `"local"` when
    this function minted one, and it reaches stdout so that a locally minted
    identifier is never silently indistinguishable from an issued one.
    """
    if identifier is None:
        identifier = next_baseline_id(document, year=captured_on[:4])
        minted = "local"
    else:
        minted = "given"
        if not RECORD_ID.fullmatch(identifier) or not identifier.startswith("BASE-"):
            raise LedgerError(
                f"{identifier!r} is not a baseline identifier: expected "
                "BASE-YYYY-NNN"
            )

    if identifier in {
        item.get("id")
        for holder in ("baselines", "records")
        for item in (document.get(holder) or [])
        if isinstance(item, dict)
    }:
        raise LedgerError(
            f"{ledger}: {identifier} is already spent in this ledger; pass a "
            "free --id, or omit --id to mint the next one"
        )

    # Read the original text before the scan, not after: `_detect_format`
    # must describe the file this write is replacing.
    try:
        with ledger.open("r", encoding="utf-8", newline="") as handle:
            original = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"Unreadable ledger: {ledger}: {exc}") from exc

    entry, messages, code = scan(
        identifier=identifier,
        client=client,
        adapter=adapter,
        user_config=user_config,
        project=project,
        captured_on=captured_on,
    )
    for message in messages:
        print(message, file=sys.stderr)

    baselines = document.get("baselines")
    if not isinstance(baselines, list):
        baselines = []
        document["baselines"] = baselines
    baselines.append(entry)
    _raise_sequence_floor(document, _prefix_and_number(identifier)[1])
    document["updated"] = captured_on

    newline, indent, trailing = _detect_format(original)
    text = json.dumps(document, indent=indent, ensure_ascii=False)
    if trailing:
        text += "\n"
    _write_atomically(ledger, text, newline)
    return identifier, minted, code


def update_command(
    ledger: Path,
    what: str,
    *,
    identifier: str | None = None,
    client: str | None = None,
    out: Path | None = None,
    lang: str | None = None,
    force: bool = False,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
    open_after: bool = False,
    today: str | None = None,
) -> int:
    """`update` as a command: one JSON object on stdout, notes on stderr.

    Exit codes follow the family: `0` clean, `1` findings or a write refusal,
    `2` a tool error or a ledger `verify` would reject -- in which case
    nothing is written at all.

    A `scan` that reports findings still appends. The findings describe the
    environment that was captured, not a defect in the capture, and refusing
    to write would leave the ledger asserting that an older, cleaner state is
    still current. The exit code carries the finding instead.
    """
    captured_on = today or datetime.date.today().isoformat()

    try:
        document = load_json(ledger)
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Unreadable ledger: {ledger}: {exc}", file=sys.stderr)
        return 2

    findings = _gate(ledger, document)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 2

    summary: dict[str, object] = {
        "updated": what,
        "baseline_id": None,
        "minted": None,
        "dashboard": None,
    }
    code = 0

    if what in ("ledger", "all"):
        try:
            identifier, minted, scan_code = _append_baseline(
                ledger,
                document,
                identifier=identifier,
                client=client,
                adapter=adapter,
                user_config=user_config,
                project=project,
                captured_on=captured_on,
            )
        except LedgerError as exc:
            print(exc, file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"cannot write {str(ledger)!r}: {exc}", file=sys.stderr)
            return 1
        summary["baseline_id"] = identifier
        summary["minted"] = minted
        code = max(code, scan_code)
        if minted == "local":
            print(
                f"{ledger}: minted {identifier} locally -- this ledger is not "
                "the ID authority, so reconcile it with the global ledger "
                "before the number is issued twice",
                file=sys.stderr,
            )
        print(f"appended {identifier} to baselines", file=sys.stderr)

    if what in ("anchors", "all"):
        out_path = out if out is not None else ledger.parent / "dashboard.html"
        # `build_command` writes its own `wrote <path>` line to stdout, and
        # this command's stdout is one JSON object. Capturing it here rather
        # than adding a quiet mode to `build_command` keeps that command's
        # stream contract exactly as its own tests pin it; the line is not
        # discarded, it moves to stderr where update's notes live.
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            build_code = build_module.build_command(
                ledger,
                out,
                lang,
                force,
                adapter=adapter,
                user_config=user_config,
                project=project,
                open_after=open_after,
            )
        for line in buffer.getvalue().splitlines():
            print(line, file=sys.stderr)
        if build_code != 0:
            return build_code
        summary["dashboard"] = str(out_path)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return code
