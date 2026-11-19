# Validation of the lean Skill, 0.10.0

Date: 2026-11-19. Spec: `docs/specs/2026-11-19-lean-skill.md`, section 10.
Clients: Claude Code 2.1.326, codex-cli 0.146.0. Model in every session: Claude Opus 5.5 (the CLI
default on this machine).

Everything below ran against the plugin archive extracted to a temporary directory outside any
checkout, loaded with `claude --plugin-dir`. The copy of the plugin installed on the machine
(0.6.0) was not loaded in any session.

## Activation

One fresh headless session per case, stopped at the first decisive signal: the Skill called, three
other tool uses, or the final answer. Twenty-two prompts: the fourteen activation cases of
`evals/suite.json` and eight requests in Brazilian Portuguese written the way a user types them
(three of them "review this before I install it": an MCP server, a plugin, a skill, each with a
real URL).

| Run | Build | Environment | Sessions | Correct | Positives | Negatives |
|---|---|---|---|---|---|---|
| 2026-11-18, 0.6.0 | checkout | the user's settings and plugins | 25 | 23 | 15 of 17 | 8 of 8 |
| A | first description | the user's settings and plugins | 22 | 19 | 10 of 13 | 9 of 9 |
| B | final description | the user's settings and plugins | 44 | 42 | 24 of 26 | 18 of 18 |
| C | released archive | `--restricted`, no user settings, no other plugin, no MCP server | 44 | 44 | 26 of 26 | 18 of 18 |

What each run showed:

- **2026-11-18.** Both misses were "review before installing" (the MCP server and the skill). That
  request fired 8 times in 10.
- **Run A.** Every "review before installing" request with a real URL fired. Two material-audit
  requests that used to fire did not (`TRG-003`, and "I saw a video saying..." in Portuguese): the
  first rewrite had pushed the audit too far down and dropped the words those requests use. The
  description was rewritten to name advice, tips, claims and recommendations, and "use when asked
  whether one holds up or is worth applying". The third miss was `TRG-013`, which then carried no
  material at all: the session went looking for the skill on disk and was cut off at three tool
  uses.
- **Run B.** Both misses were `TRG-013` in its first form, a skill bundle pasted inline that
  downloaded and ran a remote script and uploaded `~/.netrc`. The model answered at once, without
  the Skill, and answered correctly: do not install, with the three lines quoted and the
  instruction aimed at the reviewer reported and ignored. That material is now the safety case
  `SEC-003`, where activation is not what is measured, and `TRG-013` carries a bundle that takes a
  review to judge.
- **Run C.** The released archive, with nothing else on the machine able to push the model toward
  invoking a Skill. All twenty-two prompts, twice each. The same run on the build before the
  independent-review fixes, which did not touch the description, was also 44 of 44.

Read this for what it is: one machine, one model, two repetitions. In runs A and B the user's
`superpowers` plugin was active, which tells the model to invoke Skills and inflates the rate; run
C removes it. No session was run on Codex, where implicit invocation depends on the same
description but on a different matcher.

## The main path on real material

One headless session each, from the extracted archive, in an empty temporary project, with the
plugin's ledger directed to a temporary directory.

### A plugin: `STRML/cc-plugin-audit`

Request, in Portuguese: "I found this Claude Code plugin on GitHub and I am thinking of installing
it. Review it for me first: is it worth it and is it safe?"

| | 2026-11-18, 0.6.0, an article | 0.10.0, this plugin |
|---|---|---|
| Time | about 7 minutes | 184 seconds |
| Answer | 1,543 words | 594 words |
| First line | a result line, then a mandatory summary | the verdict and the reason |
| Subagents | 3 | 0 |
| Read from the Skill | `SKILL.md`, `WORKFLOW.md`, `SCOPE_AND_RISK.md`, `PLATFORM_ADAPTATION.md`, 415 lines of `LEDGER.md` | `SKILL.md`, `REVIEW.md`, `SECURITY.md`, `LEDGER.md`, the record template |
| Records | none written; the Skill asked for 1 `MAT`, 3 `PROP`, about 5 backlog entries, a baseline and a seal | 1 `MAT`, 1 file |

What the session did, checked against its transcript and the files it left:

- pinned the review to commit `07a85ec` and said the only published tag is older;
- read the manifest, the marketplace entry, the hook, the command and both scripts through the
  GitHub API, and said it had not read the tests;
- did not install, enable or run the plugin;
- found that the plugin's own marketplace entry tracks the default branch, so the reviewed code can
  change, and that one code path fails on Windows, with the line;
