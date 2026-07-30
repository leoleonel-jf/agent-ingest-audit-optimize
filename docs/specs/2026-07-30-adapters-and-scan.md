# Adapters and `scan` (0.2.5)

Status: approved 2026-07-30 under standing autonomy
Target version: 0.2.5
Phase: the second of three increments toward the design spec's 0.3.0

## 1. Where this sits

`docs/specs/2026-07-30-anchors-and-path-safety.md` §1 split the design spec's 0.3.0 into three
increments and named the second one "0.2.4". That number was spent instead on a patch release: an
Ubuntu run of the suite found `resolve_anchored` leaking a raw `RuntimeError` out of the
path-safety layer, and a defect in a shipped guard outranks the next feature. This increment is
therefore **0.2.5**. The revised table:

| Increment | Delivers | State |
|---|---|---|
| 0.2.3 | Anchor resolution, path safety, the `baselines[]` field schema | released |
| 0.2.4 | POSIX path-safety fix, portable tests | released |
| **0.2.5** — this spec | The module split, `adapter.schema.json`, three adapters, `scan`, the unknown-client flow | this one |
| 0.3.0 | `drift`, `rollback-preview` — completing design spec §16 | next |

The version `0.3.0` is still reached when §16's acceptance criteria are met, not by increment
count.

## 2. What comes due now

0.2.3 built the substrate — `anchor_path`, `resolve_anchored`, `check_glob`, the `baselines[]`
schema — and deliberately shipped no caller for it. §7 of that spec said the first real anchor
roots arrive with adapters, "which is the right time to review that boundary again with a concrete
client in hand". This is that release. Everything the substrate promised is now exercised by a
command that runs against a real machine.

`docs/research/2026-07-30-client-configuration-paths.md` is the verified input for the adapter
data. It expires 2026-10-28; the adapters inherit that expiry, and §3.3 records it in the shipped
files rather than only in the research document.

## 3. Design

### 3.1 The module split

`dashboard.py` is 1,262 lines. `docs/plans/2026-07-29-ledger-0.2.0.md:47` deferred splitting it
until `scan` and its neighbours arrive, on the grounds that module boundaries chosen before the new
code exists are guesses. The new code exists now, so the split happens first, as its own task,
before a line of `scan` is written.

The bundle keeps `assets/scripts/dashboard.py` as its entry point. That path appears in `SKILL.md`,
`references/LEDGER.md`, `README.md`, `PRIVACY.md`, `packaging/`, and the test suite; moving it buys
nothing. What changes is what is inside it:

| Module | Holds |
|---|---|
| `dashboard.py` | argument parsing, `main`, and the public names re-exported for compatibility |
| `ledgerlib/errors.py` | `LedgerError`, `PathSafetyError`, `PATH_SAFETY_REASONS` |
| `ledgerlib/constants.py` | the schema constants, regexes, and closed enums |
| `ledgerlib/paths.py` | `load_json`, `file_digest`, `anchor_path`, `resolve_anchored`, `check_glob` and their helpers |
| `ledgerlib/validate.py` | every `validate_*` function and `validate_collection` |
| `ledgerlib/verify.py` | `verify` |
| `ledgerlib/adapters.py` | adapter loading, validation, and anchor-root resolution — new |
| `ledgerlib/scan.py` | the scanner — new |

**The split changes no behaviour.** Its acceptance is that the existing 3,415-line test file passes
unchanged, with no edit other than none at all: `dashboard.py` re-exports every name the tests
already reach for. A test file edited in the same commit as the code it guards cannot prove the
code still works.

The test suite loads `dashboard.py` by file path through `importlib.util`, which does not put the
script's directory on `sys.path`. `dashboard.py` therefore inserts its own directory at the front
of `sys.path` before importing `ledgerlib`, guarded against duplicate insertion. This is the price
of a bundle that must run as a loose script under an interpreter no installer configured, and it is
paid in one place.

`ledgerlib` is a package directory inside the bundle. `packaging/` must ship it; a packaging test
asserts the bundle contains it, because a plugin zip that carries `dashboard.py` without its
modules installs cleanly and fails on first use.

### 3.2 `adapter.schema.json`

Adapters are data. The schema lives beside `ledger.schema.json` in `assets/schemas/` and is
validated at load time by `ledgerlib/adapters.py`, not only by an external validator — the bundle
has no JSON Schema library and never grows one.

```json
{
  "adapter_version": 1,
  "client": "claude-code",
  "expires_on": "2026-10-28",
  "anchors": {
    "$USER_CONFIG": ["$env:CLAUDE_CONFIG_DIR", "~/.claude"],
    "$PROJECT": ["."]
  },
  "probes": [
    { "kind": "instruction-file", "scope": "user", "glob": "$USER_CONFIG/CLAUDE.md" },
    { "kind": "skill", "scope": "user", "glob": "$USER_CONFIG/skills/*/SKILL.md" },
    { "kind": "mcp-server", "scope": "user", "path": "$USER_CONFIG/settings.json",
      "parse": "json", "pointer": "/mcpServers" }
  ],
  "sensitive_key_patterns": ["*token*", "*key*", "*secret*", "*password*", "*credential*", "env"]
}
```

