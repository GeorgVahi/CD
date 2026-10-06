"""Run one fresh Codex CLI assignment; no third-party dependencies.

This executor records evidence, not acceptance. The coordinator owns scheduling,
native-agent lifecycle, scoring, and the global review protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SCHEMA = Path(__file__).with_name("agent-report.schema.json")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def local_path(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Scope and write paths must be workspace-relative files.")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("A path escapes the workspace.")
    if path.exists() and not path.is_file():
        raise ValueError("Enumerate files, not directories, in scope/write paths.")
    return path


def fingerprint(root, paths):
    result = {}
    for name in sorted(set(paths)):
        path = local_path(root, name)
        if path.is_file():
            with path.open("rb") as stream:
                result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        else:
            result[name] = None
    return result


def git_output(root, *args):
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None


def inventory(root, state, scope, is_git):
    gitlinks = {}
    if is_git:
        result = git_output(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if result is None or result.returncode:
            raise ValueError("Cannot inventory the repository safely.")
        names = result.stdout.decode("utf-8").split("\0")
        stages = git_output(root, "ls-files", "--stage", "-z")
        if stages is None or stages.returncode:
            raise ValueError("Cannot inspect gitlink metadata.")
        for record in stages.stdout.decode("utf-8").split("\0"):
            if record:
                metadata, name = record.split("\t", 1)
                if metadata.startswith("160000 "):
                    gitlinks[name] = metadata
    else:
        names = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    names = [n for n in names if n and not (root / n).resolve().is_relative_to(state)]
    result = fingerprint(root, (set(names) - set(gitlinks)) | set(scope))
    for name, metadata in gitlinks.items():
        module = (root / name).resolve()
        if not module.is_relative_to(root):
            raise ValueError("Submodule escapes the workspace.")
        top = git_output(module, "rev-parse", "--show-toplevel") if module.is_dir() else None
        initialized = top is not None and top.returncode == 0 and Path(top.stdout.decode().strip()).resolve() == module
        head = git_output(module, "rev-parse", "HEAD") if initialized else None
        result[name] = digest([metadata, head.stdout.decode().strip() if head and head.returncode == 0 else None])
        if initialized:
            result.update({name + "/" + p: value for p, value in inventory(module, state, [], True).items()})
    return result


def outcome(status, category, **fields):
    return {"status": status, "category": category, "repair_started": False,
            "needs_reconciliation": False, **fields}


def validate(request, state):
    if not isinstance(request, dict):
        raise ValueError("Request must be an object.")
    for key in ("run_id", "assignment_id", "task_id"):
        if not isinstance(request.get(key), str) or not ID.fullmatch(request[key]):
            raise ValueError(f"Invalid {key}.")
    root = Path(request["workspace"]).resolve(strict=True)
    if not root.is_dir() or not state.is_relative_to(root) or state == root:
        raise ValueError("The state directory must be inside the workspace.")
    role = request.get("role")
    cycle = request.get("cycle")
    if role not in ("decomposer", "reviewer", "fixer"):
        raise ValueError("Unknown role.")
    if type(cycle) is not int or cycle < 0 or (role == "fixer" and cycle == 0):
        raise ValueError("Invalid cycle.")
    if not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise ValueError("A factual assignment prompt is required.")
    scope, writes = request.get("scope_paths"), request.get("write_paths", [])
    if not isinstance(scope, list) or not scope or not isinstance(writes, list):
        raise ValueError("scope_paths must contain the complete relevant file set.")
    for name in scope + writes:
        path = local_path(root, name)
        if path.is_relative_to(state):
            raise ValueError("Coordinator state is not a source file.")
        if path.relative_to(root).as_posix() != name:
            raise ValueError("Use normalized slash-separated relative paths.")
    if len(set(scope)) != len(scope) or len(set(writes)) != len(writes):
        raise ValueError("Duplicate paths are not allowed.")
    if not set(writes).issubset(scope) or (role != "fixer" and writes):
        raise ValueError("Write scope must be explicit, contained, and fixer-only.")
    sandbox = request.get("sandbox", "read-only")
    if sandbox not in ("read-only", "workspace-write") or (role != "fixer" and sandbox != "read-only"):
        raise ValueError("Reviewers/decomposers require read-only; no permission bypass is supported.")
    if role == "fixer" and (not writes or sandbox != "workspace-write"):
        raise ValueError("Fixers require authorized write_paths and workspace-write.")
    expected = request.get("expected_snapshot")
    if not isinstance(expected, dict) or set(expected) != set(scope):
        raise ValueError("expected_snapshot must cover exactly scope_paths, including missing files.")
    if any(v is not None and (not isinstance(v, str) or not HASH.fullmatch(v)) for v in expected.values()):
        raise ValueError("Expected fingerprints must be SHA-256 or null for absent files.")
    duration = request.get("timeout_seconds", 900)
    if type(duration) not in (int, float) or not 0 < duration <= 3600:
        raise ValueError("timeout_seconds must be positive and at most 3600.")
    for key in ("model", "reasoning_effort"):
        if key in request and (not isinstance(request[key], str) or not request[key].strip()):
            raise ValueError(f"Invalid {key}.")
    if "cli_path" in request:
        cli = Path(request["cli_path"])
        if not cli.is_absolute() or not cli.is_file() or cli.name.lower() not in ("codex", "codex.exe"):
            raise ValueError("cli_path must identify a discovered installed Codex binary.")
    return root


def classify_error(text):
    text = text.lower()
    for category, phrases in (
        ("cli_unavailable", ("codex executable unavailable",)),
        ("process_containment", ("process containment unavailable",)),
        ("cli_incompatible", ("requires a newer version of codex", "upgrade to the latest app or cli")),
        ("quota", ("insufficient_quota", "usage limit", "quota exceeded", "credit balance")),
        ("authentication", ("unauthorized", "authentication", "not logged in", "login required")),
        ("agent_limit", ("agent thread limit", "maximum number of agents", "max_concurrent_threads")),
        ("rate_limit", ("rate limit", "too many requests")),
        ("permissions", ("permission denied", "access denied", "requires approval", "sandbox denied")),
        ("model_unavailable", ("model is not supported", "model not found", "unsupported model")),
        ("network", ("stream disconnected", "connection refused", "error sending request", "failed to connect")),
    ):
        if any(phrase in text for phrase in phrases):
            return category
    if re.search(r"\b401\b", text):
        return "authentication"
    if re.search(r"\b429\b", text):
        return "rate_limit"
    return "process_error"


def event_summary(stream):
    stream.seek(0)
    summary = {"session_id": None, "turn_started": False, "turn_completed": False, "work_started": False, "errors": ""}
    for raw in stream:
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "thread.started":
            summary["session_id"] = event.get("thread_id")
        elif kind == "turn.started":
            summary["turn_started"] = True
        elif kind == "turn.completed":
            summary["turn_completed"] = True
        elif kind in ("item.started", "item.completed"):
            summary["work_started"] = True
        elif kind in ("error", "turn.failed"):
            summary["errors"] = (summary["errors"] + json.dumps(event))[-65536:]
    return summary


def supervise_windows(command):
    """Own a kill-on-close job before spawning CLI, so descendants cannot escape
    merely by outliving CLI. Only this short-lived supervisor joins the job.
    Its handle intentionally stays open until process exit (including termination).
    """
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                    ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        print(json.dumps({"type": "error", "message": "Process containment unavailable"}), flush=True)
        return 125
    try:
        return subprocess.call(command, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    except OSError:
        print(json.dumps({"type": "error", "message": "Codex executable unavailable"}), flush=True)
        return 127


def stop_owned_process(process):
    """Terminate only the process tree/session created for this assignment."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def build_command(prefix, request, root, output, is_git):
    args = [*prefix, "-c", 'approval_policy="never"', "exec", "--json", "--ephemeral",
            "--sandbox", request.get("sandbox", "read-only"), "-C", str(root),
            "--output-schema", str(SCHEMA), "--output-last-message", str(output)]
    if not is_git:
        args.append("--skip-git-repo-check")
    if request.get("model"):
        args += ["--model", request["model"]]
    if request.get("reasoning_effort"):
        args += ["-c", "model_reasoning_effort=" + json.dumps(request["reasoning_effort"])]
    return [*args, "-"]


