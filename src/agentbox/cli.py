#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentbox.cli — Command-line interface for AgentBox.
Entry point for 'agentbox' executable installed via pip.
"""

import sys
import argparse
from typing import List, Optional

from . import __version__
from .config import get_config, save_global_config, save_local_config, generate_rules
from .client import execute_action


def create_parser(default_cfg: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentbox",
        description=f"AgentBox v{__version__} — Token-efficient execution and AST code tools for AI agents."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default=default_cfg.get("host", ""), help="Target SSH host (e.g. user@server, or empty for local)")
    parser.add_argument("--cwd", default=default_cfg.get("cwd", ""), help="Target working directory")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # config command
    p_cfg = sub.add_parser("config", help="View or update host and directory settings")
    p_cfg.add_argument("--set-host", help="Set default SSH host")
    p_cfg.add_argument("--set-cwd", help="Set default directory")
    p_cfg.add_argument("--global", dest="is_global", action="store_true", help="Save globally to ~/.agentbox/config.json")

    # init-rules command
    p_rules = sub.add_parser("init-rules", help="Generate AI agent rules (.cursorrules, AGENTS.md, CLAUDE.md) enforcing agentbox-only remote work")
    p_rules.add_argument("--type", choices=["all", "cursor", "agents", "claude"], default="all", help="Target rule format (default: all)")

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
    p_write.add_argument("--content", default=None, help="File content (reads from stdin if omitted)")
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
    p_run.add_argument("--tail", type=int, default=default_cfg.get("tail", 15), help="Lines of log tail to display")
    p_run.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")

    # test
    p_test = sub.add_parser("test", help="High-signal test runner: silences passing tests, extracts tracebacks on failure")
    p_test.add_argument("command", help="Test command to run (pytest, cargo test, npm test, etc.)")
    p_test.add_argument("--max-lines", type=int, default=30, help="Max failure traceback lines to output")
    p_test.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")

    # spawn
    p_spawn = sub.add_parser("spawn", help="Spawn detached background process (survives disconnects)")
    p_spawn.add_argument("command", help="Shell command to spawn")

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
    p_gb.add_argument("--deep", action="store_true", help="Run deep extraction mode")

    # graphify-query
    p_gq = sub.add_parser("graphify-query", help="Query knowledge graph without blowing LLM token budget")
    p_gq.add_argument("question", help="Natural language query or concept name")
    p_gq.add_argument("path", nargs="?", default="", help="Project path with graphify-out")
    p_gq.add_argument("--max-tokens", type=int, default=1500, help="Max token output budget")

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

    host = args.host
    cwd = args.cwd

    if args.cmd == "view":
        code = execute_action(host, cwd, "view", {"path": args.path, "start": args.start, "end": args.end})
    elif args.cmd == "outline":
        code = execute_action(host, cwd, "outline", {"path": args.path})
    elif args.cmd == "get-fn":
        code = execute_action(host, cwd, "get_fn", {"path": args.path, "name": args.name})
    elif args.cmd == "write":
        content = args.content
        if content is None and not sys.stdin.isatty():
            content = sys.stdin.read()
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
        code = execute_action(host, cwd, "run", {"cmd": args.command, "cwd": cwd, "tail": args.tail, "timeout": args.timeout})
    elif args.cmd == "test":
        code = execute_action(host, cwd, "test", {"cmd": args.command, "cwd": cwd, "timeout": args.timeout, "max_lines": args.max_lines})
    elif args.cmd == "spawn":
        code = execute_action(host, cwd, "spawn", {"cmd": args.command, "cwd": cwd})
    elif args.cmd == "status":
        code = execute_action(host, cwd, "status", {"task_id": args.task_id})
    elif args.cmd == "logs":
        code = execute_action(host, cwd, "logs", {"task_id": args.task_id, "lines": args.lines, "follow": args.follow})
    elif args.cmd == "kill":
        code = execute_action(host, cwd, "kill", {"task_id": args.task_id})
    elif args.cmd == "graphify-install":
        code = execute_action(host, cwd, "graphify_install", {"upgrade": args.upgrade})
    elif args.cmd == "graphify-build":
        code = execute_action(host, cwd, "graphify_build", {"path": args.path or cwd, "deep": args.deep})
    elif args.cmd == "graphify-query":
        code = execute_action(host, cwd, "graphify_query", {"question": args.question, "path": args.path or cwd, "max_tokens": args.max_tokens})
    else:
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
