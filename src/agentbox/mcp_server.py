#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agentbox.mcp_server — Built-in Zero-Dependency Model Context Protocol (MCP) Server.
Exposes AgentBox tools natively over JSON-RPC 2.0 stdio for Claude Code, Cursor,
Antigravity, Windsurf, and Roo-Code — eliminating shell quoting errors and CLI startup overhead.
"""

import io
import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from . import __version__
from .config import get_config, find_local_config
from .client import execute_action

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "agentbox_outline",
        "description": "Extract AST outline (classes, functions, methods with line ranges) for one or more files or directories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                    "description": "File path, directory path, or list of paths"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "agentbox_get_fn",
        "description": "Extract exact function, method (supports ClassName.method_name), or class definition with line numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "name": {"type": "string", "description": "Function, class, or ClassName.method_name"}
            },
            "required": ["path", "name"]
        }
    },
    {
        "name": "agentbox_find_fn",
        "description": "Locate function or class definitions across the project via fast AST analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Symbol name or substring"},
                "path": {"type": "string", "description": "Directory to search (default: workspace root)"},
                "exact": {"type": "boolean", "description": "Exact case-sensitive match (default: false)"},
                "max": {"type": "integer", "description": "Max results (default: 30)"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "agentbox_refs",
        "description": "Find all references (imports, calls, attribute usages, inheritance) to a symbol across the codebase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Symbol name to find references for"},
                "path": {"type": "string", "description": "Directory or file path (default: workspace root)"},
                "max": {"type": "integer", "description": "Max results (default: 40)"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "agentbox_view",
        "description": "View an exact 1-indexed line slice of a file with line numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "start": {"type": "integer", "description": "Start line (1-indexed, default: 1)"},
                "end": {"type": "integer", "description": "End line (1-indexed, default: 100)"},
                "tail": {"type": "integer", "description": "View last N lines of file (overrides start/end)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "agentbox_patch",
        "description": "Atomic search-and-replace with automatic .bak backup, CRLF normalization, and Python AST syntax validation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "old": {"type": "string", "description": "Target text block to replace"},
                "new": {"type": "string", "description": "Replacement text block"},
                "all": {"type": "boolean", "description": "Replace all occurrences (default: false)"},
                "check_syntax": {"type": "boolean", "description": "Validate Python AST syntax before saving (default: true)"}
            },
            "required": ["path", "old", "new"]
        }
    },
    {
        "name": "agentbox_patch_lines",
        "description": "Atomically replace a 1-indexed inclusive line range [start..end] with new content, with auto-backup and AST syntax check.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "start": {"type": "integer", "description": "Start line (1-indexed, inclusive)"},
                "end": {"type": "integer", "description": "End line (1-indexed, inclusive)"},
                "content": {"type": "string", "description": "New content for the line range"},
                "check_syntax": {"type": "boolean", "description": "Validate Python AST syntax before saving (default: true)"}
            },
            "required": ["path", "start", "end", "content"]
        }
    },
    {
        "name": "agentbox_write",
        "description": "Safely write or append content to a file without shell quoting issues.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to target file"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default: false)"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "agentbox_rollback",
        "description": "Restore a file from its automatic .bak backup created by patch or patch_lines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "agentbox_tree",
        "description": "Compact directory tree ignoring build artifacts, virtualenvs, and VCS folders.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: workspace root)"},
                "depth": {"type": "integer", "description": "Max tree depth (default: 2)"}
            }
        }
    },
    {
        "name": "agentbox_grep",
        "description": "Fast regex/text search across project files or single file with result limits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or regex"},
                "path": {"type": "string", "description": "Directory or file path"},
                "fixed": {"type": "boolean", "description": "Treat query as exact fixed substring (default: false)"},
                "max": {"type": "integer", "description": "Max results (default: 20)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "agentbox_test",
        "description": "Silent high-signal test & typecheck runner: suppresses passing noise and extracts only failure tracebacks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Test command (e.g. pytest, cargo test, pnpm check)"},
                "cwd": {"type": "string", "description": "Working directory"},
                "max_lines": {"type": "integer", "description": "Max failure traceback lines (default: 30)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
                "venv": {"type": "string", "description": "Explicit virtualenv path"}
            },
            "required": ["cmd"]
        }
    },
    {
        "name": "agentbox_run",
        "description": "Silent command runner: buffers output to a log file and returns only exit status and tail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Command to execute"},
                "cwd": {"type": "string", "description": "Working directory"},
                "tail": {"type": "integer", "description": "Trailing lines to return (default: 15)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
                "venv": {"type": "string", "description": "Explicit virtualenv path"}
            },
            "required": ["cmd"]
        }
    },
    {
        "name": "agentbox_pip",
        "description": "Run pip inside an isolated virtualenv (auto-bootstrapping .agentbox/venv if no virtualenv exists).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pip_args": {"type": "string", "description": "Arguments to pass to pip (e.g. 'install requests')"},
                "cwd": {"type": "string", "description": "Working directory"},
                "venv": {"type": "string", "description": "Explicit virtualenv path"}
            },
            "required": ["pip_args"]
        }
    },
    {
        "name": "agentbox_git_status",
        "description": "Compact git status with (+added, -deleted) line counts per file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repository path"}
            }
        }
    },
    {
        "name": "agentbox_diff",
        "description": "Noise-free git diff ignoring lockfiles, binary assets, and whitespace changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path"},
                "rev": {"type": "string", "description": "Git revision or range"},
                "cached": {"type": "boolean", "description": "View staged changes"},
                "max_lines": {"type": "integer", "description": "Max diff lines (default: 100)"}
            }
        }
    },
    {
        "name": "agentbox_git_log",
        "description": "Compact one-line git commit log.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path"},
                "limit": {"type": "integer", "description": "Number of commits (default: 5)"}
            }
        }
    },
    {
        "name": "agentbox_stats",
        "description": "View token savings and execution statistics dashboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clear": {"type": "boolean", "description": "Clear recorded statistics"}
            }
        }
    },
    {
        "name": "agentbox_batch",
        "description": "Execute multiple AgentBox actions in a single call to save agent turns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "List of action objects: [{'action': 'outline', 'args': {'path': 'a.py'}}, ...]",
                    "items": {"type": "object"}
                },
                "stop_on_error": {"type": "boolean", "description": "Stop batch on first error (default: true)"}
            },
            "required": ["steps"]
        }
    }
]


def _resolve_project_root(args: Dict[str, Any], default_cwd: str = "") -> Optional[Path]:
    """Finds the local project root containing .agentbox.json from tool args or current directory."""
    candidates: List[str] = []
    if args.get("cwd"):
        candidates.append(str(args["cwd"]))
    raw_path = args.get("path") or args.get("paths")
    if isinstance(raw_path, list) and raw_path:
        candidates.append(str(raw_path[0]))
    elif isinstance(raw_path, str) and raw_path:
        candidates.append(raw_path)
    elif isinstance(args.get("steps"), list):
        for st in args["steps"]:
            if isinstance(st, dict) and isinstance(st.get("args"), dict):
                sp = st["args"].get("cwd") or st["args"].get("path")
                if isinstance(sp, str) and sp:
                    candidates.append(sp)
                    break
    if default_cwd:
        candidates.append(default_cwd)

    for cand in candidates:
        try:
            p = Path(os.path.expanduser(cand))
            probe = p if p.is_dir() else p.parent
            if probe.exists():
                found = find_local_config(probe)
                if found:
                    return found.parent.resolve()
        except Exception:
            pass

    found_cwd = find_local_config(Path.cwd())
    if found_cwd:
        return found_cwd.parent.resolve()
    return None


def invoke_tool_captured(
    tool_name: str,
    tool_args: Dict[str, Any],
    default_host: str = "",
    default_cwd: str = "",
    default_venv: str = ""
) -> Tuple[int, str]:
    """Executes an AgentBox tool and captures all stdout/stderr into a string."""
    action = tool_name
    if action.startswith("agentbox_"):
        action = action[len("agentbox_"):]

    args = dict(tool_args or {})

    # Dynamically discover and load .agentbox.json from the current project directory on every call
    project_root = _resolve_project_root(args, default_cwd)
    if project_root and project_root.is_dir():
        try:
            os.chdir(project_root)
        except Exception:
            pass

    cfg = get_config(start=project_root)

    host = args.pop("host", "") or default_host or cfg.get("host", "")
    eff_venv = args.get("venv") or default_venv or cfg.get("venv", "")
    is_remote = bool(host and host not in ("local", "localhost", "127.0.0.1", "."))

    arg_cwd = args.get("cwd")
    if is_remote:
        # If caller passed local workspace directory as cwd, use remote cwd from .agentbox.json instead
        if arg_cwd and project_root:
            try:
                if Path(os.path.expanduser(str(arg_cwd))).resolve() == project_root:
                    arg_cwd = None
                    args.pop("cwd", None)
            except Exception:
                pass
        cwd = arg_cwd or default_cwd or cfg.get("cwd", "")
        # Strip local project_root prefix from paths if present so remote paths stay relative to remote cwd
        if project_root:
            proj_norm = str(project_root).replace("\\", "/").rstrip("/") + "/"
            def _strip_local_prefix(val: Any) -> Any:
                if isinstance(val, str):
                    v_norm = val.replace("\\", "/")
                    if v_norm.lower().startswith(proj_norm.lower()):
                        return v_norm[len(proj_norm):]
                return val
            if "path" in args:
                if isinstance(args["path"], list):
                    args["path"] = [_strip_local_prefix(x) for x in args["path"]]
                else:
                    args["path"] = _strip_local_prefix(args["path"])
    else:
        cwd = arg_cwd or default_cwd or cfg.get("cwd", "") or (str(project_root) if project_root else "")

    if action in ("run", "test", "pip", "spawn", "graphify_build", "graphify_query"):
        args["cwd"] = cwd
        if eff_venv and not args.get("venv"):
            args["venv"] = eff_venv
    elif action in ("tree", "grep", "find_fn", "refs", "git_status", "diff", "git_log"):
        if not args.get("path") and cwd:
            args["path"] = cwd

    buf_out = io.StringIO()
    buf_err = io.StringIO()
    orig_out, orig_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf_out, buf_err
    try:
        code = execute_action(host, cwd, action, args)
    except SystemExit as se:
        code = se.code if isinstance(se.code, int) else 1
    except Exception as e:
        buf_err.write(f"ERROR: {e}\n")
        code = 1
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err

    out_text = buf_out.getvalue()
    err_text = buf_err.getvalue()
    combined = (out_text + ("\n" + err_text if err_text else "")).strip()
    return code, combined or ("OK" if code == 0 else f"Failed with exit code {code}")


def handle_mcp_request(
    req: Dict[str, Any],
    default_host: str = "",
    default_cwd: str = "",
    default_venv: str = ""
) -> Optional[Dict[str, Any]]:
    """Processes a single JSON-RPC 2.0 MCP message and returns a response dict (or None for notifications)."""
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    # Notifications have no "id" and expect no response
    if req_id is None:
        return None

    if method == "initialize":
        client_proto = params.get("protocolVersion", "2024-11-05")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_proto,
                "capabilities": {
                    "tools": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "ai-agentbox",
                    "version": __version__
                }
            }
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS}
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        valid_names = {t["name"] for t in MCP_TOOLS}
        if tool_name not in valid_names and f"agentbox_{tool_name}" not in valid_names:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"}
            }

        code, output_text = invoke_tool_captured(
            tool_name, tool_args, default_host, default_cwd, default_venv
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": output_text}],
                "isError": bool(code != 0)
            }
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def run_mcp_server(host: str = "", cwd: str = "", venv: str = "") -> int:
    """Runs the stdio MCP server loop supporting both line-delimited JSON and Content-Length framing."""
    eff_host = host
    eff_cwd = cwd
    eff_venv = venv

    raw_in = sys.stdin.buffer
    raw_out = sys.stdout.buffer

    def _send(resp: Dict[str, Any], use_content_length: bool) -> None:
        body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        if use_content_length:
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            raw_out.write(header + body)
        else:
            raw_out.write(body + b"\n")
        raw_out.flush()

    while True:
        first_line = raw_in.readline()
        if not first_line:
            break

        stripped = first_line.strip()
        if not stripped:
            continue

        use_cl = False
        if stripped.lower().startswith(b"content-length:"):
            use_cl = True
            try:
                length = int(stripped.split(b":", 1)[1].strip())
            except ValueError:
                continue
            # Consume remaining headers until empty line
            while True:
                hdr = raw_in.readline()
                if not hdr or hdr.strip() == b"":
                    break
            payload_bytes = raw_in.read(length)
            if not payload_bytes:
                break
        else:
            payload_bytes = stripped

        try:
            req = json.loads(payload_bytes.decode("utf-8", errors="replace"))
        except Exception as e:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }
            _send(err_resp, use_cl)
            continue

        if isinstance(req, list):
            responses = []
            for item in req:
                if isinstance(item, dict):
                    r = handle_mcp_request(item, eff_host, eff_cwd, eff_venv)
                    if r is not None:
                        responses.append(r)
            if responses:
                _send(responses, use_cl)
        elif isinstance(req, dict):
            resp = handle_mcp_request(req, eff_host, eff_cwd, eff_venv)
            if resp is not None:
                _send(resp, use_cl)

    return 0
