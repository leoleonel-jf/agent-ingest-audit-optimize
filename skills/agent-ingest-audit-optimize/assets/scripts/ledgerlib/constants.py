"""Schema constants, regexes, and closed enums the ledger tools validate against."""

from __future__ import annotations

import re


SCHEMA_VERSION = "1.0"

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
REQUIRED_BASELINE_FIELDS = {"id", "captured_on", "client", "adapter_version", "items"}
REQUIRED_BASELINE_ITEM_FIELDS = {
    "kind",
    "name",
    "anchor",
    "digest",
    "attributes",
    "origin",
    "state",
}

ANCHOR_REFERENCE = re.compile(r"^\$([A-Z_]+)(?:/(.*))?\Z")
ANCHOR_NAME = re.compile(r"^[A-Z_]+$")
# CON, PRN, AUX, NUL, COM1-9, LPT1-9, with or without an extension. Reserved
# on Windows regardless of extension or case; refused on every platform
# because a ledger written on Windows may be validated on Linux and must get
# the same answer either way.
DEVICE_NAME = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", re.IGNORECASE)
