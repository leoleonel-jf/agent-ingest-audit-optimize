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

The template is read once for the whole module (`_CACHE`) and shared by
every case; nothing here mutates it.
"""

from __future__ import annotations

import importlib.util
import json
import re
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
HREF = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
SRC_ATTRIBUTE = re.compile(r"(?<![\w-])src\s*=")

SIZE_BUDGET = 400 * 1024

_CACHE: dict[str, object] = {}


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

    def test_no_src_attribute_appears(self) -> None:
        """Nothing for a browser to fetch -- no image, no font, no script."""
        self.assertIsNone(SRC_ATTRIBUTE.search(self.text))

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


if __name__ == "__main__":
    unittest.main()
