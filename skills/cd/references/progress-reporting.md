# Overall progress reporting

The coordinator sends these summaries in the same user chat, in the user's language. Workers return evidence to the coordinator; they do not independently send scheduled user summaries. The rule applies during decomposition, review, repair, validation, publication, and recovery while the invocation is active.

## Timer and durable state

Use the actual clock from an available time tool or the host clock. Store UTC timestamps with an explicit timezone, and use the user's timezone for displayed clock times. Do not infer elapsed time from token counts, the number of tool calls, or a stale date in the prompt.

At invocation start, create `progress.json` beside `ledger.json` in the existing local run directory. For example:

```json
{
  "schema_version": 1,
  "run_id": "review-20261010",
  "started_at": "2026-10-10T08:00:00Z",
  "last_report_at": null,
  "next_report_due_at": "2026-10-10T10:00:00Z",
  "last_report_counts": null
}
```

The first report is due at `started_at + 7200 seconds`. A report is due when `now >= next_report_due_at`. After actually sending an overall summary, atomically save its send time as `last_report_at`, its counts as `last_report_counts`, and set `next_report_due_at` to that send time plus 7200 seconds. Preparing a draft, receiving a worker result, or sending a brief activity update does not advance the timer. An earlier full summary requested by the user can count if it contains the same overall information.

Only the coordinator writes this file. Keep it separate from the executor-owned ledger so reporting can continue while a CLI worker holds `executor.lock`. This does not relax the ledger's locking rules. Use the latest consistent ledger and assignment receipts as evidence; do not modify them merely to send a report. Keep progress state and chat summaries out of fresh reviewers' task packets because they may expose previous review outcomes.

Before dispatch, after every tool return, and after each wait, check whether a report is due. Wait or poll in intervals of at most 60 seconds, or less if the reporting deadline is nearer; retain stricter host limits. For a long CLI command, use the host's yielded process/session handle and bounded waits instead of blocking the coordinator until the command exits. Do not stop or duplicate a worker merely to report. If a tool unexpectedly prevents timely reporting, send the overdue summary on regaining control and acknowledge the delay.

On compaction, chat resumption, or executor recovery, reuse the same run ID and progress file. A new repair cycle or executor does not start a new reporting clock. If the deadline passed while the coordinator was unavailable, send **one** current summary on resuming, then start the next two-hour interval from its actual send time. If delivery happened just before a crash but the state write did not, reconcile with the visible chat before resending. When upgrading a run that has no progress file, recover the start time and last full summary from reliable receipts or chat history. If timing cannot be recovered, send a current summary immediately and initialize the next deadline from now; keep an unknown `started_at` as `null` rather than fabricating elapsed time.

Stop periodic reporting when the invocation completes, is cancelled, is explicitly paused, or ends with a blocker. Send the final result or actionable blocker immediately. If completion coincides with a deadline, the final report replaces the periodic summary. For a resumed paused run, retain its state and apply the overdue-report rule. The skill does not itself wake a closed or inactive chat; report any resulting gap on resumption. This workflow does not create a separate scheduled automation or another chat.

## Counts and useful content

Reconcile known snapshot invalidations before reporting. Use the current task ledger, not the number of finished agent processes or repair attempts.

- **Repair mode:** `total` is the number of in-scope subtasks; `complete` counts only subtasks currently accepted through the full gate; `remaining = total - complete`. Pending work, ongoing reviews/fixes, blocked, exhausted, or unreconciled tasks remain in that remainder. Reopened tasks leave the completed count; explain the decrease or any scope change.
- **Review-only mode:** report `reviewed / total`, `remaining to review`, and separately how many meet the acceptance gate or have findings. A valid, current independent review with defects still counts as reviewed. Failed, incomplete, stale, or insufficient reviews do not. Do not describe a reviewed task with defects as fixed or accepted.
- **Before decomposition is complete:** say the total is not yet established and name the current stage. Do not display a synthetic `0/0`, completion percentage, or task-based ETA.

Each concise summary contains the counts, the current activity and repair cycle `N/5` (or initial review / review-only), progress since the previous summary, and blockers with their effect or required user action. Include an estimated time remaining to this invocation's final result when supportable. With no completed tasks in the interval, still report what is running, how long it has been running if known, and why it has not yielded a result. If nothing is actionable, finish with the blocker instead of keeping an idle run alive for notifications.

Estimate a **range** from observed end-to-end timings for comparable subtasks, remaining complexity, effective concurrency, and outstanding verification/publication. Distinguish time to the next result from time to finishing the run. State assumptions briefly. Do not sum parallel worker durations as elapsed time, extrapolate from the five-cycle limit, or imply that the 9.5 target is guaranteed. When tasks vary too much, have reopened, depend on an unresolved blocker, or there is too little timing evidence, say that a reliable overall ETA is not yet available and explain what will make it estimable. Do not replace an unknown ETA with an invented number.

Example repair summary (illustrative counts and timing only):

> CD: принято 6 из 10 задач, осталось 4. Сейчас идёт проверка двух исправлений, цикл 2/5. За последние два часа приняты 3 задачи; блокеров нет. Ориентировочно осталось 1–2 часа при текущем темпе, если проверка не выявит новых дефектов.

Example review-only summary:

> CD, только ревью: проверено 6 из 10 задач, осталось проверить 4. Из проверенных 4 соответствуют критериям приёмки, в 2 найдены дефекты. Сейчас проверяется интеграция. Надёжной оценки времени пока нет: оставшиеся задачи существенно сложнее уже проверенных.

## Scenario checks for changes to this protocol

Use a simulated timeline; there is no need to wait two real hours to inspect an instruction change. Check that the coordinator's described actions satisfy these cases, and report this as a protocol walkthrough rather than a live delivery test:

| Scenario | Expected action |
| --- | --- |
| Started at 08:00 UTC; now 09:59:59 / 10:00:00 | No scheduled summary yet / send the first summary, even during decomposition or a running worker. |
| Short activity update at 09:50; no task finishes by 10:00 | The 10:00 summary is still due and reports the unchanged counts and current activity. |
| Summary sent at 10:00; executor switch at 11:00 | Next summary remains due at 12:00. |
| Last summary at 10:00; resume at 15:00 | Send one current summary; next due at 17:00, with no burst of missed messages. |
| 10 tasks; 6 accepted, then one accepted snapshot invalidated | Report 5 complete and 5 remaining; explain the reopened task. |
| Review-only: 6 valid current reviews out of 10; 2 contain defects | Report 6 reviewed, 4 remaining to review, and distinguish the 2 with defects from accepted work. |
| No comparable timings or a blocking dependency | Give no numeric overall ETA; explain the uncertainty and next useful milestone. |
| Completion at 09:30, or completion exactly when a summary is due | Send the final report immediately and stop periodic reporting. |
| A CLI worker holds `executor.lock` when a report is due | Send from consistent evidence and save only coordinator-owned `progress.json`; do not edit the locked ledger. |
