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
    "function renderBacklog(section, state)",
    "function renderDecisions(section, state)",
    "function renderMaterials(section, state)",
    "function renderHelp(section)",
)

# Task 5's three. With these, every panel in `PANELS` has a renderer and the
# instructional fall-through in `renderPanels` is unreachable -- it stays as
# the guard for a tenth panel added without one.
TASK_5_RENDERERS = (
    "function renderChanges(section, state)",
    "function renderProvenance(section, state)",
    "function renderRollback(section, state)",
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
    "changes.self_reported_other",
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
    "rollback.degraded",
    "help.results",
)

# Every i18n key Task 6 adds, named for the same reason Task 4's and Task
# 5's are. The instruction templates themselves are deliberately absent:
# they are not dictionary content at all (build spec section 1.4) and a key
# for them would be the first step towards translating one.
TASK_6_KEYS = (
    "table.actions",
    "action.copy_instruction",
    "action.queue_add",
    "action.export",
    "action.copied",
    "action.queued",
    "action.copy_manual",
    "action.copy_manual_label",
    "action.instructions_are_english",
    "queue.title",
    "queue.empty",
    "queue.order",
    "queue.copy_all",
    "queue.clear",
    "queue.cleared",
    "rollback.actions",
    "rollback.prepare",
    "rollback.confirm",
    "rollback.confirm_prompt",
    "rollback.armed",
    "rollback.locked",
    "rollback.copy",
    "overview.projects",
    "projects.open_root",
    "projects.open_ledger",
    "projects.no_path",
    "projects.unreachable_note",
)

# --- Task 6: the action model ------------------------------------------
#
# Build spec section 1.4 is the whole of this section's reason to exist: a
# `file:` page cannot run a command, so every button produces text for a
# human to paste at an agent -- and the only text it may produce is one of
# four fixed English sentences plus a record id the shell validated itself.
# No string that came out of a material may ever reach the clipboard.

# The four canonical templates. English in every UI language because they
# address the agent rather than the reader.
INSTRUCTION_TEMPLATES = {
    "implement": "Implement proposal",
    "rollback": "Roll back run",
    "revisit": "Revisit backlog entry",
    "audit": "Re-audit material",
}

# `ledger.schema.json`'s own record-id pattern, spelled the way JavaScript
# spells it. It must appear in the template exactly once: a second copy is
# a second definition, and two definitions drift.
ID_RE_SOURCE = r"/^(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$/"

# The one line in the whole file that concatenates instruction text. Pinned
# verbatim, and pinned at exactly one occurrence, so "assembled in exactly
# one place" is a property a grep can read off the source.
INSTRUCTION_ASSEMBLY = 'TEMPLATES[action] + " " + id'

# The spellings a `copyText(` argument is allowed to take. This is the
# amendment to the brief's Step 1: pinning a call *count* would break on
# every honest refactor, while pinning the *shape of every argument* is the
# property that actually matters -- text reaches the clipboard only from
# `instructionFor` (through a local named `instruction`), from `queueText`
# (which only joins those), or from `exportText` (which is `JSON.stringify`
# of a payload object).
COPY_TEXT_ARGUMENT = re.compile(
    r"^(instruction|queueText\(\)|exportText\([A-Za-z_$][A-Za-z0-9_$]*\))$"
)

# The same amendment, for `enqueue(`: the queue's whole safety property is
# that every entry's text is one of the four canonical instructions, never a
# record field, so the second argument may only ever be the local named
# `instruction` (bound by `instructionFor`, per the allow-list above). The
# first argument names the action kind, either `instructionActions`'s own
# `kind` parameter or the literal `"rollback"` `rollbackActions` calls it
# with -- never anything read off a record.
ENQUEUE_ARGUMENT = re.compile(r'^(kind|"(implement|rollback|revisit|audit)"), instruction$')

# What a copied instruction may look like, character for character.
INSTRUCTION_LINE = re.compile(
    r"^(Implement proposal|Roll back run|Revisit backlog entry|Re-audit material) "
    r"(MAT|PROP|RUN|ADR|BASE)-\d{4}-\d{3}(-P)?$"
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

# Every `id="..."` in the shipped markup. Feeds the DOM stub's fail-closed
# `getElementById`, so the runtime harness renders against the elements the
# template really carries and nothing else.
ELEMENT_ID = re.compile(r'\sid="([A-Za-z0-9_-]+)"')

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
    "{ safeHref: safeHref, attrAllowed: attrAllowed, h: h, "
    "TEMPLATES: TEMPLATES, instructionFor: instructionFor, fileUrl: fileUrl, "
    "buildPaletteIndex: buildPaletteIndex };\n"
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
            # I1: the run names two fields the Changes panel has no heading
            # for -- "tests" is not a real ledger field at all, "backup" is
            # real but belongs to Rollback -- so both used to vanish here
            # with no badge at all. `RuntimeMaliciousKeyPanelTests` extends
            # this same check with hostile names on top.
            "self_reported": ["targets", "tests", "backup"],
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

# Design spec section 14: a build that succeeded with two sub-computations
# that did not (drift, and -- I2 -- previews). Each key holds an error
# message instead of a report, and the panel that depends on it must name
# the missing guarantee rather than show a zero. Two degrade rather than one
# so the fixture also proves the Rollback panel's own degraded sentence
# (`rollback.degraded`) renders instead of the overview card's
# (`card.degraded`), which is I2: before the fix, `unavailableNoteKey`
# always returned `card.degraded`, and its "the count below" would have
# printed in a panel that carries no count at all.
DEGRADED_FIXTURE_PAYLOAD = dict(
    FIXTURE_PAYLOAD,
    computed=dict(
        FIXTURE_COMPUTED,
        drift={"error": "unknown client 'nope'"},
        previews={"error": "backup verification crashed"},
    ),
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
    "sequences": {"MAT": 0, "PROP": 0, "RUN": 1, "ADR": 2, "BASE": 1},
    "known_projects": [],
    "records": [
        {
            # I1: the run names "targets" (a known Changes field), plus a
            # hostile-looking string and two non-strings. `selfReportedBadge`
            # and `selfReportedLeftover` only ever compare a listed name by
            # value (`Array.indexOf`) and render it as text -- never use it
            # as an object key -- so "__proto__" here must land as an inert
            # badge, exactly like any other string, and the non-strings must
            # be silently dropped by `selfReportedFields`'s own type filter.
            "id": "RUN-2026-HOSTILE",
            "type": "RUN",
            "title": "A run whose self_reported list carries hostile and non-string entries",
            "status": "IMPLEMENTED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-07",
            "updated": "2026-07-07",
            "file": "records/RUN-2026-HOSTILE.md",
            "links": {},
            "evidence": [],
            "result": "VALIDATED",
            "targets": [],
            "backup": None,
            "rollback": {"tested": "NOT_TESTED"},
            "self_reported": ["targets", "__proto__", None, 7],
        },
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

  // I1: the self-reported badges the hostile-names run rendered in
  // Changes, wherever in its block they landed -- the known-field ones
  // and the leftover line's alike.
  var changes = document.getElementById("aio-panel-changes");
  facts.changesBadges = byClass(changes, "marker").map(function (badge) {
    return {
      field: badge.attributes["data-field"] || null,
      text: badge.textContent
    };
  });

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
        // `appendSet` gives an empty set's placeholder its own
        // `<p class="note">`, distinct from the note paragraph at the top
        // of the block (the indicator/backup/tested line, which is also
        // class "note" but is a longer sentence, never equal to the
        // placeholder alone). M6: a case that wants to count empty sets
        // compares against these exact strings rather than a substring of
        // the whole block's text.
        notes: byClass(node, "note").map(function (n) { return n.textContent; }),
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
    captions: byTag(changes, "CAPTION").map(function (n) { return n.textContent; }),
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

# --- the action fixture ------------------------------------------------
#
# A ledger built to attack the clipboard rather than the DOM. Its material
# is titled like an instruction -- the exact shape a reader would fail to
# notice in a paste buffer -- and its backlog carries an id that is one
# digit too long, which must produce no button at all rather than a button
# that copies an unvalidated string.

# A title that reads as a finished agent instruction. If any button on the
# page could put a title on the clipboard, this is the title that would do
# the damage: pasted at an agent it names a record that does not exist, and
# the trailing tag is the stored-XSS half for good measure.
ACTION_TITLE = "Implement proposal MAT-9999-999 </script>"

# A second ledger string shaped like the rollback template, in a field a
# different renderer reaches (a preview set's reason).
ACTION_REASON = "Roll back run RUN-9999-999"

# Fragments that exist nowhere but in ledger content. No instruction the
# page copies may contain any of them.
ACTION_FRAGMENTS = ("MAT-9999-999", "RUN-9999-999", "</script>", "Roll back run RUN-9999")

# An id one digit too long for `ID_RE`: `BASE-2026-1000` matches the eye and
# not the pattern.
ACTION_BAD_ID = "BASE-2026-1000"

# Three known projects, one of each shape the Open link has to tell apart:
# an absolute Windows path with a space in it (linkable), a root the build
# could not reach (recorded, and deliberately not linkable), and a relative
# string that is not an absolute local path at all (no link, and no crash).
ACTION_WINDOWS_ROOT = "C:\\Users\\a b\\proj"
ACTION_WINDOWS_LEDGER = "C:\\Users\\a b\\proj\\.agent-audit\\ledger.json"
ACTION_WINDOWS_URL = "file:///C:/Users/a%20b/proj"
ACTION_WINDOWS_LEDGER_URL = "file:///C:/Users/a%20b/proj/.agent-audit/ledger.json"

ACTION_FIXTURE_LEDGER = {
    "schema_version": "1.0",
    "ledger_id": "actions",
    "scope": "project",
    "language": "en",
    "client": "claude-code",
    "adapter_version": 2,
    "created": "2026-07-01",
    "updated": "2026-07-31",
    "id_authority": True,
    "sequences": {"MAT": 1, "PROP": 1, "RUN": 1, "ADR": 1, "BASE": 1},
    "known_projects": [
        {
            "project_root": ACTION_WINDOWS_ROOT,
            "ledger_path": ACTION_WINDOWS_LEDGER,
            "last_seen": "2026-07-01",
            "last_digest": DIGEST,
            "status": "OK",
        },
        {
            "project_root": "/gone",
            "ledger_path": "/gone/.agent-audit/ledger.json",
            "last_seen": "2026-07-01",
            "last_digest": DIGEST,
            "status": "UNREACHABLE",
        },
        {
            "project_root": "relative/path",
            "ledger_path": "relative/path/ledger.json",
            "last_seen": "2026-07-01",
            "last_digest": DIGEST,
            "status": "OK",
        },
    ],
    "records": [
        {
            "id": "MAT-2026-000",
            "type": "MATERIAL",
            "title": ACTION_TITLE,
            "status": "ANALYZED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-02",
            "updated": "2026-07-02",
            "file": "records/MAT-2026-000.md",
            "links": {},
            "evidence": [
                {
                    "source": ACTION_TITLE,
                    "kind": "vendor documentation",
                    "verified_on": "2026-01-02",
                    "time_sensitive": False,
                }
            ],
        },
        {
            "id": "PROP-2026-000",
            "type": "PROPOSAL",
            "title": ACTION_TITLE,
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
            "title": ACTION_REASON,
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
                    "after_digest": DIGEST_AFTER,
                    "reversible": True,
                    "residual_effect": None,
                }
            ],
            "backup": {"digest": DIGEST, "verified": True},
            "rollback": {"tested": "PASSED"},
            "self_reported": ["targets"],
        },
        {
            "id": "ADR-2026-000",
            "type": "ADR",
            "title": ACTION_TITLE,
            "status": "DECIDED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-05",
            "updated": "2026-07-05",
            "file": "records/ADR-2026-000.md",
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
                    "attributes": {},
                    "origin": "pre-existing",
                    "state": "present",
                    "portable": True,
                }
            ],
        }
    ],
    "backlog": [
        {
            "id": "MAT-2026-000",
            "classification": "MONITOR",
            "reason": ACTION_REASON,
            "revisit_trigger": "upstream ships the fix",
            "revisit_after": None,
        },
        {
            "id": ACTION_BAD_ID,
            "classification": "NEEDS MORE EVIDENCE",
            "reason": "an id one digit too long for the pattern",
            "revisit_trigger": "never",
            "revisit_after": None,
        },
    ],
}

