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
import base64
import subprocess
import argparse
import io
import fnmatch
import hashlib
import tarfile
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Union

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


def parse_file_mapping(spec: str) -> Tuple[str, str]:
    r"""
    Parses a 'source[:destination]' mapping spec.
    Handles Windows drive letters (e.g. C:\... or C:/...) on both source and destination without false splits.
    If no destination is specified, destination defaults to source.
    """
    start_search = 0
    if len(spec) >= 2 and spec[0].isalpha() and spec[1] == ":" and (len(spec) == 2 or spec[2] in "\\/"):
        start_search = 2

    sep_idx = spec.find(":", start_search)
    if sep_idx == -1:
        return spec, spec

    src = spec[:sep_idx]
    dest = spec[sep_idx + 1:]
    return src, dest or src


DEFAULT_IGNORED_DIRS = {
    ".git", ".agentbox", ".venv", "venv", "env", "__pycache__", "node_modules",
    "target", "dist", "build", ".vscode", ".idea", ".agents",
    "graphify-out", ".mypy_cache", ".pytest_cache"
}

GIT_IGNORE_DIFF_PATTERNS = [
    "*.lock", "package-lock.json", "poetry.lock", "pnpm-lock.yaml",
    "yarn.lock", "Cargo.lock", "*.min.js", "*.min.css", "*.map",
    "*.svg", "*.png", "*.jpg", "*.jpeg", "*.ico", "*.pdf", "*.woff", "*.woff2"
]


