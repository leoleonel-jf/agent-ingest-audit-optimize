# Plan: adapters re-verified

Spec: `docs/specs/2026-11-19-adapters-reverified.md`

Baseline on 2026-11-19, clean tree at `1f3c039`: dashboard 1452 passing, packaging 47 passing,
evals 11 passing, and `check_evidence_freshness.py` exiting `1` with three adapters expired.

1. Reopen every documentation page behind a declared path, and every location the 2026-11 review
   listed as read and not probed. Ask for verbatim text and mark what came back as a summary.
2. Confirm on a live installation, by key names only, what the documentation does not state (the
   key user-scope MCP servers live under).
3. Write `docs/research/2026-11-19-client-configuration-paths.md`, one row per path with its page
   and its kind of evidence.
4. Edit `claude-code.json` and `codex.json` to match, and only then move `expires_on` on all three.
5. Point `BundledAdapterTests` at the new research document and add one test per changed claim;
   keep exact equality on the resolution maps.
6. Ablate each claim: undo it in the shipped data, see the named test fail, restore.
7. `update`: tests for `findings` in the summary and for `--strict`, then the code, then the three
   ablations (the refusal, the summary key, the code on the expiry finding).
8. Run `scan` with each client adapter against a live installation and read the result.
9. Version pins, CHANGELOG, `docs/releases/v0.7.0.md`, build, checksums, the three suites.

Result on 2026-11-19: dashboard 1472 passing, packaging 47 passing, evals 11 passing.
`check_evidence_freshness.py` exits `0` with all five documents fresh. Eleven adapter ablations
and three `update` ablations held. In step 7 the code was written before its tests, against the
plan; the ablations are what show each test catches its guard. The live scan exits `0` for both
clients where 0.6.1 exited `1`, and the Codex baseline holds MCP server, plugin, hook and rule
items for the first time.