ACTION_FIXTURE_COMPUTED = {
    "drift": {"baselines": [], "runs": [], "summary": {}},
    "previews": {
        "RUN-2026-000": {
            "run": "RUN-2026-000",
            "indicator": "HEALTHY",
            "backup": {"verified": True, "reason": None},
            "will_be_restored": [
                {
                    "anchor": "$USER_CONFIG/settings.json",
                    "kind": "instruction-file",
                    "state": "IN_PLACE",
                }
            ],
            "will_not_change": [],
            "cannot_be_restored": [],
            "residual_effects": [ACTION_REASON],
        }
    },
    "expired_evidence": [],
    "unreachable_projects": ["/gone"],
}

ACTION_FIXTURE_PAYLOAD = {
    "payload_schema": 1,
    "mode": "built",
    "generated_at": "2026-07-31T00:00:00Z",
    "tool_version": "0.4.0",
    "lang": "en",
    "ledger": ACTION_FIXTURE_LEDGER,
    "computed": ACTION_FIXTURE_COMPUTED,
}

# The action probe. It does what no static test can: it presses every button
# the page built and reads back what the clipboard actually received.
#
# Three phases, because the rollback control is the one action whose whole
# point is that a single press does nothing.
#
#   A. press every action button in every panel, in document order. The
#      rollback block's order is prepare, copy, queue, export, confirm --
#      so the copy and queue presses in this phase happen *before* the
#      confirm, and must produce nothing.
#   B. press the rollback copy again, now that phase A ended on the confirm.
#   C. queue the rollback and copy the whole queue, to read the batch order.
#
# The clipboard is the DOM stub's own record of what `document.execCommand`
# was asked to copy, which is the real path a `file:` page takes: a file
# origin is not a secure context, so `navigator.clipboard` is absent and the
# selection tier is what runs.
ACTION_PROBE = r"""
(function () {
  var bad = [];
  var api = globalThis.__AIO_EXPORTS__;
  var clip = globalThis.__AIO_CLIPBOARD__;
  var facts = { failures: bad };

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  function classes(node) {
    var value = node.attributes ? node.attributes["class"] : null;
    return typeof value === "string" ? value.split(" ") : [];
  }

  function actionNodes(root, tag) {
    var out = [];
    walk(root, function (node) {
      if (node.tagName === tag && classes(node).indexOf("action") !== -1) {
        out.push(node);
      }
    });
    return out;
  }

  function press(node) {
    (node.listeners.click || []).forEach(function (fn) {
      fn({ preventDefault: function () {}, stopPropagation: function () {} });
    });
  }

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  if (!api) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }
  if (!clip) {
    bad.push("the DOM stub recorded no clipboard");
    report(2);
  }

  /* The gate itself, driven directly rather than through a button, so a
     refusal is named by an input rather than inferred from a missing
     control. */
  facts.instructionFor = [
    ["audit", "MAT-2026-000", api.instructionFor("audit", "MAT-2026-000")],
    ["audit", "MAT-2026-000-P", api.instructionFor("audit", "MAT-2026-000-P")],
    ["audit", "BASE-2026-1000", api.instructionFor("audit", "BASE-2026-1000")],
    ["audit", "MAT-2026-00", api.instructionFor("audit", "MAT-2026-00")],
    ["audit", "MAT-2026-000 x", api.instructionFor("audit", "MAT-2026-000 x")],
    ["audit", "x MAT-2026-000", api.instructionFor("audit", "x MAT-2026-000")],
    ["constructor", "MAT-2026-000", api.instructionFor("constructor", "MAT-2026-000")],
    ["toString", "MAT-2026-000", api.instructionFor("toString", "MAT-2026-000")],
    ["__proto__", "MAT-2026-000", api.instructionFor("__proto__", "MAT-2026-000")],
    ["audit", null, api.instructionFor("audit", null)],
    [null, "MAT-2026-000", api.instructionFor(null, "MAT-2026-000")]
  ];

  facts.templatesFrozen = Object.isFrozen(api.TEMPLATES);
  facts.templatesNullPrototype = Object.getPrototypeOf(api.TEMPLATES) === null;
  facts.templates = Object.keys(api.TEMPLATES).map(function (name) {
    return [name, api.TEMPLATES[name]];
  });

  facts.fileUrl = [
    ["C:\\Users\\a b\\proj", api.fileUrl("C:\\Users\\a b\\proj")],
    ["/home/a b", api.fileUrl("/home/a b")],
    ["C:\\a%b\\c#d", api.fileUrl("C:\\a%b\\c#d")],
    ["relative/path", api.fileUrl("relative/path")],
    ["", api.fileUrl("")],
    ["\\\\server\\share", api.fileUrl("\\\\server\\share")],
    ["//server/share", api.fileUrl("//server/share")],
    ["$USER_CONFIG/settings.json", api.fileUrl("$USER_CONFIG/settings.json")]
  ];

  var panels = globalThis.__AIO_PANEL_IDS__ || [];

  /* Every Open link the page built, with the href the gate let through. */
  facts.openLinks = [];
  panels.forEach(function (name) {
    var root = document.getElementById("aio-panel-" + name);
    if (!root) { return; }
    actionNodes(root, "A").forEach(function (node) {
      facts.openLinks.push({
        panel: name,
        label: node.textContent,
        href: node.attributes.href,
        title: node.attributes.title || null
      });
    });
  });

  /* Phase A. */
  var markA = clip.length;
  facts.pressed = [];
  panels.forEach(function (name) {
    var root = document.getElementById("aio-panel-" + name);
    if (!root) { return; }
    actionNodes(root, "BUTTON").forEach(function (node) {
      facts.pressed.push({ panel: name, label: node.textContent });
      press(node);
    });
  });
  facts.phaseA = clip.slice(markA);

  /* Phase B: the same rollback copy control, after phase A ended on the
     confirm. The node is re-found rather than remembered, because the queue
     drawer re-renders and a stale reference would prove nothing. */
  function rollbackButton(label) {
    var found = null;
    actionNodes(document.getElementById("aio-panel-rollback"), "BUTTON")
      .forEach(function (node) {
        if (node.textContent === label) { found = node; }
      });
    return found;
  }

  var markB = clip.length;
  var copy = rollbackButton(globalThis.__AIO_LABELS__.rollback_copy);
  if (copy === null) {
    bad.push("the rollback panel built no copy control");
    report(2);
  }
  /* M2: the selection tier is the only one reachable here -- this probe
     seeds no clipboard API, exactly like a `file:` page -- and it
     focuses the manual copy box to select it. It must give focus back
     afterwards: a reader's place on the page should survive a click of
     "Copy" the same way the clipboard survives it. */
  var focusHolder = document.createElement("div");
  focusHolder.focus();
  facts.focusBeforeCopy = document.activeElement === focusHolder;
  press(copy);
  facts.focusRestoredAfterCopy = document.activeElement === focusHolder;
  facts.phaseB = clip.slice(markB);

  /* Phase C: queue the rollback, then copy the whole queue. */
  var markC = clip.length;
  var queue = rollbackButton(globalThis.__AIO_LABELS__.queue_add);
  if (queue === null) {
    bad.push("the rollback panel built no queue control");
    report(2);
  }
  /* I1: `renderQueue` throws the whole drawer away and rebuilds it on
     every call, so a reader who opened it must have that state read off
     the outgoing node and restored on the new one -- not merely
     preserved by accident because nothing changed. Phase A already
     queued the implement instruction, so a drawer exists; force it
     open, add one more entry, and check the *new* drawer this press
     produces. */
  var queueHost = document.getElementById("aio-queue");
  var drawerBefore = queueHost.firstChild;
  if (drawerBefore) { drawerBefore.open = true; }
  facts.drawerOpenBeforeQueue = drawerBefore ? drawerBefore.open === true : null;
  press(queue);
  facts.drawerOpenAfterQueue = queueHost.firstChild
    ? queueHost.firstChild.open === true
    : null;
  var host = document.getElementById("aio-queue");
  var copyAll = null;
  actionNodes(host, "BUTTON").forEach(function (node) {
    if (node.textContent === globalThis.__AIO_LABELS__.copy_all) { copyAll = node; }
  });
  if (copyAll === null) {
    bad.push("the queue drawer built no copy-all control");
    report(2);
  }
  press(copyAll);
  facts.phaseC = clip.slice(markC);
  facts.queueText = host.textContent;

  /* The manual tier: the box is revealed and holds exactly what the last
     copy put on the clipboard. */
  facts.copyBox = {
    hidden: document.getElementById("aio-copybox").hidden,
    value: document.getElementById("aio-copytext").value
  };
  facts.live = document.getElementById("aio-live").textContent;
  facts.clipboard = clip.slice(0);

  report(bad.length === 0 ? 0 : 1);
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


def call_arguments(text: str, name: str) -> list[str]:
    """Every argument list `name(...)` is *called* with, paren-matched.

    The definition is skipped: `function copyText(text)` is not a call site,
    and counting it would make the allow-list test pass on a parameter name.
    Paren-matched rather than split on commas, so a nested call reaches the
    caller whole -- which is the point, since `copyText(exportText(record))`
    is precisely the shape being allowed.
    """
    found: list[str] = []
    for match in re.finditer(r"(?<![\w$.])" + re.escape(name) + r"\(", text):
        if text[: match.start()].rstrip().endswith("function"):
            continue
        index = match.end()
        depth = 1
        while depth:
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        found.append(text[match.end() : index])
    return found


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

    # Every id the template really ships, so the stub can answer null for
    # anything else instead of conjuring an element. Without this an
    # ablation that deletes an element from the body is invisible to every
    # runtime case: the shell asks for it, the stub invents it, and the page
    # under test is not the page that shipped.
    ids = sorted(set(ELEMENT_ID.findall(text)))

    preamble_lines = [
        "globalThis.__AIO_ISLANDS__ = " + json.dumps(seeded) + ";",
        "globalThis.__AIO_ELEMENT_IDS__ = " + json.dumps(ids) + ";",
        'globalThis.__AIO_HASH__ = "";',
        'globalThis.__AIO_LANG__ = "en";',
    ]
    for name, value in (extra_globals or {}).items():
        preamble_lines.append("globalThis." + name + " = " + json.dumps(value) + ";")
    preamble_lines.append("")
    preamble = "\n".join(preamble_lines)
    # The preamble goes *before* the stub. It used to go after, which meant
    # every global the stub reads at definition time -- `__AIO_HASH__` and
    # `__AIO_LANG__` -- was still undefined when it read them, so the shell
    # always booted on an empty fragment however a caller seeded it. Task 7
    # boots on `#panel=...&f=...` to test a bookmarked filter, which is the
    # case that made the ordering matter.
    script = "\n".join(
        (preamble, DOM_STUB.read_text(encoding="utf-8"), wired, probe)
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

        This was written expecting Task 6 to relax it. Task 6 did not, and
        the reason is worth keeping: the payload carries no resolved path
        for anything these panels show. An anchor is stored as `$NAME/...`
        by construction -- `ledgerlib.paths.resolve_anchored` refuses an
        absolute one -- and neither the drift report nor the rollback
        preview records the file it actually opened, only the anchor it
        classified. So a target anchor is exactly what an evidence source
        already is: a string that is frequently a path and is never a click.

        The Open links Task 6 did add live on the Overview, over
        `known_projects[].project_root` and `.ledger_path`, which the ledger
        stores as real paths and `build` stats directly. See `fileUrl` in
        the shell.
        """
        for signature in (
            "function renderChanges(section, state)",
            "function runBlock(record, states)",
            "function targetRow(target, states)",
            "function renderProvenance(section, state)",
            "function chainBlock(entry, byId, expired)",
            "function chainList(record, byId, expired)",
            "function renderRollback(section, state)",
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
            "function renderBacklog(section, state)",
            "function renderDecisions(section, state)",
            "function renderMaterials(section, state)",
            "function renderChanges(section, state)",
            "function renderRollback(section, state)",
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
            "function renderMaterials(section, state)",
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

    def test_changes_gives_each_runs_targets_table_a_distinct_caption(self) -> None:
        """M4: `changes.caption` is one shared sentence, repeated once per
        run block (four runs, four tables) -- so on its own it is not an
        accessible name a screen reader could use to tell one table from
        another. The run id is appended as a second text node at render
        time, never interpolated into the dictionary string, so every
        language keeps one whole sentence and only gains a distinct suffix.
        """
        captions = self._panel("changes")["captions"]
        self.assertEqual(len(captions), 4)
        for run_id in ("RUN-2026-000", "RUN-2026-001", "RUN-2026-002", "RUN-2026-003"):
            with self.subTest(run=run_id):
                self.assertTrue(
                    any(run_id in caption for caption in captions),
                    captions,
                )
        self.assertEqual(len(captions), len(set(captions)))

    def test_changes_badges_exactly_the_fields_the_run_named(self) -> None:
        """Design spec section 5's marker, driven by `self_reported`.

        `RUN-2026-000` lists only `targets`; `RUN-2026-001` lists `result`,
        `backup`, and `rollback.tested` too. A badge on a field the run did
        not name would be this page inventing a doubt, and a missing badge
        would be it hiding one -- so the assertion is set equality, in both
        directions, per run.

        `backup` and `rollback.tested` have no heading of their own in the
        Changes panel -- they belong to Rollback -- which is exactly I1's
        finding: before the fix, a field this panel had no heading for was
        silently unbadged here. `selfReportedLeftover` is what puts them on
        screen, on the one extra line, rather than dropping them.
        """
        first = self._run_block("changes", "RUN-2026-000")
        self.assertEqual({badge["field"] for badge in first["badges"]}, {"targets"})
        second = self._run_block("changes", "RUN-2026-001")
        self.assertEqual(
            {badge["field"] for badge in second["badges"]},
            {"targets", "result", "backup", "rollback.tested"},
        )
        for badge in first["badges"] + second["badges"]:
            with self.subTest(field=badge["field"]):
                self.assertIn("SELF-REPORTED", badge["text"])

    def test_changes_shows_self_reported_fields_that_have_no_heading_here(
        self,
    ) -> None:
        """I1: design spec section 7.4 asks for every listed field to be
        marked visibly. `RUN-2026-002` names `targets` (which already has a
        badge, next to the "Targets" heading), plus `tests` (not a real
        ledger field at all) and `backup` (a real one, but Rollback's, not
        Changes'). Before the fix, the badge for the two unknown fields
        never appeared anywhere on this panel -- not just unlabelled, gone.
        The fix's whole promise is that a name the run listed is never
        silently dropped, so all three must be visible, and the two that
        have no heading of their own must carry their own name as text
        since nothing else on the page names them.
        """
        block = self._run_block("changes", "RUN-2026-002")
        self.assertEqual(
            {badge["field"] for badge in block["badges"]},
            {"targets", "tests", "backup"},
        )
        by_field = {badge["field"]: badge["text"] for badge in block["badges"]}
        for field in ("tests", "backup"):
            with self.subTest(field=field):
                self.assertIn(field, by_field[field])
                self.assertIn("SELF-REPORTED", by_field[field])

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

        M6: the count is asserted against the dictionary's own
        `value.none` string, fetched from the parsed dictionary rather than
        hard-coded, and only within the set lists' own placeholders --
        `notes`, not the whole block's text -- so a coincidental "none"
        substring elsewhere in the block could never inflate it.
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
        none_label = json.loads(self.islands["aio-i18n"])["en"]["value.none"]
        self.assertEqual(
            sum(1 for note in block["notes"] if note == none_label), 3
        )

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
    """Design spec section 14: two computations failed, two panels degrade.

    The distinction this pins is the one a reader acts on. "Not computed on
    this page" is a static page and one command away; "this computation
    failed while the page was built" is a broken build, and running the same
    command again may not fix it. Both show no number, and they must not show
    the same sentence.

    `previews` degrades alongside `drift` (I2): the overview's "Rollbacks at
    risk" card and the Rollback panel itself both depend on it, and the two
    must not read alike either. The card's `card.degraded` is written for a
    card ("the count below is missing"); the panel has no count below it,
    so it carries its own sentence (`rollback.degraded`) naming its own
    command instead of quietly reusing the card's.
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
        """Two of the four indicator cards degrade in this fixture, not all
        of them (design spec section 14): "Expired evidence" depends on
        neither `drift` nor `previews`, so it still holds its number."""
        self.assertEqual(self._card("Expired evidence")["count"], "1")

    def test_inventory_falls_back_to_the_recorded_state(self) -> None:
        """A failed drift report is not a drift report: no chip, no claim."""
        self.assertEqual(self.facts["inventory"]["vocab"], [])  # type: ignore[attr-defined]
        self.assertEqual(self.facts["inventory"]["rows"], 3)  # type: ignore[attr-defined]

    # --- I2: the Rollback panel's own degraded sentence -----------------

    def test_the_rollbacks_card_shows_no_number_either(self) -> None:
        """`previews` degrades too, so this card refuses a number the same
        way "Drifted items" does."""
        card = self._card("Rollbacks at risk")
        self.assertIsNone(card["count"])
        self.assertEqual(card["unavailable"], "unavailable")

    def test_the_rollbacks_card_still_uses_the_generic_degraded_sentence(self) -> None:
        """The overview card is not the panel: its degraded copy is written
        for a card with a count below it, and that has not changed."""
        note = self._card("Rollbacks at risk")["note"]
        self.assertIn("count below", note)

    def test_the_rollback_panel_names_its_own_failed_computation(self) -> None:
        """I2: the panel's own sentence, not the overview card's. It must
        still say the computation failed and still name a command a reader
        can run for a live answer."""
        text = self.facts["rollback"]["text"]  # type: ignore[attr-defined]
        self.assertIn("failed", text)
        self.assertIn("dashboard.py rollback-preview", text)

    def test_the_rollback_panel_does_not_reuse_the_overview_cards_sentence(
        self,
    ) -> None:
        """Before the fix, `unavailableNoteKey` had one degraded key
        (`card.degraded`) for every caller, so this exact sentence -- written
        for a card, and meaningless in a panel with no count below it --
        would have appeared here too."""
        text = self.facts["rollback"]["text"]  # type: ignore[attr-defined]
        self.assertNotIn("count below", text)


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

    def test_a_hostile_self_reported_name_renders_as_inert_text(self) -> None:
        """I1, run against the real shell: `RUN-2026-HOSTILE` names `targets`
        (a known Changes field) and the string `"__proto__"` (unknown to
        this panel, so it lands on the leftover line); a null and a number
        are also in the list and must be silently dropped, exactly as they
        already are for the known badges. Nothing here is a lookup -- a
        listed name is only ever compared by value and rendered as text --
        so a ledger string of `"__proto__"` is just a badge whose name reads
        `"__proto__"`, never a route to `Object.prototype`.
        """
        badges = self.facts.get("changesBadges", [])
        fields = {badge["field"] for badge in badges}
        self.assertEqual(fields, {"targets", "__proto__"})
        by_field = {badge["field"]: badge["text"] for badge in badges}
        self.assertIn("__proto__", by_field["__proto__"])
        self.assertIn("SELF-REPORTED", by_field["__proto__"])


class ActionModelSourceTests(ShellTemplateTestCase):
    """Build spec section 1.4, read off the template text.

    The security property here is narrower and stronger than "the page
    escapes what it renders": no string that came out of a material may
    reach the clipboard *at all*. That is only true if there is exactly one
    place in the file where instruction text is assembled, exactly one
    pattern deciding which ids are allowed, and a closed set of shapes any
    `copyText` argument may take. All three are grep-able properties of the
    source, which is what these cases pin; `RuntimeActionTests` below then
    presses every button and reads the clipboard back.
    """

    shell: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.shell = extract_shell(cls.text)

    def _templates_block(self) -> str:
        at = self.shell.index("var TEMPLATES = ")
        return self.shell[at : self.shell.index("}));", at)]

    def test_the_id_pattern_appears_exactly_once(self) -> None:
        """One definition. A second copy is a second definition."""
        self.assertEqual(self.text.count(ID_RE_SOURCE), 1)

    def test_the_template_map_is_frozen_and_null_prototype(self) -> None:
        """Frozen so nothing can add a fifth template later; null-prototype
        so an action of `"constructor"` reads back undefined rather than the
        inherited function -- the same guard `own` exists for everywhere
        else in this file, needed here because the action half of the lookup
        is a plain string a caller supplies.
        """
        self.assertIn(
            "Object.freeze(Object.assign(Object.create(null)",
            self._templates_block(),
        )

    def test_the_template_map_holds_exactly_the_four_canonical_sentences(self) -> None:
        found = dict(re.findall(r'(\w+):\s*"([^"]*)"', self._templates_block()))
        self.assertEqual(found, INSTRUCTION_TEMPLATES)

    def test_no_instruction_template_is_in_either_dictionary(self) -> None:
        """Design spec section 12.2: the templates address the agent, so
        they stay English in every UI language. A template that acquired a
        dictionary key would be one translation away from an instruction the
        agent was never taught.
        """
        dicts = json.loads(self.islands["aio-i18n"])
        for code, table in dicts.items():
            for sentence in INSTRUCTION_TEMPLATES.values():
                with self.subTest(lang=code, sentence=sentence):
                    self.assertNotIn(sentence, set(table.values()))

    def test_the_assembly_line_appears_exactly_once(self) -> None:
        self.assertEqual(self.shell.count(INSTRUCTION_ASSEMBLY), 1)

    def test_the_assembly_line_lives_inside_instruction_for(self) -> None:
        body = slice_function(self.shell, "function instructionFor(action, id)")
        self.assertIn(INSTRUCTION_ASSEMBLY, body)
        self.assertIn("own(TEMPLATES, action)", body)
        self.assertIn("ID_RE.test(id)", body)

    def test_instruction_for_refuses_by_returning_null(self) -> None:
        """Two refusals, one per half, and neither of them throws: a caller
        renders no control at all when it gets null back.
        """
        body = slice_function(self.shell, "function instructionFor(action, id)")
        self.assertEqual(body.count("return null;"), 2)

    def test_no_template_literal_appears_anywhere_in_the_template(self) -> None:
        """`${` is how a title would get interpolated into an instruction."""
        self.assertNotIn("${", self.text)

    def test_every_copy_text_call_site_takes_an_allowed_argument(self) -> None:
        found = call_arguments(self.shell, "copyText")
        self.assertGreaterEqual(len(found), 4)
        for argument in found:
            with self.subTest(argument=argument):
                self.assertRegex(argument, COPY_TEXT_ARGUMENT)

    def test_every_enqueue_call_site_takes_the_pinned_shape(self) -> None:
        """`copyText`'s allow-list above has a mirror image here: a queue
        entry is only ever the `instruction` local, never a record field
        the reader would not recognize as one of the four templates.
        """
        found = call_arguments(self.shell, "enqueue")
        self.assertGreaterEqual(len(found), 2)
        for argument in found:
            with self.subTest(argument=argument):
                self.assertRegex(argument, ENQUEUE_ARGUMENT)

    def test_every_instruction_variable_comes_from_instruction_for(self) -> None:
        """The allow-list above permits a local named `instruction`; this is
        what stops that name from being assigned anything else.
        """
        found = re.findall(r"var instruction = (.+);", self.shell)
        self.assertGreaterEqual(len(found), 2)
        for source in found:
            with self.subTest(source=source):
                self.assertTrue(source.startswith("instructionFor("), source)

    def test_export_text_is_nothing_but_json_stringify(self) -> None:
        body = slice_function(self.shell, "function exportText(value)")
        self.assertIn("JSON.stringify(value, null, 2)", body)
        self.assertEqual(body.count("return"), 1)

    def test_queue_text_only_joins_what_it_was_handed(self) -> None:
        """No template, no concatenation, no ledger field: the queue's batch
        is the instruction strings already produced by `instructionFor`.
        """
        body = slice_function(self.shell, "function queueText()")
        self.assertIn(".join(", body)
        self.assertNotIn("TEMPLATES", body)
        self.assertNotIn('+ " "', body)

    def test_the_queue_orders_rollbacks_before_implementations(self) -> None:
        """Design spec section 12.2's "safe order": undo before redo. A
        rollback pasted after an implementation would be applied to a setup
        the implementation had already changed.
        """
        at = self.shell.index("var QUEUE_ORDER = ")
        line = self.shell[at : self.shell.index("\n", at)]
        self.assertLess(line.index('"rollback"'), line.index('"implement"'))
        # Statically pins the same guarantee for a machine with no node to
        # run `RuntimeActionTests` on: the batch `queueText` hands to the
        # clipboard is built from `queueOrdered()`, the one function that
        # applies `QUEUE_ORDER` above, not from `QUEUE` directly -- so the
        # sort just proven correct is provably the sort actually used.
        body = slice_function(self.shell, "function queueText()")
        self.assertIn("queueOrdered(", body)

    def test_the_manual_fallback_textarea_ships_read_only(self) -> None:
        """Build spec section 1.4's third tier is not a fallback but a
        constant: the box exists in the shipped markup, so it is there even
        for a browser that has neither clipboard API.
        """
        self.assertEqual(self.text.count("<textarea"), 1)
        self.assertIn('id="aio-copytext"', self.text)
        self.assertIn("readonly", self.text)

    def test_the_live_region_announces_politely(self) -> None:
        self.assertIn('id="aio-live"', self.text)
        self.assertIn('aria-live="polite"', self.text)

    def test_copy_text_fills_the_box_before_it_tries_either_api(self) -> None:
        """Order matters: the box is filled first, so a clipboard call that
        throws, rejects, or silently does nothing still leaves the reader
        with the text in front of them.
        """
        body = slice_function(self.shell, "function copyText(text)")
        self.assertLess(body.index("revealCopy("), body.index("writeViaClipboard("))
        self.assertLess(
            body.index("writeViaClipboard("), body.index("writeViaSelection(")
        )

    def test_the_file_url_builder_refuses_everything_but_a_local_path(self) -> None:
        body = slice_function(self.shell, "function fileUrl(path)")
        self.assertIn('"file:///"', body)
        self.assertIn("encodeURIComponent", body)
        self.assertGreaterEqual(body.count("return null;"), 2)

    def test_the_rollback_control_is_armed_by_a_flag_not_an_attribute(self) -> None:
        """The `disabled` attribute is presentation; the guard is the
        handler's own refusal. A stylesheet, an assistive technology, or a
        future edit that forgets the attribute must not be able to reach the
        instruction.
        """
        body = slice_function(self.shell, "function rollbackActions(record, preview)")
        self.assertIn("if (!armed)", body)
        self.assertEqual(body.count("armed = true;"), 1)


class ActionDictionaryTests(ShellTemplateTestCase):
    """Task 6's strings: in both dictionaries, and actually translated."""

    dicts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dicts = json.loads(cls.islands["aio-i18n"])

    def test_every_task_6_key_is_in_both_dictionaries(self) -> None:
        for code in ("en", "pt-BR"):
            for key in TASK_6_KEYS:
                with self.subTest(lang=code, key=key):
                    self.assertIn(key, self.dicts[code])

    def test_no_task_6_string_was_filled_by_paste(self) -> None:
        """A Portuguese value identical to the English one is a key someone
        copied rather than translated. The exceptions are the ones that are
        the same word in both languages.
        """
        same = {
            key
            for key in TASK_6_KEYS
            if self.dicts["en"][key] == self.dicts["pt-BR"][key]
        }
        self.assertEqual(same, set())


class RuntimeActionTests(ShellTemplateTestCase):
    """The action model, run: every button pressed, the clipboard read back.

    This is the case the whole of Task 6 exists to make true. The fixture's
    material is *titled* like a finished agent instruction -- `Implement
    proposal MAT-9999-999 </script>` -- which is exactly the string nobody
    would notice in a paste buffer. Pressing every control on the page must
    never put it, or any fragment of it, on the clipboard as an instruction.

    The clipboard here is the DOM stub's record of what `document.execCommand`
    was asked to copy, which is the tier a `file:` page actually reaches: a
    file origin is not a secure context, so `navigator.clipboard` is absent
    and the selection path is what runs.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if NODE is None:
            raise unittest.SkipTest("node is not installed")
        labels = json.loads(cls.islands["aio-i18n"])["en"]
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            ACTION_FIXTURE_PAYLOAD,
            probe=ACTION_PROBE,
            extra_globals={
                "__AIO_PANEL_IDS__": list(PANEL_IDS),
                "__AIO_LABELS__": {
                    "rollback_copy": labels["rollback.copy"],
                    "queue_add": labels["action.queue_add"],
                    "copy_all": labels["queue.copy_all"],
                },
            },
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def _fact(self, name: str):
        self.assertIn(
            name,
            self.facts,
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        return self.facts[name]

    def test_the_probe_ran_and_the_shell_booted(self) -> None:
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )
        self.assertEqual(self.facts.get("failures"), [])

    # --- the gate ------------------------------------------------------

    def test_the_template_map_is_frozen_at_runtime(self) -> None:
        self.assertIs(self._fact("templatesFrozen"), True)
        self.assertIs(self._fact("templatesNullPrototype"), True)

    def test_the_template_map_holds_the_four_canonical_sentences(self) -> None:
        self.assertEqual(dict(self._fact("templates")), INSTRUCTION_TEMPLATES)

    def test_instruction_for_answers_only_for_a_valid_pair(self) -> None:
        answers = {
            (row[0], row[1]): row[2] for row in self._fact("instructionFor")
        }
        self.assertEqual(answers[("audit", "MAT-2026-000")], "Re-audit material MAT-2026-000")
        self.assertEqual(
            answers[("audit", "MAT-2026-000-P")], "Re-audit material MAT-2026-000-P"
        )
        for pair, answer in answers.items():
            if pair in (("audit", "MAT-2026-000"), ("audit", "MAT-2026-000-P")):
                continue
            with self.subTest(pair=pair):
                self.assertIsNone(answer)

    def test_an_id_one_digit_too_long_is_refused(self) -> None:
        """The ablation's named case: delete `ID_RE.test(id)` from
        `instructionFor` and this is the assertion that goes red.
        """
        answers = {
            (row[0], row[1]): row[2] for row in self._fact("instructionFor")
        }
        self.assertIsNone(answers[("audit", ACTION_BAD_ID)])

    # --- the clipboard -------------------------------------------------

    def _instructions(self) -> list[str]:
        """Every capture that is not a JSON export."""
        return [
            text
            for text in self._fact("clipboard")
            if not text.lstrip().startswith("{")
        ]

    def _exports(self) -> list[str]:
        return [
            text for text in self._fact("clipboard") if text.lstrip().startswith("{")
        ]

    def test_pressing_every_button_copied_something(self) -> None:
        """A purity assertion over an empty clipboard would pass forever."""
        self.assertGreater(len(self._fact("clipboard")), 4)
        self.assertGreater(len(self._instructions()), 2)
        self.assertGreater(len(self._exports()), 2)

    def test_no_copied_instruction_carries_a_word_from_the_ledger(self) -> None:
        """The headline property. The fixture's material is titled like an
        instruction and its run is titled like a rollback instruction;
        neither may appear in anything the page copies as an instruction.
        """
        for text in self._instructions():
            for fragment in ACTION_FRAGMENTS:
                with self.subTest(copied=text, fragment=fragment):
                    self.assertNotIn(fragment, text)

    def test_every_copied_instruction_line_matches_the_pinned_shape(self) -> None:
        for text in self._instructions():
            for line in text.split("\n"):
                with self.subTest(line=line):
                    self.assertRegex(line, INSTRUCTION_LINE)

    def test_every_json_export_is_a_payload_object_verbatim(self) -> None:
        """An export may -- and does -- carry the hostile title, because it
        is the record itself. What it may not do is carry anything the
        payload does not: each capture must parse back to an object that is
        in the payload, not to something this page composed.
        """
        known = [record for record in ACTION_FIXTURE_LEDGER["records"]]
        known.extend(ACTION_FIXTURE_LEDGER["backlog"])
        known.extend(ACTION_FIXTURE_COMPUTED["previews"].values())
        for text in self._exports():
            with self.subTest(export=text[:60]):
                self.assertIn(json.loads(text), known)

    # --- the two-step ---------------------------------------------------

    def test_the_rollback_instruction_is_not_copied_before_the_confirm(self) -> None:
        """Phase A pressed the rollback copy and queue controls before the
        confirm, in document order. Neither may have produced anything.
        """
        for text in self._fact("phaseA"):
            with self.subTest(copied=text[:60]):
                self.assertNotEqual(text, "Roll back run RUN-2026-000")

    def test_the_rollback_instruction_is_copied_after_the_confirm(self) -> None:
        self.assertEqual(self._fact("phaseB"), ["Roll back run RUN-2026-000"])

    def test_the_queue_puts_the_rollback_before_the_implementation(self) -> None:
        """Phase A queued the implement instruction from the Provenance
        chain; phase C queued the rollback afterwards and copied the batch.
        The batch must still lead with the rollback.
        """
        batch = self._fact("phaseC")
        self.assertEqual(len(batch), 1)
        lines = batch[0].split("\n")
        self.assertEqual(lines[0], "Roll back run RUN-2026-000")
        self.assertIn("Implement proposal PROP-2026-000", lines)
        self.assertLess(
            lines.index("Roll back run RUN-2026-000"),
            lines.index("Implement proposal PROP-2026-000"),
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertRegex(line, INSTRUCTION_LINE)

    # --- the manual tier ------------------------------------------------

    def test_the_read_only_box_is_revealed_and_holds_the_last_text(self) -> None:
        box = self._fact("copyBox")
        self.assertIs(box["hidden"], False)
        self.assertEqual(box["value"], self._fact("clipboard")[-1])

    def test_the_live_region_says_what_happened(self) -> None:
        self.assertNotEqual(self._fact("live"), "")

    # --- focus and drawer state -----------------------------------------

    def test_copying_via_selection_restores_the_prior_focus(self) -> None:
        """M2: the selection tier moves focus onto the manual copy box to
        select it. It must give focus back to whatever had it, not leave
        the reader's place on the page wherever the copy happened to put
        it.
        """
        self.assertIs(self._fact("focusBeforeCopy"), True)
        self.assertIs(self._fact("focusRestoredAfterCopy"), True)

    def test_the_queue_drawer_stays_open_across_a_render(self) -> None:
        """I1: `renderQueue` rebuilds the drawer from scratch on every
        call. `open` is a DOM property, not an attribute -- it is not in
        `ALLOWED_ATTRS` -- so it survives only if the shell reads it off
        the outgoing node and reapplies it to the new one.
        """
        self.assertIs(self._fact("drawerOpenBeforeQueue"), True)
        self.assertIs(self._fact("drawerOpenAfterQueue"), True)

    # --- Open -----------------------------------------------------------

    def test_the_reachable_project_is_the_only_one_with_open_links(self) -> None:
        """Three known projects, one linkable: an absolute Windows root, a
        root the build could not reach, and a relative string that is not a
        local path at all.
        """
        hrefs = [link["href"] for link in self._fact("openLinks")]
        self.assertEqual(
            sorted(hrefs), sorted([ACTION_WINDOWS_URL, ACTION_WINDOWS_LEDGER_URL])
        )

    def test_no_open_link_was_downgraded_by_the_href_gate(self) -> None:
        """`safeHref` answers `#` for anything it refuses, so a builder that
        produced the wrong shape would show up here as a dead fragment.
        """
        for link in self._fact("openLinks"):
            with self.subTest(href=link["href"]):
                self.assertTrue(link["href"].startswith("file:///"), link["href"])
                self.assertNotEqual(link["href"][8], "/")

    def test_the_file_url_builder_answers_match_the_pinned_encoding(self) -> None:
        answers = dict(self._fact("fileUrl"))
        self.assertEqual(answers["C:\\Users\\a b\\proj"], ACTION_WINDOWS_URL)
        self.assertEqual(answers["/home/a b"], "file:///home/a%20b")
        self.assertEqual(answers["C:\\a%b\\c#d"], "file:///C:/a%25b/c%23d")
        for path in (
            "relative/path",
            "",
            "\\\\server\\share",
            "//server/share",
            "$USER_CONFIG/settings.json",
        ):
            with self.subTest(path=path):
                self.assertIsNone(answers[path])

    # --- the buttons themselves -----------------------------------------

    def test_the_invalid_backlog_id_got_no_instruction_button(self) -> None:
        """Two backlog entries, one with an id `ID_RE` refuses. The valid one
        carries a copy and a queue control; the invalid one carries only the
        export, because a control that produced nothing would be worse than
        no control.
        """
        labels = [
            row["label"] for row in self._fact("pressed") if row["panel"] == "backlog"
        ]
        dicts = json.loads(self.islands["aio-i18n"])["en"]
        self.assertEqual(labels.count(dicts["action.copy_instruction"]), 1)
        self.assertEqual(labels.count(dicts["action.queue_add"]), 1)
        self.assertEqual(labels.count(dicts["action.export"]), 2)


# A probe that presses one ordinary copy control and reads back all three
# tiers at once: what the clipboard got, what the box holds, and what the
# live region said.
CLIPBOARD_API_PROBE = r"""
(function () {
  var clip = globalThis.__AIO_CLIPBOARD__;
  var out = { api: typeof window.navigator.clipboard, failures: [] };

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  var found = null;
  walk(document.getElementById("aio-panel-materials"), function (node) {
    var value = node.attributes ? node.attributes["class"] : null;
    var classes = typeof value === "string" ? value.split(" ") : [];
    if (node.tagName === "BUTTON" && classes.indexOf("action") !== -1 && found === null) {
      found = node;
    }
  });
  if (found === null) {
    out.failures.push("the materials panel built no action button");
    process.stdout.write(JSON.stringify(out, null, 2) + "\n");
    process.exit(2);
  }
  (found.listeners.click || []).forEach(function (fn) { fn({}); });

  out.label = found.textContent;
  out.clipboard = clip.slice(0);
  out.box = document.getElementById("aio-copytext").value;
  out.live = document.getElementById("aio-live").textContent;
  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
  process.exit(0);
}());
"""


class RuntimeClipboardApiTests(ShellTemplateTestCase):
    """The first copy tier, on a browser that offers it.

    Every other runtime case here runs the `file:` reality -- no
    `navigator.clipboard`, so the selection tier is what executes. That
    leaves `writeViaClipboard` unexercised, which is how a branch nothing
    runs ends up shipping broken. This case turns the API on in the stub and
    presses one ordinary copy control.

    The assertion is not only "the API was used": it is that the read-only
    box was filled *anyway*. Build spec section 1.4 makes the box a constant
    rather than a fallback, and a copy path that skipped it whenever the
    fast tier worked would leave the reader with nothing to check against.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if NODE is None:
            raise unittest.SkipTest("node is not installed")
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            ACTION_FIXTURE_PAYLOAD,
            probe=CLIPBOARD_API_PROBE,
            extra_globals={"__AIO_CLIPBOARD_API__": True},
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def test_the_probe_ran(self) -> None:
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        self.assertEqual(self.facts.get("failures"), [])
        self.assertEqual(self.facts.get("api"), "object")

    def test_the_fast_tier_carried_the_instruction(self) -> None:
        self.assertEqual(
            self.facts.get("clipboard"), ["Re-audit material MAT-2026-000"]
        )

    def test_the_read_only_box_was_filled_anyway(self) -> None:
        self.assertEqual(self.facts.get("box"), "Re-audit material MAT-2026-000")

    def test_the_reader_was_told_the_copy_succeeded(self) -> None:
        dicts = json.loads(self.islands["aio-i18n"])["en"]
        self.assertEqual(self.facts.get("live"), dicts["action.copied"])


# --- Task 7: palette, filters, density, accessibility, print ------------

# The keys Task 7 adds. Named here rather than derived from the template so
# a key deleted from both dictionaries fails rather than passes quietly.
TASK_7_KEYS = (
    "action.palette",
    "palette.title",
    "palette.label",
    "palette.results",
    "palette.truncated",
    "palette.empty",
    "palette.close",
    "filter.bar",
    "filter.active",
    "filter.clear",
    "filter.count",
    "filter.matches",
    "filter.empty",
    "filter.never_hidden",
)


class ShellChromeSourceTests(ShellTemplateTestCase):
    """Brief step 1: the accessibility and print guarantees, read off the file.

    Greps, and brittle in the same way `GateSourceTests` is brittle. Their
    job is the same: a guarantee that was quietly deleted -- the live
    region, the focus ring, the print rules that unfold `details` -- should
    take a named test with it rather than degrade in silence on somebody
    else's machine.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.shell = extract_shell(cls.text)  # type: ignore[attr-defined]
        block = STYLE_BLOCK.search(cls.text)
        assert block is not None
        cls.style = block.group(1)  # type: ignore[attr-defined]

    # --- the palette ----------------------------------------------------

    def test_the_palette_is_a_modal_dialog(self) -> None:
        """Design spec section 4's palette, announced as what it is."""
        self.assertIn('id="aio-palette"', self.text)
        self.assertIn('role="dialog"', self.text)
        self.assertIn('aria-modal="true"', self.text)

    def test_the_palette_names_itself_and_labels_its_input(self) -> None:
        self.assertIn('aria-labelledby="aio-palette-title"', self.text)
        self.assertIn('for="aio-palette-input"', self.text)
        self.assertIn('id="aio-palette-input"', self.text)

    def test_the_palette_ships_closed(self) -> None:
        """A dialog that ships open is a dialog over the whole ledger."""
        found = re.search(r'<div class="palette" id="aio-palette"[^>]*>', self.text)
        self.assertIsNotNone(found)
        self.assertIn(" hidden", found.group(0))  # type: ignore[union-attr]

    def test_the_palette_traps_tab_and_restores_the_invoker(self) -> None:
        """The two halves of "modal" a browser will not do for you."""
        trap = slice_function(self.shell, "function trapTab(event)")
        self.assertIn("PALETTE_STOPS", trap)
        self.assertIn("preventDefault", trap)
        close = slice_function(self.shell, "function closePalette()")
        self.assertIn("PALETTE_INVOKER", close)
        self.assertIn("invoker.focus()", close)

    def test_the_palette_answers_both_spellings_of_the_shortcut(self) -> None:
        """The header promises Ctrl+K *or* Cmd+K, so both must reach it."""
        body = slice_function(self.shell, "function onGlobalKey(event)")
        self.assertIn("event.ctrlKey", body)
        self.assertIn("event.metaKey", body)
        self.assertIn("openPalette", body)

    def test_the_palette_routes_every_label_through_a_text_node(self) -> None:
        """No second escaping story. `h()` is the only way a label lands.

        `paletteResult` is the one function that puts ledger text in the
        dialog, and it hands the string to `h()`, whose only path for a
        string is `document.createTextNode` (see `appendAll`).
        """
        body = slice_function(self.shell, "function paletteResult(entry)")
        self.assertIn("entry.label", body)
        for sink in ("textContent =", "createElement", "setAttribute"):
            with self.subTest(sink=sink):
                self.assertNotIn(sink, body)

    # --- the fragment ---------------------------------------------------

    def test_parse_hash_reads_all_three_fragment_keys(self) -> None:
        body = slice_function(self.shell, "function parseHash()")
        for key in ('"panel"', '"lang"', '"f"'):
            with self.subTest(key=key):
                self.assertIn(key, body)

    def test_a_filter_change_replaces_rather_than_pushes(self) -> None:
        """Ten keystrokes must not cost ten presses of Back (section 4)."""
        body = slice_function(self.shell, "function clearFilterButton(state)")
        self.assertIn("goTo({ panel: state.panel, lang: state.lang, f: \"\" }, true)", body)
        button = slice_function(self.shell, "function filterButton(state, value, label)")
        self.assertIn("}, true)", button)

    def test_every_listing_panel_reads_the_shared_filter(self) -> None:
        """One `f` key, one reading of it, seven panels."""
        for signature in (
            "function renderInventory(section, state)",
            "function renderChanges(section, state)",
            "function renderProvenance(section, state)",
            "function renderRollback(section, state)",
            "function renderBacklog(section, state)",
            "function renderMaterials(section, state)",
        ):
            with self.subTest(renderer=signature):
                body = slice_function(self.shell, signature)
                self.assertIn("filterRows(", body)
                self.assertIn("appendFilters(", body)

    def test_decisions_filters_by_sorting_rather_than_by_hiding(self) -> None:
        """Design spec section 4: ADR records are never filtered out.

        The exception is deliberate, so it is pinned: this panel may call
        `filterRows`, but it may not drop the rows that did not match.
        """
        body = slice_function(self.shell, "function renderDecisions(section, state)")
        self.assertIn("filterRows(", body)
        self.assertNotIn("appendFilters(", body)
        self.assertIn("filter.never_hidden", body)

    def test_the_filter_match_is_case_insensitive_on_both_sides(self) -> None:
        body = slice_function(self.shell, "function matchesFilter(text, needle)")
        self.assertEqual(body.count("toLowerCase()"), 2)

    # --- density and storage --------------------------------------------

    def test_the_density_attribute_is_written_and_styled(self) -> None:
        """Both ends of the toggle: the writer and the rule it feeds."""
        body = slice_function(self.shell, "function applyDensity(value)")
        self.assertIn('setAttribute("data-density", value)', body)
        self.assertIn('body[data-density="compact"]', self.style)

    def test_the_density_control_persists_its_choice(self) -> None:
        body = slice_function(self.shell, "function densityButton(value, key)")
        self.assertIn("store(STORE_DENSITY, value)", body)
        self.assertIn("applyDensity(value)", body)

    def test_both_storage_helpers_are_wrapped(self) -> None:
        """A `file:` origin throws rather than returning null (section 4)."""
        for signature in ("function stored(key)", "function store(key, value)"):
            with self.subTest(helper=signature):
                body = slice_function(self.shell, signature)
                self.assertIn("try {", body)
                self.assertIn("catch (err)", body)

    # --- accessibility ---------------------------------------------------

    def test_the_page_carries_one_polite_live_region(self) -> None:
        """The ablation's target: delete this and the named cases go red."""
        self.assertIn('id="aio-live"', self.text)
        self.assertIn('aria-live="polite"', self.text)
        self.assertEqual(self.text.count('aria-live="'), 1)

    def test_the_live_region_is_what_announce_writes_to(self) -> None:
        body = slice_function(self.shell, "function announce(message)")
        self.assertIn('getElementById("aio-live")', body)

    def test_the_filter_and_the_palette_both_announce_a_count(self) -> None:
        for signature, key in (
            ("function announceFilter(state)", "filter.matches"),
            ("function renderPaletteResults(query)", "palette.results"),
        ):
            with self.subTest(function=signature):
                body = slice_function(self.shell, signature)
                self.assertIn("announce(", body)
                self.assertIn(key, body)

    def test_focus_visible_is_styled(self) -> None:
        """Full keyboard navigation with visible focus (design spec 12.3)."""
        self.assertIn(":focus-visible {", self.style)
        self.assertIn("outline:", self.style)

    def test_the_tab_strip_uses_a_roving_tabindex(self) -> None:
        body = slice_function(self.shell, "function renderNav(state)")
        self.assertIn('setAttribute("tabindex", selected ? "0" : "-1")', body)
        keys = slice_function(self.shell, "function onNavKey(event)")
        for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
            with self.subTest(key=key):
                self.assertIn(key, keys)

    def test_the_skip_link_targets_the_main_region(self) -> None:
        self.assertIn('href="#aio-main"', self.text)
        self.assertIn('<main id="aio-main" tabindex="-1">', self.text)

    def test_no_glyph_stands_alone(self) -> None:
        """Every decorative glyph is hidden from the accessibility tree.

        The severity is carried by a word beside it in every case (see
        `statusBlock`, `vocabChip`, `marker`); the glyph is the shape half of
        design spec section 7's acceptance item 3, and a screen reader
        reading "black up-pointing triangle" out loud is noise.
        """
        found = 0
        for line in self.shell.splitlines():
            if "GLYPHS[" not in line and "GLYPHS." not in line:
                continue
            if "var GLYPHS" in line:
                continue
            found += 1
            with self.subTest(line=line.strip()):
                self.assertIn('"aria-hidden": "true"', line)
        self.assertGreater(found, 3, "no glyph call sites were inspected")

    # --- print -----------------------------------------------------------

    def _print_block(self) -> str:
        start = self.style.index("@media print")
        return self.style[start:]

    def test_print_hides_every_control(self) -> None:
        block = self._print_block()
        for name in (
            ".skip-link", ".panels", ".filters", ".actions", ".actions-row",
            ".queue", ".copybox", ".palette", ".live",
        ):
            with self.subTest(rule=name):
                self.assertIn(name, block)

    def test_print_still_unfolds_the_provenance_chains(self) -> None:
        """Task 5's rule, kept: a collapsed chain prints as its summary."""
        block = self._print_block()
        self.assertIn("details > *:not(summary) { display: block !important; }", block)
        self.assertIn("details::details-content", block)

    def test_print_avoids_breaking_a_run_block_or_a_row_in_half(self) -> None:
        block = self._print_block()
        self.assertIn("break-inside: avoid", block)
        self.assertIn("page-break-inside: avoid", block)
        self.assertIn(".grid-table tr", block)

    def test_print_is_black_on_white(self) -> None:
        block = self._print_block()
        self.assertIn("--ink: #000000", block)
        self.assertIn("--bg: #ffffff", block)
        self.assertIn("body { background: #ffffff; color: #000000;", block)


class PaletteDictionaryTests(ShellTemplateTestCase):
    """Task 7's strings: in both dictionaries, and not left in English."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dicts = json.loads(cls.islands["aio-i18n"])  # type: ignore[attr-defined]

    def test_every_task_7_key_is_in_both_dictionaries(self) -> None:
        for key in TASK_7_KEYS:
            for lang in ("en", "pt-BR"):
                with self.subTest(key=key, lang=lang):
                    self.assertIn(key, self.dicts[lang])

    def test_no_task_7_string_was_filled_by_paste(self) -> None:
        """A pt-BR value identical to its English one is an untranslated key.

        `palette.title` is exempt for one word: "ledger" is the tool's own
        term for the file and stays English in both dictionaries, which is
        why the two values still differ everywhere else in the sentence.
        """
        for key in TASK_7_KEYS:
            with self.subTest(key=key):
                self.assertNotEqual(self.dicts["en"][key], self.dicts["pt-BR"][key])


PALETTE_PROBE = r"""
(function () {
  var bad = [];
  var facts = { failures: bad };
  var fire = globalThis.__AIO_FIRE__;
  var labels = globalThis.__AIO_LABELS__ || {};

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  function classNames(node) {
    var value = node.attributes ? node.attributes["class"] : null;
    return typeof value === "string" ? value.split(" ") : [];
  }

  function byClass(root, name) {
    var out = [];
    walk(root, function (node) {
      if (classNames(node).indexOf(name) !== -1) { out.push(node); }
    });
    return out;
  }

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  if (!globalThis.__AIO_EXPORTS__) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }
  if (typeof fire !== "function") {
    bad.push("the DOM stub exposes no event dispatch");
    report(2);
  }

  var dialog = document.getElementById("aio-palette");
  var input = document.getElementById("aio-palette-input");
  var closer = document.getElementById("aio-palette-close");
  var live = document.getElementById("aio-live");
  var results = document.getElementById("aio-palette-results");

  /* The dialog's ARIA is in the shipped markup, which this stub does not
     parse -- `ShellChromeSourceTests` reads it off the file instead. What
     is checkable here is the state the shell itself sets. */
  facts.closedAtBoot = dialog.hidden === true;

  function headerButton(text) {
    var found = null;
    walk(document.getElementById("aio-actions"), function (node) {
      if (node.tagName === "BUTTON" && node.textContent === text) { found = node; }
    });
    return found;
  }

  function press(node) {
    (node.listeners.click || []).forEach(function (fn) {
      fn({ preventDefault: function () {} });
    });
  }

  function resultLabels() {
    return byClass(results, "palette-result").map(function (node) {
      return node.textContent;
    });
  }

  function countText() {
    return document.getElementById("aio-palette-count").textContent;
  }

  var opener = headerButton(labels.palette);
  if (opener === null) {
    bad.push("the header built no palette button");
    report(2);
  }
  facts.openerShortcut = opener.attributes["aria-keyshortcuts"] || null;
  facts.openerTitle = opener.attributes.title || null;

  /* --- Ctrl+K, from a known element, so the focus restore has a target. */
  var invoker = document.createElement("div");
  invoker.focus();
  facts.ctrlHandlers = fire(document, "keydown", { key: "k", ctrlKey: true });
  facts.openedByCtrlK = dialog.hidden === false;
  facts.focusOnInput = document.activeElement === input;
  facts.countAtOpen = countText();
  facts.noteAtOpen = document.getElementById("aio-palette-note").textContent;
  facts.shownAtOpen = resultLabels().length;
  facts.liveAtOpen = live.textContent;

  /* --- typing. Each query is one keystroke's worth of state: the input's
     value is set and the `input` listener the shell registered is fired,
     which is what a browser does between one character and the next. */
  facts.queries = (globalThis.__AIO_QUERIES__ || []).map(function (query) {
    input.value = query;
    var handlers = fire(input, "input", {});
    return {
      query: query,
      handlers: handlers,
      count: countText(),
      labels: resultLabels(),
      live: live.textContent,
      note: document.getElementById("aio-palette-note").textContent
    };
  });

  /* --- the Tab trap. Named stops rather than node identities, so a failure
     says where the focus went instead of only that it went. */
  input.value = globalThis.__AIO_TAB_QUERY__;
  fire(input, "input", {});
  facts.tabStops = resultLabels().length + 2;

  function stopName() {
    var node = document.activeElement;
    if (node === input) { return "input"; }
    if (node === closer) { return "close"; }
    var at = -1;
    byClass(results, "palette-result").forEach(function (button, index) {
      if (button === node) { at = index; }
    });
    return at === -1 ? "outside" : "result" + at;
  }

  input.focus();
  facts.tabCycle = [];
  var step = 0;
  for (step = 0; step < facts.tabStops + 1; step += 1) {
    fire(dialog, "keydown", { key: "Tab", shiftKey: false });
    facts.tabCycle.push(stopName());
  }
  fire(dialog, "keydown", { key: "Tab", shiftKey: true });
  facts.afterShiftTab = stopName();

  /* --- Enter takes the first match and navigates. */
  input.value = globalThis.__AIO_ENTER_QUERY__;
  fire(input, "input", {});
  facts.enterLabels = resultLabels();
  input.focus();
  facts.hashBeforeEnter = window.location.hash;
  fire(dialog, "keydown", { key: "Enter" });
  facts.hashAfterEnter = window.location.hash;
  facts.closedAfterEnter = dialog.hidden === true;
  facts.focusRestoredAfterEnter = document.activeElement === invoker;

  /* The browser's half of a fragment navigation. */
  facts.hashchangeHandlers = fire(window, "hashchange", {});
  facts.visiblePanel = null;
  (globalThis.__AIO_PANEL_IDS__ || []).forEach(function (name) {
    var node = document.getElementById("aio-panel-" + name);
    if (node && node.hidden === false) { facts.visiblePanel = name; }
  });
  var landed = document.getElementById("aio-panel-" + facts.visiblePanel);
  facts.landedChip = byClass(landed, "filter-chip").map(function (node) {
    return node.textContent;
  });
  facts.landedChains = byClass(landed, "chain").length;

  /* --- Escape closes and gives the focus back to the button that opened
     it. Re-found after the render above, which rebuilt the header. */
  var reopener = headerButton(labels.palette);
  if (reopener === null) {
    bad.push("the header lost its palette button across a render");
    report(2);
  }
  press(reopener);
  facts.openedByButton = dialog.hidden === false;
  facts.focusOnInputAfterButton = document.activeElement === input;
  fire(dialog, "keydown", { key: "Escape" });
  facts.closedByEscape = dialog.hidden === true;
  facts.focusRestoredAfterEscape = document.activeElement === reopener;

  /* --- Cmd+K, and an uppercase key name, which is what a browser reports
     when Shift is down. */
  var metaInvoker = document.createElement("div");
  metaInvoker.focus();
  fire(document, "keydown", { key: "K", metaKey: true });
  facts.openedByMetaK = dialog.hidden === false;
  fire(document, "keydown", { key: "Escape" });
  facts.closedByGlobalEscape = dialog.hidden === true;
  facts.focusRestoredAfterGlobalEscape = document.activeElement === metaInvoker;

  /* --- an ordinary key opens nothing. */
  fire(document, "keydown", { key: "k" });
  facts.openedByBareK = dialog.hidden === false;

  /* --- density. */
  facts.densityAtBoot = document.body.attributes["data-density"] || null;
  var compact = headerButton(labels.density_compact);
  if (compact === null) {
    bad.push("the header built no compact density control");
    report(2);
  }
  press(compact);
  facts.densityAfterCompact = document.body.attributes["data-density"] || null;
  facts.densityStored = globalThis.__AIO_STORAGE__.entries["aio.density"] || null;
  var comfortable = headerButton(labels.density_comfortable);
  if (comfortable === null) {
    bad.push("the header lost its comfortable density control");
    report(2);
  }
  press(comfortable);
  facts.densityAfterComfortable = document.body.attributes["data-density"] || null;

  report(bad.length === 0 ? 0 : 1);
}());
"""


class RuntimePaletteTests(ShellTemplateTestCase):
    """The palette, driven: opened by key, typed into, chosen from, closed.

    Every fact here comes from firing an event the shell itself registered.
    The DOM stub does not bubble, so a keystroke is delivered to the element
    a browser's bubbling would have reached the handler on -- the dialog for
    the palette's own keys, `document` for the global shortcut.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if NODE is None:
            raise unittest.SkipTest("node is not installed")
        labels = json.loads(cls.islands["aio-i18n"])["en"]
        cls.labels = labels  # type: ignore[attr-defined]
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            FIXTURE_PAYLOAD,
            probe=PALETTE_PROBE,
            extra_globals={
                "__AIO_PANEL_IDS__": list(PANEL_IDS),
                "__AIO_QUERIES__": [
                    "MAT-2026-000",
                    "/hooks/0/command",
                    "drifted-skill",
                    "PIN THE MARKETPLACE TAG",
                    "no such thing",
                ],
                "__AIO_TAB_QUERY__": "hooks",
                "__AIO_ENTER_QUERY__": "/hooks/0/command",
                "__AIO_LABELS__": {
                    "palette": labels["action.palette"],
                    "density_compact": labels["action.density_compact"],
                    "density_comfortable": labels["action.density_comfortable"],
                },
            },
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def _fact(self, name: str):
        self.assertIn(
            name,
            self.facts,
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        return self.facts[name]

    def _query(self, text: str) -> dict:
        for row in self._fact("queries"):
            if row["query"] == text:
                return row
        raise AssertionError("the probe ran no query " + text)

    def test_the_probe_ran_and_the_shell_booted(self) -> None:
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )
        self.assertEqual(self.facts.get("failures"), [])

    # --- the dialog ------------------------------------------------------

    def test_the_palette_starts_closed(self) -> None:
        self.assertIs(self._fact("closedAtBoot"), True)

    def test_the_header_offers_a_button_for_a_reader_with_a_mouse(self) -> None:
        """A shortcut is not an affordance if it is the only one."""
        self.assertEqual(self._fact("openerShortcut"), "Control+K Meta+K")
        self.assertEqual(
            self._fact("openerTitle"), self.labels["action.palette_hint"]
        )

    # --- opening ---------------------------------------------------------

    def test_control_k_opens_the_palette_and_takes_the_focus(self) -> None:
        self.assertEqual(self._fact("ctrlHandlers"), 1)
        self.assertIs(self._fact("openedByCtrlK"), True)
        self.assertIs(self._fact("focusOnInput"), True)

    def test_command_k_opens_it_too(self) -> None:
        """macOS presses Cmd, and the header promises both spellings."""
        self.assertIs(self._fact("openedByMetaK"), True)

    def test_a_bare_k_opens_nothing(self) -> None:
        """A page that opened a dialog on every `k` would be unusable."""
        self.assertIs(self._fact("openedByBareK"), False)

    def test_an_empty_query_lists_the_whole_index_but_draws_a_page_of_it(self) -> None:
        shown = self._fact("shownAtOpen")
        self.assertEqual(shown, 20)
        total = int(self._fact("countAtOpen").rsplit(" ", 1)[1])
        self.assertGreater(total, shown)
        self.assertIn(self.labels["palette.truncated"], self._fact("noteAtOpen"))

    # --- searching -------------------------------------------------------

    def test_typing_filters_the_index_by_record_id(self) -> None:
        """`MAT-2026-000` is a material and a backlog entry, and no more."""
        row = self._query("MAT-2026-000")
        self.assertEqual(row["handlers"], 1)
        self.assertEqual(len(row["labels"]), 2)
        for label in row["labels"]:
            with self.subTest(label=label):
                self.assertIn("MAT-2026-000", label)
        self.assertIn("Materials", " ".join(row["labels"]))
        self.assertIn("Backlog", " ".join(row["labels"]))

    def test_a_configuration_key_is_in_the_index(self) -> None:
        """Design spec section 4: records, files, *and keys*."""
        row = self._query("/hooks/0/command")
        self.assertEqual(len(row["labels"]), 1)
        self.assertIn("/hooks/0/command", row["labels"][0])
        self.assertIn("Provenance", row["labels"][0])

    def test_baseline_item_names_and_anchors_are_in_the_index(self) -> None:
        row = self._query("drifted-skill")
        joined = " ".join(row["labels"])
        self.assertIn("Inventory", joined)
        self.assertGreaterEqual(len(row["labels"]), 2)

    def test_the_search_ignores_case(self) -> None:
        """The reader types what they remember, not what the ledger stored."""
        row = self._query("PIN THE MARKETPLACE TAG")
        self.assertGreaterEqual(len(row["labels"]), 1)
        for label in row["labels"]:
            with self.subTest(label=label):
                self.assertIn("Pin the marketplace tag", label)

    def test_a_search_that_matches_nothing_says_so(self) -> None:
        row = self._query("no such thing")
        self.assertEqual(row["labels"], [])
        self.assertIn(self.labels["palette.empty"], row["note"])

    def test_every_search_announces_its_count(self) -> None:
        """Reuses the page's one live region rather than adding a second.

        The queries chosen here all match fewer than a page of results, so
        the number announced and the number of buttons drawn are the same
        and the assertion needs no arithmetic about truncation.
        """
        for text in ("MAT-2026-000", "/hooks/0/command", "no such thing"):
            with self.subTest(query=text):
                row = self._query(text)
                self.assertEqual(
                    row["live"],
                    self.labels["palette.results"] + " " + str(len(row["labels"])),
                )
                self.assertEqual(row["live"], row["count"])

    # --- the trap --------------------------------------------------------

    def test_tab_cycles_inside_the_dialog(self) -> None:
        """Input, each result, the close button, and back to the input.

        `hooks` matches three entries in the fixture, so the ring is five
        stops long and the sixth Tab must land where the first one started.
        """
        self.assertEqual(self._fact("tabStops"), 5)
        self.assertEqual(
            self._fact("tabCycle"),
            ["result0", "result1", "result2", "close", "input", "result0"],
        )

    def test_shift_tab_cycles_the_other_way(self) -> None:
        self.assertEqual(self._fact("afterShiftTab"), "input")

    # --- choosing --------------------------------------------------------

    def test_enter_navigates_to_the_first_match(self) -> None:
        self.assertEqual(len(self._fact("enterLabels")), 1)
        self.assertEqual(self._fact("hashBeforeEnter"), "")
        self.assertEqual(
            self._fact("hashAfterEnter"),
            "#panel=provenance&f=%2Fhooks%2F0%2Fcommand",
        )

    def test_enter_closes_the_palette_and_gives_the_focus_back(self) -> None:
        self.assertIs(self._fact("closedAfterEnter"), True)
        self.assertIs(self._fact("focusRestoredAfterEnter"), True)

    def test_the_fragment_the_palette_wrote_renders_that_panel_filtered(self) -> None:
        """The whole promise: the link lands somewhere the match is visible.

        One chain out of the fixture's five carries `/hooks/0/command`, and
        the panel says in its chip which filter left it with one.
        """
        self.assertEqual(self._fact("hashchangeHandlers"), 1)
        self.assertEqual(self._fact("visiblePanel"), "provenance")
        self.assertEqual(self._fact("landedChains"), 1)
        self.assertEqual(len(self._fact("landedChip")), 1)
        self.assertIn("/hooks/0/command", self._fact("landedChip")[0])
        self.assertIn(self.labels["filter.active"], self._fact("landedChip")[0])

    # --- closing ---------------------------------------------------------

    def test_the_header_button_opens_it_and_escape_returns_the_focus(self) -> None:
        self.assertIs(self._fact("openedByButton"), True)
        self.assertIs(self._fact("focusOnInputAfterButton"), True)
        self.assertIs(self._fact("closedByEscape"), True)
        self.assertIs(self._fact("focusRestoredAfterEscape"), True)

    def test_escape_outside_the_dialog_still_closes_it(self) -> None:
        self.assertIs(self._fact("closedByGlobalEscape"), True)
        self.assertIs(self._fact("focusRestoredAfterGlobalEscape"), True)

    # --- density ---------------------------------------------------------

    def test_the_density_toggle_flips_the_attribute_and_persists(self) -> None:
        self.assertEqual(self._fact("densityAtBoot"), "comfortable")
        self.assertEqual(self._fact("densityAfterCompact"), "compact")
        self.assertEqual(self._fact("densityStored"), "compact")
        self.assertEqual(self._fact("densityAfterComfortable"), "comfortable")