def validate_report(path):
    report = read_json(path)
    if not isinstance(report, dict) or set(report) != {"status", "report", "changed_paths"}:
        raise ValueError("Unexpected report shape.")
    if report["status"] not in ("completed", "blocked") or not isinstance(report["report"], str) or not report["report"].strip():
        raise ValueError("Missing report or invalid status.")
    if not isinstance(report["changed_paths"], list) or any(not isinstance(p, str) for p in report["changed_paths"]):
        raise ValueError("Invalid changed_paths.")
    return report


def run(request, state_dir, *, command=None):
    state = Path(state_dir).resolve()
    try:
        root = validate(request, state)
    except (ValueError, KeyError, OSError, TypeError):
        return outcome("blocked", "invalid_request")
    if request["cycle"] > 5:
        return outcome("blocked", "cycle_limit")
    git = git_output(root, "rev-parse", "--show-toplevel")
    is_git = git is not None and git.returncode == 0
    if is_git:
        # The trailing slash preserves directory-only ignore rules before mkdir.
        ignored = git_output(root, "check-ignore", "--quiet", "--", state.as_posix() + "/")
        if ignored is None or ignored.returncode:
            return outcome("blocked", "state_directory_not_ignored")
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "executor.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return outcome("blocked", "busy_or_interrupted", needs_reconciliation=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "assignment_id": request["assignment_id"], "started_at": time.time()}, stream)
        return run_locked(request, root, state, is_git, command)
    except (OSError, ValueError, TypeError, KeyError):
        return outcome("blocked", "state_error", needs_reconciliation=True)
    finally:
        lock.unlink(missing_ok=True)


