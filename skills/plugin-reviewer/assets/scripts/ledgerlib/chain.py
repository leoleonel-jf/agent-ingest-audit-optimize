"""Hash-chaining the ledger's records, so tampering leaves evidence.

`verify` checks a ledger's shape, its references and its sequences. None of
those notice a valid record being replaced by a different valid record, and
the ledger is a JSON file any process with write access can rewrite. That is
an uncomfortable property for a document whose entire value is the sentence
"this is the record of what was authorized and done".

This module chains the records: each carries the digest of its own bytes and
the digest of the one before it, so an edit, a deletion or a reordering breaks
an arithmetic relationship rather than merely contradicting somebody's memory.

**What this is, precisely.** Tamper-EVIDENT, not tamper-proof:

| Scenario | Detected? |
|---|---|
| Editing a record | yes -- its digest no longer matches |
| Deleting a record from the middle | yes -- the next record's `previous` no longer matches |
| Reordering records | yes -- `index` and `previous` are inside the hash |
| Truncating the end of the chain | only with an external anchor |
| Rewriting everything and re-sealing | **no** -- without an external anchor |

The last row is why `chain_head` exists. The head digest is meant to be kept
somewhere the ledger cannot reach -- a commit message, a tag, another system --
and `verify --expect-head` compares against it. There is no key and no service
here: it is one number the user stores elsewhere, and it is enough to move
"they rewrote everything" from undetectable to detectable.

Nothing in this module is access control. It does not stop a write; it makes
one visible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ledgerlib.errors import LedgerError
from ledgerlib.paths import load_json
from ledgerlib.validate import validate_ledger


# The closed vocabulary, following `DRIFT_REASONS`: stable strings a caller can
# branch on, never an exception's own text.
CHAIN_REASONS = frozenset(
    {
        "digest_mismatch",
        "previous_mismatch",
        "index_gap",
        "unchained",
    }
)

INTACT = "INTACT"
BROKEN = "BROKEN"
PARTIAL = "PARTIAL"
UNCHAINED = "UNCHAINED"

CHAIN_VERDICTS = frozenset({INTACT, BROKEN, PARTIAL, UNCHAINED})


def canonical_text(value: object) -> str:
    """The one canonical JSON rendering in this repository.

    Sorted keys and compact separators make two calls on the same object
    byte-identical, which is the whole basis of a digest that means anything.
    `ensure_ascii=False` keeps Portuguese text as itself rather than as escapes.

    The `backslashreplace` round-trip is not decoration: a ledger string can
    hold a lone surrogate (a `\\ud800` that survived some upstream encoder),
    `json.dumps` will happily emit it, and encoding that to UTF-8 raises. The
    same trap `serialize_payload` closed for the dashboard payload is closed
    here, because hashing must not be the one operation in the tool that dies
    on a document it is meant to describe.

    `build.serialize_payload` is this function plus its HTML-embedding escapes.
    One canonicalization, two consumers -- two would eventually disagree, and
    a payload that disagreed with a digest about the same record would be
    worse than either alone.
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def canonical_bytes(value: object) -> bytes:
    return canonical_text(value).encode("utf-8")


def record_digest(record: Mapping) -> str:
    """The digest of one record, excluding only its own `chain.digest`.

    `chain.index` and `chain.previous` are deliberately INSIDE the hash: they
    are what bind a record to its position. Hash the record's content alone and
    a record could be lifted from one slot to another with its digest still
    matching, which is exactly the reordering this is meant to catch.
    """
    payload = {key: value for key, value in record.items() if key != "chain"}
    chain = record.get("chain")
    if isinstance(chain, Mapping):
        payload["chain"] = {
            key: value for key, value in chain.items() if key != "digest"
        }
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _records(ledger: object) -> list:
    if not isinstance(ledger, Mapping):
        return []
    records = ledger.get("records")
    return records if isinstance(records, list) else []


