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
from .config import get_config, save_global_config, save_local_config
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

    # view
    p_view = sub.add_parser("view", help="View slice of file with line numbers")
    p_view.add_argument("path", help="Path to file")
    p_view.add_argument("--start", type=int, default=1, help="Start line (default: 1)")
    p_view.add_argument("--end", type=int, default=100, help="End line (default: 100)")

    # outline
    p_out = sub.add_parser("outline", help="Extract AST outline (classes, functions, methods)")
    p_out.add_argument("path", help="Path to file (Python, Rust, JS, TS, C, Go)")

    # get-fn
    p_fn = sub.add_parser("get-fn", help="Extract specific function or class definition")
    p_fn.add_argument("path", help="Path to file")
    p_fn.add_argument("name", help="Name of function or class")

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

    host = args.host
    cwd = args.cwd

    if args.cmd == "view":
        code = execute_action(host, cwd, "view", {"path": args.path, "start": args.start, "end": args.end})
    elif args.cmd == "outline":
        code = execute_action(host, cwd, "outline", {"path": args.path})
    elif args.cmd == "get-fn":
        code = execute_action(host, cwd, "get_fn", {"path": args.path, "name": args.name})
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
    elif args.cmd == "spawn":
        code = execute_action(host, cwd, "spawn", {"cmd": args.command, "cwd": cwd})
    elif args.cmd == "status":
        code = execute_action(host, cwd, "status", {"task_id": args.task_id})
    elif args.cmd == "logs":
        code = execute_action(host, cwd, "logs", {"task_id": args.task_id, "lines": args.lines, "follow": args.follow})
    elif args.cmd == "kill":
        code = execute_action(host, cwd, "kill", {"task_id": args.task_id})
    else:
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
