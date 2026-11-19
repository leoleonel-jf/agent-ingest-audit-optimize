# Ledger: baselines, `scan` and adapters

What a baseline is, how `scan` captures one, how an adapter is written, and what a baseline
does not cover. Part of the ledger reference; [LEDGER.md](LEDGER.md) holds the index.

## Baselines

Each entry in `baselines[]` requires `id`, `captured_on`, `client`, `adapter_version`, `items`.

| Field | Rule |
|---|---|
| `id` | a `BASE`-prefixed identifier, matching the pattern in Identifiers ([LEDGER.md](LEDGER.md)) |
| `captured_on` | `YYYY-MM-DD` |
| `client` | non-empty string |
| `adapter_version` | integer, at least 1 |
| `items` | array (see below) |

Each element of `items` requires `kind`, `name`, `anchor`, `digest`, `attributes`, `origin`,
`state`.

| Field | Rule |
|---|---|
| `kind` | one of `instruction-file`, `skill`, `plugin`, `agent`, `command`, `hook`, `mcp-server`, `permission-rule`, `model-setting`, `env-var-name` |
| `name` | non-empty string |
| `anchor` | non-empty string |
| `digest` | `sha256:<64 hex>` or `null` |
| `attributes` | object |
| `origin` | `pre-existing`, or a record identifier with prefix `PROP` |
| `state` | `present` or `not_present` |
| `portable` | boolean, optional |

`state` records that a probe matched nothing. The design spec requires that a probe matching
nothing be recorded as `not_present`, never as an error, but gives no field to hold that outcome —
it is neither a `kind` nor one of the other documented item fields. A separate `state` field is
used rather than overloading `kind` (a closed enum client adapters are written against) or relying
on a `null` `digest`: a present item can legitimately have nothing to hash — an `env-var-name` has
a name and no readable value — so `null` already means something else.

`portable`, on a baseline item or on a run target, is a boolean when present and is never required.
Requiring it would invalidate every RUN record written before this release, including this
repository's own, none of which ever carried it.

## Capturing a baseline with `scan`

```text
python assets/scripts/dashboard.py scan --id BASE-2026-000 [--client NAME] [--project PATH]
                                        [--adapter FILE] [--user-config PATH]
```

`scan` reads one client's configuration and emits exactly one `baselines[]` entry, as JSON, on
stdout. It opens files, hashes their bytes, and parses JSON and TOML; it writes no file and creates
no directory anywhere, so stdout is the only thing it produces. It never runs anything a
configuration file names: a settings key whose value is a shell command that mints a credential is
recorded as a name and a digest like every other value.

| Argument | Meaning |
|---|---|
| `--id` | required; the `BASE` identifier the emitted entry carries |
| `--client` | the client to scan; detected when omitted, see The unknown client below |
| `--project` | the root `$PROJECT` anchors to; the process working directory when omitted |
| `--adapter` | one adapter file to run, overriding selection entirely and validated like any other |
| `--user-config` | the configuration root user adapters are read from; that directory is never read when omitted |

`--id` is required because allocation is a ledger concern and `scan` does not get a second, private
implementation of it. The rules about sequences, provisional suffixes, and cross-scope collision are
stated once, in Identifiers ([LEDGER.md](LEDGER.md)), and they need a ledger to apply; `scan` opens no ledger. It checks
only that what it was handed is a well-formed `BASE` identifier, before the adapter is opened, so a
typo costs no walk over anyone's configuration.

Placing the entry is the agent's work, not the command's: take the next free `BASE` number under the
Identifiers rules — from the global ID authority, or as a `-P` provisional identifier when the
authority is unreachable — pass it as `--id`, and append the emitted object to the target ledger's
`baselines[]` array. A baseline identifier is spent when the entry is placed, exactly as a record's
is.

Exit codes: `0` clean, `1` findings, `2` a tool error — a malformed `--id`, an adapter that does not
validate, an unknown `--client`. The entry still reaches stdout at `1`; nothing reaches it at `2`.
Selection notes and findings go to stderr, so stdout parses as one JSON document whatever the
outcome.

