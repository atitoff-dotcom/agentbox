# -*- coding: utf-8 -*-
"""
agentbox.client — Local Driver & SSH/Local Transport.
Handles local execution and remote SSH execution with zero bash quoting issues.
Auto-bootstraps worker.py to remote servers.
Includes Persistent Stdio-Daemon Bridge for sub-millisecond remote command execution.
"""

import os
import sys

# Force UTF-8 encoding on standard I/O streams across all platforms
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="surrogateescape")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import time
import socket
import secrets
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

from . import worker

WORKER_LOCAL_FILE = Path(__file__).parent / "worker.py"
REMOTE_WORKER_PATH = "~/.agentbox_worker.py"
WORKER_CACHE_FILE = Path.home() / ".agentbox" / ".worker_cache.json"
BRIDGE_RUN_DIR = Path.home() / ".agentbox" / "run"


def load_worker_cache() -> Dict[str, str]:
    """Loads cached remote worker SHA-256 hashes per host."""
    if WORKER_CACHE_FILE.is_file():
        try:
            return json.loads(WORKER_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_worker_cache(cache: Dict[str, str]) -> None:
    """Saves cached remote worker SHA-256 hashes."""
    try:
        WORKER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        WORKER_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_local_worker_bytes() -> bytes:
    if WORKER_LOCAL_FILE.is_file():
        return WORKER_LOCAL_FILE.read_bytes()
    # Fallback to reading worker module source
    import inspect
    return inspect.getsource(worker).encode("utf-8")


def win_no_window_kwargs(extra_flags: int = 0) -> dict:
    """Returns creationflags on Windows to suppress terminal/console window popups."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if extra_flags:
            flags |= extra_flags
        return {"creationflags": flags}
    return {}


def ensure_remote_worker(host: str, force: bool = False) -> None:
    """Verifies that the remote worker matches local worker SHA-256; uploads if needed.
    Caches verified hash to eliminate redundant SSH round-trips."""
    local_bytes = get_local_worker_bytes()
    local_hash = hashlib.sha256(local_bytes).hexdigest()

    cache = load_worker_cache()
    if not force and cache.get(host) == local_hash:
        return

    # Check remote hash
    check_cmd = ["ssh", host, f"sha256sum {REMOTE_WORKER_PATH} 2>/dev/null || echo NONE"]
    proc = subprocess.run(check_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    remote_out = proc.stdout.strip()
    remote_hash = remote_out.split()[0] if remote_out else "NONE"

    if remote_hash != local_hash:
        upload_cmd = ["ssh", host, f"cat > {REMOTE_WORKER_PATH} && chmod +x {REMOTE_WORKER_PATH}"]
        up_proc = subprocess.run(upload_cmd, input=local_bytes, **win_no_window_kwargs())
        if up_proc.returncode != 0:
            print(f"ERROR: Failed to bootstrap worker to {host}", file=sys.stderr)
            sys.exit(up_proc.returncode)

    cache[host] = local_hash
    save_worker_cache(cache)


# ---------------------------------------------------------------------------
# Persistent Stdio-Daemon Bridge
# ---------------------------------------------------------------------------

def get_bridge_info_path(host: str) -> Path:
    safe_host = "".join(c if c.isalnum() or c in "._-" else "_" for c in host)
    return BRIDGE_RUN_DIR / f"bridge_{safe_host}.json"


def _is_bridge_alive(info: Dict[str, Any]) -> bool:
    """Checks whether the local bridge server is alive and responding to ping."""
    try:
        port = info.get("port")
        token = info.get("token")
        if not port or not token:
            return False
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=0.5)
        req = json.dumps({"token": token, "action": "ping"}) + "\n"
        s.sendall(req.encode("utf-8"))
        f = s.makefile("r", encoding="utf-8", errors="replace")
        resp = f.readline()
        s.close()
        return bool(resp and "pong" in resp)
    except Exception:
        return False


def spawn_bridge_daemon(host: str) -> None:
    """Spawns background bridge server process detached from current terminal."""
    BRIDGE_RUN_DIR.mkdir(parents=True, exist_ok=True)
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    cmd = [sys.executable, "-m", "agentbox.client", "--bridge-server", host]
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags
        )
    except Exception:
        pass


def handle_bridge_client(conn: socket.socket, token: str, ssh_proc: subprocess.Popen) -> bool:
    """Handles single client connection. Returns True if shutdown was requested."""
    should_shutdown = False
    try:
        conn_file = conn.makefile("r", encoding="utf-8", errors="replace")
        line = conn_file.readline()
        if not line:
            return False
        try:
            req = json.loads(line)
        except Exception:
            return False

        if req.get("token") != token:
            conn.sendall(json.dumps({"event": "error", "message": "Unauthorized"}).encode("utf-8") + b"\n")
            return False

        action = req.get("action")
        req_id = req.get("id", "req")

        if action == "ping":
            conn.sendall(json.dumps({"id": req_id, "event": "pong"}).encode("utf-8") + b"\n")
            return False
        elif action == "shutdown":
            conn.sendall(json.dumps({"id": req_id, "event": "exit", "code": 0}).encode("utf-8") + b"\n")
            return True

        if ssh_proc.poll() is not None or not ssh_proc.stdin:
            conn.sendall(json.dumps({"event": "error", "message": "Remote worker dead"}).encode("utf-8") + b"\n")
            return False

        # Forward request to ssh_proc stdin
        ssh_req = json.dumps({"id": req_id, "action": action, "args": req.get("args", {})}, ensure_ascii=False)
        ssh_proc.stdin.write(ssh_req + "\n")
        ssh_proc.stdin.flush()

        # Stream lines from ssh_proc stdout until exit event matching req_id
        while True:
            out_line = ssh_proc.stdout.readline()
            if not out_line:
                break
            conn.sendall(out_line.encode("utf-8"))
            try:
                msg = json.loads(out_line)
                if msg.get("event") == "exit" and msg.get("id") == req_id:
                    break
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return should_shutdown


def run_bridge_server(host: str, idle_timeout: int = 1800) -> None:
    """Main loop of the background bridge server process."""
    BRIDGE_RUN_DIR.mkdir(parents=True, exist_ok=True)
    safe_host = "".join(c if c.isalnum() or c in "._-" else "_" for c in host)
    log_path = BRIDGE_RUN_DIR / f"bridge_{safe_host}.log"
    try:
        log_f = open(log_path, "a", encoding="utf-8")
        sys.stdout = log_f
        sys.stderr = log_f
    except Exception:
        pass

    info_path = get_bridge_info_path(host)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(5)
    port = server_sock.getsockname()[1]
    token = secrets.token_hex(16)

    # Launch SSH process in headless batch mode
    ensure_remote_worker(host)
    ssh_cmd = ["ssh", "-T", "-o", "BatchMode=yes", host, f"python3 {REMOTE_WORKER_PATH} --daemon"]
    ssh_env = os.environ.copy()
    ssh_env["PYTHONIOENCODING"] = "utf-8"
    ssh_env["LC_ALL"] = "C.UTF-8"
    ssh_env["LANG"] = "C.UTF-8"
    try:
        ssh_proc = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=ssh_env,
            **win_no_window_kwargs()
        )
    except Exception:
        server_sock.close()
        sys.exit(1)

    # Handshake ready line from remote daemon
    ready_line = ssh_proc.stdout.readline()
    if not ready_line or "ready" not in ready_line:
        try:
            ssh_proc.kill()
        except Exception:
            pass
        server_sock.close()
        sys.exit(1)

    info_data = {
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "ssh_pid": ssh_proc.pid,
        "host": host,
        "started": time.time()
    }
    info_path.write_text(json.dumps(info_data, indent=2), encoding="utf-8")

    last_active = time.time()
    try:
        log_f.write(f"[{time.strftime('%X')}] Listening on port {port}, waiting for requests (timeout={idle_timeout}s)...\n")
        log_f.flush()
        while True:
            if ssh_proc.poll() is not None:
                log_f.write(f"[{time.strftime('%X')}] SSH process exited with code {ssh_proc.returncode}\n")
                log_f.flush()
                break

            server_sock.settimeout(2.0)
            try:
                conn, addr = server_sock.accept()
            except socket.timeout:
                if time.time() - last_active > idle_timeout:
                    log_f.write(f"[{time.strftime('%X')}] Idle timeout expired ({idle_timeout}s). Exiting.\n")
                    log_f.flush()
                    break
                continue
            except Exception as e:
                log_f.write(f"[{time.strftime('%X')}] accept() error: {e}\n")
                log_f.flush()
                break

            last_active = time.time()
            log_f.write(f"[{time.strftime('%X')}] Accepted client from {addr}\n")
            log_f.flush()
            should_stop = handle_bridge_client(conn, token, ssh_proc)
            log_f.write(f"[{time.strftime('%X')}] Finished client request (should_stop={should_stop})\n")
            log_f.flush()
            if should_stop:
                break
    except Exception as e:
        log_f.write(f"[{time.strftime('%X')}] Fatal loop exception: {e}\n")
        log_f.flush()
    finally:
        log_f.write(f"[{time.strftime('%X')}] Bridge server terminating. Cleaning up.\n")
        log_f.flush()
        try:
            if info_path.is_file():
                info_path.unlink()
        except Exception:
            pass
        try:
            server_sock.close()
        except Exception:
            pass
        try:
            if ssh_proc.poll() is None:
                ssh_proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                ssh_proc.stdin.flush()
                ssh_proc.wait(timeout=2)
        except Exception:
            try:
                ssh_proc.kill()
            except Exception:
                pass


def execute_via_bridge(host: str, action: str, args: Dict[str, Any]) -> Optional[int]:
    """Attempts fast command execution via persistent local bridge."""
    info_path = get_bridge_info_path(host)

    # 1. Check existing bridge info
    info = None
    if info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            info = None

    # 2. Spawn if missing or unresponsive
    if not info or not _is_bridge_alive(info):
        try:
            if info_path.is_file():
                info_path.unlink()
        except Exception:
            pass
        spawn_bridge_daemon(host)

        # Wait up to 3.5s for bridge to start and pass ping
        start_time = time.time()
        info = None
        while time.time() - start_time < 3.5:
            time.sleep(0.08)
            if info_path.is_file():
                try:
                    cand = json.loads(info_path.read_text(encoding="utf-8"))
                    if _is_bridge_alive(cand):
                        info = cand
                        break
                except Exception:
                    pass

        if not info:
            # Fallback will handle execution
            return None

    # 3. Connect and execute
    try:
        sock = socket.create_connection(("127.0.0.1", int(info["port"])), timeout=120.0)
        sock_file = sock.makefile("r", encoding="utf-8", errors="replace")

        req_id = f"req_{int(time.time() * 1000)}"
        req = {
            "token": info["token"],
            "id": req_id,
            "action": action,
            "args": args
        }
        sock.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))

        exit_code = 0
        got_exit = False
        while True:
            line = sock_file.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except Exception:
                continue

            ev = msg.get("event")
            if ev == "stdout":
                sys.stdout.write(msg.get("data", ""))
                sys.stdout.flush()
            elif ev == "stderr":
                sys.stderr.write(msg.get("data", ""))
                sys.stderr.flush()
            elif ev == "exit":
                exit_code = msg.get("code", 0)
                got_exit = True
                break
        sock.close()
        return exit_code if got_exit else None
    except Exception:
        return None


def status_daemon(target_host: Optional[str] = None) -> int:
    """Prints status of running bridge daemons."""
    if not BRIDGE_RUN_DIR.is_dir():
        print("No active daemon bridges found.")
        return 0

    found = 0
    for p in BRIDGE_RUN_DIR.glob("bridge_*.json"):
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
            h = info.get("host", "unknown")
            if target_host and target_host != h:
                continue
            alive = _is_bridge_alive(info)
            if not alive:
                try:
                    p.unlink()
                except Exception:
                    pass
                continue
            uptime = int(time.time() - info.get("started", time.time()))
            print(f"Host: {h} | Status: ACTIVE (Sub-ms latency) | PID: {info.get('pid')} | Port: {info.get('port')} | Uptime: {uptime}s")
            found += 1
        except Exception:
            pass

    if not found:
        print("No active daemon bridges found.")
    return 0


def stop_daemon(target_host: Optional[str] = None) -> int:
    """Stops running daemon bridge and its remote worker."""
    if not BRIDGE_RUN_DIR.is_dir():
        print("No active daemons found to stop.")
        return 0

    stopped = 0
    for p in BRIDGE_RUN_DIR.glob("bridge_*.json"):
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
            h = info.get("host", "unknown")
            if target_host and target_host != h:
                continue
            port = info.get("port")
            token = info.get("token")
            pid = info.get("pid")
            if port and token:
                try:
                    s = socket.create_connection(("127.0.0.1", int(port)), timeout=1.0)
                    s.sendall((json.dumps({"token": token, "action": "shutdown"}) + "\n").encode("utf-8"))
                    s.close()
                except Exception:
                    pass
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
            print(f"Stopped daemon for host: {h} (PID: {pid})")
            stopped += 1
        except Exception as e:
            print(f"Failed to stop daemon {p.name}: {e}", file=sys.stderr)

    if not stopped:
        print("No matching daemons found to stop.")
    return 0


# ---------------------------------------------------------------------------
# Execution Dispatchers
# ---------------------------------------------------------------------------

def execute_action(host: str, cwd: str, action: str, args: Dict[str, Any], use_daemon: bool = True) -> int:
    """Executes an action either locally or remotely."""
    is_remote = bool(host and host not in ("local", "localhost", "127.0.0.1", "."))

    if not is_remote:
        return execute_local_action(cwd, action, args)

    # Normalize remote paths
    def _norm_remote_path(val: str) -> str:
        s = str(val)
        if not s.startswith("/") and not s.startswith("~") and cwd:
            return f"{cwd.rstrip('/')}/{s}"
        return s

    if "path" in args and args["path"]:
        if isinstance(args["path"], list):
            args["path"] = [_norm_remote_path(x) for x in args["path"]]
        else:
            args["path"] = _norm_remote_path(args["path"])

    if "paths" in args and isinstance(args["paths"], list):
        args["paths"] = [_norm_remote_path(x) for x in args["paths"]]

    if "cwd" in args and not args["cwd"]:
        args["cwd"] = cwd

    # 1. Fast path: execute via persistent daemon bridge
    if use_daemon:
        code = execute_via_bridge(host, action, args)
        if code is not None:
            return code

    # 2. Fallback path: direct SSH IPC over stdin
    ensure_remote_worker(host)
    payload = json.dumps({"action": action, "args": args}, ensure_ascii=False)
    cmd = ["ssh", host, f"python3 {REMOTE_WORKER_PATH} --ipc"]
    ssh_env = os.environ.copy()
    ssh_env["PYTHONIOENCODING"] = "utf-8"
    ssh_env["LC_ALL"] = "C.UTF-8"
    ssh_env["LANG"] = "C.UTF-8"
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ssh_env,
            **win_no_window_kwargs()
        )
        if proc.returncode == 127:
            ensure_remote_worker(host, force=True)
            proc = subprocess.run(
                cmd,
                input=payload,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=ssh_env,
                **win_no_window_kwargs()
            )
        return proc.returncode
    except KeyboardInterrupt:
        return 0


def execute_local_action(cwd: str, action: str, args: Dict[str, Any]) -> int:
    """Invokes worker directly in local process without extra processes."""
    if cwd:
        try:
            import os
            os.chdir(os.path.expanduser(cwd))
        except Exception:
            pass

    try:
        worker.dispatch_action(action, args)
        return 0
    except KeyboardInterrupt:
        return 0
    except SystemExit as se:
        return se.code if isinstance(se.code, int) else 1
    except Exception as e:
        print(f"ERROR: Local execution failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--bridge-server":
        target_host = sys.argv[2]
        run_bridge_server(target_host)