def verify_chain(ledger: object) -> tuple[list[dict], str]:
    """Check every record's link. Returns `(rows, verdict)`.

    One row per record, in array order, each naming the record and either a
    reason from `CHAIN_REASONS` or `None`. The verdict is `INTACT` (every
    record chained and sound), `PARTIAL` (a sound chain preceded by unchained
    records -- the normal state right after migration), `UNCHAINED` (nothing
    to check), or `BROKEN`.

    A record with no `chain` is `unchained`, never invalid. Every ledger
    written before this feature is unchained, and a tool that invalidated them
    would be destroying the very records it exists to preserve. Indices are
    counted over the chained subsequence, so the first sealed record is index
    0 with `previous: null` whether or not unchained records precede it.

    Nothing reachable from ledger content raises: a `chain` that is not an
    object, a missing `records` array, a record that is not an object -- each
    is a row, because a malformed ledger is a finding about the ledger.
    """
    rows: list[dict] = []
    expected_index = 0
    previous_digest: str | None = None
    chained = 0
    broken = False
    unchained_seen = False

    for position, entry in enumerate(_records(ledger)):
        identifier = entry.get("id") if isinstance(entry, Mapping) else None
        chain = entry.get("chain") if isinstance(entry, Mapping) else None
        if not isinstance(entry, Mapping) or not isinstance(chain, Mapping):
            unchained_seen = True
            rows.append({"id": identifier, "position": position, "reason": "unchained"})
            continue

        reason: str | None = None
        if chain.get("index") != expected_index:
            reason = "index_gap"
        elif chain.get("previous") != previous_digest:
            reason = "previous_mismatch"
        elif chain.get("digest") != record_digest(entry):
            reason = "digest_mismatch"

        if reason is not None:
            broken = True
        rows.append({"id": identifier, "position": position, "reason": reason})

        # The walk continues from what the document CLAIMS even after a
        # mismatch, so one broken link does not cascade into a wall of
        # identical findings that hides where the break actually is.
        chained += 1
        expected_index = chain.get("index", expected_index)
        if isinstance(expected_index, int):
            expected_index += 1
        else:
            expected_index = chained
        previous_digest = chain.get("digest")

    if broken:
        return rows, BROKEN
    if chained == 0:
        return rows, UNCHAINED
    return rows, (PARTIAL if unchained_seen else INTACT)


def chain_head(ledger: object) -> str | None:
    """The digest of the last chained record, or None if there is none.

    This is the value meant to live OUTSIDE the ledger. Everything inside a
    file can be rewritten together; a number written down elsewhere cannot.
    """
    for entry in reversed(_records(ledger)):
        if isinstance(entry, Mapping):
            chain = entry.get("chain")
            if isinstance(chain, Mapping) and isinstance(chain.get("digest"), str):
                return chain["digest"]
    return None


def seal_ledger(ledger: object, *, start: int = 0) -> int:
    """Write `chain` onto records that lack it. Returns how many were sealed.

    Mutates the ledger in place and leaves existing `chain` objects untouched,
    which is what makes sealing idempotent: a second call over a sealed ledger
    changes nothing at all, so re-running it can never rewrite a governance
    file for no reason.

    `start` exists for migration and for tests: records before it are left
    unchained deliberately. The caller -- not this function -- is responsible
    for refusing to seal over a chain that is already broken; sealing over
    tampering would recompute the evidence away, and `chain_command` checks
    for exactly that first.
    """
    records = _records(ledger)
    expected_index = 0
    previous_digest: str | None = None
    sealed = 0

    for position, entry in enumerate(records):
        if not isinstance(entry, dict):
            continue
        if position < start:
            continue
        chain = entry.get("chain")
        if isinstance(chain, Mapping) and isinstance(chain.get("digest"), str):
            index = chain.get("index")
            expected_index = index + 1 if isinstance(index, int) else expected_index + 1
            previous_digest = chain["digest"]
            continue
        entry["chain"] = {"index": expected_index, "previous": previous_digest}
        entry["chain"]["digest"] = record_digest(entry)
        previous_digest = entry["chain"]["digest"]
        expected_index += 1
        sealed += 1

    return sealed