A finding here means the baseline may be reporting a clean machine when it in fact looked at almost
nothing, and three raise one: the adapter is past its `expires_on`; its `$USER_CONFIG` resolved to no
directory on this machine, so every probe beneath it is `not_present` rather than looked at; or
selection fell back to `generic`, which probes nothing. Any other unresolved anchor is still recorded
on each probe beneath it, as `reason: "unresolved_anchor"` in the item's attributes, but does not
move the exit code — `codex.json`'s `$SYSTEM_CONFIG` can never resolve on Windows, and a finding an
operator can never clear teaches them to ignore the exit code, which costs every other finding its
meaning.

## The adapter format

An adapter is data, one JSON document per client, and `scan` knows nothing about any client except
what it reads from one. `assets/schemas/adapter.schema.json` states the format for humans and
external tools; the bundle carries no JSON Schema library, so the loader's own validator is what
actually runs, and a test compares the two in both directions. A single finding refuses the whole
document. Unlike a ledger's findings, which are reported and counted, an adapter's are fatal: every
probe beneath a broken adapter is suspect, and continuing would produce a baseline that looks clean
because it scanned nothing.

Every top-level field is required, and any other field is a finding:

<!-- ADAPTER_FIELDS_START -->
| Field | Rule |
|---|---|
| `adapter_version` | integer, at least 1; copied onto the emitted entry so a baseline records which generation of the adapter produced it |
| `client` | non-empty string matching `[a-z0-9-]+`. This, not the file name, is the adapter's identity: `--client` resolves against it, and a user adapter overrides a bundled one by matching it |
| `expires_on` | `YYYY-MM-DD` |
| `anchors` | object; each key an anchor name in `$NAME` form, each value a non-empty array of candidate roots |
| `probes` | array, and it may be empty — an adapter that probes nothing is the entire point of `generic.json` |
| `sensitive_key_patterns` | array of non-empty strings; required, and may be empty |
| `resolution` | optional object mapping a baseline item kind to how the client resolves that kind across scopes — `mode` is one of `override`, `key-override`, `merge`, `concatenate`; `order` (highest precedence first) is required under the first two, forbidden under the last two, and must name exactly the scopes the probes of that kind declare |
<!-- ADAPTER_FIELDS_END -->

**Anchor candidates are tried in order and the first that exists wins.** A candidate is either
`$env:NAME` — the value of that environment variable, where unset and empty are the same thing and
both are skipped, because an empty variable is what a shell leaves behind after `export NAME=` — or a
filesystem path, with a leading `~` expanded and a relative candidate resolved against `--project`
rather than against the process working directory. A candidate qualifies only when it resolves to an
existing **directory**; one that exists as a file does not, since joining a probe's tail onto a file
yields paths that can never resolve. When no candidate qualifies the anchor is *unresolved*: it is
absent from the roots rather than guessed at, and every probe beneath it is recorded `not_present`.
Guessing the vendor's default instead is the failure the research names outright — `CLAUDE_CONFIG_DIR`
and `CODEX_HOME` relocate everything, and an adapter that scans the default tree anyway reports a
clean baseline for a configuration it never looked at. This is why every `$env:` candidate is written
ahead of the default it overrides.

The shipped adapters declare anchors beyond the design spec's three, and they are extensions
rather than part of that design:

- `$SYSTEM_CONFIG`, declared by `codex.json` as `/etc/codex` on Linux and macOS and
  `C:/ProgramData/OpenAI/Codex` on Windows, exists because those locations cannot be written as a
  probe at all: `check_glob` refuses an absolute pattern, so a system path can only reach an
  adapter as an anchor root. `$MANAGED_CONFIG` and `$LEGACY_MANAGED_CONFIG` in `claude-code.json`
  exist for the same reason.
- `$HOME`, declared as `~` by `codex.json`, exists because the research places
  `<home>/.agents/skills/` against the home directory itself rather than under the relocatable
  user configuration root.
- `$APP_STATE`, declared by `claude-code.json` as `CLAUDE_CONFIG_DIR` and then `~`, is where
  `.claude.json` lives. The file sits in the home directory by default and moves under
  `CLAUDE_CONFIG_DIR` when that is set, so it needs the variable ahead of the default exactly as
  `$USER_CONFIG` does, with a different default behind it. Until 0.7.0 the file was probed under
  `$HOME`, which read the wrong state file on a relocated installation.

