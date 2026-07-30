# `scan` Dogfood — Release 0.2.5

- Date: 2026-07-30
- Plugin version: 0.2.5 (in development, Task 10 of `docs/plans/2026-07-30-adapters-and-scan.md`)
- Host: Windows 11, Python 3.13.2, CPython from `C:\Python313`
- Status: **`scan` works and its output validates — with nine findings, none fixed here**

> This is a public record and it names no path from this machine. Every absolute path this run
> produced stayed on the machine; what appears below is counts, shapes, and anchored forms. The
> baselines themselves are not committed: they contain this operator's real configuration.

## Objective

`scan` is the first command in this plugin that reads a real user's configuration rather than a
file named on the command line. Everything before it was exercised against fixtures written to
provoke a specific check. Task 10 Step 6 exists because a command whose first real run happens
after the release is not validated. This run answers three questions and nothing else: does the
emitted entry survive `verify`, does a secret escape, and is the run fast enough that anyone would
use it twice.

A dogfood that found nothing is a dogfood that did not look. This one found nine things.

## Commands and timings

Run from the repository root, five invocations each, cold OS cache not controlled for. Wall clock
includes interpreter startup, which dominates the first row.

| Command | min | median | max | exit | items |
|---|---|---|---|---|---|
| `dashboard.py scan --id BASE-2026-000` | 0.073s | 0.074s | 0.082s | 0 | **0** |
| `... scan --id BASE-2026-000 --client claude-code` | 0.162s | 0.176s | 0.208s | 0 | 110 |
| `... scan --id BASE-2026-000 --client codex` | 0.083s | 0.089s | 0.096s | 1 | 12 |

Fast enough not to think about. The `claude-code` run digests 82 files and parses six JSON
documents, one of which is this machine's `~/.claude.json`, in under a fifth of a second. Speed is
not a concern for this command and no further work on it is warranted.

## What came out

`--client claude-code`, 110 items:

| kind | present | not_present |
|---|---|---|
| skill | 54 | — |
| agent | 28 | — |
| hook | 5 | 2 |
| permission-rule | 2 | 2 |
| instruction-file | 1 | 5 |
| model-setting | 1 | 2 |
| mcp-server | 1 | 1 |
| plugin | — | 2 |
| command | — | 1 |
| env-var-name | — | 3 |

Scopes: 97 `user`, 13 `project`. Reasons on absent items: 11 `missing`, 6 `no_match`, 1
`pointer_unresolved`. No `parse_error`, no `parse_unavailable`, no path-safety refusal, nothing
flagged `portable: false`.

`--client codex`, 12 items: 2 `present` and 2 `not_present` each for `instruction-file`,
`model-setting`, and `skill`, across `user`, `project` and `system` scope. Reasons: 6 `no_match`,
1 `missing`, 2 `unresolved_anchor`.

Bare `scan --id BASE-2026-000`: **0 items**, exit **0**. See finding 1.

Cross-checked by hand against the filesystem: 28 agent files, 54 `SKILL.md` files, and the five
hook events in the user `settings.json` are exactly what is on disk. Every `not_present` is
explicable — the ones that are explicable for the wrong reason are findings 2, 3 and 7.

## Acceptance — the entry validates

The 110-item `claude-code` entry was placed unmodified into a minimal ledger and passed to the
shipped validator:

```text
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py verify <ledger>
1 ledger(s) validated
exit=0
```

Real data, real file, real command, zero findings. This is the criterion the whole release rests
on and it holds.

## Secret check

Method, run over the raw stdout of both scans rather than over the in-memory objects, because the
serialised form is what leaves the process:

1. Every key anywhere in a parsed value matched against `token|secret|password|credential|api_key|auth|bearer|key`,
   asserting each match's value is a redaction marker.
2. Every run of 28+ characters of high variety scanned for anything token-shaped, excluding
   `sha256:` digests.
3. Known credential prefixes: `sk-`, `ghp_`, `gho_`, `github_pat_`, `xoxb-`, `xoxp-`, `AKIA`,
   `ASIA`, `AIza`, `ya29.`, `eyJ…`, `-----BEGIN`.

Result: **zero credential-shaped strings in either output.** Every key under a sensitive pattern
resolved to a marker. Two MCP `env` blocks — one in Claude Code's `~/.claude.json`, one in Codex's
`config.toml` — were replaced whole by `{"redacted": true, "digest": "sha256:…"}`, and nothing
beneath either appears anywhere in the output: not the variable names, not the values. That is the
recursion-stops-at-the-match rule working on real data.

What did come out in plaintext is findings 4 and 5.

## Findings

### 1. The plan's own Step 6 command emits an empty baseline and exits `0`

`scan --id BASE-2026-000` with no `--client` — the exact command in the plan — selects
`generic.json`, emits an entry with `"items": []`, and exits `0`. The reason is correct and is
printed: this machine has both `~/.claude` and `~/.codex`, so detection is ambiguous and refuses to
guess. The note reaches stderr and says so.