def win_no_window_kwargs(extra_flags: int = 0) -> dict:
    """Returns creationflags on Windows to suppress terminal/console window popups."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if extra_flags:
            flags |= extra_flags
        return {"creationflags": flags}
    return {}


def to_path(p: str = None) -> Path:
    if not p:
        return Path.cwd()
    return Path(os.path.expanduser(str(p))).resolve()


def _find_git_root(p: Path) -> Optional[Path]:
    """Finds nearest parent directory containing .git."""
    curr = p if p.is_dir() else p.parent
    while curr != curr.parent:
        if (curr / ".git").exists():
            return curr
        curr = curr.parent
    return None


def _get_backup_path(target_file: Path) -> Path:
    """Returns safe backup path inside .agentbox/backups/ instead of cluttering project tree."""
    resolved = target_file.resolve()
    git_root = _find_git_root(resolved)
    if git_root:
        backup_dir = git_root / ".agentbox" / "backups"
        try:
            rel = resolved.relative_to(git_root.resolve())
            bak_name = rel.as_posix().replace("/", "__") + ".bak"
        except ValueError:
            bak_name = resolved.name + ".bak"
    else:
        backup_dir = Path.home() / ".agentbox" / "backups"
        bak_name = f"{abs(hash(str(resolved)))}_{resolved.name}.bak"

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        # Ensure .agentbox is ignored by git if inside repo
        if git_root:
            gi = git_root / ".agentbox" / ".gitignore"
            if not gi.exists():
                gi.write_text("*\n", encoding="utf-8")
    except Exception:
        pass

    return backup_dir / bak_name


def _is_venv_dir(p: Path) -> bool:
    """Checks whether a directory looks like a valid Python virtual environment."""
    if not p.is_dir():
        return False
    if (p / "pyvenv.cfg").is_file():
        return True
    if (p / "bin" / "activate").is_file() or (p / "bin" / "python").is_file() or (p / "bin" / "python3").is_file():
        return True
    if (p / "Scripts" / "activate.bat").is_file() or (p / "Scripts" / "python.exe").is_file():
        return True
    if (p / "bin").is_dir() or (p / "Scripts").is_dir():
        return True
    return False


def _get_venv_bin_dir(venv_path: Path) -> Optional[Path]:
    """Returns bin (POSIX) or Scripts (Windows) directory for a virtualenv."""
    if (venv_path / "bin").is_dir():
        return venv_path / "bin"
    if (venv_path / "Scripts").is_dir():
        return venv_path / "Scripts"
    return None


def _get_venv_python(venv_path: Path) -> Optional[Path]:
    """Returns the python executable inside a virtualenv."""
    bin_dir = _get_venv_bin_dir(venv_path)
    if not bin_dir:
        return None
    for exe_name in ("python.exe", "python3", "python"):
        cand = bin_dir / exe_name
        if cand.is_file():
            return cand
    return bin_dir / ("python.exe" if os.name == "nt" else "python")


def _venv_label(venv_dir: Optional[Path]) -> str:
    """Returns human-readable label for a virtualenv directory."""
    if not venv_dir:
        return ""
    if venv_dir.name == "venv" and venv_dir.parent.name == ".agentbox":
        return ".agentbox/venv"
    return venv_dir.name


def find_virtualenv(work_dir: Path, explicit_venv: Optional[str] = None) -> Optional[Path]:
    """Finds active, configured, or auto-detected virtualenv directory with .agentbox/venv priority."""
    if explicit_venv:
        v_str = str(explicit_venv).strip()
        if v_str:
            p = Path(os.path.expanduser(v_str))
            # Handle POSIX / Windows root paths and relative paths
            if not p.is_absolute() and not v_str.startswith(("/", "\\", "~")):
                p = (work_dir / p).resolve()
            # If user pointed to bin or Scripts directly
            if p.name in ("bin", "Scripts") and p.parent.is_dir():
                p = p.parent
            # If user pointed to python executable
            elif p.is_file() and p.parent.name in ("bin", "Scripts"):
                p = p.parent.parent
            if _is_venv_dir(p) or p.is_dir():
                return p

    # Auto-detection:
    # 1. Direct subdirectories in work_dir (.agentbox/venv has highest priority)
    candidates = [".agentbox/venv", ".agentbox", ".venv", "venv", ".env", "env"]
    for name in candidates:
        cand = work_dir / name
        if _is_venv_dir(cand):
            return cand

    # 2. Check parents of work_dir (up to filesystem root or git/config boundary)
    curr = work_dir.parent
    while curr != curr.parent:
        for name in [".agentbox/venv", ".agentbox", ".venv", "venv"]:
            cand = curr / name
            if _is_venv_dir(cand):
                return cand
        if (curr / ".git").exists() or (curr / ".agentbox.json").exists():
            break
        curr = curr.parent

    # 3. Check VIRTUAL_ENV environment variable
    env_venv = os.environ.get("VIRTUAL_ENV")
    if env_venv:
        p = Path(os.path.expanduser(env_venv))
        if _is_venv_dir(p):
            return p

    return None


def ensure_virtualenv(work_dir: Path, explicit_venv: Optional[str] = None) -> Path:
    """Ensures a virtualenv exists for work_dir, bootstrapping .agentbox/venv if none is found."""
    existing = find_virtualenv(work_dir, explicit_venv)
    if existing:
        return existing

    target_venv = (work_dir / ".agentbox" / "venv").resolve()
    target_venv.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(target_venv)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            **win_no_window_kwargs()
        )
    except Exception:
        import venv as _venv_mod
        _venv_mod.create(str(target_venv), with_pip=True)
    return target_venv


def sanitize_python_cmd(cmd: str, venv_dir: Optional[Path]) -> str:
    """Rewrites direct calls to system python interpreters to use the active virtualenv python."""
    if not venv_dir or not cmd:
        return cmd
    venv_py = _get_venv_python(venv_dir)
    replacement = f'"{venv_py}"' if venv_py and " " in str(venv_py) else (str(venv_py) if venv_py else "python")
    # Match direct system interpreter invocations at start of command or after shell separators
    sys_py_pattern = re.compile(
        r'(^|[;&|]\s*)(?:/usr/local/bin/python[0-9.]*|/usr/bin/python[0-9.]*|/bin/python[0-9.]*)\b'
    )
    return sys_py_pattern.sub(lambda m: f"{m.group(1)}{replacement}", cmd)


def prepare_env_for_cmd(
    work_dir: Path,
    explicit_venv: Optional[str] = None,
    auto_create: bool = False
) -> Tuple[Dict[str, str], Optional[Path]]:
    """Prepares process environment with virtualenv PATH prefixed and foreign venvs sanitized."""
    should_create = auto_create or (os.environ.get("AGENTBOX_AUTO_VENV") == "1")
    venv_dir = ensure_virtualenv(work_dir, explicit_venv) if should_create else find_virtualenv(work_dir, explicit_venv)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["LC_ALL"] = "C.UTF-8"
    env["LANG"] = "C.UTF-8"
    if venv_dir:
        bin_dir = _get_venv_bin_dir(venv_dir)
        if bin_dir:
            orig_path = env.get("PATH", "")
            # Filter out foreign virtualenv bin/Scripts directories from PATH
            clean_parts = []
            for part in orig_path.split(os.pathsep):
                if not part:
                    continue
                try:
                    p_part = Path(part)
                    if p_part.name in ("bin", "Scripts") and (p_part.parent / "pyvenv.cfg").is_file():
                        if p_part.parent.resolve() != venv_dir.resolve():
                            continue
                except Exception:
                    pass
                clean_parts.append(part)
            sanitized_path = os.pathsep.join(clean_parts)
            env["PATH"] = f"{bin_dir}{os.pathsep}{sanitized_path}" if sanitized_path else str(bin_dir)
            env["VIRTUAL_ENV"] = str(venv_dir)
            env.pop("PYTHONHOME", None)
            return env, venv_dir
    return env, None


def _record_token_stat(action: str, raw_chars: int, out_chars: int, target: str = "") -> None:
    """Records token savings for read/navigation/slice operations into history.jsonl."""
    try:
        log_dir = _get_log_dir()
        history_file = log_dir / "history.jsonl"
        saved_chars = max(0, raw_chars - out_chars)
        record = {
            "ts": int(time.time()),
            "type": action,
            "cmd": f"{action} {target}".strip(),
            "cwd": str(Path.cwd()),
            "exit": 0,
            "duration": 0.0,
            "raw_bytes": raw_chars,
            "out_bytes": out_chars,
            "saved_tokens": saved_chars // 4
        }
        with open(history_file, "a", encoding="utf-8") as hf:
            hf.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _find_brace_block_end(lines: List[str], start_line: int) -> int:
    """
    Finds the 1-indexed closing line of a brace-delimited block '{ ... }'
    starting at or shortly after `start_line` (1-indexed).
    Ignores braces inside string literals and line/block comments.
    """
    n = len(lines)
    depth = 0
    found_open = False
    in_block_comment = False
    in_string: Optional[str] = None

    for idx in range(max(1, start_line) - 1, n):
        line = lines[idx]
        i = 0
        L = len(line)
        while i < L:
            ch = line[i]
            nxt = line[i + 1] if i + 1 < L else ""

            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            if in_string:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_string:
                    in_string = None
                i += 1
                continue

            if ch == "/" and nxt == "/":
                break  # Rest of line is comment
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue
            if ch in ('"', "'", "`"):
                in_string = ch
                i += 1
                continue

            if ch == "{":
                depth += 1
                found_open = True
            elif ch == "}":
                if found_open:
                    depth -= 1
                    if depth <= 0:
                        return idx + 1
            elif ch == ";" and not found_open and idx >= start_line - 1:
                # Declaration without body (e.g. trait method signature or C prototype)
                return idx + 1
            i += 1

        # If after scanning 5 lines we still haven't seen an opening '{', treat as single-line
        if not found_open and (idx - (start_line - 1)) >= 4:
            return start_line

    return min(n, start_line + 40) if not found_open else n


def cmd_view(path: str, start: int = 1, end: int = 100, tail: Optional[int] = None) -> None:
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    total = len(lines)
    if tail is not None and tail > 0:
        s = max(1, total - tail + 1)
        e = total
    else:
        if start < 0:
            s = max(1, total + start + 1)
            if end < 0:
                e = max(s, min(total, total + end + 1))
            else:
                e = total
        else:
            s = max(1, start)
            e = min(total, end)

    out_lines = [f"[{p.name}: lines {s}-{e} of {total}]"]
    for i in range(s, e + 1):
        out_lines.append(f"{i:4d} | {lines[i - 1].rstrip()}")
    output = "\n".join(out_lines)
    print(output)
    _record_token_stat("view", len(content), len(output), p.name)


def _outline_single_file(p: Path) -> Tuple[int, int]:
    """Outputs outline for a single file and returns (raw_chars, out_chars)."""
    ext = p.suffix.lower()
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception as e:
        print(f"ERROR: Failed to read {p}: {e}", file=sys.stderr)
        return 0, 0

    out_buf: List[str] = [f"=== OUTLINE: {p.name} ({len(lines)} lines) ==="]

    if ext == ".py":
        try:
            tree = ast.parse(content, filename=str(p))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in node.args.args]
                    ret = f" -> {ast.unparse(node.returns)}" if getattr(node, 'returns', None) else ""
                    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    end_ln = getattr(node, 'end_lineno', node.lineno)
                    out_buf.append(f"{node.lineno:4d}-{end_ln:4d} | {prefix} {node.name}({', '.join(args)}){ret}")
                elif isinstance(node, ast.ClassDef):
                    end_ln = getattr(node, 'end_lineno', node.lineno)
                    bases = [ast.unparse(b) for b in node.bases]
                    base_str = f"({', '.join(bases)})" if bases else ""
                    out_buf.append(f"{node.lineno:4d}-{end_ln:4d} | class {node.name}{base_str}:")
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = [a.arg for a in sub.args.args]
                            ret = f" -> {ast.unparse(sub.returns)}" if getattr(sub, 'returns', None) else ""
                            sub_prefix = "async def" if isinstance(sub, ast.AsyncFunctionDef) else "def"
                            sub_end = getattr(sub, 'end_lineno', sub.lineno)
                            out_buf.append(f"{sub.lineno:4d}-{sub_end:4d} |     {sub_prefix} {sub.name}({', '.join(args)}){ret}")
            output = "\n".join(out_buf)
            print(output)
            return len(content), len(output)
        except Exception:
            pass  # Fallback to regex

    # Regex + brace-balanced end line detection for Rust, JS, TS, C, C++, Go, etc.
    regexes = [
        re.compile(r"^\s*(pub(?:\([^)]+\))?\s+)?(async\s+)?fn\s+([a-zA-Z0-9_]+)\s*(<[^>]+>)?\s*\((.*?)\)"),
        re.compile(r"^\s*(pub(?:\([^)]+\))?\s+)?(struct|enum|trait|impl)\b(.*)$"),
        re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s+([a-zA-Z0-9_]+)\s*(<[^>]+>)?\s*\((.*?)\)"),
        re.compile(r"^\s*(export\s+)?(default\s+)?(abstract\s+)?(class|interface|type)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^\s*(export\s+)?(const|let|var)\s+([a-zA-Z0-9_]+)\s*=\s*(async\s*)?\((.*?)\)\s*=>"),
        re.compile(r"^\s*func\s+(\([^)]+\)\s*)?([a-zA-Z0-9_]+)\s*\((.*?)\)"),
    ]

    for idx, line in enumerate(lines, start=1):
        for rx in regexes:
            if rx.search(line):
                end_ln = _find_brace_block_end(lines, idx)
                sig = line.strip().rstrip("{").strip()[:100]
                if end_ln > idx:
                    out_buf.append(f"{idx:4d}-{end_ln:4d} | {sig}")
                else:
                    out_buf.append(f"{idx:4d}      | {sig}")
                break

    output = "\n".join(out_buf)
    print(output)
    return len(content), len(output)


def cmd_outline(path: Union[str, List[str]]) -> None:
    """Extracts AST outline for one or multiple files or directories."""
    paths = [path] if isinstance(path, str) else list(path or [])
    if not paths:
        print("ERROR: Missing path for outline", file=sys.stderr)
        sys.exit(1)

    code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".h", ".hpp"}
    targets: List[Path] = []
    for raw_p in paths:
        p = to_path(raw_p)
        if p.is_file():
            targets.append(p)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted([d for d in dirs if d not in DEFAULT_IGNORED_DIRS and not d.startswith(".")])
                for f in sorted(files):
                    fp = Path(root) / f
                    if fp.suffix.lower() in code_exts:
                        targets.append(fp)
                        if len(targets) >= 25:
                            break
                if len(targets) >= 25:
                    break
        else:
            print(f"ERROR: File not found: {raw_p}", file=sys.stderr)
            sys.exit(1)

    total_raw = 0
    total_out = 0
    for idx, t in enumerate(targets):
        if idx > 0:
            print()
        r_len, o_len = _outline_single_file(t)
        total_raw += r_len
        total_out += o_len

    _record_token_stat("outline", total_raw, total_out, ",".join(str(x) for x in paths))


def cmd_get_fn(path: str, name: Union[str, List[str]]) -> None:
    """
    Extracts exact function, method, or class definition(s).
    Supports qualified `ClassName.method_name` lookups and decorator inclusion.
    Accepts a single name or a list of names.
    """
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    target_names = [name] if isinstance(name, str) else list(name)
    if not target_names:
        print(f"ERROR: No function or class names provided", file=sys.stderr)
        sys.exit(1)

    ext = p.suffix.lower()
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    tree = None
    if ext == ".py":
        try:
            tree = ast.parse(content, filename=str(p))
        except Exception:
            tree = None

    def _node_span(n: ast.AST) -> Tuple[int, int]:
        decs = getattr(n, "decorator_list", None) or []
        start_line = min([n.lineno] + [d.lineno for d in decs if hasattr(d, "lineno")])
        end_line = getattr(n, "end_lineno", n.lineno)
        return start_line, end_line

    found_sections: List[str] = []
    missing_names: List[str] = []

    for target in target_names:
        matches: List[Tuple[str, int, int]] = []
        if tree is not None:
            if "." in target:
                parts = target.split(".")
                curr_nodes = list(tree.body)
                qual_prefix = []
                for idx_part, part in enumerate(parts):
                    found_next = None
                    for n in curr_nodes:
                        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part:
                            found_next = n
                            break
                    if not found_next:
                        curr_nodes = []
                        break
                    qual_prefix.append(part)
                    if idx_part == len(parts) - 1:
                        s, e = _node_span(found_next)
                        matches.append((".".join(qual_prefix), s, e))
                    else:
                        curr_nodes = list(getattr(found_next, "body", []))
            else:
                def _walk_scope(body_nodes, scope_prefix=""):
                    for n in body_nodes:
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            qual = f"{scope_prefix}.{n.name}" if scope_prefix else n.name
                            if n.name == target:
                                s, e = _node_span(n)
                                matches.append((qual, s, e))
                            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                                _walk_scope(getattr(n, "body", []), qual)

                _walk_scope(tree.body)

        if matches:
            out_lines: List[str] = []
            for idx_m, (qual_name, s, e) in enumerate(matches):
                if idx_m > 0:
                    out_lines.append("")
                out_lines.append(f"[{p.name}: {qual_name} lines {s}-{e}]")
                for i in range(s, e + 1):
                    out_lines.append(f"{i:4d} | {lines[i - 1]}")
            found_sections.append("\n".join(out_lines))
            continue

        # Generic search with brace-balanced block extraction for Rust, TS, JS, Go, C/C++
        short_name = target.split(".")[-1]
        patterns = [
            re.compile(rf"\b(def|fn|function|class|struct|enum|trait|interface|type|func)\b[^\n]*?\b{re.escape(short_name)}\b"),
            re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+{re.escape(short_name)}\s*="),
            re.compile(rf"^\s*(?:pub\s+)?(?:async\s+)?{re.escape(short_name)}\s*\([^;]*\)\s*(?::\s*[^{{]+)?\{{"),
        ]
        generic_found = False
        for idx, line in enumerate(lines, start=1):
            if any(rx.search(line) for rx in patterns):
                end_ln = _find_brace_block_end(lines, idx)
                out_lines = [f"[{p.name}: {target} lines {idx}-{end_ln}]"]
                for j in range(idx, min(len(lines) + 1, end_ln + 1)):
                    out_lines.append(f"{j:4d} | {lines[j - 1]}")
                found_sections.append("\n".join(out_lines))
                generic_found = True
                break

        if not generic_found:
            missing_names.append(target)

    if found_sections:
        output = "\n\n".join(found_sections)
        print(output)
        _record_token_stat("get_fn", len(content), len(output), f"{p.name}:{','.join(target_names)}")
        if missing_names:
            for m in missing_names:
                print(f"WARNING: Function or class '{m}' not found in {p.name}", file=sys.stderr)
        return

    if len(target_names) == 1:
        print(f"ERROR: Function or class '{target_names[0]}' not found in {p.name}", file=sys.stderr)
    else:
        print(f"ERROR: None of the requested functions/classes ({', '.join(target_names)}) were found in {p.name}", file=sys.stderr)
    sys.exit(1)


def cmd_find_fn(name: str, path: str = ".", exact: bool = False, max_results: int = 30) -> None:
    """Recursively locates functions and classes across the project via AST analysis."""
    p = to_path(path)
    search_root = p.parent if p.is_file() else p

    if not search_root.is_dir():
        print(f"ERROR: Directory not found: {path}", file=sys.stderr)
        sys.exit(1)

    code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".h", ".hpp"}
    matches = []
    target_lower = name.lower()

    generic_rx = re.compile(
        r"^\s*(?:pub\s+)?(?:async\s+)?(?:export\s+)?(?:default\s+)?(?:def|fn|function|class|struct|trait|func)\s+([a-zA-Z0-9_]+)"
    )

    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORED_DIRS and not d.startswith(".")]
        for file in files:
            fp = Path(root) / file
            ext = fp.suffix.lower()
            if ext not in code_exts:
                continue

            try:
                rel = fp.relative_to(search_root)
            except Exception:
                rel = fp

            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if ext == ".py":
                try:
                    tree = ast.parse(content, filename=str(fp))
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            n_name = node.name
                            hit = (n_name == name) if exact else (target_lower in n_name.lower())
                            if hit:
                                if isinstance(node, ast.ClassDef):
                                    bases = [ast.unparse(b) for b in node.bases]
                                    base_str = f"({', '.join(bases)})" if bases else ""
                                    sig = f"class {node.name}{base_str}"
                                else:
                                    pref = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                                    args = [a.arg for a in node.args.args]
                                    ret = f" -> {ast.unparse(node.returns)}" if getattr(node, 'returns', None) else ""
                                    sig = f"{pref} {node.name}({', '.join(args)}){ret}"
                                matches.append((str(rel).replace("\\", "/"), node.lineno, sig))
                                if len(matches) >= max_results:
                                    break
                except Exception:
                    pass
            else:
                for line_idx, line in enumerate(content.splitlines(), start=1):
                    m = generic_rx.search(line)
                    if m:
                        n_name = m.group(1)
                        hit = (n_name == name) if exact else (target_lower in n_name.lower())
                        if hit:
                            matches.append((str(rel).replace("\\", "/"), line_idx, line.strip()[:90]))
                            if len(matches) >= max_results:
                                break

            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    if not matches:
        print(f"No symbols found matching '{name}' in {search_root.name or '.'}")
        return

    print(f"=== FOUND SYMBOLS: '{name}' ({len(matches)} matches) ===")
    for rel_path, lineno, sig in matches:
        print(f"  {rel_path}:{lineno:<4d} | {sig}")


def cmd_refs(name: str, path: str = ".", max_results: int = 40) -> None:
    """
    Finds symbol references (imports, calls, attribute usages, inheritance) across the codebase.
    Filters out comments and unrelated substring matches.
    """
    p = to_path(path)
    search_root = p.parent if p.is_file() else p
    single_file = p if p.is_file() else None

    if not search_root.is_dir():
        print(f"ERROR: Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".svelte"}
    refs: List[Tuple[str, int, str, str]] = []
    word_rx = re.compile(rf"\b{re.escape(name)}\b")
    call_rx = re.compile(rf"\b{re.escape(name)}\s*\(")
    import_rx = re.compile(rf"^\s*(?:import|from|use|require)\b.*\b{re.escape(name)}\b")

    def _scan_file(fp: Path):
        ext = fp.suffix.lower()
        if ext not in code_exts:
            return
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        if name not in content:
            return

        lines = content.splitlines()
        try:
            rel = str(fp.relative_to(search_root)).replace("\\", "/") if not single_file else fp.name
        except Exception:
            rel = str(fp)

        if ext == ".py":
            try:
                tree = ast.parse(content, filename=str(fp))
                line_kinds: Dict[int, str] = {}

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == name or alias.name.endswith(f".{name}") or alias.asname == name:
                                line_kinds[node.lineno] = "import"
                    elif isinstance(node, ast.ImportFrom):
                        if (node.module and (node.module == name or node.module.endswith(f".{name}"))) or any(
                            a.name == name or a.asname == name for a in node.names
                        ):
                            line_kinds[node.lineno] = "import"
                    elif isinstance(node, ast.Call):
                        func = node.func
                        if (isinstance(func, ast.Name) and func.id == name) or (
                            isinstance(func, ast.Attribute) and func.attr == name
                        ):
                            line_kinds[node.lineno] = "call"
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name == name:
                            line_kinds.setdefault(node.lineno, "def")
                        if isinstance(node, ast.ClassDef):
                            for b in node.bases:
                                if (isinstance(b, ast.Name) and b.id == name) or (
                                    isinstance(b, ast.Attribute) and b.attr == name
                                ):
                                    line_kinds[node.lineno] = "inherit"
                    elif isinstance(node, ast.Attribute) and node.attr == name:
                        line_kinds.setdefault(node.lineno, "attr")
                    elif isinstance(node, ast.Name) and node.id == name:
                        line_kinds.setdefault(node.lineno, "ref")

                for ln in sorted(line_kinds.keys()):
                    if 1 <= ln <= len(lines):
                        refs.append((rel, ln, line_kinds[ln], lines[ln - 1].strip()[:100]))
                        if len(refs) >= max_results:
                            return
                return
            except Exception:
                pass

        # Non-Python or fallback scan (skipping comment lines)
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(("//", "#", "/*", "*")):
                continue
            if word_rx.search(line):
                if import_rx.search(line):
                    kind = "import"
                elif call_rx.search(line):
                    kind = "call"
                else:
                    kind = "ref"
                refs.append((rel, idx, kind, stripped[:100]))
                if len(refs) >= max_results:
                    return

    if single_file:
        _scan_file(single_file)
    else:
        for root, dirs, files in os.walk(search_root):
            dirs[:] = sorted([d for d in dirs if d not in DEFAULT_IGNORED_DIRS and not d.startswith(".")])
            for file in sorted(files):
                _scan_file(Path(root) / file)
                if len(refs) >= max_results:
                    break
            if len(refs) >= max_results:
                break

    if not refs:
        print(f"No references found for '{name}' in {search_root.name or '.'}")
        return

    print(f"=== REFERENCES: '{name}' ({len(refs)} matches) ===")
    for rel_path, lineno, kind, snippet in refs:
        print(f"  {rel_path}:{lineno:<4d} | [{kind:<7s}] {snippet}")


def _validate_syntax(path: Path, old_content: str, new_content: str) -> Optional[str]:
    """
    If `path` is a supported file (.py, .json) that previously parsed cleanly (or did not exist),
    checks if `new_content` has valid syntax.
    Returns None if valid, or a formatted SyntaxError description if broken.
    """
    ext = path.suffix.lower()
    if ext == ".py":
        if old_content:
            try:
                ast.parse(old_content, filename=str(path))
            except SyntaxError:
                # Original file already had syntax errors; allow patching to fix it
                return None
        try:
            ast.parse(new_content, filename=str(path))
            return None
        except SyntaxError as se:
            err_line = se.text.strip() if se.text else ""
            return f"Line {se.lineno}: {se.msg}" + (f" -> `{err_line}`" if err_line else "")

    elif ext == ".json":
        if old_content:
            try:
                json.loads(old_content)
            except Exception:
                # Original file already had JSON syntax errors; allow patching to fix it
                return None
        try:
            json.loads(new_content)
            return None
        except json.JSONDecodeError as jde:
            return f"Line {jde.lineno} col {jde.colno}: {jde.msg}"
        except Exception as e:
            return str(e)

    return None


_validate_python_syntax = _validate_syntax

def cmd_patch(
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    check_syntax: bool = True
) -> None:
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        raw_bytes = p.read_bytes()
        file_newline = "\r\n" if b"\r\n" in raw_bytes else "\n"
        content = raw_bytes.decode("utf-8")
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Normalize to LF internally for reliable matching across CRLF/LF environments
    norm_content = content.replace("\r\n", "\n")
    norm_old = old_text.replace("\r\n", "\n")
    norm_new = new_text.replace("\r\n", "\n")

    count = norm_content.count(norm_old)
    matched_via_fuzzy = False

    if count == 0:
        # Fallback: trailing-whitespace tolerant line matching
        c_lines = norm_content.split("\n")
        o_lines = norm_old.split("\n")
        if o_lines and any(l.strip() for l in o_lines):
            c_stripped = [l.rstrip() for l in c_lines]
            o_stripped = [l.rstrip() for l in o_lines]
            m_len = len(o_stripped)
            match_indices = [
                i for i in range(len(c_stripped) - m_len + 1)
                if c_stripped[i:i + m_len] == o_stripped
            ]
            count = len(match_indices)
            if count == 1 or (count > 1 and replace_all):
                matched_via_fuzzy = True
                n_lines = norm_new.split("\n")
                for idx in reversed(match_indices if replace_all else match_indices[:1]):
                    c_lines[idx:idx + m_len] = n_lines
                new_norm_content = "\n".join(c_lines)

    if count == 0:
        print(f"ERROR: Target content not found in {p.name}", file=sys.stderr)
        sys.exit(1)
    if count > 1 and not replace_all:
        print(f"ERROR: Target content found {count} times in {p.name}. Provide unique context or use --all", file=sys.stderr)
        sys.exit(1)

    if not matched_via_fuzzy:
        new_norm_content = (
            norm_content.replace(norm_old, norm_new)
            if replace_all
            else norm_content.replace(norm_old, norm_new, 1)
        )

    # Validate Python AST syntax before committing
    if check_syntax:
        syntax_err = _validate_syntax(p, norm_content, new_norm_content)
        if syntax_err:
            kind = "Python SyntaxError" if p.suffix.lower() == ".py" else ("JSON SyntaxError" if p.suffix.lower() == ".json" else "SyntaxError")
            print(
                f"ERROR: Patch rejected — introduced {kind} in {p.name} ({syntax_err}). File was NOT modified.",
                file=sys.stderr
            )
            sys.exit(1)

    # Backup original bytes safely into .agentbox/backups/
    bak_path = _get_backup_path(p)
    try:
        bak_path.write_bytes(raw_bytes)
    except Exception as e:
        print(f"ERROR: Failed to create backup {bak_path.name}: {e}", file=sys.stderr)
        sys.exit(1)

    final_content = new_norm_content.replace("\n", file_newline) if file_newline == "\r\n" else new_norm_content
    p.write_bytes(final_content.encode("utf-8"))

    print("OK")


def cmd_patch_lines(
    path: str,
    start: int,
    end: int,
    content: Optional[str] = None,
    check_syntax: bool = True
) -> None:
    """Atomically replaces 1-indexed line range [start..end] inclusive with new content."""
    p = to_path(path)
    if not p.is_file():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    if content is None:
        content = read_stdin_utf8()

    try:
        raw_bytes = p.read_bytes()
        file_newline = "\r\n" if b"\r\n" in raw_bytes else "\n"
        orig_text = raw_bytes.decode("utf-8")
    except Exception as e:
        print(f"ERROR: Failed to read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    norm_orig = orig_text.replace("\r\n", "\n")
    lines = norm_orig.split("\n")
    total = len(lines)

    if start < 1 or end < start or start > total:
        print(f"ERROR: Invalid line range {start}-{end} for {p.name} ({total} lines)", file=sys.stderr)
        sys.exit(1)

    end_clamped = min(total, end)
    norm_replacement = content.replace("\r\n", "\n")
    # Avoid inserting an extra trailing empty line if replacement ends with newline
    if norm_replacement.endswith("\n"):
        rep_lines = norm_replacement[:-1].split("\n")
    else:
        rep_lines = norm_replacement.split("\n") if norm_replacement else []

    new_lines = lines[:start - 1] + rep_lines + lines[end_clamped:]
    new_norm_text = "\n".join(new_lines)

    if check_syntax:
        syntax_err = _validate_syntax(p, norm_orig, new_norm_text)
        if syntax_err:
            kind = "Python SyntaxError" if p.suffix.lower() == ".py" else ("JSON SyntaxError" if p.suffix.lower() == ".json" else "SyntaxError")
            print(
                f"ERROR: Line patch rejected — introduced {kind} in {p.name} ({syntax_err}). File was NOT modified.",
                file=sys.stderr
            )
            sys.exit(1)

    # Backup original bytes safely into .agentbox/backups/
    bak_path = _get_backup_path(p)
    try:
        bak_path.write_bytes(raw_bytes)
    except Exception as e:
        print(f"ERROR: Failed to create backup {bak_path.name}: {e}", file=sys.stderr)
        sys.exit(1)

    final_content = new_norm_text.replace("\n", file_newline) if file_newline == "\r\n" else new_norm_text
    p.write_bytes(final_content.encode("utf-8"))
    print("OK")


def cmd_rollback(path: str) -> None:
    p = to_path(path)
    bak_path = _get_backup_path(p)
    if not bak_path.is_file():
        # Fallback to legacy in-tree backup
        legacy_bak = p.with_suffix(p.suffix + ".bak")
        if legacy_bak.is_file():
            bak_path = legacy_bak
        else:
            print(f"ERROR: Backup file for {p.name} not found (checked {bak_path.name})", file=sys.stderr)
            sys.exit(1)

    bak_bytes = bak_path.read_bytes()
    p.write_bytes(bak_bytes)
    try:
        bak_path.unlink()
    except Exception:
        pass
    print("OK")


def cmd_write(path: str, content: str = None, append: bool = False) -> None:
    """Safely writes or appends content to a file, reading from stdin if content is None."""
    p = to_path(path)
    if content is None:
        content = read_stdin_utf8()

    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    try:
        with open(p, mode, encoding="utf-8", newline="") as f:
            f.write(content)
        print("OK")
    except Exception as e:
        print(f"ERROR: Failed writing to {path}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_write_files(files: List[Dict[str, Any]], append: bool = False) -> None:
    """Safely writes multiple files in a single invocation."""
    if not files:
        print("OK (0 files written)")
        return

    mode = "a" if append else "w"
    written_count = 0
    for item in files:
        if not isinstance(item, dict):
            continue
        target_path = item.get("path")
        if not target_path:
            continue
        content = item.get("content")
        if content is None and item.get("base64"):
            content = decode_base64_text(item["base64"])
        if content is None:
            content = ""

        p = to_path(target_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, mode, encoding="utf-8", newline="") as f:
                f.write(content)
            written_count += 1
        except Exception as e:
            print(f"ERROR: Failed writing to {target_path}: {e}", file=sys.stderr)
            sys.exit(1)

    if written_count == 1:
        print("OK")
    else:
        print(f"OK ({written_count} files written)")


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


def _grep_file(pattern: re.Pattern, fpath: Path, display_path: Union[str, Path], max_results: int, files_only: bool = False) -> int:
    count = 0
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
            for idx, line in enumerate(fh, start=1):
                if pattern.search(line):
                    if files_only:
                        print(str(display_path))
                        return 1
                    print(f"{display_path}:{idx} | {line.strip()[:120]}")
                    count += 1
                    if count >= max_results:
                        return count
    except Exception:
        pass
    return count


def _grep_python(pattern: re.Pattern, root: Path, max_results: int, files_only: bool = False) -> None:
    if root.is_file():
        count = _grep_file(pattern, root, root.name, max_results, files_only=files_only)
        if count >= max_results and not files_only:
            print(f"... [stopped at max {max_results} results]")
        return

    count = 0
    for cur_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORED_DIRS]
        for f in files:
            if f.endswith((".pyc", ".png", ".jpg", ".bin", ".tar", ".gz", ".zip", ".iso", ".frb")):
                continue
            fpath = Path(cur_root) / f
            try:
                rel = fpath.relative_to(root)
            except ValueError:
                rel = fpath
            count += _grep_file(pattern, fpath, rel, max_results - count, files_only=files_only)
            if count >= max_results:
                if not files_only:
                    print(f"... [stopped at max {max_results} results]")
                return


def cmd_grep(query: str, path: str = ".", max_results: int = 20, fixed: bool = False, files_only: bool = False) -> None:
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
            "--no-heading",
            "--color", "never",
            f"--max-count={max_results}",
        ]
        if files_only:
            rg_cmd.append("-l")
        else:
            rg_cmd.append("--line-number")
        if fixed:
            rg_cmd.append("-F")
        if root.is_dir():
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
                errors="replace",
                **win_no_window_kwargs()
            )
            count = 0
            if proc.stdout:
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    if files_only:
                        p_match = Path(line)
                        if root.is_file():
                            rel = root.name
                        else:
                            try:
                                rel = p_match.relative_to(root)
                            except ValueError:
                                rel = p_match
                        print(str(rel))
                    else:
                        # format: /abs/path:line:content or rel/path:line:content
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            match_path, line_no, content = parts[0], parts[1], parts[2]
                            p_match = Path(match_path)
                            if root.is_file():
                                rel = root.name
                            else:
                                try:
                                    rel = p_match.relative_to(root)
                                except ValueError:
                                    rel = p_match
                            print(f"{rel}:{line_no} | {content.strip()[:120]}")
                        else:
                            print(line[:120])

                    count += 1
                    if count >= max_results:
                        if not files_only:
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

    if fixed:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    else:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            # Auto-fallback to literal string match on invalid regex syntax
            pattern = re.compile(re.escape(query), re.IGNORECASE)

    _grep_python(pattern, root, max_results, files_only=files_only)

def cmd_git_status(path: str = ".") -> None:
    """Compact git status showing only modified/untracked files with +/- diff count."""
    p = to_path(path)
    git_root = _find_git_root(p)
    if not git_root:
        print(f"ERROR: Not a git repository: {p}", file=sys.stderr)
        sys.exit(1)

    # 1. Get porcelain status
    res = subprocess.run(["git", "status", "--porcelain=v1", "-uall"], cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if res.returncode != 0:
        print(f"ERROR: git status failed: {res.stderr.strip()}", file=sys.stderr)
        sys.exit(res.returncode)

    status_lines = [l for l in res.stdout.splitlines() if l.strip()]
    if not status_lines:
        print("OK: Working tree clean (nothing to commit).")
        return

    # 2. Get numstat for diff counts (+N, -M)
    numstat_map = {}
    diff_res = subprocess.run(["git", "diff", "--numstat", "HEAD"], cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if diff_res.returncode != 0:
        diff_res = subprocess.run(["git", "diff", "--numstat"], cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if diff_res.returncode == 0:
        for line in diff_res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                adds, dels, fpath = parts[0].strip(), parts[1].strip(), parts[2].strip()
                numstat_map[fpath] = f"(+{adds}, -{dels})"

    print(f"=== GIT STATUS: {len(status_lines)} changed files ===")
    for line in status_lines:
        code = line[:2].strip()
        fpath = line[2:].strip()
        stat = numstat_map.get(fpath, "")
        stat_str = f" {stat}" if stat else ""
        print(f"  {code:2s}  {fpath}{stat_str}")


def cmd_diff(path: str = "", rev: str = None, cached: bool = False, max_lines: int = 100) -> None:
    """Token-efficient git diff ignoring whitespace noise and lockfiles."""
    p = to_path(path) if path else Path.cwd()
    git_root = _find_git_root(p)
    if not git_root:
        print(f"ERROR: Not a git repository: {p}", file=sys.stderr)
        sys.exit(1)

    cmd = ["git", "diff", "-w", "-U2"]
    if cached:
        cmd.append("--cached")
    if rev:
        cmd.append(rev)

    cmd.append("--")
    if p.is_file():
        try:
            rel = p.relative_to(git_root)
            cmd.append(str(rel).replace("\\", "/"))
        except ValueError:
            cmd.append(str(p))
    else:
        if p != git_root and p.is_dir():
            try:
                rel = p.relative_to(git_root)
                cmd.append(str(rel).replace("\\", "/"))
            except ValueError:
                pass
        for pattern in GIT_IGNORE_DIFF_PATTERNS:
            cmd.append(f":(exclude){pattern}")

    proc = subprocess.run(cmd, cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if proc.returncode != 0:
        print(f"ERROR: git diff failed: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(proc.returncode)

    raw_diff = proc.stdout
    if not raw_diff.strip():
        print("OK: No changes detected.")
        return

    lines = raw_diff.splitlines()
    total = len(lines)
    if total <= max_lines:
        print(raw_diff.rstrip())
    else:
        print("\n".join(lines[:max_lines]))
        print(f"\n... [diff truncated: showing {max_lines} of {total} lines. Use --max-lines to see more]")


def cmd_git_log(path: str = "", limit: int = 5) -> None:
    """Compact one-line git commit log."""
    p = to_path(path) if path else Path.cwd()
    git_root = _find_git_root(p)
    if not git_root:
        print(f"ERROR: Not a git repository: {p}", file=sys.stderr)
        sys.exit(1)

    cmd = ["git", "log", f"-n{max(1, limit)}", "--pretty=format:%h (%cr) %s <%an>"]
    if p.is_file() or (p != git_root and p.is_dir()):
        try:
            rel = p.relative_to(git_root)
            cmd.extend(["--", str(rel).replace("\\", "/")])
        except ValueError:
            pass

    proc = subprocess.run(cmd, cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if proc.returncode != 0:
        print(f"ERROR: git log failed: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(proc.returncode)

    output = proc.stdout.strip()
    if not output:
        print("OK: No commits found.")
        return

    target_name = p.name if p != git_root else "repository"
    print(f"=== GIT LOG: {target_name} (last {limit} commits) ===")
    print(output)


def cmd_git_view(path: str, rev: str = "HEAD", start: int = 1, end: int = 100) -> None:
    """Views line slice of a file from any Git revision without downloading full file."""
    p = to_path(path)
    git_root = _find_git_root(p)
    if not git_root:
        print(f"ERROR: Not a git repository: {p}", file=sys.stderr)
        sys.exit(1)

    try:
        rel_path = str(p.relative_to(git_root)).replace("\\", "/")
    except ValueError:
        rel_path = str(p).replace("\\", "/")

    target = f"{rev}:{rel_path}"
    proc = subprocess.run(["git", "show", target], cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if proc.returncode != 0:
        print(f"ERROR: Failed to retrieve {target}: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(proc.returncode)

    lines = proc.stdout.splitlines()
    total = len(lines)
    s = max(1, start)
    e = min(total, end)

    print(f"[{p.name} @ {rev}: lines {s}-{e} of {total}]")
    for i in range(s, e + 1):
        print(f"{i:4d} | {lines[i - 1]}")


def cmd_git_fn_history(path: str, name: str, limit: int = 3) -> None:
    """Traces modification history of a specific function or class across Git commits."""
    p = to_path(path)
    git_root = _find_git_root(p)
    if not git_root:
        print(f"ERROR: Not a git repository: {p}", file=sys.stderr)
        sys.exit(1)

    try:
        rel_path = str(p.relative_to(git_root)).replace("\\", "/")
    except ValueError:
        rel_path = str(p).replace("\\", "/")

    # 1. Try git log -L :<funcname>:<file> (AST function tracing in git)
    cmd = ["git", "log", f"-n{limit}", "-w", f"-L:{name}:{rel_path}"]
    proc = subprocess.run(cmd, cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if proc.returncode == 0 and proc.stdout.strip():
        lines = proc.stdout.splitlines()
        capped = lines[:80]
        print(f"=== GIT FUNCTION HISTORY: {name} in {p.name} (last {limit} modifications) ===")
        print("\n".join(capped))
        if len(lines) > 80:
            print(f"... [truncated {len(lines) - 80} lines]")
        return

    # 2. Fallback to git log -S <name> -p
    fb_cmd = ["git", "log", f"-n{limit}", "-w", "-S", name, "-p", "-U2", "--", rel_path]
    fb_proc = subprocess.run(fb_cmd, cwd=str(git_root), capture_output=True, text=True, encoding="utf-8", errors="replace", **win_no_window_kwargs())
    if fb_proc.returncode == 0 and fb_proc.stdout.strip():
        lines = fb_proc.stdout.splitlines()
        capped = lines[:80]
        print(f"=== GIT HISTORY: {name} in {p.name} (last {limit} commits) ===")
        print("\n".join(capped))
        if len(lines) > 80:
            print(f"... [truncated {len(lines) - 80} lines]")
        return

    print(f"OK: No git history found for '{name}' in {p.name}")


def _get_log_dir() -> Path:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _record_execution_stat(
    cmd_type: str,
    cmd_str: str,
    cwd: str,
    ret_code: int,
    duration_sec: float,
    venv_name: Optional[str] = None,
    raw_bytes: int = 0,
    out_bytes: int = 0
) -> None:
    """Appends an execution record to history.jsonl for learning, heuristics, and token analytics."""
    try:
        log_dir = _get_log_dir()
        history_file = log_dir / "history.jsonl"
        saved_chars = max(0, raw_bytes - out_bytes)
        record = {
            "ts": int(time.time()),
            "type": cmd_type,
            "cmd": cmd_str,
            "cwd": str(cwd),
            "exit": ret_code,
            "duration": round(duration_sec, 3),
            "venv": venv_name or "",
            "raw_bytes": raw_bytes,
            "out_bytes": out_bytes,
            "saved_tokens": saved_chars // 4
        }
        with open(history_file, "a", encoding="utf-8") as hf:
            hf.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def cmd_run(cmd: str, cwd: str = None, tail: int = 15, timeout: int = None, venv: str = None, head: int = None, silent: bool = False) -> None:
    log_dir = _get_log_dir()
    task_id = f"task_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    exec_cmd = sanitize_python_cmd(cmd, venv_dir)
    v_label = _venv_label(venv_dir)
    start_time = time.time()

    temp_script = None
    if sys.platform == "win32" and "\n" in exec_cmd:
        temp_script = log_dir / f"{task_id}.cmd"
        with open(temp_script, "w", encoding="utf-8") as sf:
            sf.write(f"@echo off\r\n{exec_cmd}\r\n")
        exec_target = f'"{temp_script}"'
    else:
        exec_target = exec_cmd

    with open(log_file, "w", encoding="utf-8") as out:
        venv_note = f" (venv: {v_label})" if v_label else ""
        out.write(f"=== Command: {exec_cmd}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
        out.flush()
        try:
            proc = subprocess.Popen(
                exec_target,
                shell=True,
                cwd=str(work_dir),
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **win_no_window_kwargs()
            )
            proc.wait(timeout=timeout)
            ret_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            ret_code = -1
            out.write("\n=== ERROR: Timeout expired\n")
        finally:
            if temp_script and temp_script.exists():
                try:
                    temp_script.unlink()
                except Exception:
                    pass
    duration = time.time() - start_time
    dur_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {int(duration % 60)}s"

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    # Filter out initial agentbox execution metadata header lines for slice display
    if len(all_lines) >= 4 and all_lines[0].startswith("=== Command:") and all_lines[3].strip() == "":
        lines = all_lines[4:]
    else:
        lines = all_lines

    raw_len = sum(len(l) for l in all_lines)
    tail_lines = lines[-tail:] if len(lines) > tail else lines
    tail_str = "".join(tail_lines).strip()

    v_tag = f" [{v_label}]" if v_label else ""
    if ret_code == 0:
        header = f"OK [exit 0, {dur_str}]{v_tag} Log: {log_file}"
        print(header)
        if silent or tail == 0:
            out_len = len(header)
        elif len(lines) <= 15:
            # Smart auto-inline for short output (e.g. git status, versions, short scripts)
            if lines:
                print("".join(lines).rstrip())
            out_len = len(header) + raw_len
        elif head is not None and head > 0:
            slice_lines = lines[:head]
            print(f"--- Output Head ({len(slice_lines)} of {len(lines)} lines) ---")
            print("".join(slice_lines).rstrip())
            out_len = len(header) + sum(len(l) for l in slice_lines) + 40
        elif tail > 0:
            slice_lines = lines[-tail:]
            print(f"--- Output Tail ({len(slice_lines)} of {len(lines)} lines) ---")
            print("".join(slice_lines).rstrip())
            out_len = len(header) + sum(len(l) for l in slice_lines) + 40
        else:
            out_len = len(header)
        _record_execution_stat("run", cmd, str(work_dir), ret_code, duration, v_label or None, raw_len, out_len)
    else:
        header = f"FAILED [exit {ret_code}, {dur_str}]{v_tag} Log: {log_file}"
        print(header)
        print(f"--- Failure Tail ({len(tail_lines)} lines) ---")
        print(tail_str)
        out_len = len(header) + len(tail_str) + 35
        _record_execution_stat("run", cmd, str(work_dir), ret_code, duration, v_label or None, raw_len, out_len)
        sys.exit(ret_code)
        sys.exit(ret_code)


def cmd_py(code: str, cwd: str = None, script_args: Optional[List[str]] = None, tail: int = 30, max_lines: int = 30, timeout: Optional[int] = None, venv: Optional[str] = None) -> None:
    """Silent Python evaluator: zero-escaping stdin execution, venv auto-detection, token protection."""
    log_dir = _get_log_dir()
    task_id = f"py_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    py_exe = str(_get_venv_python(venv_dir) if venv_dir else sys.executable)
    v_label = _venv_label(venv_dir)
    start_time = time.time()

    extra_args = script_args or []
    exec_target = [py_exe, "-", *extra_args]

    ret_code = 0
    stdout_str = ""
    stderr_str = ""
    try:
        proc = subprocess.Popen(
            exec_target,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(work_dir),
            env=env,
            **win_no_window_kwargs()
        )
        stdout_str, stderr_str = proc.communicate(input=code, timeout=timeout)
        ret_code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        ret_code = -1
        try:
            stdout_str, stderr_str = proc.communicate()
        except Exception:
            pass
        stderr_str += "\n=== ERROR: Python execution timeout expired\n"

    duration = time.time() - start_time
    dur_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {int(duration % 60)}s"

    with open(log_file, "w", encoding="utf-8") as f:
        venv_note = f" (venv: {v_label})" if v_label else ""
        args_str = f" {' '.join(extra_args)}" if extra_args else ""
        f.write(f"=== Python Eval: {py_exe} -{args_str}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
        f.write("=== CODE ===\n")
        f.write(code)
        f.write("\n\n=== STDOUT ===\n")
        f.write(stdout_str)
        f.write("\n\n=== STDERR ===\n")
        f.write(stderr_str)
        f.write(f"\n\n=== Exit Code: {ret_code} ===\n")

    raw_len = len(code) + len(stdout_str) + len(stderr_str)
    v_tag = f" [{v_label}]" if v_label else ""

    if ret_code == 0:
        out_lines = stdout_str.splitlines(keepends=True)
        if not out_lines:
            header = f"OK [exit 0, {dur_str}]{v_tag} Log: {log_file}"
            print(header)
            out_len = len(header)
        elif len(out_lines) <= max_lines:
            header = f"OK [exit 0, {dur_str}]{v_tag}"
            print(header)
            print("".join(out_lines).rstrip())
            out_len = len(header) + len(stdout_str)
        else:
            tail_lines = out_lines[-tail:] if len(out_lines) > tail else out_lines
            header = f"OK [exit 0, {dur_str}]{v_tag} (output truncated: showing last {len(tail_lines)} of {len(out_lines)} lines, full log: {log_file})"
            print(header)
            print("--- Output Tail ---")
            print("".join(tail_lines).rstrip())
            out_len = len(header) + sum(len(l) for l in tail_lines) + 30
        _record_execution_stat("py", code[:50], str(work_dir), ret_code, duration, v_label or None, raw_len, out_len)
    else:
        err_lines = (stderr_str if stderr_str else stdout_str).splitlines(keepends=True)
        tb_lines = []
        in_tb = False
        for line in err_lines:
            if "Traceback (most recent call last):" in line:
                in_tb = True
            if in_tb:
                tb_lines.append(line)
        if not tb_lines:
            tb_lines = err_lines[-max_lines:] if len(err_lines) > max_lines else err_lines

        header = f"FAILED [exit {ret_code}, {dur_str}]{v_tag} Log: {log_file}"
        print(header)
        print("--- High-Signal Failure Traceback ---")
        print("".join(tb_lines).strip())
        out_len = len(header) + sum(len(l) for l in tb_lines) + 40
        _record_execution_stat("py", code[:50], str(work_dir), ret_code, duration, v_label or None, raw_len, out_len)
        sys.exit(ret_code)


def _extract_svelte_check(lines: list, max_lines: int) -> Optional[str]:
    """Extracts svelte-check diagnostics, suppressing warnings if errors are present."""
    has_svelte = any("svelte-check" in l.lower() or "(svelte)" in l for l in lines)
    has_errors = any("Error:" in l for l in lines)
    if not (has_svelte or (has_errors and any(".svelte" in l for l in lines))):
        return None

    extracted = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip noisy loader headers
        if "Loading svelte-check" in line or "Getting Svelte diagnostics" in line or line.startswith("==="):
            i += 1
            continue

        if "Error:" in line:
            # Include preceding file path line if present
            if i > 0 and lines[i - 1].strip() and not lines[i - 1].startswith("==="):
                prev = lines[i - 1].rstrip()
                if not extracted or extracted[-1] != prev:
                    extracted.append(prev)
            extracted.append(line.rstrip())
            # Include indented code snippet line if present
            if i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
                extracted.append(lines[i + 1].rstrip())
        elif "svelte-check found" in line:
            extracted.append("\n" + line.strip())
        i += 1

    if extracted:
        if len(extracted) > max_lines:
            extracted = extracted[:max_lines] + ["\n... [truncated high-signal failure slice]"]
        return "\n".join(extracted)
    return None


def _extract_tsc(lines: list, max_lines: int) -> Optional[str]:
    """Extracts TypeScript compiler diagnostics."""
    has_tsc = any(re.search(r"\berror TS\d+:", l) for l in lines)
    if not has_tsc:
        return None

    extracted = []
    for line in lines:
        l_str = line.rstrip()
        if re.search(r"\berror TS\d+:", l_str) or (l_str.startswith("Found ") and "error" in l_str):
            extracted.append(l_str)
        elif extracted and line.startswith((" ", "\t")) and len(extracted) < max_lines:
            extracted.append(l_str)

    if extracted:
        if len(extracted) > max_lines:
            extracted = extracted[:max_lines] + ["\n... [truncated high-signal failure slice]"]
        return "\n".join(extracted)
    return None


def _extract_eslint(lines: list, max_lines: int) -> Optional[str]:
    """Extracts ESLint error lines, suppressing minor stylistic warnings."""
    has_eslint = any(re.search(r"✖ \d+ problems?|\s+error\s+", l) for l in lines)
    if not has_eslint:
        return None

    extracted = []
    current_file = ""
    for line in lines:
        l_strip = line.strip()
        # File header in eslint
        if l_strip.startswith(("/", "\\", ".")) or (":" in l_strip and "error" not in l_strip and "warning" not in l_strip):
            current_file = l_strip
        elif "error" in line.lower() and "0 error" not in line.lower():
            if current_file:
                extracted.append(current_file)
                current_file = ""
            extracted.append(line.rstrip())
        elif "✖ " in line:
            extracted.append("\n" + line.strip())

    if extracted:
        if len(extracted) > max_lines:
            extracted = extracted[:max_lines] + ["\n... [truncated high-signal failure slice]"]
        return "\n".join(extracted)
    return None


def _extract_vitest(lines: list, max_lines: int) -> Optional[str]:
    """Extracts Vitest / Jest test failure tracebacks, suppressing passed tests."""
    has_vitest = any("FAIL " in l or "Failed Tests" in l or "AssertionError" in l for l in lines)
    if not has_vitest:
        return None

    fail_idx = -1
    for i, line in enumerate(lines):
        if "FAIL " in line or "Failed Tests" in line or "AssertionError" in line:
            fail_idx = i
            break

    if fail_idx != -1:
        extracted = lines[fail_idx:]
        # Filter out green passed checkmarks
        filtered = [l for l in extracted if not l.strip().startswith("✓")]
        if len(filtered) > max_lines:
            filtered = filtered[:max_lines] + ["\n... [truncated high-signal failure slice]\n"]
        return "".join(filtered).strip()
    return None


def _extract_test_failures(lines: list, max_lines: int = 25) -> str:
    """Extracts high-signal failure tracebacks from pytest, cargo, svelte-check, tsc, eslint, vitest."""
    # 1. Try Svelte-check
    s_check = _extract_svelte_check(lines, max_lines)
    if s_check:
        return s_check

    # 2. Try TypeScript tsc
    tsc_res = _extract_tsc(lines, max_lines)
    if tsc_res:
        return tsc_res

    # 3. Try ESLint
    es_res = _extract_eslint(lines, max_lines)
    if es_res:
        return es_res

    # 4. Try Vitest / Jest
    vt_res = _extract_vitest(lines, max_lines)
    if vt_res:
        return vt_res

    # 5. Check for Python unittest failure block (===... followed by FAIL: or ERROR:)
    for i in range(len(lines) - 1):
        if lines[i].startswith("======================================================================"):
            if lines[i + 1].startswith(("FAIL:", "ERROR:")):
                extracted = lines[i:]
                if len(extracted) > max_lines:
                    extracted = extracted[:max_lines] + ["\n... [truncated high-signal failure slice]\n"]
                return "".join(extracted).strip()

    # 6. Check for pytest / cargo FAILURES section
    fail_idx = -1
    for i, line in enumerate(lines):
        if any(kw in line for kw in ["FAILURES", "=== ERRORS ===", "failures:", "error[E"]):
            fail_idx = i
            break

    if fail_idx != -1:
        extracted = lines[fail_idx:]
        if len(extracted) > max_lines:
            extracted = extracted[:max_lines] + ["\n... [truncated high-signal failure slice]\n"]
        return "".join(extracted).strip()

    # Fallback to tail
    tail_slice = lines[-max_lines:] if len(lines) > max_lines else lines
    return "".join(tail_slice).strip()


def cmd_test(cmd: str, cwd: str = None, timeout: int = None, max_lines: int = 30, venv: str = None) -> None:
    """Token-optimized test runner: silences passed output, extracts failure tracebacks."""
    log_dir = _get_log_dir()
    task_id = f"test_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    exec_cmd = sanitize_python_cmd(cmd, venv_dir)
    v_label = _venv_label(venv_dir)
    start_time = time.time()

    temp_script = None
    if sys.platform == "win32" and "\n" in exec_cmd:
        temp_script = log_dir / f"{task_id}.cmd"
        with open(temp_script, "w", encoding="utf-8") as sf:
            sf.write(f"@echo off\r\n{exec_cmd}\r\n")
        exec_target = f'"{temp_script}"'
    else:
        exec_target = exec_cmd

    with open(log_file, "w", encoding="utf-8") as out:
        venv_note = f" (venv: {v_label})" if v_label else ""
        out.write(f"=== Test Command: {exec_cmd}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
        out.flush()
        try:
            proc = subprocess.Popen(
                exec_target,
                shell=True,
                cwd=str(work_dir),
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **win_no_window_kwargs()
            )
            proc.wait(timeout=timeout)
            ret_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            ret_code = -1
            out.write("\n=== ERROR: Test timeout expired\n")
        finally:
            if temp_script and temp_script.exists():
                try:
                    temp_script.unlink()
                except Exception:
                    pass
    duration = time.time() - start_time
    dur_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {int(duration % 60)}s"

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    raw_len = sum(len(l) for l in lines)

    # Find summary line if available (pytest, vitest, svelte-check, tsc, eslint)
    summary_line = ""
    for line in reversed(lines[-25:]):
        l_strip = line.strip()
        if any(kw in l_strip.lower() for kw in [
            "passed", "failed", "test result", "ran ",
            "svelte-check found", "problems (", "found "
        ]):
            summary_line = l_strip
            break

    v_tag = f" [{v_label}]" if v_label else ""
    if ret_code == 0:
        verdict = f" ({summary_line})" if summary_line else ""
        msg = f"OK [tests passed in {dur_str}]{v_tag}{verdict} Log: {log_file}"
        print(msg)
        _record_execution_stat("test", cmd, str(work_dir), ret_code, duration, v_label or None, raw_len, len(msg))
    else:
        failure_body = _extract_test_failures(lines, max_lines=max_lines)
        header = f"FAILED [exit {ret_code}, {dur_str}]{v_tag} Log: {log_file}"
        print(header)
        if summary_line:
            print(f"Summary: {summary_line}")
        print(f"--- High-Signal Failure Traceback ---")
        print(failure_body)
        out_len = len(header) + len(summary_line) + len(failure_body) + 40
        _record_execution_stat("test", cmd, str(work_dir), ret_code, duration, v_label or None, raw_len, out_len)
        sys.exit(ret_code)


def cmd_pip(pip_args: str, cwd: str = None, venv: str = None) -> None:
    """Runs pip inside an isolated virtualenv (auto-creating .agentbox/venv if no venv exists)."""
    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv, auto_create=True)
    v_py = _get_venv_python(venv_dir) if venv_dir else Path(sys.executable)
    py_quoted = f'"{v_py}"' if " " in str(v_py) else str(v_py)
    full_cmd = f"{py_quoted} -m pip {pip_args.strip()}"
    cmd_run(full_cmd, cwd=str(work_dir), tail=10, venv=str(venv_dir) if venv_dir else venv)


def cmd_stats(clear: bool = False) -> None:
    """Displays token savings and command execution analytics from history.jsonl."""
    log_dir = _get_log_dir()
    history_file = log_dir / "history.jsonl"

    if clear:
        if history_file.is_file():
            history_file.unlink()
        print("OK: Cleared AgentBox execution & token statistics.")
        return

    if not history_file.is_file():
        print("=== AGENTBOX STATS: No recorded operations yet ===")
        return

    total_ops = 0
    total_saved_tokens = 0
    total_raw_bytes = 0
    total_out_bytes = 0
    total_duration = 0.0
    by_type: Dict[str, Dict[str, Any]] = {}

    try:
        lines = history_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        print(f"ERROR: Could not read stats: {e}", file=sys.stderr)
        sys.exit(1)

    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        total_ops += 1
        ctype = rec.get("type", "unknown")
        dur = float(rec.get("duration", 0.0) or 0.0)
        raw_b = int(rec.get("raw_bytes", 0) or 0)
        out_b = int(rec.get("out_bytes", 0) or 0)
        saved_t = int(rec.get("saved_tokens", max(0, (raw_b - out_b) // 4)) or 0)
        exit_c = int(rec.get("exit", 0) or 0)

        total_duration += dur
        total_raw_bytes += raw_b
        total_out_bytes += out_b
        total_saved_tokens += saved_t

        bucket = by_type.setdefault(ctype, {"count": 0, "ok": 0, "fail": 0, "saved_tokens": 0, "duration": 0.0})
        bucket["count"] += 1
        if exit_c == 0:
            bucket["ok"] += 1
        else:
            bucket["fail"] += 1
        bucket["saved_tokens"] += saved_t
        bucket["duration"] += dur

    reduction_pct = (
        round((1.0 - (total_out_bytes / total_raw_bytes)) * 100, 1)
        if total_raw_bytes > 0 and total_raw_bytes >= total_out_bytes
        else 0.0
    )

    print(f"=== AGENTBOX TOKEN & EXECUTION STATS ({total_ops} operations) ===")
    print(f"  Estimated Tokens Saved : ~{total_saved_tokens:,} tokens ({reduction_pct}% noise reduction)")
    print(f"  Raw Output Processed   : {total_raw_bytes:,} bytes -> {total_out_bytes:,} bytes sent to LLM")
    print(f"  Total Active Runtime   : {total_duration:.2f}s")
    if by_type:
        print("\n  Breakdown by Command:")
        for ctype, info in sorted(by_type.items(), key=lambda kv: (-kv[1]["saved_tokens"], -kv[1]["count"])):
            print(
                f"    {ctype:<10s} | runs: {info['count']:<4d} (ok: {info['ok']}, fail: {info['fail']}) "
                f"| saved: ~{info['saved_tokens']:,} tokens | time: {info['duration']:.1f}s"
            )


def cmd_spawn(cmd: str, cwd: str = None, venv: str = None) -> None:
    log_dir = _get_log_dir()
    task_id = f"bg_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"
    meta_file = log_dir / f"{task_id}.json"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    exec_cmd = sanitize_python_cmd(cmd, venv_dir)
    v_label = _venv_label(venv_dir)
    start_time = time.time()

    out = open(log_file, "w", encoding="utf-8")
    venv_note = f" (venv: {v_label})" if v_label else ""
    out.write(f"=== Spawned: {exec_cmd}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
    out.flush()

    if os.name != "nt":
        kwargs = {"start_new_session": True}
    else:
        extra_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs = win_no_window_kwargs(extra_flags)

    proc = subprocess.Popen(
        exec_cmd,
        shell=True,
        cwd=str(work_dir),
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
        **kwargs
    )

    meta = {
        "task_id": task_id,
        "pid": proc.pid,
        "cmd": exec_cmd,
        "cwd": str(work_dir),
        "venv": str(venv_dir) if venv_dir else "",
        "start_time": start_time,
        "log_file": str(log_file),
    }
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    venv_tag = f" venv={v_label}" if v_label else ""
    print(f"SPAWNED: task_id={task_id} pid={proc.pid}{venv_tag} log={log_file}")


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
            proc = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, **win_no_window_kwargs())
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

    venv_str = f" | Venv: {meta.get('venv')}" if meta.get("venv") else ""
    print(f"TASK: {task_id} | Status: {status_str} | PID: {pid}{venv_str} | Runtime: {runtime:.1f}s")
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
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], **win_no_window_kwargs())
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


def _find_graphify_python(work_dir: Path = None, explicit_venv: str = None) -> str:
    """Finds python executable that has graphify installed or in graphify-out/.graphify_python."""
    if work_dir is None:
        work_dir = Path.cwd()

    # Check venv python first if available
    venv_dir = find_virtualenv(work_dir, explicit_venv)
    if venv_dir:
        bin_dir = _get_venv_bin_dir(venv_dir)
        if bin_dir:
            for py_name in ["python3", "python", "python.exe"]:
                cand = bin_dir / py_name
                if cand.is_file():
                    try:
                        chk = subprocess.run([str(cand), "-c", "import graphify; print('OK')"], capture_output=True, text=True, **win_no_window_kwargs())
                        if chk.returncode == 0:
                            return str(cand)
                    except Exception:
                        pass

    pointer = work_dir / "graphify-out" / ".graphify_python"
    if pointer.is_file():
        try:
            py = pointer.read_text(encoding="utf-8").strip()
            if py and Path(py).exists():
                return py
        except Exception:
            pass

    # Check current python
    try:
        proc = subprocess.run([sys.executable, "-c", "import graphify; print(sys.executable)"], capture_output=True, text=True, **win_no_window_kwargs())
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass

    # Check uv / pipx
    for cmd in ["uv", "pipx", "python3", "python"]:
        path = shutil.which(cmd)
        if path:
            try:
                chk = subprocess.run([path, "-c", "import graphify; print('OK')"] if "python" in cmd else [path, "run", "python", "-c", "import graphify; print('OK')"], capture_output=True, text=True, **win_no_window_kwargs())
                if chk.returncode == 0:
                    return path
            except Exception:
                pass

    return ""


def cmd_graphify_install(upgrade: bool = False) -> None:
    """Silently installs or updates graphifyy on the target machine."""
    existing_py = _find_graphify_python()
    if existing_py and not upgrade:
        print(f"OK: graphify already installed at {existing_py}")
        return

    print("Installing graphifyy (silent mode)...")
    cmd = []
    if shutil.which("uv"):
        cmd = ["uv", "tool", "install", "--upgrade", "graphifyy"] if upgrade else ["uv", "tool", "install", "graphifyy"]
    elif shutil.which("pipx"):
        cmd = ["pipx", "upgrade", "graphifyy"] if upgrade else ["pipx", "install", "graphifyy"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade" if upgrade else "--quiet", "graphifyy"]

    proc = subprocess.run(cmd, capture_output=True, text=True, **win_no_window_kwargs())
    if proc.returncode != 0:
        print(f"FAILED: Failed to install graphifyy (exit {proc.returncode})\n{proc.stderr.strip()[:400]}", file=sys.stderr)
        sys.exit(proc.returncode)

    py = _find_graphify_python()
    print(f"OK: graphifyy installed successfully. Interpreter: {py or sys.executable}")


def cmd_graphify_build(path: str = ".", deep: bool = False, venv: str = None) -> None:
    """Builds a knowledge graph with graphifyy silently, reporting summary."""
    p = to_path(path)
    py = _find_graphify_python(p, venv) or sys.executable

    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "graphify_build.log"

    build_cmd = [py, "-m", "graphify", str(p)]
    if deep:
        build_cmd.append("--mode=deep")

    start_time = time.time()
    with open(log_file, "w", encoding="utf-8") as out:
        out.write(f"=== Graphify Build: {' '.join(build_cmd)}\n=== Started: {time.ctime(start_time)}\n\n")
        out.flush()
        proc = subprocess.run(build_cmd, stdout=out, stderr=subprocess.STDOUT, cwd=str(p), **win_no_window_kwargs())

    dur = time.time() - start_time
    if proc.returncode != 0:
        # Fallback to code-only AST extraction (requires no LLM API key)
        fallback_cmd = [py, "-m", "graphify", "update", str(p)]
        proc = subprocess.run(fallback_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(p), **win_no_window_kwargs())
        if proc.returncode != 0:
            print(f"FAILED: Graphify build failed [exit {proc.returncode}, {dur:.1f}s]. Log: {log_file}", file=sys.stderr)
            sys.exit(proc.returncode)

    # Check graph.json / GRAPH_REPORT.md
    out_dir = p / "graphify-out"
    graph_file = out_dir / "graph.json"
    if graph_file.is_file():
        try:
            data = json.loads(graph_file.read_text(encoding="utf-8"))
            nodes_cnt = len(data.get("nodes", []))
            edges_cnt = len(data.get("edges", []))
            print(f"OK: Knowledge graph built in {dur:.1f}s ({nodes_cnt} nodes, {edges_cnt} edges). Location: {out_dir}")
            return
        except Exception:
            pass

    print(f"OK: Graphify completed in {dur:.1f}s. Outputs in {out_dir}")


def cmd_graphify_query(question: str, path: str = ".", max_tokens: int = 1500, venv: str = None) -> None:
    """Queries an existing graphify knowledge graph without blowing LLM context (auto-builds if needed)."""
    p = to_path(path)
    out_dir = p / "graphify-out"
    graph_file = out_dir / "graph.json"
    report_file = out_dir / "GRAPH_REPORT.md"

    if not graph_file.is_file() and not report_file.is_file():
        cmd_graphify_build(path=str(p), venv=venv)
        if not graph_file.is_file() and not report_file.is_file():
            print(f"ERROR: No knowledge graph found in {p}. Build could not complete.", file=sys.stderr)
            sys.exit(1)
    py = _find_graphify_python(p, venv) or sys.executable
    # Try native graphify query CLI
    proc = subprocess.run([py, "-m", "graphify", "query", question], capture_output=True, text=True, cwd=str(p), **win_no_window_kwargs())
    if proc.returncode == 0 and proc.stdout.strip():
        # Trim output to token budget
        output_lines = proc.stdout.strip().splitlines()[:50]
        print(f"=== GRAPH QUERY: {question} ===")
        print("\n".join(output_lines))
        return

    # Lightweight in-worker fallback on graph.json
    if graph_file.is_file():
        try:
            data = json.loads(graph_file.read_text(encoding="utf-8"))
            tokens = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
            matched_nodes = []
            for node in data.get("nodes", []):
                label = str(node.get("label", ""))
                node_id = str(node.get("id", ""))
                score = sum(1 for t in tokens if t in label.lower() or t in node_id.lower())
                if score > 0:
                    matched_nodes.append((score, node))

            matched_nodes.sort(key=lambda x: x[0], reverse=True)
            top_nodes = matched_nodes[:10]

            print(f"=== GRAPH QUERY: {question} ({len(top_nodes)} relevant nodes found) ===")
            for score, n in top_nodes:
                nid = n.get("id")
                lbl = n.get("label", nid)
                ntype = n.get("node_type", n.get("type", "entity"))
                loc = n.get("source_location", n.get("file", ""))
                print(f"• [{ntype}] {lbl} ({loc})")

            # Match connected edges
            matched_ids = {n.get("id") for _, n in top_nodes}
            relevant_edges = []
            for e in data.get("edges", []):
                src = e.get("source")
                tgt = e.get("target")
                rel = e.get("relation", e.get("rel", "->"))
                if src in matched_ids and tgt in matched_ids:
                    relevant_edges.append(f"  {src} --[{rel}]--> {tgt}")

            if relevant_edges:
                print("\nConnections:")
                for edge in relevant_edges[:10]:
                    print(edge)
            return
        except Exception as e:
            print(f"ERROR: Failed parsing graph.json: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"ERROR: Query could not be processed for: {question}", file=sys.stderr)
    sys.exit(1)


def cmd_graphify_export_html(path: str = ".", venv: str = None) -> None:
    """Exports graph.html content as base64 for client-side visualization (auto-builds if missing)."""
    p = to_path(path)
    if p.is_file() and p.name.endswith(".html"):
        html_file = p
    else:
        html_file = p / "graphify-out" / "graph.html"

    if not html_file.is_file():
        cmd_graphify_build(path=str(p), venv=venv)
        if not html_file.is_file():
            print(f"ERROR: No graph.html found at {html_file}. Please run 'agentbox graphify-build' first.", file=sys.stderr)
            sys.exit(1)

    try:
        data = html_file.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        print(b64)
    except Exception as e:
        print(f"ERROR: Failed reading {html_file}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_graphify_open(path: str = ".", venv: str = None, no_open: bool = False, out: str = None) -> None:
    """Locates graph.html, optionally copies to destination, and opens in browser."""
    p = to_path(path)
    if p.is_file() and p.name.endswith(".html"):
        html_file = p
    else:
        html_file = p / "graphify-out" / "graph.html"

    if not html_file.is_file():
        cmd_graphify_build(path=str(p), venv=venv)
        if not html_file.is_file():
            print(f"ERROR: No graph.html found at {html_file}. Please run 'agentbox graphify-build' first.", file=sys.stderr)
            sys.exit(1)

    dest_file = html_file
    if out:
        dest_p = to_path(out)
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        dest_p.write_bytes(html_file.read_bytes())
        dest_file = dest_p

    print(f"Knowledge graph: {dest_file}")
    if not no_open:
        try:
            import webbrowser
            webbrowser.open(dest_file.resolve().as_uri())
            print(f"OK: Opened {dest_file} in browser.")
        except Exception as e:
            print(f"Notice: Could not launch browser ({e}). View file at: {dest_file}")


def cmd_batch(steps: Union[str, List[Dict[str, Any]]] = None, stop_on_error: bool = True, cwd: Optional[str] = None) -> None:
    """Executes multiple AgentBox actions in a single worker invocation to save agent turns."""
    if cwd:
        try:
            os.chdir(os.path.expanduser(cwd))
        except Exception:
            pass
    if steps is None:
        raw_in = read_stdin_utf8().strip()
        if not raw_in:
            print("ERROR: Empty batch input", file=sys.stderr)
            sys.exit(1)
        try:
            steps_list = json.loads(raw_in)
        except Exception as e:
            print(f"ERROR: Invalid JSON for batch: {e}", file=sys.stderr)
            sys.exit(1)
    elif isinstance(steps, str):
        try:
            steps_list = json.loads(steps)
        except Exception as e:
            print(f"ERROR: Invalid JSON string for batch: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        steps_list = list(steps)

    if not isinstance(steps_list, list) or not steps_list:
        print("ERROR: Batch steps must be a non-empty JSON array of action objects", file=sys.stderr)
        sys.exit(1)

    total = len(steps_list)
    had_error = 0

    for idx, step in enumerate(steps_list, start=1):
        if not isinstance(step, dict):
            print(f"ERROR: Batch step {idx} is not an object", file=sys.stderr)
            if stop_on_error:
                sys.exit(1)
            had_error = 1
            continue

        raw_action = str(step.get("action") or step.get("cmd") or "").strip()
        action = raw_action.replace("-", "_")
        step_args = step.get("args")
        if not isinstance(step_args, dict):
            step_args = {k: v for k, v in step.items() if k not in ("action", "cmd", "continue_on_error")}

        if idx > 1:
            print()
        print(f"=== [Batch {idx}/{total}: {raw_action or action}] ===")
        try:
            dispatch_action(action, step_args)
        except SystemExit as se:
            code = se.code if isinstance(se.code, int) else (1 if se.code else 0)
            if code != 0:
                had_error = code
                if stop_on_error and not step.get("continue_on_error", False):
                    sys.exit(code)
        except Exception as e:
            print(f"ERROR in batch step {idx} ({action}): {e}", file=sys.stderr)
            had_error = 1
            if stop_on_error and not step.get("continue_on_error", False):
                sys.exit(1)

    if had_error != 0:
        sys.exit(had_error)



# ---------------------------------------------------------------------------
# Bidirectional Project Sync Engine (In-Memory Tar Transport)
# ---------------------------------------------------------------------------

ALWAYS_IGNORE = [
    ".git",
    ".git/*",
    "*venv*",
    ".*venv*",
    "venv",
    "venv/*",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".pytest_cache/*",
    ".agentbox",
    ".agentbox/*",
    "node_modules",
    "node_modules/*",
    ".idea",
    ".idea/*",
    ".vscode",
    ".vscode/*",
    ".DS_Store",
    "Thumbs.db",
    "*.egg-info",
    "*.egg-info/*",
    "dist",
    "dist/*",
    "build",
    "build/*"
]


def parse_gitignore(root_dir: Path) -> List[str]:
    """Parses local .gitignore file if present and returns cleaned pattern list."""
    gitignore_file = root_dir / ".gitignore"
    if not gitignore_file.is_file():
        return []
    patterns: List[str] = []
    try:
        content = gitignore_file.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("/"):
                line = line[:-1]
            patterns.append(line)
    except Exception:
        pass
    return patterns


def should_ignore(rel_path: str, is_dir: bool = False, extra_patterns: Optional[List[str]] = None) -> bool:
    """Checks whether a relative path matches ALWAYS_IGNORE or gitignore patterns."""
    norm = rel_path.replace("\\", "/").strip("/")
    parts = norm.split("/")

    for ign in ALWAYS_IGNORE:
        ign_clean = ign.replace("\\", "/").rstrip("/*")
        for p in parts:
            if fnmatch.fnmatch(p.lower(), ign_clean.lower()):
                return True
        if fnmatch.fnmatch(norm.lower(), ign.lower()):
            return True

    if extra_patterns:
        for pat in extra_patterns:
            pat_clean = pat.replace("\\", "/").strip("/")
            if "/" not in pat_clean:
                for p in parts:
                    if fnmatch.fnmatch(p, pat_clean):
                        return True
            else:
                if fnmatch.fnmatch(norm, pat_clean) or fnmatch.fnmatch(norm, f"{pat_clean}/*"):
                    return True

    return False


def hash_file_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file in 64KB blocks."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def build_manifest(root_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    Builds a dictionary manifest of all synchronized files in root_dir.
    Keys are relative POSIX paths; values include size, mtime, and sha256.
    """
    manifest: Dict[str, Dict[str, Any]] = {}
    gitignore_patterns = parse_gitignore(root_dir)

    for root, dirs, files in os.walk(str(root_dir)):
        rel_root = os.path.relpath(root, str(root_dir))
        if rel_root == ".":
            rel_root = ""

        dirs[:] = [
            d for d in dirs
            if not should_ignore(
                f"{rel_root}/{d}" if rel_root else d,
                is_dir=True,
                extra_patterns=gitignore_patterns
            )
        ]

        for fname in files:
            rel_path = f"{rel_root}/{fname}".replace("\\", "/").lstrip("/")
            if should_ignore(rel_path, is_dir=False, extra_patterns=gitignore_patterns):
                continue

            full_p = Path(root) / fname
            try:
                st = full_p.stat()
                manifest[rel_path] = {
                    "size": st.st_size,
                    "mtime": round(st.st_mtime, 2),
                    "sha256": hash_file_sha256(full_p)
                }
            except Exception:
                continue

    return manifest


