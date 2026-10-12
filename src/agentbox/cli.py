#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentbox.cli — Command-line interface for AgentBox.
Entry point for 'agentbox' executable installed via pip.
"""

import sys
import argparse
from typing import List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import __version__
from .config import get_config, save_global_config, save_local_config, generate_rules, get_tasks, add_task, remove_task
from .client import execute_action


def create_parser(default_cfg: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentbox",
        description=f"AgentBox v{__version__} — Token-efficient execution and AST code tools for AI agents."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default=default_cfg.get("host", ""), help="Target SSH host (e.g. user@server, or empty for local)")
    parser.add_argument("--cwd", default=default_cfg.get("cwd", ""), help="Target working directory")
    parser.add_argument("--venv", default=None, help="Target virtualenv path (auto-detected if omitted)")

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
    p_out = sub.add_parser("outline", help="Extract AST outline (classes, functions, methods)")
    p_out.add_argument("path", help="Path to file (Python, Rust, JS, TS, C, Go)")

    # get-fn
    # get-fn
    p_fn = sub.add_parser("get-fn", help="Extract specific function or class definition")
    p_fn.add_argument("path", help="Path to file")
    p_fn.add_argument("name", help="Name of function or class")

    # write
    p_write = sub.add_parser("write", help="Safely write or append content to file without bash quoting issues")
    p_write.add_argument("path", help="Path to target file")
    p_write.add_argument("--content", default=None, help="File content (reads from stdin if --stdin is specified)")
    p_write.add_argument("--stdin", action="store_true", help="Read content from stdin")
    p_write.add_argument("--append", action="store_true", help="Append instead of overwrite")

    # patch
    p_patch = sub.add_parser("patch", help="Atomic find-and-replace with auto-backup")
    p_patch.add_argument("path", help="Path to file")
    p_patch.add_argument("--old", required=True, help="Exact target text to replace")
    p_patch.add_argument("--new", required=True, help="Replacement text")
    p_patch.add_argument("--all", action="store_true", help="Replace all occurrences (default: exactly 1)")

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
    p_run.add_argument("command", help="Shell command to execute")
    p_run.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_run.add_argument("--tail", type=int, default=default_cfg.get("tail", 15), help="Lines of log tail to display")
    p_run.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")

    # test
    p_test = sub.add_parser("test", help="High-signal test runner: silences passing tests, extracts tracebacks on failure")
    p_test.add_argument("command", help="Test command to run (pytest, cargo test, npm test, etc.)")
    p_test.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_test.add_argument("--max-lines", type=int, default=30, help="Max failure traceback lines to output")
    p_test.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")

    # spawn
    p_spawn = sub.add_parser("spawn", help="Spawn detached background process (survives disconnects)")
    p_spawn.add_argument("command", help="Shell command to spawn")
    p_spawn.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")

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

    return parser


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
        code = execute_action(host, cwd, "run", {
            "cmd": resolved_cmd,
            "cwd": cwd,
            "tail": cfg.get("tail", 15),
            "timeout": cfg.get("timeout", None),
            "venv": venv
        })
        return code

    host = args.host
    cwd = args.cwd
    venv = getattr(args, "cmd_venv", None) or getattr(args, "venv", None) or cfg.get("venv", "")

    if args.cmd == "view":
        code = execute_action(host, cwd, "view", {"path": args.path, "start": args.start, "end": args.end})
    elif args.cmd == "outline":
        code = execute_action(host, cwd, "outline", {"path": args.path})
    elif args.cmd == "get-fn":
        code = execute_action(host, cwd, "get_fn", {"path": args.path, "name": args.name})
    elif args.cmd == "write":
        content = args.content
        if content is None:
            if getattr(args, "stdin", False):
                content = sys.stdin.read()
            else:
                print("ERROR: Provide content via --content \"...\" or pass --stdin to read from standard input.", file=sys.stderr)
                return 1
        code = execute_action(host, cwd, "write", {"path": args.path, "content": content, "append": args.append})
    elif args.cmd == "patch":
        code = execute_action(host, cwd, "patch", {"path": args.path, "old": args.old, "new": args.new, "all": args.all})
    elif args.cmd == "rollback":
        code = execute_action(host, cwd, "rollback", {"path": args.path})
    elif args.cmd == "tree":
        code = execute_action(host, cwd, "tree", {"path": args.path or cwd, "depth": args.depth})
    elif args.cmd == "grep":
        code = execute_action(host, cwd, "grep", {"query": args.query, "path": args.path or cwd, "max": args.max})
    elif args.cmd == "run":
        code = execute_action(host, cwd, "run", {"cmd": args.command, "cwd": cwd, "tail": args.tail, "timeout": args.timeout, "venv": venv})
    elif args.cmd == "test":
        code = execute_action(host, cwd, "test", {"cmd": args.command, "cwd": cwd, "timeout": args.timeout, "max_lines": args.max_lines, "venv": venv})
    elif args.cmd == "spawn":
        code = execute_action(host, cwd, "spawn", {"cmd": args.command, "cwd": cwd, "venv": venv})
    elif args.cmd == "status":
        code = execute_action(host, cwd, "status", {"task_id": args.task_id})
    elif args.cmd == "logs":
        code = execute_action(host, cwd, "logs", {"task_id": args.task_id, "lines": args.lines, "follow": args.follow})
    elif args.cmd == "kill":
        code = execute_action(host, cwd, "kill", {"task_id": args.task_id})
    elif args.cmd == "graphify-install":
        code = execute_action(host, cwd, "graphify_install", {"upgrade": args.upgrade})
    elif args.cmd == "graphify-build":
        code = execute_action(host, cwd, "graphify_build", {"path": args.path or cwd, "deep": args.deep, "venv": venv})
    elif args.cmd == "graphify-query":
        code = execute_action(host, cwd, "graphify_query", {"question": args.question, "path": args.path or cwd, "max_tokens": args.max_tokens, "venv": venv})
    elif args.cmd == "git-status":
        code = execute_action(host, cwd, "git_status", {"path": args.path or cwd})
    elif args.cmd == "diff":
        code = execute_action(host, cwd, "diff", {"path": args.path or cwd, "rev": args.rev, "cached": args.cached, "max_lines": args.max_lines})
    elif args.cmd == "git-log":
        code = execute_action(host, cwd, "git_log", {"path": args.path or cwd, "limit": args.limit})
    elif args.cmd == "git-view":
        code = execute_action(host, cwd, "git_view", {"path": args.path, "rev": args.rev, "start": args.start, "end": args.end})
    elif args.cmd == "git-fn-history":
        code = execute_action(host, cwd, "git_fn_history", {"path": args.path, "name": args.name, "limit": args.limit})
    else:
        code = 1

    return code


if __name__ == "__main__":
    sys.exit(main())
