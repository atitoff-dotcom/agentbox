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
from typing import Dict, Any, Optional, Tuple

DEFAULT_IGNORED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
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


def find_virtualenv(work_dir: Path, explicit_venv: Optional[str] = None) -> Optional[Path]:
    """Finds active, configured, or auto-detected virtualenv directory."""
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
    # 1. Direct subdirectories in work_dir
    candidates = [".venv", "venv", ".env", "env"]
    for name in candidates:
        cand = work_dir / name
        if _is_venv_dir(cand):
            return cand

    # 2. Check parents of work_dir (up to filesystem root or git/config boundary)
    curr = work_dir.parent
    while curr != curr.parent:
        for name in [".venv", "venv"]:
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


def prepare_env_for_cmd(work_dir: Path, explicit_venv: Optional[str] = None) -> Tuple[Dict[str, str], Optional[Path]]:
    """Prepares process environment with virtualenv PATH prefixed."""
    venv_dir = find_virtualenv(work_dir, explicit_venv)
    env = os.environ.copy()
    if venv_dir:
        bin_dir = _get_venv_bin_dir(venv_dir)
        if bin_dir:
            orig_path = env.get("PATH", "")
            env["PATH"] = f"{bin_dir}{os.pathsep}{orig_path}"
            env["VIRTUAL_ENV"] = str(venv_dir)
            env.pop("PYTHONHOME", None)
            return env, venv_dir
    return env, None


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


def cmd_write(path: str, content: str = None, append: bool = False) -> None:
    """Safely writes or appends content to a file, reading from stdin if content is None."""
    p = to_path(path)
    if content is None:
        content = sys.stdin.read()

    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    try:
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        action_word = "Appended to" if append else "Wrote"
        print(f"OK: {action_word} {p.name} ({len(content)} chars, {len(content.splitlines())} lines).")
    except Exception as e:
        print(f"ERROR: Failed writing to {path}: {e}", file=sys.stderr)
        sys.exit(1)


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
                errors="replace",
                **win_no_window_kwargs()
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


