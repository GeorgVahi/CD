---
name: cd
description: "Run independent subagent review and repair of work completed in the current chat, with evidence-based 0–10 scores, a 9.5 target, and at most five repair cycles. Use when explicitly invoked as $cd or explicitly requested by name."
---

# CD

Improve the actual code through independent review, not by negotiating a higher score. The default scope is all implemented work attributable to the available context of this chat, including committed changes. A narrower user-specified scope takes precedence.

## Invocation and limits

- Invoke with `$cd`. The host may expose a skill picker; do not claim that installing this folder registers a custom `/cd` slash command.
- This is an explicit-only review **and repair** workflow. Invocation authorizes local, task-scoped fixes and the subagents described below, subject to project instructions and existing permissions. A user request for review without edits overrides repair mode.
- Target: **9.5/10 for each subtask**, not an average across subtasks. Maximum: **five repair cycles in total for this invocation**, not five new cycles every time a task reopens. The initial review and final verification do not grant additional repair cycles.
- Follow the active project's `AGENTS.md`, owner documentation, validation commands, and publication policy. Do not invoke another end-to-end build workflow automatically.
- Use the existing configured model and reasoning settings. Do not pin model names, change global configuration, or install tools to run this skill.

## 0. Select an executor and recover existing progress

Read [references/runtime-recovery.md](references/runtime-recovery.md) before dispatching work. Inspect actual delegation/lifecycle tools and existing agents. A completed turn does **not** prove that its agent slot was released. If the host cannot close agents or completed agents keep occupying slots, use fresh standalone Codex CLI assignments as described there; do not wait for an unavailable lifecycle operation.

The CLI fallback is part of this authorized workflow and runs against the same workspace, with a new context for each assignment. Keep the existing model/settings and applicable permissions; preserve account limits and bounded concurrency. Do not create sidebar chats, reuse an old conversation, or substitute a self-review. If the CLI on PATH is incompatible, look for an already installed compatible binary, including the active desktop app's binary, before reporting a blocker. Never install/update Codex or silently change models as recovery.

Create or recover the local run checkpoint before dispatch. Switching executors, restarting this chat, or recovering a failed process must preserve completed results, task IDs, and the global cycle counter. In-flight or partially written work requires reconciliation before another writer starts.

## Overall progress every two hours

The coordinator must send an overall progress message **in the current user chat every two hours while this invocation is running**, including review-only runs. Start the reporting clock when the invocation begins, before decomposition or worker dispatch. Read [references/progress-reporting.md](references/progress-reporting.md) for the durable timer, counting rules, recovery, and examples. This summary is additional to any more frequent updates required by the host or project; ordinary brief updates do not reset its clock.

Report how many subtasks are complete, how many remain, what is happening now, the repair cycle out of five (or review-only mode), changes since the last summary, blockers, and an approximate remaining-time range when supported by observed progress. Count a subtask as complete in repair mode only while it meets the full acceptance gate on its current snapshot. Clearly distinguish completed reviews from accepted implementations in review-only mode. Never invent a total, percentage, or ETA when evidence is insufficient.

Check the real clock before dispatch and after each tool return or wait; use bounded waits so the coordinator can report while workers are still running. When a summary is due, send it even if no task has completed since the last one. Preserve the timer across compaction and executor switches. On recovery, send one overdue summary rather than a burst of missed updates. Report completion or a blocker that stops the run immediately, without waiting for the next two-hour deadline.

## 1. Establish scope and delegate decomposition

Inspect the current repository state and available conversation before inferring scope. Record the repository root, branch, HEAD, relevant staged/unstaged/untracked paths, and any commits attributable to the chat. Read the applicable project instructions.

Create **exactly one read-only decomposition assignment** for the invocation, using a native subagent or fresh CLI worker. Reuse its saved result when recovering the same run. Give it the available chat context or a faithful factual digest of user requests, implemented tasks, acceptance criteria, changed paths, and attributable commits. A native decomposer may inherit conversation history. Its job is to reconcile that history with current files and divide completed work into cohesive, reviewable subtasks.

Require its output to contain:

- A stable task ID, purpose, acceptance criteria, and current implementation paths for each subtask.
- A verified comparison base or explicit changed hunks/commits. Include committed work even when the working tree is clean; staged/unstaged diffs alone are insufficient.
- Tests, relevant callers/dependencies, and contracts to examine for each subtask.
- Dependencies between subtasks, shared files, and which task owns each shared contract. Give integration between changed components an explicit owner so it cannot fall between reviewers.
- Excluded changes and unresolved scope ambiguities.

