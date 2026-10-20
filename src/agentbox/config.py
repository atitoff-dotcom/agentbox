# -*- coding: utf-8 -*-
"""
agentbox.config — Configuration manager for AgentBox.
Supports global (~/.agentbox/config.json) and project-level (.agentbox.json) settings.
"""

import os
import re
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
    sync_rules_with_tasks()


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
    sync_rules_with_tasks()
    return True


RULE_TEMPLATE = """# 🛡️ MANDATORY PROTOCOL: Remote & Local Execution (AgentBox)

> [!CAUTION]
> **CRITICAL PRE-FLIGHT RULES (READ BEFORE FIRST TOOL CALL):**
> 1. **CALL MCP TOOLS DIRECTLY ON STEP 1:** Call `call_mcp_tool` (`ServerName: "agentbox"`) immediately using the JSON signatures below. **NEVER** read, list, or search `.json` schema files in `~/.gemini` or `C:\\Users\\...\\antigravity\\mcp\\`!
> 2. **DYNAMIC `.agentbox.json` (LOCAL & SSH):** `agentbox mcp` automatically reloads `.agentbox.json` from the project directory on every call (including SSH `host`, `cwd`, `venv`). Always pass `"cwd": "<workspace_root>"` or full file paths so `agentbox mcp` locks onto the project's `.agentbox.json`.
> 3. **NO FULL-FILE DUMPS:** Never read entire 200+ line files — start with `agentbox_outline` or `agentbox_get_fn`, then slice with `agentbox_view`.
> 4. **BATCH MULTIPLE STEPS:** Use `agentbox_batch` when combining 2 or more operations in a single turn.

### 🚫 STRICTLY BANNED COMMANDS (LOCAL & OVER SSH):
1. DO NOT read entire files: never use `cat <file>` or download full 200+ line files -> USE `agentbox_outline` or `agentbox_view`.
2. DO NOT search files using raw find/grep: never use `find .` or raw `grep` -> USE `agentbox_tree`, `agentbox_refs`, or `agentbox_grep`.
3. DO NOT stream noisy builds or tests: never run raw `pytest`, `cargo build`, or `npm test` -> USE `agentbox_test` or `agentbox_run`.
4. DO NOT write files via `cat << 'EOF'`: shell escaping breaks quotes and symbols -> USE `agentbox_write`, `agentbox_patch`, or `agentbox_patch_lines`.
5. DO NOT dump raw git diff or log: never run raw `git diff` or `git log -p` -> USE `agentbox_diff`, `agentbox_git_log`, or `agentbox_git_view`.

### ⚡ MANDATORY MCP SIGNATURES (`call_mcp_tool`, `ServerName: "agentbox"`):
*(Вызывай `call_mcp_tool` сразу с первого же шага, НЕ читая файлы схем в `~/.gemini`!)*

#### 1. Code Navigation & Slicing
#### 1. Code Navigation & Slicing
* `agentbox_outline` → `{"path": "<file_or_dir_or_list>", "cwd"?: "<proj_dir>"}`
* `agentbox_get_fn` → `{"path": "<file>", "name": "<fn_or_Class.method>", "cwd"?: "<proj_dir>"}`
* `agentbox_find_fn` → `{"name": "<symbol>", "path"?: "<dir>", "exact"?: false, "max"?: 30}`
* `agentbox_refs` → `{"name": "<symbol>", "path"?: "<dir>", "max"?: 40}`
* `agentbox_view` → `{"path": "<file>", "start"?: 1, "end"?: 100, "tail"?: 50, "cwd"?: "<proj_dir>"}`

#### 2. Safe File Writing & Atomic Patching
* `agentbox_patch_lines` → `{"path": "<file>", "start": 1, "end": 10, "content": "...", "check_syntax"?: true, "cwd"?: "<proj_dir>"}` *(Preferred standard)*
* `agentbox_patch` → `{"path": "<file>", "old": "...", "new": "...", "all"?: false, "check_syntax"?: true, "cwd"?: "<proj_dir>"}`
* `agentbox_write` → `{"path": "<file>", "content": "...", "append"?: false, "cwd"?: "<proj_dir>"}`
* `agentbox_rollback` → `{"path": "<file>", "cwd"?: "<proj_dir>"}` *(Restores from `.agentbox/backups/`)*

#### 3. Search, Silent Builds, Tests, Venv & Batching
* `agentbox_tree` → `{"path"?: "<dir>", "depth"?: 2, "cwd"?: "<proj_dir>"}`
* `agentbox_grep` → `{"query": "<regex_or_string>", "path"?: "<dir_or_file>", "fixed"?: false, "max"?: 20, "cwd"?: "<proj_dir>"}`
* `agentbox_test` → `{"cmd": "<test_cmd>", "cwd"?: "<proj_dir>", "max_lines"?: 30, "timeout"?: 300, "venv"?: "<path>"}`
* `agentbox_run` → `{"cmd": "<build_cmd>", "cwd"?: "<proj_dir>", "tail"?: 15, "timeout"?: 300, "venv"?: "<path>"}`
* `agentbox_pip` → `{"pip_args": "install <pkg>", "cwd"?: "<proj_dir>", "venv"?: "<path>"}`
* `agentbox_batch` → `{"steps": [{"action": "view", "path": "f.py", "start": 1, "end": 20}, {"action": "patch_lines", "path": "f.py", "start": 5, "end": 8, "content": "..."}], "stop_on_error"?: true, "cwd"?: "<proj_dir>"}`
* `agentbox_stats` → `{"clear"?: false}`

#### 4. Token-Efficient Git History & Changes
* `agentbox_git_status` → `{"path"?: "<repo_dir>", "cwd"?: "<proj_dir>"}`
* `agentbox_diff` → `{"path"?: "<file_or_dir>", "rev"?: "<rev>", "cached"?: false, "max_lines"?: 100, "cwd"?: "<proj_dir>"}`
* `agentbox_git_log` → `{"path"?: "<file_or_dir>", "limit"?: 5, "cwd"?: "<proj_dir>"}`

### 💻 CLI WORKFLOW & POWERSHELL SAFE PATTERNS:

#### 1. Code Navigation & Slicing
* `agentbox outline <file> [files...]` — extracts AST classes and function signatures with line ranges (~120 tokens vs 3,000).
* `agentbox get-fn <file> <name>` — extracts exact target function, class, or `ClassName.method_name` definition.
* `agentbox find-fn <name> [path]` — scans project AST to locate where a function or class is defined across files.
* `agentbox refs <name> [path]` — finds all symbol references (imports, calls, attributes, inheritance) across the codebase.
* `agentbox view <file> --start N --end M` — views an exact line slice with 1-indexed numbers.
* `agentbox view <file> --tail N` — views last N lines of a file (or log) in a single step.

#### 2. Safe File Writing & Atomic Patching
* `agentbox patch-lines <file> --start N --end M --content "..."` — replaces 1-indexed line range `[N..M]` with auto-backup (`.agentbox/backups/`) and AST check.
* `agentbox patch-lines <file> --start N --end M --base64 <b64>` — 100% immune to PowerShell/SSH quoting and Cyrillic encoding bugs:
  ```powershell
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(@'
  Любой сложный код с "кавычками", $переменными и кириллицей
  '@))
  agentbox patch-lines file.py --start 10 --end 20 --base64 $b64
  ```
* `agentbox write <file> --content "..." [--base64 <b64>]` — safely writes/overwrites file.
* `agentbox patch <file> --old "..." --new "..."` — in-place atomic search-and-replace with auto-backup and AST check.
* `agentbox rollback <file>` — restores from `.agentbox/backups/` keeping workspace clean.

#### 3. Search, Silent Builds, Tests, Venv & Batching
* `agentbox grep "<query>" [path_or_file] [-F]` — fast search across directories OR a single file (case-insensitive regex or `-F` literal string).
* `agentbox test "<test_cmd>"` — silent test runner; suppresses passing tests and extracts high-signal failure tracebacks (auto-detects `.agentbox/venv` / `.venv`).
* `agentbox run "<build_cmd>"` — suppresses intermediate noisy terminal stream, buffering to log (auto-detects `.agentbox/venv` / `.venv`).
* `agentbox pip <args>` — runs `pip` inside isolated `.agentbox/venv` (auto-creating it if no virtualenv exists).
* `agentbox batch '<json_steps>'` / `agentbox batch --base64 <b64>` — executes multiple actions in 1 turn:
  ```json
  [
    {"action": "view", "path": "src/app.py", "start": 1, "end": 30},
    {"action": "patch_lines", "path": "src/app.py", "start": 10, "end": 12, "content": "    return True\n"}
  ]
  ```
* `agentbox stats` — displays token savings and execution statistics dashboard.
* `agentbox spawn "<cmd>"` / `agentbox status <id>` / `agentbox logs <id> -f` — detached background tasks.

#### 4. Architecture & Knowledge Graph
* `agentbox graphify-query "<question>"` — queries code connections and God nodes directly on host without dumping large JSON.

#### 5. Token-Efficient Git History & Changes
* `agentbox git-status` — compact changed file status with (+add, -del) counts.
* `agentbox diff [file]` — noise-free diff (ignores lockfiles and whitespace changes).
* `agentbox git-log [file] -n N` — ultra-compact 1-line commit log.
* `agentbox git-view <file> [rev] --start N --end M` — views line slice from any Git revision without downloading full file.
* `agentbox git-fn-history <file> <fn>` — traces AST modification history of a function across Git commits.

#### 6. Project Tasks & Recipes (.agentbox.json)
* `agentbox task` / `agentbox task list` — lists available project recipes and tasks.
* `agentbox task <name> [args]` — executes saved task with optional argument substitution ({args} or appended).
* `agentbox task add <name> "<cmd>"` — saves or updates a task recipe in project `.agentbox.json`.
* `agentbox task rm <name>` — removes a task from `.agentbox.json`.

<!-- AGENTBOX_TASKS_START -->
<!-- AGENTBOX_TASKS_END -->

### 🔄 Самообучение и рецепты (Task Auto-Memoization):
Если в процессе работы потребовалось подобрать сложную или неочевидную команду проекта (подключение к БД, вызов внутреннего скрипта, миграция, перезапуск сервиса) — после её успешного выполнения ОБЯЗАТЕЛЬНО сохрани её как рецепт:
`agentbox task add <name> "<command>"`
и используй в дальнейшем `agentbox task <name>`, чтобы не подбирать параметры повторно.
"""


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