def run_locked(request, root, state, is_git, command):
    ledger_path = state / "ledger.json"
    ledger = read_json(ledger_path) if ledger_path.exists() else {
        "schema_version": 1, "run_id": request["run_id"], "current_cycle": 0,
        "tasks": {}, "assignments": {}}
    if ledger.get("schema_version") != 1 or ledger.get("run_id") != request["run_id"]:
        return outcome("blocked", "run_conflict")
    assignment = request["assignment_id"]
    request_hash = digest(request)
    previous = ledger["assignments"].get(assignment)
    if previous:
        if previous["request_hash"] != request_hash:
            return outcome("blocked", "assignment_conflict")
        if previous["status"] in ("prepared", "running"):
            return outcome("blocked", "interrupted_assignment", needs_reconciliation=True)
        if previous["status"] == "completed" and fingerprint(root, request["scope_paths"]) != previous["post_snapshot"]:
            return outcome("stale", "snapshot_changed", assignment_id=assignment)
        return previous
    cycle, role = request["cycle"], request["role"]
    current = ledger["current_cycle"]
    if role == "fixer" and any((a.get("needs_reconciliation") or a.get("status") in ("prepared", "running"))
                              and a.get("reconciliation", {}).get("status") != "resolved"
                              for a in ledger["assignments"].values()):
        return outcome("blocked", "unreconciled_assignment", needs_reconciliation=True)
    if (role == "fixer" and cycle not in (current, current + 1)) or (role != "fixer" and cycle != current):
        return outcome("blocked", "cycle_conflict")
    if role == "fixer" and any(a.get("role") == "fixer" and a.get("task_id") == request["task_id"]
                               and a.get("cycle") == cycle and a.get("repair_started") for a in ledger["assignments"].values()):
        return outcome("blocked", "repair_already_attempted", needs_reconciliation=True)
    scope = request["scope_paths"]
    pre_scope = fingerprint(root, scope)
    if pre_scope != request["expected_snapshot"]:
        return outcome("stale", "snapshot_changed")
    before = inventory(root, state, scope, is_git)
    entry = outcome("prepared", None, request_hash=request_hash, assignment_id=assignment,
                    task_id=request["task_id"], role=role, cycle=cycle, backend="cli",
                    fresh_context=True, pre_snapshot=pre_scope, started_at=time.time())
    ledger["assignments"][assignment] = entry
    atomic_json(ledger_path, ledger)
    binary = request.get("cli_path") or shutil.which("codex")
    prefix = command or ([binary] if binary else None)
    if not prefix:
        entry.update(status="blocked", category="cli_unavailable")
        atomic_json(ledger_path, ledger)
        return entry
    entry["executable"] = prefix[0]
    output = state / "reports" / (assignment + ".json")
    output.parent.mkdir(exist_ok=True)
    if output.exists():
        entry.update(status="blocked", category="orphan_report", needs_reconciliation=True)
        atomic_json(ledger_path, ledger)
        return entry
    args = build_command(prefix, request, root, output, is_git)
    if os.name == "nt":
        args = [sys.executable, "-B", str(Path(__file__).resolve()), "--supervise", *args]
    header = ("You are a fresh, bounded code-review worker, not the workflow coordinator. "
              "Do not spawn/delegate, resume other sessions, invoke the $cd workflow, "
              "read earlier chats/review reports/coordinator state, or commit/push. "
              "Read applicable AGENTS.md and obey its instructions within this assignment. "
              "Never read or print credentials. Preserve unrelated edits. "
              "Return the required JSON envelope; report completed means assignment finished, not quality accepted.\n"
              f"Role: {role}. Authorized write files: {json.dumps(request.get('write_paths', []))}.\n")
    code, failure, process = None, None, None
    summary = {"session_id": None, "turn_started": False, "turn_completed": False, "work_started": False, "errors": ""}
    with tempfile.TemporaryFile(dir=state) as stdout, tempfile.TemporaryFile(dir=state) as stderr:
        try:
            process = subprocess.Popen(args, cwd=root, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                       start_new_session=os.name != "nt",
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            entry.update(status="running", pid=process.pid)
            atomic_json(ledger_path, ledger)
            process.communicate((header + request["prompt"]).encode("utf-8"), timeout=request.get("timeout_seconds", 900))
            code = process.returncode
        except subprocess.TimeoutExpired:
            failure = "timeout"
            stop_owned_process(process)
        except KeyboardInterrupt:
            failure = "cancelled"
            if process:
                stop_owned_process(process)
        except OSError:
            failure = "cli_unavailable" if process is None else "process_error"
            if process and process.poll() is None:
                stop_owned_process(process)
        finally:
            if process and process.poll() is None:
                stop_owned_process(process)
            elif process and os.name != "nt":
                # The process-group leader can exit before its descendants.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        summary = event_summary(stdout)
        stderr.seek(0, os.SEEK_END)
        stderr.seek(max(0, stderr.tell() - 65536))
        error_category = classify_error(summary["errors"] or stderr.read().decode("utf-8", errors="replace"))
    after = inventory(root, state, scope, is_git)
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    entry.update(post_snapshot=fingerprint(root, scope), changed_paths=changed,
                 session_id=summary["session_id"], exit_code=code, finished_at=time.time())
    prework_rejection = (failure or error_category) in {"authentication", "quota", "agent_limit", "rate_limit",
        "cli_incompatible", "cli_unavailable", "model_unavailable", "process_containment"} and not changed and not summary["work_started"]
    entry["repair_started"] = role == "fixer" and bool(changed or summary["work_started"] or (summary["turn_started"] and not prework_rejection))
    if entry["repair_started"]:
        ledger["current_cycle"] = max(current, cycle)
    if failure or code != 0:
        entry.update(status="blocked", category=failure or error_category)
    elif not summary["turn_completed"] or not isinstance(summary["session_id"], str) or not summary["session_id"]:
        entry.update(status="blocked", category="incomplete_run")
    elif any(a is not entry and a.get("session_id") == summary["session_id"] for a in ledger["assignments"].values()):
        entry.update(status="blocked", category="context_reused", fresh_context=False)
    else:
        try:
            report = validate_report(output)
            entry.update(status=report["status"], category=None if report["status"] == "completed" else "agent_blocked", result=report)
        except (ValueError, OSError):
            entry.update(status="blocked", category="invalid_report")
    drift = sorted(set(changed) - set(request.get("write_paths", [])))
    if drift:
        entry.update(status="stale" if role != "fixer" else "blocked", category="scope_drift", unexpected_paths=drift)
    entry["needs_reconciliation"] = role == "fixer" and (bool(drift) or (entry["status"] != "completed" and process is not None and not prework_rejection))
    atomic_json(ledger_path, ledger)
    return entry


def main():
    if sys.argv[1:2] == ["--supervise"] and os.name == "nt":
        return supervise_windows(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(read_json(args.request), args.state_dir)
    except (OSError, ValueError):
        result = outcome("blocked", "invalid_request")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
