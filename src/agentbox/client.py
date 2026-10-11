# -*- coding: utf-8 -*-
"""
agentbox.client — Local Driver & SSH/Local Transport.
Handles local execution and remote SSH execution with zero bash quoting issues.
Auto-bootstraps worker.py to remote servers.
"""

import sys
import json
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, Any

from . import worker

WORKER_LOCAL_FILE = Path(__file__).parent / "worker.py"
REMOTE_WORKER_PATH = "~/.agentbox_worker.py"


def get_local_worker_bytes() -> bytes:
    if WORKER_LOCAL_FILE.is_file():
        return WORKER_LOCAL_FILE.read_bytes()
    # Fallback to reading worker module source
    import inspect
    return inspect.getsource(worker).encode("utf-8")


def ensure_remote_worker(host: str) -> None:
    """Verifies that the remote worker matches local worker SHA-256; uploads if needed."""
    local_bytes = get_local_worker_bytes()
    local_hash = hashlib.sha256(local_bytes).hexdigest()

    # Check remote hash
    check_cmd = ["ssh", host, f"sha256sum {REMOTE_WORKER_PATH} 2>/dev/null || echo NONE"]
    proc = subprocess.run(check_cmd, capture_output=True, text=True)
    remote_out = proc.stdout.strip()
    remote_hash = remote_out.split()[0] if remote_out else "NONE"

    if remote_hash != local_hash:
        upload_cmd = ["ssh", host, f"cat > {REMOTE_WORKER_PATH} && chmod +x {REMOTE_WORKER_PATH}"]
        up_proc = subprocess.run(upload_cmd, input=local_bytes)
        if up_proc.returncode != 0:
            print(f"ERROR: Failed to bootstrap worker to {host}", file=sys.stderr)
            sys.exit(up_proc.returncode)


def execute_action(host: str, cwd: str, action: str, args: Dict[str, Any]) -> int:
    """Executes an action either locally or remotely."""
    is_remote = bool(host and host not in ("local", "localhost", "127.0.0.1", "."))

    if not is_remote:
        # Local execution via worker functions
        return execute_local_action(cwd, action, args)

    # Remote execution over SSH with JSON-IPC over stdin
    ensure_remote_worker(host)

    if "path" in args and args["path"]:
        p = str(args["path"])
        if not p.startswith("/") and not p.startswith("~") and cwd:
            args["path"] = f"{cwd.rstrip('/')}/{p}"

    if "cwd" in args and not args["cwd"]:
        args["cwd"] = cwd

    payload = json.dumps({"action": action, "args": args})
    cmd = ["ssh", host, f"python3 {REMOTE_WORKER_PATH} --ipc"]
    try:
        proc = subprocess.run(cmd, input=payload, text=True)
        return proc.returncode
    except KeyboardInterrupt:
        return 0


def execute_local_action(cwd: str, action: str, args: Dict[str, Any]) -> int:
    """Invokes worker directly in local process."""
    if cwd:
        orig_cwd = Path.cwd()
        try:
            import os
            os.chdir(os.path.expanduser(cwd))
        except Exception:
            pass

    try:
        if action == "view":
            worker.cmd_view(args.get("path"), args.get("start", 1), args.get("end", 100))
        elif action == "outline":
            worker.cmd_outline(args.get("path"))
        elif action == "get_fn":
            worker.cmd_get_fn(args.get("path"), args.get("name"))
        elif action == "write":
            worker.cmd_write(args.get("path"), args.get("content"), args.get("append", False))
        elif action == "patch":
            worker.cmd_patch(args.get("path"), args.get("old"), args.get("new"), args.get("all", False))
        elif action == "rollback":
            worker.cmd_rollback(args.get("path"))
        elif action == "tree":
            worker.cmd_tree(args.get("path", "."), args.get("depth", 2))
        elif action == "grep":
            worker.cmd_grep(args.get("query"), args.get("path", "."), args.get("max", 20))
        elif action == "run":
            worker.cmd_run(args.get("cmd"), args.get("cwd"), args.get("tail", 15), args.get("timeout"))
        elif action == "test":
            worker.cmd_test(args.get("cmd"), args.get("cwd"), args.get("timeout"), args.get("max_lines", 30))
        elif action == "spawn":
            worker.cmd_spawn(args.get("cmd"), args.get("cwd"))
        elif action == "status":
            worker.cmd_status(args.get("task_id"))
        elif action == "logs":
            worker.cmd_logs(args.get("task_id"), args.get("lines", 50), args.get("follow", False))
        elif action == "kill":
            worker.cmd_kill(args.get("task_id"))
        else:
            print(f"ERROR: Unknown action '{action}'", file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        return 0
    except SystemExit as se:
        return se.code if isinstance(se.code, int) else 1
    except Exception as e:
        print(f"ERROR: Local execution failed: {e}", file=sys.stderr)
        return 1