Nothing in the path layer treats any of these names specially: a path found under one is stored
anchored, and the longest-anchor rule decides between them like any other pair.

**Probes.** Each requires `kind` and exactly one of `glob` or `path` — both is a finding, neither is
a finding:

<!-- PROBE_FIELDS_START -->
| Field | Rule |
|---|---|
| `kind` | required; one of the ten `items[].kind` values in Baselines above, imported from the same closed enum rather than restated |
| `glob` | anchored pattern, expanded under its resolved anchor, one item per match and one `not_present` item when it matches nothing |
| `path` | anchored path, yielding exactly one item |
| `scope` | optional non-empty string, copied onto the item's attributes |
| `parse` | optional `json` or `toml`, and only alongside `path` |
| `pointer` | optional RFC 6901 JSON pointer, and only alongside `parse` |
| `lockable` | optional boolean, false by omission: whether this probe's items are pinned into `agent.lock` |
<!-- PROBE_FIELDS_END -->

`glob` and `path` both pass `check_glob` at **load** time, under the rules in Adapter glob safety
([LEDGER_PATHS.md](LEDGER_PATHS.md)), so an adapter carrying a `..` segment or an absolute form is refused before a single probe
runs. That check is about the pattern; every path a probe actually produces is re-checked against its
anchor before it is opened, because a symlinked directory can carry a match out of the tree between
the adapter being validated and the walk running.

`parse` reads the file, and `pointer` selects a sub-document within it: the location a pointer names
becomes one item per key, which is what turns one `settings.json` into one `mcp-server` item per
server. `parse` pairs only with `path` because parsing is per-document and a glob yields many
documents against one pointer. A pointer that does not resolve is one `not_present` item, not an
error — a client with no MCP servers configured has no `mcpServers` key, and the baseline has to
record that it looked. A file that will not parse is `present`, with its digest and a stable
`parse_error`; a `toml` probe under an interpreter without `tomllib` is `present`, with its digest and
`parse_unavailable`, never a crash and never a pretence that the file held nothing.

`scope` is recorded and never resolved. It names the layer an item came from — the shipped adapters
use `user`, `project`, `system`, and `managed`. `scan` computes no precedence winner from it;
Declared resolution below states what `drift` may later make of it. A probe therefore records that
a file exists, never that the client loaded it: `claude-code.json` probes `AGENTS.md`, which the
client reads only when no `CLAUDE.md` is in the working directory or above it.

No text a parsed document holds reaches a baseline. Every string value is replaced by
`{"redacted": true, "digest": "sha256:…"}`, whatever key it sits under, so an item's
`attributes.value` carries the document's shape (key names, nesting, array lengths, and its
numbers, booleans and nulls) and one digest per string. That is enough to say which leaf changed
between two baselines and never enough to say what it held.

`sensitive_key_patterns` are `fnmatch` patterns matched case-insensitively against key names in a
parsed document, so `*key*` and the literal `env` both work, and `env` matches the key `env` without
matching `environment`. A matching key keeps its name; its value is replaced by
`{"redacted": true, "digest": "sha256:…"}` whatever its type, because an object and an array carry
secrets as readily as a string. Recursion stops at the match: nothing beneath a redacted value is
walked or recorded, which is why the single pattern `env` protects an entire MCP `env` block without
enumerating what is inside it. The digest is there so drift can tell "the token changed" from "the
token is gone" without ever having held either. The patterns live in adapter data rather than in code
because the key name a vendor invents next is not something the code can know.

`expires_on` exists because a vendor path is time-sensitive evidence, under the same rule Evidence
([LEDGER.md](LEDGER.md)) states for every other claim: the shipped adapters were built from one research document and
inherit its expiry. Running an adapter past that date is a finding rather than an error, and the scan
still produces its baseline, because an adapter whose paths have quietly gone stale is exactly the
case that produces a clean-looking baseline of nothing.

## Declared resolution

`resolution` is the adapter's statement of how its client resolves one kind of configuration
across layers, and it is declared data closing a gap this document used to record: the format had
nowhere to state an ordering, so `drift` was going to need one "from somewhere"; the ordering now
ships as declared data, beside the probes it ranks, and it inherits the same research expiry those
probes already carry — `expires_on` covers the resolution claims exactly as it covers the paths.

