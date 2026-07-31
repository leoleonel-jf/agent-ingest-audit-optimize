"""Static security and structure tests over the shipped shell, `dashboard.html`.

This suite reads one file and never runs a browser. That is deliberate: the
properties design spec `docs/specs/2026-07-31-dashboard-build.md` section 1
relies on are properties of the *template text*, not of any particular
render. A rendering test can only show that today's ledger produced inert
output; a grep over the source shows that no ledger could produce anything
else, because the sinks that would let it are not in the file at all.

The three controls the suite pins, in the order section 1 states them:

1. the data island is the only entry point for ledger content, and the
   template ships it holding exactly the static default of section 2 --
   `test_build.py` owns the escaping that keeps a literal `<` out of it;
2. the shell has no DOM sink and no dynamic-evaluation call anywhere in its
   source -- the grep is unconditional, comments and string literals
   included, so the shell's own comments are written to stay clear of the
   vocabulary rather than the test being taught to forgive them;
3. the document carries the section 1.3 CSP verbatim, names no network
   scheme, and offers no `src` attribute for a browser to fetch -- together
   with 1 and 2 that is what makes "opens offline, issues no request"
   (section 7 acceptance item 1) a claim about the file rather than about a
   particular browsing session.

The dictionary tests exist for a different reason: design spec section 5
promises `en` and `pt-BR` carry identical key sets, and a missing key is
invisible at runtime -- `t()` falls back to English and the page looks fine
in Portuguese while quietly speaking English. Only a test notices.

One thing a grep cannot do is prove a guard *refuses* anything. A reviewer
demonstrated exactly that: `safeHref` could be gutted to `return
String(value)` and the whole static suite still passed, because the property
those tests pin is "no sink is present", not "the gate works". So the suite
has a second half. `RuntimeGateTests` boots the real shell -- the script
extracted from the very template the static half reads -- against a ~120-line
DOM fixture (`fixtures/dom_stub.js`) under `node`, and drives `safeHref`,
`attrAllowed`, and the tag coercion in `h()` through a table of inputs. The
node process compares each answer itself and exits nonzero on any mismatch,
so the assertion here is a real one rather than a formality.

`node` is not a dependency of this plugin, so that class skips where node is
absent; CI and every dogfood machine have it. The static half runs
everywhere, and `GateSourceTests` keeps a cheap tripwire on the gate bodies
themselves so a gutted gate is caught even on a machine that skips.

The template is read once for the whole module (`_CACHE`) and shared by
every case; nothing here mutates it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "assets"
    / "scripts"
    / "dashboard.py"
)
# Loaded for its side effect only: `dashboard.py` puts its own directory at
# the front of `sys.path`, which is what makes `from ledgerlib...` below
# resolve to the bundle's copy rather than to anything installed. Every
# other suite in this directory bootstraps the same way.
SPEC = importlib.util.spec_from_file_location("dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)

from ledgerlib.build import TEMPLATE_PATH, serialize_payload  # noqa: E402


# Design spec section 1.3, verbatim. Assembled by concatenation because the
# line carries both quote characters; the pieces join into exactly one line
# of the template.
CSP_META = (
    '<meta http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; img-src data:; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'\">"
)

# Design spec section 2's closing paragraph, verbatim and on one line: the
# island the template ships with before any build touches it.
STATIC_ISLAND = (
    '{"payload_schema":1,"mode":"static","generated_at":null,'
    '"tool_version":null,"lang":null,"ledger":null,"computed":null}'
)

PANEL_IDS = (
    "overview",
    "inventory",
    "changes",
    "provenance",
    "rollback",
    "backlog",
    "decisions",
    "materials",
    "help",
)

# Task 4's six renderers.
TASK_4_RENDERERS = (
    "function renderOverview(section)",
    "function renderInventory(section, state)",
    "function renderBacklog(section)",
    "function renderDecisions(section, state)",
    "function renderMaterials(section)",
    "function renderHelp(section)",
)

# Task 5's three. With these, every panel in `PANELS` has a renderer and the
# instructional fall-through in `renderPanels` is unreachable -- it stays as
# the guard for a tenth panel added without one.
TASK_5_RENDERERS = (
    "function renderChanges(section)",
    "function renderProvenance(section)",
    "function renderRollback(section)",
)

# The severity vocabulary, worst first. The rank is the index, so this tuple
# *is* the ordering `sortBySeverityThenRecency` applies.
SEVERITY_ORDER = ("error", "warning", "info")

# Design spec section 10's five drift states, mapped onto the three
# severities. `DRIFTED` and `MISSING` are the two that mean the ledger no
# longer describes the disk; `UNVERIFIABLE` means nobody could tell, which is
# a warning rather than a failure; the other two are the quiet outcomes.
DRIFT_SEVERITY = {
    "IN_PLACE": "info",
    "DRIFTED": "error",
    "REVERTED": "info",
    "MISSING": "error",
    "UNVERIFIABLE": "warning",
}

# Design spec section 11's three rollback indicators, same three severities.
INDICATOR_SEVERITY = {
    "HEALTHY": "info",
    "AT_RISK": "warning",
    "BROKEN": "error",
}

# `rollback.tested` from `ledger.schema.json`, mapped the same way. An
# untested rollback is a warning rather than a note on purpose: the record
# promises an undo nobody has ever exercised, and reading that as quiet is
# how an untested promise ends up believed. A rollback that was tried and
# failed is the error -- the undo exists and is known not to work.
TESTED_SEVERITY = {
    "NOT_TESTED": "warning",
    "PARTIAL": "warning",
    "PASSED": "info",
    "FAILED": "error",
}

# The six results a `RUN` may record. Exactly one of them -- `VALIDATED` --
# says the change was applied, checked, and did what it claimed; the Changes
# panel ranks every other result as a finding.
RUN_RESULTS = (
    "VALIDATED",
    "VALIDATED WITH CAVEATS",
    "PARTIALLY VALIDATED",
    "NOT VALIDATED",
    "FAILED",
    "ROLLBACK COMPLETED",
)

# The two closed vocabularies the Help panel glosses and the record panels
# use as tooltips, straight from `ledger.schema.json`.
CLASSIFICATIONS = (
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
)

RECORD_STATUSES = (
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
)

# Every i18n key Task 4 adds, named here rather than only counted, so that
# deleting one fails a test that says which.
TASK_4_KEYS = (
    "overview.cards",
    "overview.unreachable",
    "card.active_changes",
    "card.active_changes.note",
    "card.drift",
    "card.drift.note",
    "card.rollbacks_at_risk",
    "card.rollbacks_at_risk.note",
    "card.expired_evidence",
    "card.expired_evidence.note",
    "card.unreachable_projects",
    "card.unreachable_projects.note",
    "card.unavailable",
    "card.unavailable.drift",
    "card.unavailable.previews",
    "card.unavailable.expired_evidence",
    "table.kind",
    "table.name",
    "table.anchor",
    "table.state",
    "table.origin",
    "table.portable",
    "table.record",
    "table.title",
    "table.status",
    "table.classification",
    "table.reason",
    "table.revisit",
    "table.updated",
    "table.evidence",
    "table.links",
    "value.yes",
    "value.no",
    "value.unknown",
    "filter.kind",
    "filter.all",
    "backlog.revisit_due",
    "backlog.trigger_only",
    "decisions.superseded_by",
    "decisions.supersedes",
    "materials.expired",
    "materials.expiry_unchecked",
    "materials.source_is_text",
    "help.states",
    "help.classifications",
    "help.statuses",
    "help.commands",
    "help.cmd.verify",
    "help.cmd.scan",
    "help.cmd.drift",
    "help.cmd.rollback_preview",
    "help.cmd.build",
)

# Every i18n key Task 5 adds, named for the same reason Task 4's are: the
# parity test says only that the two dictionaries agree, and two dictionaries
# that lost the same key agree perfectly.
TASK_5_KEYS = (
    "table.key",
    "table.before",
    "table.after",
    "table.reversible",
    "table.residual",
    "value.none",
    "changes.intro",
    "changes.caption",
    "changes.targets",
    "changes.result",
    "changes.proposal",
    "changes.authorized",
    "changes.deviations",
    "changes.self_reported",
    "provenance.intro",
    "provenance.runs",
    "provenance.proposal",
    "provenance.material",
    "provenance.no_material",
    "rollback.intro",
    "rollback.indicator",
    "rollback.backup",
    "rollback.tested",
    "rollback.restorable",
    "rollback.cannot_restore",
    "rollback.not_touched",
    "rollback.residual",
    "rollback.no_backup_heading",
    "rollback.no_backup",
    "rollback.preview_missing",
    "help.results",
)

# `class: "a b"` literals in the shell whose last token ends in `-` are
# completed at runtime from a closed family. The families are declared here
# so the stylesheet seam can still be checked end to end.
DYNAMIC_CLASS_FAMILIES = {
    "status-": SEVERITY_ORDER,
    "card-": SEVERITY_ORDER,
    "row-": SEVERITY_ORDER,
    "vocab-": SEVERITY_ORDER,
    "run-": SEVERITY_ORDER,
}

CLASS_LITERAL = re.compile(r'class:\s*"([^"]*)"')
STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.DOTALL)

# `DRIFT_STATES` plus `ROLLBACK_INDICATORS` from `ledgerlib.constants`: the
# canonical vocabulary that stays English on screen (design spec section 5)
# and therefore needs a translated tooltip in every dictionary.
CANONICAL_STATES = (
    "IN_PLACE",
    "DRIFTED",
    "REVERTED",
    "MISSING",
    "UNVERIFIABLE",
    "HEALTHY",
    "AT_RISK",
    "BROKEN",
)

# Design spec section 1.2's list, minus `javascript:` which is checked
# case-insensitively on its own below.
PROHIBITED = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
    "srcdoc",
    'setTimeout("',
    'setInterval("',
)

# Design spec section 1.3: no network scheme may appear anywhere, so that
# "issues no request" is readable off the file.
NETWORK_SCHEMES = ("http://", "https://")

ISLAND = re.compile(
    r'<script type="application/json" id="([A-Za-z0-9_-]+)">(.*?)</script>',
    re.DOTALL,
)
HREF = re.compile(
    r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE
)

# Every attribute a browser will dereference on its own, not just `src`.
# Case-insensitive because HTML attribute names are: `SRC=` fetches exactly
# as `src=` does, and a template that spelled it that way would have walked
# past the old pattern.
FETCHING_ATTRIBUTE = re.compile(
    r"(?<![\w-])(src|srcset|poster|background|ping|formaction|data|action)\s*=",
    re.IGNORECASE,
)

# `url(...)` is the stylesheet's own fetch. A single `url(data:...)` would be
# harmless and a single `url(https://...)` would not, so the rule is the
# blunt one: the function does not appear.
CSS_URL = "url("

SIZE_BUDGET = 400 * 1024

# --- the executable half -----------------------------------------------
#
# Case tables shared by the node harness. Each row is (kind, value,
# expected); `kind` says how the harness should materialize `value` on the
# JavaScript side, because a JSON table cannot carry a non-string input.

NODE = shutil.which("node")

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOM_STUB = FIXTURES / "dom_stub.js"

SAFE_HREF_CASES = (
    # The two shapes the gate exists to pass through.
    ("string", "#x", "#x"),
    ("string", "#panel=rollback&lang=pt-BR", "#panel=rollback&lang=pt-BR"),
    ("string", "file:///C:/x", "file:///C:/x"),
    # The scheme that would turn a rendered link into code, in the three
    # spellings a browser treats as identical and a naive prefix test does
    # not: exact, leading whitespace, mixed case.
    ("string", "javascript:alert(1)", "#"),
    ("string", " javascript:x", "#"),
    ("string", "JavaScript:x", "#"),
    # `file:` in any case but the one this tool writes.
    ("string", "File://x", "#"),
    ("string", "FILE://x", "#"),
    # A UNC host: a network fetch wearing a local scheme, in both spellings.
    ("string", "file://host/share", "#"),
    ("string", "file:////server/share", "#"),
    # Everything else.
    ("string", "http://example.test/a", "#"),
    ("string", "data:text/html,x", "#"),
    ("string", "", "#"),
    ("null", None, "#"),
    ("number", None, "#"),
)

ATTR_ALLOWED_CASES = (
    ("onclick", False),
    ("ONCLICK", False),
    ("OnClick", False),
    ("onerror", False),
    # Not a handler, but a lever: `style` would let ledger content paint,
    # `src`/`srcdoc` would let it fetch, and `id` would let it mint a global
    # name a later lookup could pick up instead of the chrome's own element.
    ("style", False),
    ("src", False),
    ("srcdoc", False),
    ("id", False),
    ("formaction", False),
    ("class", True),
    ("aria-label", True),
    ("data-x", True),
    ("title", True),
    ("href", True),
    ("role", True),
)

TAG_CASES = (
    # Coerced: the elements whose mere presence in the document is a
    # capability, in both cases, plus anything that is not a tag name.
    ("string", "script", "SPAN"),
    ("string", "SCRIPT", "SPAN"),
    ("string", "iframe", "SPAN"),
    ("string", "object", "SPAN"),
    ("string", "embed", "SPAN"),
    ("string", "link", "SPAN"),
    ("string", "meta", "SPAN"),
    ("string", "base", "SPAN"),
    ("string", "style", "SPAN"),
    ("string", "form", "SPAN"),
    ("string", "", "SPAN"),
    ("string", "my-tag", "SPAN"),
    ("string", "DIV", "SPAN"),
    ("null", None, "SPAN"),
    ("number", None, "SPAN"),
    # Built as asked.
    ("string", "div", "DIV"),
    ("string", "h2", "H2"),
    ("string", "code", "CODE"),
    # Task 6's action model needs a real one of these, so it is not on the
    # refusal list and this row is what keeps it off.
    ("string", "textarea", "TEXTAREA"),
)

# Appended inside the shell's own IIFE, as its last statement, so the gates
# can be called from outside a closure that deliberately exports nothing.
# It runs only after a successful boot: if the shell takes a fatal path the
# export never happens and the probe says so.
SHELL_EXPORT = (
    "  globalThis.__AIO_EXPORTS__ = "
    "{ safeHref: safeHref, attrAllowed: attrAllowed, h: h };\n"
)
IIFE_CLOSE = "}());"

PROBE = r"""
(function () {
  var api = globalThis.__AIO_EXPORTS__;
  var cases = globalThis.__AIO_CASES__;
  var table = { tabs: null, safeHref: [], attrAllowed: [], tag: [] };
  var bad = [];

  function materialize(kind, value) {
    if (kind === "null") { return null; }
    if (kind === "number") { return 42; }
    return value;
  }

  function report(code) {
    process.stdout.write(
      JSON.stringify({ ok: bad.length === 0, failures: bad, table: table }, null, 2) + "\n"
    );
    process.exit(code);
  }

  if (!api) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }

  /* Proves the table below was produced by a shell that actually rendered,
     not by a file that merely parsed. */
  table.tabs = document.getElementById("aio-nav").childNodes.length;
  if (table.tabs !== 9) { bad.push("nav built " + table.tabs + " tabs, want 9"); }

  cases.safeHref.forEach(function (row) {
    var got = api.safeHref(materialize(row[0], row[1]));
    table.safeHref.push([row[0], row[1], row[2], got]);
    if (got !== row[2]) {
      bad.push("safeHref(" + row[0] + " " + JSON.stringify(row[1]) + ") = " +
               JSON.stringify(got) + ", want " + JSON.stringify(row[2]));
    }
  });

  cases.attrAllowed.forEach(function (row) {
    var got = api.attrAllowed(row[0]);
    table.attrAllowed.push([row[0], row[1], got]);
    if (got !== row[1]) {
      bad.push("attrAllowed(" + JSON.stringify(row[0]) + ") = " + got +
               ", want " + row[1]);
    }
  });

  cases.tag.forEach(function (row) {
    var got = api.h(materialize(row[0], row[1]), {}).tagName;
    table.tag.push([row[0], row[1], row[2], got]);
    if (got !== row[2]) {
      bad.push("h(" + row[0] + " " + JSON.stringify(row[1]) + ") built " + got +
               ", want " + row[2]);
    }
  });

  report(bad.length === 0 ? 0 : 1);
}());
"""

# --- the built-mode fixture --------------------------------------------
#
# A ledger small enough to read, carrying one of every record type plus the
# three shapes the panels have to get right: an item that DRIFTED, a run
# whose rollback preview is BROKEN, and a backlog entry whose revisit date
# has passed. It is hand-written rather than built by `dashboard.py` on
# purpose -- the point is to pin what the *shell* does with a known payload,
# so the payload must not move when the environment does.

DIGEST = "sha256:" + "0" * 64

# A second digest, so a target's before and after are visibly different and
# the twelve-character abbreviation has something to abbreviate. The repeated
# pair makes the expected prefix readable in an assertion rather than a count
# of zeroes.
DIGEST_AFTER = "sha256:" + "9f" * 32

# The stored-XSS regression, verbatim. `serialize_payload` rewrites every
# `<` as a JSON escape, so this string cannot close the island; the
# assertion below is that the shell then renders it as one literal text node
# and creates no element for it.
XSS_TITLE = "</script><script>x"

FIXTURE_LEDGER = {
    "schema_version": "1.0",
    "ledger_id": "fixture",
    "scope": "project",
    "language": "en",
    "client": "claude-code",
    "adapter_version": 2,
    "created": "2026-07-01",
    "updated": "2026-07-31",
    "id_authority": True,
    "sequences": {"MAT": 2, "PROP": 2, "RUN": 4, "ADR": 2, "BASE": 1},
    "known_projects": [
        {
            "project_root": "/gone",
            "ledger_path": "/gone/.agent-audit/ledger.json",
            "last_seen": "2026-07-01",
            "last_digest": DIGEST,
            "status": "UNREACHABLE",
        }
    ],
    "records": [
        {
            "id": "MAT-2026-000",
            "type": "MATERIAL",
            "title": XSS_TITLE,
            "status": "ANALYZED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-02",
            "updated": "2026-07-02",
            "file": "records/MAT-2026-000.md",
            "links": {},
            "evidence": [
                {
                    "source": "vendor documentation, page 4",
                    "kind": "vendor documentation",
                    "verified_on": "2026-01-02",
                    "time_sensitive": True,
                    "expires_on": "2026-04-02",
                }
            ],
        },
        {
            "id": "PROP-2026-000",
            "type": "PROPOSAL",
            "title": "Pin the marketplace tag",
            "status": "DECIDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-03",
            "updated": "2026-07-03",
            "file": "records/PROP-2026-000.md",
            "links": {"materials": ["MAT-2026-000"]},
            "evidence": [],
        },
        {
            "id": "RUN-2026-000",
            "type": "RUN",
            "title": "Pin the marketplace tag",
            "status": "IMPLEMENTED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-04",
            "updated": "2026-07-04",
            "file": "records/RUN-2026-000.md",
            "links": {"materials": ["MAT-2026-000"]},
            "evidence": [],
            "proposal": "PROP-2026-000",
            "authorization": {"quote": "go ahead", "recorded_on": "2026-07-04"},
            "result": "VALIDATED",
            "targets": [
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "kind": "instruction-file",
                    "before_digest": DIGEST,
                    "after_digest": DIGEST,
                    "reversible": True,
                    "residual_effect": None,
                }
            ],
            "backup": {"digest": DIGEST, "verified": True},
            "rollback": {"tested": "NOT_TESTED"},
            "self_reported": ["targets"],
        },
        # The second material and proposal exist for one reason: the
        # Provenance chain has to be provably per-run. Both runs below touch
        # `$USER_CONFIG/settings.json`, and each must reach its *own*
        # evidence through its own proposal -- a chain that merged them would
        # still look plausible on screen.
        {
            "id": "MAT-2026-001",
            "type": "MATERIAL",
            "title": "A second reading of the same subject",
            "status": "ANALYZED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-05-05",
            "updated": "2026-05-05",
            "file": "records/MAT-2026-001.md",
            "links": {},
            "evidence": [
                {
                    "source": "release notes, second edition",
                    "kind": "vendor documentation",
                    "verified_on": "2026-05-05",
                    "time_sensitive": True,
                    "expires_on": "2027-05-05",
                }
            ],
        },
        {
            "id": "PROP-2026-001",
            "type": "PROPOSAL",
            "title": "Rewrite the hook command",
            "status": "DECIDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-02",
            "updated": "2026-07-02",
            "file": "records/PROP-2026-001.md",
            "links": {"materials": ["MAT-2026-001"]},
            "evidence": [],
        },
        # The deviating run, and the oldest of the four: it must still sort
        # above every clean run, which is the only way to tell severity-first
        # ordering from recency-first ordering by looking at the panel.
        {
            "id": "RUN-2026-001",
            "type": "RUN",
            "title": "Rewrite the hook command",
            "status": "IMPLEMENTED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-02",
            "updated": "2026-07-02",
            "file": "records/RUN-2026-001.md",
            "links": {},
            "evidence": [],
            "proposal": "PROP-2026-001",
            "authorization": {"quote": "do it", "recorded_on": "2026-07-02"},
            "result": "PARTIALLY VALIDATED",
            "targets": [
                # Shares an anchor with RUN-2026-000, and carries no key, so
                # the two runs land under one Provenance entry.
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "kind": "instruction-file",
                    "before_digest": DIGEST,
                    "after_digest": DIGEST_AFTER,
                    "reversible": True,
                    "residual_effect": None,
                },
                {
                    "anchor": "$USER_CONFIG/hooks/guard.js",
                    "kind": "json field",
                    "before_digest": None,
                    "after_digest": DIGEST_AFTER,
                    "reversible": True,
                    "residual_effect": None,
                    "key": "/hooks/0/command",
                },
                # The stored-XSS regression, moved into a run target: an
                # anchor and a residual effect are both ledger strings that
                # reach the page through a different renderer than the
                # material title does.
                {
                    "anchor": XSS_TITLE,
                    "kind": "markdown document",
                    "before_digest": DIGEST,
                    "after_digest": None,
                    "reversible": False,
                    "residual_effect": XSS_TITLE,
                },
            ],
            "backup": {"digest": DIGEST, "verified": True},
            "rollback": {"tested": "PARTIAL"},
            "self_reported": ["targets", "result", "backup", "rollback.tested"],
        },
        # A run with a plan deviation and an otherwise clean result: the
        # second of the two triggers that make a run a finding.
        {
            "id": "RUN-2026-002",
            "type": "RUN",
            "title": "Add the second hook",
            "status": "IMPLEMENTED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-06",
            "updated": "2026-07-06",
            "file": "records/RUN-2026-002.md",
            "links": {"materials": ["MAT-2026-001"]},
            "evidence": [],
            "proposal": "PROP-2026-001",
            "authorization": {"quote": "go on", "recorded_on": "2026-07-06"},
            "result": "VALIDATED",
            "deviations": ["the second hook was left out"],
            "targets": [
                {
                    "anchor": "$USER_CONFIG/CLAUDE.md",
                    "kind": "instruction-file",
                    "before_digest": DIGEST,
                    "after_digest": DIGEST_AFTER,
                    "reversible": True,
                    "residual_effect": None,
                }
            ],
            # No backup: this run and the one below are what the Rollback
            # panel has to be honest about rather than silently omit.
            "backup": None,
            "rollback": {"tested": "NOT_TESTED"},
            "self_reported": ["targets"],
        },
        # The newest run of the four, and undone: it must sort *below* both
        # findings despite being the most recent, because a change that was
        # rolled back is history rather than a fault.
        {
            "id": "RUN-2026-003",
            "type": "RUN",
            "title": "Pin the skill version",
            "status": "ROLLBACK",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-07",
            "updated": "2026-07-07",
            "file": "records/RUN-2026-003.md",
            "links": {},
            "evidence": [],
            "proposal": "PROP-2026-001",
            "authorization": {"quote": "try it", "recorded_on": "2026-07-07"},
            "result": "ROLLBACK COMPLETED",
            "targets": [
                {
                    "anchor": "$USER_CONFIG/skills/drifted-skill",
                    "kind": "skill",
                    "before_digest": DIGEST,
                    "after_digest": DIGEST,
                    "reversible": True,
                    "residual_effect": None,
                }
            ],
            "backup": None,
            "rollback": {"tested": "PASSED"},
            "self_reported": ["targets"],
        },
        {
            "id": "ADR-2026-000",
            "type": "ADR",
            "title": "Version source of truth",
            "status": "SUPERSEDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-05",
            "updated": "2026-07-05",
            "file": "records/ADR-2026-000.md",
            "links": {"adrs": ["ADR-2026-001"]},
            "evidence": [],
        },
        {
            "id": "ADR-2026-001",
            "type": "ADR",
            "title": "Version source of truth, second take",
            "status": "DECIDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-06",
            "updated": "2026-07-06",
            "file": "records/ADR-2026-001.md",
            "links": {},
            "evidence": [],
        },
    ],
    "baselines": [
        {
            "id": "BASE-2026-000",
            "captured_on": "2026-07-03",
            "client": "claude-code",
            "adapter_version": 2,
            "items": [
                {
                    "kind": "instruction-file",
                    "name": "CLAUDE.md",
                    "anchor": "$USER_CONFIG/CLAUDE.md",
                    "digest": DIGEST,
                    "attributes": {"scope": "user"},
                    "origin": "pre-existing",
                    "state": "present",
                    "portable": True,
                },
                {
                    "kind": "skill",
                    "name": "drifted-skill",
                    "anchor": "$USER_CONFIG/skills/drifted-skill",
                    "digest": DIGEST,
                    "attributes": {},
                    "origin": "PROP-2026-000",
                    "state": "present",
                    "portable": False,
                },
                {
                    "kind": "hook",
                    "name": "guard",
                    "anchor": "$USER_CONFIG/hooks/guard.js",
                    "digest": None,
                    "attributes": {},
                    "origin": "pre-existing",
                    "state": "not_present",
                    "portable": True,
                },
            ],
        }
    ],
    # Input order is deliberately the wrong one: the `info` entry is first
    # and the overdue `warning` entry second, so a panel that renders in
    # ledger order and a panel that sorts are distinguishable.
    "backlog": [
        {
            "id": "MAT-2026-000",
            "classification": "MONITOR",
            "reason": "waiting on the upstream fix",
            "revisit_trigger": "upstream ships the fix",
            "revisit_after": None,
        },
        {
            "id": "MAT-2026-000",
            "classification": "NEEDS MORE EVIDENCE",
            "reason": "one vendor page only",
            "revisit_trigger": None,
            "revisit_after": "2026-01-15",
        },
    ],
}

FIXTURE_COMPUTED = {
    "drift": {
        "baselines": [
            {
                "id": "BASE-2026-000",
                "client": "claude-code",
                "items": [
                    {
                        "kind": "instruction-file",
                        "name": "CLAUDE.md",
                        "anchor": "$USER_CONFIG/CLAUDE.md",
                        "scope": "user",
                        "recorded_state": "present",
                        "state": "IN_PLACE",
                        "reason": None,
                    },
                    {
                        "kind": "skill",
                        "name": "drifted-skill",
                        "anchor": "$USER_CONFIG/skills/drifted-skill",
                        "scope": None,
                        "recorded_state": "present",
                        "state": "DRIFTED",
                        "reason": None,
                    },
                    {
                        "kind": "hook",
                        "name": "guard",
                        "anchor": "$USER_CONFIG/hooks/guard.js",
                        "scope": None,
                        "recorded_state": "not_present",
                        "state": "IN_PLACE",
                        "reason": None,
                    },
                ],
            }
        ],
        "runs": [
            {
                "id": "RUN-2026-000",
                "targets": [
                    {
                        "kind": "instruction-file",
                        "anchor": "$USER_CONFIG/settings.json",
                        "state": "DRIFTED",
                        "reason": None,
                    }
                ],
            }
        ],
        "summary": {
            "DRIFTED": 2,
            "IN_PLACE": 2,
            "MISSING": 0,
            "REVERTED": 0,
            "UNVERIFIABLE": 0,
        },
    },
    # One preview per RUN that kept a backup, which is two of the four runs.
    # Between them they cover the two shapes the panel must get right: a
    # BROKEN preview whose three other sets are empty -- the case that proves
    # all four headings render whatever the sets hold -- and an AT_RISK
    # preview with every set populated.
    "previews": {
        "RUN-2026-000": {
            "run": "RUN-2026-000",
            "indicator": "BROKEN",
            "backup": {"verified": False, "reason": "backup_missing"},
            "will_be_restored": [],
            "will_not_change": [],
            "cannot_be_restored": [
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "kind": "instruction-file",
                    "state": "DRIFTED",
                    "reason": "backup_missing",
                }
            ],
            "residual_effects": [],
        },
        "RUN-2026-001": {
            "run": "RUN-2026-001",
            "indicator": "AT_RISK",
            "backup": {"verified": True, "reason": None},
            "will_be_restored": [
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "kind": "instruction-file",
                    "state": "IN_PLACE",
                }
            ],
            "will_not_change": [
                {
                    "anchor": "$USER_CONFIG/hooks/guard.js",
                    "kind": "json field",
                    "state": "REVERTED",
                }
            ],
            "cannot_be_restored": [
                {
                    "anchor": XSS_TITLE,
                    "kind": "markdown document",
                    "state": "MISSING",
                    "reason": "MISSING",
                }
            ],
            # Verbatim, as `rollback_preview` records it: the string the
            # target itself carried.
            "residual_effects": [XSS_TITLE],
        },
    },
    "expired_evidence": [
        {
            "record": "MAT-2026-000",
            "source": "vendor documentation, page 4",
            "expires_on": "2026-04-02",
        }
    ],
    "unreachable_projects": ["/gone"],
}

FIXTURE_PAYLOAD = {
    "payload_schema": 1,
    "mode": "built",
    "generated_at": "2026-07-31T00:00:00Z",
    "tool_version": "0.4.0",
    "lang": "en",
    "ledger": FIXTURE_LEDGER,
    "computed": FIXTURE_COMPUTED,
}

# Design spec section 2's no-Python degradation path: the same ledger, hand
# wrapped in a static envelope, with no `computed` key at all. This is the
# payload `references/DASHBOARD.md` tells a reader to assemble when there is
# no Python on the machine, so it is a shape the shell really meets.
STATIC_FIXTURE_PAYLOAD = {
    "payload_schema": 1,
    "mode": "static",
    "generated_at": None,
    "tool_version": None,
    "lang": None,
    "ledger": FIXTURE_LEDGER,
    "computed": None,
}

# Design spec section 14: a build that succeeded with a sub-computation that
# did not. The key holds an error message instead of a report, and the panel
# that depends on it must name the missing guarantee rather than show a zero.
DEGRADED_FIXTURE_PAYLOAD = dict(
    FIXTURE_PAYLOAD,
    computed=dict(FIXTURE_COMPUTED, drift={"error": "unknown client 'nope'"}),
)

# --- the I1 fixture: ledger strings used as plain-object keys -----------
#
# Every plain object literal in the shell (`{}`) inherits from
# Object.prototype, so a ledger-supplied string of "constructor",
# "toString", or similar can read back a function instead of undefined from
# a lookup keyed on it. This ledger carries exactly the two shapes a
# reviewer named: an ADR record whose own id is "toString" (the read side --
# `decisionRow` looks up `replaced[record.id]`), and a second ADR, marked
# SUPERSEDED, whose `links.adrs` names "constructor" (the write side --
# `supersessionIndex` does `index[other] = []; index[other].push(...)`,
# which throws on a plain `{}` because `index["constructor"]` is already the
# truthy inherited Function and has no `.push`). The computed report adds a
# drift summary keyed "toString" and a baseline item whose drift state is
# "constructor", for the two lookups in `driftIndicator` and
# `inventorySeverity`.
MALICIOUS_KEY_FIXTURE_LEDGER = {
    "schema_version": "1.0",
    "ledger_id": "malicious-keys",
    "scope": "project",
    "language": "en",
    "client": "claude-code",
    "adapter_version": 2,
    "created": "2026-07-01",
    "updated": "2026-07-31",
    "id_authority": True,
    "sequences": {"MAT": 0, "PROP": 0, "RUN": 0, "ADR": 2, "BASE": 1},
    "known_projects": [],
    "records": [
        {
            "id": "toString",
            "type": "ADR",
            "title": "A record id that collides with Object.prototype.toString",
            "status": "DECIDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-05",
            "updated": "2026-07-05",
            "file": "records/ADR-toString.md",
            "links": {},
            "evidence": [],
        },
        {
            "id": "ADR-2026-CTOR",
            "type": "ADR",
            "title": "A superseding record whose links.adrs names constructor",
            "status": "SUPERSEDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-06",
            "updated": "2026-07-06",
            "file": "records/ADR-2026-CTOR.md",
            "links": {"adrs": ["constructor"]},
            "evidence": [],
        },
    ],
    "baselines": [
        {
            "id": "BASE-2026-000",
            "captured_on": "2026-07-03",
            "client": "claude-code",
            "adapter_version": 2,
            "items": [
                {
                    "kind": "instruction-file",
                    "name": "poisoned",
                    "anchor": "$USER_CONFIG/poisoned",
                    "digest": DIGEST,
                    "attributes": {},
                    "origin": "pre-existing",
                    "state": "present",
                    "portable": True,
                }
            ],
        }
    ],
    "backlog": [],
}

MALICIOUS_KEY_FIXTURE_COMPUTED = {
    "drift": {
        "baselines": [
            {
                "id": "BASE-2026-000",
                "client": "claude-code",
                "items": [
                    {
                        "kind": "instruction-file",
                        "name": "poisoned",
                        "anchor": "$USER_CONFIG/poisoned",
                        "scope": None,
                        "recorded_state": "present",
                        # Not one of the five real drift states: this is the
                        # `inventorySeverity` case -- an unrecognised state
                        # must fall through to the unknown/undefined
                        # treatment (a plain "row-warning"), never to a class
                        # built by concatenating a stringified function.
                        "state": "constructor",
                        "reason": None,
                    }
                ],
            }
        ],
        "runs": [],
        # The five real states are all zero; "toString" carries a large
        # count that must NOT reach the Drifted card, because
        # `DRIFT_SEVERITY` has no *own* "toString" key.
        "summary": {
            "IN_PLACE": 0,
            "DRIFTED": 0,
            "MISSING": 0,
            "REVERTED": 0,
            "UNVERIFIABLE": 0,
            "toString": 999999,
        },
    },
    "previews": {},
    "expired_evidence": [],
    "unreachable_projects": [],
}

MALICIOUS_KEY_FIXTURE_PAYLOAD = {
    "payload_schema": 1,
    "mode": "built",
    "generated_at": "2026-07-31T00:00:00Z",
    "tool_version": "0.4.0",
    "lang": "en",
    "ledger": MALICIOUS_KEY_FIXTURE_LEDGER,
    "computed": MALICIOUS_KEY_FIXTURE_COMPUTED,
}

# A dedicated probe rather than a reuse of PANEL_PROBE: this fixture is
# about facts PANEL_PROBE never gathers -- whether every one of the nine
# panel sections exists at all, whether the footer got populated, and the
# actual CSS class a poisoned inventory row was built with -- not the six
# panels' usual content facts.
MALICIOUS_KEY_PROBE = r"""
(function () {
  var bad = [];

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  function classes(node) {
    var value = node.attributes ? node.attributes["class"] : null;
    return typeof value === "string" ? value.split(" ") : [];
  }

  function byClass(root, name) {
    var out = [];
    walk(root, function (node) {
      if (classes(node).indexOf(name) !== -1) { out.push(node); }
    });
    return out;
  }

  function byTag(root, tag) {
    var out = [];
    walk(root, function (node) { if (node.tagName === tag) { out.push(node); } });
    return out;
  }

  function bodyRows(root) {
    var bodies = byTag(root, "TBODY");
    if (bodies.length === 0) { return []; }
    return byTag(bodies[0], "TR");
  }

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  var facts = { failures: bad };

  if (!globalThis.__AIO_EXPORTS__) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }

  var panelIds = globalThis.__AIO_PANEL_IDS__ || [];
  facts.panelsPresent = {};
  panelIds.forEach(function (name) {
    facts.panelsPresent[name] = Boolean(document.getElementById("aio-panel-" + name));
  });

  facts.tabs = document.getElementById("aio-nav").childNodes.length;

  var footer = document.getElementById("aio-footer");
  facts.footerEntries = footer ? footer.childNodes.length : 0;

  var overview = document.getElementById("aio-panel-overview");
  facts.driftCard = null;
  byClass(overview, "card").forEach(function (card) {
    var label = byClass(card, "card-label")[0];
    if (label && label.textContent === "Drifted items") {
      var counts = byClass(card, "card-count");
      facts.driftCard = {
        count: counts.length ? counts[0].textContent : null,
        severity: classes(card).filter(function (name) {
          return name.lastIndexOf("card-", 0) === 0 && name !== "card-count";
        })
      };
    }
  });

  var inventory = document.getElementById("aio-panel-inventory");
  facts.inventoryRows = bodyRows(inventory).map(function (row) {
    return { classes: classes(row), text: row.textContent };
  });

  var decisions = document.getElementById("aio-panel-decisions");
  facts.decisionsRows = bodyRows(decisions).length;
  facts.decisionsText = decisions.textContent;

  report(bad.length === 0 ? 0 : 1);
}());
"""

# The panel probe. Unlike `PROBE` it does not hold its own expectations: it
# walks the rendered tree and reports facts, and the Python cases below do
# the comparing, so a regression is named by a test rather than by a line in
# a JSON blob. It still exits nonzero for the two failures that would make
# every fact vacuous -- a shell that never booted, and a panel that is not
# in the document at all.
PANEL_PROBE = r"""
(function () {
  var bad = [];

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  function classes(node) {
    var value = node.attributes ? node.attributes["class"] : null;
    return typeof value === "string" ? value.split(" ") : [];
  }

  function byClass(root, name) {
    var out = [];
    walk(root, function (node) {
      if (classes(node).indexOf(name) !== -1) { out.push(node); }
    });
    return out;
  }

  function byTag(root, tag) {
    var out = [];
    walk(root, function (node) { if (node.tagName === tag) { out.push(node); } });
    return out;
  }

  function textValues(root) {
    var out = [];
    walk(root, function (node) {
      if (node.tagName === "#TEXT") { out.push(node.text); }
    });
    return out;
  }

  function bodyRows(root) {
    var bodies = byTag(root, "TBODY");
    if (bodies.length === 0) { return []; }
    return byTag(bodies[0], "TR");
  }

  function panel(name) {
    var node = document.getElementById("aio-panel-" + name);
    if (!node) { bad.push("panel " + name + " is absent"); }
    return node;
  }

  /* The Changes and Rollback panels list runs as blocks rather than rows, so
     the facts a case wants are per block: the severity it was painted with,
     which fields carry a SELF-REPORTED badge, and the set headings under it.
     `data-field` is what makes the badge check exact -- the rendered tree
     names the field each badge belongs to. */
  function runBlocks(root) {
    return byClass(root, "run").map(function (node) {
      return {
        classes: classes(node),
        badges: byClass(node, "marker").map(function (badge) {
          return {
            field: badge.attributes["data-field"] || null,
            text: badge.textContent
          };
        }),
        headings: byTag(node, "H4").map(function (n) { return n.textContent; }),
        text: node.textContent
      };
    });
  }

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  var facts = { failures: bad };

  if (!globalThis.__AIO_EXPORTS__) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }

  var overview = panel("overview");
  var inventory = panel("inventory");
  var changes = panel("changes");
  var provenance = panel("provenance");
  var rollback = panel("rollback");
  var backlog = panel("backlog");
  var decisions = panel("decisions");
  var materials = panel("materials");
  var help = panel("help");
  if (bad.length !== 0) { report(2); }

  facts.overview = {
    cards: byClass(overview, "card").map(function (card) {
      var counts = byClass(card, "card-count");
      var unavailable = byClass(card, "unavailable");
      return {
        label: byClass(card, "card-label")[0].textContent,
        note: byClass(card, "card-note")[0].textContent,
        count: counts.length === 0 ? null : counts[0].textContent,
        unavailable: unavailable.length === 0 ? null : unavailable[0].textContent,
        severity: classes(card).filter(function (name) {
          return name.lastIndexOf("card-", 0) === 0 && name !== "card-count";
        }),
        href: byTag(card, "A").map(function (a) { return a.attributes.href; })
      };
    }),
    text: overview.textContent
  };

  facts.inventory = {
    rows: bodyRows(inventory).length,
    vocab: byClass(inventory, "vocab").map(function (node) {
      return node.textContent;
    }),
    tableClasses: byTag(inventory, "TABLE").map(function (node) {
      return node.attributes["class"];
    }),
    labels: byTag(inventory, "TD").map(function (node) {
      return node.attributes["data-label"];
    }),
    text: inventory.textContent
  };

  facts.changes = {
    runs: runBlocks(changes),
    headers: byTag(changes, "TH").map(function (n) { return n.textContent; }),
    labels: byTag(changes, "TD").map(function (n) {
      return n.attributes["data-label"];
    }),
    digests: byClass(changes, "digest").map(function (n) {
      return { text: n.textContent, title: n.attributes.title || null };
    }),
    vocab: byClass(changes, "vocab").map(function (n) { return n.textContent; }),
    texts: textValues(changes),
    anchors: byTag(changes, "A").length,
    text: changes.textContent
  };

  facts.provenance = {
    summaries: byTag(provenance, "SUMMARY").map(function (n) {
      return n.textContent;
    }),
    chains: byTag(provenance, "DETAILS").map(function (n) { return n.textContent; }),
    texts: textValues(provenance),
    anchors: byTag(provenance, "A").length,
    text: provenance.textContent
  };

  facts.rollback = {
    runs: runBlocks(rollback),
    headings: byTag(rollback, "H4").map(function (n) { return n.textContent; }),
    vocab: byClass(rollback, "vocab").map(function (n) { return n.textContent; }),
    texts: textValues(rollback),
    anchors: byTag(rollback, "A").length,
    text: rollback.textContent
  };

  facts.backlog = {
    rows: bodyRows(backlog).length,
    rowText: bodyRows(backlog).map(function (row) { return row.textContent; }),
    text: backlog.textContent
  };

  facts.decisions = {
    rows: bodyRows(decisions).length,
    text: decisions.textContent
  };

  facts.materials = {
    rows: bodyRows(materials).length,
    texts: textValues(materials),
    text: materials.textContent,
    anchors: byTag(materials, "A").length
  };

  facts.help = { text: help.textContent };

  facts.created = globalThis.__AIO_CREATED__;

  report(0);
}());
"""

_CACHE: dict[str, object] = {}


def extract_shell(text: str) -> str:
    """The shell script's body: everything inside the last `script` element.

    The two islands carry a `type` attribute; the shell's opening tag is the
    bare one and it is the last of the three, so "after the final bare
    opening, up to the next closing" is unambiguous. The count of both is
    pinned at three by `test_exactly_three_script_openings`, which is what
    keeps this arithmetic honest.
    """
    opening = "<script>"
    start = text.rindex(opening) + len(opening)
    return text[start : text.index("</script>", start)]


def slice_function(text: str, signature: str) -> str:
    """The source of one top-level function in the shell, brace-matched.

    Used by the tripwire tests so an assertion about `safeHref`'s body
    cannot be satisfied by a string that happens to live somewhere else in
    the file.
    """
    start = text.index(signature)
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError("unbalanced braces after " + signature)


def boot_shell(
    text: str,
    islands: dict,
    payload: dict,
    probe: str = PANEL_PROBE,
    extra_globals: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real shell over `payload` under node, and return the process.

    The same wiring `RuntimeGateTests` uses -- the template's own script, the
    DOM stub, one appended export line inside the shell's IIFE -- with the
    payload island replaced by `serialize_payload(payload)`. Serialized by
    the very function `build` calls, so the island the shell parses here has
    been through the section 1.1 escaping exactly as a real one would.

    `probe` defaults to `PANEL_PROBE` but callers with a different question to
    ask of the rendered tree -- `RuntimeMaliciousKeyPanelTests`, for one --
    can supply their own. `extra_globals` seeds additional `globalThis` names
    the alternate probe may need, JSON-serialized the same way the standard
    globals above it are.
    """
    shell = extract_shell(text).rstrip()
    assert shell.endswith(IIFE_CLOSE), "the shell is no longer a bare IIFE"
    wired = shell[: -len(IIFE_CLOSE)] + SHELL_EXPORT + IIFE_CLOSE + "\n"

    seeded = dict(islands)
    seeded["aio-payload"] = serialize_payload(payload)

    preamble_lines = [
        "globalThis.__AIO_ISLANDS__ = " + json.dumps(seeded) + ";",
        'globalThis.__AIO_HASH__ = "";',
        'globalThis.__AIO_LANG__ = "en";',
    ]
    for name, value in (extra_globals or {}).items():
        preamble_lines.append("globalThis." + name + " = " + json.dumps(value) + ";")
    preamble_lines.append("")
    preamble = "\n".join(preamble_lines)
    script = "\n".join(
        (DOM_STUB.read_text(encoding="utf-8"), preamble, wired, probe)
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shell_panels.js"
        path.write_text(script, encoding="utf-8")
        return subprocess.run(  # noqa: S603
            [str(NODE), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )


class ShellTemplateTestCase(unittest.TestCase):
    """Reads the template once and shares it with every case below."""

    text: str
    islands: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        if "text" not in _CACHE:
            _CACHE["text"] = TEMPLATE_PATH.read_text(encoding="utf-8")
            _CACHE["bytes"] = TEMPLATE_PATH.read_bytes()
            _CACHE["islands"] = {
                name: body for name, body in ISLAND.findall(str(_CACHE["text"]))
            }
        cls.text = _CACHE["text"]  # type: ignore[assignment]
        cls.raw = _CACHE["bytes"]  # type: ignore[attr-defined]
        cls.islands = _CACHE["islands"]  # type: ignore[assignment]


class DocumentHeadTests(ShellTemplateTestCase):
    """The declarations a browser reads before it reads anything else."""

    def test_csp_meta_appears_verbatim_exactly_once(self) -> None:
        """Design spec section 1.3's tag, character for character, once.

        Verbatim rather than parsed: a CSP that has been reformatted is a
        CSP someone edited, and this one is quoted in the spec as the text
        the document carries. One occurrence, so a second (weaker) policy
        cannot be appended below it.
        """
        self.assertEqual(self.text.count(CSP_META), 1)

    def test_html_element_declares_english(self) -> None:
        """The document's shipped language; the shell re-sets it per render."""
        self.assertIn('<html lang="en">', self.text)

    def test_charset_and_viewport_metas_are_present(self) -> None:
        """UTF-8 because the pt-BR dictionary is not ASCII; viewport for 360px."""
        self.assertIn('<meta charset="utf-8">', self.text)
        self.assertIn('<meta name="viewport"', self.text)


class PayloadIslandTests(ShellTemplateTestCase):
    """The one entry point ledger content has into the document."""

    def test_payload_island_appears_exactly_once(self) -> None:
        """`build`'s injection asserts the same count (design spec section 3)."""
        self.assertEqual(self.text.count('id="aio-payload"'), 1)

    def test_payload_island_holds_the_spec_static_default(self) -> None:
        """Byte-for-byte the string design spec section 2 names.

        Not "parses to the same object": `inject_payload` replaces this
        text by locating it, and a template whose default has drifted in
        whitespace is a template whose injection point has moved.
        """
        self.assertEqual(self.islands.get("aio-payload"), STATIC_ISLAND)

    def test_payload_island_parses_as_a_static_mode_envelope(self) -> None:
        """The no-browser sanity check: the shipped island is loadable JSON."""
        payload = json.loads(self.islands["aio-payload"])
        self.assertEqual(payload["payload_schema"], 1)
        self.assertEqual(payload["mode"], "static")
        self.assertIsNone(payload["ledger"])
        self.assertIsNone(payload["computed"])

    def test_payload_island_id_attribute_is_the_tags_last_attribute(self) -> None:
        """M9: `id="aio-payload"` must stay the tag's LAST attribute before `>`.

        `inject_payload` locates the splice point by scanning forward from
        the marker for the first `>` (a comment beside that scan, and a
        mirror comment on this very tag, both say so). If a later attribute
        were added after the marker, that scan would still stop at the
        first `>` it finds -- which would then belong to the wrong
        attribute -- and corrupt the splice. This regexes the actual
        shipped opening tag rather than merely asserting the marker string
        appears somewhere in the document, so a later attribute added after
        `id="aio-payload"` fails this test rather than silently reaching a
        build.
        """
        match = re.search(r'<script\b[^>]*id="aio-payload"[^>]*>', self.text)
        self.assertIsNotNone(match, "the aio-payload island tag was not found")
        tag = match.group(0)
        self.assertTrue(
            tag.endswith('id="aio-payload">'),
            f"id=\"aio-payload\" is not the tag's last attribute: {tag!r}",
        )


class ProhibitedTokenTests(ShellTemplateTestCase):
    """Design spec section 1.2: the sinks that are simply not in the file."""

    def test_no_dom_sink_or_dynamic_evaluation_token_appears(self) -> None:
        """Unconditional -- comments and string literals are not exempt.

        A shell that mentions a sink in a comment is a shell one edit away
        from calling it, and a grep that forgives comments is a grep that
        forgives the edit. The shell's own prose is written around this.
        """
        for token in PROHIBITED:
            with self.subTest(token=token):
                self.assertNotIn(token, self.text)

    def test_no_javascript_scheme_appears_in_any_case(self) -> None:
        """Case-insensitive: the scheme is case-insensitive to the browser."""
        self.assertIsNone(re.search("javascript:", self.text, re.IGNORECASE))

    def test_no_network_scheme_literal_appears(self) -> None:
        """Design spec section 1.3: the page cites record IDs, never URLs."""
        for scheme in NETWORK_SCHEMES:
            with self.subTest(scheme=scheme):
                self.assertNotIn(scheme, self.text)

    def test_no_fetching_attribute_appears(self) -> None:
        """Nothing for a browser to dereference on its own.

        Wider than the `src=` this replaced. `srcset`, `poster`,
        `background`, `ping`, `formaction`, `data`, and `action` all cause a
        request without anyone clicking anything, and "opens offline, issues
        no request" (design spec section 7 acceptance item 1) is a claim
        about all of them, not about `src` alone. Case-insensitive: the
        browser does not care how the attribute is spelled.
        """
        found = FETCHING_ATTRIBUTE.search(self.text)
        self.assertIsNone(found, found.group(0) if found else "")

    def test_no_css_url_function_appears(self) -> None:
        """The stylesheet's own way of fetching, closed off with the rest.

        Every colour is a custom property and there is no image, so the
        function has nothing legitimate to do here; a blanket refusal is
        cheaper to keep true than an allow-list of `data:` payloads.
        """
        self.assertNotIn(CSS_URL, self.text)

    def test_every_static_href_is_a_fragment(self) -> None:
        """The only navigation the shipped document offers is in-page.

        `safeHref` guards the hrefs the shell *builds*; this guards the ones
        it ships, which no gate ever sees.
        """
        found = HREF.findall(self.text)
        self.assertTrue(found, "the template should carry at least a skip link")
        for double, single, bare in found:
            value = double or single or bare
            with self.subTest(href=value):
                self.assertTrue(value.startswith("#"), value)

    def test_exactly_three_script_openings(self) -> None:
        """Two inert JSON islands and one shell script -- a pinned number.

        The islands are `type="application/json"` and so are never executed;
        counting them anyway is the point. The guard is not "scripts are
        dangerous", it is "the number of them is known", so that anything
        added later -- by a bad injection, a careless edit, a build that
        appends instead of replacing -- changes a number a test watches.
        """
        self.assertEqual(self.text.count("<script"), 3)
        self.assertEqual(self.text.count("</script>"), 3)


class DictionaryTests(ShellTemplateTestCase):
    """Design spec section 5: two dictionaries, one key set, no silent gaps."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dicts = json.loads(cls.islands["aio-i18n"])

    def test_i18n_island_carries_both_dictionaries(self) -> None:
        self.assertEqual(set(self.dicts), {"en", "pt-BR"})

    def test_dictionaries_have_identical_key_sets(self) -> None:
        """The whole reason this test exists: a gap is invisible at runtime.

        `t()` falls back to English for a missing key, so a half-translated
        dictionary renders a page that looks finished and speaks the wrong
        language in places. Nothing at runtime can notice; this can.
        """
        self.assertEqual(set(self.dicts["en"]), set(self.dicts["pt-BR"]))

    def test_every_value_is_a_non_empty_string(self) -> None:
        for code, dictionary in self.dicts.items():
            for key, value in dictionary.items():
                with self.subTest(lang=code, key=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())

    def test_every_panel_has_a_title_and_an_empty_state(self) -> None:
        """Empty states are instructional (design spec section 4), so they
        are content, not chrome, and every panel owes one in both languages."""
        for code, dictionary in self.dicts.items():
            for panel in PANEL_IDS:
                with self.subTest(lang=code, panel=panel):
                    self.assertIn("panel." + panel + ".title", dictionary)
                    self.assertIn("panel." + panel + ".empty", dictionary)

    def test_canonical_vocabulary_has_a_tooltip_in_both_languages(self) -> None:
        """Design spec section 5: the label stays English, the gloss does not."""
        for code, dictionary in self.dicts.items():
            for state in CANONICAL_STATES:
                with self.subTest(lang=code, state=state):
                    self.assertIn("state." + state + ".tip", dictionary)

    def test_canonical_state_names_survive_translation(self) -> None:
        """The English name appears inside its own pt-BR gloss's neighbours.

        Weaker but honest form: the pt-BR dictionary must not translate the
        state names themselves, which is checked where they are rendered --
        as literal keys. Here we assert only that no pt-BR tooltip is a copy
        of the English one, which would mean a key was filled by paste.
        """
        for state in CANONICAL_STATES:
            key = "state." + state + ".tip"
            with self.subTest(state=state):
                self.assertNotEqual(self.dicts["en"][key], self.dicts["pt-BR"][key])

    def test_i18n_island_contains_no_literal_less_than(self) -> None:
        """The same property design spec section 1.1 gives the payload island.

        The dictionaries are authored, not attacker-influenced, so this is
        belt and braces -- but the two islands live side by side and there
        is no reason for one to be weaker than the other. Placeholders like
        the one in the Inventory empty state are written `\\u003c`, which
        `JSON.parse` restores.
        """
        self.assertNotIn("<", self.islands["aio-i18n"])


class ShellStructureTests(ShellTemplateTestCase):
    """The skeleton the router and the Task 4-5 renderers will fill."""

    def test_every_panel_section_is_present(self) -> None:
        for panel in PANEL_IDS:
            with self.subTest(panel=panel):
                self.assertIn('data-panel="' + panel + '"', self.text)

    def test_shell_exposes_the_named_helpers(self) -> None:
        """The names Task 2's interface list promises the later tasks."""
        for marker in (
            "function h(tag, attrs, ...children)",
            "function t(key)",
            "function safeHref(value)",
            "function parseHash()",
            "function render()",
            "const PANELS",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_stylesheet_carries_the_required_media_queries(self) -> None:
        """Design spec section 4's UI requirements, each one testable as text."""
        for query in (
            "@media print",
            "@media (prefers-color-scheme: dark)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            with self.subTest(query=query):
                self.assertIn(query, self.text)

    def test_stylesheet_carries_a_narrow_breakpoint(self) -> None:
        """Usable at 360px means a breakpoint exists above it."""
        self.assertIn("(max-width:", self.text)

    def test_template_stays_under_the_size_budget(self) -> None:
        """A self-contained file has no other lever against unbounded growth."""
        self.assertLess(len(self.raw), SIZE_BUDGET)

    def test_template_path_resolves_inside_the_bundle(self) -> None:
        """`build` reads the template from here and nowhere else (section 3)."""
        expected = (
            REPO_ROOT
            / "skills"
            / "agent-ingest-audit-optimize"
            / "assets"
            / "templates"
            / "dashboard.html"
        )
        self.assertEqual(TEMPLATE_PATH, expected)
        self.assertTrue(TEMPLATE_PATH.is_file())


class GateSourceTests(ShellTemplateTestCase):
    """A tripwire on the gate bodies, for the machines that skip `node`.

    These are greps, and greps are brittle: rename a variable and one of
    them fails for no security reason. That is the accepted price. Their
    only job is to make a *gutted* gate -- `safeHref` rewritten to `return
    String(value)`, `id` quietly added back to the allow-list -- fail
    something on a machine with no node on it. `RuntimeGateTests` below is
    the real coverage; if the two ever disagree, believe that one.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.shell = extract_shell(cls.text)  # type: ignore[attr-defined]

    def test_safe_href_still_refuses(self) -> None:
        """The refusal itself, inside `safeHref`'s own braces."""
        body = slice_function(self.shell, "function safeHref(value)")
        self.assertIn('return "#";', body)
        self.assertIn('if (typeof value !== "string") { return "#"; }', body)

    def test_safe_href_requires_an_empty_file_authority(self) -> None:
        """The UNC refusal: the exact prefix, and no fourth slash after it.

        `file://host/share` is a network fetch wearing a local scheme, and
        on Windows it is an SMB path. The check is two clauses and both are
        load-bearing, so both are pinned.
        """
        body = slice_function(self.shell, "function safeHref(value)")
        self.assertIn('value.lastIndexOf("file:///", 0) === 0', body)
        self.assertIn('value.charAt(8) !== "/"', body)

    def test_attribute_allow_list_omits_the_dangerous_names(self) -> None:
        """`id`, `style`, and anything fetching are not on the list.

        `style` was never on it and must not arrive: nothing in the skeleton
        needs a per-element style, and one would let ledger content paint.
        """
        listing = re.search(
            r"var ALLOWED_ATTRS = \[(.*?)\];", self.shell, re.DOTALL
        )
        assert listing is not None
        names = set(re.findall(r'"([^"]+)"', listing.group(1)))
        for name in ("id", "style", "src", "srcset", "onclick"):
            with self.subTest(name=name):
                self.assertNotIn(name, names)
        self.assertIn("class", names)

    def test_no_h_call_passes_an_id(self) -> None:
        """M1's other half: the allow-list only helps if nothing relies on it.

        The tab strip needs real ids -- the panel sections name them in
        `aria-labelledby` -- so `buildNav` assigns one directly from the
        `PANELS` constant. That is the tool naming its own chrome. What must
        not exist is an `id:` key in an `attrs` object, because that is the
        shape a ledger string would arrive in.
        """
        self.assertIsNone(re.search(r"^\s*id:\s", self.shell, re.MULTILINE))
        self.assertIn('node.id = "aio-tab-" + panel;', self.shell)

    def test_tag_refusal_list_is_present_and_spares_textarea(self) -> None:
        """`h()` coerces the capability elements, and only those."""
        listing = re.search(
            r"var FORBIDDEN_TAGS = \[(.*?)\];", self.shell, re.DOTALL
        )
        assert listing is not None
        names = set(re.findall(r'"([^"]+)"', listing.group(1)))
        self.assertEqual(
            names,
            {
                "script",
                "iframe",
                "object",
                "embed",
                "link",
                "meta",
                "base",
                "style",
                "form",
            },
        )
        # Task 6's action model needs one; forbidding it now would be a
        # refusal a later task has to unpick.
        self.assertNotIn("textarea", names)

    def test_h_routes_its_tag_through_the_gate(self) -> None:
        """A refusal list nothing calls is decoration."""
        body = slice_function(self.shell, "function h(tag, attrs, ...children)")
        self.assertIn("document.createElement(safeTag(tag))", body)
        gate = slice_function(self.shell, "function safeTag(tag)")
        self.assertIn('return "span";', gate)
        self.assertIn("TAG_PATTERN.test(tag)", gate)

    def test_last_resort_severity_word_is_hard_coded(self) -> None:
        """M3: with no dictionary, `t()` would render the literal key.

        A page already telling the reader it is damaged should not also show
        them `status.error`.
        """
        body = slice_function(self.shell, "function severityLabel(severity)")
        self.assertIn('if (!DICTS) { return "Error"; }', body)

    def test_overview_names_the_built_mode_explicitly(self) -> None:
        """M4: the assurance is made for exactly one value, not for `else`."""
        body = slice_function(self.shell, "function renderOverview(section)")
        self.assertIn('PAYLOAD.mode === "static"', body)
        self.assertIn('PAYLOAD.mode === "built"', body)
        self.assertIn("banner.mode_unknown.title", body)

    def test_print_dependency_is_written_down_in_both_places(self) -> None:
        """M8: the comment pair that stops a plausible optimization.

        Rendering only the active panel would look identical on screen and
        would silently drop eight of nine sections from a print, which no
        test that inspects the screen could catch. Both the stylesheet and
        the renderer say so.
        """
        self.assertIn("Do not optimize renderPanels", self.text)
        self.assertIn("Do not optimize this loop", self.text)

    def test_print_stylesheet_unfolds_the_provenance_chains(self) -> None:
        """M8's failure mode one level down.

        The print block unhides all nine panel sections so a printed page is
        the whole ledger. Provenance is nothing but collapsed `details`, so
        unhiding its section alone would print that panel's heading and none
        of its chains -- the same silent loss, and just as invisible to a
        test that inspects the screen. Two selectors because engines hide the
        closed content two different ways, and an engine that knows neither
        is no worse off than before.
        """
        block = self.text[self.text.index("@media print"):]
        self.assertIn("details > *:not(summary) { display: block !important; }", block)
        self.assertIn("details::details-content", block)

    def test_attribute_prefix_check_is_labelled_as_not_the_guard(self) -> None:
        """The `on` prefix test is case sensitive; the allow-list is the gate."""
        body = slice_function(self.shell, "function attrAllowed(name)")
        self.assertIn("ONCLICK", body)
        self.assertIn("allow-list", body)


@unittest.skipUnless(
    NODE, "node is not on PATH -- the executable gate suite needs it"
)
class RuntimeGateTests(ShellTemplateTestCase):
    """The gates, run.

    Boots the real shell -- the script extracted from the template the class
    above greps -- against `fixtures/dom_stub.js` under `node`, then drives
    each gate through `SAFE_HREF_CASES`, `ATTR_ALLOWED_CASES`, and
    `TAG_CASES`. The node process holds the same tables and exits nonzero on
    any mismatch, so `test_node_harness_exits_clean` is a real assertion and
    not a formality; the per-row cases below exist to name *which* input
    regressed when one does.

    The only edit made to the shell is one appended line inside its own
    IIFE, which hands the three gates out so they can be called at all. It
    is the last statement in the closure, so it runs only if boot completed:
    a shell that fell through to a fatal path exports nothing and the probe
    reports that rather than passing vacuously.
    """

    proc: subprocess.CompletedProcess[str]
    report: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        shell = extract_shell(cls.text).rstrip()
        assert shell.endswith(IIFE_CLOSE), "the shell is no longer a bare IIFE"
        wired = shell[: -len(IIFE_CLOSE)] + SHELL_EXPORT + IIFE_CLOSE + "\n"

        preamble = "\n".join(
            (
                "globalThis.__AIO_ISLANDS__ = " + json.dumps(cls.islands) + ";",
                'globalThis.__AIO_HASH__ = "";',
                'globalThis.__AIO_LANG__ = "en";',
                "globalThis.__AIO_CASES__ = "
                + json.dumps(
                    {
                        "safeHref": [list(row) for row in SAFE_HREF_CASES],
                        "attrAllowed": [list(row) for row in ATTR_ALLOWED_CASES],
                        "tag": [list(row) for row in TAG_CASES],
                    }
                )
                + ";",
                "",
            )
        )

        script = "\n".join(
            (DOM_STUB.read_text(encoding="utf-8"), preamble, wired, PROBE)
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shell_gates.js"
            path.write_text(script, encoding="utf-8")
            cls.proc = subprocess.run(  # noqa: S603
                [str(NODE), str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        try:
            cls.report = json.loads(cls.proc.stdout)
        except ValueError:
            cls.report = {}

    def _rows(self, name: str) -> list:
        self.assertIn(name, self.report.get("table", {}), self.proc.stderr)
        return self.report["table"][name]

    def test_node_harness_exits_clean(self) -> None:
        """One assertion covering the whole table, enforced by node itself."""
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )

    def test_the_shell_actually_booted(self) -> None:
        """Nine tabs in the strip: the table came from a render, not a parse."""
        self.assertEqual(self.report.get("table", {}).get("tabs"), 9)

    def test_safe_href_answers_match_the_table(self) -> None:
        for kind, value, want, got in self._rows("safeHref"):
            with self.subTest(kind=kind, value=value):
                self.assertEqual(got, want)

    def test_attribute_gate_answers_match_the_table(self) -> None:
        for name, want, got in self._rows("attrAllowed"):
            with self.subTest(attribute=name):
                self.assertEqual(got, want)

    def test_tag_coercion_answers_match_the_table(self) -> None:
        for kind, value, want, got in self._rows("tag"):
            with self.subTest(kind=kind, tag=value):
                self.assertEqual(got, want)

    def test_every_case_in_the_tables_was_actually_exercised(self) -> None:
        """A probe that silently ran nothing would pass everything above."""
        self.assertEqual(len(self._rows("safeHref")), len(SAFE_HREF_CASES))
        self.assertEqual(len(self._rows("attrAllowed")), len(ATTR_ALLOWED_CASES))
        self.assertEqual(len(self._rows("tag")), len(TAG_CASES))


class PanelRendererSourceTests(ShellTemplateTestCase):
    """Task 4's six renderers, as source: present, wired, and severity-aware.

    Greps again, and for the same narrow reason `GateSourceTests` is: these
    say a renderer *exists and is reachable*, which is cheap to keep true on
    a machine with no node. `RuntimePanelTests` below is what says the
    renderers produce the right document; if the two disagree, believe that
    one.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.shell = extract_shell(cls.text)  # type: ignore[attr-defined]

    def test_every_task_4_renderer_is_defined(self) -> None:
        for signature in TASK_4_RENDERERS:
            with self.subTest(renderer=signature):
                self.assertIn(signature, self.shell)

    def test_every_task_4_renderer_is_dispatched_by_render_panels(self) -> None:
        """A renderer nothing calls is dead code that a grep would still pass."""
        body = slice_function(self.shell, "function renderPanels(state)")
        for signature in TASK_4_RENDERERS:
            name = signature.split("(")[0].replace("function ", "")
            with self.subTest(renderer=name):
                self.assertIn(name + "(section", body)

    def test_every_task_5_renderer_is_defined(self) -> None:
        for signature in TASK_5_RENDERERS:
            with self.subTest(renderer=signature):
                self.assertIn(signature, self.shell)

    def test_every_task_5_renderer_is_dispatched_by_render_panels(self) -> None:
        """Same reason as Task 4's: the three panels each have an
        instructional empty state, and a renderer that is defined but never
        dispatched leaves that empty state on screen for a ledger that is
        full of runs -- which reads as "nothing was ever recorded"."""
        body = slice_function(self.shell, "function renderPanels(state)")
        for signature in TASK_5_RENDERERS:
            name = signature.split("(")[0].replace("function ", "")
            with self.subTest(renderer=name):
                self.assertIn(name + "(section", body)

    def test_task_5_panels_build_no_link_elements(self) -> None:
        """Anchors and evidence sources are text in these panels too.

        The `file:` Open links belong to Task 6, which adds them behind
        `safeHref` deliberately and all at once. Until then a target anchor
        is exactly what an evidence source already is -- a string that is
        frequently a path and is never a click -- and the way to keep that
        true is for these renderers to build no `a` at all.
        """
        for signature in (
            "function renderChanges(section)",
            "function runBlock(record, states)",
            "function targetRow(target, states)",
            "function renderProvenance(section)",
            "function chainBlock(entry, byId, expired)",
            "function chainList(record, byId, expired)",
            "function renderRollback(section)",
            "function rollbackBlock(record, preview)",
            "function setRow(row, withReason)",
        ):
            with self.subTest(function=signature):
                body = slice_function(self.shell, signature)
                self.assertNotIn('h("a"', body)
                self.assertNotIn("href", body)

    def test_the_self_reported_badge_reads_the_records_own_list(self) -> None:
        """Design spec section 5's marker is driven by the ledger field that
        names it, not by a guess about which fields look unverified.

        This is the grep half of the ablation the plan asks for: delete the
        branch and `RuntimePanelTests` fails on the rendered tree, but a
        machine with no node would otherwise notice nothing.
        """
        body = slice_function(self.shell, "function selfReportedFields(record)")
        self.assertIn("record.self_reported", body)
        gate = slice_function(self.shell, "function selfReportedBadge(record, field)")
        self.assertIn("isSelfReported(record, field)", gate)
        self.assertIn("SELF_REPORTED", gate)

    def test_rollback_tested_values_map_to_the_documented_severities(self) -> None:
        """An untested rollback is a warning, a failed one an error.

        Mapping `NOT_TESTED` to `info` would paint an undo nobody has ever
        exercised exactly like one that passed.
        """
        listing = re.search(r"var TESTED_SEVERITY = \{(.*?)\};", self.shell, re.DOTALL)
        assert listing is not None
        pairs = dict(re.findall(r'(\w+):\s*"(\w+)"', listing.group(1)))
        self.assertEqual(pairs, TESTED_SEVERITY)

    def test_the_run_result_vocabulary_matches_the_schema(self) -> None:
        """The six results, in the schema's own order, from one list."""
        listing = re.search(r"var RUN_RESULTS = \[(.*?)\];", self.shell, re.DOTALL)
        assert listing is not None
        found = tuple(re.findall(r'"([^"]+)"', listing.group(1)))
        self.assertEqual(found, RUN_RESULTS)
        self.assertIn('var CLEAN_RESULT = "VALIDATED";', self.shell)

    def test_the_digest_abbreviation_keeps_the_whole_value_in_reach(self) -> None:
        """Twelve characters on screen, and the full digest in the tooltip.

        Truncating without the tooltip would make two digests that share a
        prefix indistinguishable on the page with no way to tell from here.
        """
        self.assertIn("var DIGEST_CHARS = 12;", self.shell)
        body = slice_function(self.shell, "function digestCell(value)")
        self.assertIn("title: value", body)
        self.assertIn("hex.slice(0, DIGEST_CHARS)", body)

    def test_severity_order_is_error_then_warning_then_info(self) -> None:
        """The one list the whole sort depends on, in the one order it means."""
        listing = re.search(r"var SEVERITY_ORDER = \[(.*?)\];", self.shell, re.DOTALL)
        assert listing is not None
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', listing.group(1))), SEVERITY_ORDER)

    def test_drift_states_map_to_the_documented_severities(self) -> None:
        """`DRIFTED`/`MISSING` severe, `UNVERIFIABLE` warning, the rest quiet.

        Mapping a drifted item to `info` would leave it sorted below a note
        and painted like one -- a silent downgrade of the finding the whole
        drift machinery exists to surface.
        """
        listing = re.search(r"var DRIFT_SEVERITY = \{(.*?)\};", self.shell, re.DOTALL)
        assert listing is not None
        pairs = dict(re.findall(r'(\w+):\s*"(\w+)"', listing.group(1)))
        self.assertEqual(pairs, DRIFT_SEVERITY)

    def test_rollback_indicators_map_to_the_documented_severities(self) -> None:
        listing = re.search(
            r"var INDICATOR_SEVERITY = \{(.*?)\};", self.shell, re.DOTALL
        )
        assert listing is not None
        pairs = dict(re.findall(r'(\w+):\s*"(\w+)"', listing.group(1)))
        self.assertEqual(pairs, INDICATOR_SEVERITY)

    def test_the_shared_sort_helper_is_defined(self) -> None:
        self.assertIn(
            "function sortBySeverityThenRecency(rows, severityOf)", self.shell
        )

    def test_every_record_listing_panel_uses_the_shared_sort(self) -> None:
        """One ordering rule, applied in one place, used by all four panels.

        Design spec section 4 gives the whole dashboard a single default
        ordering. A panel that sorted its own way would look right in
        isolation and disagree with every other panel about which row
        matters most.
        """
        for renderer in (
            "function renderInventory(section, state)",
            "function renderBacklog(section)",
            "function renderDecisions(section, state)",
            "function renderMaterials(section)",
            "function renderChanges(section)",
            "function renderRollback(section)",
            # Provenance sorts two lists -- the anchors, and the runs under
            # each -- and both happen inside the index it builds, so that is
            # the function the rule has to hold in.
            "function anchorIndex(runs)",
        ):
            with self.subTest(renderer=renderer):
                body = slice_function(self.shell, renderer)
                self.assertIn("sortBySeverityThenRecency(", body)

    def test_evidence_sources_are_never_routed_through_href(self) -> None:
        """Design spec section 1.3: a source is copyable text, never a link.

        Evidence sources are the one ledger field that routinely *is* a URL.
        Rendering one as a link would put a network scheme in the document
        and hand a reader a click that leaves the offline guarantee behind,
        so the materials renderer must not build an `a` at all.

        `renderMaterials` only assembles the table shell -- the row markup,
        where each evidence source is actually placed on the page, is built
        by `materialRow`. A slice of `renderMaterials` alone would pass this
        assertion even if `materialRow` built a link, which is exactly the
        gap a reviewer found: this now checks both functions' source, and
        `RuntimePanelTests.test_materials_panel_builds_no_anchor_elements`
        below checks the rendered tree itself rather than only the source.
        """
        for signature in (
            "function renderMaterials(section)",
            "function materialRow(record, expired)",
            # Where the source actually lands since Task 5 shared this list
            # with the Provenance chain.
            "function evidenceList(record, expired)",
        ):
            with self.subTest(function=signature):
                body = slice_function(self.shell, signature)
                self.assertNotIn('h("a"', body)
                self.assertNotIn("href", body)

    def test_no_object_literal_line_starts_with_an_id_key(self) -> None:
        """M1 again, over the code Task 4 adds: `id` never reaches `h()`."""
        self.assertIsNone(re.search(r"^\s*id:\s", self.shell, re.MULTILINE))


class StylesheetSeamTests(ShellTemplateTestCase):
    """Every class the shell emits has a rule in the stylesheet that ships.

    This is the seam a reviewer flagged after Task 2: the narrow-width
    `.grid-table` rules were written before any renderer emitted a table, so
    nothing checked that the class names in the CSS and the class names in
    the JavaScript were the same strings. A typo there costs the 360px
    layout and nothing else notices -- the page still renders, just badly,
    and only on a phone.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.shell = extract_shell(cls.text)  # type: ignore[attr-defined]
        block = STYLE_BLOCK.search(cls.text)
        assert block is not None
        cls.style = block.group(1)  # type: ignore[attr-defined]

    def emitted_classes(self) -> set[str]:
        names: set[str] = set()
        for literal in CLASS_LITERAL.findall(self.shell):
            for token in literal.split():
                if token.endswith("-"):
                    for suffix in DYNAMIC_CLASS_FAMILIES[token]:
                        names.add(token + suffix)
                    continue
                names.add(token)
        return names

    def test_the_shell_emits_classes_at_all(self) -> None:
        """A seam test over an empty set would pass forever."""
        found = self.emitted_classes()
        self.assertIn("grid-table", found)
        self.assertGreater(len(found), 20)

    def test_every_emitted_class_has_a_stylesheet_rule(self) -> None:
        for name in sorted(self.emitted_classes()):
            with self.subTest(css_class=name):
                self.assertIsNotNone(
                    re.search(r"\." + re.escape(name) + r"(?![\w-])", self.style),
                    f".{name} is emitted by the shell and styled nowhere",
                )

    def test_every_dynamic_family_is_declared_before_it_is_expanded(self) -> None:
        """A `class: "row-"` with no family here would expand to nothing."""
        for literal in CLASS_LITERAL.findall(self.shell):
            for token in literal.split():
                if token.endswith("-"):
                    with self.subTest(family=token):
                        self.assertIn(token, DYNAMIC_CLASS_FAMILIES)

    def test_the_narrow_card_fold_has_something_to_fold(self) -> None:
        """The 720px rules address `.grid-table td[data-label]`; tds carry one."""
        self.assertIn("content: attr(data-label)", self.style)
        self.assertIn('"data-label"', self.shell)


class PanelDictionaryTests(ShellTemplateTestCase):
    """Task 4's strings: named, in both dictionaries, and not left English."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dicts = json.loads(cls.islands["aio-i18n"])  # type: ignore[attr-defined]

    def test_every_task_4_key_is_in_both_dictionaries(self) -> None:
        for code in ("en", "pt-BR"):
            for key in TASK_4_KEYS:
                with self.subTest(lang=code, key=key):
                    self.assertIn(key, self.dicts[code])

    def test_every_task_5_key_is_in_both_dictionaries(self) -> None:
        for code in ("en", "pt-BR"):
            for key in TASK_5_KEYS:
                with self.subTest(lang=code, key=key):
                    self.assertIn(key, self.dicts[code])

    def test_the_self_reported_badge_has_a_translated_explanation(self) -> None:
        """The word stays English; the sentence under it does not.

        `SELF-REPORTED` is canonical vocabulary -- it is what the commands
        and the records call it -- so it is not translated. The tooltip that
        says what it means is prose, and a reader who needs the tooltip is
        precisely the reader who is not reading English by choice.
        """
        for code in ("en", "pt-BR"):
            with self.subTest(lang=code):
                self.assertIn("changes.self_reported", self.dicts[code])
        self.assertNotEqual(
            self.dicts["en"]["changes.self_reported"],
            self.dicts["pt-BR"]["changes.self_reported"],
        )

    def test_every_run_result_has_a_gloss_in_both_languages(self) -> None:
        """The result chips in the Changes panel, and Help's own list."""
        for code in ("en", "pt-BR"):
            for name in RUN_RESULTS:
                with self.subTest(lang=code, result=name):
                    self.assertIn("vocab.result." + name + ".tip", self.dicts[code])

    def test_every_rollback_tested_value_has_a_gloss_in_both_languages(self) -> None:
        for code in ("en", "pt-BR"):
            for name in TESTED_SEVERITY:
                with self.subTest(lang=code, tested=name):
                    self.assertIn("rollback.tested." + name + ".tip", self.dicts[code])

    def test_no_task_5_gloss_was_filled_by_paste(self) -> None:
        """A pt-BR value identical to its English twin is an untranslated key."""
        keys = ["vocab.result." + name + ".tip" for name in RUN_RESULTS]
        keys += ["rollback.tested." + name + ".tip" for name in TESTED_SEVERITY]
        for key in keys:
            with self.subTest(key=key):
                self.assertNotEqual(self.dicts["en"][key], self.dicts["pt-BR"][key])

    def test_every_classification_has_a_gloss_in_both_languages(self) -> None:
        """The Help panel's vocabulary list, and the chips' tooltips."""
        for code in ("en", "pt-BR"):
            for name in CLASSIFICATIONS:
                with self.subTest(lang=code, classification=name):
                    self.assertIn("vocab.class." + name + ".tip", self.dicts[code])

    def test_every_record_status_has_a_gloss_in_both_languages(self) -> None:
        for code in ("en", "pt-BR"):
            for name in RECORD_STATUSES:
                with self.subTest(lang=code, status=name):
                    self.assertIn("vocab.status." + name + ".tip", self.dicts[code])

    def test_no_task_4_gloss_was_filled_by_paste(self) -> None:
        """A pt-BR value identical to its English twin is an untranslated key.

        Command strings are the exception and are not glosses: they are the
        tool's own vocabulary and stay English in every language.
        """
        for name in CLASSIFICATIONS:
            key = "vocab.class." + name + ".tip"
            with self.subTest(classification=name):
                self.assertNotEqual(self.dicts["en"][key], self.dicts["pt-BR"][key])
        for name in RECORD_STATUSES:
            key = "vocab.status." + name + ".tip"
            with self.subTest(status=name):
                self.assertNotEqual(self.dicts["en"][key], self.dicts["pt-BR"][key])

    def test_the_unavailable_cards_name_the_command_that_fills_them(self) -> None:
        """Design spec section 4: an empty state names the exact command.

        A static-mode card that said only "unavailable" would be a dead end;
        the reader is one command away from the number and should be told
        which one.
        """
        commands = {
            "card.unavailable.drift": "dashboard.py drift",
            "card.unavailable.previews": "dashboard.py rollback-preview",
            "card.unavailable.expired_evidence": "dashboard.py build",
        }
        for code in ("en", "pt-BR"):
            for key, command in commands.items():
                with self.subTest(lang=code, key=key):
                    self.assertIn(command, self.dicts[code][key])


@unittest.skipUnless(
    NODE, "node is not on PATH -- the executable panel suite needs it"
)
class RuntimePanelTests(ShellTemplateTestCase):
    """The six renderers, run against a known built-mode payload.

    Same harness as `RuntimeGateTests` -- the real shell, the real DOM stub,
    one appended export line -- with the payload island swapped for
    `FIXTURE_PAYLOAD`, serialized by the very function `build` uses. The
    probe walks the rendered tree and reports facts; the cases below do the
    comparing.

    The last case is the one that matters most: a material whose title is
    `</script><script>x` must reach the document as one literal text node.
    That is design spec section 7's acceptance item 2, asserted against a
    render rather than against a grep. The DOM stub's `createElement` tally
    is a separate, narrower check, not the proof of that item: `h()` always
    calls `createElement(safeTag(tag))`, so the tally only ever sees a tag
    name after `safeTag` has already coerced it. It cannot show that the
    payload was never *offered* to `createElement` as a tag; it can only
    catch a future code path that calls `createElement` directly, bypassing
    `h()` and `safeTag` both.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict
    payload: dict = FIXTURE_PAYLOAD

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.proc = boot_shell(cls.text, cls.islands, cls.payload)
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def _panel(self, name: str) -> dict:
        self.assertIn(
            name,
            self.facts,
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        return self.facts[name]

    def _card(self, label: str) -> dict:
        for card in self._panel("overview")["cards"]:
            if card["label"] == label:
                return card
        raise AssertionError("no overview card labelled " + label)

    def test_the_probe_ran_and_the_shell_booted(self) -> None:
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )
        self.assertEqual(self.facts.get("failures"), [])

    # --- Overview ------------------------------------------------------

    def test_overview_renders_one_card_per_indicator(self) -> None:
        self.assertEqual(len(self._panel("overview")["cards"]), 5)

    def test_overview_counts_active_changes_from_the_records(self) -> None:
        """Four RUN records, one of them rolled back and so not active.

        The count and the Changes panel read the same two fields through the
        same function, which is what stops this card from disagreeing with
        the panel it links to.
        """
        self.assertEqual(self._card("Active changes")["count"], "3")

    def test_overview_counts_drift_from_the_computed_summary(self) -> None:
        """Two DRIFTED in the summary, and nothing else off IN_PLACE."""
        card = self._card("Drifted items")
        self.assertEqual(card["count"], "2")
        self.assertIn("card-error", card["severity"])

    def test_overview_counts_rollbacks_at_risk_from_the_previews(self) -> None:
        """Two previews, `BROKEN` and `AT_RISK`; the card takes the worse."""
        card = self._card("Rollbacks at risk")
        self.assertEqual(card["count"], "2")
        self.assertIn("card-error", card["severity"])

    def test_overview_counts_expired_evidence_and_unreachable_projects(self) -> None:
        self.assertEqual(self._card("Expired evidence")["count"], "1")
        self.assertEqual(self._card("Unreachable projects")["count"], "1")

    def test_every_overview_card_links_to_a_panel_fragment(self) -> None:
        """Design spec section 4's router owns `#panel=`; the cards use it."""
        for card in self._panel("overview")["cards"]:
            with self.subTest(card=card["label"]):
                self.assertEqual(len(card["href"]), 1)
                self.assertTrue(card["href"][0].startswith("#panel="), card["href"])

    def test_overview_names_the_unreachable_project_root(self) -> None:
        self.assertIn("/gone", self._panel("overview")["text"])

    # --- Inventory -----------------------------------------------------

    def test_inventory_renders_one_row_per_baseline_item(self) -> None:
        self.assertEqual(self._panel("inventory")["rows"], 3)

    def test_inventory_uses_the_grid_table_class(self) -> None:
        """The seam `StylesheetSeamTests` checks statically, met at runtime."""
        self.assertEqual(self._panel("inventory")["tableClasses"], ["grid-table"])

    def test_inventory_labels_every_cell_for_the_card_fold(self) -> None:
        labels = self._panel("inventory")["labels"]
        self.assertTrue(labels)
        self.assertTrue(all(isinstance(label, str) and label for label in labels))

    def test_inventory_shows_the_drift_state_of_the_drifted_item(self) -> None:
        """The join: baseline item to drift report row, by anchor and name."""
        self.assertIn("DRIFTED", "".join(self._panel("inventory")["vocab"]))

    def test_inventory_sorts_the_drifted_item_first(self) -> None:
        """Severity first: an item that drifted outranks two that did not."""
        text = self._panel("inventory")["text"]
        self.assertLess(text.index("drifted-skill"), text.index("CLAUDE.md"))

    def test_inventory_renders_the_proposal_origin_as_text(self) -> None:
        self.assertIn("PROP-2026-000", self._panel("inventory")["text"])

    # --- Changes -------------------------------------------------------

    def _run_block(self, panel: str, run_id: str) -> dict:
        for block in self._panel(panel)["runs"]:
            if run_id in block["text"]:
                return block
        raise AssertionError("no " + panel + " block for " + run_id)

    def test_changes_renders_one_block_per_run(self) -> None:
        self.assertEqual(len(self._panel("changes")["runs"]), 4)

    def test_changes_sorts_the_deviating_runs_above_the_clean_ones(self) -> None:
        """Severity first, recency second -- and the fixture is built so the
        two rules disagree.

        `RUN-2026-002` recorded a plan deviation and `RUN-2026-001` a result
        that is not `VALIDATED`; both must sort above `RUN-2026-003`, which
        is the newest record of the four. A panel that ordered by date alone
        would put the newest first and look perfectly reasonable.
        """
        order = [block["text"][:40] for block in self._panel("changes")["runs"]]
        self.assertIn("RUN-2026-002", order[0])
        self.assertIn("RUN-2026-001", order[1])
        self.assertIn("RUN-2026-003", order[2])
        self.assertIn("RUN-2026-000", order[3])

    def test_changes_paints_the_two_kinds_of_finding_as_warnings(self) -> None:
        """A deviation and a non-clean result each earn the same severity."""
        self.assertIn("run-warning", self._run_block("changes", "RUN-2026-002")["classes"])
        self.assertIn("run-warning", self._run_block("changes", "RUN-2026-001")["classes"])

    def test_changes_treats_a_rolled_back_run_as_history(self) -> None:
        """`ROLLBACK COMPLETED` is not a fault: the change was undone on
        purpose and the record stays to say so. Ranking it as a finding would
        float every undone change above the ones still in effect."""
        self.assertIn("run-info", self._run_block("changes", "RUN-2026-003")["classes"])

    def test_changes_names_the_deviation_it_sorted_on(self) -> None:
        """The reason a run outranks the rest is on the page, not only in the
        sort: a block painted as a finding with nothing in it that says why
        is a block the reader cannot act on."""
        block = self._run_block("changes", "RUN-2026-002")
        self.assertIn("Plan deviations", block["headings"])
        self.assertIn("the second hook was left out", block["text"])

    def test_changes_abbreviates_every_digest_to_twelve_characters(self) -> None:
        """And keeps the whole value in the tooltip.

        Twelve is enough to tell two digests apart at a glance; the title is
        what makes the shortening lossless. A digest rendered whole would push
        the table past any viewport, and one rendered short with no title
        would be a fact the page destroyed on the way in.
        """
        digests = self._panel("changes")["digests"]
        self.assertTrue(digests)
        for entry in digests:
            with self.subTest(digest=entry["text"]):
                self.assertEqual(len(entry["text"]), 12)
                self.assertTrue(entry["title"].startswith("sha256:"), entry["title"])
                self.assertEqual(len(entry["title"]), len("sha256:") + 64)
                # The shown text is the head of the value in the tooltip, so
                # the two cannot describe different digests.
                self.assertTrue(
                    entry["title"][len("sha256:"):].startswith(entry["text"]),
                    entry,
                )
        self.assertIn(DIGEST_AFTER, {entry["title"] for entry in digests})
        self.assertIn(
            DIGEST_AFTER[len("sha256:"):][:12], {entry["text"] for entry in digests}
        )

    def test_changes_renders_the_target_key_beside_the_digest_pair(self) -> None:
        """0.4.0's whole "before/after diff": the digest pair plus the key.

        The ledger stores digests, not file bodies, so there is nothing here
        to diff -- and the panel says exactly that rather than implying more.
        """
        panel = self._panel("changes")
        self.assertIn("/hooks/0/command", panel["text"])
        self.assertIn("Key", panel["headers"])
        self.assertIn("not a line-by-line diff", panel["text"])

    def test_changes_badges_exactly_the_fields_the_run_named(self) -> None:
        """Design spec section 5's marker, driven by `self_reported`.

        `RUN-2026-000` lists only `targets`; `RUN-2026-001` lists `result`
        too. A badge on a field the run did not name would be this page
        inventing a doubt, and a missing badge would be it hiding one --
        so the assertion is set equality, in both directions, per run.
        """
        first = self._run_block("changes", "RUN-2026-000")
        self.assertEqual({badge["field"] for badge in first["badges"]}, {"targets"})
        second = self._run_block("changes", "RUN-2026-001")
        self.assertEqual(
            {badge["field"] for badge in second["badges"]}, {"targets", "result"}
        )
        for badge in first["badges"] + second["badges"]:
            with self.subTest(field=badge["field"]):
                self.assertIn("SELF-REPORTED", badge["text"])

    def test_changes_labels_every_cell_for_the_card_fold(self) -> None:
        labels = self._panel("changes")["labels"]
        self.assertTrue(labels)
        self.assertTrue(all(isinstance(label, str) and label for label in labels))

    def test_changes_annotates_a_target_with_its_computed_drift_state(self) -> None:
        """The run-target half of the drift report, joined by anchor and kind.

        Only `RUN-2026-000` is in the report's `runs`, so only its block may
        carry a state -- a page that showed a state for the others would be
        claiming a comparison nobody made.
        """
        panel = self._panel("changes")
        self.assertIn("State", panel["headers"])
        self.assertIn("DRIFTED", self._run_block("changes", "RUN-2026-000")["text"])
        self.assertNotIn("DRIFTED", self._run_block("changes", "RUN-2026-002")["text"])

    def test_changes_builds_no_link_elements(self) -> None:
        """Target anchors are text at 0.4.0; Task 6 owns the `file:` links."""
        self.assertEqual(self._panel("changes")["anchors"], 0)

    def test_a_script_payload_in_a_target_anchor_lands_as_one_text_node(self) -> None:
        """The stored-XSS regression, through a second renderer.

        A target anchor and a residual effect are ledger strings that reach
        the document by a different path than a material title does. The
        payload is the same one; the assertion is the same one -- it arrives
        as a value and leaves as text.
        """
        self.assertIn(XSS_TITLE, self._panel("changes")["texts"])

    def test_a_script_payload_in_a_residual_effect_lands_as_one_text_node(self) -> None:
        texts = self._panel("changes")["texts"]
        self.assertGreaterEqual(texts.count(XSS_TITLE), 2)

    # --- Provenance ----------------------------------------------------

    def _chain(self, needle: str) -> str:
        for text in self._panel("provenance")["chains"]:
            if needle in text:
                return text
        raise AssertionError("no provenance chain mentioning " + needle)

    def test_provenance_indexes_every_distinct_target(self) -> None:
        """Five targets across four runs, two of them the same anchor and key.

        The shared anchor is the point: the index is keyed on anchor *and*
        key, so two runs that wrote the same file land under one entry and
        two runs that wrote different keys inside one file do not.
        """
        self.assertEqual(len(self._panel("provenance")["summaries"]), 5)

    def test_provenance_puts_both_runs_under_the_shared_anchor(self) -> None:
        chain = self._chain("$USER_CONFIG/settings.json")
        self.assertIn("RUN-2026-000", chain)
        self.assertIn("RUN-2026-001", chain)

    def test_provenance_reaches_each_runs_own_evidence(self) -> None:
        """The whole chain, end to end and per run: run → proposal → material
        → the evidence that material rests on, with its dates.

        Both runs touched one file, and each has to arrive at its *own*
        evidence. A chain that followed only the first proposal would look
        complete and would attribute one run's change to the other's source.
        """
        chain = self._chain("$USER_CONFIG/settings.json")
        for token in (
            "PROP-2026-000",
            "MAT-2026-000",
            "vendor documentation, page 4",
            "2026-01-02",
            "PROP-2026-001",
            "MAT-2026-001",
            "release notes, second edition",
            "2026-05-05",
        ):
            with self.subTest(token=token):
                self.assertIn(token, chain)

    def test_provenance_orders_anchors_by_the_run_that_moved_last(self) -> None:
        summaries = self._panel("provenance")["summaries"]
        self.assertIn("$USER_CONFIG/skills/drifted-skill", summaries[0])
        self.assertIn("$USER_CONFIG/CLAUDE.md", summaries[1])
        self.assertIn("$USER_CONFIG/settings.json", summaries[2])

    def test_provenance_shows_the_key_that_distinguishes_two_targets(self) -> None:
        self.assertIn("/hooks/0/command", self._chain("$USER_CONFIG/hooks/guard.js"))

    def test_provenance_builds_no_link_elements(self) -> None:
        self.assertEqual(self._panel("provenance")["anchors"], 0)

    def test_a_script_payload_in_an_anchor_is_inert_in_provenance(self) -> None:
        self.assertIn(XSS_TITLE, self._panel("provenance")["texts"])

    # --- Rollback ------------------------------------------------------

    def test_rollback_renders_a_block_for_every_run_with_a_backup(self) -> None:
        """Two of the four runs kept one."""
        self.assertEqual(len(self._panel("rollback")["runs"]), 2)

    def test_rollback_lists_all_four_sets_even_when_they_are_empty(self) -> None:
        """Design spec section 11's four sets partition the run's targets, so
        an empty set is an answer -- `BROKEN` restores nothing, and that is
        the finding. A panel that dropped the empty ones would make "nothing
        could be restored" and "this was never computed" look identical.
        """
        block = self._run_block("rollback", "RUN-2026-000")
        self.assertEqual(
            block["headings"],
            [
                "Will be restored",
                "Cannot be restored",
                "Will not change",
                "Residual effects — undoing the run does not undo these",
            ],
        )
        self.assertEqual(block["text"].count("none"), 3)

    def test_rollback_shows_the_broken_indicator_and_its_reason(self) -> None:
        block = self._run_block("rollback", "RUN-2026-000")
        self.assertIn("BROKEN", block["text"])
        self.assertIn("backup_missing", block["text"])
        self.assertIn("run-error", block["classes"])

    def test_rollback_fills_all_four_sets_when_the_preview_does(self) -> None:
        block = self._run_block("rollback", "RUN-2026-001")
        self.assertIn("AT_RISK", block["text"])
        self.assertIn("$USER_CONFIG/settings.json", block["text"])
        self.assertIn("$USER_CONFIG/hooks/guard.js", block["text"])
        self.assertIn("MISSING", block["text"])
        self.assertNotIn("none", block["text"])

    def test_rollback_sorts_the_broken_preview_above_the_at_risk_one(self) -> None:
        first = self._panel("rollback")["runs"][0]
        self.assertIn("RUN-2026-000", first["text"])

    def test_rollback_badges_the_backup_fields_the_run_named(self) -> None:
        """`RUN-2026-001` lists `backup` and `rollback.tested`; the run above
        it lists neither, and its block must carry no badge at all."""
        self.assertEqual(self._run_block("rollback", "RUN-2026-000")["badges"], [])
        self.assertEqual(
            {b["field"] for b in self._run_block("rollback", "RUN-2026-001")["badges"]},
            {"backup", "rollback.tested"},
        )

    def test_rollback_names_the_runs_that_kept_no_backup(self) -> None:
        """Two runs recorded none, and the panel says so in words rather than
        leaving them out: a run missing from this panel would read as a run
        that can be undone, which is the opposite of the truth."""
        text = self._panel("rollback")["text"]
        self.assertIn("Runs with no backup", text)
        self.assertIn("RUN-2026-002", text)
        self.assertIn("RUN-2026-003", text)
        self.assertIn("recorded no backup", text)

    def test_rollback_builds_no_link_elements(self) -> None:
        self.assertEqual(self._panel("rollback")["anchors"], 0)

    def test_a_script_payload_in_a_preview_set_is_inert(self) -> None:
        self.assertIn(XSS_TITLE, self._panel("rollback")["texts"])

    # --- Backlog -------------------------------------------------------

    def test_backlog_sorts_the_overdue_entry_first(self) -> None:
        """The fixture lists it second; a passed revisit date is a warning.

        This is the one assertion that fails loudly if
        `sortBySeverityThenRecency` stops being applied here: the rows still
        render, in ledger order, and the entry that is due gets buried.
        """
        rows = self._panel("backlog")["rowText"]
        self.assertEqual(len(rows), 2)
        self.assertIn("NEEDS MORE EVIDENCE", rows[0])
        self.assertIn("MONITOR", rows[1])

    def test_backlog_marks_the_passed_revisit_date(self) -> None:
        panel = self._panel("backlog")
        self.assertIn("revisit date passed", panel["rowText"][0])
        self.assertIn("2026-01-15", panel["rowText"][0])

    # --- Decisions -----------------------------------------------------

    def test_decisions_renders_every_adr_including_the_superseded_one(self) -> None:
        """Design spec section 4: ADRs are never filtered out, only sorted."""
        self.assertEqual(self._panel("decisions")["rows"], 2)
        self.assertIn("SUPERSEDED", self._panel("decisions")["text"])

    def test_decisions_names_the_record_that_superseded_this_one(self) -> None:
        text = self._panel("decisions")["text"]
        self.assertIn("superseded by", text)
        self.assertIn("ADR-2026-001", text)

    def test_decisions_names_the_record_this_one_supersedes(self) -> None:
        """The reverse index: the replacement says what it replaced."""
        self.assertIn("supersedes", self._panel("decisions")["text"])

    # --- Materials -----------------------------------------------------

    def test_materials_renders_the_material_record(self) -> None:
        self.assertEqual(self._panel("materials")["rows"], 2)

    def test_materials_marks_the_expired_evidence(self) -> None:
        text = self._panel("materials")["text"]
        self.assertIn("evidence expired", text)
        self.assertIn("2026-04-02", text)

    def test_materials_renders_the_evidence_source_as_text(self) -> None:
        self.assertIn("vendor documentation, page 4", self._panel("materials")["text"])

    def test_materials_panel_builds_no_anchor_elements(self) -> None:
        """The behavioral half of I2: not just absent from the source, absent
        from the render. `test_evidence_sources_are_never_routed_through_href`
        greps `materialRow`'s body; this counts `<a>` elements in the actual
        rendered Materials panel and requires zero, so a source built through
        some path the grep does not slice -- or added later -- still fails
        here.
        """
        self.assertEqual(self._panel("materials")["anchors"], 0)

    # --- The regression this whole file exists for ---------------------

    def test_a_script_payload_in_a_material_title_lands_as_one_text_node(self) -> None:
        """Design spec section 7, acceptance item 2, asserted on a render.

        Not "the escaped form appears in the source" -- the string arrives at
        `h()` intact and must leave it as a *value*, so the assertion is that
        the exact title is one text node's text.
        """
        self.assertIn(XSS_TITLE, self._panel("materials")["texts"])

    def test_rendering_that_payload_created_no_script_element(self) -> None:
        """The counter the DOM stub keeps of every `createElement` argument.

        This is a narrower guarantee than it looks. `h()` always calls
        `createElement(safeTag(tag))`, so the name this counter records has
        already been through `safeTag`'s coercion by the time `createElement`
        sees it -- a shell that somehow routed the title through `h("script",
        ...)` would still only ever tally "span" here, the same as any other
        coerced tag. What a zero under "script"/"SCRIPT" actually rules out is
        a *future* code path calling `createElement` directly, bypassing
        `h()` and `safeTag` both. The proof that this title specifically
        never became an element is
        `test_a_script_payload_in_a_material_title_lands_as_one_text_node`,
        just above, which asserts on the text node rather than on this tally.
        """
        created = self.facts.get("created", {})
        self.assertEqual(created.get("script"), None)
        self.assertEqual(created.get("SCRIPT"), None)
        self.assertGreater(sum(created.values()), 50)


@unittest.skipUnless(NODE, "node is not on PATH -- this suite needs it")
class RuntimeStaticModePanelTests(RuntimePanelTests):
    """The same ledger with no `computed`, which is what a hand-injected
    static page is (design spec section 2's degradation path).

    Inheriting the built-mode class is deliberate: every case that describes
    the *ledger* -- how many rows, which order, that a script payload stays
    text -- has to hold here too, because none of it depends on a
    computation. The cases that describe a computed guarantee are overridden
    below to assert the honest refusal instead of a number. If a future edit
    makes a ledger-only panel quietly need `computed`, it fails here.
    """

    payload = STATIC_FIXTURE_PAYLOAD

    def test_overview_counts_drift_from_the_computed_summary(self) -> None:
        card = self._card("Drifted items")
        self.assertIsNone(card["count"])
        self.assertEqual(card["unavailable"], "unavailable")
        self.assertIn("dashboard.py drift", card["note"])

    def test_overview_counts_rollbacks_at_risk_from_the_previews(self) -> None:
        card = self._card("Rollbacks at risk")
        self.assertIsNone(card["count"])
        self.assertIn("dashboard.py rollback-preview", card["note"])

    def test_overview_counts_expired_evidence_and_unreachable_projects(self) -> None:
        """Expiry needs the build; an unreachable project does not.

        `known_projects` records the status something observed the last time
        it looked, and reporting that is honest in a way reporting zero would
        not be -- so this one card still holds a number on a static page.
        """
        expired = self._card("Expired evidence")
        self.assertIsNone(expired["count"])
        self.assertIn("dashboard.py build", expired["note"])
        self.assertEqual(self._card("Unreachable projects")["count"], "1")

    def test_inventory_shows_the_drift_state_of_the_drifted_item(self) -> None:
        """No drift report, so no drift chip: the recorded state, plainly.

        The baseline's own `state` is scan-verified data and renders as
        itself. What must not happen is a drift state appearing without a
        drift report behind it.
        """
        self.assertEqual(self._panel("inventory")["vocab"], [])
        self.assertIn("present", self._panel("inventory")["text"])
        self.assertNotIn("DRIFTED", self._panel("inventory")["text"])

    def test_inventory_sorts_the_drifted_item_first(self) -> None:
        """Nothing is severe without a drift report, so ledger order stands."""
        text = self._panel("inventory")["text"]
        self.assertLess(text.index("CLAUDE.md"), text.index("drifted-skill"))

    def test_materials_marks_the_expired_evidence(self) -> None:
        """No expiry comparison on this page, and the panel says exactly that.

        The recorded dates are still shown -- they are ledger data -- but
        nothing is marked expired, because marking would claim a comparison
        this page did not make.
        """
        text = self._panel("materials")["text"]
        self.assertNotIn("evidence expired", text)
        self.assertIn("dashboard.py build", text)
        self.assertIn("2026-04-02", text)

    def test_changes_annotates_a_target_with_its_computed_drift_state(self) -> None:
        """No drift report, so no state column at all.

        A column of "not recorded" would read as a gap in the ledger. The
        gap is in this page: nothing here compared a target against disk.
        """
        panel = self._panel("changes")
        self.assertNotIn("State", panel["headers"])
        self.assertNotIn("DRIFTED", panel["text"])

    def test_rollback_renders_a_block_for_every_run_with_a_backup(self) -> None:
        """The blocks still exist -- the runs did keep backups -- and each one
        says its preview is missing rather than showing four empty sets."""
        blocks = self._panel("rollback")["runs"]
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            with self.subTest(block=block["text"][:24]):
                self.assertEqual(block["headings"], [])
                self.assertIn("No preview was computed", block["text"])

    def test_rollback_lists_all_four_sets_even_when_they_are_empty(self) -> None:
        """There are no sets to list: the panel names the command instead.

        This is the distinction the whole static mode rests on. Four headings
        with "none" under each would say a preview ran and found nothing,
        which is a claim no static page is entitled to make.
        """
        panel = self._panel("rollback")
        self.assertEqual(panel["headings"], [])
        self.assertIn("dashboard.py rollback-preview", panel["text"])

    def test_rollback_shows_the_broken_indicator_and_its_reason(self) -> None:
        """No preview, so no indicator: `BROKEN` is a computed verdict.

        The only chips left are the two the ledger itself recorded -- what
        each run said about testing its own rollback -- and each still
        carries its severity glyph, which is what makes it legible without
        colour.
        """
        panel = self._panel("rollback")
        self.assertNotIn("BROKEN", panel["text"])
        self.assertEqual(
            [chip.lstrip("▲✕●") for chip in panel["vocab"]],
            ["NOT_TESTED", "PARTIAL"],
        )

    def test_rollback_fills_all_four_sets_when_the_preview_does(self) -> None:
        """Nothing to fill them from, and the run still has to be listed."""
        block = self._run_block("rollback", "RUN-2026-001")
        self.assertNotIn("AT_RISK", block["text"])
        self.assertIn("No preview was computed", block["text"])

    def test_rollback_sorts_the_broken_preview_above_the_at_risk_one(self) -> None:
        """With no previews every run ranks the same, so recency decides and
        the newer of the two backed-up runs comes first."""
        self.assertIn("RUN-2026-000", self._panel("rollback")["runs"][0]["text"])

    def test_a_script_payload_in_a_preview_set_is_inert(self) -> None:
        """The payload reaches this panel only through a preview, and there
        is none -- so the assertion is that it is absent, not inert."""
        self.assertNotIn(XSS_TITLE, self._panel("rollback")["texts"])


@unittest.skipUnless(NODE, "node is not on PATH -- this suite needs it")
class RuntimeDegradedPanelTests(ShellTemplateTestCase):
    """Design spec section 14: one computation failed, one panel degrades.

    The distinction this pins is the one a reader acts on. "Not computed on
    this page" is a static page and one command away; "this computation
    failed while the page was built" is a broken build, and running the same
    command again may not fix it. Both show no number, and they must not show
    the same sentence.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.proc = boot_shell(cls.text, cls.islands, DEGRADED_FIXTURE_PAYLOAD)
        try:
            cls.facts = json.loads(cls.proc.stdout)  # type: ignore[attr-defined]
        except ValueError:
            cls.facts = {}  # type: ignore[attr-defined]

    def _card(self, label: str) -> dict:
        for card in self.facts["overview"]["cards"]:  # type: ignore[attr-defined]
            if card["label"] == label:
                return card
        raise AssertionError("no overview card labelled " + label)

    def test_the_shell_booted(self) -> None:
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)  # type: ignore[attr-defined]

    def test_the_failed_computation_is_named_in_the_overview(self) -> None:
        """`degradedKeys` already lists it; the card must not contradict it."""
        self.assertIn("computed.drift", self.facts["overview"]["text"])  # type: ignore[attr-defined]

    def test_the_dependent_card_shows_no_number(self) -> None:
        card = self._card("Drifted items")
        self.assertIsNone(card["count"])
        self.assertEqual(card["unavailable"], "unavailable")

    def test_the_dependent_card_says_the_computation_failed(self) -> None:
        """Not "run this command": the command already ran and did not work."""
        note = self._card("Drifted items")["note"]
        self.assertIn("failed", note)
        self.assertNotIn("dashboard.py drift", note)

    def test_the_other_cards_still_hold_their_numbers(self) -> None:
        """One panel degrades, not all of them (design spec section 14)."""
        self.assertEqual(self._card("Rollbacks at risk")["count"], "2")
        self.assertEqual(self._card("Expired evidence")["count"], "1")

    def test_inventory_falls_back_to_the_recorded_state(self) -> None:
        """A failed drift report is not a drift report: no chip, no claim."""
        self.assertEqual(self.facts["inventory"]["vocab"], [])  # type: ignore[attr-defined]
        self.assertEqual(self.facts["inventory"]["rows"], 3)  # type: ignore[attr-defined]


@unittest.skipUnless(NODE, "node is not on PATH -- this suite needs it")
class RuntimeMaliciousKeyPanelTests(ShellTemplateTestCase):
    """I1: ledger strings used as plain-object keys, run against the real
    shell rather than argued about in the abstract.

    `MALICIOUS_KEY_FIXTURE_LEDGER` carries a record id of "toString" and a
    SUPERSEDED record whose `links.adrs` names "constructor"; the computed
    report adds a drift summary keyed "toString" and a baseline item whose
    drift state is "constructor". Before this fix, the second of those threw
    inside `supersessionIndex` (`index["constructor"].push` on the inherited
    Function, which has no such method) and the first would have returned
    `Object.prototype.toString` to `decisionRow`'s `.forEach` call. Both are
    exercised by simply rendering the Decisions panel; nothing here calls
    either function directly, because a fix that only worked when called
    directly, and not from the render path, would not be a fix.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            MALICIOUS_KEY_FIXTURE_PAYLOAD,
            probe=MALICIOUS_KEY_PROBE,
            extra_globals={"__AIO_PANEL_IDS__": list(PANEL_IDS)},
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def test_the_shell_booted_without_throwing(self) -> None:
        """(a): a "constructor"-linking, "toString"-named ledger must not
        crash the render. Before the `Object.create(null)` fix in
        `supersessionIndex`, this exited nonzero with an uncaught TypeError.
        """
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )
        self.assertEqual(self.facts.get("failures"), [])

    def test_every_panel_is_present(self) -> None:
        """(a) continued: all nine sections, not just the ones this fixture
        happens to populate."""
        self.assertEqual(self.facts.get("tabs"), 9)
        present = self.facts.get("panelsPresent", {})
        for panel in PANEL_IDS:
            with self.subTest(panel=panel):
                self.assertTrue(present.get(panel), panel + " is absent")

    def test_the_footer_is_populated(self) -> None:
        """(a) continued: a render that crashed partway would leave the
        footer empty rather than absent, since `renderFooter` runs last."""
        self.assertGreater(self.facts.get("footerEntries", 0), 0)

    def test_the_decisions_panel_rendered_both_records(self) -> None:
        """The render this fixture is really testing: the ADR with id
        "toString" and the SUPERSEDED ADR whose links.adrs names
        "constructor" both reach the Decisions table."""
        self.assertEqual(self.facts.get("decisionsRows"), 2)
        self.assertIn("toString", self.facts.get("decisionsText", ""))
        self.assertIn("constructor", self.facts.get("decisionsText", ""))

    def test_drift_summary_key_toString_does_not_inflate_the_card(self) -> None:
        """(b): the fixture's five real states are all zero; only a lookup
        that treated "toString" as if it were one of `DRIFT_SEVERITY`'s own
        keys would make this card show anything but a clean zero.
        """
        card = self.facts.get("driftCard")
        self.assertIsNotNone(card, "no Drifted items card in the render")
        self.assertEqual(card["count"], "0")
        self.assertIn("card-info", card["severity"])

    def test_drift_state_constructor_gets_the_unknown_treatment(self) -> None:
        """(c): an inventory item whose drift state is "constructor" must
        fall through `inventorySeverity`'s explicit unknown-state branch --
        rendered as a plain "row-warning" -- rather than reading back
        `DRIFT_SEVERITY`'s inherited `constructor` (the Object function) and
        stringifying it into the row's class list.
        """
        rows = self.facts.get("inventoryRows", [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("row-warning", row["classes"])
        for css_class in row["classes"]:
            with self.subTest(css_class=css_class):
                self.assertNotIn("function", css_class.lower())
                self.assertNotIn("[native code]", css_class)
        self.assertIn("constructor", row["text"])


if __name__ == "__main__":
    unittest.main()