- checked a claim in the README against its source: the upstream issue the README calls open was
  closed as not planned;
- compared with the machine: no conflict with the existing hooks, and which installed plugins the
  tool would have anything to compare;
- ended on "adopt with changes", recorded as `ADAPT`: install pinned to that commit with
  auto-update off, and how to remove it;
- wrote one record, `MAT-2026-000`, and one record file from the template. `dashboard.py verify`
  on that ledger, run again from outside the session, exits 0.

This session ran on the first build of the day. The released archive differs from it in the
`description` line (rewritten after run A) and in the sentences added after the independent read
and after the MCP bench, listed in `docs/plans/2026-11-19-lean-skill.md`. The six steps, the
verdict rules and the record rules it followed are unchanged. It also ran before the harness was
isolated, with command tools available and the user's settings loaded, which is how it could
compare with the real setup; its ledger was the temporary one, as the transcript shows.

### An MCP server: `modelcontextprotocol/servers`, `src/filesystem`

Request, in Portuguese: "I want to install this MCP server I found on GitHub, is it safe to adopt?"
Run from the released archive, with the isolated harness described below: no tool that runs a
command, no MCP server, file tools confined to the temporary project, the extracted plugin and the
temporary ledger directory.

- 132 seconds, 586 words, no subagent. Read `SKILL.md`, `REVIEW.md`, `LEDGER.md` and the record
  template;
- the first line is the verdict: adopt with changes, at a fixed version, on the project's
  directory only, starting read-only;
- named the transport and what the client starts, the sixteen tools and the six that change files,
  and said it had read the tool descriptions for instructions and found none;
- found two published security advisories, each with the version that fixes it, and the limitation
  the server's own README states for Windows;
- said what it had not done: compared the published package with the repository, read past the
  first page of advisories, read the license file, or looked at the user's own MCP configuration,
  which the harness kept out of reach;
- gave the way back, and said nothing had been installed or changed;
- wrote one record, `MAT-2026-000`, classification `ADAPT`, no backlog entry, and said in the
  answer that the record was unverified because the session had no way to run `verify`. Run from
  outside afterwards, `dashboard.py verify` exits 0.

An earlier attempt of this same run is why the Skill now carries the sentence about never writing
a ledger from memory. The harness had confined the file tools so tightly that the session could
not open the plugin's own reference files. It reviewed the server anyway and wrote a ledger with
fields of its own, which `verify` refused. The harness was corrected, the sentence was added, and
the run above is the one that followed.

## Install benches

- `claude plugin validate --strict <extracted>`: passed.
- Codex, with `CODEX_HOME` pointing at an empty temporary directory and a local marketplace whose
  entry points at the extracted archive: `codex plugin marketplace add` and `codex plugin add`
  both exit 0; the installed tree is version 0.10.0 with both skills, all twelve reference files
  and the three manifests.

## What went wrong while measuring

The first version of the activation probe ended each session by killing the process it had
started. On Windows that process is the `claude` launcher, not the session, so the sessions kept
running to the end, under the machine's default permission mode and with its MCP servers
available. Seven of them did what the Skill tells them to do and wrote a review record. They wrote
it to the real global ledger of the machine.

The owner was told and chose to have the seven records removed. The ledger was copied first, the
records, one backlog entry and the seven record files were taken out, and `verify --chain` reports
the chain intact with the same head as before the probe ran.

The probe now runs each session with `--restricted --strict-mcp-config` and only `Skill`, `Read`,
`WebFetch` and `WebSearch`, so a session has nothing to write with, and it ends the whole process
tree. Run C used that harness; the MCP server review used the same isolation with `Write` allowed
inside the temporary directories only. After each, the real ledger was compared byte for byte
with the verified copy and was identical. Runs A and B predate the fix, and their numbers stand
because activation is decided by the first tool call.

Two things follow for the product, neither changed in this version:

- the Skill writes its record without asking, by design, and to the global ledger when the session
  is not in a project. A headless or scheduled session therefore leaves records behind;
- nothing in the plugin stops two sessions from writing the same ledger at once. Seven did, within
  eight minutes, and the file survived, which is luck and not a guarantee.

## Not verified

- Activation on Codex, and with any model other than Opus 5.5.
- The material-audit path end to end after the rewrite: it was exercised for activation only.
- A review of a standalone skill end to end (activation only).
- Step 5 of a review, the comparison with the user's real setup, under the isolated harness: only
  the first, unisolated run could read it.