FILTER_PROBE = r"""
(function () {
  var bad = [];
  var facts = { failures: bad };
  var fire = globalThis.__AIO_FIRE__;

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  function classNames(node) {
    var value = node.attributes ? node.attributes["class"] : null;
    return typeof value === "string" ? value.split(" ") : [];
  }

  function byClass(root, name) {
    var out = [];
    walk(root, function (node) {
      if (classNames(node).indexOf(name) !== -1) { out.push(node); }
    });
    return out;
  }

  function byTag(root, tag) {
    var out = [];
    walk(root, function (node) { if (node.tagName === tag) { out.push(node); } });
    return out;
  }

  function rowsIn(root) {
    var bodies = byTag(root, "TBODY");
    if (bodies.length === 0) { return 0; }
    return byTag(bodies[0], "TR").length;
  }

  function texts(root, name) {
    return byClass(root, name).map(function (node) { return node.textContent; });
  }

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  if (!globalThis.__AIO_EXPORTS__) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }

  function survey() {
    var out = {};
    (globalThis.__AIO_PANEL_IDS__ || []).forEach(function (name) {
      var node = document.getElementById("aio-panel-" + name);
      if (!node) { return; }
      out[name] = {
        hidden: node.hidden === true,
        chip: texts(node, "filter-chip"),
        count: texts(node, "filter-count"),
        clears: byClass(node, "filter-clear").length,
        bars: byClass(node, "filters").length,
        empties: texts(node, "empty"),
        notes: texts(node, "note"),
        rows: rowsIn(node),
        runs: byClass(node, "run").length,
        chains: byClass(node, "chain").length
      };
    });
    return out;
  }

  facts.hash = window.location.hash;
  facts.filtered = survey();
  facts.live = document.getElementById("aio-live").textContent;

  /* The clear control, pressed on the panel the fragment opened. */
  var open = document.getElementById("aio-panel-changes");
  var clears = byClass(open, "filter-clear");
  if (clears.length !== 1) {
    bad.push("the open panel offered " + clears.length + " clear controls, want 1");
    report(2);
  }
  (clears[0].listeners.click || []).forEach(function (fn) {
    fn({ preventDefault: function () {} });
  });
  facts.hashAfterClear = window.location.hash;
  fire(window, "hashchange", {});
  facts.cleared = survey();
  facts.liveAfterClear = document.getElementById("aio-live").textContent;

  /* Inventory's kind buttons are a shortcut into the same one filter. */
  var inventory = document.getElementById("aio-panel-inventory");
  var kinds = byClass(inventory, "filters");
  facts.inventoryBars = kinds.length;
  var pressed = null;
  byTag(kinds[0], "BUTTON").forEach(function (node) {
    if (node.textContent === "skill") { pressed = node; }
  });
  if (pressed === null) {
    bad.push("the inventory bar offered no skill button");
    report(2);
  }
  (pressed.listeners.click || []).forEach(function (fn) {
    fn({ preventDefault: function () {} });
  });
  facts.hashAfterKind = window.location.hash;
  fire(window, "hashchange", {});
  facts.byKind = survey();

  report(bad.length === 0 ? 0 : 1);
}());
"""


