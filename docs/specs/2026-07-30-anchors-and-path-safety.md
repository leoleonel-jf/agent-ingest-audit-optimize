# Anchors, Path Safety, and the Baseline Schema (0.2.3)

Status: approved 2026-07-30 under standing autonomy
Target version: 0.2.3
Phase: the first of three increments toward the spec's 0.3.0

## 1. Where this sits

`docs/specs/2026-07-29-ledger-and-dashboard-design.md` §16 defines phase 0.3.0 as one release
delivering `adapter.schema.json`, three client adapters, `scan`, `drift`, `rollback-preview`, and
the unknown-client flow. A coupling review of those deliverables found `scan` blocked on four
things that do not exist, and `rollback-preview` defined entirely in terms of `drift`'s output. It
is not one release.

It ships as three increments. The **version** `0.3.0` is reached when §16's acceptance criteria are
all met, not before:

| Increment | Delivers |
|---|---|
| **0.2.3** — this spec | Anchor resolution (§7.1), path safety (§13.6), the `baselines[]` field schema |
| 0.2.4 | `dashboard.py` split into modules, `adapter.schema.json`, the three adapters, `scan`, the unknown-client flow |
| 0.3.0 | `drift`, `rollback-preview` — completing §16 |

This increment adds no new command. It builds the substrate the next one consumes, and every piece
of it is testable on its own.

### 1.1 Why the module split is not here

`docs/plans/2026-07-29-ledger-0.2.0.md:47` deferred splitting `dashboard.py` to 0.3.0, on the
grounds that `scan`, `drift`, `rollback-preview`, and `build` arrive and a single file stops being
defensible. It belongs immediately before those, not here. Splitting 742 lines now means moving
code into module boundaries chosen without knowing what the new modules are, and rewriting the
import surface of a 2,224-line test file for no behavioural gain. It is the first task of 0.2.4,
where the new modules exist to justify the boundaries.

## 2. What comes due now

Two spec requirements were deliberately deferred through 0.2.0, 0.2.1, and 0.2.2 because nothing
exercised them. `scan` exercises both, so they come due before `scan`, not with it.

### 2.1 Anchor resolution — spec §7.1

Verbatim from the design spec:

> Absolute paths are never stored when an anchor applies. Anchors resolve per client adapter:
> `$USER_CONFIG` — the client's user-level configuration root; `$PROJECT` — the project root of the
> ledger that owns the record; `$PLUGIN` — the installed bundle root. Anything outside an anchor is
> stored absolute and flagged `portable: false`.

Today `verify` treats `anchor` as an opaque string. Nothing resolves one, nothing produces one,
nothing checks that a stored path is anchored when it could have been.

### 2.2 Path safety — spec §13.6

Verbatim, and listed under requirements the spec calls mandatory and covered by evaluations:

> `dashboard.py` refuses to read or write outside resolved anchors, rejects symlinks that escape an
> anchor, and refuses adapter globs containing `..`.

This constrains `scan` and `build`. Neither exists. What this release delivers is the enforcement
layer itself, with its own tests, so that `scan` consumes a proven primitive rather than growing
its own.

It does **not** change `verify`. `verify` reads the paths the user names on the command line, which
are outside every anchor by construction, and 0.2.2 established the rule that `verify` never opens
a path read out of ledger content. Both remain true.

### 2.3 The baseline schema

`ledger.schema.json` declares `baselines` as `{"type": "array", "items": {"type": "object"}}` and
nothing more. `references/LEDGER.md` says so honestly: "each element must be an object, but no
field-level schema yet." Meanwhile the design spec §7.5 defines every field a baseline entry
carries. `scan` writes those entries, so `verify` must be able to validate them before `scan` can
be trusted to produce them.

## 3. Design

### 3.1 The anchor resolver

A resolver is constructed from a mapping of anchor name to an absolute root:

- `$USER_CONFIG` — the client's user-level configuration root;
- `$PROJECT` — the project root of the ledger that owns the record;
- `$PLUGIN` — the installed bundle root.

It offers two directions.

**Anchoring** takes an absolute path and returns the anchored form when one applies — `$PROJECT/x/y`
— or the absolute path plus a `portable: false` marker when none does. When more than one anchor
contains the path, the **longest matching root wins**, so a project nested inside a user
configuration root anchors to `$PROJECT` rather than `$USER_CONFIG`. The spec does not state this;
it is the only choice that keeps the more specific anchor meaningful, and it is written down here
rather than left to whoever implements `scan`.

**Resolution** takes an anchored path and returns the absolute path, or refuses. Refusal is the
subject of §3.2.

Anchor roots are supplied by the caller. This release does not decide where a client's user
configuration root is — that is adapter data, and it arrives in 0.2.4.

### 3.2 The safety rules

Resolution refuses, with a distinct reason for each, when:

1. the anchored path names an anchor that was not supplied;
2. the path contains a `..` segment, before any normalization — the check is textual and happens
   first, so it cannot be defeated by a form that normalizes into the anchor and back out;
3. the path is absolute where an anchor form was required;
4. the resolved result lies outside the anchor's root after resolving symlinks;
5. any component of the path is a symlink whose target lies outside the anchor's root.

Rules 4 and 5 are the only ones that touch the filesystem, and they touch it only under a root the
caller supplied — never a root read out of a ledger. That is the same boundary 0.2.2 drew for the
digest check, held for the same reason.