Preserve unrelated user changes. Never assume every dirty file, the last commit, or the entire branch belongs to this chat. When the history was compacted, use the reliable summary and disk evidence; do not invent missing tasks. Ask a concise scope question only if the intended work cannot be identified safely. If no implemented work is attributable to this chat, report that and finish without a repository-wide audit or a synthetic score.

Keep the durable coordinator ledger described in runtime-recovery: `task ID | paths/contracts | reviewed snapshot | score/confidence | findings | checks | status | last repair cycle`, plus executor and assignment receipts. Track the single global cycle counter and preserve it through compaction. Task statuses: `pending`, `needs-fix`, `accepted`, `blocked`, `needs-reconciliation`, `exhausted`. A score is evidence about a particular snapshot, not a permanent property of a task.

## 2. Spawn independent initial reviewers

Read [references/review-contract.md](references/review-contract.md) for the scoring rubric and agent handoff contracts. Give each subtask its **own new read-only reviewer**.

For **every reviewer and fixer**, create a new execution context with no inherited conversation: a native fresh subagent or a new `codex exec` assignment through [scripts/run_agent.py](scripts/run_agent.py). With `collaboration.spawn_agent`, explicitly set `fork_turns: "none"`; with other delegation tools use their documented fresh-context equivalent. Omitting this setting may inherit the whole conversation. CLI workers must not use `resume` or `fork`. Do not reuse an old context for another task, role, cycle, or verification; follow-up messages may clarify only a still-open native assignment. A new process using an old conversation is not a fresh context.

Each reviewer receives only the factual task packet: repository/instruction paths, acceptance criteria, exact scope and comparison base, current snapshot, dependencies, permitted checks, and the review contract. Keep previous total and dimension scores, score changes, prior acceptance/rejection verdicts, reviewer conclusions, and the implementer's justification out of this packet. This applies to initial reviews, verification, reopened tasks, recovery, and follow-up clarifications. Repository instructions and necessary source code are allowed context; previous chat reasoning is not. Ask reviewers to avoid reading coordinator logs or previous review reports.

Before dispatch, check the actual prompt and supplied files for review history; build the packet from current requirements and source/check evidence rather than forwarding a previous report. Retain historical scores and verdicts in coordinator state, outside reviewer-facing context; a reviewer must produce its own 0–10 assessment. If earlier review scores are accidentally exposed, that context cannot establish acceptance: obtain a new independent review without the leaked history. This replacement review grants no additional repair cycle.

Record a snapshot sufficient to identify the **actual files on disk**: HEAD plus content fingerprints of scoped implementation, relevant dependency, configuration, and test files, including untracked files and deletions. HEAD alone cannot identify uncommitted changes. Bind the review and its check results to this snapshot. If relevant files change while it is running, the result is stale and cannot establish acceptance.

Reviewers inspect implementation and relevant callers/tests beyond the changed lines, looking for missed requirements, regressions, edge cases, and integration failures. They must not edit source, update snapshots, accept generated changes, commit, or push. Tests that write build/cache artifacts are allowed only in appropriate local/ignored locations and must not race on shared outputs.

Parallelize native read-only reviewers only within available slots and safe test resources; default CLI execution to one assignment at a time. Wait for the review wave to finish before allowing fixes. Save results before closing native agents with an actual close tool, when available. On a capacity failure, follow runtime-recovery immediately; batching alone cannot release retained completed agents. Report a fresh-context blocker only after checking the available native and CLI paths. Do not bypass account quotas, authorization failures, or permission denials by changing execution paths.

## 3. Run at most five repair cycles

The sequence is `initial independent review → [fresh fixer → fresh independent review] × at most 5`. Every bracket is one global repair cycle; each unresolved subtask can receive at most one repair assignment in that cycle. A verification review that fails supplies the findings for the next cycle, so no redundant opening review is needed for an unchanged snapshot.

After the initial reviews, accept tasks only if they satisfy the acceptance gate below. If all tasks pass, finish immediately. Otherwise, for cycles **1 through 5**:

1. Skip accepted subtasks whose reviewed code, dependencies, contracts, and required checks are still current. Keep blocked tasks visible and continue independent work where possible.
2. For every actionable unresolved subtask, create a **new fresh-context fixer**. Give it the factual packet, concrete findings, authorized write scope, and reproduction/validation evidence. It may see the previous review; it cannot award the next score. One assignment may contain several related fixes, but do not launch repeated fixers for the same task within one cycle.
3. Fixers make the smallest coherent corrections in the owner layer and run the relevant checks. For behavior bugs, establish the narrowest practical failing signal before changing behavior, then show it passing. Documentation or cosmetic corrections need no ceremonial failing test. Do not weaken tests, suppress diagnostics, remove requirements, or invent work to chase points.
4. Default to **one active writer for the shared working tree**. Tell every fixer it is not alone, must preserve others' changes, and must stay inside its explicit ownership. Serialize fixes to shared files, dependencies, generated outputs, and contracts. If ownership must expand, the coordinator assigns the affected work before writing. Do not create external worktrees or project copies to run the loop.
5. Collect the changed paths, finding dispositions, check results, and fresh snapshots. Invalidate acceptance for any subtask affected by a changed dependency or shared contract, even if its own files are unchanged; set it back to `pending` until independently reviewed again. Do not broaden the product scope to unrelated pre-existing defects.
6. After the writes settle, create **new fresh-context reviewers** for every repaired or invalidated subtask. Give them the current factual packets and rubric, without previous scores or fixers' claims. Run the required integration checks on the combined state. Record the independent scores and evidence.
7. Accept qualifying subtasks; retain actionable findings for the next cycle. Stop when every subtask is accepted or no authorized, actionable work remains. An unresolved material product choice, unavailable required environment, or tool failure is a blocker, not a reason to invent a pass or repeat identical checks five times.

Record transport failures separately from review results. A failed spawn or rejected CLI request before repair work starts consumes no repair cycle. A fixer that starts and then times out may already have edited files: preserve its changes, count that repair attempt, and reconcile before any retry. Never allocate a second fixer to the same task in the same cycle merely by changing executor or assignment ID.

After fixes in cycle 5, perform the same independent verification and then **stop editing**. Mark unresolved tasks `exhausted` or `blocked`, report their actual scores and next actions. There is no sixth fixer, hidden cleanup cycle, or automatic restart under a new task ID. If the final verification finds a new problem, report it within the same limit.

In review-only mode, perform decomposition and the initial reviews, report results, and stop without launching fixers. This invocation must not stage, commit, or push changes.

## Acceptance gate

Accept a subtask only when all of these hold:

- Its latest independent score is **at least 9.5/10**, backed by the rubric.
- The reviewer explicitly reports no confirmed unresolved material defects (P0, P1, or P2), the coordinator's finding register has no open P0–P2 defects, and relevant acceptance criteria are met. A high score never overrides an open material defect.
- Required task checks passed on the reviewed state; no required check is failed, timed out, or unavailable. Optional omitted checks are explained.
- There is no material unresolved uncertainty about scope, behavior, or a touched contract.
- Its snapshot is still current, including dependencies, and applicable checks of the combined implementation passed.

Carry confirmed material findings across cycles in coordinator state, without revealing the earlier reviews or scores to the next reviewer. Close a finding only after the coordinator verifies evidence on the current snapshot: a focused check demonstrates the correction, or reproducible/code evidence establishes that the finding was mistaken. A fixer's claim or omission from the next review is not closure. Disputed or unverified material findings remain open and block acceptance; unrelated pre-existing findings remain separately recorded outside task scope. Perform these targeted checks separately from the new reviewer's independent assessment.

If a report omits required evidence or violates the scoring rubric, request a factual correction from that reviewer within its current assignment. Until corrected, do not accept it; do not negotiate a higher score or silently repair the reported score yourself.

Do not average different reviews, round 9.45 into a pass, or upgrade a score yourself after a fixer reports success. A reviewer may honestly conclude 10/10 when supported; reaching 9.5 is enough to stop. The score is a calibrated review judgment, not proof that the code has no bugs.

## Completion and publication

Review the final task-owned diff and confirm the final ledger still matches the files. If final checks invalidate a result, reopen the affected task within the remaining global cycles; if five are already used, report it without further fixes. Do not make unchecked code edits after the last review.

Follow existing commit/push authorization and repository requirements; the skill creates no new permission to publish. Only the coordinator handles Git publication. When required, verify branch and status before each commit/push, isolate task-owned changes, and verify remote synchronization afterward. Do not create commits merely to advance a cycle, publish someone else's dirty changes, or create an empty commit. Report publication failures separately from review results.

Answer in the user's language. Lead with whether all subtasks reached the target and how many repair cycles were used. Provide a compact table: `subtask | initial score → final score | status`. Name the meaningful fixes, actual validation commands/results, any remaining findings or unverified risks, and the commit/push result when applicable. Mention an executor switch and whether it preserved fresh contexts. If there were no changes, say so. Do not call the workflow successful while any task is below the target, stale, blocked, needs reconciliation, or exhausted.
