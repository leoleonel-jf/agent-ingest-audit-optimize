#!/usr/bin/env python3
"""Say which bundled evidence has expired, or is about to.

Adapters and control mappings each carry `expires_on`: the day after which
their content can no longer be assumed to match what a vendor or a regulator
publishes. The commands that read them already tell the user when that day has
passed. This script answers the maintainer's question instead -- "is anything
we ship stale, or about to be" -- and it is the only place in the repository's
checks where that question meets the calendar.

The three test suites deliberately do not ask it. They pin every date, so they
say whether the code is right and never whether time has passed. Run this on a
schedule, and before a release:

    python packaging/scripts/check_evidence_freshness.py --margin-days 14

Exit codes match the bundle's own: `0` nothing stale, `1` something expired or
inside the margin, `2` the check could not be trusted (a malformed date, or no
dated evidence found at all).

Renewing a date is never the fix by itself. Re-verify the content against its
source first; `docs/research/` records how that was done last time.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DEFAULT_MARGIN_DAYS = 14


class FreshnessError(Exception):
    """The check itself cannot be trusted; distinct from finding stale evidence."""


def _parse_date(value: object, what: str) -> datetime.date:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        raise FreshnessError(f"{what} must be YYYY-MM-DD: {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise FreshnessError(f"{what} is not a calendar date: {value!r}") from exc


def dated_evidence(root: Path) -> list[tuple[Path, datetime.date]]:
    """Every JSON document under `skills/` whose top level carries `expires_on`.

    Top level only: a schema that merely describes an `expires_on` property is
    not evidence, and counting it would let the check pass on a tree where the
    real evidence had been moved out from under it.
    """
    found: list[tuple[Path, datetime.date]] = []
    for path in sorted((root / "skills").rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FreshnessError(f"{path}: cannot be read as JSON: {exc}") from exc
        if not isinstance(document, dict) or "expires_on" not in document:
            continue
        relative = path.relative_to(root).as_posix()
        found.append((path, _parse_date(document["expires_on"], f"{relative}: expires_on")))
    return found


def classify(expires_on: datetime.date, today: datetime.date, margin_days: int) -> str:
    """`expired`, `expiring`, or `fresh`.

    Expiry is strict, to agree with `scan`, which reports an adapter only when
    the run is dated after `expires_on`. `expiring` asks the same question of
    a later day: evidence is expiring when it would be expired `margin_days`
    from today. A margin of zero therefore never reports `expiring`.
    """
    if today > expires_on:
        return "expired"
    if today + datetime.timedelta(days=margin_days) > expires_on:
        return "expiring"
    return "fresh"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--today", help="the date to judge against, YYYY-MM-DD; the clock when omitted")
    parser.add_argument("--margin-days", type=int, default=DEFAULT_MARGIN_DAYS)
    arguments = parser.parse_args(argv)

    try:
        today = datetime.date.today() if arguments.today is None else _parse_date(arguments.today, "--today")
        if arguments.margin_days < 0:
            raise FreshnessError(f"--margin-days must not be negative: {arguments.margin_days}")
        evidence = dated_evidence(arguments.root)
        if not evidence:
            raise FreshnessError(
                f"no dated evidence found under {arguments.root / 'skills'}: "
                "a check that looked at nothing cannot report that nothing is stale"
            )
    except FreshnessError as exc:
        print(exc, file=sys.stderr)
        return 2

    stale = 0
    for path, expires_on in evidence:
        status = classify(expires_on, today, arguments.margin_days)
        stale += status != "fresh"
        relative = path.relative_to(arguments.root).as_posix()
        print(f"{status:<8} {expires_on.isoformat()}  {relative}")
    print(f"judged on {today.isoformat()} with a margin of {arguments.margin_days} day(s): {stale} of {len(evidence)} stale")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
