"""Schema constants, regexes, and closed enums the ledger tools validate against."""

from __future__ import annotations

import re


SCHEMA_VERSION = "1.0"

# The single source of truth for the plugin's own version is
# `.claude-plugin/plugin.json` -> `version`, but the bundle ships without
# that file (packaging strips everything outside `skills/`), so a value
# baked in here at release time is the only one `dashboard.py build` can
# read at runtime. `packaging/tests/test_version_consistency.py` pins every
# *other* copy of the version to that one source; this one is kept in step
# by the same release step that bumps the rest, not by an import that would
# require shipping the manifest inside the bundle.
TOOL_VERSION = "0.4.0"

REQUIRED_LEDGER_FIELDS = {
    "schema_version",
    "ledger_id",
    "scope",
    "language",
    "client",
    "adapter_version",
    "created",
    "updated",
    "id_authority",
    "sequences",
    "known_projects",
    "records",
    "baselines",
    "backlog",
}

SEQUENCE_PREFIXES = ("MAT", "PROP", "RUN", "ADR", "BASE")
LEDGER_SCOPES = {"global", "project"}
ARRAY_FIELDS = ("known_projects", "records", "baselines", "backlog")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

RECORD_ID = re.compile(r"^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$")
PROVISIONAL_ID = re.compile(r"-P$")
RECORD_TYPES = {"MATERIAL", "PROPOSAL", "RUN", "ADR", "BASELINE"}
RECORD_STATUSES = {
    "ANALYZED",
    "PROPOSED",
    "DECIDED",
    "IMPLEMENTED",
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "NOT IMPLEMENTED",
    "PENDING",
    "ROLLBACK",
    "SUPERSEDED",
}
CLASSIFICATIONS = {
    "ADOPT GLOBALLY",
    "ADOPT AS A DEFAULT FOR NEW PROJECTS",
    "MIGRATE EXISTING PROJECTS",
    "ADOPT LOCALLY",
    "TEST IN ISOLATION",
    "ADAPT",
    "MONITOR",
    "REJECT",
    "OBSOLETE",
    "ALREADY IMPLEMENTED",
    "NOT APPLICABLE",
    "NEEDS MORE EVIDENCE",
    "RISK EXCEEDS BENEFIT",
}
RECORD_SCOPES = {
    "session",
    "project",
    "workspace",
    "user-global",
    "organization",
    "fleet",
}
LINK_FIELDS = ("materials", "runs", "adrs")
REQUIRED_RECORD_FIELDS = {
    "id",
    "type",
    "title",
    "status",
    "classification",
    "scope",
    "created",
    "updated",
    "file",
    "links",
    "evidence",
}
EVIDENCE_FIELDS = {"source", "kind", "verified_on", "time_sensitive"}

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_RESULTS = {
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "PARTIALLY VALIDATED",
    "NOT VALIDATED",
    "FAILED",
    "ROLLBACK COMPLETED",
}
ROLLBACK_TEST_STATES = {"NOT_TESTED", "PARTIAL", "PASSED", "FAILED"}
REQUIRED_RUN_FIELDS = {
    "proposal",
    "authorization",
    "result",
    "targets",
    "backup",
    "rollback",
    "self_reported",
}
REQUIRED_TARGET_FIELDS = {
    "anchor",
    "kind",
    "before_digest",
    "after_digest",
    "reversible",
    "residual_effect",
}

BACKLOG_CLASSIFICATIONS = {
    "REJECT",
    "NEEDS MORE EVIDENCE",
    "RISK EXCEEDS BENEFIT",
    "MONITOR",
    "TEST IN ISOLATION",
}
TERMINAL_CLASSIFICATIONS = {"OBSOLETE", "NOT APPLICABLE", "ALREADY IMPLEMENTED"}
REQUIRED_BACKLOG_FIELDS = {
    "id",
    "classification",
    "reason",
    "revisit_trigger",
    "revisit_after",
}
PROJECT_STATUSES = {"OK", "UNREACHABLE", "CHANGED_EXTERNALLY"}
REQUIRED_PROJECT_FIELDS = {
    "project_root",
    "ledger_path",
    "last_seen",
    "last_digest",
    "status",
}

BASELINE_ITEM_KINDS = {
    "instruction-file",
    "skill",
    "plugin",
    "agent",
    "command",
    "hook",
    "mcp-server",
    "permission-rule",
    "model-setting",
    "env-var-name",
}
BASELINE_ITEM_STATES = {"present", "not_present"}
# How a client resolves one kind across scopes. `override` is the only mode
# `drift` may compute a winner under; the other three exist so an adapter can
# declare that no per-item winner is well-formed rather than staying silent.
RESOLUTION_MODES = {"override", "key-override", "merge", "concatenate"}
# The modes that rank scopes. `order` is required under these and forbidden
# under the rest: an ordering carried by `merge` or `concatenate` would claim
# a precedence the mode itself denies.
ORDERED_RESOLUTION_MODES = {"override", "key-override"}
REQUIRED_BASELINE_FIELDS = {"id", "captured_on", "client", "adapter_version", "items"}
# Written by `scan` since 0.5.0, and deliberately NOT required: every baseline
# captured before it is still valid, and demanding the field would invalidate
# the very records this tool exists to preserve. `platform` says which
# `sys.platform` produced the entry, so a layer missing because the platform
# has no such anchor is distinguishable from a layer missing because it drifted.
OPTIONAL_BASELINE_FIELDS = {"platform"}
REQUIRED_BASELINE_ITEM_FIELDS = {
    "kind",
    "name",
    "anchor",
    "digest",
    "attributes",
    "origin",
    "state",
}

# The five states `drift` can assign a baseline item or a run target (design
# spec section 10). Closed: a sixth state would need a row in the spec's
# tables first, and `REVERTED` is reachable only for run targets -- a baseline
# item has no before/after pair to revert between, and `drift` never
# manufactures one.
DRIFT_STATES = {"IN_PLACE", "DRIFTED", "REVERTED", "MISSING", "UNVERIFIABLE"}

# The three-value rollback health indicator `rollback-preview` derives per RUN
# (design spec section 11). Closed like DRIFT_STATES: a fourth value would
# need a row in the spec's indicator table first. BROKEN is about the backup,
# not the targets -- a backup that cannot be trusted makes every other promise
# moot -- and it is checked first without short-circuiting the four sets.
ROLLBACK_INDICATORS = {"HEALTHY", "AT_RISK", "BROKEN"}

ANCHOR_REFERENCE = re.compile(r"^\$([A-Z_]+)(?:/(.*))?\Z")
ANCHOR_NAME = re.compile(r"^[A-Z_]+$")
# CON, PRN, AUX, NUL, COM1-9, LPT1-9, with or without an extension. Reserved
# on Windows regardless of extension or case; refused on every platform
# because a ledger written on Windows may be validated on Linux and must get
# the same answer either way.
DEVICE_NAME = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", re.IGNORECASE)
