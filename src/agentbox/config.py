# -*- coding: utf-8 -*-
"""
agentbox.config — Configuration manager for AgentBox.
Supports global (~/.agentbox/config.json) and project-level (.agentbox.json) settings,
named multi-targets / SSH environments, and project task automation recipes.
"""

import os
import re
import time
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
GLOBAL_CONFIG_DIR = Path.home() / ".agentbox"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"
LOCAL_CONFIG_FILE = Path(".agentbox.json")


def find_local_config(start: Optional[Path] = None) -> Optional[Path]:
    """Recursively searches for .agentbox.json upwards from start directory to git root or filesystem root."""
    cur = (start or Path.cwd()).resolve()
    for parent in [cur] + list(cur.parents):
        candidate = parent / ".agentbox.json"
        if candidate.is_file():
            return candidate
        if (parent / ".git").exists():
            break
    return None


def get_local_config_file(for_writing: bool = False, start: Optional[Path] = None) -> Path:
    """Returns path to .agentbox.json: either found in parent tree or default in current dir."""
    found = find_local_config(start=start)
    if found:
        return found
    if start:
        base = start if start.is_dir() else start.parent
        return base / ".agentbox.json"
    return LOCAL_CONFIG_FILE


DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "",
    "cwd": "",
    "venv": "",
    "timeout": 300,
    "tail": 15,
    "tasks": {},
    "default_target": "",
    "targets": {},
}


