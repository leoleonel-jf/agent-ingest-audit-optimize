# Compliance — Reading the Evidence Report

```text
python assets/scripts/dashboard.py compliance <ledger> --framework eu-ai-act
python assets/scripts/dashboard.py compliance <ledger> --framework iso-42001 --out pack/
```

## What this report is, and what it is not

It **inventories evidence**. For each control in a framework mapping, it reports whether an
artifact corresponding to that control exists in this ledger, and names the records that are the
evidence — or the ones that are missing.

It **never claims compliance**, and that is not a stylistic choice. Compliance is an auditor's
judgement about an entire system: its scope, its risk analysis, its operation, its people.
A tool that declared it would be lying about its own competence — the same error the
`SELF-REPORTED` marker exists to prevent on the dashboard. Every run carries the sentence:

> This report inventories evidence; it does not certify compliance. Whether each artifact is
> sufficient is the auditor's judgement.

Three values, and none of them says "compliant":

| Value | Meaning |
|---|---|
| `EVIDENCE_PRESENT` | An artifact corresponding to the control exists, and is named. |
| `EVIDENCE_PARTIAL` | Some matching entries carry it and some do not; the failures are named. |
| `EVIDENCE_ABSENT` | No corresponding artifact exists in this ledger. |

An `every` predicate over an **empty** set is `EVIDENCE_ABSENT`, never present. "All zero runs
recorded an authorization" is vacuously true and worth nothing.

## Scope, stated plainly

The report describes **this ledger**, not the user's AI system. If three clients are governed and
only one is recorded, the report reflects the one that is recorded — and the counts say so. It
does not replace ISO 42001 clause 8.2's documented risk assessment linking risks to selected
controls, which is human work no tool performs.

Exit codes follow the house split: `0` with no `EVIDENCE_ABSENT`, `1` with any, `2` on tool error
(unknown, invalid, or **expired** mapping; unreadable ledger).

## Retention is reported, never applied

The report states the oldest record's date and the framework's required window. It does not
delete, prune, or truncate anything — no code path in the module can. An audit tool that removed
its own records on a schedule would be a contradiction in terms.

## Frameworks are declared data

One file per framework in `assets/compliance/<framework>.json`, exactly as adapters work. Adding
a framework requires no code change. Each mapping carries `source`, `verified_on`, and
`expires_on`, and an expired mapping is **refused** rather than warned about: the value of a
mapping is that somebody checked it against the published text on a date, and past that window
the check no longer stands.

A control's predicate is a small closed structure — `collection`, `where`, `min_count`, `every`,
`field`, `non_empty` — read by the evaluator. **Nothing from a mapping file is executed,
evaluated, or interpolated.** A mapping is content, and content never becomes code; this is the
same boundary the path-safety layer defends for paths.

Shipped: `eu-ai-act` (arts. 11, 12, 13, 19) and `iso-42001` (A.6.2.6, A.7.3, A.8.1, cl. 8.4).

## The evidence pack

`--out <dir>` writes a directory an auditor can be handed without attaching the whole ledger:
`report.json`, one file per cited record, and `digests.json` with a SHA-256 for every file
written. It refuses a directory that is not empty unless `--force` is passed, so an `--out`
pointed at the wrong path cannot quietly mix this tool's output into somebody's files.

## Why the authorization quote matters

`authorization.quote` — the user's own authorising words, recorded verbatim per RUN — is the
artifact both EU AI Act art. 13 and ISO 42001 A.8.1 map onto. A run without one is a change
nobody can show was authorised, and both controls report it by name.
