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