def get_config(start: Optional[Path] = None) -> Dict[str, Any]:
    """Loads merged configuration: default -> global -> local."""
    cfg = dict(DEFAULT_CONFIG)

    if GLOBAL_CONFIG_FILE.is_file():
        try:
            cfg.update(json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

    local_path = get_local_config_file(start=start)
    if local_path.is_file():
        try:
            cfg.update(json.loads(local_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"WARNING: Failed to parse {local_path}: {e}", file=sys.stderr)
        except Exception:
            pass
    else:
        # Zero-config Local First: without .agentbox.json, everything runs 100% locally
        cfg["host"] = ""
        cfg["cwd"] = ""

    return cfg


def save_global_config(updates: Dict[str, Any]) -> None:
    """Updates and saves global configuration."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if GLOBAL_CONFIG_FILE.is_file():
        try:
            cfg = json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg.update(updates)
    GLOBAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def save_local_config(updates: Dict[str, Any]) -> None:
    """Updates and saves local project-level configuration."""
    cfg = {}
    local_path = get_local_config_file(for_writing=True)
    if local_path.is_file():
        try:
            cfg = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg.update(updates)
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_tasks() -> Dict[str, str]:
    """Returns merged tasks: global tasks overridden by local tasks."""
    tasks: Dict[str, str] = {}
    if GLOBAL_CONFIG_FILE.is_file():
        try:
            g_data = json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(g_data.get("tasks"), dict):
                tasks.update(g_data["tasks"])
        except Exception:
            pass

    local_path = get_local_config_file()
    if local_path.is_file():
        try:
            l_data = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(l_data.get("tasks"), dict):
                tasks.update(l_data["tasks"])
        except Exception:
            pass

    return tasks


def add_task(name: str, command: str) -> None:
    """Saves or updates a task in the local project .agentbox.json."""
    cfg = {}
    local_path = get_local_config_file(for_writing=True)
    if local_path.is_file():
        try:
            cfg = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    tasks = cfg.get("tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
    tasks[name] = command
    cfg["tasks"] = tasks
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules()


def remove_task(name: str) -> bool:
    """Removes a task from local project .agentbox.json. Returns True if removed, False if not found."""
    local_path = get_local_config_file()
    if not local_path.is_file():
        return False

    try:
        cfg = json.loads(local_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    tasks = cfg.get("tasks", {})
    if not isinstance(tasks, dict) or name not in tasks:
        return False

    del tasks[name]
    cfg["tasks"] = tasks
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules()
    return True


def get_targets() -> Dict[str, Dict[str, str]]:
    """Returns merged named targets: global targets overridden by local targets."""
    targets: Dict[str, Dict[str, str]] = {}
    if GLOBAL_CONFIG_FILE.is_file():
        try:
            g_data = json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(g_data.get("targets"), dict):
                for k, v in g_data["targets"].items():
                    if isinstance(v, dict):
                        targets[k] = {
                            "host": str(v.get("host") or ""),
                            "cwd": str(v.get("cwd") or ""),
                            "venv": str(v.get("venv") or ""),
                            "readonly": bool(v.get("readonly") or v.get("read_only") or False),
                        }
        except Exception:
            pass

    local_path = get_local_config_file()
    if local_path.is_file():
        try:
            l_data = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(l_data.get("targets"), dict):
                for k, v in l_data["targets"].items():
                    if isinstance(v, dict):
                        targets[k] = {
                            "host": str(v.get("host") or ""),
                            "cwd": str(v.get("cwd") or ""),
                            "venv": str(v.get("venv") or ""),
                            "readonly": bool(v.get("readonly") or v.get("read_only") or False),
                        }
        except Exception:
            pass

    return targets


def get_default_target_name() -> str:
    """Returns configured default target name, or empty string if none set."""
    local_path = get_local_config_file()
    if local_path.is_file():
        try:
            l_data = json.loads(local_path.read_text(encoding="utf-8"))
            if l_data.get("default_target"):
                return str(l_data["default_target"])
        except Exception:
            pass

    if GLOBAL_CONFIG_FILE.is_file():
        try:
            g_data = json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8"))
            if g_data.get("default_target"):
                return str(g_data["default_target"])
        except Exception:
            pass

    return ""


def resolve_target(target: Optional[str] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Resolves a target specification to a dict with keys: 'name', 'host', 'cwd', 'venv'.
    Supports:
    - None/empty: resolves to default_target if set, else top-level host/cwd/venv from config.
    - 'local': forces host='' (runs on local machine).
    - configured target name (e.g. 'prod', 'dev'): returns saved target settings.
    - ad-hoc target (e.g. 'user@server' or '192.168.1.1'): returns host=target with empty cwd/venv.
    """
    if cfg is None:
        cfg = get_config()

    targets = get_targets()

    # 1. If target is explicitly specified
    if target:
        t_clean = target.strip()
        if t_clean in targets:
            t = targets[t_clean]
            return {
                "name": t_clean,
                "host": t.get("host", ""),
                "cwd": t.get("cwd", ""),
                "venv": t.get("venv", ""),
                "readonly": bool(t.get("readonly", False)),
            }
        if t_clean.lower() == "local":
            return {"name": "local", "host": "", "cwd": "", "venv": "", "readonly": False}
        # Ad-hoc SSH host
        return {"name": t_clean, "host": t_clean, "cwd": "", "venv": "", "readonly": False}

    # 2. Check default target
    def_name = get_default_target_name()
    if def_name:
        if def_name in targets:
            t = targets[def_name]
            return {
                "name": def_name,
                "host": t.get("host", ""),
                "cwd": t.get("cwd", ""),
                "venv": t.get("venv", ""),
                "readonly": bool(t.get("readonly", False)),
            }
        if def_name.lower() == "local":
            return {"name": "local", "host": "", "cwd": "", "venv": "", "readonly": False}
    # 3. Fallback to top-level host/cwd/venv in config
    top_host = cfg.get("host", "") or ""
    top_cwd = cfg.get("cwd", "") or ""
    top_venv = cfg.get("venv", "") or ""
    target_name = top_host if top_host else "local"
    return {
        "name": target_name,
        "host": top_host,
        "cwd": top_cwd,
        "venv": top_venv,
        "readonly": bool(cfg.get("readonly") or cfg.get("read_only") or False),
    }


def add_target(name: str, host: str = "", cwd: str = "", venv: str = "", is_default: bool = False, readonly: bool = False) -> None:
    """Adds or updates a target in local project .agentbox.json."""
    cfg = {}
    local_path = get_local_config_file(for_writing=True)
    if local_path.is_file():
        try:
            cfg = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    targets = cfg.get("targets", {})
    if not isinstance(targets, dict):
        targets = {}
    targets[name] = {
        "host": host,
        "cwd": cwd,
        "venv": venv,
        "readonly": bool(readonly),
    }
    cfg["targets"] = targets
    if is_default or not cfg.get("default_target"):
        cfg["default_target"] = name
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules()


def set_target_readonly(name: str, readonly: bool = True) -> bool:
    """Sets or clears the readonly flag for a target in local project .agentbox.json. Returns True if updated."""
    local_path = get_local_config_file()
    if not local_path.is_file():
        return False
    try:
        cfg = json.loads(local_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    targets = cfg.get("targets", {})
    if not isinstance(targets, dict) or name not in targets:
        return False
    if not isinstance(targets[name], dict):
        targets[name] = {}
    targets[name]["readonly"] = bool(readonly)
    cfg["targets"] = targets
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules()
    return True


def remove_target(name: str) -> bool:
    """Removes a target from local project .agentbox.json. Returns True if removed, False otherwise."""
    local_path = get_local_config_file()
    if not local_path.is_file():
        return False

    try:
        cfg = json.loads(local_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    targets = cfg.get("targets", {})
    if not isinstance(targets, dict) or name not in targets:
        return False

    del targets[name]
    cfg["targets"] = targets
    if cfg.get("default_target") == name:
        cfg["default_target"] = next(iter(targets.keys())) if targets else ""
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules()
    return True


def set_default_target(name: str) -> bool:
    """Sets the active default target in local project .agentbox.json."""
    targets = get_targets()
    if name != "local" and name not in targets:
        return False

    cfg = {}
    local_path = get_local_config_file(for_writing=True)
    if local_path.is_file():
        try:
            cfg = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    cfg["default_target"] = name
    local_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules()
    return True


def get_audit_log_path() -> Path:
    """Returns path to audit.jsonl in local project if .agentbox exists or project root, else global."""
    local_cfg = find_local_config()
    if local_cfg:
        box_dir = local_cfg.parent / ".agentbox"
        box_dir.mkdir(parents=True, exist_ok=True)
        return box_dir / "audit.jsonl"

    box_dir = Path(".agentbox")
    if box_dir.is_dir():
        return box_dir / "audit.jsonl"

    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return GLOBAL_CONFIG_DIR / "audit.jsonl"


def record_audit(
    cmd: str,
    target: str = "local",
    path: str = "",
    code: int = 0,
    duration_ms: int = 0,
    error: str = "",
    arg: str = "",
    query: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Silently appends an action audit record to .agentbox/audit.jsonl (fail-safe)."""
    try:
        log_file = get_audit_log_path()
        record: Dict[str, Any] = {
            "ts": int(time.time()),
            "cmd": cmd,
            "target": target or "local",
            "path": path,
            "code": code,
            "ms": duration_ms,
        }
        if arg:
            record["arg"] = arg[:150].strip()
        if query:
            record["query"] = query[:100].strip()
        if meta and isinstance(meta, dict):
            for k, v in meta.items():
                if v is not None and v != "":
                    record[k] = v
        if error:
            record["err"] = error[:120].strip()

        # Rotation: if log file > 5MB, keep last 2000 lines
        if log_file.is_file() and log_file.stat().st_size > 5 * 1024 * 1024:
            try:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) > 2000:
                    log_file.write_text("\n".join(lines[-2000:]) + "\n", encoding="utf-8")
            except Exception:
                pass

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_audit_summary(tail: Optional[int] = None, clear: bool = False) -> str:
    """Parses audit.jsonl and returns an aggregated telemetry dashboard."""
    log_file = get_audit_log_path()
    if clear:
        if log_file.is_file():
            log_file.unlink()
        return "OK: Cleared AgentBox action audit log."

    if not log_file.is_file():
        return "=== AGENTBOX AUDIT: No recorded actions yet ==="

    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"ERROR: Could not read audit log: {e}"

    if not lines:
        return "=== AGENTBOX AUDIT: No recorded actions yet ==="

    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue

    if not records:
        return "=== AGENTBOX AUDIT: Log file is empty ==="

    total_ops = len(records)
    by_cmd: Dict[str, Dict[str, Any]] = {}
    by_target: Dict[str, int] = {}
    failures = []

    for r in records:
        cmd = r.get("cmd", "unknown")
        tgt = r.get("target", "local")
        code = r.get("code", 0)
        ms = r.get("ms", 0)

        by_target[tgt] = by_target.get(tgt, 0) + 1
        b = by_cmd.setdefault(cmd, {"count": 0, "ok": 0, "fail": 0, "total_ms": 0})
        b["count"] += 1
        b["total_ms"] += ms
        if code == 0:
            b["ok"] += 1
        else:
            b["fail"] += 1
            failures.append(r)

    out = [f"=== AGENTBOX AUDIT SUMMARY ({total_ops} actions recorded) ==="]

    tgt_parts = [f"{t}: {cnt} ({int(cnt * 100 / total_ops)}%)" for t, cnt in sorted(by_target.items(), key=lambda x: -x[1])]
    out.append(f"Targets : {', '.join(tgt_parts)}")
    out.append("")
    out.append(f"{'Command':<16} {'Calls':<8} {'Success':<10} {'Avg Latency'}")
    out.append("-" * 46)

    for cmd, data in sorted(by_cmd.items(), key=lambda x: -x[1]["count"]):
        pct = int((data["ok"] / data["count"]) * 100) if data["count"] else 0
        avg_ms = int(data["total_ms"] / data["count"]) if data["count"] else 0
        dur_str = f"{avg_ms}ms" if avg_ms < 1000 else f"{avg_ms / 1000:.1f}s"
        out.append(f"{cmd:<16} {data['count']:<8} {pct}%{'':<6} {dur_str}")

    if failures:
        out.append("")
        out.append(f"Recent Failures (last {min(5, len(failures))} of {len(failures)} total):")
        for f in failures[-5:]:
            t_str = f.get("target", "local")
            c_str = f.get("cmd", "")
            err_str = f.get("err") or f"exit {f.get('code', 1)}"
            details = []
            if f.get("path"):
                details.append(f["path"])
            if f.get("arg"):
                details.append(f"cmd: {f['arg']}")
            if f.get("query"):
                details.append(f"query: {f['query']}")
            p_str = f" ({', '.join(details)})" if details else ""
            out.append(f"  * [{t_str}] {c_str}{p_str} -> {err_str}")

    if tail and tail > 0:
        out.append("")
        out.append(f"=== Last {min(tail, len(records))} Raw Records ===")
        for r in records[-tail:]:
            t_str = r.get("target", "local")
            c_str = r.get("cmd", "")
            code_str = "OK" if r.get("code") == 0 else f"ERR({r.get('code')})"
            ms_str = f"{r.get('ms', 0)}ms"
            extra = []
            if r.get("path"):
                extra.append(r["path"])
            if r.get("arg"):
                extra.append(f"cmd: {r['arg']}")
            if r.get("query"):
                extra.append(f"query: {r['query']}")
            if r.get("lines"):
                extra.append(f"lines: {r['lines'][0]}-{r['lines'][1]}")
            if r.get("tail"):
                extra.append(f"tail: {r['tail']}")
            p_str = f" [{', '.join(extra)}]" if extra else ""
            out.append(f"  {r.get('ts', 0)} | {t_str:<8} | {c_str:<12} | {code_str:<6} | {ms_str:<6}{p_str}")
    return "\n".join(out)
RULE_TEMPLATE = """# 🛡️ MANDATORY PROTOCOL: Local & Remote Execution via AgentBox CLI

> [!IMPORTANT]
> **NEED-TO-KNOW & ZERO-ESCAPING PROTOCOL:**
> - DO NOT read or edit `.agentbox.json` directly (Need-to-Know: use `-t <target>` and `agentbox task`).
> - NEVER read full files, run raw grep/find, cat, or dump noisy git diffs/builds. Use `agentbox` tools.
> - **Zero-Escaping on Windows:** NEVER pass code or scripts inside raw CLI quotes (`"..."`). Prefer `agentbox task <name> [args]`, `--file` (write via native `write_file` -> pass path), or `--base64`.
> - **Multi-host:** Add `-t <target>` to run on configured target. Without `-t`, runs 100% locally.
> - **Read-Only Targets:** Targets marked `(read-only)` STRICTLY forbid any modifications (`write`, `patch`, `sync push`, `pip`) and code executions (`run`, `py`, `spawn`, `test`, `task`). Use ONLY Inspect & Navigate tools (`view`, `outline`, `get-fn`, `find-fn`, `refs`, `tree`, `grep`, `diff`, `git-*`, `sync pull`, `graphify-query`).

<!-- AGENTBOX_TARGETS_START -->
<!-- AGENTBOX_TARGETS_END -->

### 🧰 AgentBox Toolset:

#### 1. Inspect & Navigate
* `agentbox view <file> --start N --end M` (or `--tail N`) — line slice with 1-indexed numbers.
* `agentbox outline <file>` — AST outline of classes/functions (~120 tokens vs 3000).
* `agentbox get-fn <file> <name>` — extracts exact function or `Class.method` definition.
* `agentbox refs <sym>` / `agentbox find-fn <sym>` — locate symbol definitions and usages across project.
* `agentbox tree [path] [--depth N]` — compact directory tree.
* `agentbox grep "<query>" [path] [-F] [-l]` — text search (`-F`: exact text, `-l`: file names only).
* `agentbox graphify-query "<query>" [path] [--max-tokens N]` — architecture map & symbol relations (auto-builds if missing).
* `agentbox graphify-build [path] [--deep]` — force (re)build knowledge graph of target project.
* `agentbox graphify-install [--upgrade]` — silently provision/upgrade graphify engine.
* `agentbox graphify-open [path]` — open interactive graph in local browser (Remote-Compute, Local-Artifact).

#### 2. Edit, Write & Sync (Safe Payloads: `--file` or `--base64` ONLY)
* `agentbox patch-lines <file> --start N --end M --file <path> | --base64 <b64>` — replaces line slice `[N..M]` with auto-backup & AST check.
* `agentbox write <file> --file <path> | --base64 <b64> [--append]` — writes/appends file safely.
* `agentbox cp <src> <dest>` — copies file directly between targets or local workspace (`[target:]path`).
* `agentbox patch <file> --old-file <old> --new-file <new>` — atomic search-and-replace.
* `agentbox rollback <file>` — restores previous version from backup.
* `agentbox sync status | push | pull [-t <tgt>] [--dry-run] [--force]` — two-way project sync.

#### 3. Test & Execute (Silent Runners)
* `agentbox test "<cmd>" | --file <path> | --base64 <b64>` — silences passing tests, extracts failure tracebacks (prefer `agentbox task <name>` to avoid Windows escaping issues).
* `agentbox run "<cmd>" | --file <path> | --base64 <b64>` — silent build/script runner.
* `agentbox spawn "<cmd>" | --file <path>` / `agentbox logs <id> -f` / `agentbox kill <id>` — background tasks.
* `agentbox pip <args>` — runs pip in isolated project venv.
* `agentbox diff [file]` / `agentbox git-status` / `agentbox git-log -n N` — token-efficient git info.

#### 4. Verified Project Recipes
* `agentbox task` — lists available project recipes (`agentbox task <name> [args]`).

<!-- AGENTBOX_TASKS_START -->
<!-- AGENTBOX_TASKS_END -->

### ⚡ Pre-Flight Checklist before execution:
1. Zero-Escaping on Windows: Did you use `agentbox py --base64`, `task`, or `--file` instead of raw shell quotes?
2. Context Guard: Did you use `outline` / `get-fn` / `py` instead of dumping full files into context?
3. Remote Target: Did you pass `-t <target>` if the operation should run on a remote server?
4. Read-Only Guard: Is the target marked `read-only`? If yes, use ONLY Inspect & Navigate tools (no edits/runs/push).
"""


def format_targets_markdown(targets: Optional[Dict[str, Dict[str, Any]]] = None, default_target: Optional[str] = None, newline: str = "\n") -> str:
    """Formats targets into a compact Markdown bullet list showing only names, active status, and readonly flags (zero leaked paths/hosts)."""
    if targets is None:
        targets = get_targets()
    if default_target is None:
        default_target = get_default_target_name()

    lines = ["<!-- AGENTBOX_TARGETS_START -->"]
    lines.append("##### 🌐 Available Execution Targets:")
    if targets:
        for name in sorted(targets.keys()):
            t = targets[name]
            is_active = (name == default_target) or (not default_target and name == next(iter(targets.keys())))
            is_ro = bool(t.get("readonly") or t.get("read_only"))
            status_parts = []
            if is_active:
                status_parts.append("active")
            if is_ro:
                status_parts.append("read-only")
            status = f" ({', '.join(status_parts)})" if status_parts else ""
            lines.append(f"* `{name}`{status}")
    else:
        lines.append("* `local` (active)")
    lines.append("<!-- AGENTBOX_TARGETS_END -->")
    return newline.join(lines)


def format_tasks_markdown(tasks: Optional[Dict[str, str]] = None, newline: str = "\n") -> str:
    """Formats tasks into a compact Markdown bullet list for rule injection."""
    if tasks is None:
        tasks = get_tasks()

    lines = ["<!-- AGENTBOX_TASKS_START -->"]
    if tasks:
        lines.append("##### 📋 Verified Project Recipes (Auto-Memoized):")
        for name, cmd in sorted(tasks.items()):
            lines.append(f"* `agentbox task {name}` — `{cmd}`")
    lines.append("<!-- AGENTBOX_TASKS_END -->")
    return newline.join(lines)


def sync_rules(target_dir: Optional[Path] = None) -> List[str]:
    """Deterministically injects active targets and tasks into existing rule files preserving original line endings."""
    root = target_dir or Path.cwd()
    rule_filenames = ["AGENTS.md", ".cursorrules", "CLAUDE.md"]
    updated_files = []
    tasks = get_tasks()
    targets = get_targets()
    def_target = get_default_target_name()

    tasks_start = "<!-- AGENTBOX_TASKS_START -->"
    tasks_end = "<!-- AGENTBOX_TASKS_END -->"
    targets_start = "<!-- AGENTBOX_TARGETS_START -->"
    targets_end = "<!-- AGENTBOX_TARGETS_END -->"

    for fname in rule_filenames:
        p = root / fname
        if not p.is_file():
            continue

        raw_bytes = p.read_bytes()
        newline = "\r\n" if b"\r\n" in raw_bytes else "\n"
        content = raw_bytes.decode("utf-8")
        orig_content = content

        if tasks_start in content and tasks_end in content:
            new_tasks_block = format_tasks_markdown(tasks, newline)
            pattern_tasks = re.compile(
                re.escape(tasks_start) + r".*?" + re.escape(tasks_end),
                re.DOTALL
            )
            content = pattern_tasks.sub(new_tasks_block, content)

        if targets_start in content and targets_end in content:
            new_targets_block = format_targets_markdown(targets, def_target, newline)
            pattern_targets = re.compile(
                re.escape(targets_start) + r".*?" + re.escape(targets_end),
                re.DOTALL
            )
            content = pattern_targets.sub(new_targets_block, content)

        if content != orig_content:
            p.write_bytes(content.encode("utf-8"))
            updated_files.append(fname)

    return updated_files


def sync_rules_with_tasks(target_dir: Optional[Path] = None) -> List[str]:
    """Backwards-compatible alias for sync_rules."""
    return sync_rules(target_dir)


def generate_rules(target_type: str = "agents", target_dir: Optional[Path] = None) -> List[str]:
    """Generates AI agent rule files (AGENTS.md by default)."""
    root = target_dir or Path.cwd()
    tasks_block = format_tasks_markdown()
    targets_block = format_targets_markdown()

    full_content = RULE_TEMPLATE.replace(
        "<!-- AGENTBOX_TASKS_START -->\n<!-- AGENTBOX_TASKS_END -->",
        tasks_block
    ).replace(
        "<!-- AGENTBOX_TARGETS_START -->\n<!-- AGENTBOX_TARGETS_END -->",
        targets_block
    )

    targets = []
    if target_type in ("agents", "all"):
        targets.append("AGENTS.md")
    if target_type in ("cursor", "all"):
        targets.append(".cursorrules")
    if target_type in ("claude", "all"):
        targets.append("CLAUDE.md")

    written = []
    for fname in targets:
        p = root / fname
        p.write_text(full_content, encoding="utf-8")
        written.append(fname)
        print(f"Generated {fname}")

    return written