def sync_rules_with_tasks(target_dir: Optional[Path] = None) -> List[str]:
    """Deterministically injects active tasks into existing rule files preserving original line endings."""
    root = target_dir or Path.cwd()
    rule_filenames = [".cursorrules", "AGENTS.md", "AGENT.md", "CLAUDE.md"]
    updated_files = []
    tasks = get_tasks()

    start_marker = "<!-- AGENTBOX_TASKS_START -->"
    end_marker = "<!-- AGENTBOX_TASKS_END -->"

    for fname in rule_filenames:
        p = root / fname
        if not p.is_file():
            continue

        try:
            raw_bytes = p.read_bytes()
            newline = "\r\n" if b"\r\n" in raw_bytes else "\n"
            content = raw_bytes.decode("utf-8")
        except Exception:
            continue

        tasks_block = format_tasks_markdown(tasks, newline=newline)

        if start_marker in content and end_marker in content:
            # Replace existing block between markers
            pattern = re.compile(rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL)
            new_content = pattern.sub(tasks_block, content)
        else:
            # Inject block right after Project Tasks & Recipes header if present
            anchor = "#### 6. Project Tasks & Recipes (.agentbox.json)"
            if anchor in content:
                new_content = content.replace(anchor, f"{anchor}{newline}{newline}{tasks_block}")
            else:
                new_content = content + f"{newline}{newline}{tasks_block}{newline}"

        if new_content != content:
            p.write_bytes(new_content.encode("utf-8"))
            updated_files.append(fname)

    return updated_files