class RuntimeBookmarkedFilterTests(ShellTemplateTestCase):
    """A `#panel=...&f=...` link, opened cold.

    This is the property the palette exists to deliver and the reason `f`
    had to stop meaning something different in each panel: the page boots on
    somebody else's fragment, every listing panel narrows to it, and the one
    that is on screen says which filter did the narrowing.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if NODE is None:
            raise unittest.SkipTest("node is not installed")
        cls.labels = json.loads(cls.islands["aio-i18n"])["en"]  # type: ignore
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            FIXTURE_PAYLOAD,
            probe=FILTER_PROBE,
            extra_globals={
                "__AIO_PANEL_IDS__": list(PANEL_IDS),
                "__AIO_HASH__": "#panel=changes&f=hooks",
            },
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def _fact(self, name: str):
        self.assertIn(
            name,
            self.facts,
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        return self.facts[name]

    def test_the_probe_ran_and_the_shell_booted_on_the_fragment(self) -> None:
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )
        self.assertEqual(self.facts.get("failures"), [])
        self.assertEqual(self._fact("hash"), "#panel=changes&f=hooks")

    def test_the_open_panel_shows_the_chip_the_count_and_a_way_out(self) -> None:
        panel = self._fact("filtered")["changes"]
        self.assertIs(panel["hidden"], False)
        self.assertEqual(len(panel["chip"]), 1)
        self.assertIn(self.labels["filter.active"], panel["chip"][0])
        self.assertIn("hooks", panel["chip"][0])
        self.assertEqual(
            panel["count"], [self.labels["filter.count"] + " 1/4"]
        )
        self.assertEqual(panel["clears"], 1)
        self.assertEqual(panel["runs"], 1)

    def test_every_listing_panel_applied_the_same_filter(self) -> None:
        """One `f`, seven readings of it, and none of them ignored it.

        The fixture's only `hooks` anchor is `guard.js`, written by one run
        and recorded by one baseline item, so the arithmetic is checkable by
        hand: one run in Changes, one chain in Provenance, one row in
        Inventory, one backed-up run in Rollback, and nothing at all in
        Backlog or Materials.
        """
        found = self._fact("filtered")
        self.assertEqual(found["inventory"]["rows"], 1)
        self.assertEqual(found["provenance"]["chains"], 1)
        self.assertEqual(found["rollback"]["runs"], 1)
        for name in ("backlog", "materials"):
            with self.subTest(panel=name):
                self.assertEqual(found[name]["rows"], 0)
                self.assertIn(self.labels["filter.empty"], found[name]["empties"])

    def test_decisions_kept_every_record_and_said_why(self) -> None:
        """Design spec section 4's exception, visible on the page."""
        panel = self._fact("filtered")["decisions"]
        self.assertEqual(panel["rows"], 2)
        self.assertEqual(len(panel["chip"]), 1)
        self.assertIn(self.labels["filter.never_hidden"], panel["notes"])

    def test_the_open_panels_count_was_announced(self) -> None:
        """The ablation's named case: no live region, no announcement."""
        self.assertEqual(
            self._fact("live"), self.labels["filter.matches"] + " 1"
        )

    def test_clearing_the_filter_replaces_the_fragment_and_restores_the_rows(
        self,
    ) -> None:
        self.assertEqual(self._fact("hashAfterClear"), "#panel=changes")
        cleared = self._fact("cleared")["changes"]
        self.assertEqual(cleared["runs"], 4)
        self.assertEqual(cleared["chip"], [])
        self.assertEqual(cleared["bars"], 0)
        self.assertEqual(self._fact("liveAfterClear"), "")

    def test_a_kind_button_writes_the_same_one_filter(self) -> None:
        """Inventory's buttons are a shortcut into `f`, not a filter of
        their own -- which is what lets a kind chosen here survive a
        bookmark and a palette link alike.
        """
        self.assertEqual(self._fact("inventoryBars"), 1)
        self.assertEqual(self._fact("hashAfterKind"), "#panel=changes&f=skill")
        found = self._fact("byKind")
        self.assertEqual(found["inventory"]["rows"], 1)
        self.assertEqual(found["changes"]["runs"], 1)


