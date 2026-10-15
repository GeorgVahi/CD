# Contributing to CD

The distributable source lives in `skills/loop-code-review`. Edit it here, then update any installed copy deliberately. Keep `README.md` and `README.ru.md` aligned when changing installation, requirements, or user-facing behavior.

The skill has two host branches. The Codex branch is SKILL.md plus `references/runtime-recovery.md`; the Claude Code branch adds `references/claude-code.md`, which replaces only the Codex-specific mechanism. Keep shared rules (scope, review contract, acceptance gate, five-cycle budget, ledger, progress reporting) in the shared files, and change one branch without silently changing the other.

## Local checks

Use Python 3.9+ and Git. No third-party Python packages are required for the runner or its tests. On Windows, use `python` instead of `python3`.

```bash
python3 -B -m unittest discover -s skills/loop-code-review/tests -v
python3 -B skills/loop-code-review/scripts/run_agent.py --help
git diff --check
```

`tests/test_skill_metadata.py` checks the frontmatter, the explicit-only settings for both hosts, relative Markdown links, and the identical licenses.

If the built-in `skill-creator` validator is available in your Codex installation, you can also run it against `skills/loop-code-review`:

```text
python3 -B -X utf8 <skill-creator>/scripts/quick_validate.py skills/loop-code-review
```

That validator has its own dependencies; it is not a runtime dependency of CD. It reports `disable-model-invocation` as an unexpected key. This is a known, intentional difference: Claude Code needs that key for explicit-only invocation. Treat any other validator finding as a real problem. Parse `agents/openai.yaml` and `scripts/agent-report.schema.json` after editing them.

## Behavioral changes

For an executor bug, add a focused failing regression test before changing the implementation. Codex behavior is covered by `tests/test_run_agent.py`, Claude Code behavior by `tests/test_run_agent_claude.py`. A request without `host` must keep producing the original Codex command. Preserve fresh contexts, permission boundaries, snapshot binding, process ownership, and the single global five-cycle budget shared by both hosts. Keep model selection in the user's environment.

Tests use fake CLIs and temporary workspaces created inside the test directory. They do not perform a real model review. Changes to delegation or recovery also need the live checks described in [runtime-recovery.md](skills/loop-code-review/references/runtime-recovery.md#validate-changes-to-this-mechanism) for Codex and in [claude-code.md](skills/loop-code-review/references/claude-code.md#validate-changes-to-this-branch) for Claude Code, within an authorized fixture. Record the OS, Python and CLI versions, commands, results, and any checks that could not run. Do not present mock coverage as a live integration pass.

For documentation-only or packaging changes, inspect the relevant documents, validate the skill, and smoke-test installation into an isolated destination. Do not run a paid multi-agent review merely to validate wording.

For changes to progress instructions, walk through the simulated timelines in [progress-reporting.md](skills/loop-code-review/references/progress-reporting.md#scenario-checks-for-changes-to-this-protocol). Cover the two-hour boundary, unchanged progress, recovery, invalidated acceptance, review-only counts, uncertain ETA, completion, and an executor holding the ledger lock. Keep this evidence distinct from a live two-hour chat-delivery test; the Python executor tests do not validate coordinator message timing.

## Packaging and releases

- Keep every runtime reference inside `skills/loop-code-review`; folder-only installation must remain self-contained.
- Keep the skill `name` equal to its folder name.
- Preserve `policy.allow_implicit_invocation: false` in `agents/openai.yaml` and `disable-model-invocation: true` in SKILL.md unless an intentional product change calls for a different invocation policy.
- Keep the root `LICENSE` and `skills/loop-code-review/LICENSE` identical so the MIT notice accompanies both repository and skill-only distributions.
- Exclude local review ledgers, request packets, reports, environment files, credentials, caches, and temporary test outputs.
- Before publication, review the exact staged diff and run the relevant checks. Check the branch and working-tree state before committing and pushing.
- Use a version tag for a reproducible release. Installation URLs may use that tag or a full commit SHA instead of `main`.
- A release archive for manual skill installation should contain one top-level `loop-code-review/` directory, including its license and all runtime files.

Report defects through [GitHub Issues](https://github.com/GeorgVahi/CD/issues). Include a minimal reproduction and redacted diagnostics; do not attach private repository data, authentication files, or raw model transcripts.