def generate_rules(target_type: str = "all") -> None:
    """Generates rules files in current workspace for AI assistants."""
    created = []

    types = ["cursor", "agents", "claude"] if target_type == "all" else [target_type]

    # Pre-render rule template with current tasks
    tasks_block = format_tasks_markdown()
    rendered_template = RULE_TEMPLATE.replace(
        "<!-- AGENTBOX_TASKS_START -->\n<!-- AGENTBOX_TASKS_END -->",
        tasks_block
    )

    if "cursor" in types:
        p = Path(".cursorrules")
        p.write_text(rendered_template, encoding="utf-8")
        created.append(".cursorrules")

    if "agents" in types:
        p = Path("AGENTS.md")
        p.write_text(rendered_template, encoding="utf-8")
        created.append("AGENTS.md")
        p2 = Path("AGENT.md")
        p2.write_text(rendered_template, encoding="utf-8")
        created.append("AGENT.md")

    if "claude" in types:
        p = Path("CLAUDE.md")
        p.write_text(rendered_template, encoding="utf-8")
        created.append("CLAUDE.md")

    # Ensure .agentbox/venv is ignored in .gitignore if .gitignore exists
    gitignore = Path(".gitignore")
    if gitignore.is_file():
        try:
            gi_text = gitignore.read_text(encoding="utf-8")
            if ".agentbox/venv" not in gi_text and ".agentbox/" not in gi_text:
                sep = "" if gi_text.endswith("\n") else "\n"
                gitignore.write_text(f"{gi_text}{sep}.agentbox/venv/\n", encoding="utf-8")
        except Exception:
            pass

    print(f"OK: Created AI rule files: {', '.join(created)}")