def _detect_format(text: str) -> tuple[str, int, bool]:
    """The original's line ending, indent width, and trailing newline.

    A governance file is read by people and tracked in git. Re-serializing it
    with different line endings would rewrite every line to change three, and
    a diff nobody can read is a diff nobody reviews -- which defeats the point
    of a document whose value is that somebody can check it.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    match = re.search(r"[\r\n]([ ]+)\"", text)
    indent = len(match.group(1)) if match else 2
    return newline, indent, text.endswith(("\n", "\r"))


def _write_atomically(path: Path, text: str, newline: str) -> None:
    """`os.replace` onto `path`, the idiom `write_dashboard` already uses.

    A reader never observes a half-written ledger: the rename is the one step
    that makes new content visible, and it either happens wholly or not at all.
    On any failure the temporary file is removed before the exception
    propagates, so a failed seal leaves no stray `.tmp` beside the ledger.
    """
    handle_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def chain_command(*, ledger: Path, head: bool, seal: bool) -> int:
    """`chain` as a command: print the head, or seal the ledger.

    Exit codes follow the house split: `0` on success, `1` when there is no
    chain to report a head for, `2` on tool error -- an unreadable or invalid
    ledger, or a chain that is already broken.

    `--seal` is the second command in this bundle that writes a file, after
    `build`, and it is guarded accordingly. It refuses a ledger that does not
    validate, because sealing a document nothing vouched for would certify
    garbage. It refuses to seal over a broken chain, because recomputing the
    links would erase the very evidence the chain exists to preserve -- the
    one thing this command must never do. And it is idempotent: a sealed
    ledger sealed again is byte-identical, so re-running it can never churn a
    governance file for nothing.
    """
    try:
        document = load_json(ledger)
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2

    if head:
        current = chain_head(document)
        if current is None:
            print(
                f"{ledger}: unchained -- no record carries a chain, so there "
                "is no head to report. Seal it first with: chain <ledger> --seal",
                file=sys.stderr,
            )
            return 1
        print(current)
        return 0

    if not seal:  # pragma: no cover -- argparse requires one of the two
        print("chain requires --head or --seal", file=sys.stderr)
        return 2

    invalid = validate_ledger(document, source=str(ledger))
    if invalid:
        for finding in invalid:
            print(finding, file=sys.stderr)
        print(
            f"{ledger}: refusing to seal a ledger that does not validate",
            file=sys.stderr,
        )
        return 2

    rows, verdict = verify_chain(document)
    if verdict == BROKEN:
        for row in rows:
            if row["reason"] is not None:
                print(
                    f"{ledger}: records[{row['position']}] {row['id']!r}: "
                    f"{row['reason']}",
                    file=sys.stderr,
                )
        print(
            f"{ledger}: refusing to seal over a broken chain -- resealing "
            "would recompute the links and erase the evidence. Investigate "
            "the records above first.",
            file=sys.stderr,
        )
        return 2

    try:
        # `newline=""` disables universal-newline translation. Without it
        # Python turns CRLF into LF on the way in, `_detect_format` sees only
        # LF, and the seal silently rewrites every line of a CRLF ledger.
        with ledger.open("r", encoding="utf-8", newline="") as handle:
            original = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Unreadable ledger: {ledger}: {exc}", file=sys.stderr)
        return 2

    sealed = seal_ledger(document)
    if sealed:
        newline, indent, trailing = _detect_format(original)
        text = json.dumps(document, indent=indent, ensure_ascii=False)
        if trailing:
            text += "\n"
        _write_atomically(ledger, text, newline)

    current = chain_head(document)
    print(f"sealed {sealed} record(s)", file=sys.stderr)
    print(current if current is not None else "")
    return 0