The field is optional, and an adapter written before it existed stays valid: its absence means
every kind is undeclared, which `drift` reports rather than papers over. When present, each key is
a baseline item kind and each value declares:

<!-- RESOLUTION_FIELDS_START -->
| Field | Rule |
|---|---|
| `mode` | required; one of the four modes tabled below, and anything else is a refusal, never a skip |
| `order` | an array of scope names, most-precedent scope first; required under `override` and `key-override`, forbidden under `merge` and `concatenate` |
<!-- RESOLUTION_FIELDS_END -->

An `order` must rank every item it will meet: each scope it names must be one some probe of that
kind declares, each scope those probes declare must appear, and no scope may repeat. An ordering
that fails any of these is refused at load, when the author can still fix it, not at drift time.
It ranks only the scope vocabulary the adapter itself probes — `user`, `project`, `system` in the
shipped files — and claims nothing about layers the adapter does not look at; the research's
unrestricted chains stay in the research document.

The four modes, and what `drift` computes under each — a winner exists only under `override`:

<!-- RESOLUTION_MODES_START -->
| Mode | Meaning | What `drift` computes |
|---|---|---|
| `override` | a same-kind, same-name item at an earlier scope shadows one at a later scope, whole | a winner: `effective` on the earliest scope present, `shadowed_by` on the rest |
| `key-override` | layers resolve per key inside parsed documents, so item granularity cannot rank whole files | no winner; the declared chain is reported as context |
| `merge` | every layer contributes and nothing shadows anything | no winner; the mode itself is the answer |
| `concatenate` | layers are read in a defined order and every layer in the chain is live | no winner; the order is reading order, not rank |
<!-- RESOLUTION_MODES_END -->

A kind absent from `resolution` is undeclared, and `drift` reports exactly that — not a defect but
the honest state for cross-scope semantics nobody verified. Claude Code hooks, agents, commands,
and plugins ship undeclared for precisely that reason: no primary source in the research states
their cross-scope behaviour, and this project does not ship an ordering nobody verified.

## The unknown client

Without `--client`, `scan` detects: an adapter matches when at least one of its `$USER_CONFIG`
candidates resolves, under the candidate rules above and no others, so an adapter is detected on
exactly the conditions its probes would later run under. Exactly one match selects that adapter. Two
or more, or none, selects `generic`, which declares no probes and therefore emits an entry whose
`items` array is empty. Detection never guesses between two plausible clients silently.

Reaching `generic` by falling back and asking for it by name are deliberately different outcomes.
`--client generic` is an answer, and it exits `0`. A fallback is not an answer; it is a scan that
covered nothing while looking clean, so it is a finding that names the clients weighed and points at
`--client`. The two are told apart by structured data carried out of selection, never by matching on
the wording of a note.

A client no bundled adapter covers is served by a user adapter, at:

```text
<user-config>/agent-ingest-audit-optimize/adapters/local.json
```

`<user-config>` is what `--user-config` names, and without it that directory is never opened — not
defaulted to the home directory. The tool cannot know which client's configuration root is meant on a
machine that may have several, and reading a directory the user did not name is the thing the whole
path boundary exists to prevent.

A user adapter is keyed by its `client` value like every other adapter, and a user adapter beats a
bundled one declaring the same client, with a note recording the override and naming both files. Two
adapters in the *same* directory declaring one client is refused outright: whichever won would be
decided by sort order, and the loser would be invisible — including to the user who edited it and saw
nothing change.

A user adapter is validated exactly as a bundled one is, and refused the same way. It is never
silently skipped in favour of the bundled file it was written to replace: routing around a broken
override leaves the user reading a baseline from the adapter they thought they had overridden.
`SKILL.md` owns the other half of this — how the agent asks for the paths and what it may write.

## What a baseline does not cover

`scan` reads less than the configuration it walks, and each of these is a decision rather than an
oversight. They are recorded because a gap nobody wrote down is indistinguishable from a gap nobody
noticed.

