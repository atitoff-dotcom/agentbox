#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentbox.cli — Command-line interface for AgentBox.
Entry point for 'agentbox' executable installed via pip.
Supports local execution and multi-host SSH execution via -t / --target and named targets.
"""

import sys
import argparse
from typing import List, Optional, Any, Union, Dict

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
import base64
import time
import re
import shlex
import subprocess
from pathlib import Path


def _format_task_command(raw_cmd: str, task_args: List[str]) -> str:
    """Formats a task command with safe argument quoting, positional placeholders {1}, {2}, $1, $2, and $@ / {args}."""
    if not task_args:
        clean = raw_cmd.replace("{args}", "").replace("$@", "")
        clean = re.sub(r'\{[0-9]+\}|\$[0-9]+', '', clean)
        return clean.strip()

    def quote_arg(arg: str) -> str:
        if sys.platform == "win32":
            return subprocess.list2cmdline([arg])
        return shlex.quote(arg)

    def join_args(args: List[str]) -> str:
        if sys.platform == "win32":
            return subprocess.list2cmdline(args)
        return shlex.join(args)

    all_joined = join_args(task_args)
    resolved_cmd = raw_cmd

    matches = re.findall(r'\{([1-9][0-9]*)\}|\$([1-9][0-9]*)', raw_cmd)
    highest_pos = 0
    if matches:
        for m1, m2 in matches:
            idx = int(m1 if m1 else m2)
            if idx > highest_pos:
                highest_pos = idx
            val = quote_arg(task_args[idx - 1]) if idx <= len(task_args) else ""
            if m1:
                resolved_cmd = resolved_cmd.replace(f"{{{m1}}}", val)
            if m2:
                resolved_cmd = resolved_cmd.replace(f"${m2}", val)

    if "{args}" in resolved_cmd:
        resolved_cmd = resolved_cmd.replace("{args}", all_joined)
    elif "$@" in resolved_cmd:
        resolved_cmd = resolved_cmd.replace("$@", all_joined)
    elif highest_pos > 0:
        if len(task_args) > highest_pos:
            remaining = join_args(task_args[highest_pos:])
            resolved_cmd = f"{resolved_cmd} {remaining}".strip()
    else:
        resolved_cmd = f"{resolved_cmd} {all_joined}".strip()

    return resolved_cmd.strip()

def decode_base64_text(val: str) -> str:
    """Decodes a base64 string to utf-8 text safely, immune to shell quoting/encoding bugs."""
    try:
        raw = base64.b64decode(val.strip())
        for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8-sig", errors="replace")
    except Exception as e:
        print(f"ERROR: Failed to decode base64 input: {e}", file=sys.stderr)
        sys.exit(1)


from .worker import parse_file_mapping


def parse_target_path(spec: str) -> Tuple[Optional[str], str]:
    """Parses [target:]path safely avoiding Windows drive letters (e.g. C:\\path)."""
    if ":" in spec:
        parts = spec.split(":", 1)
        if len(parts[0]) == 1 and parts[0].isalpha() and (parts[1].startswith("\\") or parts[1].startswith("/")):
            return None, spec
        target_name = parts[0].strip()
        path_str = parts[1].strip()
        if not target_name or target_name == "local":
            return None, path_str
        return target_name, path_str
    return None, spec


def read_stdin_utf8() -> str:
    """Reads all content from stdin safely, handling UTF-8 (with or without BOM), Windows CP1251, CP866, and other encodings."""
    try:
        if hasattr(sys.stdin, "buffer"):
            raw_bytes = sys.stdin.buffer.read()
            for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
                try:
                    return raw_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw_bytes.decode("utf-8-sig", errors="replace")
        text = sys.stdin.read()
        return text.lstrip("\ufeff")
    except Exception:
        try:
            return sys.stdin.read().lstrip("\ufeff")
        except Exception:
            return ""


from . import __version__
from .config import (
    get_config,
    save_global_config,
    save_local_config,
    generate_rules,
    sync_rules,
    get_tasks,
    add_task,
    remove_task,
    get_targets,
    get_default_target_name,
    resolve_target,
    add_target,
    remove_target,
    set_default_target,
    set_target_readonly,
    record_audit,
    get_audit_summary,
)
from .client import execute_action, status_daemon, stop_daemon


SAFE_READONLY_COMMANDS = {
    "view",
    "outline",
    "get-fn",
    "find-fn",
    "refs",
    "tree",
    "grep",
    "diff",
    "git-status",
    "git-log",
    "graphify-query",
    "graphify-open",
    "audit",
    "stats",
    "target",
    "rules",
    "init-rules",
    "config",
    "daemon",
}

SAFE_READONLY_ACTIONS = {
    "view",
    "outline",
    "get_fn",
    "find_fn",
    "refs",
    "tree",
    "grep",
    "diff",
    "git_status",
    "git_log",
    "graphify_query",
    "sync_manifest",
    "sync_pack",
    "file_read_b64",
    "cp_read",
}


HUMAN_MANUAL = """=== AgentBox Setup & Administration Guide ===

1. Target Management (Multi-Host SSH):
  agentbox target                         Show active execution target
  agentbox target list                    List all configured targets
  agentbox target add <name> --host <h>   Save target [--cwd <dir>] [--venv <v>] [--default] [--readonly]
  agentbox target readonly <name> [--off] Toggle read-only protection for target
  agentbox target use <name>              Switch active default target
  agentbox target rm <name>               Remove target from .agentbox.json

2. Project Tasks & Recipes:
  agentbox task                           List verified project recipes
  agentbox task add <name> "<cmd>"        Add/update project recipe in .agentbox.json
  agentbox task rm <name>                 Remove project recipe
  agentbox task <name> [args]             Execute saved recipe

3. Rules for AI Agents:
  agentbox rules                          Generate/refresh AGENTS.md
  agentbox rules --sync                   Sync targets and tasks into AGENTS.md

4. Ad-Hoc Execution:
  agentbox -t <target> run "<cmd>"        Run command on specified target
  agentbox -t local run "<cmd>"           Force local execution
