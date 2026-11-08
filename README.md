# 📦 AgentBox (`ai-agentbox`)

[![PyPI version](https://img.shields.io/pypi/v/ai-agentbox.svg)](https://pypi.org/project/ai-agentbox/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#zero-dependencies)

**Ultra-lean, token-efficient execution, AST outlining, and safe atomic patching proxy for AI coding agents.**

Designed for LLM agents (**Claude Code, Cursor, Antigravity, Aider, Roo-Code, Windsurf**) working on remote servers or local machines.

---

## ⚡ The Problem & The Solution

AI coding assistants burn **thousands of wasted tokens** reading full files, streaming noisy build logs (`pytest`, `cargo`, `docker`), and failing on shell quote escaping over SSH.

AgentBox cuts token consumption by **80% to 95%**:

| Task | Standard AI Agent over SSH | With AgentBox | Token Savings |
|---|:---:|:---:|:---:|
| **Analyze 800-line file** | Reads full file (`~3,000` tokens) | `agentbox outline` (`~120` tokens) | **-96%** ⚡ |
| **Inspect target function** | Guesses line ranges (`~600` tokens) | `agentbox get-fn` (`~150` tokens) | **-75%** 📉 |
| **Run long build (`cargo`)** | Streams 200 lines (`~1,500` tokens) | `agentbox run` silent (`~40` tokens) | **-97%** ⚡ |
| **Atomic in-place patch** | Raw diff / cat (`~400` tokens) | `agentbox patch` (`~60` tokens) | **-85%** 📉 |
| **Project navigation** | `find .` / `tree` (`~1,200` tokens) | `agentbox tree` (`~150` tokens) | **-88%** 📉 |

---

## 🚀 Quickstart: Setup in 60 Seconds

You do not need to memorize or run low-level commands manually. Setup takes 2 simple steps: **configure your project and targets**, then **generate agent instructions**. Your AI assistant handles the rest!

### 1. Install `ai-agentbox`
```bash
pip install ai-agentbox
```

### 2. Configure `.agentbox.json`
Create `.agentbox.json` in your project root to define execution targets (local or remote SSH) and verified project task recipes.

#### Option A: Direct JSON (Recommended)
```json
{
  "default_target": "local",
  "targets": {
    "local": {
      "cwd": "."
    },
    "dev": {
      "host": "developer@dev.server.com",
      "cwd": "/home/developer/app",
      "venv": "/home/developer/app/.venv"
    },
    "prod": {
      "host": "deploy@prod.server.com",
      "cwd": "/var/www/backend",
      "readonly": true
    }
  },
  "tasks": {
    "test": "pytest tests/ -v",
    "build": "python -m build",
    "db": "psql -U postgres -d mydb -c {args}"
  }
}
```

> [!TIP]
> * **Zero-Config Local:** If `.agentbox.json` is omitted, AgentBox works 100% locally out of the box.
> * **Read-Only Guard:** Targets marked `"readonly": true` forbid modifications (`write`, `patch`, `sync push`) and arbitrary runs (`run`, `test`, `spawn`), allowing ONLY safe inspection (`view`, `outline`, `tree`, `grep`, `graphify-query`).

#### Option B: Via CLI Commands
```bash
# Add targets:
agentbox target add prod --host deploy@prod.server.com --cwd /var/www/backend --readonly
agentbox target add dev --host developer@dev.server.com --cwd /home/developer/app

# Add verified task recipes:
agentbox task add test "pytest tests/ -v"
agentbox task add build "python -m build"
agentbox task add db "psql -U postgres -d mydb -c {args}"
```

---

### 3. Generate AI Agent Rules (`AGENTS.md`)

Generate strict anti-token-waste instructions for your AI agent with a single command:

```bash
agentbox rules
```
*(Alias: `agentbox init-rules`)*

This creates `AGENTS.md` (or `--type cursor` for `.cursorrules`, `--type claude` for `CLAUDE.md`, or `--type all`):
* Prohibits noisy `cat`, `find`, raw `grep`, and unbuffered test commands.
* Injects your configured **targets** (with read-only badges) and **task recipes** directly into the prompt context.
* Instructs the agent on how to use AgentBox's zero-escaping and AST inspection tools.

Whenever you add or update targets or tasks in `.agentbox.json`, sync your rules in one step:
```bash
agentbox rules --sync
```

---

### 4. Let Your AI Agent Work!

Open **Cursor, Claude Code, Antigravity, Windsurf, Roo-Code, or Aider** and give it any task:

> *"Inspect the authentication service on prod, locate verify_token, and run test suite on dev."*

The AI assistant reads `AGENTS.md` and uses AgentBox automatically:
* Connects seamlessly over SSH.
* Self-bootstraps the zero-dependency worker on the remote host in milliseconds.
* Extracts function ASTs, runs silent tests, and applies escape-proof atomic patches.

---

## 🧰 AgentBox Toolset Overview

While AI assistants use these tools autonomously via `AGENTS.md`, you can also use them directly:

| Category | Commands | Description |
|---|---|---|
| **Targets & Tasks** | `agentbox target`, `agentbox task` | Manage execution environments and run verified project recipes. |
| **Inspect & Navigate** | `agentbox outline`, `agentbox get-fn`, `agentbox find-fn`, `agentbox view`, `agentbox tree`, `agentbox grep` | AST extraction of classes/functions and token-capped code slices. |
| **Safe File Edits** | `agentbox patch-lines`, `agentbox write`, `agentbox cp`, `agentbox patch`, `agentbox rollback` | Escape-proof atomic edits with auto-backup and AST validation. |
| **Silent Runners** | `agentbox test`, `agentbox run`, `agentbox spawn`, `agentbox logs`, `agentbox kill` | Suppress stdout noise; extract high-signal failure tracebacks. |
| **Git & History** | `agentbox git-status`, `agentbox diff`, `agentbox git-log`, `agentbox git-view`, `agentbox git-fn-history` | Token-capped diffs (ignoring lockfiles/whitespace) and commit logs. |
| **Sync & Knowledge** | `agentbox sync`, `agentbox graphify-*`, `agentbox daemon` | Two-way file sync, architecture knowledge graph, and sub-ms daemon bridge. |

👉 **For the complete guide and syntax of all 30+ commands, see the [Detailed CLI Reference Manual (`docs/CLI.md`)](docs/CLI.md).**

---

## 💡 Key Architecture Highlights

* **Zero External Dependencies**: Standard Python library only (`argparse`, `ast`, `subprocess`, `json`, `socket`).
* **Self-Bootstrapping Worker**: Deploys `~/.agentbox_worker.py` over SSH on demand — never requires manual server setup.
* **Persistent Daemon Bridge**: In-memory worker connection reduces remote execution latency to **2–5 ms**.
* **Zero-Escaping Protocol**: Code edits and command payloads pass via Base64, `--file`, or stdin streams, eliminating PowerShell and SSH quotation bugs forever.

---

## 📄 License

MIT License. Free for open-source and commercial use.
