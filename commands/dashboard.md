---
description: Render the governance ledger's dashboard, optionally recapturing the environment first.
argument-hint: "[all|ledger|anchors] [--open] [--id BASE-YYYY-NNN]"
---

Run the bundle's `update` command against this project's ledger. This is a thin wrapper around
`dashboard.py`, not a second implementation: everything it decides is which ledger to point at.

## Resolve the ledger

Use, in order, the first that exists:

1. a path the user named in `$ARGUMENTS`;
2. `.agent-audit/ledger.json` under the project root;
3. otherwise, stop and say no ledger was found — do not create one.

## Choose the word

`$ARGUMENTS` may begin with `all`, `ledger`, or `anchors`. When it names none of them, use
`anchors`.

**`anchors` is the only word this command may choose on its own.** It writes the dashboard and
never the ledger. `ledger` and `all` append a new baseline to the ledger, which is a persistent
change, and the README's line holds here: analysis is read-only, and a persistent change needs an
unambiguous instruction. A bare `/dashboard` is not one. If the user typed `ledger` or `all`, that
is the instruction — proceed without asking again.

## Run it

```
python skills/agent-ingest-audit-optimize/assets/scripts/dashboard.py update <ledger> <what> [--open] [passthrough flags]
```

Pass `--open` through when the user asked to see the dashboard. Forward `--id`, `--client`,
`--out`, `--lang`, `--force`, `--project`, `--adapter` and `--user-config` verbatim when given.

## Report

stdout is one JSON object; stderr carries the notes. Report:

- which word ran and which ledger it ran against;
- the `baseline_id` and whether `minted` was `local` or `given` — when it is `local`, say plainly
  that the identifier was minted locally and needs reconciling with the global ledger;
- the dashboard path when one was written;
- every stderr note, especially a scan finding.

Exit `1` means findings, not failure: the artifact was still written. Exit `2` means nothing was
written — report what the validator said and stop.
