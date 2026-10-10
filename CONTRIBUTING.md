# Contributing to CD

The distributable source lives in `skills/cd`. Edit it here, then update any installed copy deliberately. Keep `README.md` and `README.ru.md` aligned when changing installation, requirements, or user-facing behavior.

## Local checks

Use Python 3.11+ and Git. No third-party Python packages are required for the runner or its tests.

```bash
python -B -m unittest discover -s skills/cd/tests -v
python -B skills/cd/scripts/run_agent.py --help
git diff --check
```

If the built-in `skill-creator` validator is available in your Codex installation, run it against `skills/cd` as well:

```text
python -B -X utf8 <skill-creator>/scripts/quick_validate.py skills/cd
```

That validator has its own dependencies; it is not a runtime dependency of CD. Check all relative Markdown links and parse `agents/openai.yaml` and `scripts/agent-report.schema.json` after editing them.

## Behavioral changes

For an executor bug, add a focused failing regression test before changing the implementation. Preserve fresh contexts, permission boundaries, snapshot binding, process ownership, and the single global five-cycle budget. Keep model selection in the user's environment.

Tests use a fake CLI and temporary workspaces created inside the test directory. They do not perform a real model review. Changes to delegation or recovery also need the live checks described in [runtime-recovery.md](skills/cd/references/runtime-recovery.md#validate-changes-to-this-mechanism), within an authorized fixture. Record the OS, Python and CLI versions, commands, results, and any checks that could not run. Do not present mock coverage as a live integration pass.

For documentation-only or packaging changes, inspect the relevant documents, validate the skill, and smoke-test installation into an isolated destination. Do not run a paid multi-agent review merely to validate wording.

For changes to progress instructions, walk through the simulated timelines in [progress-reporting.md](skills/cd/references/progress-reporting.md#scenario-checks-for-changes-to-this-protocol). Cover the two-hour boundary, unchanged progress, recovery, invalidated acceptance, review-only counts, uncertain ETA, completion, and an executor holding the ledger lock. Keep this evidence distinct from a live two-hour chat-delivery test; the Python executor tests do not validate coordinator message timing.

## Packaging and releases

- Keep every runtime reference inside `skills/cd`; folder-only installation must remain self-contained.
- Preserve `policy.allow_implicit_invocation: false` unless an intentional product change calls for a different invocation policy.
- Keep the root `LICENSE` and `skills/cd/LICENSE` identical so the MIT notice accompanies both repository and skill-only distributions.
- Exclude local review ledgers, request packets, reports, environment files, credentials, caches, and temporary test outputs.
- Before publication, review the exact staged diff and run the relevant checks. Check the branch and working-tree state before committing and pushing.
- Use a version tag for a reproducible release. Installation URLs may use that tag or a full commit SHA instead of `main`.
- A release archive for manual skill installation should contain one top-level `cd/` directory, including its license and all runtime files.

Report defects through [GitHub Issues](https://github.com/GeorgVahi/CD/issues). Include a minimal reproduction and redacted diagnostics; do not attach private repository data, authentication files, or raw model transcripts.