# --- I1: the palette-index invariant -------------------------------------
#
# Reviewer-specified: every entry the palette itself indexes must land on a
# panel where that entry's own filter actually shows something. This does
# not pick one query by hand -- it walks the *real* index the shell builds
# from the fixture ledger (`api.buildPaletteIndex()`, exported for exactly
# this) and, for each entry, writes that entry's own `panel` + `f` onto the
# fragment (precisely what `paletteGo` does) and counts what rendered.
PALETTE_INVARIANT_PROBE = r"""
(function () {
  var bad = [];
  var facts = { failures: bad };
  var fire = globalThis.__AIO_FIRE__;
  var api = globalThis.__AIO_EXPORTS__;

  function walk(node, fn) {
    fn(node);
    (node.childNodes || []).forEach(function (child) { walk(child, fn); });
  }

  function classNames(node) {
    var value = node.attributes ? node.attributes["class"] : null;
    return typeof value === "string" ? value.split(" ") : [];
  }

  function byClass(root, name) {
    var out = [];
    walk(root, function (node) {
      if (classNames(node).indexOf(name) !== -1) { out.push(node); }
    });
    return out;
  }

  function byTag(root, tag) {
    var out = [];
    walk(root, function (node) { if (node.tagName === tag) { out.push(node); } });
    return out;
  }

  function rowsIn(root) {
    var bodies = byTag(root, "TBODY");
    if (bodies.length === 0) { return 0; }
    return byTag(bodies[0], "TR").length;
  }

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  if (!api) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }
  if (typeof api.buildPaletteIndex !== "function") {
    bad.push("buildPaletteIndex was not exported for this probe to call");
    report(2);
  }

  var index = api.buildPaletteIndex();
  facts.indexSize = index.length;
  facts.results = index.map(function (entry) {
    window.location.hash =
      "#panel=" + encodeURIComponent(entry.panel) + "&f=" + encodeURIComponent(entry.f);
    fire(window, "hashchange", {});
    var node = document.getElementById("aio-panel-" + entry.panel);
    var rendered = node
      ? rowsIn(node) + byClass(node, "chain").length + byClass(node, "run").length
      : 0;
    if (rendered === 0) {
      bad.push(
        "palette entry " + JSON.stringify(entry.label) + " (panel=" + entry.panel +
        ", f=" + JSON.stringify(entry.f) + ") rendered nothing"
      );
    }
    return { label: entry.label, panel: entry.panel, f: entry.f, rendered: rendered };
  });

  report(bad.length === 0 ? 0 : 1);
}());
"""


