"""Previewing what a rollback of one `RUN` would and would not restore.

`rollback-preview` is the third read-only ledger command: it loads a ledger,
finds one named `RUN` record, classifies that run's targets against the
environment now, verifies the recorded backup, and reports design spec
section 11's four sets and the three-value health indicator. It writes
nothing -- no file, no directory -- and it executes nothing. Spec
`docs/specs/2026-07-30-drift-and-rollback-preview.md` section 3.3 owns the
behaviour.

Two reuse rules are structural rather than stylistic, and both are held by
calling through another module's binding so a single patch observes them:

- Target classification is `drift.classify_target`, reached as an attribute
  of `ledgerlib.drift` at call time -- same code, not similar code. A second
  classifier here would eventually disagree with `drift` about the very
  states this report is built from.

- Backup digest recomputation is the `file_digest` binding `verify` itself
  calls (`ledgerlib.verify.file_digest`), reached the same way. The recorded
  `backup.digest` describes the backup's on-disk bytes exactly as
  `known_projects[].last_digest` describes a ledger's, so the two commands
  must recompute with one function or their answers can split.

The four sets are always all present, empty ones as `[]`, and `BROKEN` never
short-circuits them: the indicator is checked first because an untrustworthy
backup makes every other promise moot, but the sets are still computed and
reported, because the reader deciding what to do next is entitled to the
target states either way.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from ledgerlib import drift, verify
from ledgerlib.adapters import (
    resolve_anchor_roots,
    select_adapter_detail,
)
from ledgerlib.constants import ROLLBACK_INDICATORS  # noqa: F401  (re-export)
from ledgerlib.drift import DRIFTED, IN_PLACE, MISSING, REVERTED, UNVERIFIABLE
from ledgerlib.errors import LedgerError, PathSafetyError
from ledgerlib.paths import load_json, resolve_anchored
from ledgerlib.scan import BUNDLED_ADAPTERS
from ledgerlib.validate import validate_ledger


HEALTHY = "HEALTHY"
AT_RISK = "AT_RISK"
BROKEN = "BROKEN"

# The reasons backup verification itself attaches, following `DRIFT_REASONS`:
# a closed set of stable strings, never an exception's own text.
# `PathSafetyError.reason` keys pass through unchanged for the reason `drift`
# gives -- the path layer already owns a stable vocabulary for its refusals,
# and restating them here would give one refusal two names.
BACKUP_REASONS = frozenset(
    {
        "missing",
        "malformed",
        "digest_not_recorded",
        "unreadable",
        "digest_mismatch",
    }
)


def _find_run(ledger: dict, run_id: object) -> dict:
    """The named `RUN` record, or a `LedgerError` naming the ID `!r`.

    An unknown ID and an ID naming a non-RUN record are both tool errors
    (spec 3.3): the caller asked a question about a run that does not exist,
    which is not a fact about the environment the report could carry.
    """
    records = ledger.get("records")
    records = records if isinstance(records, list) else []
    for record in records:
        if isinstance(record, dict) and record.get("id") == run_id:
            if record.get("type") != "RUN":
                raise LedgerError(
                    f"record {run_id!r} is not a RUN: its type is "
                    f"{record.get('type')!r} and only a RUN has targets and a "
                    "backup to preview"
                )
            return record
    raise LedgerError(f"no record with id {run_id!r} exists in this ledger")


def _verify_backup(
    backup: object, roots: Mapping[str, Path]
) -> tuple[bool, str | None]:
    """Recompute the recorded backup digest. Returns `(verified, reason)`.

    Nothing reachable from ledger data raises: a missing path, an anchor that
    does not resolve, an unreadable file -- each is `(False, reason)`, and the
    caller turns any of them into `BROKEN`. The recorded `verified` flag is
    deliberately ignored: it is the run's own claim, and this function exists
    to recompute rather than to trust.

    The backup path is ledger content, so it goes through `resolve_anchored`
    before it is opened, exactly like every target anchor -- a backup stored
    outside the resolved anchors is a backup this tool refuses to read, not
    an exception to the path-safety layer.
    """
    if backup is None:
        return False, "missing"
    if not isinstance(backup, dict):
        return False, "malformed"
    recorded = backup.get("digest")
    if not isinstance(recorded, str):
        return False, "digest_not_recorded"
    try:
        path = resolve_anchored(backup.get("path"), roots)
    except PathSafetyError as exc:
        return False, exc.reason
    try:
        # `verify.file_digest`, not a local import of `paths.file_digest`:
        # the attribute lookup at call time is what makes the reuse a fact a
        # test can observe by patching `ledgerlib.verify.file_digest` once.
        current = verify.file_digest(path)
    except FileNotFoundError:
        return False, "missing"
    except (OSError, ValueError, MemoryError):
        return False, "unreadable"
    if current != recorded:
        return False, "digest_mismatch"
    return True, None


def rollback_preview(
    ledger: dict,
    run_id: str,
    *,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
    bundled: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[dict, list[str], int]:
    """Preview one run's rollback. Returns `(report, messages, code)`.

    `messages` follows `drift_report`'s contract: adapter-selection notes
    first, then findings, one list because they share one stream. `code` is
    `0` for `HEALTHY` with no findings and `1` otherwise; `2` is not returned
    here at all -- a tool error (an unknown run ID, an unknown client, an
    unreadable adapter) is raised as `LedgerError`, and the command wrapper
    is the one place that turns it into `2`, exactly as `drift_command` does.

    Anchor resolution reuses the 0.2.5 machinery unchanged, and the ledger's
    top-level `client` drives it, as it does for `drift`'s run targets: run
    targets belong to the ledger, not to any baseline entry, so the document's
    own client is the only provenance they carry.

    Set membership is by classified state (spec 3.3): `will_be_restored`
    holds `IN_PLACE` targets and only under a verified backup -- restoring is
    a promise about the backup's bytes, and nothing verified them under
    `BROKEN`, so the set empties while `will_not_change` (`REVERTED`) and
    `cannot_be_restored` (`DRIFTED`, `MISSING`, `UNVERIFIABLE`, each carrying
    its state as the reason) still populate from target states.
    """
    if not isinstance(ledger, dict):
        raise LedgerError("ledger must be a JSON object")

    project = Path.cwd() if project is None else project
    environ = os.environ if environ is None else environ
    bundled = BUNDLED_ADAPTERS if bundled is None else bundled

    record = _find_run(ledger, run_id)

    client = ledger.get("client")
    selection = select_adapter_detail(
        client=client if isinstance(client, str) and adapter is None else None,
        adapter=adapter,
        user_config=user_config,
        bundled=bundled,
        environ=environ,
        project=project,
    )
    notes = list(selection["notes"])
    findings: list[str] = []
    roots, _unresolved = resolve_anchor_roots(
        selection["document"], project=project, environ=environ
    )

    # The backup is checked first -- an untrustworthy backup makes every
    # other promise moot -- and that is ALL "first" means: classification and
    # the four sets are computed and reported regardless of the outcome.
    verified, backup_reason = _verify_backup(record.get("backup"), roots)

    targets = record.get("targets")
    if not isinstance(targets, list):
        findings.append(
            f"record {run_id!r} targets must be an array and was not "
            f"classified: {targets!r}"
        )
        targets = []

    will_be_restored: list[dict] = []
    will_not_change: list[dict] = []
    cannot_be_restored: list[dict] = []
    residual_effects: list[object] = []
    states: list[str] = []

    for target in targets:
        # `drift.classify_target` through the module attribute, at call time:
        # same code as `drift`, not similar code, observable by one patch.
        state, _reason = drift.classify_target(target, roots)
        states.append(state)
        anchor = target.get("anchor") if isinstance(target, dict) else None
        row = {
            "anchor": anchor,
            # `drift.resolved_path`, through the module attribute for the
            # reason `classify_target` is: the row's `path` must be the very
            # answer drift's rows carry, or the two reports could name
            # different files for one anchor.
            "path": drift.resolved_path(anchor, roots),
            "kind": target.get("kind") if isinstance(target, dict) else None,
            "state": state,
        }
        if state == IN_PLACE and verified:
            will_be_restored.append(row)
        elif state == IN_PLACE:
            # Intact, and still unrestorable: restoring needs the backup, and
            # the backup failed verification. Dropping these rows instead
            # made the first real preview report 11 of a run's 17 targets --
            # the four sets partition the run's targets, or "the report is
            # complete" is false.
            cannot_be_restored.append({**row, "reason": backup_reason})
        elif state == REVERTED:
            will_not_change.append(row)
        elif state in (DRIFTED, MISSING, UNVERIFIABLE):
            cannot_be_restored.append({**row, "reason": state})
        residual = (
            target.get("residual_effect") if isinstance(target, dict) else None
        )
        if residual is not None:
            # Verbatim, per spec 3.3: the tool cannot undo an installed
            # dependency or a published artifact, and the preview's job is to
            # make sure nobody believes otherwise.
            residual_effects.append(residual)

    if not verified:
        indicator = BROKEN
    elif any(state == DRIFTED for state in states) or residual_effects:
        indicator = AT_RISK
    elif all(state == IN_PLACE for state in states):
        indicator = HEALTHY
    else:
        # The literal indicator table (design spec section 11) covers neither
        # this run's targets nor its backup: the backup verifies, nothing
        # DRIFTED, no residual exists -- yet some target is MISSING,
        # UNVERIFIABLE, or already REVERTED, so HEALTHY's "every target
        # IN_PLACE" fails too. Spec 3.3's cannot_be_restored rationale --
        # restoring would destroy an unrelated edit, or there is nothing left
        # to restore onto -- is a statement of risk, so a rollback that
        # cannot restore everything resolves to AT_RISK, never silently to
        # HEALTHY.
        indicator = AT_RISK

    # The backup's own resolved path, beside its verdict: design spec 12.2's
    # Open offer names "the record, the backup, or the changed file", and the
    # backup is a real file this preview verified (or failed to). Resolved
    # through the same binding the rows use, and None -- never a raise --
    # when the backup is absent, malformed, or refuses to resolve.
    recorded_backup = record.get("backup")
    backup_path = drift.resolved_path(
        recorded_backup.get("path") if isinstance(recorded_backup, dict) else None,
        roots,
    )

    report = {
        "run": run_id,
        "indicator": indicator,
        "backup": {
            "verified": verified,
            "reason": backup_reason,
            "path": backup_path,
        },
        "will_be_restored": will_be_restored,
        "will_not_change": will_not_change,
        "cannot_be_restored": cannot_be_restored,
        "residual_effects": residual_effects,
    }
    code = 0 if indicator == HEALTHY and not findings else 1
    return report, [*notes, *findings], code


def rollback_preview_command(
    *,
    ledger: Path,
    run_id: str,
    adapter: Path | None = None,
    user_config: Path | None = None,
    project: Path | None = None,
) -> int:
    """`rollback-preview` as a command: report to stdout, the rest to stderr.

    The split of streams is `drift_command`'s contract, kept for the same
    reason: a caller pipes stdout straight into a JSON reader, so not one
    byte that is not the report may go there.

    Exit codes per spec 3.3: `0` for `HEALTHY`, `1` for `AT_RISK` or
    `BROKEN` (or a finding), `2` on tool error -- an unreadable or invalid
    ledger, an invalid adapter, an unknown run ID, an ID naming a non-RUN
    record. An invalid ledger is a tool error rather than a finding, and
    `validate_ledger` is reused rather than re-implemented, exactly as
    `drift_command` reuses it: a document the validator refuses is not a
    record of anything, and previewing a rollback from fields nothing
    vouched for would print promises nobody made.
    """
    try:
        document = load_json(ledger)
        invalid = validate_ledger(document, source=str(ledger))
        if invalid:
            for finding in invalid:
                print(finding, file=sys.stderr)
            return 2
        report, messages, code = rollback_preview(
            document,
            run_id,
            adapter=adapter,
            user_config=user_config,
            project=project,
        )
    except LedgerError as exc:
        print(exc, file=sys.stderr)
        return 2

    for message in messages:
        print(message, file=sys.stderr)
    print(json.dumps(report, indent=2))
    return code