"""


class AgentBoxParser(argparse.ArgumentParser):
    """Custom parser that silences noisy help dumps and formats concise one-line errors."""
    def error(self, message):
        sys.stderr.write(f"ERROR: {message}. See AGENTS.md for command syntax.\n")
        sys.exit(2)

    def format_help(self):
        return "AgentBox: See AGENTS.md for command reference.\n"

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
                elif token == "--head" and i + 1 < len(cmd_list):
                    try:
                        res.head = int(cmd_list[i + 1])
                    except ValueError:
                        pass
                    i += 2
                elif token.startswith("--head="):
                    try:
                        res.head = int(token.split("=", 1)[1])
                    except ValueError:
                        pass
                    i += 1
                elif token in ("--silent", "-s"):
                    res.silent = True
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
        add_help=False,
        description=f"AgentBox v{__version__} — Token-efficient execution and AST code tools for AI agents."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-h", "--help", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--help-human", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--target", "-t", default=None, help="Target environment name from config or SSH host string")
    parser.add_argument("--host", default=None, help="Target SSH host (e.g. user@server, or empty for local)")
    parser.add_argument("--cwd", default=None, help="Target working directory")
    parser.add_argument("--venv", default=None, help="Target virtualenv path (auto-detected if omitted)")
    parser.add_argument("--no-daemon", action="store_true", help="Bypass persistent daemon bridge and run direct SSH")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # config command
    p_cfg = sub.add_parser("config", help="View or update host, directory, and virtualenv settings")
    p_cfg.add_argument("--set-host", help="Set default SSH host")
    p_cfg.add_argument("--set-cwd", help="Set default directory")
    p_cfg.add_argument("--set-venv", help="Set default virtualenv path (or empty string to clear)")
    p_cfg.add_argument("--global", dest="is_global", action="store_true", help="Save globally to ~/.agentbox/config.json")

    # target command
    p_tgt = sub.add_parser("target", help="Multi-host target management: list, add, rm, use")
    p_tgt.add_argument("target_action", nargs="?", default=None, help="'list', 'add', 'rm', 'use', or empty to show active")
    p_tgt.add_argument("target_name", nargs="?", default=None, help="Target name")
    p_tgt.add_argument("--host", default="", help="SSH host string (e.g. user@server)")
    p_tgt.add_argument("--cwd", default="", help="Target working directory")
    p_tgt.add_argument("--venv", default="", help="Target virtualenv path")
    p_tgt.add_argument("--default", action="store_true", help="Set as default target")
    p_tgt.add_argument("--readonly", "--ro", action="store_true", dest="readonly", help="Mark target as read-only")
    p_tgt.add_argument("--off", action="store_true", dest="readonly_off", help="Disable read-only mode for target")

    # rules command
    p_rules = sub.add_parser("rules", help="Generate or update AI agent rules (AGENTS.md)")
    p_rules.add_argument("--type", choices=["agents", "cursor", "claude", "all"], default="agents", help="Target rule format (default: agents)")
    p_rules.add_argument("--sync", action="store_true", help="Sync targets and tasks into existing rule files")

    # init-rules alias for backwards compatibility
    p_init_rules = sub.add_parser("init-rules", help="Alias for 'agentbox rules'")
    p_init_rules.add_argument("--type", choices=["agents", "cursor", "claude", "all"], default="agents", help="Target rule format (default: agents)")

    # task command
    p_task = sub.add_parser("task", help="Project Tasks & Recipes: list, run, add, or remove task automation recipes")
    p_task.add_argument("task_action", nargs="?", default=None, help="Task name, 'list', 'add', or 'rm' / 'remove'")
    p_task.add_argument("task_args", nargs=argparse.REMAINDER, default=[], help="Arguments for the task or command definition for add")

    # view
    p_view = sub.add_parser("view", help="View slice of file with line numbers")
    p_view.add_argument("path", help="Path to file")
    p_view.add_argument("--start", type=int, default=1, help="Start line (default: 1)")
    p_view.add_argument("--end", type=int, default=100, help="End line (default: 100)")
    p_view.add_argument("--tail", "-n", type=int, default=None, help="View last N lines of file (overrides start/end)")

    # outline
    p_out = sub.add_parser("outline", help="Extract AST outline (classes, functions, methods) for one or more files/dirs")
    p_out.add_argument("path", nargs="+", help="Path(s) to file or directory (Python, Rust, JS, TS, C, Go)")

    # get-fn
    p_fn = sub.add_parser("get-fn", help="Extract specific function, method (Class.method), or class definition")
    p_fn.add_argument("path", help="Path to file")
    p_fn.add_argument("name", nargs="+", help="Name(s) of function, class, or ClassName.method_name")

    # write
    p_write = sub.add_parser("write", help="Safely write or append content to file without bash quoting issues")
    p_write.add_argument("paths", nargs="+", help="Path(s) to target file, or multiple local:target mappings")
    p_write.add_argument("--content", default=None, help="File content (reads from stdin if --stdin is specified)")
    p_write.add_argument("--file", dest="file_path", default=None, help="Read content from a local file")
    p_write.add_argument("--base64", "-b", dest="b64", default=None, help="File content encoded in UTF-8 base64")
    p_write.add_argument("--stdin", action="store_true", help="Read content from stdin")
    p_write.add_argument("--append", action="store_true", help="Append instead of overwrite")

    # patch
    p_patch = sub.add_parser("patch", help="Atomic find-and-replace with auto-backup and Python AST validation")
    p_patch.add_argument("path", help="Path to file")
    p_patch.add_argument("--old", default=None, help="Target text to replace")
    p_patch.add_argument("--new", default=None, help="Replacement text")
    p_patch.add_argument("--base64-old", default=None, help="Target text to replace encoded in UTF-8 base64")
    p_patch.add_argument("--base64-new", default=None, help="Replacement text encoded in UTF-8 base64")
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
    p_pl.add_argument("--file", dest="file_path", default=None, help="Read replacement content from a local file")
    p_pl.add_argument("--base64", "-b", dest="b64", default=None, help="Replacement text encoded in UTF-8 base64")
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
    # grep
    p_grep = sub.add_parser("grep", help="Fast text search with limits")
    p_grep.add_argument("query", help="Search query or regex")
    p_grep.add_argument("path", nargs="?", default="", help="Directory path or specific file")
    p_grep.add_argument("-F", "--fixed", action="store_true", help="Treat query as a fixed string instead of regex")
    p_grep.add_argument("-l", "--files-only", action="store_true", help="Print only filenames matching query")
    p_grep.add_argument("--max", type=int, default=20, help="Max results (default: 20)")

    # py
    # py
    p_py = sub.add_parser("py", help="Silent Python evaluator with zero shell escaping and project venv auto-detection")
    p_py.add_argument("--base64", "-b", dest="b64", default=None, help="Python code encoded in UTF-8 base64")
    p_py.add_argument("--file", dest="file_path", default=None, help="Read Python code from local file")
    p_py.add_argument("--code", "-c", dest="code", default=None, help="Inline Python code string")
    p_py.add_argument("--stdin", action="store_true", help="Read Python code from stdin")
    p_py.add_argument("--tail", type=int, default=30, help="Lines of output tail to show if truncated (default: 30)")
    p_py.add_argument("--max-lines", type=int, default=30, help="Max lines before truncation (default: 30)")
    p_py.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")
    p_py.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_py.add_argument("py_args", nargs=argparse.REMAINDER, default=[], help="Arguments passed to script (sys.argv[1:])")
    # sync
    p_sync = sub.add_parser("sync", help="Two-way project synchronization between local and remote target")
    p_sync.add_argument("sync_action", choices=["status", "push", "pull"], help="Sync operation: status, push, pull")
    p_sync.add_argument("--dry-run", action="store_true", help="Preview sync changes without modifying files")
    p_sync.add_argument("--force", "-f", action="store_true", help="Force overwrite in case of conflicts")
    p_sync.add_argument("--delete", action="store_true", help="Delete files on destination that do not exist on source")

    # cp
    p_cp = sub.add_parser("cp", help="Copy file between targets or local workspace ([target:]path)")
    p_cp.add_argument("src", help="Source file path: [target:]path")
    p_cp.add_argument("dest", help="Destination file or directory path: [target:]path")

    # run
    p_run = sub.add_parser("run", help="Run build/test command silently with log tailing on failure")
    p_run.add_argument("--tail", type=int, default=default_cfg.get("tail", 15), help="Lines of log tail to display")
    p_run.add_argument("--head", type=int, default=None, help="Lines of log head to display on success")
    p_run.add_argument("--silent", "-s", action="store_true", help="Completely silence log output on success")
    p_run.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")
    p_run.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_run.add_argument("--base64", "-b", dest="b64", default=None, help="Command encoded in UTF-8 base64")
    p_run.add_argument("--file", dest="file_path", default=None, help="Read command from local file")
    p_run.add_argument("command", nargs=argparse.REMAINDER, help="Shell command to execute")
    # test
    p_test = sub.add_parser("test", help="Run test suite silently, extracting only high-signal failure tracebacks")
    p_test.add_argument("--timeout", type=int, default=default_cfg.get("timeout", None), help="Timeout in seconds")
    p_test.add_argument("--max-lines", type=int, default=30, help="Max failure lines to show (default: 30)")
    p_test.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_test.add_argument("--base64", "-b", dest="b64", default=None, help="Test command encoded in UTF-8 base64")
    p_test.add_argument("--file", dest="file_path", default=None, help="Read test command from local file")
    p_test.add_argument("command", nargs=argparse.REMAINDER, help="Test command to execute")

    # pip
    p_pip = sub.add_parser("pip", help="Run pip inside isolated virtualenv (auto-creates .agentbox/venv if needed)")
    p_pip.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path")
    p_pip.add_argument("command", nargs=argparse.REMAINDER, help="Arguments passed to pip (e.g. install pytest)")

    # stats
    p_stats = sub.add_parser("stats", help="Display token savings and command execution dashboard")
    p_stats.add_argument("--clear", action="store_true", help="Clear recorded statistics")

    # audit
    p_audit = sub.add_parser("audit", help="Display agent action telemetry, usage frequency, and friction analytics")
    p_audit.add_argument("-n", "--tail", type=int, default=0, help="Show last N raw action log records")
    p_audit.add_argument("--clear", action="store_true", help="Clear action audit log")

    # batch
    p_batch = sub.add_parser("batch", help="Execute multiple AgentBox actions in a single call to save agent turns")
    p_batch.add_argument("steps", nargs="?", default=None, help="JSON array of action steps")
    p_batch.add_argument("--base64", "-b", dest="b64", default=None, help="JSON array of action steps encoded in UTF-8 base64")
    p_batch.add_argument("--stdin", action="store_true", help="Read JSON batch array from stdin")
    p_batch.add_argument("--continue-on-error", dest="stop_on_error", action="store_false", help="Continue executing remaining steps if a step fails")

    # spawn
    p_spawn = sub.add_parser("spawn", help="Spawn detached background process (survives disconnects)")
    p_spawn.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path (overrides auto-detection)")
    p_spawn.add_argument("--base64", "-b", dest="b64", default=None, help="Command encoded in UTF-8 base64")
    p_spawn.add_argument("--file", dest="file_path", default=None, help="Read command from local file")
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

    # graphify-open
    p_go = sub.add_parser("graphify-open", help="Open interactive knowledge graph in local browser (Remote-Compute, Local-Artifact)")
    p_go.add_argument("path", nargs="?", default="", help="Project path with graphify-out")
    p_go.add_argument("--venv", dest="cmd_venv", default=None, help="Target virtualenv path")
    p_go.add_argument("--no-open", action="store_true", help="Download/locate graph.html without launching browser")
    p_go.add_argument("--out", default=None, help="Custom local destination path for graph.html")

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


def _resolve_exec_command(args: Any) -> str:
    """Resolves command from --base64, --file, or command line tokens."""
    b64 = getattr(args, "b64", None)
    if b64:
        return decode_base64_text(b64)
    file_path = getattr(args, "file_path", None)
    if file_path:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    return _resolve_cmd_string(getattr(args, "command", None))


def main(argv: Optional[List[str]] = None):
    start_time = time.time()
    check_args = list(argv) if argv is not None else sys.argv[1:]
    if "--help-human" in check_args:
        print(HUMAN_MANUAL.strip())
        return 0
    if "-h" in check_args or "--help" in check_args or not check_args:
        print("AgentBox: See AGENTS.md for command reference.")
        return 0

    cfg = get_config()
    parser = create_parser(cfg)
    args = parser.parse_args(argv)

    if args.cmd == "audit":
        print(get_audit_summary(tail=args.tail, clear=args.clear))
        return 0
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

    if args.cmd == "target":
        action = args.target_action
        tgt_name = args.target_name

        # 1. agentbox target / agentbox target show
        if not action or action == "show":
            targets = get_targets()
            resolved = resolve_target(None, cfg)
            print("=== ACTIVE TARGET ===")
            print(f"  Name     : {resolved['name']}")
            print(f"  Host     : {resolved['host'] or '(local)'}")
            print(f"  CWD      : {resolved['cwd'] or '(project root)'}")
            print(f"  Venv     : {resolved['venv'] or '(auto-detect)'}")
            print(f"  Readonly : {'yes' if resolved.get('readonly') else 'no'}")
            if not targets and not cfg.get("host"):
                print("\nTip: Add a remote target with: agentbox target add <name> --host <user@server> [--cwd <path>]")
            return 0

        # 2. agentbox target list
        if action == "list":
            targets = get_targets()
            def_name = get_default_target_name()
            if not targets:
                print("No named targets configured in .agentbox.json.")
                print("Default mode: local (zero-config)")
                print("Add a target with: agentbox target add <name> --host <user@server> [--cwd <path>]")
            else:
                print(f"=== CONFIGURED TARGETS ({len(targets)}) ===")
                for name, t in sorted(targets.items()):
                    is_active = (name == def_name) or (not def_name and name == next(iter(targets.keys())))
                    mark = "* " if is_active else "  "
                    host_str = t.get("host") or "(local)"
                    cwd_str = t.get("cwd") or "(project root)"
                    ro_str = " [READ-ONLY]" if t.get("readonly") else ""
                    print(f"{mark}{name:15} : host={host_str:<25} cwd={cwd_str}{ro_str}")
            return 0

        # 3. agentbox target add <name> [--host ...] [--cwd ...] [--venv ...] [--default] [--readonly]
        if action == "add":
            if not tgt_name:
                print("ERROR: Missing target name. Usage: agentbox target add <name> --host <host> [--cwd <cwd>] [--venv <venv>] [--default] [--readonly]", file=sys.stderr)
                return 1
            is_ro = bool(getattr(args, "readonly", False))
            add_target(
                tgt_name,
                host=getattr(args, "host", "") or "",
                cwd=getattr(args, "cwd", "") or "",
                venv=getattr(args, "venv", "") or "",
                is_default=getattr(args, "default", False),
                readonly=is_ro,
            )
            ro_msg = " [READ-ONLY]" if is_ro else ""
            print(f"OK: Target '{tgt_name}'{ro_msg} saved to .agentbox.json.")
            return 0

        # 4. agentbox target rm / remove <name>
        if action in ("rm", "remove"):
            if not tgt_name:
                print("ERROR: Missing target name. Usage: agentbox target rm <name>", file=sys.stderr)
                return 1
            if remove_target(tgt_name):
                print(f"OK: Target '{tgt_name}' removed from .agentbox.json.")
                return 0
            else:
                print(f"ERROR: Target '{tgt_name}' not found.", file=sys.stderr)
                return 1

        # 5. agentbox target use / set-default <name>
        if action in ("use", "set-default"):
            if not tgt_name:
                print("ERROR: Missing target name. Usage: agentbox target use <name>", file=sys.stderr)
                return 1
            if set_default_target(tgt_name):
                print(f"OK: Active target set to '{tgt_name}'.")
                return 0
            else:
                print(f"ERROR: Target '{tgt_name}' not found.", file=sys.stderr)
                return 1

        # 6. agentbox target readonly / ro <name> [--off]
        if action in ("readonly", "ro"):
            if not tgt_name:
                print("ERROR: Missing target name. Usage: agentbox target readonly <name> [--off]", file=sys.stderr)
                return 1
            new_val = not getattr(args, "readonly_off", False)
            if set_target_readonly(tgt_name, new_val):
                status_str = "READ-ONLY" if new_val else "READ-WRITE"
                print(f"OK: Target '{tgt_name}' set to {status_str} in .agentbox.json.")
                return 0
            else:
                print(f"ERROR: Target '{tgt_name}' not found.", file=sys.stderr)
                return 1
                print(f"ERROR: Target '{tgt_name}' not found. Configured targets: {list(get_targets().keys())}", file=sys.stderr)
                return 1

        print(f"ERROR: Unknown target action '{action}'. Use list, add, rm, use, or show.", file=sys.stderr)
        return 1

    if args.cmd in ("rules", "init-rules"):
        if getattr(args, "sync", False):
            updated = sync_rules()
            if updated:
                print(f"OK: Synced rules in: {', '.join(updated)}")
            else:
                print("Rules are already up to date.")
        else:
            generate_rules(getattr(args, "type", "agents"))
        return 0

    if args.cmd == "task":
        action = args.task_action
        task_args = args.task_args or []

        # 1. agentbox task / agentbox task list
        # 1. agentbox task / agentbox task list
        if not action or action == "list":
            tasks = get_tasks()
            if not tasks:
                print("No tasks defined in .agentbox.json.")
                print("Add one with: agentbox task add <name> \"<command>\"")
            else:
                print(f"=== PROJECT TASKS ({len(tasks)}) ===")
                for name, cmd_val in sorted(tasks.items()):
                    if isinstance(cmd_val, dict):
                        c_str = cmd_val.get("cmd", "")
                        tgt = f" [target: {cmd_val['target']}]" if cmd_val.get("target") else ""
                        desc = f" - {cmd_val['desc']}" if cmd_val.get("desc") else ""
                        print(f"  {name:15} : {c_str}{tgt}{desc}")
                    else:
                        print(f"  {name:15} : {cmd_val}")
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

        task_entry = tasks[task_name]
        if isinstance(task_entry, dict):
            raw_cmd = task_entry.get("cmd", "")
            task_target = task_entry.get("target")
        else:
            raw_cmd = str(task_entry)
            task_target = None

        resolved_cmd = _format_task_command(raw_cmd, task_args)

        # Target resolution
        target_spec = getattr(args, "target", None) or task_target
        resolved_tgt = resolve_target(target_spec, cfg)
        if resolved_tgt.get("readonly"):
            print(f"ERROR: Target '{resolved_tgt['name']}' is READ-ONLY in .agentbox.json. Task execution is forbidden.", file=sys.stderr)
            record_audit("task", resolved_tgt.get("name", ""), "", 1, 0, "BLOCKED_READONLY")
            return 1
        host = args.host if args.host is not None else resolved_tgt["host"]
        cwd = args.cwd if args.cwd is not None else (resolved_tgt["cwd"] or cfg.get("cwd", ""))
        venv = getattr(args, "cmd_venv", None) or getattr(args, "venv", None) or resolved_tgt["venv"] or cfg.get("venv", "")
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

    # Global Target resolution
    target_spec = getattr(args, "target", None)
    resolved_tgt = resolve_target(target_spec, cfg)
    host = args.host if args.host is not None else resolved_tgt["host"]
    cwd = args.cwd if args.cwd is not None else (resolved_tgt["cwd"] or cfg.get("cwd", ""))
    venv = getattr(args, "cmd_venv", None) or getattr(args, "venv", None) or resolved_tgt["venv"] or cfg.get("venv", "")

    # Read-only target enforcement
    if resolved_tgt.get("readonly"):
        if args.cmd not in SAFE_READONLY_COMMANDS and args.cmd not in ("sync", "batch", "cp"):
            print(
                f"ERROR: Target '{resolved_tgt['name']}' is READ-ONLY in .agentbox.json. "
                f"Command '{args.cmd}' is forbidden. Only inspection tools are allowed.",
                file=sys.stderr
            )
            record_audit(args.cmd, resolved_tgt.get("name", ""), "", 1, 0, "BLOCKED_READONLY")
            return 1

    def run_action(action: str, act_args: dict) -> int:
        if getattr(args, "no_daemon", False):
            return execute_action(host, cwd, action, act_args, use_daemon=False)
        return execute_action(host, cwd, action, act_args)

    if args.cmd == "view":
        act_args = {"path": args.path, "start": args.start, "end": args.end}
        if getattr(args, "tail", None) is not None:
            act_args["tail"] = args.tail
        code = run_action("view", act_args)
    elif args.cmd == "outline":
        code = run_action("outline", {"path": args.path})
    elif args.cmd == "get-fn":
        code = run_action("get_fn", {"path": args.path, "name": args.name})
    elif args.cmd == "find-fn":
        code = run_action("find_fn", {"name": args.name, "path": args.path or cwd, "exact": args.exact, "max": args.max_results})
    elif args.cmd == "refs":
        code = run_action("refs", {"name": args.name, "path": args.path or cwd, "max": args.max_results})
    elif args.cmd == "write":
        from pathlib import Path as _P
        content = args.content
        if content is None and getattr(args, "b64", None):
            content = decode_base64_text(args.b64)
        if content is None and getattr(args, "file_path", None):
            try:
                content = _P(args.file_path).read_text(encoding="utf-8")
            except Exception as e:
                print(f"ERROR: Failed to read file {args.file_path}: {e}", file=sys.stderr)
                return 1
        if content is None and getattr(args, "stdin", False):
            content = read_stdin_utf8()

        if content is not None:
            if len(args.paths) == 1:
                code = run_action("write", {"path": args.paths[0], "content": content, "append": args.append})
            else:
                files_payload = [{"path": p, "content": content} for p in args.paths]
                code = run_action("write", {"files": files_payload, "append": args.append})
        else:
            files_payload = []
            for spec in args.paths:
                src, dest = parse_file_mapping(spec)
                src_path = _P(src)
                if not src_path.is_file():
                    if len(args.paths) == 1 and ":" not in spec:
                        print("ERROR: Provide content via --content \"...\", --base64, --file <path>, or pass --stdin.", file=sys.stderr)
                    else:
                        print(f"ERROR: Local source file not found: {src}", file=sys.stderr)
                    return 1
                try:
                    src_content = src_path.read_text(encoding="utf-8")
                except Exception as e:
                    print(f"ERROR: Failed to read local file {src}: {e}", file=sys.stderr)
                    return 1
                files_payload.append({"path": dest, "content": src_content})

            if len(files_payload) == 1 and ":" not in args.paths[0]:
                code = run_action("write", {"path": files_payload[0]["path"], "content": files_payload[0]["content"], "append": args.append})
            else:
                code = run_action("write", {"files": files_payload, "append": args.append})
    elif args.cmd == "patch":
        old_val = args.old
        new_val = args.new
        if old_val is None and getattr(args, "base64_old", None):
            old_val = decode_base64_text(args.base64_old)
        if new_val is None and getattr(args, "base64_new", None):
            new_val = decode_base64_text(args.base64_new)
        if old_val is None and getattr(args, "old_file", None):
            from pathlib import Path as _P
            try:
                old_val = _P(args.old_file).read_text(encoding="utf-8")
            except Exception as e:
                print(f"ERROR: Failed to read old-file {args.old_file}: {e}", file=sys.stderr)
                return 1
        if new_val is None and getattr(args, "new_file", None):
            from pathlib import Path as _P
            try:
                new_val = _P(args.new_file).read_text(encoding="utf-8")
            except Exception as e:
                print(f"ERROR: Failed to read new-file {args.new_file}: {e}", file=sys.stderr)
                return 1
        if old_val is None or new_val is None:
            print("ERROR: Provide both target text (--old, --base64-old, or --old-file) and replacement (--new, --base64-new, or --new-file).", file=sys.stderr)
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
        if content is None and getattr(args, "b64", None):
            content = decode_base64_text(args.b64)
        if content is None and getattr(args, "file_path", None):
            from pathlib import Path as _P
            try:
                content = _P(args.file_path).read_text(encoding="utf-8")
            except Exception as e:
                print(f"ERROR: Failed to read file {args.file_path}: {e}", file=sys.stderr)
                return 1
        if content is None:
            if getattr(args, "stdin", False):
                content = read_stdin_utf8()
            else:
                print("ERROR: Provide replacement via --content \"...\", --base64, --file <path>, or pass --stdin.", file=sys.stderr)
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
        code = run_action("grep", {
            "query": args.query,
            "path": args.path or cwd,
            "max": args.max,
            "fixed": getattr(args, "fixed", False),
            "files_only": getattr(args, "files_only", False)
        })
    elif args.cmd == "run":
        cmd_str = _resolve_exec_command(args)
        if not cmd_str:
            print("ERROR: Missing command to execute. Usage: agentbox run <command> [--base64 <b64>] [--file <path>]", file=sys.stderr)
            return 1
        run_payload = {"cmd": cmd_str, "cwd": cwd, "tail": args.tail, "timeout": args.timeout, "venv": venv}
        if getattr(args, "head", None) is not None:
            run_payload["head"] = args.head
        if getattr(args, "silent", False):
            run_payload["silent"] = args.silent
        code = run_action("run", run_payload)
    elif args.cmd == "py":
        code_str = None
        if getattr(args, "b64", None):
            code_str = decode_base64_text(args.b64)
        elif getattr(args, "file_path", None):
            try:
                code_str = Path(args.file_path).read_text(encoding="utf-8")
            except Exception as e:
                print(f"ERROR: Failed to read file {args.file_path}: {e}", file=sys.stderr)
                return 1
        elif getattr(args, "code", None):
            code_str = args.code
        elif getattr(args, "stdin", False) or (getattr(args, "py_args", None) and getattr(args, "py_args") == ["-"]):
            code_str = read_stdin_utf8()

        if not code_str:
            print("ERROR: No Python code provided. Usage: agentbox py --base64 <b64> | --file <path> | --code \"<code>\" | -", file=sys.stderr)
            print("💡 AGENT HINT: Use --base64 <b64> to avoid PowerShell quote escaping.", file=sys.stderr)
            return 1

        py_args = getattr(args, "py_args", []) or []
        if py_args and py_args[0] == "--":
            py_args = py_args[1:]
        code = run_action("py", {
            "code": code_str,
            "cwd": cwd,
            "args": py_args,
            "tail": getattr(args, "tail", 30),
            "max_lines": getattr(args, "max_lines", 30),
            "timeout": getattr(args, "timeout", None),
            "venv": venv
        })
    elif args.cmd == "sync":
        from .sync import build_manifest, compute_sync_diff, pack_sync_tar, unpack_sync_tar
        target_spec = getattr(args, "target", None)
        resolved_tgt = resolve_target(target_spec, cfg)
        host = args.host if args.host is not None else resolved_tgt["host"]
        cwd = args.cwd if args.cwd is not None else (resolved_tgt["cwd"] or cfg.get("cwd", ""))
        is_remote = bool(host and host not in ("local", "localhost", "127.0.0.1", "."))

        if not is_remote:
            print("ERROR: 'agentbox sync' requires a remote target specified via -t <target> (e.g. agentbox -t pyferro2 sync ...).", file=sys.stderr)
            return 1

        local_dir = Path.cwd()
        local_manifest = build_manifest(local_dir)

        # 1. Fetch remote manifest
        print(f"Fetching remote file manifest from '{host}'...")
        res = execute_action(host, cwd, "sync_manifest", {"cwd": cwd}, capture=True)
        if isinstance(res, tuple):
            m_code, m_out, m_err = res
        else:
            m_code, m_out, m_err = res, "", ""

        if m_code != 0:
            print(f"ERROR: Failed to fetch remote manifest from {host} [exit {m_code}]: {m_err}", file=sys.stderr)
            return m_code
        try:
            remote_manifest = json.loads(m_out.strip())
        except Exception as e:
            print(f"ERROR: Failed to parse remote manifest from {host}: {e}\nRaw output: {m_out[:200]}", file=sys.stderr)
            return 1

        diff = compute_sync_diff(local_manifest, remote_manifest)
        action = args.sync_action

        if resolved_tgt.get("readonly") and action not in ("status", "pull"):
            print(f"ERROR: Target '{resolved_tgt['name']}' is READ-ONLY in .agentbox.json. 'sync push' is forbidden.", file=sys.stderr)
            record_audit("sync", resolved_tgt.get("name", ""), "", 1, 0, "BLOCKED_READONLY")
            return 1

        if action == "status":
            print(f"=== SYNC STATUS ({host}:{cwd or '.'}) ===")
            print(f"  In sync      : {len(diff['in_sync'])} files")
            print(f"  Local ahead  (to push): {len(diff['to_push'])} files" + (f" -> {', '.join(diff['to_push'][:5])}{'...' if len(diff['to_push']) > 5 else ''}" if diff['to_push'] else ""))
            print(f"  Remote ahead (to pull): {len(diff['to_pull'])} files" + (f" -> {', '.join(diff['to_pull'][:5])}{'...' if len(diff['to_pull']) > 5 else ''}" if diff['to_pull'] else ""))
            if diff["conflicts_push"]:
                print(f"  ⚠️ Conflicts on push (remote is newer): {len(diff['conflicts_push'])} files ({', '.join(diff['conflicts_push'][:3])})")
            if diff["conflicts_pull"]:
                print(f"  ⚠️ Conflicts on pull (local is newer): {len(diff['conflicts_pull'])} files ({', '.join(diff['conflicts_pull'][:3])})")
            return 0

        elif action == "push":
            to_send = diff["to_push"]
            if not to_send:
                print(f"OK [sync push -> {host}] Everything up to date ({len(diff['in_sync'])} files in sync).")
                return 0

            if diff["conflicts_push"] and not args.force:
                print(f"ERROR: Aborting sync push. {len(diff['conflicts_push'])} remote file(s) are newer than local:", file=sys.stderr)
                for f in diff["conflicts_push"][:5]:
                    print(f"  - {f}", file=sys.stderr)
                print("💡 AGENT HINT: Use 'agentbox sync pull' to retrieve remote changes, or --force to overwrite.", file=sys.stderr)
                return 1

            if args.dry_run:
                print(f"[DRY-RUN] Would push {len(to_send)} file(s) to {host}:")
                for f in to_send[:10]:
                    print(f"  + {f}")
                if len(to_send) > 10:
                    print(f"  ... and {len(to_send) - 10} more.")
                return 0

            start_t = time.time()
            tar_bytes = pack_sync_tar(local_dir, to_send, to_lf=True)
            tar_b64 = base64.b64encode(tar_bytes).decode("ascii")
            tar_kb = len(tar_bytes) / 1024

            res = execute_action(host, cwd, "sync_unpack", {"cwd": cwd, "tar_b64": tar_b64}, capture=True)
            u_code = res[0] if isinstance(res, tuple) else res
            u_err = res[2] if isinstance(res, tuple) else ""
            if u_code != 0:
                print(f"ERROR: Sync push failed on remote [exit {u_code}]: {u_err}", file=sys.stderr)
                return u_code

            dur = time.time() - start_t
            del_msg = ""
            if args.delete and diff["remote_only"]:
                d_res = execute_action(host, cwd, "sync_delete", {"cwd": cwd, "files": diff["remote_only"]}, capture=True)
                d_code = d_res[0] if isinstance(d_res, tuple) else d_res
                if d_code == 0:
                    del_msg = f", deleted {len(diff['remote_only'])} stale remote files"

            print(f"OK [sync push -> {host}] Synced {len(to_send)} file(s) ({tar_kb:.1f} KB) in {dur:.2f}s{del_msg}.")
            return 0

        elif action == "pull":
            to_receive = diff["to_pull"]
            if not to_receive:
                print(f"OK [sync pull <- {host}] Everything up to date ({len(diff['in_sync'])} files in sync).")
                return 0

            if diff["conflicts_pull"] and not args.force:
                print(f"ERROR: Aborting sync pull. {len(diff['conflicts_pull'])} local file(s) are newer than remote:", file=sys.stderr)
                for f in diff["conflicts_pull"][:5]:
                    print(f"  - {f}", file=sys.stderr)
                print("💡 AGENT HINT: Use 'agentbox sync push' to send local changes, or --force to overwrite.", file=sys.stderr)
                return 1

            if args.dry_run:
                print(f"[DRY-RUN] Would pull {len(to_receive)} file(s) from {host}:")
                for f in to_receive[:10]:
                    print(f"  + {f}")
                if len(to_receive) > 10:
                    print(f"  ... and {len(to_receive) - 10} more.")
                return 0

            start_t = time.time()
            res = execute_action(host, cwd, "sync_pack", {"cwd": cwd, "files": to_receive}, capture=True)
            p_code = res[0] if isinstance(res, tuple) else res
            p_out = res[1] if isinstance(res, tuple) else ""
            p_err = res[2] if isinstance(res, tuple) else ""
            if p_code != 0:
                print(f"ERROR: Sync pull failed on remote [exit {p_code}]: {p_err}", file=sys.stderr)
                return p_code

            tar_bytes = base64.b64decode(p_out.strip())
            tar_kb = len(tar_bytes) / 1024
            unpacked = unpack_sync_tar(local_dir, tar_bytes)
            dur = time.time() - start_t

            del_msg = ""
            if args.delete and diff["local_only"]:
                for f in diff["local_only"]:
                    p = local_dir / f
                    if p.is_file():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                del_msg = f", deleted {len(diff['local_only'])} stale local files"

            print(f"OK [sync pull <- {host}] Synced {len(unpacked)} file(s) ({tar_kb:.1f} KB) in {dur:.2f}s{del_msg}.")
            return 0
    elif args.cmd == "cp":
        src_target_name, src_path = parse_target_path(args.src)
        dest_target_name, dest_path = parse_target_path(args.dest)

        src_resolved = resolve_target(src_target_name, cfg) if src_target_name else {"host": "", "cwd": "", "venv": "", "name": "local", "readonly": False}
        dest_resolved = resolve_target(dest_target_name, cfg) if dest_target_name else {"host": "", "cwd": "", "venv": "", "name": "local", "readonly": False}

        if dest_resolved.get("readonly"):
            print(f"ERROR: Destination target '{dest_resolved.get('name')}' is READ-ONLY in .agentbox.json. Writing files is forbidden.", file=sys.stderr)
            record_audit("cp", dest_resolved.get("name", ""), f"{args.src} -> {args.dest}", 1, 0, "BLOCKED_READONLY")
            return 1

        src_host = src_resolved.get("host") or ""
        src_cwd = src_resolved.get("cwd") or ""
        src_is_remote = bool(src_host and src_host not in ("local", "localhost", "127.0.0.1", "."))

        dest_host = dest_resolved.get("host") or ""
        dest_cwd = dest_resolved.get("cwd") or ""
        dest_is_remote = bool(dest_host and dest_host not in ("local", "localhost", "127.0.0.1", "."))

        t0 = time.time()
        # 1. Read source
        if not src_is_remote:
            src_p = Path(src_path).expanduser()
            if not src_p.is_absolute():
                src_p = (Path.cwd() / src_p).resolve()
            if not src_p.is_file():
                if src_p.is_dir():
                    print(f"ERROR: Source path is a directory (directories not supported in cp v1): {src_path}", file=sys.stderr)
                else:
                    print(f"ERROR: Local source file not found: {src_path}", file=sys.stderr)
                return 1
            try:
                raw_bytes = src_p.read_bytes()
            except Exception as e:
                print(f"ERROR: Failed reading local source file {src_path}: {e}", file=sys.stderr)
                return 1
        else:
            res = execute_action(src_host, src_cwd, "file_read_b64", {"path": src_path}, capture=True)
            if isinstance(res, tuple):
                r_code, r_out, r_err = res
            else:
                r_code, r_out, r_err = res, "", ""
            if r_code != 0:
                err_msg = r_err.strip() or r_out.strip() or f"exit code {r_code}"
                print(f"ERROR: Failed reading from '{src_resolved.get('name', src_host)}': {err_msg}", file=sys.stderr)
                return r_code
            try:
                raw_bytes = base64.b64decode(r_out.strip())
            except Exception as e:
                print(f"ERROR: Failed decoding source data from '{src_resolved.get('name', src_host)}': {e}", file=sys.stderr)
                return 1

        src_filename = Path(src_path).name or "file"

        # 2. Write destination
        if not dest_is_remote:
            dest_p = Path(dest_path).expanduser()
            if not dest_p.is_absolute():
                dest_p = (Path.cwd() / dest_p).resolve()
            if dest_p.is_dir() or str(dest_path).endswith("/") or str(dest_path).endswith("\\"):
                dest_p = dest_p / src_filename
            try:
                dest_p.parent.mkdir(parents=True, exist_ok=True)
                dest_p.write_bytes(raw_bytes)
            except Exception as e:
                print(f"ERROR: Failed writing to local destination {dest_p}: {e}", file=sys.stderr)
                return 1
        else:
            data_b64 = base64.b64encode(raw_bytes).decode("ascii")
            res = execute_action(dest_host, dest_cwd, "file_write_b64", {
                "path": dest_path,
                "data_b64": data_b64,
                "src_filename": src_filename
            }, capture=True)
            if isinstance(res, tuple):
                w_code, w_out, w_err = res
            else:
                w_code, w_out, w_err = res, "", ""
            if w_code != 0:
                err_msg = w_err.strip() or w_out.strip() or f"exit code {w_code}"
                print(f"ERROR: Failed writing to '{dest_resolved.get('name', dest_host)}': {err_msg}", file=sys.stderr)
                return w_code

        dur = time.time() - t0
        size_bytes = len(raw_bytes)
        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{size_bytes / 1024:.1f} KB"

        src_display = f"{src_resolved.get('name')}:{src_path}" if src_target_name else src_path
        dest_display = f"{dest_resolved.get('name')}:{dest_path}" if dest_target_name else dest_path
        print(f"OK: Copied {size_str} ({src_display} -> {dest_display} in {dur:.2f}s)")
        record_audit("cp", f"{src_resolved.get('name', 'local')} -> {dest_resolved.get('name', 'local')}", f"{src_path} -> {dest_path}", 0, int(dur * 1000), size_str)
        return 0
    elif args.cmd == "test":
        cmd_str = _resolve_exec_command(args)
        if not cmd_str:
            print("ERROR: Missing test command to run. Usage: agentbox test <test_cmd> [--base64 <b64>] [--file <path>]", file=sys.stderr)
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
        if steps_raw is None and getattr(args, "b64", None):
            steps_raw = decode_base64_text(args.b64)
        if steps_raw is None:
            if getattr(args, "stdin", False):
                steps_raw = read_stdin_utf8()
            else:
                print("ERROR: Provide JSON steps argument, --base64, or pass --stdin.", file=sys.stderr)
                return 1

        import json
        try:
            steps_obj = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
        except Exception:
            steps_obj = None

        has_per_step_targets = False
        if isinstance(steps_obj, list):
            for step in steps_obj:
                if isinstance(step, dict) and ("target" in step or "host" in step):
                    has_per_step_targets = True
                    break

        if has_per_step_targets:
            # Multi-target client-orchestrated batch
            total = len(steps_obj)
            stop_on_err = getattr(args, "stop_on_error", True)
            last_code = 0
            for idx, step in enumerate(steps_obj, 1):
                if not isinstance(step, dict):
                    print(f"ERROR: Batch step {idx} is not an object", file=sys.stderr)
                    return 1
                s_action = step.get("action")
                s_args = step.get("args") or {k: v for k, v in step.items() if k not in ("action", "args", "target", "host", "cwd", "venv")}
                s_target = step.get("target")
                s_host_override = step.get("host")
                s_resolved = resolve_target(s_target, cfg) if s_target else resolved_tgt
                if s_resolved.get("readonly") and s_action not in SAFE_READONLY_ACTIONS:
                    print(f"ERROR: Target '{s_resolved['name']}' is READ-ONLY in .agentbox.json. Action '{s_action}' is forbidden.", file=sys.stderr)
                    record_audit(f"batch:{s_action}", s_resolved.get("name", ""), "", 1, 0, "BLOCKED_READONLY")
                    return 1
                s_host = s_host_override if s_host_override is not None else s_resolved["host"]
                s_cwd = step.get("cwd") or s_resolved["cwd"] or cwd
                s_venv = step.get("venv") or s_resolved["venv"] or venv

                print(f"=== [Batch {idx}/{total}: {s_action} on {s_resolved['name'] or s_host or 'local'}] ===")
                act_kw = {"use_daemon": False} if getattr(args, "no_daemon", False) else {}
                code = execute_action(s_host, s_cwd, s_action, s_args, **act_kw)
                last_code = code
                if code != 0 and stop_on_err:
                    print(f"ERROR: Batch stopped at step {idx} ({s_action}) with exit code {code}", file=sys.stderr)
                    return code
            return last_code
        else:
            if resolved_tgt.get("readonly") and isinstance(steps_obj, list):
                for idx, step in enumerate(steps_obj, 1):
                    s_act = step.get("action") if isinstance(step, dict) else None
                    if s_act not in SAFE_READONLY_ACTIONS:
                        print(f"ERROR: Target '{resolved_tgt['name']}' is READ-ONLY in .agentbox.json. Batch action '{s_act}' at step {idx} is forbidden.", file=sys.stderr)
                        record_audit(f"batch:{s_act}", resolved_tgt.get("name", ""), "", 1, 0, "BLOCKED_READONLY")
                        return 1
            code = run_action("batch", {"steps": steps_raw, "stop_on_error": getattr(args, "stop_on_error", True), "cwd": cwd})
    elif args.cmd == "spawn":
        cmd_str = _resolve_exec_command(args)
        if not cmd_str:
            print("ERROR: Missing command to spawn. Usage: agentbox spawn <command> [--base64 <b64>] [--file <path>]", file=sys.stderr)
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
    elif args.cmd == "graphify-open":
        target_path = args.path or cwd or "."
        is_remote = bool(host and host not in ("local", "localhost", "127.0.0.1", "."))
        curr_tgt_name = getattr(args, "target", None) or (resolved_tgt.get("name") if "resolved_tgt" in locals() else "local")
        if is_remote:
            from pathlib import Path as _P
            res = execute_action(host, cwd, "graphify_export_html", {"path": target_path, "venv": venv}, capture=True)
            if isinstance(res, tuple):
                ret_code, stdout_str, stderr_str = res
            else:
                ret_code, stdout_str, stderr_str = res, "", ""
            if ret_code != 0:
                if stderr_str:
                    sys.stderr.write(stderr_str)
                code = ret_code
            else:
                try:
                    html_bytes = base64.b64decode(stdout_str.strip())
                except Exception as e:
                    print(f"ERROR: Failed to decode remote graph payload: {e}", file=sys.stderr)
                    code = 1
                    html_bytes = None

                if html_bytes is not None:
                    if args.out:
                        local_dest = _P(args.out).resolve()
                    else:
                        cache_dir = _P.home() / ".agentbox" / "graphs"
                        safe_target = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(curr_tgt_name or host or "remote"))
                        local_dest = cache_dir / f"{safe_target}_graph.html"

                    try:
                        local_dest.parent.mkdir(parents=True, exist_ok=True)
                        local_dest.write_bytes(html_bytes)
                        print(f"OK: Downloaded remote knowledge graph from '{curr_tgt_name}' ({len(html_bytes):,} bytes) -> {local_dest}")
                        if not args.no_open:
                            try:
                                import webbrowser
                                webbrowser.open(local_dest.as_uri())
                                print("OK: Opened knowledge graph in local browser.")
                            except Exception as e:
                                print(f"Notice: Could not launch browser ({e}). View file at: {local_dest}")
                        code = 0
                    except Exception as e:
                        print(f"ERROR: Failed to save graph artifact to {local_dest}: {e}", file=sys.stderr)
                        code = 1
        else:
            code = run_action("graphify_open", {
                "path": target_path,
                "venv": venv,
                "no_open": args.no_open,
                "out": args.out
            })
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

    dur_ms = int((time.time() - start_time) * 1000)
    target_name = getattr(args, "target", None) or (resolved_tgt.get("name") if "resolved_tgt" in locals() else "local")
    target_path = getattr(args, "path", None) or getattr(args, "task_id", None) or getattr(args, "task_action", None) or ""
    if isinstance(target_path, list):
        target_path = " ".join(target_path)

    cmd_arg = ""
    if hasattr(args, "command") and args.command:
        cmd_arg = _resolve_cmd_string(args.command)
    elif args.cmd == "task":
        task_name = getattr(args, "task_name", "") or ""
        task_args = " ".join(getattr(args, "task_args", []) or [])
        cmd_arg = f"{task_name} {task_args}".strip()
    elif getattr(args, "question", None):
        cmd_arg = getattr(args, "question", "")

    query_str = getattr(args, "query", "") or getattr(args, "name", "") or ""

    audit_meta: Dict[str, Any] = {}
    if args.cmd == "view":
        if getattr(args, "start", None) is not None and getattr(args, "end", None) is not None:
            audit_meta["lines"] = [args.start, args.end]
        if getattr(args, "tail", None) is not None:
            audit_meta["tail"] = args.tail
    elif args.cmd == "patch-lines":
        if getattr(args, "start", None) is not None and getattr(args, "end", None) is not None:
            audit_meta["lines"] = [args.start, args.end]
    elif args.cmd == "patch":
        if getattr(args, "all", False):
            audit_meta["all"] = True
    elif args.cmd == "git-view":
        if getattr(args, "start", None) is not None and getattr(args, "end", None) is not None:
            audit_meta["lines"] = [args.start, args.end]
        if getattr(args, "rev", None):
            audit_meta["rev"] = args.rev
    elif args.cmd == "diff":
        if getattr(args, "rev", None):
            audit_meta["rev"] = args.rev
        if getattr(args, "cached", False):
            audit_meta["cached"] = True
    elif args.cmd == "tree":
        if getattr(args, "depth", None) is not None and args.depth != 2:
            audit_meta["depth"] = args.depth
    elif args.cmd == "grep":
        if getattr(args, "fixed", False):
            audit_meta["fixed"] = True

    err_msg = ""
    if code != 0:
        if args.cmd in ("run", "test", "pip", "spawn"):
            err_msg = f"exit {code}"
        elif args.cmd == "patch-lines":
            err_msg = f"patch rejected or failed (exit {code})"
        elif args.cmd == "patch":
            err_msg = f"patch failed (exit {code})"

    record_audit(
        cmd=args.cmd,
        target=target_name,
        path=str(target_path),
        code=code,
        duration_ms=dur_ms,
        error=err_msg,
        arg=cmd_arg,
        query=query_str,
        meta=audit_meta,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
