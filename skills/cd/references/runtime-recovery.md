# Runtime selection, recovery, and checkpoints

Read this before the first delegation and when a worker fails. Recovery changes the execution mechanism, not scope, permissions, model, clean-context requirements, or the five-cycle limit.

## Select and release native workers

1. Inspect the actual tool catalog, its slot limits, and the current agent list. Account for the root, existing workers, and completed-but-open workers according to the host's semantics. Do not infer that `completed` releases capacity.
2. If a genuine close tool exists, persist a finished worker's report, close only workers owned by this review, and verify the lifecycle operation succeeded. `interrupt`, `wait`, archiving a sidebar chat, and sending a new message are not substitutes for closing or resetting an agent.
3. Use fresh native workers when that lifecycle supports the remaining work. Do not spend a slot on a capacity probe. If close is absent, completed slots are retained, or a fresh native context is unavailable, prefer the CLI executor from the outset or switch to it at the first confirmed capacity error.
4. If all slots are merely running, wait for owned assignments and preserve results. Retry a native spawn at most once after an actual capacity change; do not issue repeated identical rejected spawns. A second capacity failure selects CLI for the rest of this run.
5. Let active native assignments settle before switching or writing. Never stop unrelated agents. Keep total active work within the host's stated concurrency limit; CLI is a different lifecycle, not extra parallel capacity.

## Discover a usable CLI without changing the installation

- Inspect the installed binary and `codex exec --help`. The executor needs `--json`, `--ephemeral`, `--sandbox`, `--output-schema`, `--output-last-message`, and stdin prompts.
- PATH can point to an older installation than the desktop app. On Windows, `Get-Command codex` and `Get-Process -Name codex | Select-Object -ExpandProperty Path -Unique` can identify the PATH binary and the active app's installed binary. On other hosts use their supported process/runtime discovery. Verify candidate paths and `--version`; never hard-code a machine-specific path in this skill.
- If the server reports that the configured model requires a newer Codex version, use another **already installed** compatible binary discovered above through the request's `cli_path`. Do not upgrade/install software, alter PATH/config.toml, or silently choose a different model. Record this as `cli_incompatible`, not a quota failure.
- The fresh invocation uses ordinary user/project configuration and rules. Pass verified current model/reasoning overrides only when they differ from configured defaults. Preserve applicable provider, profile, environment, and effective permission constraints. If those cannot be represented by this runner, do not launch it under broader or different settings.
- Reviewer/decomposer assignments use read-only; fixers may use workspace-write only within already authorized scope. The runner disallows unrestricted sandboxing and runs with noninteractive approvals disabled. It does not bypass hooks, rules, authentication, or quota. Live runtime restrictions can be stricter than saved config; the coordinator must account for them before launch.
- Do not use `resume`, `fork`, another chat's transcript, or a reused provider conversation. `--ephemeral` controls rollout persistence; **a new `exec` invocation without resume/fork** supplies the new conversation.

## Durable run state

Use a unique run directory inside the current workspace's existing ignored local-artifact location, e.g. `.local/code-review/runs/<run-id>/`. This storage path remains compatible with runs created before the skill was renamed to CD. Do not alter `.gitignore` merely to run a review. For non-Git workspaces, use a local task directory. Reuse the same directory/run ID for recovery; distinguish an explicit new review request from resuming an incomplete run.

`ledger.json` has this shared coordinator/executor shape:

```json
{
  "schema_version": 1,
  "run_id": "review-20261005",
  "current_cycle": 0,
  "tasks": {},
  "assignments": {}
}
```

The coordinator maintains `tasks`: scope/base, dependencies, snapshots, scores, findings, checks, status, last repair cycle. Assignments have unique stable IDs, task ID, role, cycle, executor, input hash, start/end status, process/session identity, before/after snapshots, and results. The CLI runner records its own assignments; record native assignments in the same ledger with `backend: native` and `repair_started` when a fixer actually begins. Do not overwrite executor entries. Write state atomically only while no executor holds `executor.lock`.

On migration from an older checkpoint, preserve its original run identity, task IDs, scores, snapshots, and `globalRepairCycle` as `current_cycle`. Convert task lists to an ID-keyed map. Keep the old checkpoint until migration is verified. Do not reset an interrupted review to cycle zero.

Before dispatch, record the packet and exact source/dependency/test fingerprints. Before using a saved result, compare the fingerprints with current files and invalidate affected dependents. Do not credit scores from changed files. Successful transport alone never meets the 9.5 gate.

## Run one CLI assignment

Prepare a UTF-8 JSON request in the run directory. Example shape (replace the example fingerprint with the actual SHA-256):

