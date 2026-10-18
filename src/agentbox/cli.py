#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentbox.cli — Command-line interface for AgentBox.
Entry point for 'agentbox' executable installed via pip.
"""

import sys
import argparse
from typing import List, Optional, Any, Union

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


def read_stdin_utf8() -> str:
    """Reads all content from stdin safely, handling UTF-8 (with or without BOM), Windows CP1251, and other encodings."""
    try:
        if hasattr(sys.stdin, "buffer"):
            raw_bytes = sys.stdin.buffer.read()
            try:
                return raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    return raw_bytes.decode("cp1251")
                except UnicodeDecodeError:
                    return raw_bytes.decode("utf-8-sig", errors="replace")
        text = sys.stdin.read()
        return text.lstrip("\ufeff")
    except Exception:
        try:
            return sys.stdin.read().lstrip("\ufeff")
        except Exception:
            return ""


from . import __version__
from .config import get_config, save_global_config, save_local_config, generate_rules, get_tasks, add_task, remove_task
from .client import execute_action, status_daemon, stop_daemon


class AgentBoxParser(argparse.ArgumentParser):
    """Custom parser that allows flexible command trailing flags for run, test, spawn, pip."""
    def parse_args(self, args=None, namespace=None):
        res = super().parse_args(args, namespace)
        if getattr(res, "cmd", None) == "outline" and hasattr(res, "path"):
            if isinstance(res.path, list) and len(res.path) == 1:
                res.path = res.path[0]
        if getattr(res, "cmd", None) in ("run", "test", "spawn", "pip") and hasattr(res, "command"):
            cmd_list = res.command or []
            new_cmd = []
            i = 0
            while i < len(cmd_list):
                token = cmd_list[i]
                if token == "--":
                    new_cmd.extend(cmd_list[i + 1:])
                    break
                elif token == "--venv" and i + 1 < len(cmd_list):
                    res.cmd_venv = cmd_list[i + 1]
                    i += 2
                elif token.startswith("--venv="):
                    res.cmd_venv = token.split("=", 1)[1]
                    i += 1
                elif token == "--tail" and i + 1 < len(cmd_list):
                    try:
                        res.tail = int(cmd_list[i + 1])
                    except ValueError:
                        pass
                    i += 2
                elif token.startswith("--tail="):
                    try:
                        res.tail = int(token.split("=", 1)[1])
                    except ValueError:
                        pass
                    i += 1
                elif token == "--timeout" and i + 1 < len(cmd_list):
                    try:
                        res.timeout = int(cmd_list[i + 1])
                    except ValueError:
                        pass
                    i += 2
                elif token.startswith("--timeout="):
                    try:
                        res.timeout = int(token.split("=", 1)[1])
                    except ValueError:
                        pass
                    i += 1
                elif token in ("--max-lines", "--max_lines") and i + 1 < len(cmd_list):
                    try:
                        res.max_lines = int(cmd_list[i + 1])
                    except ValueError:
                        pass
                    i += 2
                elif token.startswith("--max-lines=") or token.startswith("--max_lines="):
                    try:
                        res.max_lines = int(token.split("=", 1)[1])
                    except ValueError:
                        pass
                    i += 1
                else:
                    new_cmd.append(token)
                    i += 1
            res.command = new_cmd
        return res


def create_parser(default_cfg: dict) -> argparse.ArgumentParser:
    parser = AgentBoxParser(
        prog="agentbox",
        description=f"AgentBox v{__version__} — Token-efficient execution and AST code tools for AI agents."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default=default_cfg.get("host", ""), help="Target SSH host (e.g. user@server, or empty for local)")
    parser.add_argument("--cwd", default=default_cfg.get("cwd", ""), help="Target working directory")
    parser.add_argument("--venv", default=None, help="Target virtualenv path (auto-detected if omitted)")
    parser.add_argument("--no-daemon", action="store_true", help="Bypass persistent daemon bridge and run direct SSH")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # config command
    p_cfg = sub.add_parser("config", help="View or update host, directory, and virtualenv settings")
    p_cfg.add_argument("--set-host", help="Set default SSH host")
    p_cfg.add_argument("--set-cwd", help="Set default directory")
    p_cfg.add_argument("--set-venv", help="Set default virtualenv path (or empty string to clear)")
    p_cfg.add_argument("--global", dest="is_global", action="store_true", help="Save globally to ~/.agentbox/config.json")

    # init-rules command
    p_rules = sub.add_parser("init-rules", help="Generate AI agent rules (.cursorrules, AGENTS.md, CLAUDE.md) enforcing agentbox-only remote work")
    p_rules.add_argument("--type", choices=["all", "cursor", "agents", "claude"], default="all", help="Target rule format (default: all)")

    # task command
    p_task = sub.add_parser("task", help="Project Tasks & Recipes: list, run, add, or remove task automation recipes")
    p_task.add_argument("task_action", nargs="?", default=None, help="Task name, 'list', 'add', or 'rm' / 'remove'")
    p_task.add_argument("task_args", nargs=argparse.REMAINDER, default=[], help="Arguments for the task or command definition for add")

    # view
    p_view = sub.add_parser("view", help="View slice of file with line numbers")
    p_view.add_argument("path", help="Path to file")
    p_view.add_argument("--start", type=int, default=1, help="Start line (default: 1)")
    p_view.add_argument("--end", type=int, default=100, help="End line (default: 100)")

    # outline
    p_out = sub.add_parser("outline", help="Extract AST outline (classes, functions, methods) for one or more files/dirs")
    p_out.add_argument("path", nargs="+", help="Path(s) to file or directory (Python, Rust, JS, TS, C, Go)")

    # get-fn
    p_fn = sub.add_parser("get-fn", help="Extract specific function, method (Class.method), or class definition")
    p_fn.add_argument("path", help="Path to file")
    p_fn.add_argument("name", help="Name of function, class, or ClassName.method_name")

    # write
    p_write = sub.add_parser("write", help="Safely write or append content to file without bash quoting issues")
    p_write.add_argument("path", help="Path to target file")
    p_write.add_argument("--content", default=None, help="File content (reads from stdin if --stdin is specified)")
    p_write.add_argument("--stdin", action="store_true", help="Read content from stdin")
    p_write.add_argument("--append", action="store_true", help="Append instead of overwrite")

    # patch
    p_patch = sub.add_parser("patch", help="Atomic find-and-replace with auto-backup and Python AST validation")
    p_patch.add_argument("path", help="Path to file")
    p_patch.add_argument("--old", default=None, help="Target text to replace")
    p_patch.add_argument("--new", default=None, help="Replacement text")
    p_patch.add_argument("--old-file", default=None, help="Read target text to replace from a local file")
    p_patch.add_argument("--new-file", default=None, help="Read replacement text from a local file")
    p_patch.add_argument("--all", action="store_true", help="Replace all occurrences (default: exactly 1)")
    p_patch.add_argument("--no-check", dest="check_syntax", action="store_false", help="Skip Python AST syntax check")

    # patch-lines
    p_pl = sub.add_parser("patch-lines", help="Atomically replace a 1-indexed line range [start..end] with new content")
    p_pl.add_argument("path", help="Path to file")
    p_pl.add_argument("--start", type=int, required=True, help="Start line (1-indexed, inclusive)")
    p_pl.add_argument("--end", type=int, required=True, help="End line (1-indexed, inclusive)")
    p_pl.add_argument("--content", default=None, help="Replacement text (or pass --stdin)")
    p_pl.add_argument("--stdin", action="store_true", help="Read replacement content from stdin")
    p_pl.add_argument("--no-check", dest="check_syntax", action="store_false", help="Skip Python AST syntax check")

    # rollback
    p_rb = sub.add_parser("rollback", help="Restore file from automatic .bak backup")
    p_rb.add_argument("path", help="Path to file")

    # tree
    p_tree = sub.add_parser("tree", help="Compact directory tree ignoring build artifacts and VCS")
    p_tree.add_argument("path", nargs="?", default="", help="Directory path")
    p_tree.add_argument("--depth", type=int, default=2, help="Max depth (default: 2)")

    # grep
    p_grep = sub.add_parser("grep", help="Fast text search with limits")
    p_grep.add_argument("query", help="Search query or regex")
    p_grep.add_argument("path", nargs="?", default="", help="Directory path")
    p_grep.add_argument("--max", type=int, default=20, help="Max results (default: 20)")

    # run
    p_run = sub.add_parser("run", help="Silent execution: suppresses noise, buffers to log, notifies on completion")
    p_run.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_run.add_argument("--tail", type=int, default=default_cfg.get("tail", 15), help="Lines of log tail to display")
    p_run.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")
    p_run.add_argument("command", nargs=argparse.REMAINDER, help="Shell command to execute")

    # test
    p_test = sub.add_parser("test", help="High-signal test runner: silences passing tests, extracts tracebacks on failure")
    p_test.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_test.add_argument("--max-lines", type=int, default=30, help="Max failure traceback lines to output")
    p_test.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")
    p_test.add_argument("command", nargs=argparse.REMAINDER, help="Test command to run (pytest, cargo test, npm test, etc.)")

    # pip
    p_pip = sub.add_parser("pip", help="Run pip inside isolated virtualenv (auto-creates .agentbox/venv if needed)")
    p_pip.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path")
    p_pip.add_argument("command", nargs=argparse.REMAINDER, help="Arguments passed to pip (e.g. install pytest)")

    # stats
    p_stats = sub.add_parser("stats", help="Display token savings and command execution dashboard")
    p_stats.add_argument("--clear", action="store_true", help="Clear recorded statistics")

    # batch
    p_batch = sub.add_parser("batch", help="Execute multiple AgentBox actions in a single call to save agent turns")
    p_batch.add_argument("steps", nargs="?", default=None, help="JSON array of action steps")
    p_batch.add_argument("--stdin", action="store_true", help="Read JSON batch array from stdin")
    p_batch.add_argument("--continue-on-error", dest="stop_on_error", action="store_false", help="Continue executing remaining steps if a step fails")

    # mcp
    sub.add_parser("mcp", help="Start built-in Model Context Protocol (MCP) server over stdio")

    # spawn
    p_spawn = sub.add_parser("spawn", help="Spawn detached background process (survives disconnects)")
    p_spawn.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_spawn.add_argument("command", nargs=argparse.REMAINDER, help="Shell command to spawn")

    # status
    p_stat = sub.add_parser("status", help="Check status of background task")
    p_stat.add_argument("task_id", help="Task ID from spawn command")

    # logs / tail
    p_logs = sub.add_parser("logs", help="View or stream log output of background task")
    p_logs.add_argument("task_id", help="Task ID from spawn command")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Number of trailing lines (default: 50)")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Continuously stream new log output (tail -f)")

    # kill
    p_kill = sub.add_parser("kill", help="Terminate background task")
    p_kill.add_argument("task_id", help="Task ID from spawn command")

    # graphify-install
    p_gi = sub.add_parser("graphify-install", help="Silently install or update graphifyy on target host")
    p_gi.add_argument("--upgrade", action="store_true", help="Upgrade graphifyy to latest version")

    # graphify-build
    p_gb = sub.add_parser("graphify-build", help="Build knowledge graph of target project silently")
    p_gb.add_argument("path", nargs="?", default="", help="Project path to build graph for")
    p_gb.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path")
    p_gb.add_argument("--deep", action="store_true", help="Run deep extraction mode")

    # graphify-query
    p_gq = sub.add_parser("graphify-query", help="Query knowledge graph without blowing LLM token budget")
    p_gq.add_argument("question", help="Natural language query or concept name")
    p_gq.add_argument("path", nargs="?", default="", help="Project path with graphify-out")
    p_gq.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path")
    p_gq.add_argument("--max-tokens", type=int, default=1500, help="Max token output budget")

    # git-status
    p_gs = sub.add_parser("git-status", help="Compact git status showing changed files and diff counts")
    p_gs.add_argument("path", nargs="?", default="", help="Path or directory (default: repo root)")

    # diff
    p_diff = sub.add_parser("diff", help="Token-efficient git diff ignoring whitespace and lockfiles")
    p_diff.add_argument("path", nargs="?", default="", help="Path to file or directory")
    p_diff.add_argument("--rev", default=None, help="Git revision or range (e.g. HEAD~1, main..HEAD)")
    p_diff.add_argument("--cached", "--staged", dest="cached", action="store_true", help="View staged changes")
    p_diff.add_argument("--max-lines", type=int, default=100, help="Max diff output lines (default: 100)")

    # git-log
    p_gl = sub.add_parser("git-log", help="Compact one-line git commit history")
    p_gl.add_argument("path", nargs="?", default="", help="Path to file or directory")
    p_gl.add_argument("-n", "--limit", type=int, default=5, help="Number of commits (default: 5)")

    # git-view
    p_gv = sub.add_parser("git-view", help="View line slice of a file from any Git revision without downloading full file")
    p_gv.add_argument("path", help="Path to file")
    p_gv.add_argument("rev", nargs="?", default="HEAD", help="Git revision (commit hash, branch, or HEAD~N, default: HEAD)")
    p_gv.add_argument("--start", type=int, default=1, help="Start line (default: 1)")
    p_gv.add_argument("--end", type=int, default=100, help="End line (default: 100)")

    # git-fn-history
    p_gfh = sub.add_parser("git-fn-history", help="Trace modification history of a specific function or class across Git commits")
    p_gfh.add_argument("path", help="Path to file")
    p_gfh.add_argument("name", help="Name of function or class")
    p_gfh.add_argument("-n", "--limit", type=int, default=3, help="Max revisions to inspect (default: 3)")

    # find-fn
    p_ff = sub.add_parser("find-fn", help="Locate functions or classes across project via fast AST analysis")
    p_ff.add_argument("name", help="Name or substring of function/class to locate")
    p_ff.add_argument("path", nargs="?", default="", help="Directory to search (default: current working directory)")
    p_ff.add_argument("--exact", action="store_true", help="Exact name match only (case-sensitive)")
    p_ff.add_argument("--max", dest="max_results", type=int, default=30, help="Max results (default: 30)")

    # refs
    p_refs = sub.add_parser("refs", help="Find symbol references (imports, calls, attributes, inheritance) across project")
    p_refs.add_argument("name", help="Symbol name to search references for")
    p_refs.add_argument("path", nargs="?", default="", help="Directory or file to search (default: current working directory)")
    p_refs.add_argument("--max", dest="max_results", type=int, default=40, help="Max results (default: 40)")

    # daemon
    p_daemon = sub.add_parser("daemon", help="Manage persistent background daemon connections")
    p_daemon.add_argument("daemon_action", choices=["status", "stop"], nargs="?", default="status", help="Action: status or stop (default: status)")
    p_daemon.add_argument("daemon_host", nargs="?", default=None, help="Target remote host (optional)")

    return parser


def _resolve_cmd_string(cmd_arg: Any) -> str:
    """Combines list of command tokens or raw command string safely."""
    if isinstance(cmd_arg, list):
        if cmd_arg and cmd_arg[0] == "--":
            cmd_arg = cmd_arg[1:]
        return " ".join(cmd_arg).strip()
    return (cmd_arg or "").strip()


def main(argv: Optional[List[str]] = None):
    cfg = get_config()
    parser = create_parser(cfg)
    args = parser.parse_args(argv)

    if args.cmd == "config":
        updates = {}
        if args.set_host is not None:
            updates["host"] = args.set_host
        if args.set_cwd is not None:
            updates["cwd"] = args.set_cwd
        if args.set_venv is not None:
            updates["venv"] = args.set_venv

        if updates:
            if args.is_global:
                save_global_config(updates)
                print(f"Global config updated (~/.agentbox/config.json): {updates}")
            else:
                save_local_config(updates)
                print(f"Local config updated (.agentbox.json): {updates}")
        else:
            print("Current configuration:")
            for k, v in cfg.items():
                print(f"  {k}: {v}")
        return 0

    if args.cmd == "init-rules":
        generate_rules(args.type)
        return 0

    if args.cmd == "task":
        action = args.task_action
        task_args = args.task_args or []

        # 1. agentbox task / agentbox task list
        if not action or action == "list":
            tasks = get_tasks()
            if not tasks:
                print("No tasks defined in .agentbox.json.")
                print("Add one with: agentbox task add <name> \"<command>\"")
            else:
                print(f"=== PROJECT TASKS ({len(tasks)}) ===")
                for name, cmd_str in sorted(tasks.items()):
                    print(f"  {name:15} : {cmd_str}")
            return 0

        # 2. agentbox task add <name> "<command>"
        if action == "add":
            if not task_args:
                print("ERROR: Missing task name and command. Usage: agentbox task add <name> \"<command>\"", file=sys.stderr)
                return 1
            task_name = task_args[0]
            if len(task_args) < 2:
                print(f"ERROR: Missing command for task '{task_name}'. Usage: agentbox task add <name> \"<command>\"", file=sys.stderr)
                return 1
            cmd_str = " ".join(task_args[1:])
            add_task(task_name, cmd_str)
            print(f"OK: Task '{task_name}' saved to .agentbox.json.")
            return 0

        # 3. agentbox task rm / remove <name>
        if action in ("rm", "remove"):
            if not task_args:
                print("ERROR: Missing task name. Usage: agentbox task rm <name>", file=sys.stderr)
                return 1
            task_name = task_args[0]
            if remove_task(task_name):
                print(f"OK: Task '{task_name}' removed from .agentbox.json.")
                return 0
            else:
                print(f"ERROR: Task '{task_name}' not found in .agentbox.json.", file=sys.stderr)
                return 1

        # 4. agentbox task <name> [args...]
        task_name = action
        tasks = get_tasks()
        if task_name not in tasks:
            print(f"ERROR: Task '{task_name}' not found.", file=sys.stderr)
            print("Run 'agentbox task' to see available tasks, or 'agentbox task add <name> \"<command>\"' to add it.", file=sys.stderr)
            return 1

        raw_cmd = tasks[task_name]
        joined_args = " ".join(task_args)

        if "{args}" in raw_cmd:
            resolved_cmd = raw_cmd.replace("{args}", joined_args).strip()
        elif "$@" in raw_cmd:
            resolved_cmd = raw_cmd.replace("$@", joined_args).strip()
        elif joined_args:
            resolved_cmd = f"{raw_cmd} {joined_args}".strip()
        else:
            resolved_cmd = raw_cmd

        # Silent execution pipeline via run action
        host = args.host
        cwd = args.cwd
        venv = getattr(args, "cmd_venv", None) or getattr(args, "venv", None) or cfg.get("venv", "")
        act_kwargs = {"use_daemon": False} if getattr(args, "no_daemon", False) else {}
        code = execute_action(host, cwd, "run", {
            "cmd": resolved_cmd,
            "cwd": cwd,
            "tail": cfg.get("tail", 15),
            "timeout": cfg.get("timeout", None),
            "venv": venv
        }, **act_kwargs)
        return code

    if args.cmd == "daemon":
        if args.daemon_action == "stop":
            return stop_daemon(args.daemon_host or args.host)
        else:
            return status_daemon(args.daemon_host)

    host = args.host
    cwd = args.cwd
    venv = getattr(args, "cmd_venv", None) or getattr(args, "venv", None) or cfg.get("venv", "")

    if args.cmd == "mcp":
        from .mcp_server import run_mcp_server
        return run_mcp_server(host=host, cwd=cwd, venv=venv)

    def run_action(action: str, act_args: dict) -> int:
        if getattr(args, "no_daemon", False):
            return execute_action(host, cwd, action, act_args, use_daemon=False)
        return execute_action(host, cwd, action, act_args)

    if args.cmd == "view":
        code = run_action("view", {"path": args.path, "start": args.start, "end": args.end})
    elif args.cmd == "outline":
        code = run_action("outline", {"path": args.path})
    elif args.cmd == "get-fn":
        code = run_action("get_fn", {"path": args.path, "name": args.name})
    elif args.cmd == "find-fn":
        code = run_action("find_fn", {"name": args.name, "path": args.path or cwd, "exact": args.exact, "max": args.max_results})
    elif args.cmd == "refs":
        code = run_action("refs", {"name": args.name, "path": args.path or cwd, "max": args.max_results})
    elif args.cmd == "write":
        content = args.content
        if content is None:
            if getattr(args, "stdin", False):
                content = read_stdin_utf8()
            else:
                print("ERROR: Provide content via --content \"...\" or pass --stdin to read from standard input.", file=sys.stderr)
                return 1
        code = run_action("write", {"path": args.path, "content": content, "append": args.append})
    elif args.cmd == "patch":
        old_val = args.old
        new_val = args.new
        if old_val is None and getattr(args, "old_file", None):
            from pathlib import Path as _P
            old_val = _P(args.old_file).read_text(encoding="utf-8")
        if new_val is None and getattr(args, "new_file", None):
            from pathlib import Path as _P
            new_val = _P(args.new_file).read_text(encoding="utf-8")
        if old_val is None or new_val is None:
            print("ERROR: Provide --old and --new (or --old-file / --new-file).", file=sys.stderr)
            return 1
        code = run_action("patch", {
            "path": args.path,
            "old": old_val,
            "new": new_val,
            "all": args.all,
            "check_syntax": getattr(args, "check_syntax", True)
        })
    elif args.cmd == "patch-lines":
        content = args.content
        if content is None:
            if getattr(args, "stdin", False):
                content = read_stdin_utf8()
            else:
                print("ERROR: Provide replacement via --content \"...\" or pass --stdin.", file=sys.stderr)
                return 1
        code = run_action("patch_lines", {
            "path": args.path,
            "start": args.start,
            "end": args.end,
            "content": content,
            "check_syntax": getattr(args, "check_syntax", True)
        })
    elif args.cmd == "rollback":
        code = run_action("rollback", {"path": args.path})
    elif args.cmd == "tree":
        code = run_action("tree", {"path": args.path or cwd, "depth": args.depth})
    elif args.cmd == "grep":
        code = run_action("grep", {"query": args.query, "path": args.path or cwd, "max": args.max})
    elif args.cmd == "run":
        cmd_str = _resolve_cmd_string(args.command)
        if not cmd_str:
            print("ERROR: Missing command to execute. Usage: agentbox run <command>", file=sys.stderr)
            return 1
        code = run_action("run", {"cmd": cmd_str, "cwd": cwd, "tail": args.tail, "timeout": args.timeout, "venv": venv})
    elif args.cmd == "test":
        cmd_str = _resolve_cmd_string(args.command)
        if not cmd_str:
            print("ERROR: Missing test command to run. Usage: agentbox test <test_cmd>", file=sys.stderr)
            return 1
        code = run_action("test", {"cmd": cmd_str, "cwd": cwd, "timeout": args.timeout, "max_lines": args.max_lines, "venv": venv})
    elif args.cmd == "pip":
        pip_str = _resolve_cmd_string(args.command)
        if not pip_str:
            print("ERROR: Missing pip arguments. Usage: agentbox pip install <package>", file=sys.stderr)
            return 1
        code = run_action("pip", {"pip_args": pip_str, "cwd": cwd, "venv": venv})
    elif args.cmd == "stats":
        code = run_action("stats", {"clear": args.clear})
    elif args.cmd == "batch":
        steps_raw = args.steps
        if steps_raw is None:
            if getattr(args, "stdin", False):
                steps_raw = read_stdin_utf8()
            else:
                print("ERROR: Provide JSON steps argument or pass --stdin.", file=sys.stderr)
                return 1
        code = run_action("batch", {"steps": steps_raw, "stop_on_error": getattr(args, "stop_on_error", True)})
    elif args.cmd == "spawn":
        cmd_str = _resolve_cmd_string(args.command)
        if not cmd_str:
            print("ERROR: Missing command to spawn. Usage: agentbox spawn <command>", file=sys.stderr)
            return 1
        code = run_action("spawn", {"cmd": cmd_str, "cwd": cwd, "venv": venv})
    elif args.cmd == "status":
        code = run_action("status", {"task_id": args.task_id})
    elif args.cmd == "logs":
        code = run_action("logs", {"task_id": args.task_id, "lines": args.lines, "follow": args.follow})
    elif args.cmd == "kill":
        code = run_action("kill", {"task_id": args.task_id})
    elif args.cmd == "graphify-install":
        code = run_action("graphify_install", {"upgrade": args.upgrade})
    elif args.cmd == "graphify-build":
        code = run_action("graphify_build", {"path": args.path or cwd, "deep": args.deep, "venv": venv})
    elif args.cmd == "graphify-query":
        code = run_action("graphify_query", {"question": args.question, "path": args.path or cwd, "max_tokens": args.max_tokens, "venv": venv})
    elif args.cmd == "git-status":
        code = run_action("git_status", {"path": args.path or cwd})
    elif args.cmd == "diff":
        code = run_action("diff", {"path": args.path or cwd, "rev": args.rev, "cached": args.cached, "max_lines": args.max_lines})
    elif args.cmd == "git-log":
        code = run_action("git_log", {"path": args.path or cwd, "limit": args.limit})
    elif args.cmd == "git-view":
        code = run_action("git_view", {"path": args.path, "rev": args.rev, "start": args.start, "end": args.end})
    elif args.cmd == "git-fn-history":
        code = run_action("git_fn_history", {"path": args.path, "name": args.name, "limit": args.limit})
    else:
        code = 1

    return code


if __name__ == "__main__":
    sys.exit(main())
