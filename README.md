# 📦 AgentBox (`ai-agentbox`)

[![PyPI version](https://img.shields.io/pypi/v/ai-agentbox.svg)](https://pypi.org/project/ai-agentbox/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#zero-dependencies)

**Ultra-lean, token-efficient remote execution, AST outlining, and safe atomic patching proxy for AI coding agents.**

Designed for LLM agents (**Claude Code, Cursor, Antigravity, Aider, Roo-Code, Windsurf**) working on remote servers or local machines.

---

## 🎯 The Problem

When AI coding assistants work over SSH or terminal sessions, they burn massive token budgets on:
1. **Dumping entire files** (hundreds of lines of code just to locate one function).
2. **Intermediate noise from long commands** (`cargo build`, `pytest`, `docker build` streaming lines every second and triggering unnecessary agent turns).
3. **Broken shell quoting** (escaping nested quotes `\"` and `'` in bash over SSH leads to repeated syntax errors and retry loops).

---

## ⚡ The Solution: AgentBox

AgentBox provides a **Client $\leftrightarrow$ Worker** architecture that reduces token consumption by **80% to 95%**:

| Task | Standard AI Agent over SSH | With AgentBox | Token Savings |
|---|:---:|:---:|:---:|
| **Analyze 800-line file** | Reads full file (`~3,000` tokens) | `agentbox outline` (`~120` tokens) | **-96%** ⚡ |
| **Inspect target function** | Guesses line ranges (`~600` tokens) | `agentbox get-fn` (`~150` tokens) | **-75%** 📉 |
| **Run long build (`cargo`)** | Streams 200 lines (`~1,500` tokens) | `agentbox run` silent (`~40` tokens) | **-97%** ⚡ |
| **Atomic in-place patch** | Raw diff / cat (`~400` tokens) | `agentbox patch` (`~60` tokens) | **-85%** 📉 |
| **Project navigation** | `find .` / `tree` (`~1,200` tokens) | `agentbox tree` (`~150` tokens) | **-88%** 📉 |

---

## 🚀 Key Features

* **Zero External Dependencies**: Built entirely on the Python 3 standard library.
* **Self-Bootstrapping Worker**: When targeting a remote SSH server, AgentBox automatically verifies, hashes, and deploys its standalone worker in milliseconds.
* **Silent Task Runner**: Suppresses intermediate stdout noise, streams to a local log file, and returns only execution time, exit code, and failure tail.
* **Background Process Manager**: Detached process spawning (`spawn`, `status`, `logs`, `kill`) that survives SSH disconnections.
* **AST-Powered Skeletons**: Extracts class and function signatures for Python, Rust, JavaScript, TypeScript, C/C++, and Go.
* **Escape-Proof Atomic Patching**: Sends replacement payloads over stdin IPC streams, eliminating bash quote escaping bugs forever.

---

## 📦 Installation

```bash
pip install ai-agentbox
```

---

## 🛠️ Quickstart

### 1. Configure Target (Optional)

Configure your remote SSH server once (stored in `.agentbox.json` or `~/.agentbox/config.json`):

```bash
agentbox config --set-host user@192.168.1.171 --set-cwd ~/my_project
```

Or pass `--host` and `--cwd` directly to any command:

```bash
agentbox --host user@192.168.1.171 --cwd ~/my_project tree
```

To run **locally**, simply omit the host:
```bash
agentbox tree
```

---

## 📖 Command Reference

### 1. Code Navigation & Skeletons

#### `agentbox outline <file>`
Extracts only class, function, and method signatures with line numbers:
```bash
agentbox outline src/gateway.py
```
*Output:*
```text
=== OUTLINE: gateway.py (350 lines) ===
  12-  45 | class GatewayConfig:
  48- 110 | async def handle_connection(reader, writer) -> bool
 115- 180 | def commit_flash_block(offset: int) -> None
```

#### `agentbox get-fn <file> <function_name>`
Extracts the exact definition and body of a target function:
```bash
agentbox get-fn src/gateway.py handle_connection
```

#### `agentbox view <file> [--start N] [--end M]`
Displays an exact line slice with 1-indexed line numbers:
```bash
agentbox view src/gateway.py --start 48 --end 65
```

---

### 2. Silent & Background Process Runner

#### `agentbox run "<command>" [--tail N] [--timeout T]`
Silently executes a command, redirects all stdout/stderr to a log file, and returns only the final verdict:
```bash
agentbox run "cargo build --release"
```
*Output on success:*
```text
OK [exit 0, 42.15s] Log: /tmp/agent_logs/task_123456.log
```
*Output on failure (automatically prints tail):*
```text
FAILED [exit 1, 12.30s] Log: /tmp/agent_logs/task_123456.log
--- Failure Tail (5 lines) ---
error[E0308]: mismatched types
  --> src/main.rs:42:15
   |
42 |     let x: u8 = val;
   |                 ^^^ expected `u8`, found `u16`
```

#### `agentbox spawn "<command>"`
Spawns a detached background task that survives SSH disconnects:
```bash
agentbox spawn "python3 train_model.py"
# Output: SPAWNED: task_id=bg_849201 pid=4215 log=/tmp/agent_logs/bg_849201.log

agentbox status bg_849201
# Output: TASK: bg_849201 | Status: RUNNING | PID: 4215 | Runtime: 1m 24s

agentbox logs bg_849201 -n 20
# Output: displays last 20 lines of log

agentbox logs bg_849201 -f
# Output: live real-time log streaming (tail -f)

agentbox kill bg_849201
# Output: OK: Task bg_849201 (PID 4215) terminated.
```

---

### 3. Safe Atomic Patching

#### `agentbox patch <file> --old "<exact_code>" --new "<replacement>"`
Safely replaces code with automatic `.bak` backup creation:
```bash
agentbox patch src/config.py --old 'PORT = 8000' --new 'PORT = 9000'
# Output: OK: Replaced 1 occurrence(s) in config.py. Backup: config.py.bak
```

#### `agentbox rollback <file>`
Restores file from backup in case of errors:
```bash
agentbox rollback src/config.py
# Output: OK: Restored config.py from backup and removed backup.
```

---

### 4. Search & Directory Tree

#### `agentbox tree [path] [--depth N]`
Prints clean directory structure while automatically ignoring `.git`, `node_modules`, `target`, `__pycache__`, `.venv`, and build artifacts:
```bash
agentbox tree --depth 2
```

#### `agentbox grep "<query>" [path] [--max N]`
Fast token-limited search across text files:
```bash
agentbox grep "handle_packet" src/ --max 10
```

---

## 🤖 System Prompt for AI Agents

Add this rule to your project's `AGENTS.md` or `.cursorrules` to instruct your AI agent to use `agentbox`:

```markdown
## Remote & Local Execution (AgentBox)
Always use `agentbox` for remote server operations to minimize token consumption:
1. Use `agentbox outline <file>` before reading entire files.
2. Use `agentbox get-fn <file> <name>` to read specific functions.
3. Use `agentbox run "<command>"` for all builds, tests, and long commands.
4. Use `agentbox patch <file> --old "..." --new "..."` for code modifications.
```

---

## 📄 License

MIT License. Free for open-source and commercial use.
