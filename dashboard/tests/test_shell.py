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

from ledgerlib.build import TEMPLATE_PATH  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