**Credential files are not probed at all.** Codex's `auth.json` and Claude Code's credentials file
are the two highest-risk files the research names, and nothing looks at either — not even for a
digest and a `present`/`not_present` state, which would hold no secret. The obstacle is the `kind`
enum: it is closed by the design spec, all ten values name a kind of configuration, and none of them
fits a credential store. The cost is a drift signal one would very much want, because a credentials
file appearing where there was none says the store moved from the OS keyring onto the disk. Deferred
until there is an eleventh kind to record it under.

**Hook scripts are not digested, only their registrations.** A `hook` item records that a hook is
registered under a settings file's `hooks` key; the script it runs is not opened and not hashed, so
rewriting that script produces an identical baseline. This is deliberate and not an oversight:
resolving a path read out of a configuration file would cross the boundary drawn in 0.2.2, which
`verify` states as never dereferencing a path that arrived as content rather than as an argument.
A probe naming a hooks directory outright would be a different thing and is allowed by the format;
none is shipped.

**Managed policy is probed as of 0.5.0, except on Codex and except the Windows registry.** The
three `managed-settings.json` paths were verified against first-party documentation on 2026-07-31
and ship as `$MANAGED_CONFIG`; the Windows path that lost support in v2.1.75 ships as
`$LEGACY_MANAGED_CONFIG` and is probed as an expected absence, so policy the client no longer reads
raises `DRIFTED`/`appeared` if it reappears. What remains unprobed, and is not guessed: the Windows
registry policy keys the 2026-07-30 research names without a path, and any managed-policy location
for Codex, for which no primary source was found. `mcp-server` also carries no `managed` entry in
its precedence chain, because no managed MCP location is documented — the adapter validator refuses
an order naming a scope no probe declares, which is how that mistake was caught rather than shipped.

**A layer a platform does not have is skipped, not recorded absent.** A `$platform:<system>:<path>`
candidate applies only where `sys.platform` starts with `<system>`, and is skipped textually before
any filesystem call otherwise. An anchor whose every candidate is skipped that way is *not
applicable on this platform*: its probes produce **no items at all**, plus a note naming the anchor
and the platform. This closes what this list used to record about `$SYSTEM_CONFIG` having no way to
be marked absent by design — `/etc/codex` on Windows now yields nothing rather than a permanent
`not_present`, because `not_present` means "looked, found nothing" and nothing was looked at.
Applicable-and-absent is unchanged: a guard that matches makes the anchor applicable even when the
directory is missing, and that absence is verified and recorded.

Because a baseline therefore covers different anchors on different platforms, each entry records
the `sys.platform` that produced it in `platform`. The field is optional: entries captured before
0.5.0 stay valid.

**Text is withheld; key names and numbers are not.** Until 0.6.1 a secret was protected only by the
key it sat under, so one under a key no pattern named was copied whole: a credential in a hook's
`command` and one in a permission rule were both reproduced reaching a baseline and, through
`update`, the ledger. Every string a parsed document holds is now replaced by a digest, which closes
that for text without anyone having to guess a key name. `sensitive_key_patterns` still matter for
what a digest per string does not cover: a matching key withholds its whole subtree, key names
included, which is why `env` hides the variable names of an MCP `env` block and not only their
values. `*url*` is a substring match and will also withhold a key that merely contains those three
letters, `curl` among them, which costs a server named that way its whole entry. What stays open: a
secret used as a key name outside a withheld subtree is copied, a numeric secret is copied, and the
digests are unsalted, so a short or common value can be confirmed by hashing a guess. A baseline
captured by 0.6.0 or earlier keeps the text it copied; the remedy is to capture a new one and stop
sharing the old.

**A `parse` probe over an empty `sensitive_key_patterns` is a finding, not a refusal.** An adapter
may legitimately declare no patterns — `generic.json` does, and it probes nothing — so refusing the
empty list outright would refuse the one file that needs it. But an adapter that parses a document
while redacting nothing writes every key name and every number it reads straight into the baseline,
and a user adapter
overriding a bundled client by name is exactly how that arrives: the override is honoured whole, the
bundled patterns are not merged into it, and a scan that used to withhold an `env` block whole would
then enumerate every variable name inside it while exiting `0`. `scan` therefore raises a finding for the combination,
which moves the exit code without withholding the baseline. It is recorded here as a gap rather than
as a fix because the finding reaches stderr beside the baseline it warns about: an operator who
redirects stdout and ignores the exit code has the key names anyway.
