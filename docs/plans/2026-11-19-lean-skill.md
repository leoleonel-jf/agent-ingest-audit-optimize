# Plan: the lean Skill

Spec: `docs/specs/2026-11-19-lean-skill.md`

Baseline on 2026-11-19, clean tree at `9358d02` (0.9.0): dashboard 1449 passing, packaging 73
passing, evals 11 passing over 34 cases.

1. Reopen the limits the description and the file size answer to, each from its own page, and
   record what could not be read (spec section 2).
2. Write the guards first, in `dashboard/tests/test_dashboard.py`: the description, the shape and
   the order of `SKILL.md`, the ground rules, the six steps and the checklist, the five verdicts,
   the wording of an authorization, one record per review, the delegation motive, and the
   section-to-file table of the split. See them fail against the 0.9.0 Skill.
3. Split `references/LEDGER.md` by script: sections move whole into `LEDGER_PATHS.md`,
   `LEDGER_BASELINES.md`, `LEDGER_CHANGES.md` and `LEDGER_INTEGRITY.md`. Add the index and the
   complete one-record example to `LEDGER.md`; name the file in each cross-reference that now
   crosses one. The 80 phrase tests keep reading the reference as one text.
4. Rewrite `SKILL.md`. Add `references/REVIEW.md`, `references/MODEL_AND_EFFORT.md` and
   `assets/templates/REVIEW.md`. Drop the context motive from `PLATFORM_ADAPTATION.md`.
5. Rewrite the guards the old text pinned, one by one: every phrase a test held before is held
   after, the two section-budget tests follow their headings, and none is removed.
6. Four activation cases and one safety case in `evals/suite.json`; the manifests, `agents/openai.yaml`, `README.md`
   and `docs/SUBMISSION.md` describe the review first.
7. A packaging test that both archives ship every file `SKILL.md` links.
8. Ablate each new or rewritten guard once: mutate the guarded text, see the named test fail,
   restore.
9. Measure activation in clean sessions against the extracted archive, and run the main path once
   on real material outside the repository.
10. An independent read of the rewrite against the old Skill, looking for a guard lost or weakened,
    for content lost in the split, and for contradictions between the files. Fix what it finds,
    each fix with its guard and its ablation.
11. Version pins, CHANGELOG, `docs/releases/v0.10.0.md`, build, checksums, the three suites.

## Guards the old text pinned

| Guard | Before | After |
|---|---|---|
| `SkillDocumentTests`: links `references/LEDGER.md`; "never counts as implementing a proposal"; "Keep the ledger" within 40 lines | held | held, same words |
| `DelegationPolicyTests`: "Never delegate implementation"; the section within 14 lines | held, heading "Delegate to preserve context" | held, heading "Delegate without handing over the pen" |
| `UnknownClientWorkflowTests`: four sentences of the unknown-client flow | held | held, same words |
| `SubagentLedgerWriteTests`: the delegating agent holds the pen; a subagent never touches `ledger.json` | held | held, same words |
| `DriftWorkflowTests`: `drift` before proposing changes; `rollback-preview` before and after | held | held, same words |
| `TheCutSkillTests`: nothing optional runs unasked; the default path names none of the four tools; `verify` stays; five safety sentences; the compliance disclaimer | held | held, same words |
| `test_plugin_formats`: the Skill says where `dashboard.py` is | held | held, same words |
| `ReferenceTests` and the other phrase tests on `LEDGER.md` | one file | five files read as one text, with the section-to-file table pinned beside them |

## Result on 2026-11-19

Dashboard 1510 passing, packaging 74 passing, evals 11 passing over 39 cases. Seventy-three
ablations held: 54 on the new and rewritten documentation guards, one on a phrase test read
through the split, one on the archive test, one on the eval count, and 16 on the guards added in
step 10. The guards of step 2 were
written and seen failing (24 failures and 126 errors) before `SKILL.md` or the references
changed.

`SKILL.md` went from 188 lines to 135, with the description at 1,015 characters. A review reads
`SKILL.md` and `REVIEW.md` (about 260 lines together) and, to write its record, the first 80 lines
of `LEDGER.md`, where it used to be sent through 1,423.

## What the independent read found

Two blockers and a handful of smaller points, all fixed before the release:

- authorization had lost "unambiguous" and its tie to a specific change, and three texts
  disagreed about it. It is restored, and an adoption authorized after a review is written as a
  `PROP` first, which also settles the reference saying an adopted classification carries through
  to a proposal;
- defining the test and the criterion before the first change, running `drift` before proposing,
  and recording an executed rollback had stayed on the material-audit path only, or gone;
- fetching a copy to read was not reconciled with read-only analysis; the rule about fetched
  pages and sensitive data had narrowed;
- `WORKFLOW.md` used `NOT VALIDATED`, which is not a record status;
- `REVIEW.md` stated client behavior in its own voice. Each statement is now a quotation with its
  page, or marked as this checklist's own.

The split lost no paragraph: the read confirmed it mechanically, and found one cross-reference
that did not name its file.

A bench session added one more: unable to open the reference, it wrote a ledger from memory. The
Skill now forbids that.

Activation and the runs on real material are recorded in `docs/validation/lean-skill-0.10.0.md`.