Field rules:

| Field | Rule |
|---|---|
| `adapter_version` | integer, at least 1; required |
| `client` | non-empty string, lowercase, `[a-z0-9-]+`; required |
| `expires_on` | `YYYY-MM-DD`; required — see §3.3 |
| `anchors` | object; each key an anchor name (`$NAME`), each value a non-empty array of candidate roots |
| `probes` | array; may be empty (the generic adapter's whole point) |
| `sensitive_key_patterns` | array of non-empty strings; required, may be empty |

A probe requires `kind` and exactly one of `glob` or `path`. `kind` is one of the ten in design
spec §7.5 — the same closed enum `baselines[].items[].kind` already validates against, imported
from `constants.py` rather than restated, so the two cannot drift apart. Optional: `scope` (a
non-empty string, see §3.4), `parse` (`json` or `toml`, only with `path`), `pointer` (an RFC 6901
JSON pointer, only with `parse`).

Every `glob` and `path` passes `check_glob` at **load** time, not at scan time. An adapter carrying
a `..` segment or an absolute form is refused before a single probe runs, so a hostile adapter
cannot get one directory walk out of the tool.

**Anchor candidates.** A candidate is `$env:NAME` — the value of that environment variable, skipped
when unset or empty — or a filesystem path, with a leading `~` expanded. The first candidate that
resolves to an existing directory wins; if none does, the anchor is *unresolved*, and every probe
under it is recorded `not_present` rather than raising. This is the mechanism the research
demanded: `CLAUDE_CONFIG_DIR` and `CODEX_HOME` relocate everything, and an adapter that hardcodes
the default root reports a clean baseline for a tree it never looked at.

### 3.3 The three adapters and their expiry

`assets/adapters/claude-code.json`, `codex.json`, `generic.json`, built from the research document
and nothing else. `generic.json` has an empty `probes` array, per design spec §9.

Vendor paths are time-sensitive by the rule `references/LEDGER.md` already states, so each adapter
carries `expires_on`. `scan` emits a finding — not an error — when it runs an adapter past its
expiry, and the baseline entry records it. An adapter whose paths have quietly gone stale produces
a baseline that looks clean, and a silently clean baseline is the worst output this tool can
produce.

Two research findings are honoured structurally rather than in prose:

- The Claude Code adapter does **not** probe `AGENTS.md`. Claude Code does not read it, and a probe
  would record an inert file as live configuration.
- The Codex adapter probes both the documented `~/.agents/skills` root and the undocumented
  skills directory under the configuration home, because the research found the latter on disk
  while it is absent from the documented search list.

### 3.4 What `scan` does

```text
dashboard.py scan --id BASE-2026-000 [--client NAME] [--project PATH] [--adapter FILE]
```

Read-only discovery. It opens files, hashes them, parses two formats, and writes nothing anywhere
except its own stdout. It emits one `baselines[]` entry as JSON, valid against
`ledger.schema.json`, for the agent to place in a ledger under the allocation rules
`references/LEDGER.md` already owns.

**`--id` is required.** Identifier allocation is a ledger concern with rules about sequences,
provisional suffixes, and cross-scope collision; `scan` does not get a second, private
implementation of it. A `--id` that is not a well-formed `BASE` identifier exits `2`.

**Client selection.** `--client` names one. Without it, `scan` detects: an adapter matches when at
least one of its `$USER_CONFIG` candidates resolves. Exactly one match selects it; more than one,
or none, selects `generic.json` and says which and why. Detection never guesses between two
plausible clients silently.

**Probing.** For each probe: `glob` expands under its resolved anchor and yields one item per
match; `path` yields one item. A probe that matches nothing yields exactly one item with
`state: "not_present"` and a `null` digest — never an error, never silence. Present items carry a
`sha256:` digest of the file's bytes; a directory or an unreadable file is `present` with a `null`
digest and the reason in `attributes`.

Every path a probe produces is re-checked with `resolve_anchored` before it is opened. The glob
expansion is not trusted to have stayed inside the anchor: a symlinked directory inside
`$USER_CONFIG/skills/` can carry a match out of the tree, and `check_glob` at load time says
nothing about what the filesystem contains at scan time. A refusal is recorded as an item with
`state: "not_present"` and the `PathSafetyError` reason in `attributes` — the scan continues.
Refusing to look at one path is not a reason to abandon the baseline.

**Parsing.** `parse: "json"` reads the file and, with `pointer`, selects a sub-document; the result
becomes one item per key at that location — this is what turns one `settings.json` into one
`mcp-server` item per server. `parse: "toml"` does the same through `tomllib`, which exists from
Python 3.11. Below that the file is still recorded, `present`, with its digest and
`attributes.parse_unavailable: "toml"` — the honest degradation the design spec §14 asks for, not a
crash and not a pretence that the file held nothing. A file that fails to parse is `present` with
`attributes.parse_error` naming the failure, never the parser's message verbatim.

**`scope`** is copied from the probe onto the item's attributes. The research found that precedence
in both clients is per-subsystem — settings and skills resolve in different orders inside one
client — so any single "which layer wins" answer computed at scan time would be wrong for half the
kinds. `scan` records the layer each item came from and computes no winner. Resolving precedence
belongs with `drift`, which has both a baseline and a reason to care.

`origin` is `pre-existing` for every item. Design spec §7.5 determines it by matching against run
targets; that match needs a ledger, which `scan` does not read.

### 3.5 Sensitive values

Design spec §9: a value under a `sensitive_key_patterns` match is never copied — the key name and a
digest of the value are stored — and it applies recursively into nested objects.

Implemented as: a key matches when it matches any pattern case-insensitively (`fnmatch`, so `*key*`
and the literal `env` both work). On a match, the value is replaced by
`{"redacted": true, "digest": "sha256:…"}`, computed over the value's canonical JSON encoding, for
values of every type. Recursion stops at the match — nothing under a redacted subtree is walked,
because walking it would put the values in memory and one bug away from output.

The digest exists so `drift` can tell "the token changed" from "the token is gone" without ever
having held it.

This rule protects the highest-risk files in the research: Codex's `auth.json`, MCP `env` blocks
and headers in both clients, and the three Claude Code keys that name shell commands which mint
secrets. `scan` executes nothing, ever; those three keys are recorded as names like any other.

### 3.6 The unknown-client flow

Design spec §9: an unknown client selects `generic.json`, which probes nothing, and the Skill asks
the user for paths and writes `$USER_CONFIG/agent-ingest-audit-optimize/adapters/local.json`. A
user adapter takes precedence over a bundled one with the same `client`.

`scan` looks for user adapters in `<user-config>/agent-ingest-audit-optimize/adapters/*.json`,
where `<user-config>` comes from `--user-config` or, unset, is skipped entirely. It is skipped
rather than defaulted because the tool cannot know which client's configuration root is meant on a
machine that may have several, and reading a directory the user did not name is exactly what §13.6
exists to prevent.

A user adapter is validated against the same schema as a bundled one and refused the same way. The
`SKILL.md` and `references/` change is the workflow half of this: how the agent asks, what it
writes, and that it never writes an adapter the user did not confirm.

## 4. Scope

In scope: the module split; `adapter.schema.json`; the three adapters; `scan`; sensitive-value
redaction; the unknown-client flow including its `SKILL.md` and `references/LEDGER.md` changes;
tests for all of it; the 0.2.5 release.

Out of scope: `drift` and `rollback-preview` (0.3.0); `build` and the dashboard (0.4.0); writing
into `ledger.json` from any command; `origin` matching against run targets; computing precedence
winners; executing anything a configuration file names; adapters for clients other than the three.

## 5. Compatibility

Additive. No existing command changes behaviour, no ledger written under 0.2.4 becomes invalid, and
`verify` is untouched except for where its code lives. The new command is opt-in by being new.

The one externally visible structural change is that the bundle now ships a directory of Python
modules beside `dashboard.py`. An installation that copied only `dashboard.py` would break — which
is why §3.1 requires the packaging test.

## 6. Acceptance

| Criterion | Evidence |
|---|---|
| The split changes nothing | The full suite passes with `dashboard/tests/test_dashboard.py` unmodified |
| The bundle ships its modules | A packaging test finds `ledgerlib/` in both zips |
| An invalid adapter is refused at load | One test per field rule |
| An adapter with `..` or an absolute glob is refused at load | Before any probe runs |
| `$env:` candidates win over defaults | `CLAUDE_CONFIG_DIR` pointed at a temporary tree scans that tree |
| An unresolved anchor is not an error | Every probe under it is `not_present` |
| A probe matching nothing is recorded | Exactly one `not_present` item, never an error |
| A glob escaping its anchor at scan time is refused | A symlink inside the anchor pointing out; the scan still completes |
| A sensitive value is never stored | Its key is present, its value is a digest, and the plaintext appears nowhere in the output |
| Redaction recurses | A secret nested three objects deep is redacted |
| `toml` degrades honestly | With `tomllib` absent the file is `present`, digested, and flagged |
| An expired adapter is a finding | Not an error, and the scan still produces a baseline |
| Unknown client selects `generic` | And says why |
| A user adapter beats a bundled one | Same `client`, user file wins |
| `scan` output validates | The emitted entry, placed in a ledger, exits `verify` at `0` |
| `scan` writes nothing | A read-only tree scans successfully |
| Nothing regressed | Every suite green; this repository's own ledger still exits `0` |

## 7. Risk

**`scan` is the first command that reads a real user's configuration.** Everything before it read
files named on the command line. The mitigations are structural: `check_glob` at load, a second
`resolve_anchored` check at open time, no anchor root the caller did not supply, no execution of
anything, and redaction before any value reaches memory it can escape from. The residual risk is a
`sensitive_key_patterns` list that misses a key name a vendor invents later, which is why the
patterns live in adapter data with an expiry rather than in code.

**The module split is a large diff that must be provably inert.** The defence is that the test file
does not change; if a name moved, the suite says so before the release does.

**An adapter that is right today is wrong in three months.** `expires_on` makes that visible in the
output instead of leaving it to be discovered by a baseline that quietly stopped covering anything.
