"""Behavioral tests for the fresh-context CLI executor (stdlib only)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("run_agent", SKILL / "scripts/run_agent.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

FAKE = r'''
import json, pathlib, subprocess, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
root = pathlib.Path(args[args.index('-C') + 1])
count = root / '.review-state' / 'calls.txt'
count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')
(root / '.review-state' / 'argv.json').write_text(json.dumps(args))
mode = (root / 'mode.txt').read_text()
if mode == 'auth':
    print('authentication failed: 401; SECRET_SHOULD_NOT_LEAK', file=sys.stderr)
    sys.exit(1)
if mode == 'quota':
    print('insufficient_quota', file=sys.stderr)
    sys.exit(1)
if mode == 'limit':
    print('agent thread limit reached', file=sys.stderr)
    sys.exit(1)
if mode == 'orphan':
    subprocess.Popen([sys.executable, '-c', "import pathlib,time;time.sleep(0.7);pathlib.Path('source.py').write_text('orphan mutation')"], cwd=root)
    sys.exit(1)
print(json.dumps({'type':'thread.started','thread_id':'reused' if mode == 'reused' else 'fake-' + count.read_text()}), flush=True)
print(json.dumps({'type':'turn.started'}), flush=True)
if mode == 'late_auth':
    print(json.dumps({'type':'turn.failed','error':{'message':'HTTP 401 authentication failed'}}), flush=True)
    sys.exit(1)
if mode in ('fix', 'timeout', 'outside'):
    (root / ('other.py' if mode == 'outside' else 'source.py')).write_text('changed\n')
if mode == 'timeout':
    time.sleep(30)
out = pathlib.Path(args[args.index('--output-last-message') + 1])
if mode == 'malformed':
    out.write_text('{broken')
else:
    out.write_text(json.dumps({'status':'completed','report':'Reviewed source; no required check omitted.','changed_paths':['source.py'] if mode == 'fix' else []}))
if mode != 'incomplete':
    print(json.dumps({'type':'turn.completed'}), flush=True)
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SKILL / "tests")
        self.root = Path(self.temp.name)
        # Non-Git fixtures must not inherit the enclosing skill repository.
        # Fixtures that initialize their own repository remain discoverable.
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

    def request(self, role="reviewer", cycle=0, assignment="initial-r1"):
        return dict(run_id="test-run", assignment_id=assignment, task_id="R1",
                    role=role, cycle=cycle, workspace=str(self.root),
                    prompt="Review source.py against the stated requirements.",
                    scope_paths=["source.py", "other.py"],
                    expected_snapshot={p: hashlib.sha256((self.root / p).read_bytes()).hexdigest()
                                       for p in ("source.py", "other.py")},
                    write_paths=["source.py"] if role == "fixer" else [],
                    sandbox="workspace-write" if role == "fixer" else "read-only",
                    timeout_seconds=5)

    def execute(self, request):
        return runner.run(request, self.state, command=self.command)

    def test_new_session_and_restrictive_options(self):
        result = self.execute(self.request())
        self.assertEqual(result["status"], "completed")
        argv = json.loads((self.state / "argv.json").read_text())
        self.assertIn("--ephemeral", argv)
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertNotIn("resume", argv)
        self.assertNotIn("--ignore-rules", argv)
        self.assertNotIn("--ignore-user-config", argv)
        self.assertFalse(any("bypass" in x for x in argv))

    def test_duplicate_completed_assignment_does_not_execute_twice(self):
        request = self.request()
        first = self.execute(request)
        second = self.execute(request)
        self.assertEqual(first["status"], second["status"])
        self.assertEqual((self.state / "calls.txt").read_text(), "1")

    def test_stale_snapshot_does_not_launch_or_reuse_acceptance(self):
        request = self.request()
        self.assertEqual(self.execute(request)["status"], "completed")
        (self.root / "source.py").write_text("user edit\n")
        self.assertEqual(self.execute(request)["status"], "stale")
        self.assertEqual((self.state / "calls.txt").read_text(), "1")
        request["assignment_id"] = "second"
        self.assertEqual(self.execute(request)["status"], "stale")
        self.assertEqual((self.state / "calls.txt").read_text(), "1")

    def test_assignment_identity_cannot_be_reused_for_a_different_prompt(self):
        request = self.request()
        self.execute(request)
        request["prompt"] = "Different task"
        self.assertEqual(self.execute(request)["category"], "assignment_conflict")
        self.assertEqual((self.state / "calls.txt").read_text(), "1")

    def test_auth_quota_and_agent_limit_do_not_consume_a_repair_cycle(self):
        for mode, category in (("auth", "authentication"), ("quota", "quota"), ("limit", "agent_limit")):
            with self.subTest(mode=mode):
                (self.root / "mode.txt").write_text(mode)
                result = self.execute(self.request("fixer", 1, mode))
                self.assertEqual(result["category"], category)
                self.assertFalse(result["repair_started"])
                self.assertNotIn("SECRET_SHOULD_NOT_LEAK", json.dumps(result))
        self.assertEqual(json.loads((self.state / "ledger.json").read_text())["current_cycle"], 0)

    def test_timeout_preserves_partial_edits_and_requires_reconciliation(self):
        (self.root / "mode.txt").write_text("timeout")
        request = self.request("fixer", 1)
        request["timeout_seconds"] = 0.3
        result = self.execute(request)
        self.assertEqual(result["category"], "timeout")
        self.assertTrue(result["needs_reconciliation"])
        self.assertTrue(result["repair_started"])
        self.assertEqual((self.root / "source.py").read_text(), "changed\n")
        self.execute(request)
        self.assertEqual((self.state / "calls.txt").read_text(), "1")

    def test_changed_dependency_invalidates_read_only_review(self):
        (self.root / "mode.txt").write_text("outside")
        result = self.execute(self.request())
        self.assertEqual(result["status"], "stale")
        self.assertIn("other.py", result["changed_paths"])

    def test_out_of_scope_fixer_change_is_not_accepted(self):
        (self.root / "mode.txt").write_text("outside")
        result = self.execute(self.request("fixer", 1))
        self.assertEqual(result["category"], "scope_drift")
        self.assertTrue(result["needs_reconciliation"])

    def test_malformed_output_is_not_a_success(self):
        (self.root / "mode.txt").write_text("malformed")
        result = self.execute(self.request())
        self.assertEqual(result["category"], "invalid_report")
        self.assertNotEqual(result["status"], "completed")

    def test_five_cycles_persist_across_executor_invocations(self):
        for cycle in range(1, 6):
            (self.root / "mode.txt").write_text("fix")
            result = self.execute(self.request("fixer", cycle, f"fix-{cycle}"))
            self.assertEqual(result["status"], "completed")
        result = self.execute(self.request("fixer", 6, "fix-6"))
        self.assertEqual(result["category"], "cycle_limit")
        self.assertEqual((self.state / "calls.txt").read_text(), "5")
        self.assertEqual(json.loads((self.state / "ledger.json").read_text())["current_cycle"], 5)

    def test_six_reviews_can_run_sequentially_without_reusing_context(self):
        ids = []
        for index in range(6):
            result = self.execute(self.request(assignment=f"review-{index}"))
            self.assertEqual(result["status"], "completed")
            ids.append(result["session_id"])
        self.assertEqual(len(set(ids)), 6)

    def test_path_escape_and_running_assignment_are_not_replayed(self):
        request = self.request()
        request["scope_paths"] = ["../outside.py"]
        result = self.execute(request)
        self.assertEqual(result["category"], "invalid_request")
        self.assertFalse((self.state / "calls.txt").exists())

    def test_crashed_assignment_is_not_silently_replayed(self):
        request = self.request()
        self.execute(request)
        path = self.state / 'ledger.json'
        ledger = json.loads(path.read_text())
        ledger['assignments'][request['assignment_id']]['status'] = 'running'
        path.write_text(json.dumps(ledger))
        result = self.execute(request)
        self.assertEqual(result['category'], 'interrupted_assignment')
        self.assertTrue(result['needs_reconciliation'])
        self.assertEqual((self.state / 'calls.txt').read_text(), '1')

    def test_busy_lock_prevents_a_second_executor(self):
        self.state.mkdir()
        (self.state / 'executor.lock').write_text('{"pid": 123}')
        result = self.execute(self.request())
        self.assertEqual(result['category'], 'busy_or_interrupted')
        self.assertFalse((self.state / 'calls.txt').exists())

    def test_native_repair_cycle_is_preserved_when_switching_to_cli(self):
        self.state.mkdir()
        (self.state / 'ledger.json').write_text(json.dumps({
            'schema_version':1,'run_id':'test-run','current_cycle':5,'tasks':{},
            'assignments':{'native-fix':{'backend':'native','role':'fixer','cycle':5,
                'task_id':'R1','repair_started':True,'status':'completed'}}}))
        result = self.execute(self.request('fixer',5,'cli-fix'))
        self.assertEqual(result['category'],'repair_already_attempted')
        result = self.execute(self.request('fixer',6,'cli-fix-next'))
        self.assertEqual(result['category'],'cycle_limit')
        self.assertFalse((self.state / 'calls.txt').exists())

    def test_incomplete_run_and_reused_session_are_not_successful(self):
        (self.root / 'mode.txt').write_text('incomplete')
        self.assertEqual(self.execute(self.request(assignment='incomplete'))['category'], 'incomplete_run')
        (self.root / 'mode.txt').write_text('reused')
        self.assertEqual(self.execute(self.request(assignment='reused-one'))['status'], 'completed')
        self.assertEqual(self.execute(self.request(assignment='reused-two'))['category'], 'context_reused')

    def test_exited_cli_cannot_leave_a_background_writer(self):
        (self.root / 'mode.txt').write_text('orphan')
        result = self.execute(self.request('fixer',1))
        self.assertNotEqual(result['status'],'completed')
        time.sleep(0.9)
        self.assertEqual((self.root / 'source.py').read_text(),'original\n')

    def test_api_rejection_after_turn_started_does_not_consume_a_cycle(self):
        (self.root / 'mode.txt').write_text('late_auth')
        result = self.execute(self.request('fixer',1))
        self.assertEqual(result['category'],'authentication')
        self.assertFalse(result['repair_started'])

    def test_unreconciled_partial_fixer_blocks_another_writer(self):
        (self.root / 'mode.txt').write_text('timeout')
        request=self.request('fixer',1)
        request['timeout_seconds']=0.3
        self.execute(request)
        (self.root / 'mode.txt').write_text('fix')
        result=self.execute(self.request('fixer',2,'another-writer'))
        self.assertEqual(result['category'],'unreconciled_assignment')
        self.assertEqual((self.state/'calls.txt').read_text(),'1')

    def test_unrelated_initialized_gitlink_does_not_block_assignment(self):
        def git(*args):
            subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True)
        git('init','--quiet')
        (self.root/'.gitignore').write_text('.review-state/\n')
        git('add','source.py','other.py','.gitignore','mode.txt','fake.py')
        module=self.root/'vendor'/'lib'
        module.mkdir(parents=True)
        subprocess.run(['git','-C',str(module),'init','--quiet'],check=True,capture_output=True)
        (module/'library.py').write_text('value=1\n')
        git('update-index','--add','--cacheinfo','160000,1234567890123456789012345678901234567890,vendor/lib')
        result=self.execute(self.request())
        self.assertEqual(result['status'],'completed')

    def test_error_classification_ignores_digits_inside_identifiers(self):
        self.assertEqual(runner.classify_error('request id abc429def; model requires a newer version of Codex'), 'cli_incompatible')
        self.assertEqual(runner.classify_error('request id abc401def; stream disconnected'), 'network')
        self.assertEqual(runner.classify_error('HTTP 429 Too Many Requests'), 'rate_limit')

    def test_missing_binary_does_not_consume_cycle(self):
        result = runner.run(self.request("fixer", 1), self.state,
                            command=[str(self.root / "does-not-exist")])
        self.assertEqual(result["category"], "cli_unavailable")
        self.assertFalse(result["repair_started"])


if __name__ == "__main__":
    unittest.main()
