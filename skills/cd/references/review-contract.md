# Independent review and repair contract

## Scoring

Assess the current implementation against its actual requirements and the risks of the change. Score each dimension from zero to its maximum and report the sum, **truncated to one decimal place**, with a concise justification for deductions.

| Dimension | Maximum | Evidence to examine |
| --- | ---: | --- |
| Correctness and requirements | 4.0 | Intended outcomes, invariants, failure cases, unmet requirements |
| Robustness and safety | 2.0 | Applicable input/error handling, concurrency, authorization, resource and data lifecycle |
| Integration and regression risk | 2.0 | Callers, shared contracts, dependencies, compatibility, interactions between changed components |
| Maintainability | 1.0 | Clear ownership, understandable control flow, minimal duplication and unnecessary complexity |
| Verification | 1.0 | Meaningful relevant tests/checks and reproducible evidence covering the changed behavior |

Evaluate only risks relevant to the task. Do not demand unrelated security mechanisms, architecture changes, or arbitrary coverage percentages. Pure prose or cosmetic tasks can use inspection/rendering as appropriate verification. Give no bonus for code volume, test count, or agreement with a previous reviewer. Do not deduct points solely for personal style preferences. Every material deduction needs an observed defect or a concrete uncertainty and a useful next check.

Use the following priorities and total-score caps:

- **P0:** Critical, immediate failure such as demonstrated severe data loss or exposure; score at most **3.0**.
- **P1:** Serious correctness, security, or core-path breakage requiring prompt correction; score at most **6.0**.
- **P2:** A concrete normal-priority bug, unmet requirement, or meaningful regression risk; score at most **9.0**.
- **P3:** Minor, nonblocking improvement; can coexist with **9.5 or higher**.
- A required check that failed or could not run, or a material unknown, caps a provisional score at **9.4**, even without a confirmed bug. If the code cannot be inspected at all, return **unscored/blocked**, not a fabricated zero or ten.

Apply the most restrictive cap after calculating the sum. A high score needs positive evidence and adequate confidence. "No findings" alone does not prove 9.5. Separate confirmed defects from questions and optional suggestions. A low score is a valid result; never alter it because a target would otherwise be missed.

## Reviewer handoff

The coordinator fills the following factual packet for each newly spawned reviewer. Provide this contract and the acceptance criteria; omit earlier total/dimension scores, score changes, acceptance/rejection verdicts, findings, repair narratives, and intended conclusions. Apply the same rule to verification, resumed workflow dispatches, and follow-up clarifications. Supply current requirements, source, and check evidence directly, not a previous review report with only its numeric score removed.

The same packet applies to native and CLI workers. A CLI worker's `report` field contains the structured review below; the transport envelope's `status: completed` only means the assignment finished, never that the quality gate passed. Never expose the coordinator ledger or earlier report files as reviewer context. For a CLI reviewer, the coordinator runs checks that require writes and supplies factual commands/results with their snapshot; the reviewer distinguishes those from checks it ran itself.

```text
Role: independent read-only reviewer; do not delegate further or run repair loops.
Run ID, assignment ID, executor, global cycle, fresh-context mechanism:
Repository root and instruction paths:
Task ID, intended behavior, acceptance criteria:
Implementation paths, comparison base/changed hunks, current snapshot:
Relevant callers, tests, dependencies, shared contracts:
Required checks and local execution constraints:
Review the current files independently. Do not edit tracked source or publish.
Return the structured review below. Do not consult prior review reports.
```

The reviewer returns:

1. Task ID and actual reviewed snapshot; paths and contracts examined.
2. Findings with stable IDs, P0–P3 priority, file/line, trigger, observed consequence, and reproduction or code evidence. Distinguish defects introduced by this work from unrelated existing issues.
3. Acceptance criteria met or unmet; relevant boundary and integration cases checked.
4. Dimension scores, any cap, final score `/10`, and confidence (`high`, `medium`, `low`) with reasons.
5. Actual commands run and their results. Separate checks it ran from supplied evidence; unavailable, failed, and timed-out checks are never passing checks. Avoid running a destructive/integration check against a live external system.
6. An explicit material-defect assessment: `confirmed` with IDs of unresolved P0–P2 findings, `none-confirmed` when the completed inspection found none, or `undetermined` when inspection is insufficient. List remaining material unknowns separately; `none-confirmed` does not certify the absence of undiscovered bugs or clear a required check that did not pass.
7. Optional P3 suggestions and a recommendation (`accept`, `needs-fix`, `blocked`). Confirmed unresolved P0–P2 defects require `needs-fix` regardless of score; material uncertainty or insufficient inspection prevents acceptance. The coordinator independently enforces the full acceptance gate, including current checks and closure evidence for previously confirmed findings.

## Fixer handoff

```text
Role: fresh repair agent; do not delegate further or award a review score.
Run ID, assignment ID, executor, fresh-context mechanism:
Repository root and applicable instruction paths:
Task ID, intended behavior, acceptance criteria, current global cycle / 5:
Current snapshot and explicit authorized write paths/contracts:
Findings with reproductions and validation evidence:
Relevant dependencies, tests, required validation:
You are not alone in this workspace. Preserve unrelated/user/other-agent edits.
Fix supported findings in the owner layer within this assignment's scope.
Ask the coordinator before expanding ownership. Do not commit or push.
Return: changed files, finding-to-fix mapping, before/after check results,
unresolved/disputed findings with evidence, and contracts/tasks affected.
```

A fixer may reject a finding with reproducible evidence rather than making a harmful change. The next independent reviewer determines the current quality. If the same snapshot and evidence recur with no actionable fix, report the blocker instead of spending remaining cycles trying to obtain a friendlier score.

After an interrupted fixer, the coordinator first checks its process is stopped and reconciles the actual diff against the receipt. A new independent review may assess partial work. Another repair assignment, if needed, belongs to the next global cycle; switching runtimes cannot reset the attempt counter.
