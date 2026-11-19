# Withholding parsed text, and shipping the whole plugin

Status: approved 2026-11-18 (review decisions in `docs/reviews/2026-11-18-revisao-do-plugin.md`)
Target version: 0.6.1
Phase: third increment of the 2026-11 review

Two defects in what the archives ship. They share a release because the second reviewer grouped
them as the first thing to close, ahead of everything that reshapes the plugin.

## 1. Parsed text reached the baseline

### 1.1 The defect

`scan` parses JSON and TOML and records each item's value. `redact` replaced the value under any
key matching the adapter's `sensitive_key_patterns`. Everything else was copied as written.

A pattern can only name a key. A second review reproduced two credentials sitting under keys no
pattern could reasonably name, using synthetic data and the shipped `claude-code` patterns:

- `hooks.PreToolUse[0].hooks[0].command`, a command line carrying a password argument;
- `permissions.allow[0]`, a permission rule carrying an authorization header.

Both came out of `redact` intact. `update` appends `scan`'s output to `baselines[]`, so both reach
`ledger.json` on disk.

How much real text this had already copied was measured on this project's own dogfood ledger, by
counting and without printing: each of its two baselines holds 42 plain strings, 18 of them under
`hook` items.

### 1.2 What the value was for

Nothing in the bundle reads `attributes.value` back. `drift` compares file digests and re-resolves
recorded pointers; `lock` reads item digests; no dashboard panel renders the attribute. The text
was kept for a reader who might open the baseline, and that reader is the exposure.

### 1.3 The change

`withhold_text(value)` replaces every string leaf with the marker `redact` already writes,
`{"redacted": true, "digest": "sha256:…"}`. `scan` applies it to the parsed document immediately
after `redact`.

What a baseline keeps of a parsed document:

- its shape: key names, nesting, array lengths;
- numbers, booleans and nulls;
- one digest per string, so a single leaf changing between two baselines is visible without
  either baseline having held it.

`redact` is unchanged and still runs first. It does what a digest per string cannot: a matching
key withholds its whole subtree, key names included, which is why `env` hides the variable names
of an MCP `env` block. Markers written by `redact` pass through `withhold_text` untouched; walking
into one would replace its digest with a digest of a digest.

`drift` is unchanged. Its one parse re-resolves a pointer against a redacted document, and a
string leaf resolves the same way whether or not it has been replaced by a marker.

### 1.4 Limits, stated rather than closed

- A key name is kept. A secret used as a key name outside a withheld subtree is copied.
- A number is kept. A numeric secret is copied.
- The digest is unsalted. It reveals nothing about a long random token; a short or common value
  can be confirmed by hashing a guess. Salting was not attempted: a salt stored beside the digest
  protects nothing, and one stored elsewhere breaks comparison across baselines.
- A baseline captured by 0.6.0 or earlier keeps the text it copied. Nothing rewrites it.
- Item names and recorded locations still carry account, project and server names and local
  paths. That was already documented and is unchanged.

### 1.5 Considered and not done

An allowlist of keys whose text is safe to keep (`type`, `matcher`, `model`). It would restore
some readability and add a new adapter field, a schema change, and a list to keep right. Since
nothing reads the values, there is no reader to serve yet.

Detecting secrets by the look of the value. Heuristic, and unnecessary once no text is kept.

## 2. The plugin archive left out `commands/`

### 2.1 The defect

0.6.0 added `commands/dashboard.md`. `package_plugin.py` builds the plugin archive from an explicit
list, and `commands/` was never added to it. An install from the repository had `/dashboard`; an
install from the release zip did not.

No test could see it: every archive test compared the zip with `expected_entries()`, the
packager's own list.

### 2.2 The change

The packager ships every file under `commands/`, `agents/` and `hooks/` when the directory exists,
and the symlink refusal covers them.

Two tests start from the repository instead of from the packager:

- every file under a plugin component directory is in the extracted archive, byte for byte;
- every tracked top-level entry is either shipped or named in `NOT_SHIPPED`, so a new entry fails
  until someone decides which.

### 2.3 Not fixed here

`commands/dashboard.md` invokes the bundle by a path relative to the repository root, which is
expected to fail when the plugin is installed and run from another project. Shipping the file does
not change that. It belongs to the format increment, where it can be exercised outside the
repository.

## 3. Guards and their ablations

| Removed | Tests that failed |
|---|---|
| `withhold_text` at its call site in `_parse_items` | 13, among them `test_a_credential_in_a_hook_command_is_not_copied`, `test_a_credential_in_a_permission_rule_is_not_copied`, `test_neither_credential_reaches_the_ledger_the_page_or_a_stream` |
| the marker guard in `withhold_text` | `test_an_existing_marker_is_left_exactly_as_it_is`, `test_a_marker_replaces_what_was_removed` |
| the array branch in `withhold_text` | 8, among them `test_strings_inside_arrays_become_markers` |
| `COMPONENT_ROOTS` in the packager (the state before the fix) | `test_plugin_archive_ships_every_plugin_component`, `test_every_top_level_entry_is_shipped_or_deliberately_left_out` |

## 4. Tests that changed meaning

Five tests asserted that a parsed value lands in an item as written, and one asserted that an
empty pattern list means no redaction. They now assert the shape with every string replaced, with
the expectation computed in the test file rather than by calling the implementation. Five
documentation tests pinned sentences describing the old rule, including "is copied into the
baseline verbatim"; they now pin the new rule and its limits, and assert the old sentences are
gone.
