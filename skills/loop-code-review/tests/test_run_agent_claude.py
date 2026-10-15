"""Behavioral tests for the Claude Code host of the CLI executor (stdlib only)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

SKILL = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("run_agent", SKILL / "scripts/run_agent.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

FAKE = r'''
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
root = pathlib.Path.cwd()
state = root / '.review-state'
count = state / 'calls.txt'
count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')
(state / 'argv.json').write_text(json.dumps(args))
(state / 'prompt.txt').write_text(prompt)
(state / 'env.json').write_text(json.dumps(sorted(k for k in os.environ if k.startswith(('CLAUDE', 'KEEP_')))))
mode = (root / 'mode.txt').read_text()
session = args[args.index('--session-id') + 1]
def emit(**event):
    print(json.dumps(event), flush=True)
def report(changed=()):
    return {'status': 'completed', 'report': 'Reviewed source; no required check omitted.', 'changed_paths': list(changed)}
if mode == 'nested':
    print('Error: Claude Code cannot be launched inside another Claude Code session.', file=sys.stderr)
    sys.exit(1)
if mode == 'incompatible':
    print("error: unknown option '--permission-prompts'", file=sys.stderr)
    sys.exit(1)
if mode == 'orphan':
    subprocess.Popen([sys.executable, '-c', "import pathlib,time;time.sleep(0.7);pathlib.Path('source.py').write_text('orphan mutation')"], cwd=root)
    sys.exit(1)
emit(type='system', subtype='init', session_id='reused' if mode == 'reused' else session)
if mode == 'auth':
    emit(type='assistant', error='authentication_failed', session_id=session,
         message={'content': [{'type': 'text', 'text': 'Not logged in. Please run /login SECRET_SHOULD_NOT_LEAK'}]})
    emit(type='result', subtype='success', is_error=True, result='Not logged in. Please run /login', session_id=session)
    sys.exit(1)
if mode == 'quota':
    emit(type='result', subtype='success', is_error=True, result="You've hit your session limit, resets 3:45pm", session_id=session)
    sys.exit(1)
if mode == 'rate':
    emit(type='system', subtype='api_retry', attempt=1, max_retries=1, retry_delay_ms=1, error_status=429, error='rate_limit')
    emit(type='result', subtype='error_during_execution', is_error=True, errors=['Request rejected (429)'], session_id=session)
    sys.exit(1)
if mode == 'error_exit0':
    emit(type='result', subtype='error_during_execution', is_error=True, errors=['tool crashed'], session_id=session)
    sys.exit(0)
if mode in ('fix', 'timeout', 'outside'):
    emit(type='assistant', session_id=session, message={'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {}}]})
    (root / ('other.py' if mode == 'outside' else 'source.py')).write_text('changed\n')
if mode == 'timeout':
    time.sleep(30)
if mode == 'incomplete':
    sys.exit(0)
if mode == 'malformed':
    emit(type='result', subtype='success', is_error=False, result='not json', session_id=session)
elif mode == 'text_report':
    emit(type='result', subtype='success', is_error=False, result=json.dumps(report()), session_id=session)
elif mode == 'denied':
    emit(type='result', subtype='success', is_error=False, structured_output=report(),
         permission_denials=[{'tool_name': 'Bash'}], session_id=session)
else:
    emit(type='result', subtype='success', is_error=False,
         structured_output=report(['source.py'] if mode == 'fix' else []), session_id=session)
'''

FORBIDDEN_FLAGS = {
    "-c", "--continue", "-r", "--resume", "--fork-session", "--bare", "--safe-mode", "--restricted",
    "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "bypassPermissions",
    "auto", "--bg", "--background", "--cloud", "exec", "--ephemeral", "--sandbox", "-C",
}


class ClaudeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SKILL / "tests")
        self.root = Path(self.temp.name)
        # Non-Git fixtures must not inherit the enclosing skill repository.
        environment = patch.dict(os.environ, {
            "GIT_CEILING_DIRECTORIES": str(self.root.parent),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.state = self.root / ".review-state"
        (self.root / "source.py").write_text("original\n")
        (self.root / "other.py").write_text("other\n")
        (self.root / "mode.txt").write_text("ok")
        (self.root / "fake.py").write_text(FAKE)
        self.command = [sys.executable, str(self.root / "fake.py")]

    def tearDown(self):
        self.temp.cleanup()

    def request(self, role="reviewer", cycle=0, assignment="initial-r1", host="claude"):
        return dict(run_id="test-run", assignment_id=assignment, task_id="R1", host=host,
                    role=role, cycle=cycle, workspace=str(self.root),
                    prompt="Review source.py against the stated requirements.",
                    scope_paths=["source.py", "other.py"],
                    expected_snapshot={p: hashlib.sha256((self.root / p).read_bytes()).hexdigest()
                                       for p in ("source.py", "other.py")},
                    write_paths=["source.py"] if role == "fixer" else [],
                    sandbox="workspace-write" if role == "fixer" else "read-only",
                    timeout_seconds=5)

    def execute(self, request, command=None):
        return runner.run(request, self.state, command=command or self.command)

    def argv(self):
        return json.loads((self.state / "argv.json").read_text())

    def mode(self, value):
        (self.root / "mode.txt").write_text(value)

    def test_reviewer_is_a_fresh_restricted_headless_run(self):
        result = self.execute(self.request())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["host"], "claude")
        argv = self.argv()
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(str(uuid.UUID(argv[argv.index("--session-id") + 1])), result["session_id"])
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "default")
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]),
                         json.loads(runner.SCHEMA.read_text(encoding="utf-8")))
        self.assertEqual(argv[argv.index("--tools") + 1].split(","), ["Read", "Grep", "Glob", "Bash"])
        denied = argv[argv.index("--disallowedTools") + 1].split(",")
        self.assertTrue({"Edit", "Write", "NotebookEdit", "Agent"} <= set(denied))
        self.assertFalse(FORBIDDEN_FLAGS & set(argv))
        self.assertFalse(any("bypass" in x.lower() or "dangerous" in x.lower() for x in argv))
        prompt = (self.state / "prompt.txt").read_text()
        self.assertIn("CLAUDE.md", prompt)
        self.assertIn("Review source.py", prompt)

    def test_fixer_may_edit_but_not_delegate(self):
        self.mode("fix")
        result = self.execute(self.request("fixer", 1))
        self.assertEqual(result["status"], "completed")
        argv = self.argv()
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertIn("Agent", argv[argv.index("--disallowedTools") + 1].split(","))
        self.assertNotIn("--tools", argv)
        self.assertFalse(FORBIDDEN_FLAGS & set(argv))
        self.assertTrue(result["repair_started"])

    def test_model_and_effort_overrides_use_claude_flags(self):
        request = self.request()
        request.update(model="opus", reasoning_effort="high")
        self.execute(request)
        argv = self.argv()
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertEqual(argv[argv.index("--effort") + 1], "high")

    def test_invoking_session_variables_are_not_inherited(self):
        with patch.dict(os.environ, {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "host",
                                     "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/host.sock", "KEEP_ME": "1"}):
            self.assertEqual(self.execute(self.request())["status"], "completed")
        names = set(json.loads((self.state / "env.json").read_text()))
        self.assertIn("KEEP_ME", names)
        self.assertFalse(names & runner.CLAUDE_SESSION_VARIABLES)

    def test_structured_output_becomes_the_saved_report(self):
        result = self.execute(self.request())
        saved = json.loads((self.state / "reports" / "initial-r1.json").read_text())
        self.assertEqual(saved, result["result"])
        self.assertEqual(saved["status"], "completed")

    def test_json_result_text_is_accepted_as_a_fallback_report(self):
        self.mode("text_report")
        self.assertEqual(self.execute(self.request())["status"], "completed")

    def test_missing_or_malformed_report_is_not_a_success(self):
        self.mode("malformed")
        result = self.execute(self.request())
        self.assertEqual(result["category"], "invalid_report")

    def test_permission_denials_are_recorded(self):
        self.mode("denied")
        result = self.execute(self.request())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["permission_denials"], 1)

    def test_every_assignment_gets_a_new_session(self):
        ids = [self.execute(self.request(assignment=f"review-{i}"))["session_id"] for i in range(3)]
        self.assertEqual(len(set(ids)), 3)

    def test_ignored_session_id_is_not_a_fresh_context(self):
        self.mode("reused")
        result = self.execute(self.request())
        self.assertEqual(result["category"], "session_mismatch")
        self.assertFalse(result["fresh_context"])

    def test_prework_rejections_do_not_consume_a_repair_cycle(self):
        for mode, category in (("auth", "authentication"), ("quota", "quota"), ("rate", "rate_limit"),
                               ("nested", "nested_session"), ("incompatible", "cli_incompatible")):
            with self.subTest(mode=mode):
                self.mode(mode)
                result = self.execute(self.request("fixer", 1, mode))
                self.assertEqual(result["category"], category)
                self.assertFalse(result["repair_started"])
                self.assertNotIn("SECRET_SHOULD_NOT_LEAK", json.dumps(result))
        self.assertEqual(json.loads((self.state / "ledger.json").read_text())["current_cycle"], 0)

    def test_error_result_with_zero_exit_is_not_a_success(self):
        self.mode("error_exit0")
        result = self.execute(self.request())
        self.assertEqual(result["status"], "blocked")

    def test_run_without_result_event_is_incomplete(self):
        self.mode("incomplete")
        self.assertEqual(self.execute(self.request())["category"], "incomplete_run")

    def test_timeout_preserves_partial_edits_and_requires_reconciliation(self):
        self.mode("timeout")
        request = self.request("fixer", 1)
        request["timeout_seconds"] = 0.3
        result = self.execute(request)
        self.assertEqual(result["category"], "timeout")
        self.assertTrue(result["needs_reconciliation"])
        self.assertTrue(result["repair_started"])
        self.assertEqual((self.root / "source.py").read_text(), "changed\n")

    def test_changes_outside_scope_are_not_accepted(self):
        self.mode("outside")
        self.assertEqual(self.execute(self.request())["status"], "stale")
        (self.root / "other.py").write_text("other\n")
        result = self.execute(self.request("fixer", 1, "fixer-outside"))
        self.assertEqual(result["category"], "scope_drift")
        self.assertTrue(result["needs_reconciliation"])

    def test_exited_cli_cannot_leave_a_background_writer(self):
        self.mode("orphan")
        result = self.execute(self.request("fixer", 1))
        self.assertNotEqual(result["status"], "completed")
        time.sleep(0.9)
        self.assertEqual((self.root / "source.py").read_text(), "original\n")

    def test_cycle_budget_is_shared_with_codex_and_native_assignments(self):
        self.state.mkdir()
        (self.state / "ledger.json").write_text(json.dumps({
            "schema_version": 1, "run_id": "test-run", "current_cycle": 5, "tasks": {},
            "assignments": {"codex-fix": {"backend": "cli", "host": "codex", "role": "fixer", "cycle": 5,
                                          "task_id": "R1", "repair_started": True, "status": "completed"}}}))
        self.assertEqual(self.execute(self.request("fixer", 5, "claude-fix"))["category"], "repair_already_attempted")
        self.assertEqual(self.execute(self.request("fixer", 6, "claude-fix-next"))["category"], "cycle_limit")
        self.assertFalse((self.state / "calls.txt").exists())

    def test_host_and_cli_path_must_match(self):
        request = self.request()
        request["host"] = "other"
        self.assertEqual(self.execute(request)["category"], "invalid_request")
        (self.root / "codex").write_text("")
        request = self.request()
        request["cli_path"] = str(self.root / "codex")
        self.assertEqual(self.execute(request)["category"], "invalid_request")
        (self.root / "claude").write_text("")
        request = self.request(assignment="named-claude")
        request["cli_path"] = str(self.root / "claude")
        self.assertEqual(self.execute(request)["status"], "completed")
        self.assertFalse((self.state / "calls.txt").read_text() != "1")

    def test_missing_binary_does_not_consume_cycle(self):
        result = self.execute(self.request("fixer", 1), command=[str(self.root / "does-not-exist")])
        self.assertEqual(result["category"], "cli_unavailable")
        self.assertFalse(result["repair_started"])

    def test_claude_error_classification(self):
        cases = {
            "Error: Claude Code cannot be launched inside another Claude Code session.": "nested_session",
            "error: unknown option '--json-schema'": "cli_incompatible",
            "error: option '--permission-mode <mode>' argument 'x' is invalid. Allowed choices are a, b.": "cli_incompatible",
            "Not logged in · Please run /login": "authentication",
            "Invalid API key · Please run /login": "authentication",
            "API Error: 401 Invalid authentication credentials": "authentication",
            "You’ve hit your weekly limit · resets Mon 12:00am": "quota",
            '{"api_retry": "billing_error"}': "quota",
            "Request rejected (429)": "rate_limit",
            "API Error: Repeated 529 Overloaded errors.": "overloaded",
            "Concurrent subagent limit reached": "agent_limit",
            '{"assistant_error": "model_not_found"}': "model_unavailable",
            '{"result": "error_max_structured_output_retries"}': "invalid_report",
            "request id abc429def; fetch failed": "network",
            "something else": "process_error",
        }
        for text, category in cases.items():
            with self.subTest(text=text):
                self.assertEqual(runner.classify_claude_error(text), category)


if __name__ == "__main__":
    unittest.main()
