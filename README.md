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

## 🛠️ Quickstart: 3-Step Setup for Any Remote Project

Follow this simple flow when starting a local workspace to work on an existing remote Linux server:

### Step 1: Install `ai-agentbox` locally
```bash
pip install ai-agentbox
```

### Step 2: Bind Remote Server & Generate AI Rules
Run these two commands in your local project root:
```bash
# 1. Bind target SSH host, remote project path, and optional virtualenv:
agentbox config --set-host user@remote-server --set-cwd /home/user/my_project
# Optional: explicitly set virtualenv path (otherwise .venv/venv is auto-detected!)
agentbox config --set-venv /home/user/my_project/.venv

# 2. Automatically generate strict anti-token-waste rules for your AI agent:
agentbox init-rules
```
*`init-rules` creates `.cursorrules`, `AGENTS.md`, and `CLAUDE.md`, strictly prohibiting the AI agent from using raw `cat`/`grep`/`pytest` over SSH and forcing `agentbox`.*

### Step 3: Let AI Agent Work (Zero Setup on Remote Server!)
Give any task to your AI assistant (**Cursor, Claude Code, Antigravity, Windsurf, Roo-Code**).

When the agent executes any `agentbox` command (e.g. `agentbox tree` or `agentbox outline`):
* AgentBox **automatically connects via SSH** to your Linux server.
* Checks if `~/.agentbox_worker.py` exists and matches SHA-256 hash.
* **Auto-deploys the zero-dependency worker to the server in milliseconds**.
* You **never** have to log in to the remote server or install anything there manually!

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

#### `agentbox test "<test_command>" [--venv <path>]`
Token-optimized test & type runner that suppresses passing tests and noise, extracting only high-signal failure tracebacks.
Supports **Python** (`pytest`, `unittest`), **Rust** (`cargo test`), and **Frontend** (`svelte-check`, `tsc`, `eslint`, `vitest`, `pnpm check`).

> [!TIP]
> **Frontend & Svelte 5 / TypeScript Support**: Running `agentbox test "pnpm check"` or `agentbox test "pnpm svelte-check"` automatically strips noisy compilation banners and stylistic warnings, highlighting only real type errors, file locations, and failure code snippets!

> [!TIP]
> **Automatic Virtualenv Detection**: AgentBox automatically checks for `.venv` or `venv` in your working directory and parent project directories, prefixing `PATH="$VENV/bin:$PATH"` so tools like `pytest` and `granian` work instantly without full paths! You can also pass `--venv /path/to/venv` or set it in config (`agentbox config --set-venv /path`).

```bash
# Automatically finds .venv / venv:
agentbox test "pytest tests/"

# Or with explicit virtualenv:
agentbox test "pytest tests/" --venv /home/alex/pl3_2/.venv
```
*Output on success:*
```text
OK [tests passed in 1.45s] (12 passed) Log: /tmp/agent_logs/test_491823.log
```
*Output on failure (extracts traceback, saving up to 95% tokens):*
```text
FAILED [exit 1, 1.82s] Log: /tmp/agent_logs/test_491823.log
--- High-Signal Failure Traceback ---
>   assert result == 42
E   AssertionError: assert 100 == 42
tests/test_calc.py:15: AssertionError
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

### 3. File Operations & Safe Atomic Patching

#### `agentbox write <file> [--content "..."] [--append]`
Safely creates or appends to a file without any bash quote escaping issues (supports stdin streaming):
```bash
agentbox write src/settings.py --content 'DEBUG = True\nPORT = 8080'
# Or via pipeline:
cat config.json | agentbox write config.json
```

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

### 5. Knowledge Graph & Architecture (`graphify`)

AgentBox integrates with `graphifyy` to build and navigate deep code knowledge graphs without blowing LLM context budgets:

#### `agentbox graphify-install [--upgrade]`
Silently ensures `graphifyy` is installed on the local machine or remote SSH server:
```bash
agentbox graphify-install
```

#### `agentbox graphify-build [path] [--deep]`
Silently builds a navigable knowledge graph on the target host:
```bash
agentbox graphify-build
# Output: OK: Knowledge graph built in 4.2s (180 nodes, 420 edges). Location: graphify-out
```

#### `agentbox graphify-query "<question>"`
Queries graph structure, relationships, and God nodes directly on the host, returning token-capped answers (~150 tokens instead of dumping megabytes of JSON):
```bash
agentbox graphify-query "Authentication and Token flow"
```

---

### 6. Token-Efficient Git History & Changes

Agents waste thousands of tokens downloading full files just to see what changed or inspect past implementations:

#### `agentbox git-status [path]`
Compact status showing only modified and untracked files with `(+add, -del)` count in a few clean lines:
```bash
agentbox git-status
```
*Output (~25 tokens vs 500+):*
```text
=== GIT STATUS: 3 changed files ===
  M   src/auth.py (+12, -3)
  M   src/config.py (+2, -0)
  ??  tests/test_auth_new.py
```

#### `agentbox diff [path] [--rev <rev>] [--cached] [--max-lines N]`
Token-optimized diff that automatically ignores lockfiles (`package-lock.json`, `poetry.lock`, `Cargo.lock`), strips formatting whitespace noise (`-w`), and caps output to avoid context overflow:
```bash
agentbox diff src/auth.py
# Or compare against a commit:
agentbox diff --rev HEAD~1
```

#### `agentbox git-log [path] [-n N]`
Ultra-compact one-line commit history:
```bash
agentbox git-log -n 5
```
*Output (~30 tokens vs 2,000+):*
```text
=== GIT LOG: repository (last 3 commits) ===
df71336 (2 hours ago) docs: add AGENT.md, AGENTS.md <atitoff>
0508bc0 (3 hours ago) fix: update project URLs <atitoff>
2937539 (4 hours ago) feat: initial commit <atitoff>
```

#### `agentbox git-view <file> [rev] [--start N --end M]`
Extracts an exact slice of lines from any Git revision without downloading the entire 800-line historical file:
```bash
agentbox git-view src/auth.py HEAD~1 --start 20 --end 45
```

#### `agentbox git-fn-history <file> <function_name> [-n N]`
Traces the AST modification history of a specific function across Git commits:
```bash
agentbox git-fn-history src/auth.py verify_jwt -n 3
```

---

## 🤖 Enforce AI Agents to use AgentBox (`agentbox init-rules`)

Generate strict anti-token-waste rules for AI assistants (**Cursor, Claude Code, Antigravity, Windsurf, Roo-Code**) with a single command:

```bash
agentbox init-rules
# Output: OK: Created AI rule files: .cursorrules, AGENTS.md, CLAUDE.md
```

Or target a specific environment:
```bash
agentbox init-rules --type cursor   # generates .cursorrules
agentbox init-rules --type agents   # generates AGENTS.md
agentbox init-rules --type claude   # generates CLAUDE.md
```

This installs strict rules prohibiting the AI assistant from running noisy `cat`, `grep`, `find`, or raw test commands over SSH, forcing the use of token-efficient `agentbox` commands.

---

## 📄 License

MIT License. Free for open-source and commercial use.