The exit code does not. A caller that checks the exit code, which is the one thing a caller is
supposed to check, is told the scan was clean. It scanned nothing. This is precisely the failure
the spec names — "a silently clean baseline is the worst output this tool can produce" — reached
by a path the spec did not consider, because §3.4 treats falling back to `generic` as a selection
outcome rather than as a coverage failure. On any machine with two supported clients installed, the
default invocation of this command is useless and says it succeeded.

Not fixed here, and deliberately not fixed in `scan.py`: `select_adapter` returns its notes as
plain strings with nothing machine-readable distinguishing "generic because detection was
ambiguous" from "generic because the user asked for it", and re-deriving detection inside `scan`
to tell them apart would put the detection rules in two places — the thing `_user_config_resolves`
exists to avoid. The fix belongs in `adapters.py`: return a structured selection result carrying
*why*, and let `scan` turn a fallback into a finding.

### 2. The `plugin` kind found nothing on a machine with dozens of plugins installed

`claude-code.json` probes `$USER_CONFIG/installed_plugins.json` and
`$USER_CONFIG/known_marketplaces.json`. Neither file exists on this machine. Both come back
`missing`, the `plugin` kind ends with zero present items, and the exit code stays `0`.

This machine has a populated `~/.claude/plugins/` directory and a large number of active plugins —
the session that produced this document is running many of them. The baseline says there are none.
Nothing in the output distinguishes "this user installed no plugins" from "the adapter is looking
at two filenames that do not exist here", and that is the exact confusion the whole `expires_on`
mechanism was built to make visible. `expires_on` catches a path that goes stale with time; it does
nothing about a path that was never right on this platform or this version.

The finding is against `assets/adapters/claude-code.json`, not against `scan`. Whether the correct
probe is `$USER_CONFIG/plugins/**` or something else is a research question, and
`docs/research/2026-07-30-client-configuration-paths.md` is the only thing allowed to answer it.

### 3. `settings.local.json` is probed at project scope and not at user scope

`claude-code.json` probes `$PROJECT/.claude/settings.json` *and*
`$PROJECT/.claude/settings.local.json` — model settings, permissions, hooks, and env for each. At
user scope it probes only `$USER_CONFIG/settings.json`. This machine has
`~/.claude/settings.local.json`, and none of it is in the baseline.

Local settings are where a user's machine-specific permission grants live. A permission audit whose
baseline covers the shared user settings and silently omits the local overlay is reporting a
permission posture the machine does not have. The asymmetry looks like an omission rather than a
decision: the same four probes exist one scope down.

### 4. Codex's `shell_environment_policy.set` is stored in plaintext

Codex's `config.toml` carries a `[shell_environment_policy]` table whose `set` sub-table maps
environment variable names to their values, and Codex injects them into every shell it runs. On
this machine it holds three entries whose values are a backend list, an allow-list of hashes, and
a path — nothing sensitive, and all three were copied verbatim into the baseline.

`codex.json`'s `sensitive_key_patterns` are `*token*`, `*key*`, `*secret*`, `*password*`,
`*credential*`, `*auth*`, `env`, `headers`. `set` matches none of them, and the variable names
underneath only match by luck. A user who puts a personal access token in this table under a name
like `MY_PAT` gets it written into the baseline in full. This is the same shape as an MCP `env`
block — a mapping of names to injected values — and it is protected only when a variable happens to
be named after one of eight patterns.

The residual risk §7 of the spec names is exactly this, and the mitigation it names is exactly the
right one: the patterns live in adapter data. Adding `set` to `codex.json`'s patterns closes it.
Outside my files; reported, not done.

### 5. Thirteen absolute local paths, including the account name, are copied into the baseline

Codex's `config.toml` has a `projects` table keyed by absolute project path. All thirteen keys
land in the baseline verbatim, including one on a second drive with a non-ASCII personal folder
name. Claude Code's output has none of this.

The anchoring layer exists so a baseline stores `$USER_CONFIG/CLAUDE.md` and not a path carrying
someone's account name, and every `anchor` field in both outputs obeys that. Parsed *values* bypass
it completely: `attributes.value` is whatever the file said. That is defensible — the tool cannot
know which strings inside a document are paths — but it means the claim "a baseline is portable"
holds for the `anchor` field only, and a baseline is more personally identifying than the anchoring
rules suggest. `PRIVACY.md` should say so plainly before 0.2.5 ships, since Task 11 is writing it
anyway.

### 6. `auth.json`, named in the spec as the highest-risk file, is not probed at all

Spec §3.5: "This rule protects the highest-risk files in the research: Codex's `auth.json`, MCP
`env` blocks and headers in both clients, and the three Claude Code keys that name shell commands."
`~/.codex/auth.json` exists on this machine and `codex.json` has no probe for it. The redaction
rule has therefore never been exercised against the first file the spec names.

There is a real argument for leaving it alone — do not open a credential file you have no reason to
read. There is a better one for probing it without `parse`: a digest and a `present`/`not_present`
state, no parsing, no values, which is precisely what lets a future `drift` say "your credentials
were rotated" without ever having held them. Either answer is fine; the current state, where the
spec claims protection for a file nothing looks at, is not.

### 7. `mcp-server` covers one server on a machine running dozens

