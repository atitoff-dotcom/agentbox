# -*- coding: utf-8 -*-
"""
agentbox.config — Configuration manager for AgentBox.
Supports global (~/.agentbox/config.json) and project-level (.agentbox.json) settings.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any

GLOBAL_CONFIG_DIR = Path.home() / ".agentbox"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"
LOCAL_CONFIG_FILE = Path(".agentbox.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": "",
    "cwd": "",
    "timeout": 300,
    "tail": 15,
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
    cfg = get_config()
    cfg.update(updates)
    GLOBAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def save_local_config(updates: Dict[str, Any]) -> None:
    """Updates and saves local project-level configuration."""
    cfg = get_config()
    cfg.update(updates)
    LOCAL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


RULE_TEMPLATE = """# 🛡️ MANDATORY PROTOCOL: Remote & Local Execution (AgentBox)

> [!IMPORTANT]
> To eliminate token waste and prevent shell syntax errors, you MUST use `agentbox` for all remote (SSH) and project code operations.
> Direct raw execution of `cat`, `grep`, `find`, or streaming test runners over SSH is STRICTLY PROHIBITED.

### 🚫 STRICTLY BANNED COMMANDS OVER SSH:
1. DO NOT read entire files: never use `cat <file>` or download full 200+ line files -> USE `agentbox outline <file>` or `agentbox view <file>`.
2. DO NOT search files using raw find/grep: never use `find .` or raw `grep` -> USE `agentbox tree` or `agentbox grep "<query>"`.
3. DO NOT stream noisy builds or tests: never run raw `pytest`, `cargo build`, or `npm test` -> USE `agentbox test "<cmd>"` or `agentbox run "<cmd>"`.
4. DO NOT write files via `cat << 'EOF'`: bash escaping often breaks quotes and symbols -> USE `agentbox write <file>` or `agentbox patch <file>`.

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
* `agentbox test "<test_cmd>"` — silent test runner; suppresses passing tests and extracts high-signal failure tracebacks.
* `agentbox run "<build_cmd>"` — suppresses intermediate noisy terminal stream, buffering to log.
* `agentbox spawn "<cmd>"` / `agentbox status <id>` / `agentbox logs <id> -f` — detached background tasks.

#### 4. Architecture & Knowledge Graph
* `agentbox graphify-query "<question>"` — queries code connections and God nodes directly on host without dumping large JSON.
"""


def generate_rules(target_type: str = "all") -> None:
    """Generates rules files in current workspace for AI assistants."""
    created = []

    types = ["cursor", "agents", "claude"] if target_type == "all" else [target_type]

    if "cursor" in types:
        p = Path(".cursorrules")
        p.write_text(RULE_TEMPLATE, encoding="utf-8")
        created.append(".cursorrules")

    if "agents" in types:
        p = Path("AGENTS.md")
        p.write_text(RULE_TEMPLATE, encoding="utf-8")
        created.append("AGENTS.md")

    if "claude" in types:
        p = Path("CLAUDE.md")
        p.write_text(RULE_TEMPLATE, encoding="utf-8")
        created.append("CLAUDE.md")

    print(f"OK: Created AI rule files: {', '.join(created)}")