**Rule 5 is deliberately stricter than rule 4.** A symlink that points outside the root is refused
even when the final resolved path lands back inside it, because a link that leaves the anchor is a
link an attacker can re-point later. The spec says "rejects symlinks that escape an anchor"; this
is what that means operationally.

A `PathSafetyError` carries the offending path and the rule that refused it. Callers report it as a
finding; nothing swallows it.

### 3.3 Glob safety

Adapter globs are refused when they contain a `..` segment or are absolute, per §9's fourth rule
("no probe field may contain a shell command or a glob that escapes its anchor; `scan` rejects `..`
segments and absolute globs"). The check lives here so 0.2.4's adapter loader consumes it rather
than reimplementing it.

Globs are not expanded in this release. Nothing yet has a directory to expand them against.

### 3.4 The baseline entry

From design spec §7.5, now made structural. A `baselines[]` entry requires `id`, `captured_on`,
`client`, `adapter_version`, `items`:

| Field | Rule |
|---|---|
| `id` | matches the record identifier pattern, prefix `BASE` |
| `captured_on` | `YYYY-MM-DD` |
| `client` | non-empty string |
| `adapter_version` | integer, at least 1 |
| `items` | array; each element an object as below |

Each item requires `kind`, `name`, `anchor`, `digest`, `attributes`, `origin`, `state`:

| Field | Rule |
|---|---|
| `kind` | one of the ten in §7.5: `instruction-file`, `skill`, `plugin`, `agent`, `command`, `hook`, `mcp-server`, `permission-rule`, `model-setting`, `env-var-name` |
| `name` | non-empty string |
| `anchor` | non-empty string |
| `digest` | `sha256:<64 hex>` or `null` |
| `attributes` | object |
| `origin` | `pre-existing`, or a record identifier with prefix `PROP` |
| `state` | `present` or `not_present` |

`sequences.BASE` covers a `baselines[]` entry's number exactly as it covers a record's. The
existing sequence rules — the per-document floor and the authority's set-wide coverage added in
0.2.2 — extend to baseline identifiers. A `BASE` identifier is an identifier; it was already in the
pattern and already had a sequence slot, and nothing was feeding either.

**`state` fills a gap the design spec left.** §9 requires that "a probe that matches nothing is
recorded as `not_present`, never as an error", but §7.5 gives no field to record it in — it is
neither a `kind` nor a documented item field. A separate `state` field is chosen over overloading
`kind` or relying on a null `digest`, because a present item can legitimately have a null digest
(an `env-var-name` has a name and no readable content) and overloading `kind` would corrupt a
closed enum that adapters are written against. This is a spec gap being filled, and it is recorded
as such rather than presented as if §7.5 had said it.

### 3.5 Where `portable: false` lives

§7.1 and §8 both refer to a `portable: false` flag for a path stored absolute because no anchor
applied. Nothing in the schema carries it. It becomes an optional boolean on a baseline item and on
a run target, defaulting to absent, which means portable. `verify` checks its type when present and
does not require it — requiring it would invalidate every RUN record written before this release,
including this repository's own, for no gain.

## 4. Scope

In scope: the anchor resolver and its safety rules, glob safety, the `baselines[]` schema and its
runtime validation, `portable` as an optional field, `references/LEDGER.md`, tests for all of it,
and the 0.2.3 release.

Out of scope: the module split (0.2.4); `adapter.schema.json` and the adapters (0.2.4); `scan`,
`drift`, `rollback-preview` (0.2.4 and 0.3.0); expanding globs; deciding where any client keeps its
configuration; any change to how `verify` reads command-line paths.

## 5. Compatibility

Additive. A ledger valid under 0.2.2 stays valid: `baselines` is empty in every ledger that exists,
`portable` is optional, and no existing check changes. The first ledger that can fail these rules
is one written by `scan`, which does not exist yet.

## 6. Acceptance

| Criterion | Evidence |
|---|---|
| A path under an anchor anchors | A path inside `$PROJECT` returns `$PROJECT/...` |
| The longest anchor wins | A project nested inside the user config root anchors to `$PROJECT` |
| A path under no anchor is absolute and marked | Returns the absolute path with `portable: false` |
| `..` is refused textually, before normalization | `$PROJECT/a/../b` is refused even though it normalizes inside |
| An unknown anchor is refused | `$NOPE/x` names its rule |
| A symlink escaping the anchor is refused | Even when the final path resolves back inside |
| An absolute path where an anchor was required is refused | Names its rule |
| Adapter globs with `..` or absolute globs are refused | Both cases |
| A well-formed baseline validates | `verify` exits `0` |
| Every baseline field rule produces a finding when broken | One test per rule |
| `BASE` identifiers feed the sequence rules | A baseline numbered above `sequences.BASE` is a finding, in both the per-document and authority forms |
| `portable` stays optional | A ledger without it validates |
| Nothing regressed | Every suite green; this repository's own ledger still exits `0` |

## 7. Risk

The symlink rules are the only new filesystem access in the release. They run only under a root the
caller supplies, and this release supplies no roots — only tests do. The first real roots arrive
with adapters in 0.2.4, which is the right time to review that boundary again with a concrete
client in hand.

Making `BASE` identifiers participate in the sequence rules is the one change that could surprise:
a ledger that had baselines and a low `sequences.BASE` would newly fail. No such ledger exists —
`baselines` is empty everywhere, because nothing has ever written one.