```json
{
  "run_id": "review-20261005",
  "assignment_id": "r1-initial",
  "task_id": "R1",
  "role": "reviewer",
  "cycle": 0,
  "workspace": "<absolute-workspace-root>",
  "prompt": "<factual role packet and review contract; no prior conclusions>",
  "scope_paths": ["src/contract.js"],
  "expected_snapshot": {"src/contract.js": "<64-character-sha256>"},
  "write_paths": [],
  "sandbox": "read-only",
  "timeout_seconds": 900
}
```

Optional fields: `cli_path` (absolute path to a discovered installed Codex binary), `model`, `reasoning_effort`. Omit model/effort to retain saved defaults when those match the current task. Roles are `decomposer`, `reviewer`, `fixer`; a fixer requires cycle 1–5, explicit `write_paths`, and `sandbox: workspace-write`. Use normalized workspace-relative file paths; `null` fingerprints represent not-yet-existing files. Scope must include relevant instructions, implementation, dependencies, and tests, and every authorized write path. Keep reports, prompts, and ledger out of reviewer scope.

Run with the host's available Python 3.11+ executable, substituting absolute paths:

```text
python -B <skill>/scripts/run_agent.py --request <run-dir>/request.json --state-dir <run-dir>
```

The runner executes an argument array without a shell, sends the prompt through stdin, binds results to actual file fingerprints, and records the CLI session ID. A repeated session ID for another assignment is rejected. Its report schema is [agent-report.schema.json](../scripts/agent-report.schema.json). Output `completed` means a valid assignment report arrived; the coordinator must still inspect the findings, checks, and score. Any other status exits nonzero. Raw CLI tool logs are not printed or retained by the runner; reports must not contain secrets.

Default to one CLI assignment at a time. Wait in short tool intervals and continue user-facing updates while it runs. A lock blocks simultaneous use of the same run directory. Tests and builds requiring shared generated output also need serialization.

## Recovery decisions

| Condition | Action |
| --- | --- |
| Native `agent thread limit reached` | Persist existing results; release owned agents with a real close tool if possible, otherwise switch to fresh CLI workers. |
| CLI incompatible with the configured model | Check the active app's installed binary, verify its version, and retry once with a new attempt ID and unchanged task/cycle. |
| CLI missing | Discover installed alternatives; do not install one automatically. Preserve checkpoint if unavailable. |
| Authentication, permission denial, or account quota | Stop that path with a precise blocker. Never rotate accounts/models/executors to evade it. Continue independent work only if authorized and unaffected. |
| Temporary rate/network error before a repair turn starts | Respect retry hints, make at most one bounded retry, and retain task/cycle. Do not retry identical errors indefinitely. |
| Timeout, cancellation, malformed report, or incomplete process | Stop the owned process tree. The runner contains Windows workers in a job established before CLI launch, or a separate POSIX process group, and cleans up surviving descendants even when CLI already exited. Inspect receipt and actual diff; do not interpret exit/output as successful review. |
| Process containment unavailable | Preserve state and report the host limitation; do not disable process ownership controls to continue. |
| Changed files during a review | Invalidate its score and affected dependents; prepare a new snapshot after writes settle. |
| Partial fixer or changes outside its ownership | Set `needs-reconciliation`, preserve edits, establish provenance, and review actual state before scheduling another writer. Never auto-reset/stash or roll back others' changes. |

An identical completed request returns the saved result without re-execution, unless its snapshot is stale. A different request cannot reuse that assignment ID. A failed attempt is not silently replayed: use a new attempt ID only after the recovery decision is recorded. Failed creation before any repair activity consumes zero cycles. A started or partially applied repair counts in its cycle; a second repair for that task requires the next global cycle. Fixers after cycle five are rejected.

After a runner crash, its `prepared`/`running` receipt or leftover lock is a recovery condition. Verify the recorded runner/child processes have ended, inspect the actual diff, and record the outcome before clearing only that owned stale lock. Do not erase a receipt to enable blind replay. Preserve started repair attempts even if the process died before updating the counter; conservatively reserve that cycle when the evidence cannot rule out work. A new fixer is blocked while any assignment remains unresolved; after reconciliation, preserve its terminal outcome and record `reconciliation: {"status": "resolved", "evidence": "<process/diff/check evidence>"}`. If repair work occurred, preserve `repair_started: true` and advance `current_cycle` as needed before continuing.

If neither path can provide a fresh context, keep the checkpoint and report the specific blocker. Do not relabel an old agent as fresh, reset the cycle budget, or turn a transport failure into a code-quality score.

## Validate changes to this mechanism

Run `python -B -m unittest discover -s <skill>/tests -v` plus the skill-creator validator. Use an isolated fixture inside the authorized workspace for live tests. Verify native capacity exhaustion with retained completed agents routes to CLI, and a real `review → fix → independent review` sequence uses distinct session IDs. Exercise sequential work for six areas, stale dependency snapshots, five cycles, malformed output, missing/incompatible CLI, quota/auth failures, and timeout after partial edits. Mock subprocess tests do not replace a live CLI check.
