"""The withdrawn `compliance` command.

`compliance` used to map ledger records to the controls of the EU AI Act and
ISO/IEC 42001 and report which evidence existed. Its mapping named the wrong
articles and controls, and correcting it would mean maintaining a legal reading
this project has no standing to own, so 0.8.0 withdrew the command. The
subcommand stays registered, with its old arguments, only so that an existing
invocation ends in an explanation instead of an argument error. It reads no
ledger and writes nothing; the record of the errors is the 0.8.0 entry in
`CHANGELOG.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path


WITHDRAWN_NOTICE = (
    "the `compliance` command was withdrawn in 0.8.0: its control mapping "
    "misidentified the articles and controls it named, and this plugin does not "
    "assess regulatory compliance. Nothing was read and nothing was written. "
    "The reasons are in the 0.8.0 entry of CHANGELOG.md."
)


def compliance_command(
    *,
    ledger: Path,
    framework: str,
    out: Path | None = None,
    force: bool = False,
) -> int:
    """Say the command was withdrawn and exit `2`, the code for "nothing was produced".

    The arguments are accepted and ignored on purpose: touching `ledger` or
    `out` would turn a refusal into a side effect.
    """
    print(WITHDRAWN_NOTICE, file=sys.stderr)
    return 2