def is_text_content(data: bytes) -> bool:
    """Heuristic to detect if file content is text vs binary (checks for null bytes)."""
    if not data:
        return True
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def pack_sync_tar(root_dir: Path, rel_paths: List[str], to_lf: bool = False) -> bytes:
    """Packs specified relative file paths from root_dir into an in-memory gzipped tarball."""
    bio = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=bio) as tar:
        for rel in sorted(rel_paths):
            full_path = root_dir / rel
            if not full_path.is_file():
                continue
            try:
                data = full_path.read_bytes()
                if to_lf and is_text_content(data):
                    data = data.replace(b"\r\n", b"\n")

                ti = tarfile.TarInfo(name=rel.replace("\\", "/"))
                ti.size = len(data)
                try:
                    ti.mtime = full_path.stat().st_mtime
                except Exception:
                    ti.mtime = 0
                ti.mode = 0o644
                tar.addfile(ti, io.BytesIO(data))
            except Exception:
                continue
    return bio.getvalue()


def unpack_sync_tar(root_dir: Path, tar_bytes: bytes) -> List[str]:
    """Safely unpacks in-memory gzipped tarball into root_dir, preventing directory traversal."""
    bio = io.BytesIO(tar_bytes)
    unpacked: List[str] = []
    with tarfile.open(mode="r:gz", fileobj=bio) as tar:
        for member in tar.getmembers():
            norm_name = os.path.normpath(member.name).replace("\\", "/")
            if norm_name.startswith("..") or os.path.isabs(norm_name):
                continue

            target_path = root_dir / norm_name
            target_path.parent.mkdir(parents=True, exist_ok=True)

            f = tar.extractfile(member)
            if f:
                content = f.read()
                target_path.write_bytes(content)
                unpacked.append(norm_name)
    return unpacked


