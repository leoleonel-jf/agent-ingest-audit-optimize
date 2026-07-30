"""Exceptions the ledger tools raise, and the refusal reasons they carry."""

from __future__ import annotations


class LedgerError(RuntimeError):
    """Raised when a ledger cannot be read at all."""


class PathSafetyError(RuntimeError):
    """Raised when a path may not be resolved under its anchor.

    Every refusal carries a stable `reason` key in addition to its ordinary
    human-readable message, so a caller -- and this module's own alignment
    test against `references/LEDGER.md` -- can enumerate every refusal the
    path-safety layer can produce without parsing message text.
    `PATH_SAFETY_REASONS` is the definitive, exhaustive set of keys this
    exception can carry.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# The exhaustive set of reason keys any PathSafetyError raised anywhere in
# this module can carry. `references/LEDGER.md` must document exactly this
# set -- no more, no fewer. `PathSafetyReasonAlignmentTests` in
# dashboard/tests/test_dashboard.py checks both directions: every key here
# must be documented there, and every key documented there must be one the
# code can actually raise -- so a tenth refusal added to the code without
# being documented fails the test, and so does a documented reason the code
# can no longer raise.
PATH_SAFETY_REASONS = frozenset(
    {
        "invalid_anchor_name",
        "glob_not_string",
        "glob_nul_byte",
        "glob_dotdot_segment",
        "glob_absolute",
        "resolve_failed",
        "path_empty",
        "path_embedded_nul",
        "path_dotdot_segment",
        "path_absolute",
        "path_malformed_anchor_reference",
        "path_unknown_anchor",
        "path_reserved_device_name",
        "path_alternate_data_stream",
        "path_link_crosses_anchor",
        "path_resolves_outside_anchor",
        "path_inspect_failed",
        "path_hardlinked",
    }
)