def cmd_git_status(path: str = ".") -> None:
    """Compact git status showing only modified/untracked files with +/- diff count."""
    p = to_path(path)
    git_root = _find_git_root(p)
    if not git_root:
        print(f"ERROR: Not a git repository: {p}", file=sys.stderr)
        sys.exit(1)

    # 1. Get porcelain status
    res = subprocess.run(["git", "status", "--porcelain=v1", "-uall"], cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
    if res.returncode != 0:
        print(f"ERROR: git status failed: {res.stderr.strip()}", file=sys.stderr)
        sys.exit(res.returncode)

    status_lines = [l for l in res.stdout.splitlines() if l.strip()]
    if not status_lines:
        print("OK: Working tree clean (nothing to commit).")
        return

    # 2. Get numstat for diff counts (+N, -M)
    numstat_map = {}
    diff_res = subprocess.run(["git", "diff", "--numstat", "HEAD"], cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
    if diff_res.returncode != 0:
        diff_res = subprocess.run(["git", "diff", "--numstat"], cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
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

    proc = subprocess.run(cmd, cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
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

    proc = subprocess.run(cmd, cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
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
    proc = subprocess.run(["git", "show", target], cwd=str(git_root), capture_output=True, text=True, errors="replace", **win_no_window_kwargs())
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
    proc = subprocess.run(cmd, cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
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
    fb_proc = subprocess.run(fb_cmd, cwd=str(git_root), capture_output=True, text=True, **win_no_window_kwargs())
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


def _record_execution_stat(cmd_type: str, cmd_str: str, cwd: str, ret_code: int, duration_sec: float, venv_name: Optional[str] = None) -> None:
    """Appends an execution record to history.jsonl for learning and heuristics."""
    try:
        log_dir = _get_log_dir()
        history_file = log_dir / "history.jsonl"
        record = {
            "ts": int(time.time()),
            "type": cmd_type,
            "cmd": cmd_str,
            "cwd": str(cwd),
            "exit": ret_code,
            "duration": round(duration_sec, 3),
            "venv": venv_name or ""
        }
        with open(history_file, "a", encoding="utf-8") as hf:
            hf.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def cmd_run(cmd: str, cwd: str = None, tail: int = 15, timeout: int = None, venv: str = None) -> None:
    log_dir = _get_log_dir()
    task_id = f"task_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    start_time = time.time()

    with open(log_file, "w", encoding="utf-8") as out:
        venv_note = f" (venv: {venv_dir.name})" if venv_dir else ""
        out.write(f"=== Command: {cmd}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
        out.flush()
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(work_dir),
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                text=True,
                **win_no_window_kwargs()
            )
            proc.wait(timeout=timeout)
            ret_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            ret_code = -1
            out.write("\n=== ERROR: Timeout expired\n")

    duration = time.time() - start_time
    dur_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {int(duration % 60)}s"
    _record_execution_stat("run", cmd, str(work_dir), ret_code, duration, venv_dir.name if venv_dir else None)

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    tail_lines = lines[-tail:] if len(lines) > tail else lines
    tail_str = "".join(tail_lines).strip()

    v_tag = f" [{venv_dir.name}]" if venv_dir else ""
    if ret_code == 0:
        print(f"OK [exit 0, {dur_str}]{v_tag} Log: {log_file}")
        if tail > 0 and len(lines) > 3:
            print(f"--- Tail ({len(tail_lines)} lines) ---")
            print(tail_str)
    else:
        print(f"FAILED [exit {ret_code}, {dur_str}]{v_tag} Log: {log_file}")
        print(f"--- Failure Tail ({len(tail_lines)} lines) ---")
        print(tail_str)
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

    # 5. Check for pytest / unittest / cargo FAILURES section
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
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"test_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    start_time = time.time()

    with open(log_file, "w", encoding="utf-8") as out:
        venv_note = f" (venv: {venv_dir.name})" if venv_dir else ""
        out.write(f"=== Test Command: {cmd}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
        out.flush()
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(work_dir),
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                text=True,
                **win_no_window_kwargs()
            )
            proc.wait(timeout=timeout)
            ret_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            ret_code = -1
            out.write("\n=== ERROR: Test timeout expired\n")

    duration = time.time() - start_time
    dur_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {int(duration % 60)}s"
    _record_execution_stat("test", cmd, str(work_dir), ret_code, duration, venv_dir.name if venv_dir else None)

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

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

    v_tag = f" [{venv_dir.name}]" if venv_dir else ""
    if ret_code == 0:
        verdict = f" ({summary_line})" if summary_line else ""
        print(f"OK [tests passed in {dur_str}]{v_tag}{verdict} Log: {log_file}")
    else:
        failure_body = _extract_test_failures(lines, max_lines=max_lines)
        print(f"FAILED [exit {ret_code}, {dur_str}]{v_tag} Log: {log_file}")
        if summary_line:
            print(f"Summary: {summary_line}")
        print(f"--- High-Signal Failure Traceback ---")
        print(failure_body)
        sys.exit(ret_code)


def cmd_spawn(cmd: str, cwd: str = None, venv: str = None) -> None:
    log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"bg_{int(time.time() * 1000) % 1000000}"
    log_file = log_dir / f"{task_id}.log"
    meta_file = log_dir / f"{task_id}.json"

    work_dir = to_path(cwd)
    env, venv_dir = prepare_env_for_cmd(work_dir, venv)
    start_time = time.time()

    out = open(log_file, "w", encoding="utf-8")
    venv_note = f" (venv: {venv_dir.name})" if venv_dir else ""
    out.write(f"=== Spawned: {cmd}{venv_note}\n=== CWD: {work_dir}\n=== Started: {time.ctime(start_time)}\n\n")
    out.flush()

    if os.name != "nt":
        kwargs = {"start_new_session": True}
    else:
        extra_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs = win_no_window_kwargs(extra_flags)

    proc = subprocess.Popen(
        cmd,
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
        "cmd": cmd,
        "cwd": str(work_dir),
        "venv": str(venv_dir) if venv_dir else "",
        "start_time": start_time,
        "log_file": str(log_file),
    }
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    venv_tag = f" venv={venv_dir.name}" if venv_dir else ""
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
    """Queries an existing graphify knowledge graph without blowing LLM context."""
    p = to_path(path)
    out_dir = p / "graphify-out"
    graph_file = out_dir / "graph.json"
    report_file = out_dir / "GRAPH_REPORT.md"

    if not graph_file.is_file() and not report_file.is_file():
        print(f"ERROR: No knowledge graph found in {p}. Run 'agentbox graphify build' first.", file=sys.stderr)
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


def dispatch_action(action: str, args: Dict[str, Any]) -> None:
    """Dispatches an action name to the corresponding worker command."""
    if action == "view":
        cmd_view(args.get("path"), args.get("start", 1), args.get("end", 100))
    elif action == "outline":
        cmd_outline(args.get("path"))
    elif action == "get_fn":
        cmd_get_fn(args.get("path"), args.get("name"))
    elif action == "write":
        cmd_write(args.get("path"), args.get("content"), args.get("append", False))
    elif action == "patch":
        cmd_patch(args.get("path"), args.get("old"), args.get("new"), args.get("all", False))
    elif action == "rollback":
        cmd_rollback(args.get("path"))
    elif action == "tree":
        cmd_tree(args.get("path", "."), args.get("depth", 2))
    elif action == "grep":
        cmd_grep(args.get("query"), args.get("path", "."), args.get("max", 20))
    elif action == "run":
        cmd_run(args.get("cmd"), args.get("cwd"), args.get("tail", 15), args.get("timeout"), venv=args.get("venv"))
    elif action == "test":
        cmd_test(args.get("cmd"), args.get("cwd"), args.get("timeout"), args.get("max_lines", 30), venv=args.get("venv"))
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
    else:
        print(f"ERROR: Unknown action '{action}'", file=sys.stderr)
        sys.exit(1)


def handle_ipc_mode() -> None:
    """Reads a single JSON request from stdin and executes it without bash shell escaping."""
    try:
        payload = json.loads(sys.stdin.read())
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
            msg = json.dumps({"id": self.req_id, "event": self.event_type, "data": s})
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
    p_out.add_argument("path")

    p_fn = sub.add_parser("get-fn")
    p_fn.add_argument("path")
    p_fn.add_argument("name")

    p_write = sub.add_parser("write")
    p_write.add_argument("path")
    p_write.add_argument("--content", default=None)
    p_write.add_argument("--append", action="store_true")

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
    p_run.add_argument("--venv", default=None)
    p_run.add_argument("--tail", type=int, default=15)
    p_run.add_argument("--timeout", type=int, default=None)

    p_test = sub.add_parser("test")
    p_test.add_argument("command")
    p_test.add_argument("--cwd", default=None)
    p_test.add_argument("--venv", default=None)
    p_test.add_argument("--max-lines", type=int, default=30)
    p_test.add_argument("--timeout", type=int, default=None)

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

    args = parser.parse_args()

    if args.cmd == "view":
        cmd_view(args.path, args.start, args.end)
    elif args.cmd == "outline":
        cmd_outline(args.path)
    elif args.cmd == "get-fn":
        cmd_get_fn(args.path, args.name)
    elif args.cmd == "find-fn":
        cmd_find_fn(args.name, args.path, args.exact, args.max_results)
    elif args.cmd == "write":
        cmd_write(args.path, args.content, args.append)
    elif args.cmd == "patch":
        cmd_patch(args.path, args.old, args.new, args.all)
    elif args.cmd == "rollback":
        cmd_rollback(args.path)
    elif args.cmd == "tree":
        cmd_tree(args.path, args.depth)
    elif args.cmd == "grep":
        cmd_grep(args.query, args.path, args.max)
    elif args.cmd == "run":
        cmd_run(args.command, args.cwd, args.tail, args.timeout, venv=args.venv)
    elif args.cmd == "test":
        cmd_test(args.command, args.cwd, args.timeout, args.max_lines, venv=args.venv)
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