class RuntimePaletteInvariantTests(ShellTemplateTestCase):
    """I1: no palette entry may dead-end.

    Every entry `buildPaletteIndex()` produces from the fixture ledger is
    replayed through the real router (a hash write and a `hashchange`,
    exactly what `paletteGo` does) and the target panel is inspected for at
    least one rendered row, chain, or run block. Before the fix, every
    PROPOSAL entry -- `PROP-2026-000` and `PROP-2026-001`, by id and by
    title -- named the Provenance panel, but `chainText` read only the
    anchor, the key, and each run's own id/title, never the run's
    `proposal` field or that proposal's title. A search built from exactly
    the label the palette itself offered therefore found zero chains.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if NODE is None:
            raise unittest.SkipTest("node is not installed")
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            FIXTURE_PAYLOAD,
            probe=PALETTE_INVARIANT_PROBE,
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def test_the_probe_ran_and_every_index_entry_rendered_somewhere(self) -> None:
        self.assertGreater(
            self.facts.get("indexSize", 0),
            0,
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        self.assertEqual(
            self.facts.get("failures"),
            [],
            "\n".join((self.proc.stdout.strip(), self.proc.stderr.strip())),
        )
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )


# --- M4: exact-match-first on Enter ---------------------------------------
#
# A dedicated, minimal ledger rather than the shared fixture: the point is
# the tie-break rule in isolation. Two MATERIAL records share the token
# "hooks" -- the first, in payload order, titled "hooks documentation" (a
# substring match only), the second titled exactly "hooks". Enter must take
# the second despite it sorting later in `PALETTE_MATCHES`.
EXACT_MATCH_FIXTURE_LEDGER = {
    "schema_version": "1.0",
    "ledger_id": "exact-match",
    "scope": "project",
    "language": "en",
    "client": "claude-code",
    "adapter_version": 2,
    "created": "2026-07-01",
    "updated": "2026-07-31",
    "id_authority": True,
    "sequences": {"MAT": 2, "PROP": 0, "RUN": 0, "ADR": 0, "BASE": 0},
    "known_projects": [],
    "records": [
        {
            "id": "MAT-2026-000",
            "type": "MATERIAL",
            "title": "hooks documentation",
            "status": "ANALYZED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-02",
            "updated": "2026-07-02",
            "file": "records/MAT-2026-000.md",
            "links": {},
            "evidence": [],
        },
        {
            "id": "MAT-2026-001",
            "type": "MATERIAL",
            "title": "hooks",
            "status": "ANALYZED",
            "classification": "ADOPT LOCALLY",
            "scope": "project",
            "created": "2026-07-03",
            "updated": "2026-07-03",
            "file": "records/MAT-2026-001.md",
            "links": {},
            "evidence": [],
        },
    ],
    "baselines": [],
    "backlog": [],
}

EXACT_MATCH_FIXTURE_PAYLOAD = {
    "payload_schema": 1,
    "mode": "static",
    "generated_at": None,
    "tool_version": None,
    "lang": None,
    "ledger": EXACT_MATCH_FIXTURE_LEDGER,
    "computed": None,
}

EXACT_MATCH_PROBE = r"""
(function () {
  var bad = [];
  var facts = { failures: bad };
  var fire = globalThis.__AIO_FIRE__;

  function report(code) {
    process.stdout.write(JSON.stringify(facts, null, 2) + "\n");
    process.exit(code);
  }

  if (!globalThis.__AIO_EXPORTS__) {
    bad.push("the shell never reached its export: boot took a fatal path");
    report(2);
  }

  var dialog = document.getElementById("aio-palette");
  var input = document.getElementById("aio-palette-input");

  var invoker = document.createElement("div");
  invoker.focus();
  fire(document, "keydown", { key: "k", ctrlKey: true });

  input.value = "hooks";
  fire(input, "input", {});
  facts.matchLabels = (function () {
    var out = [];
    (document.getElementById("aio-palette-results").childNodes || []).forEach(
      function (li) {
        (li.childNodes || []).forEach(function (button) {
          out.push(button.textContent);
        });
      }
    );
    return out;
  }());
  facts.hashBeforeEnter = window.location.hash;
  fire(dialog, "keydown", { key: "Enter" });
  facts.hashAfterEnter = window.location.hash;

  report(bad.length === 0 ? 0 : 1);
}());
"""


class RuntimePaletteExactMatchTests(ShellTemplateTestCase):
    """M4: Enter prefers an exact, case-insensitive label match on Enter.

    Before the fix, Enter always took `PALETTE_MATCHES[0]` -- the first
    substring match in payload order -- so a reader who typed the *whole*
    record title, expecting the record that title names, could still land
    on an earlier, merely-containing match instead.
    """

    proc: subprocess.CompletedProcess[str]
    facts: dict

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if NODE is None:
            raise unittest.SkipTest("node is not installed")
        cls.proc = boot_shell(
            cls.text,
            cls.islands,
            EXACT_MATCH_FIXTURE_PAYLOAD,
            probe=EXACT_MATCH_PROBE,
        )
        try:
            cls.facts = json.loads(cls.proc.stdout)
        except ValueError:
            cls.facts = {}

    def test_the_probe_ran(self) -> None:
        self.assertEqual(
            self.proc.returncode,
            0,
            "\n".join(
                ("node reported:", self.proc.stdout.strip(), self.proc.stderr.strip())
            ),
        )
        self.assertEqual(self.facts.get("failures"), [])

    def test_both_the_substring_and_the_exact_match_are_offered(self) -> None:
        labels = self.facts.get("matchLabels") or []
        self.assertEqual(len(labels), 2)
        self.assertIn("hooks documentation", labels[0])
        self.assertIn("hooks", labels[1])
        self.assertNotIn("documentation", labels[1])

    def test_enter_prefers_the_exact_match_over_an_earlier_substring_match(
        self,
    ) -> None:
        self.assertEqual(self.facts.get("hashBeforeEnter"), "")
        self.assertEqual(self.facts.get("hashAfterEnter"), "#panel=materials&f=hooks")


# Task 8: the docs-shell lockstep test. `references/DASHBOARD.md` documents the shell this
# module tests -- the nine panels and the five commands -- and nothing pins the two together
# except this test. A panel added to `PANELS` (line 1536 of the template) or a command added
# to dashboard.py without a matching mention in the reference is invisible to every other suite
# in this file, because they all read the shell, never the doc.
DASHBOARD_REFERENCE = (
    REPO_ROOT
    / "skills"
    / "agent-ingest-audit-optimize"
    / "references"
    / "DASHBOARD.md"
)

# The five subcommands `dashboard.py` implements, per `references/LEDGER.md` and this
# module's own SCRIPT invocations above.
DASHBOARD_COMMANDS = ("verify", "scan", "drift", "rollback-preview", "build")


class DashboardReferenceLockstepTests(unittest.TestCase):
    """`references/DASHBOARD.md` must exist and name every panel id and command."""

    def test_reference_file_exists(self) -> None:
        self.assertTrue(
            DASHBOARD_REFERENCE.is_file(),
            f"missing {DASHBOARD_REFERENCE} -- the brief's Step 1 deliverable",
        )

    def test_reference_names_every_panel_id(self) -> None:
        text = DASHBOARD_REFERENCE.read_text(encoding="utf-8")
        for panel_id in PANEL_IDS:
            self.assertIn(
                panel_id,
                text,
                f"references/DASHBOARD.md never mentions panel id {panel_id!r}",
            )

    def test_reference_names_every_command(self) -> None:
        # A bare substring check has no teeth for "build": incidental prose
        # ("rebuild", "building") keeps it alive after every real command
        # mention is renamed. Require the invocation form instead.
        text = DASHBOARD_REFERENCE.read_text(encoding="utf-8")
        for command in DASHBOARD_COMMANDS:
            self.assertIn(
                f"dashboard.py {command}",
                text,
                f"references/DASHBOARD.md never shows `dashboard.py {command}`",
            )


if __name__ == "__main__":
    unittest.main()
