#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentbox.worker — Universal High-Efficiency Worker.
Runs on the target server (or locally). Requires ONLY Python 3 standard library.
Handles AST outlining, token-efficient slicing, atomic patching, and silent task execution.
"""

import os
import sys
import re
import ast
import json
import time
import signal
import shutil
import subprocess
import argparse
from pathlib import Path

DEFAULT_IGNORED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    "target", "dist", "build", ".vscode", ".idea", ".agents",
    "graphify-out", ".mypy_cache", ".pytest_cache"
}


def to_path(p: str = None) -> Path:
    if not p:
        return Path.cwd()
    return Path(os.path.expanduser(str(p))).resolve()


def cmd_view(path: str, start: int = 1, end: int = 100) -> None:
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    total = len(lines)
    s = max(1, start)
    e = min(total, end)

    print(f"[{p.name}: lines {s}-{e} of {total}]")
    for i in range(s, e + 1):
        print(f"{i:4d} | {lines[i - 1].rstrip()}")


def cmd_outline(path: str) -> None:
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ext = p.suffix.lower()
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"=== OUTLINE: {p.name} ({len(lines)} lines) ===")

    if ext == ".py":
        try:
            tree = ast.parse(content, filename=str(p))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in node.args.args]
                    ret = f" -> {ast.unparse(node.returns)}" if getattr(node, 'returns', None) else ""
                    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    end_ln = getattr(node, 'end_lineno', node.lineno)
                    print(f"{node.lineno:4d}-{end_ln:4d} | {prefix} {node.name}({', '.join(args)}){ret}")
                elif isinstance(node, ast.ClassDef):
                    end_ln = getattr(node, 'end_lineno', node.lineno)
                    bases = [ast.unparse(b) for b in node.bases]
                    base_str = f"({', '.join(bases)})" if bases else ""
                    print(f"{node.lineno:4d}-{end_ln:4d} | class {node.name}{base_str}:")
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = [a.arg for a in sub.args.args]
                            ret = f" -> {ast.unparse(sub.returns)}" if getattr(sub, 'returns', None) else ""
                            sub_prefix = "async def" if isinstance(sub, ast.AsyncFunctionDef) else "def"
                            sub_end = getattr(sub, 'end_lineno', sub.lineno)
                            print(f"{sub.lineno:4d}-{sub_end:4d} |     {sub_prefix} {sub.name}({', '.join(args)}){ret}")
            return
        except Exception:
            pass  # Fallback to regex

    # Regex-based outline for other languages (Rust, JS, TS, C, Go, etc.)
    regexes = [
        re.compile(r"^\s*(pub\s+)?(async\s+)?fn\s+([a-zA-Z0-9_]+)\s*(<[^>]+>)?\s*\((.*?)\)"),
        re.compile(r"^\s*(pub\s+)?(struct|enum|trait|impl)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^\s*(export\s+)?(async\s+)?function\s+([a-zA-Z0-9_]+)\s*\((.*?)\)"),
        re.compile(r"^\s*(export\s+)?class\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^\s*(const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*(async\s*)?\((.*?)\)\s*=>"),
        re.compile(r"^\s*func\s+([a-zA-Z0-9_]+)\s*\((.*?)\)"),
    ]

    for idx, line in enumerate(lines, start=1):
        for rx in regexes:
            if rx.search(line):
                print(f"{idx:4d} | {line.strip()[:100]}")
                break


def cmd_get_fn(path: str, name: str) -> None:
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ext = p.suffix.lower()
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    if ext == ".py":
        try:
            tree = ast.parse(content, filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == name:
                        s = node.lineno
                        e = getattr(node, 'end_lineno', s)
                        print(f"[{p.name}: {node.name} lines {s}-{e}]")
                        for i in range(s, e + 1):
                            print(f"{i:4d} | {lines[i - 1]}")
                        return
        except Exception:
            pass

    # Generic search
    target_pattern = re.compile(rf"(def|fn|function|class|func)\s+{re.escape(name)}\b")
    for idx, line in enumerate(lines, start=1):
        if target_pattern.search(line):
            print(f"[{p.name}: match at line {idx}]")
            for j in range(idx, min(len(lines) + 1, idx + 40)):
                print(f"{j:4d} | {lines[j - 1]}")
            return

    print(f"ERROR: Function or class '{name}' not found in {p.name}", file=sys.stderr)
    sys.exit(1)


def cmd_patch(path: str, old_text: str, new_text: str, replace_all: bool = False) -> None:
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    count = content.count(old_text)
    if count == 0:
        print(f"ERROR: Target content not found in {p.name}", file=sys.stderr)
        sys.exit(1)
    if count > 1 and not replace_all:
        print(f"ERROR: Target content found {count} times in {p.name}. Provide unique context or use --all", file=sys.stderr)
        sys.exit(1)

    # Backup
    bak_path = p.with_suffix(p.suffix + ".bak")
    try:
        bak_path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"ERROR: Failed to create backup {bak_path.name}: {e}", file=sys.stderr)
        sys.exit(1)

    # Replace
    new_content = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
    p.write_text(new_content, encoding="utf-8")

    print(f"OK: Replaced {count if replace_all else 1} occurrence(s) in {p.name}. Backup: {bak_path.name}")


def cmd_rollback(path: str) -> None:
    p = to_path(path)
    bak_path = p.with_suffix(p.suffix + ".bak")
    if not bak_path.is_file():
        print(f"ERROR: Backup file {bak_path.name} not found", file=sys.stderr)
        sys.exit(1)

    bak_content = bak_path.read_text(encoding="utf-8")
    p.write_text(bak_content, encoding="utf-8")
    bak_path.unlink()
    print(f"OK: Restored {p.name} from backup and removed backup.")


def cmd_tree(path: str = ".", max_depth: int = 2) -> None:
    root = to_path(path)
    if not root.exists():
        print(f"ERROR: Directory not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"=== TREE: {root} (depth <= {max_depth}) ===")
    root_level = len(root.parts)

    for current_root, dirs, files in os.walk(root):
        cur_path = Path(current_root)
        level = len(cur_path.parts) - root_level
        if level > max_depth:
            dirs.clear()
            continue

        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORED_DIRS and not d.startswith(".")]

        indent = "  " * level
        if level > 0:
            print(f"{indent}📂 {cur_path.name}/")

        sub_indent = "  " * (level + 1)
        visible_files = [f for f in sorted(files) if not f.startswith(".") and not f.endswith((".pyc", ".bak", ".swp"))]
        for f in visible_files[:15]:
            print(f"{sub_indent}📄 {f}")
        if len(visible_files) > 15:
            print(f"{sub_indent}... and {len(visible_files) - 15} more files")


def _grep_python(pattern: re.Pattern, root: Path, max_results: int) -> None:
    count = 0
    for cur_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORED_DIRS]
        for f in files:
            if f.endswith((".pyc", ".png", ".jpg", ".bin", ".tar", ".gz", ".zip", ".iso", ".frb")):
                continue
            fpath = Path(cur_root) / f
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    for idx, line in enumerate(fh, start=1):
                        if pattern.search(line):
                            try:
                                rel = fpath.relative_to(root)
                            except ValueError:
                                rel = fpath
                            print(f"{rel}:{idx} | {line.strip()[:120]}")
                            count += 1
                            if count >= max_results:
                                print(f"... [stopped at max {max_results} results]")
                                return
            except Exception:
                pass


def cmd_grep(query: str, path: str = ".", max_results: int = 20) -> None:
    root = to_path(path)
    if not root.exists():
        print(f"ERROR: Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    # Check for ripgrep (rg) adaptive acceleration
    rg_bin = shutil.which("rg")
    if rg_bin:
        rg_cmd = [
            rg_bin,
            "-i",
            "--line-number",
            "--no-heading",
            "--color", "never",
            f"--max-count={max_results}",
        ]
        for ign in DEFAULT_IGNORED_DIRS:
            rg_cmd.extend(["-g", f"!{ign}"])
        rg_cmd.extend([query, str(root)])

        try:
            proc = subprocess.Popen(
                rg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            count = 0
            if proc.stdout:
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    # format: /abs/path:line:content or rel/path:line:content
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        match_path, line_no, content = parts[0], parts[1], parts[2]
                        try:
                            rel = Path(match_path).relative_to(root)
                        except ValueError:
                            rel = Path(match_path)
                        print(f"{rel}:{line_no} | {content.strip()[:120]}")
                    else:
                        print(line[:120])

                    count += 1
                    if count >= max_results:
                        print(f"... [stopped at max {max_results} results]")
                        proc.terminate()
                        try:
                            proc.wait(timeout=0.5)
                        except Exception:
                            pass
                        return
            proc.wait()
            return
        except Exception:
            # Fallback to pure Python search on any rg execution issue
            pass

    pattern = re.compile(query, re.IGNORECASE)
    _grep_python(pattern, root, max_results)


def cmd_run(cmd: str, cwd: str = None, tail: int = 15, timeout: int = None) -> None:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"task_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"

    work_dir = to_path(cwd)
    start_time = time.time()

    with open(log_file, "w", encoding="utf-8") as out:
        out.write(f"=== Command: {cmd}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
        out.flush()
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(work_dir),
                stdout=out,
                stderr=subprocess.STDOUT,
                text=True,
            )
            proc.wait(timeout=timeout)
            ret_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            ret_code = -1
            out.write("\n=== ERROR: Timeout expired\n")

    duration = time.time() - start_time
    dur_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {int(duration % 60)}s"

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    tail_lines = lines[-tail:] if len(lines) > tail else lines
    tail_str = "".join(tail_lines).strip()

    if ret_code == 0:
        print(f"OK [exit 0, {dur_str}] Log: {log_file}")
        if tail > 0 and len(lines) > 3:
            print(f"--- Tail ({len(tail_lines)} lines) ---")
            print(tail_str)
    else:
        print(f"FAILED [exit {ret_code}, {dur_str}] Log: {log_file}")
        print(f"--- Failure Tail ({len(tail_lines)} lines) ---")
        print(tail_str)
        sys.exit(ret_code)


def cmd_spawn(cmd: str, cwd: str = None) -> None:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"bg_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"
    meta_file = log_dir / f"{task_id}.json"

    work_dir = to_path(cwd)
    start_time = time.time()

    out = open(log_file, "w", encoding="utf-8")
    out.write(f"=== Spawned: {cmd}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
    out.flush()

    kwargs = {"start_new_session": True} if os.name != "nt" else {}

    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=str(work_dir),
        stdout=out,
        stderr=subprocess.STDOUT,
        **kwargs
    )

    meta = {
        "task_id": task_id,
        "pid": proc.pid,
        "cmd": cmd,
        "cwd": str(work_dir),
        "start_time": start_time,
        "log_file": str(log_file),
    }
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"SPAWNED: task_id={task_id} pid={proc.pid} log={log_file}")


def cmd_status(task_id: str) -> None:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    meta_file = log_dir / f"{task_id}.json"
    if not meta_file.is_file():
        print(f"ERROR: Task {task_id} not found", file=sys.stderr)
        sys.exit(1)

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    pid = meta["pid"]
    alive = False
    try:
        if os.name != "nt":
            os.kill(pid, 0)
            alive = True
        else:
            proc = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            alive = str(pid) in proc.stdout
    except OSError:
        alive = False

    runtime = time.time() - meta["start_time"]
    status_str = "RUNNING" if alive else "FINISHED"

    log_file = Path(meta["log_file"])
    tail_str = ""
    if log_file.is_file():
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        tail_str = "\n".join(lines[-5:]) if lines else ""

    print(f"TASK: {task_id} | Status: {status_str} | PID: {pid} | Runtime: {runtime:.1f}s")
    if tail_str:
        print(f"--- Last 5 lines ---\n{tail_str}")


def cmd_kill(task_id: str) -> None:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    meta_file = log_dir / f"{task_id}.json"
    if not meta_file.is_file():
        print(f"ERROR: Task {task_id} not found", file=sys.stderr)
        sys.exit(1)

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    pid = meta["pid"]
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            time.sleep(0.3)
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)])
        print(f"OK: Task {task_id} (PID {pid}) terminated.")
    except Exception as e:
        print(f"ERROR: Failed to kill PID {pid}: {e}", file=sys.stderr)


def cmd_logs(task_id: str, lines: int = 50, follow: bool = False) -> None:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    meta_file = log_dir / f"{task_id}.json"
    log_file = log_dir / f"{task_id}.log"

    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if "log_file" in meta:
                log_file = Path(meta["log_file"])
        except Exception:
            pass

    if not log_file.is_file():
        print(f"ERROR: Log file for task {task_id} not found at {log_file}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            if lines > 0:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    sys.stdout.write(line)
                sys.stdout.flush()
            else:
                f.seek(0, os.SEEK_END)

            if not follow:
                return

            # Follow / streaming mode (tail -f)
            while True:
                line = f.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"ERROR: Failed reading log: {e}", file=sys.stderr)
        sys.exit(1)


def handle_ipc_mode() -> None:
    """Reads a JSON request from stdin and executes it without bash shell escaping."""
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as e:
        print(f"ERROR: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    action = payload.get("action")
    args = payload.get("args", {})

    if action == "view":
        cmd_view(args.get("path"), args.get("start", 1), args.get("end", 100))
    elif action == "outline":
        cmd_outline(args.get("path"))
    elif action == "get_fn":
        cmd_get_fn(args.get("path"), args.get("name"))
    elif action == "patch":
        cmd_patch(args.get("path"), args.get("old"), args.get("new"), args.get("all", False))
    elif action == "rollback":
        cmd_rollback(args.get("path"))
    elif action == "tree":
        cmd_tree(args.get("path", "."), args.get("depth", 2))
    elif action == "grep":
        cmd_grep(args.get("query"), args.get("path", "."), args.get("max", 20))
    elif action == "run":
        cmd_run(args.get("cmd"), args.get("cwd"), args.get("tail", 15), args.get("timeout"))
    elif action == "spawn":
        cmd_spawn(args.get("cmd"), args.get("cwd"))
    elif action == "status":
        cmd_status(args.get("task_id"))
    elif action == "logs":
        cmd_logs(args.get("task_id"), args.get("lines", 50), args.get("follow", False))
    elif action == "kill":
        cmd_kill(args.get("task_id"))
    else:
        print(f"ERROR: Unknown action '{action}'", file=sys.stderr)
        sys.exit(1)


def main():
    if "--ipc" in sys.argv:
        handle_ipc_mode()
        return

    parser = argparse.ArgumentParser(description="Universal High-Efficiency AgentBox Worker")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_view = sub.add_parser("view")
    p_view.add_argument("path")
    p_view.add_argument("--start", type=int, default=1)
    p_view.add_argument("--end", type=int, default=100)

    p_out = sub.add_parser("outline")
    p_out.add_argument("path")

    p_fn = sub.add_parser("get-fn")
    p_fn.add_argument("path")
    p_fn.add_argument("name")

    p_patch = sub.add_parser("patch")
    p_patch.add_argument("path")
    p_patch.add_argument("--old", required=True)
    p_patch.add_argument("--new", required=True)
    p_patch.add_argument("--all", action="store_true")

    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("path")

    p_tree = sub.add_parser("tree")
    p_tree.add_argument("path", nargs="?", default=".")
    p_tree.add_argument("--depth", type=int, default=2)

    p_grep = sub.add_parser("grep")
    p_grep.add_argument("query")
    p_grep.add_argument("path", nargs="?", default=".")
    p_grep.add_argument("--max", type=int, default=20)

    p_run = sub.add_parser("run")
    p_run.add_argument("command")
    p_run.add_argument("--cwd", default=None)
    p_run.add_argument("--tail", type=int, default=15)
    p_run.add_argument("--timeout", type=int, default=None)

    p_spawn = sub.add_parser("spawn")
    p_spawn.add_argument("command")
    p_spawn.add_argument("--cwd", default=None)

    p_stat = sub.add_parser("status")
    p_stat.add_argument("task_id")

    p_logs = sub.add_parser("logs")
    p_logs.add_argument("task_id")
    p_logs.add_argument("-n", "--lines", type=int, default=50)
    p_logs.add_argument("-f", "--follow", action="store_true")

    p_kill = sub.add_parser("kill")
    p_kill.add_argument("task_id")

    args = parser.parse_args()

    if args.cmd == "view":
        cmd_view(args.path, args.start, args.end)
    elif args.cmd == "outline":
        cmd_outline(args.path)
    elif args.cmd == "get-fn":
        cmd_get_fn(args.path, args.name)
    elif args.cmd == "patch":
        cmd_patch(args.path, args.old, args.new, args.all)
    elif args.cmd == "rollback":
        cmd_rollback(args.path)
    elif args.cmd == "tree":
        cmd_tree(args.path, args.depth)
    elif args.cmd == "grep":
        cmd_grep(args.query, args.path, args.max)
    elif args.cmd == "run":
        cmd_run(args.command, args.cwd, args.tail, args.timeout)
    elif args.cmd == "spawn":
        cmd_spawn(args.command, args.cwd)
    elif args.cmd == "status":
        cmd_status(args.task_id)
    elif args.cmd == "logs":
        cmd_logs(args.task_id, args.lines, args.follow)
    elif args.cmd == "kill":
        cmd_kill(args.task_id)


if __name__ == "__main__":
    main()
