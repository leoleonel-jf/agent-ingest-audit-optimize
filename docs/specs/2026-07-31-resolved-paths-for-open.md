# Resolved paths for Open (toward 0.5.0)

Status: approved 2026-07-31 under standing autonomy
Target version: 0.5.0 (first increment; does not bump the version by itself)
Phase: closes the first of the deliberate narrowings `2026-07-31-dashboard-build.md` §8 recorded

## 1. Where this sits

The 0.4.0 dashboard shipped §12.2's "Open" narrowed to known projects, because the two paths a
`known_projects[]` entry stores were the only absolute local paths the payload carried: the drift
report and the rollback preview recorded the anchor each row classified, never the filesystem
path that classification actually looked at. The 0.4.0 spec named making the full promise true "a
0.5.0 change to the Python side". This is that change.

## 2. Behaviour

Every row the two report producers emit gains one key, `path`:

- `drift_report` — every baseline-item row and every run-target row.
- `rollback_preview` — every row of the three target sets, and the report's `backup` object.

`path` is the string form of the very answer `resolve_anchored` gave for that row's anchor,
produced by one new public helper, `ledgerlib.drift.resolved_path` (re-exported from
`dashboard.py`; `rollback` reaches it through the module attribute, exactly as it reaches
`classify_target`, so one patch observes the reuse). It is `None` — never a raise — wherever no
single local file exists to open:

- a non-string anchor (a malformed item classifies `UNVERIFIABLE` and still gets a row);
- a glob pattern (`scan` stores a matchless probe's pattern as its anchor);
- any anchor the path-safety layer refuses — the refusal is already the row's classification,
  and repeating it as an error would give one refusal two voices.

A `MISSING` row keeps its path: resolution is textual for a file that is not there, and "which
file is gone" is exactly what that row's reader asks next.

## 3. The shell

`fileUrl`/`openLink` are unchanged — they already accept any absolute local path and refuse
everything else. What changes is what reaches them:

- the Inventory join (`driftStatesFor`) and the Changes join (`driftTargetStates`) carry
  `{state, path}` per row instead of the bare state (and the former now uses
  `Object.create(null)`, as the latter always did);
- the anchor cell in Inventory and Changes renders the anchor text plus an "Open" action link
  (`anchorCell`), only when the joined drift row recorded a path;
- each Rollback set row (`setRow`) and the recomputed backup line (`backupCell`) get the same
  link from the preview row's own `path`.

The anchor stays the visible text everywhere — it is the recorded fact; the link is an action
beside it, never a rewrite of it. No path in the payload (a static page, a degraded report, a
null) renders exactly what 0.4.0 rendered: plain text. One dictionary key is added in both
languages: `table.open` ("Open" / "Abrir").

## 4. What this does not do

- No new resolver, no second path-safety layer: `resolved_path` calls `resolve_anchored` and
  maps refusal to `None`.
- Records' `file` stays unlinkable — still relative to a ledger whose location the page does
  not know. If it is ever wanted, it is a `build`-side change (build knows the ledger path),
  recorded here as out of scope.
- No version bump, no packaging change: 0.5.0 ships when its remaining candidates land.

## 5. Acceptance

- `ledgerlib` tests pin: rows carry the resolved absolute path; `MISSING` keeps its path;
  pattern/refused/malformed rows carry `None`; the preview backup carries its path and `None`
  when absent, malformed, or refused; `build_payload` embeds the paths.
- Shell runtime tests (node + dom_stub) pin: Inventory links exactly the pathed rows; Changes
  links only the drift-reported target; Rollback links the pathed set rows and the one resolved
  backup; the hostile-anchor row and every static-mode panel render linkless.
- The full suites stay green: dashboard, packaging, evals.
