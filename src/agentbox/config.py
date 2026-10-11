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

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "",
    "cwd": "",
    "venv": "",
    "timeout": 300,
    "tail": 15,
    "tasks": {},
}


def get_config() -> Dict[str, Any]:
    """Loads merged configuration: default -> global -> local."""
    cfg = dict(DEFAULT_CONFIG)

    if GLOBAL_CONFIG_FILE.is_file():
        try:
            cfg.update(json.loads(GLOBAL_CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

    if LOCAL_CONFIG_FILE.is_file():
        try:
            cfg.update(json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

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
    if LOCAL_CONFIG_FILE.is_file():
        try:
            cfg = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg.update(updates)
    LOCAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


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

    if LOCAL_CONFIG_FILE.is_file():
        try:
            l_data = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(l_data.get("tasks"), dict):
                tasks.update(l_data["tasks"])
        except Exception:
            pass

    return tasks


def add_task(name: str, command: str) -> None:
    """Saves or updates a task in the local project .agentbox.json."""
    cfg = {}
    if LOCAL_CONFIG_FILE.is_file():
        try:
            cfg = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    tasks = cfg.get("tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
    tasks[name] = command
    cfg["tasks"] = tasks
    LOCAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules_with_tasks()


def remove_task(name: str) -> bool:
    """Removes a task from local project .agentbox.json. Returns True if removed, False if not found."""
    if not LOCAL_CONFIG_FILE.is_file():
        return False

    try:
        cfg = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False

    tasks = cfg.get("tasks", {})
    if not isinstance(tasks, dict) or name not in tasks:
        return False

    del tasks[name]
    cfg["tasks"] = tasks
    LOCAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    sync_rules_with_tasks()
    return True


RULE_TEMPLATE = """# 🛡️ MANDATORY PROTOCOL: Remote & Local Execution (AgentBox)

> [!IMPORTANT]
> To eliminate token waste and prevent shell syntax errors, you MUST use `agentbox` for all remote (SSH) and project code operations.
> Direct raw execution of `cat`, `grep`, `find`, or streaming test runners over SSH is STRICTLY PROHIBITED.

### 🚫 STRICTLY BANNED COMMANDS OVER SSH:
1. DO NOT read entire files: never use `cat <file>` or download full 200+ line files -> USE `agentbox outline <file>` or `agentbox view <file>`.
2. DO NOT search files using raw find/grep: never use `find .` or raw `grep` -> USE `agentbox tree` or `agentbox grep "<query>"`.
3. DO NOT stream noisy builds or tests: never run raw `pytest`, `cargo build`, or `npm test` -> USE `agentbox test "<cmd>"` or `agentbox run "<cmd>"`.
4. DO NOT write files via `cat << 'EOF'`: bash escaping often breaks quotes and symbols -> USE `agentbox write <file>` or `agentbox patch <file>`.
5. DO NOT dump raw git diff or log: never run raw `git diff` or `git log -p` -> USE `agentbox diff` or `agentbox git-log` / `agentbox git-view`.

### ✅ MANDATORY AGENTBOX CLI TOOLSET:

#### 1. Code Navigation & Slicing
* `agentbox outline <file>` — extracts AST classes and function signatures with line ranges (~120 tokens vs 3,000).
* `agentbox get-fn <file> <name>` — extracts exact target function or class definition.
* `agentbox view <file> --start N --end M` — views an exact line slice with 1-indexed numbers.

#### 2. Safe File Writing & Atomic Patching
* `agentbox write <file> --content "..."` — safely writes/overwrites file without ANY bash quote escaping bugs.
* `agentbox patch <file> --old "..." --new "..."` — in-place atomic search-and-replace with auto-backup (`.bak`).
* `agentbox rollback <file>` — restores from backup if an edit caused errors.

#### 3. Silent Builds, Tests & Background Tasks
* `agentbox test "<test_cmd>"` — silent test runner; suppresses passing tests and extracts high-signal failure tracebacks (auto-detects .venv/venv or --venv).
* `agentbox run "<build_cmd>"` — suppresses intermediate noisy terminal stream, buffering to log (auto-detects .venv/venv or --venv).
* `agentbox spawn "<cmd>"` / `agentbox status <id>` / `agentbox logs <id> -f` — detached background tasks (auto-detects .venv/venv or --venv).

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


def format_tasks_markdown(tasks: Optional[Dict[str, str]] = None) -> str:
    """Formats tasks into a compact Markdown bullet list for rule injection."""
    if tasks is None:
        tasks = get_tasks()

    lines = ["<!-- AGENTBOX_TASKS_START -->"]
    if tasks:
        lines.append("##### 📋 Verified Project Recipes (Auto-Memoized):")
        for name, cmd in sorted(tasks.items()):
            lines.append(f"* `agentbox task {name}` — `{cmd}`")
    lines.append("<!-- AGENTBOX_TASKS_END -->")
    return "\n".join(lines)


def sync_rules_with_tasks(target_dir: Optional[Path] = None) -> List[str]:
    """Deterministically injects active tasks into existing rule files."""
    root = target_dir or Path.cwd()
    rule_filenames = [".cursorrules", "AGENTS.md", "AGENT.md", "CLAUDE.md"]
    updated_files = []
    tasks = get_tasks()
    tasks_block = format_tasks_markdown(tasks)

    start_marker = "<!-- AGENTBOX_TASKS_START -->"
    end_marker = "<!-- AGENTBOX_TASKS_END -->"

    for fname in rule_filenames:
        p = root / fname
        if not p.is_file():
            continue

        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue

        if start_marker in content and end_marker in content:
            # Replace existing block between markers
            pattern = re.compile(rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL)
            new_content = pattern.sub(tasks_block, content)
        else:
            # Inject block right after Project Tasks & Recipes header if present
            anchor = "#### 6. Project Tasks & Recipes (.agentbox.json)"
            if anchor in content:
                new_content = content.replace(anchor, f"{anchor}\n\n{tasks_block}")
            else:
                new_content = content + f"\n\n{tasks_block}\n"

        if new_content != content:
            p.write_text(new_content, encoding="utf-8")
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

    print(f"OK: Created AI rule files: {', '.join(created)}")
