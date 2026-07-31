"use strict";

/* A DOM small enough to read in one sitting, and just large enough to boot
   the shell in `skills/agent-ingest-audit-optimize/assets/templates/
   dashboard.html` under plain `node`.

   It exists so the shell's runtime gates -- `safeHref`, `attrAllowed`,
   `safeTag` -- can be *executed* by `dashboard/tests/test_shell.py` rather
   than only grepped. The static suite can prove a guard's source is present;
   only running it proves the guard refuses anything.

   Deliberately not a browser: nodes remember a tag name, a flat attribute
   map, their children, and nothing else. No layout, no CSS, no event
   dispatch -- listeners are recorded and never fired, because the gates
   under test run during construction, not during interaction.

   The harness concatenates this file, a preamble of globals, the shell
   source, and a probe into one temporary script, so `document` and `window`
   below are in scope for the shell exactly as they would be in a page.
   Islands are seeded through `globalThis.__AIO_ISLANDS__` (an id -> text
   map); every other id is created empty on first request.

   Node builtins only. No dependency to install, nothing to keep current. */

function El(tag) {
  this.tagName = String(tag).toUpperCase();
  this.childNodes = [];
  this.attributes = Object.create(null);
  this.listeners = Object.create(null);
  this.text = "";
  this.hidden = false;
  this.id = "";
  this.lang = "";
}

El.prototype.setAttribute = function (name, value) {
  this.attributes[name] = String(value);
  if (name === "id") { this.id = String(value); }
};

El.prototype.getAttribute = function (name) {
  return name in this.attributes ? this.attributes[name] : null;
};

El.prototype.removeAttribute = function (name) { delete this.attributes[name]; };

El.prototype.appendChild = function (child) { this.childNodes.push(child); return child; };

El.prototype.removeChild = function (child) {
  var at = this.childNodes.indexOf(child);
  if (at !== -1) { this.childNodes.splice(at, 1); }
  return child;
};

El.prototype.addEventListener = function (type, fn) {
  if (!this.listeners[type]) { this.listeners[type] = []; }
  this.listeners[type].push(fn);
};

El.prototype.focus = function () { this.focused = true; };

Object.defineProperty(El.prototype, "firstChild", {
  get: function () { return this.childNodes.length === 0 ? null : this.childNodes[0]; }
});

Object.defineProperty(El.prototype, "textContent", {
  get: function () {
    if (this.childNodes.length === 0) { return this.text; }
    return this.childNodes.map(function (child) { return child.textContent; }).join("");
  },
  set: function (value) { this.childNodes = []; this.text = String(value); }
});

var registry = Object.create(null);

/* A tally of every argument `createElement` actually received. `h()` always
   calls `createElement(safeTag(tag))`, so by the time a name lands here it
   has already been through `safeTag`'s coercion -- this counter cannot show
   what tag ledger content *asked* for, only what tag name ultimately reached
   `createElement`. Its value is narrower than that: it catches a future
   direct `createElement` call that bypasses `h()` (and therefore `safeTag`)
   entirely, which a look at the finished tree would not, since the finished
   tree only ever shows the coerced result either way. The actual inertness
   guarantee -- that ledger content never becomes an element at all -- is the
   text-node assertion in `dashboard/tests/test_shell.py`
   (`RuntimePanelTests`), not this counter. */
var created = Object.create(null);

var document = {
  title: "",
  documentElement: new El("html"),
  body: new El("body"),
  createElement: function (tag) {
    var name = String(tag);
    created[name] = (created[name] || 0) + 1;
    return new El(tag);
  },
  createTextNode: function (value) {
    var node = new El("#text");
    node.text = String(value);
    return node;
  },
  getElementById: function (id) {
    if (!(id in registry)) {
      var node = new El("div");
      node.setAttribute("id", id);
      var islands = globalThis.__AIO_ISLANDS__ || {};
      if (id in islands) { node.text = islands[id]; }
      registry[id] = node;
    }
    return registry[id];
  },
  addEventListener: function () {}
};

/* `file:` origins throw on storage in some browsers; the shell wraps every
   read and write for that reason. Here storage simply works, so the wrap is
   exercised on its succeeding branch. */
var storage = {
  entries: Object.create(null),
  getItem: function (key) { return key in this.entries ? this.entries[key] : null; },
  setItem: function (key, value) { this.entries[key] = String(value); }
};

var window = {
  document: document,
  location: {
    hash: String(globalThis.__AIO_HASH__ || ""),
    replace: function (value) { this.hash = String(value); }
  },
  navigator: { language: String(globalThis.__AIO_LANG__ || "en") },
  localStorage: storage,
  matchMedia: function (query) {
    return {
      media: String(query),
      matches: false,
      addEventListener: function () {},
      addListener: function () {}
    };
  },
  addEventListener: function () {}
};

globalThis.document = document;
globalThis.window = window;
globalThis.__AIO_REGISTRY__ = registry;
globalThis.__AIO_CREATED__ = created;