def compute_sync_diff(
    local_manifest: Dict[str, Dict[str, Any]],
    remote_manifest: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Computes bidirectional synchronization delta and detects potential conflicts."""
    to_push: List[str] = []
    to_pull: List[str] = []
    conflicts_push: List[str] = []
    conflicts_pull: List[str] = []
    in_sync: List[str] = []

    all_keys = sorted(set(local_manifest.keys()) | set(remote_manifest.keys()))

    for key in all_keys:
        loc = local_manifest.get(key)
        rem = remote_manifest.get(key)

        if loc and not rem:
            to_push.append(key)
        elif rem and not loc:
            to_pull.append(key)
        elif loc and rem:
            if loc["sha256"] == rem["sha256"]:
                in_sync.append(key)
            else:
                if rem["mtime"] > loc["mtime"]:
                    conflicts_push.append(key)
                else:
                    conflicts_pull.append(key)
                to_push.append(key)
                to_pull.append(key)

    return {
        "to_push": to_push,
        "to_pull": to_pull,
        "conflicts_push": conflicts_push,
        "conflicts_pull": conflicts_pull,
        "in_sync": in_sync,
        "remote_only": [k for k in all_keys if k not in local_manifest],
        "local_only": [k for k in all_keys if k not in remote_manifest],
    }


def cmd_file_read_b64(path: str) -> None:
    """Reads file content and prints it as base64 encoded binary data."""
    p = to_path(path)
    if not p.is_file():
        if p.is_dir():
            print(f"ERROR: Source path is a directory (directories not supported in cp v1): {path}", file=sys.stderr)
        else:
            print(f"ERROR: Source file not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        data = p.read_bytes()
        print(base64.b64encode(data).decode("ascii"))
    except Exception as e:
        print(f"ERROR: Failed reading file {path}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_file_write_b64(path: str, data_b64: str, src_filename: Optional[str] = None) -> None:
    """Writes base64 encoded binary data to target path."""
    p = to_path(path)
    if p.is_dir() or str(path).endswith("/") or str(path).endswith("\\"):
        fname = src_filename or "file"
        p = p / fname
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = base64.b64decode(data_b64)
        p.write_bytes(data)
        print("OK")
    except Exception as e:
        print(f"ERROR: Failed writing file {path}: {e}", file=sys.stderr)
        sys.exit(1)


def dispatch_action(action: str, args: Dict[str, Any]) -> None:
    """Dispatches an action name to the corresponding worker command."""
    action = (action or "").replace("-", "_")
    if action == "view":
        cmd_view(
            args.get("path"),
            int(args.get("start", 1)),
            int(args.get("end", 100)),
            tail=int(args["tail"]) if args.get("tail") is not None else None
        )
    elif action == "outline":
        cmd_outline(args.get("paths") or args.get("path"))
    elif action == "get_fn":
        cmd_get_fn(args.get("path"), args.get("names") or args.get("name"))
    elif action in ("write", "write_files"):
        if args.get("files"):
            cmd_write_files(args.get("files"), args.get("append", False))
        else:
            content = args.get("content")
            if content is None and args.get("base64"):
                content = decode_base64_text(args["base64"])
            if content is None and (args.get("file") or args.get("file_path")):
                content = to_path(args.get("file") or args.get("file_path")).read_text(encoding="utf-8")
            cmd_write(args.get("path"), content, args.get("append", False))
    elif action == "patch":
        old_val = args.get("old")
        new_val = args.get("new")
        if old_val is None and args.get("base64_old"):
            old_val = decode_base64_text(args["base64_old"])
        if new_val is None and args.get("base64_new"):
            new_val = decode_base64_text(args["base64_new"])
        if old_val is None and (args.get("old_file") or args.get("old_file_path")):
            old_val = to_path(args.get("old_file") or args.get("old_file_path")).read_text(encoding="utf-8")
        if new_val is None and (args.get("new_file") or args.get("new_file_path")):
            new_val = to_path(args.get("new_file") or args.get("new_file_path")).read_text(encoding="utf-8")
        cmd_patch(
            args.get("path"),
            old_val,
            new_val,
            args.get("all", False),
            check_syntax=args.get("check_syntax", True)
        )
    elif action == "patch_lines":
        content = args.get("content")
        if content is None and args.get("base64"):
            content = decode_base64_text(args["base64"])
        if content is None and (args.get("file") or args.get("file_path")):
            content = to_path(args.get("file") or args.get("file_path")).read_text(encoding="utf-8")
        cmd_patch_lines(
            args.get("path"),
            int(args.get("start", 1)),
            int(args.get("end", 1)),
            content,
            check_syntax=args.get("check_syntax", True)
        )
    elif action == "rollback":
        cmd_rollback(args.get("path"))
    elif action == "tree":
        cmd_tree(args.get("path", "."), args.get("depth", 2))
    elif action == "grep":
        cmd_grep(args.get("query"), args.get("path", "."), args.get("max", 20), fixed=args.get("fixed", False), files_only=args.get("files_only", False))
    elif action == "run":
        cmd_run(args.get("cmd"), args.get("cwd"), args.get("tail", 15), args.get("timeout"), venv=args.get("venv"), head=args.get("head"), silent=args.get("silent", False))
    elif action == "py":
        cmd_py(args.get("code", ""), args.get("cwd"), args.get("args"), tail=args.get("tail", 30), max_lines=args.get("max_lines", 30), timeout=args.get("timeout"), venv=args.get("venv"))
    elif action == "test":
        cmd_test(args.get("cmd"), args.get("cwd"), args.get("timeout"), args.get("max_lines", 30), venv=args.get("venv"))
    elif action == "pip":
        cmd_pip(args.get("pip_args") or args.get("cmd", ""), args.get("cwd"), venv=args.get("venv"))
    elif action == "stats":
        cmd_stats(clear=args.get("clear", False))
    elif action == "batch":
        steps_val = args.get("steps")
        if steps_val is None and args.get("base64"):
            steps_val = decode_base64_text(args["base64"])
        cmd_batch(steps_val, stop_on_error=args.get("stop_on_error", True), cwd=args.get("cwd"))
    elif action == "spawn":
        cmd_spawn(args.get("cmd"), args.get("cwd"), venv=args.get("venv"))
    elif action == "status":
        cmd_status(args.get("task_id"))
    elif action == "logs":
        cmd_logs(args.get("task_id"), args.get("lines", 50), args.get("follow", False))
    elif action == "kill":
        cmd_kill(args.get("task_id"))
    elif action == "graphify_install":
        cmd_graphify_install(args.get("upgrade", False))
    elif action == "graphify_build":
        cmd_graphify_build(args.get("path", "."), args.get("deep", False), venv=args.get("venv"))
    elif action == "graphify_query":
        cmd_graphify_query(args.get("question"), args.get("path", "."), args.get("max_tokens", 1500), venv=args.get("venv"))
    elif action == "graphify_export_html":
        cmd_graphify_export_html(args.get("path", "."), venv=args.get("venv"))
    elif action == "graphify_open":
        cmd_graphify_open(args.get("path", "."), venv=args.get("venv"), no_open=args.get("no_open", False), out=args.get("out"))
    elif action == "git_status":
        cmd_git_status(args.get("path", "."))
    elif action == "diff":
        cmd_diff(args.get("path", ""), args.get("rev"), args.get("cached", False), args.get("max_lines", 100))
    elif action == "git_log":
        cmd_git_log(args.get("path", ""), args.get("limit", 5))
    elif action == "git_view":
        cmd_git_view(args.get("path"), args.get("rev", "HEAD"), args.get("start", 1), args.get("end", 100))
    elif action == "git_fn_history":
        cmd_git_fn_history(args.get("path"), args.get("name"), args.get("limit", 3))
    elif action == "find_fn":
        cmd_find_fn(args.get("name"), args.get("path", "."), args.get("exact", False), args.get("max", 30))
    elif action == "refs":
        cmd_refs(args.get("name"), args.get("path", "."), args.get("max", 40))
    elif action == "sync_manifest":
        work_dir = to_path(args.get("cwd") or ".")
        manifest = build_manifest(work_dir)
        print(json.dumps(manifest, ensure_ascii=False))
    elif action == "sync_pack":
        work_dir = to_path(args.get("cwd") or ".")
        files = args.get("files", [])
        to_lf = args.get("to_lf", False)
        tar_bytes = pack_sync_tar(work_dir, files, to_lf=to_lf)
        print(base64.b64encode(tar_bytes).decode("ascii"))
    elif action == "sync_unpack":
        work_dir = to_path(args.get("cwd") or ".")
        tar_b64 = args.get("tar_b64", "")
        unpacked = unpack_sync_tar(work_dir, base64.b64decode(tar_b64))
        print(json.dumps({"unpacked": unpacked}, ensure_ascii=False))
    elif action == "sync_delete":
        work_dir = to_path(args.get("cwd") or ".")
        files = args.get("files", [])
        deleted = []
        for f in files:
            p = work_dir / f
            if p.is_file():
                try:
                    p.unlink()
                    deleted.append(f)
                except Exception:
                    pass
        print(json.dumps({"deleted": deleted}, ensure_ascii=False))
    elif action in ("file_read_b64", "cp_read"):
        cmd_file_read_b64(args.get("path", ""))
    elif action in ("file_write_b64", "cp_write"):
        cmd_file_write_b64(args.get("path", ""), args.get("data_b64", ""), args.get("src_filename"))
    else:
        print(f"ERROR: Unknown action '{action}'", file=sys.stderr)
        sys.exit(1)


def handle_ipc_mode() -> None:
    """Reads a single JSON request from stdin and executes it without bash shell escaping."""
    raw_in = read_stdin_utf8()
    try:
        payload = json.loads(raw_in)
    except Exception as e:
        print(f"ERROR: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    action = payload.get("action")
    args = payload.get("args", {})
    dispatch_action(action, args)


class DaemonEventWriter:
    """Redirects stdout/stderr writes into line-delimited JSON daemon protocol events."""
    def __init__(self, req_id: str, event_type: str, raw_stream):
        self.req_id = req_id
        self.event_type = event_type
        self.raw_stream = raw_stream

    def write(self, s: str) -> int:
        if not s:
            return 0
        try:
            msg = json.dumps({"id": self.req_id, "event": self.event_type, "data": s}, ensure_ascii=False)
            self.raw_stream.write(msg + "\n")
            self.raw_stream.flush()
        except Exception:
            pass
        return len(s)

    def flush(self) -> None:
        try:
            self.raw_stream.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


def handle_daemon_mode(idle_timeout: int = 1800) -> None:
    """Persistent stdio daemon mode for sub-millisecond execution over a persistent SSH connection.
    Reads line-delimited JSON requests from stdin, streams stdout/stderr events,
    and terminates on idle timeout or stdin EOF."""
    raw_stdin = sys.stdin
    raw_stdout = getattr(sys, "__stdout__", None) or sys.stdout
    raw_stderr = getattr(sys, "__stderr__", None) or sys.stderr

    # Send ready handshake
    try:
        raw_stdout.write(json.dumps({"event": "ready", "pid": os.getpid()}) + "\n")
        raw_stdout.flush()
    except Exception:
        sys.exit(1)

    while True:
        # Check idle timeout on platforms supporting select on stdin (Linux/macOS)
        if sys.platform != "win32":
            import select
            rlist, _, _ = select.select([raw_stdin], [], [], idle_timeout)
            if not rlist:
                break

        line = raw_stdin.readline()
        if not line:
            # EOF -> Connection closed by client
            break

        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception as e:
            raw_stdout.write(json.dumps({"event": "error", "message": f"Invalid JSON: {e}"}) + "\n")
            raw_stdout.flush()
            continue

        req_id = req.get("id", "req")
        action = req.get("action")
        args = req.get("args", {})

        if action == "ping":
            raw_stdout.write(json.dumps({"id": req_id, "event": "pong"}) + "\n")
            raw_stdout.flush()
            continue
        elif action == "shutdown":
            raw_stdout.write(json.dumps({"id": req_id, "event": "exit", "code": 0}) + "\n")
            raw_stdout.flush()
            break

        out_stream = DaemonEventWriter(req_id, "stdout", raw_stdout)
        err_stream = DaemonEventWriter(req_id, "stderr", raw_stdout)

        orig_out = sys.stdout
        orig_err = sys.stderr
        sys.stdout = out_stream
        sys.stderr = err_stream

        exit_code = 0
        try:
            dispatch_action(action, args)
        except SystemExit as se:
            exit_code = se.code if isinstance(se.code, int) else (1 if se.code else 0)
        except Exception as e:
            exit_code = 1
            err_stream.write(f"ERROR: Execution failed: {e}\n")
        finally:
            sys.stdout = orig_out
            sys.stderr = orig_err
            raw_stdout.write(json.dumps({"id": req_id, "event": "exit", "code": exit_code}) + "\n")
            raw_stdout.flush()


def main():
    if "--daemon" in sys.argv:
        handle_daemon_mode()
        return
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
    p_out.add_argument("path", nargs="+")

    p_fn = sub.add_parser("get-fn")
    p_fn.add_argument("path")
    p_fn.add_argument("name", nargs="+")

    p_write = sub.add_parser("write")
    p_write.add_argument("path", nargs="+")
    p_write.add_argument("--content", default=None)
    p_write.add_argument("--file", default=None)
    p_write.add_argument("--append", action="store_true")

    p_patch = sub.add_parser("patch")
    p_patch.add_argument("path")
    p_patch.add_argument("--old", required=True)
    p_patch.add_argument("--new", required=True)
    p_patch.add_argument("--all", action="store_true")
    p_patch.add_argument("--no-check", dest="check_syntax", action="store_false")

    p_pl = sub.add_parser("patch-lines")
    p_pl.add_argument("path")
    p_pl.add_argument("--start", type=int, required=True)
    p_pl.add_argument("--end", type=int, required=True)
    p_pl.add_argument("--content", default=None)
    p_pl.add_argument("--file", default=None)
    p_pl.add_argument("--no-check", dest="check_syntax", action="store_false")
    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("path")

    p_tree = sub.add_parser("tree")
    p_tree.add_argument("path", nargs="?", default=".")
    p_tree.add_argument("--depth", type=int, default=2)

    p_grep = sub.add_parser("grep")
    p_grep.add_argument("query")
    p_grep.add_argument("path", nargs="?", default=".")
    p_grep.add_argument("--max", type=int, default=20)
    p_grep.add_argument("-F", "--fixed", action="store_true")
    p_grep.add_argument("-l", "--files-only", action="store_true")

    p_run = sub.add_parser("run")
    p_run.add_argument("command")
    p_run.add_argument("--cwd", default=None)
    p_run.add_argument("--venv", default=None)
    p_run.add_argument("--tail", type=int, default=15)
    p_run.add_argument("--timeout", type=int, default=None)

    p_test = sub.add_parser("test")
    p_test.add_argument("command")
    p_test.add_argument("--cwd", default=None)
    p_test.add_argument("--venv", default=None)
    p_test.add_argument("--max-lines", type=int, default=30)
    p_test.add_argument("--timeout", type=int, default=None)

    p_pip = sub.add_parser("pip")
    p_pip.add_argument("pip_args")
    p_pip.add_argument("--cwd", default=None)
    p_pip.add_argument("--venv", default=None)

    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--clear", action="store_true")

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("steps", nargs="?", default=None)
    p_batch.add_argument("--continue-on-error", dest="stop_on_error", action="store_false")

    p_spawn = sub.add_parser("spawn")
    p_spawn.add_argument("command")
    p_spawn.add_argument("--cwd", default=None)
    p_spawn.add_argument("--venv", default=None)

    p_stat = sub.add_parser("status")
    p_stat.add_argument("task_id")

    p_logs = sub.add_parser("logs")
    p_logs.add_argument("task_id")
    p_logs.add_argument("-n", "--lines", type=int, default=50)
    p_logs.add_argument("-f", "--follow", action="store_true")

    p_kill = sub.add_parser("kill")
    p_kill.add_argument("task_id")

    p_g_inst = sub.add_parser("graphify-install")
    p_g_inst.add_argument("--upgrade", action="store_true")

    p_g_build = sub.add_parser("graphify-build")
    p_g_build.add_argument("path", nargs="?", default=".")
    p_g_build.add_argument("--venv", default=None)
    p_g_build.add_argument("--deep", action="store_true")

    p_g_query = sub.add_parser("graphify-query")
    p_g_query.add_argument("question")
    p_g_query.add_argument("path", nargs="?", default=".")
    p_g_query.add_argument("--venv", default=None)
    p_g_query.add_argument("--max-tokens", type=int, default=1500)

    p_g_open = sub.add_parser("graphify-open")
    p_g_open.add_argument("path", nargs="?", default=".")
    p_g_open.add_argument("--venv", default=None)
    p_g_open.add_argument("--no-open", action="store_true")
    p_g_open.add_argument("--out", default=None)

    # git-status
    p_gs = sub.add_parser("git-status")
    p_gs.add_argument("path", nargs="?", default=".")

    # diff
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("path", nargs="?", default="")
    p_diff.add_argument("--rev", default=None)
    p_diff.add_argument("--cached", action="store_true")
    p_diff.add_argument("--max-lines", type=int, default=100)

    # git-log
    p_gl = sub.add_parser("git-log")
    p_gl.add_argument("path", nargs="?", default="")
    p_gl.add_argument("-n", "--limit", type=int, default=5)

    # git-view
    p_gv = sub.add_parser("git-view")
    p_gv.add_argument("path")
    p_gv.add_argument("rev", nargs="?", default="HEAD")
    p_gv.add_argument("--start", type=int, default=1)
    p_gv.add_argument("--end", type=int, default=100)

    # git-fn-history
    p_gfh = sub.add_parser("git-fn-history")
    p_gfh.add_argument("path")
    p_gfh.add_argument("name")
    p_gfh.add_argument("-n", "--limit", type=int, default=3)

    # find-fn
    p_ff = sub.add_parser("find-fn")
    p_ff.add_argument("name")
    p_ff.add_argument("path", nargs="?", default=".")
    p_ff.add_argument("--exact", action="store_true")
    p_ff.add_argument("--max", dest="max_results", type=int, default=30)

    # refs
    p_refs = sub.add_parser("refs")
    p_refs.add_argument("name")
    p_refs.add_argument("path", nargs="?", default=".")
    p_refs.add_argument("--max", dest="max_results", type=int, default=40)

    args = parser.parse_args()

    if args.cmd == "view":
        cmd_view(args.path, args.start, args.end)
    elif args.cmd == "outline":
        cmd_outline(args.path if len(args.path) > 1 else args.path[0])
    elif args.cmd == "get-fn":
        cmd_get_fn(args.path, args.name)
    elif args.cmd == "find-fn":
        cmd_find_fn(args.name, args.path, args.exact, args.max_results)
    elif args.cmd == "refs":
        cmd_refs(args.name, args.path, args.max_results)
    elif args.cmd == "write":
        paths = args.path if isinstance(args.path, list) else [args.path]
        content = args.content
        if content is None and getattr(args, "file", None):
            content = to_path(args.file).read_text(encoding="utf-8")
        if content is not None:
            if len(paths) == 1:
                cmd_write(paths[0], content, args.append)
            else:
                cmd_write_files([{"path": p, "content": content} for p in paths], args.append)
        else:
            files_list = []
            for item in paths:
                src, dest = parse_file_mapping(item)
                src_p = to_path(src)
                if not src_p.is_file():
                    if len(paths) == 1 and ":" not in item:
                        cmd_write(paths[0], None, args.append)
                        return
                    print(f"ERROR: Local source file not found: {src}", file=sys.stderr)
                    sys.exit(1)
                files_list.append({"path": dest, "content": src_p.read_text(encoding="utf-8")})
            if len(files_list) == 1 and ":" not in paths[0]:
                cmd_write(files_list[0]["path"], files_list[0]["content"], args.append)
            else:
                cmd_write_files(files_list, args.append)
    elif args.cmd == "patch":
        cmd_patch(args.path, args.old, args.new, args.all, check_syntax=args.check_syntax)
    elif args.cmd == "patch-lines":
        content = args.content
        if content is None and getattr(args, "file", None):
            content = to_path(args.file).read_text(encoding="utf-8")
        cmd_patch_lines(args.path, args.start, args.end, content, check_syntax=args.check_syntax)
    elif args.cmd == "rollback":
        cmd_rollback(args.path)
    elif args.cmd == "tree":
        cmd_tree(args.path, args.depth)
    elif args.cmd == "grep":
        cmd_grep(args.query, args.path, args.max, fixed=getattr(args, "fixed", False), files_only=getattr(args, "files_only", False))
    elif args.cmd == "run":
        cmd_run(args.command, args.cwd, args.tail, args.timeout, venv=args.venv)
    elif args.cmd == "test":
        cmd_test(args.command, args.cwd, args.timeout, args.max_lines, venv=args.venv)
    elif args.cmd == "pip":
        cmd_pip(args.pip_args, args.cwd, venv=args.venv)
    elif args.cmd == "stats":
        cmd_stats(clear=args.clear)
    elif args.cmd == "batch":
        cmd_batch(args.steps, stop_on_error=args.stop_on_error)
    elif args.cmd == "spawn":
        cmd_spawn(args.command, args.cwd, venv=args.venv)
    elif args.cmd == "status":
        cmd_status(args.task_id)
    elif args.cmd == "logs":
        cmd_logs(args.task_id, args.lines, args.follow)
    elif args.cmd == "kill":
        cmd_kill(args.task_id)
    elif args.cmd == "graphify-install":
        cmd_graphify_install(args.upgrade)
    elif args.cmd == "graphify-build":
        cmd_graphify_build(args.path, args.deep, venv=args.venv)
    elif args.cmd == "graphify-query":
        cmd_graphify_query(args.question, args.path, args.max_tokens, venv=args.venv)
    elif args.cmd == "graphify-open":
        cmd_graphify_open(args.path, venv=args.venv, no_open=args.no_open, out=args.out)
    elif args.cmd == "git-status":
        cmd_git_status(args.path)
    elif args.cmd == "diff":
        cmd_diff(args.path, args.rev, args.cached, args.max_lines)
    elif args.cmd == "git-log":
        cmd_git_log(args.path, args.limit)
    elif args.cmd == "git-view":
        cmd_git_view(args.path, args.rev, args.start, args.end)
    elif args.cmd == "git-fn-history":
        cmd_git_fn_history(args.path, args.name, args.limit)


if __name__ == "__main__":
    main()