The `claude-code` scan found exactly one MCP server, from `~/.claude.json`. The session this
document was written in has many more, supplied by plugins whose configuration is not in either
probed file. Same class as finding 2: a kind that reports one when the truth is forty, with no
signal that the number is wrong.

### 8. Eight hook scripts on disk are invisible; only their registrations are recorded

The five `hook` items come from the keys under `/hooks` in the user `settings.json`. The eight
scripts in `~/.claude/hooks/` are not probed, so the baseline records that a `PreToolUse` hook is
registered but never digests the file it runs. A hook whose script is rewritten produces an
identical baseline. For a tool whose purpose is detecting configuration drift in things that
execute, that is the wrong half of the pair to record — and `$USER_CONFIG/hooks/*` is a one-line
probe.

### 9. `--client codex` exits `1` on every Windows machine, permanently

`codex.json` declares `$SYSTEM_CONFIG` with the single candidate `/etc/codex`. On Windows that can
never resolve, so the anchor is unresolved on every run, and the unresolved-anchor finding this
task added fires forever. `--client codex` will exit `1` on this platform for reasons that will
never change and that the operator can do nothing about.

I am reporting this against my own addition as much as against the adapter. The finding class is
right — an anchor that did not resolve and a client that is genuinely absent must not look the same
in the output — but a permanent, unfixable finding trains an operator to ignore the exit code,
which costs more than it buys. The cleanest resolution is in the adapter: a POSIX-only anchor
should either carry a Windows candidate or be declared optional, so that "no system-wide Codex
configuration exists on Windows" is a fact rather than a complaint. Second-cleanest is for the
finding to fire only when the anchor is one a probe actually needed *and* the platform could have
had it. Neither is in my files.

## What was right

- The entry validates on real data, first try, with no adjustment to the ledger to accommodate it.
- Redaction held. Two real MCP `env` blocks — one JSON, one TOML — were replaced whole, and nothing
  from inside either survived anywhere in the output, including the variable names.
- Every `anchor` in both outputs is anchored and portable. Not one absolute path, not one
  `portable: false`, on a Windows machine with a non-ASCII second drive in play.
- Every item carried its probe's `scope`, and every item's `origin` was `pre-existing`, with no
  exceptions across 122 items from two clients.
- `not_present` was produced 30 times and was never an error, never silence, and always named what
  was absent. The 11 `missing` and 6 `no_match` items are what let findings 2, 3 and 7 be found at
  all — a tool that omitted them would have produced a shorter, cleaner, wronger baseline.
- Streams are clean. Both stdout payloads parse as JSON with nothing else in them; every note and
  finding went to stderr.
- The `pointer_unresolved` on `/env` in the user `settings.json` is correct: that file has no `env`
  key. It is the one absent item on this machine that is absent for exactly the reason it says.

## What I would change

In rough order of how much a wrong answer costs the operator:

1. Make a fallback to `generic` a finding (finding 1). An empty baseline must not exit `0`.
2. Give `scan` a way to say "this kind found nothing anywhere" distinctly from "this kind is
   absent". Findings 2 and 7 are the same failure and neither is visible in the exit code; a
   per-kind coverage line on stderr would have surfaced both in one glance instead of in an hour of
   cross-checking against the filesystem.
3. Add `set` to `codex.json`'s `sensitive_key_patterns` (finding 4), and revisit whether an
   allow-list of safe keys beats a deny-list of secret-shaped ones for env-injection tables.
4. Probe `$USER_CONFIG/settings.local.json` and `$USER_CONFIG/hooks/*` (findings 3 and 8).
5. Decide `auth.json` (finding 6) explicitly, in the research document, either way.
6. Say in `PRIVACY.md` that `attributes.value` is verbatim file content and can carry absolute
   local paths (finding 5).

None of this is in `scan.py`, `dashboard.py`, or the test suite, which is why none of it was done.

## Full check, clean

```text
python -m unittest discover -s dashboard/tests    Ran 599 tests    OK (skipped=2)
python -m unittest discover -s packaging/tests    Ran 20 tests     OK (skipped=1)
python -m unittest discover -s evals/tests        Ran 11 tests     OK
```

`dashboard/tests` was 541 before this task; the 58 added cover assembly, expiry, the identifier
check, the CLI surface through `main`, a subprocess run over a real pipe, and a read-only guard
that patches every write API in `pathlib` and `builtins` to fail loudly.

## Conclusion

`scan` does what §3.4 says: it reads a real machine, keeps no secret, writes nothing, emits an
entry that a shipped validator accepts, and does it fast enough to run on every audit. The command
is sound.

The adapters are not yet. Seven of the nine findings are coverage gaps in adapter data — files that
do not exist on this platform, a settings file probed at one scope and not the other, an
environment-injection table outside the redaction patterns, a POSIX-only anchor on a Windows host.
Every one of them produces a baseline that looks clean, and the two mechanisms built to prevent
exactly that — `expires_on` and the `not_present` item — caught none of them, because a path that
is wrong today rather than stale next quarter is a different failure than the one they guard.
That is the thing this exercise found, and it is worth more than the passing run that surfaced it.
