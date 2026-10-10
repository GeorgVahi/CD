# CD

**Independent code review and bounded repair for Codex.**

[Русский](README.ru.md) · [Skill instructions](skills/cd/SKILL.md) · [MIT license](LICENSE)

CD reviews the work implemented in your current chat, splits it into reviewable subtasks, and gives each subtask an independent review. When a review finds defects, a fresh agent makes focused repairs and another fresh reviewer checks the result.

The target is **9.5/10 for every subtask**, with **at most five repair cycles for the entire invocation**. Passing also requires current checks, a matching file snapshot, and no unresolved material defects. A score is a review judgment, not a guarantee of bug-free code.

## Install from GitHub

In Codex, send:

```text
$skill-installer install the skill from https://github.com/GeorgVahi/CD/tree/main/skills/cd
```

The installable folder is `skills/cd`, not the repository root. Install the whole folder so that references, the report schema, and the CLI helper remain together. If the skill does not appear after installation, restart Codex. The built-in installer supports GitHub repositories; see the [official skills documentation](https://learn.chatgpt.com/docs/build-skills#install-curated-skills-for-local-use).

For a fixed version, use a published tag or commit in place of `main` in the URL.

### Manual installation

Clone this repository, then copy `skills/cd` into your personal skills directory. These commands use the [documented local skills location](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) and stop if CD is already installed there.

**macOS / Linux (Bash):**

```bash
(
  set -eu
  git clone https://github.com/GeorgVahi/CD.git
  destination="$HOME/.agents/skills/cd"
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    echo "CD already exists at $destination; preserve local edits before updating." >&2
    exit 1
  fi
  mkdir -p "$HOME/.agents/skills"
  cp -R CD/skills/cd "$destination"
)
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/GeorgVahi/CD.git
if ($LASTEXITCODE -ne 0) { throw 'Clone failed.' }
$skillParent = Join-Path $HOME '.agents/skills'
$destination = Join-Path $skillParent 'cd'
if (Test-Path -LiteralPath $destination) {
    throw "CD already exists at $destination; preserve local edits before updating."
}
New-Item -ItemType Directory -Path $skillParent -Force | Out-Null
Copy-Item -LiteralPath './CD/skills/cd' -Destination $destination -Recurse
```

For a shared repository installation, copy the same folder to `<project>/.agents/skills/cd`. Existing Codex installations or the bundled installer may use `$CODEX_HOME/skills` (usually `~/.codex/skills`); keep using the location your installation manages. Avoid installing multiple copies named `cd` in discovery paths.

## Use

Run CD in the chat where the implementation happened:

```text
$cd
```

Limit the scope when needed:

```text
$cd Review and repair only the authentication changes implemented in this chat.
```

For a review without edits:

```text
$cd Review only. Do not edit files, commit, or push.
```

CD is **explicit-only**. Its metadata disables automatic invocation. Installing it does not register a custom `/cd` command.

## Progress during long runs

While CD is running, the coordinator sends an overall summary in the same chat **every two hours**, starting two hours after invocation. It reports completed and remaining subtasks, current work, the repair cycle, progress since the previous summary, blockers, and an approximate remaining-time range when actual timings support one. If the total or ETA is not yet known, it says so.

In repair mode, only tasks that currently pass the full acceptance gate count as complete. Review-only summaries distinguish finished reviews from accepted work. Reports still arrive when no task has finished; shorter activity updates do not postpone the two-hour summary.

The reporting deadline is saved with the run and survives compaction and executor changes. On resumption after an overdue deadline, CD sends one current summary and starts the next interval from that message. Completion and blocking issues that stop the run are reported immediately. Reporting stops when the run finishes or is paused; the skill cannot wake an inactive chat. See the [progress protocol](skills/cd/references/progress-reporting.md) for details.

## What happens

1. The coordinator identifies work attributable to the chat, including committed changes, and records the repository state.
2. One read-only agent decomposes that work into subtasks with acceptance criteria and comparison bases.
3. Each subtask receives a fresh, independent reviewer. Reviewers do not receive previous scores or verdicts.
4. Unresolved subtasks receive focused fixes, followed by new independent reviews. The entire invocation shares a five-cycle repair budget.
5. The coordinator reports scores, fixes, actual checks, blockers, and publication results. It stops when every subtask passes or no authorized, actionable work remains.

Review-only mode stops after the initial reviews. If there is no implemented work attributable to the chat, CD reports that instead of inventing a repository-wide audit.

| Review dimension | Maximum |
| --- | ---: |
| Correctness and requirements | 4.0 |
| Robustness and safety | 2.0 |
| Integration and regression risk | 2.0 |
| Maintainability | 1.0 |
| Verification | 1.0 |

The [review contract](skills/cd/references/review-contract.md) defines severity caps and required evidence. Unresolved P0–P2 defects, unavailable required checks, stale snapshots, or material uncertainty prevent acceptance even if the numeric target is reached.

## Requirements and boundaries

- A Codex environment that can read the workspace and create fresh subagent contexts, or run a compatible installed Codex CLI.
- For the CLI fallback: **Python 3.11+**, an authenticated Codex CLI, and `codex exec` support for `--json`, `--ephemeral`, `--sandbox`, `--output-schema`, `--output-last-message`, and prompts on stdin. The Python helper uses only the standard library.
- Git for Git repository inspection, plus the target project's own validation tools.
- An existing ignored location inside a Git workspace for review checkpoints. CD does not modify the project's `.gitignore` just to run a review.

Native workers are preferred when their lifecycle supports fresh contexts. If completed agents retain capacity and cannot be closed, CD uses new standalone CLI assignments. See [runtime and recovery](skills/cd/references/runtime-recovery.md) for request fields, checkpoints, failure handling, and the runner command.

Invoking CD authorizes task-scoped local repairs subject to project rules and current permissions. It preserves unrelated edits, uses one writer at a time by default, and retains the cycle counter across recovery. It does not grant new commit/push permissions, change your configured model, install or upgrade tools, or bypass account limits. Review-only mode never stages, commits, or pushes.

Each agent assignment consumes normal Codex usage. Five cycles is a stopping limit; CD can finish below the target with an honest report of remaining findings or blockers. Other agent hosts must provide equivalent execution and permission semantics; this package is documented for Codex.

## Update or remove

An installed copy does not update when the GitHub repository changes. Preserve any local edits, update a separate checkout with `git pull --ff-only`, and replace only the installed `cd` folder with the new `skills/cd`. The built-in installer refuses to overwrite an existing destination; it is not an updater.

To remove CD, remove only its installed `cd` folder. Do not remove the containing skills directory or your Codex configuration.

## Repository layout and validation

```text
skills/cd/
├── SKILL.md                       Workflow and acceptance gate
├── LICENSE                        License retained by folder installs
├── agents/openai.yaml             Display metadata and explicit-only policy
├── references/review-contract.md  Scoring and handoff contracts
├── references/runtime-recovery.md Executor selection and recovery
├── references/progress-reporting.md Two-hour summaries and ETA guidance
├── scripts/run_agent.py           One fresh CLI assignment
├── scripts/agent-report.schema.json
└── tests/test_run_agent.py         Executor regression tests
```

Run from the repository root:

```bash
python -B -m unittest discover -s skills/cd/tests -v
python -B skills/cd/scripts/run_agent.py --help
```

The suite uses a fake CLI subprocess, needs no account credentials, and does not spend model usage. It exercises lifecycle, snapshots, recovery, cycle limits, and process cleanup. It does not establish compatibility with every live Codex model or host. See [CONTRIBUTING.md](CONTRIBUTING.md) for validation and release guidance.

## License

[MIT](LICENSE), copyright © 2026 GeorgVahi. The installable folder includes the same license so it travels with the skill.
