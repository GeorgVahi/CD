# Claude Code host

Read this after [Host selection](../SKILL.md#host-selection) identifies Claude Code. It maps the Codex-specific mechanism in SKILL.md and [runtime-recovery.md](runtime-recovery.md) to Claude Code. Everything not named here applies unchanged: scope, decomposition, the ledger and checkpoints, snapshots, the [review contract](review-contract.md), the acceptance gate, the single five-cycle budget, recovery bookkeeping, [progress reporting](progress-reporting.md), publication, and the final report.

## Invocation and project instructions

- Invoke with `/loop-code-review`. Text after the command is the user's scope or mode, for example `/loop-code-review review only`. In Claude Code, installing this folder in a skills directory does register that command; `disable-model-invocation: true` keeps the skill explicit-only. The name avoids shadowing the built-in `/cd` and `/code-review` commands.
- The coordinator runs in the invoking conversation because it needs this chat's history. Do not move the coordinator into a subagent or a forked skill context.
- Where SKILL.md names `AGENTS.md`, follow the project's Claude Code instructions: every applicable `CLAUDE.md`, plus `AGENTS.md` when the project keeps one.
- The skill directory is `${CLAUDE_SKILL_DIR}`; use it wherever the Codex text writes `<skill>`.

## Native workers (preferred)

- Spawn the decomposer, every reviewer, and every fixer with the `Agent` tool and an explicit `subagent_type: "general-purpose"`. A non-fork Agent call starts without the conversation history; this is the Claude Code equivalent of `fork_turns: "none"`.
- The `fork` type inherits the whole conversation. It is never a fresh context: never use it for reviewers or fixers. Because SKILL.md lets the decomposer inherit history, the decomposer may use `fork` when that type is available; otherwise give it a faithful factual digest.
- Do not pass `model` (subagents inherit the session model unless the user configured a default subagent model) and do not pass `isolation: "worktree"`. Side sessions, background or cloud sessions (`claude --bg`, `--cloud`), and the Workflow tool are not substitutes for workers; they are the "sidebar chats" SKILL.md forbids.
- A finished subagent does not hold a concurrency slot and there is no close tool to call; the limit counts running subagents only. The Codex retained-slot problem therefore does not apply. Save each result to the ledger as soon as its notification arrives.
- Continuing a finished agent with `SendMessage` reuses its context. Use it only to request a factual correction within that agent's own assignment, never for another task, role, cycle, or verification.
- Subagents may spawn their own subagents in Claude Code. Every packet already says "do not delegate further"; keep that line.
- Record native assignments in the ledger with `backend: "native"`, `host: "claude"`, the assignment ID, task, role, cycle, the returned agent ID, and `repair_started` once a fixer actually begins.

### Read-only reviewers without an OS sandbox

Native reviewers share the session's permissions; read-only is an instruction, not an OS guarantee. Before dispatching a reviewer, record `git status --porcelain=v1 -uall` and the SHA-256 of every scoped file (`shasum -a 256` on macOS, `sha256sum` on Linux, `Get-FileHash` on Windows). Repeat both after the reviewer returns. Any difference makes that review stale and may need reconciliation before another writer starts. A reviewer runs only checks the session already permits; when a check must write outside ignored locations, the coordinator runs it and supplies the command and result, as for CLI reviewers.

## When to use the Claude CLI executor

The CLI is the fallback, not the default. Use it when the `Agent` tool is unavailable in the coordinator's context, when a spawn fails with `Concurrent subagent limit reached` again after the owned running work settles and one retry, or when the user asks for process-separated workers. Each CLI assignment is a new headless process with a new session ID. Default to one CLI assignment at a time; the CLI does not add parallel capacity.

## Discover the CLI without changing the installation

- In order: `$CLAUDE_CODE_EXECPATH` (the binary running this session, when set), `command -v claude` (Windows: `Get-Command claude`), then the running process (`ps -axo pid,comm`). The desktop app may run a bundled CLI that is not on PATH. Verify a candidate with `<path> --version` and pass its absolute path as `cli_path`. Never hard-code a machine-specific path in this skill.
- Check `<path> --help` for `-p`, `--output-format stream-json`, `--verbose`, `--no-session-persistence`, `--session-id`, `--permission-mode`, `--permission-prompts`, `--json-schema`, `--tools`, and `--disallowedTools`. A missing flag is `cli_incompatible`.
- The desktop app signs its own session in through the app, and a child CLI does not inherit that sign-in. `<path> auth status` reports the standalone state without an API call. With `"loggedIn": false`, the CLI path is blocked until the user signs in themselves with `<path> auth login` (or configures their own API key or `setup-token`); keep using native workers meanwhile.
- Do not install or update Claude Code, alter PATH or settings, or log in on the user's behalf.

## Run one Claude CLI assignment

Use the request format from [runtime-recovery.md](runtime-recovery.md#run-one-cli-assignment) and add `"host": "claude"`. `cli_path` must name a `claude` binary; `reasoning_effort` maps to `--effort`. Run it with Python 3.9+ (`python3` on macOS and Linux):

```text
python3 -B "${CLAUDE_SKILL_DIR}/scripts/run_agent.py" --request <run-dir>/request.json --state-dir <run-dir>
```

Run it with Bash in the background when it may outlast the Bash timeout, and check the reporting clock when it returns. The runner translates the Codex options as follows:

| Codex runner | Claude runner |
| --- | --- |
| `exec`, prompt on stdin | `-p`, prompt on stdin |
| `--json` | `--output-format stream-json --verbose` |
| `--ephemeral`, new `exec` | `--no-session-persistence` plus a new `--session-id`; the `init` event must echo it (`session_mismatch` otherwise) |
| `--sandbox read-only` | `--permission-mode default`, `--tools Read,Grep,Glob,Bash`, `--disallowedTools Edit,Write,NotebookEdit,Agent` |
| `--sandbox workspace-write` | `--permission-mode acceptEdits`, `--disallowedTools Agent` |
| `approval_policy="never"` | `--permission-prompts none`: anything that would prompt is denied |
| `--output-schema`, `--output-last-message` | `--json-schema`; the runner saves `structured_output` from the `result` event as `reports/<assignment>.json` |
| `-C <root>` | the process starts in the workspace root |

The runner never passes `-c`/`--continue` (in Claude Code, `-c` continues an old conversation), `-r`/`--resume`, `--fork-session`, `--bare`, `--safe-mode`, `--restricted`, `--dangerously-skip-permissions`, or the `bypassPermissions` and `auto` modes. Each of these would reuse a context, drop project instructions and hooks, or widen permissions.

The runner removes only the variables that bind a child to the invoking session (`CLAUDECODE`, session IDs, the desktop messaging socket, and similar); provider, authentication, and other user configuration are inherited. If the child still cannot start or authenticate, report that as the CLI path's blocker and keep using native workers.

Bash commands in a CLI worker run only when the user's settings already allow them; everything else is denied and counted in the receipt's `permission_denials`. A required check that was denied could not run: it caps the score at 9.4 unless the coordinator runs it. Commands the user allowed can still write files; the runner's before/after inventory marks such a review stale and such a fixer `scope_drift`.

## Recovery decisions for Claude Code

These rows extend the [runtime-recovery table](runtime-recovery.md#recovery-decisions); the cycle and receipt rules there apply unchanged.

| Condition | Action |
| --- | --- |
| `Concurrent subagent limit reached` | Wait for owned running agents and preserve results. Retry once after one finishes; a second failure selects the CLI for the rest of the run. |
| `Agent` tool unavailable | Use the CLI executor. |
| `nested_session` | The CLI refused to start inside this session despite the removed bindings. Report the host limitation and continue with native workers. |
| `authentication` (`Not logged in`, `Invalid API key`, `authentication_failed`) | Stop that path with a precise blocker. Never switch accounts or log in for the user. Under the desktop app this is expected until the standalone CLI is signed in; the rejection costs no usage and consumes no cycle. |
| `quota` (`You've hit your session/weekly limit`, `billing_error`) | Stop with the blocker, including the reset time if shown. Do not rotate executors to evade it. |
| `rate_limit` or `overloaded` (429/529) | The CLI already retries internally. Allow at most one more bounded retry with a new attempt ID and unchanged task and cycle. |
| `cli_incompatible` (`unknown option`, invalid choice) | Look for another installed `claude` binary, such as the desktop app's, verify its version, and pass it as `cli_path`. Do not update. |
| `session_mismatch` | The CLI did not honor the new session ID. Treat it as a context failure, not a review result. |
| `invalid_report` (including `error_max_structured_output_retries`) | Handle it like a malformed report. |

## Progress reporting

- Read the clock with `date -u +%Y-%m-%dT%H:%M:%SZ`.
- Background agents and background Bash commands wake the coordinator when they finish; check the deadline on every such return.
- If a summary could fall due while all owned work runs in the background with nothing else to wake the coordinator, arm one bounded timer: a background command that sleeps until the deadline, or the host's Monitor tool. Do not busy-poll. When it fires, send the summary if due and re-arm only while owned work is still running. Arm nothing once the run completes, pauses, or blocks.

## Validate changes to this branch

- `python3 -B -m unittest discover -s <skill>/tests -v` runs the Codex and Claude runner tests with fake CLIs and needs no account.
- Live check, which uses account usage and runs only when the user authorizes it: in an isolated fixture inside the authorized workspace, run one CLI reviewer, one CLI fixer, and a fresh CLI reviewer, and confirm distinct session IDs and write-scope drift handling. Separately run a native review → fix → review sequence with distinct agents. Record the Claude Code version, OS, Python version, commands, and results. Mock coverage does not replace this check.
