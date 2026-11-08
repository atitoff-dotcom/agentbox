# 📖 AgentBox CLI Reference Manual

AgentBox provides a unified, token-efficient command-line toolkit for AI coding assistants (**Cursor, Claude Code, Antigravity, Aider, Windsurf, Roo-Code**) working across local environments and remote SSH servers.

> [!TIP]
> **For AI Assistants:** You usually do not need to memorize these manually — run `agentbox rules` to generate `AGENTS.md` in your project, and your AI assistant will use these commands automatically!

---

## 📑 Table of Contents
1. [Global Flags & Options](#global-flags--options)
2. [Target Management (`agentbox target`)](#1-target-management-agentbox-target)
3. [Task Recipes (`agentbox task`)](#2-task-recipes-agentbox-task)
4. [AI Rules Generator (`agentbox rules`)](#3-ai-rules-generator-agentbox-rules)
5. [Code Navigation & AST Inspection](#4-code-navigation--ast-inspection)
6. [Safe File Operations & Atomic Patching](#5-safe-file-operations--atomic-patching)
7. [Silent Execution & Process Management](#6-silent-execution--process-management)
8. [Token-Efficient Git History & Changes](#7-token-efficient-git-history--changes)
9. [Two-Way Project Synchronization (`agentbox sync`)](#8-two-way-project-synchronization-agentbox-sync)
10. [Knowledge Graph & Architecture (`graphify`)](#9-knowledge-graph--architecture-graphify)
11. [Persistent Daemon Bridge (`agentbox daemon`)](#10-persistent-daemon-bridge-agentbox-daemon)

---

## Global Flags & Options

All commands accept global flags placed before or after the subcommand:

```bash
agentbox [-t <target>] [--host <user@host>] [--cwd <path>] [--venv <path>] [--no-daemon] <command>
```

| Flag | Description |
|---|---|
| `-t, --target <name>` | Select named target defined in `.agentbox.json` (e.g. `-t prod`, `-t dev`, or SSH string `user@host`). Defaults to active/default target or local. |
| `--host <user@host>` | Ad-hoc SSH target host for a single command. |
| `--cwd <path>` | Working directory on the target host. |
| `--venv <path>` | Explicit virtualenv path (automatically discovered if omitted). |
| `--no-daemon` | Bypass persistent daemon bridge and run direct SSH execution. |
| `--version` | Display version and exit. |

---

## 1. Target Management (`agentbox target`)

Manage local and remote execution targets stored in `.agentbox.json`.

```bash
# List all configured targets and see active target
agentbox target
# or: agentbox target list

# Add a remote SSH target
agentbox target add prod --host user@prod.server.com --cwd /var/www/app --venv /var/www/app/.venv

# Add a local target or staging server
agentbox target add local --cwd .
agentbox target add dev --host user@dev.server.com --cwd /home/user/dev

# Mark target as read-only (prevents write, patch, run, spawn, test, sync push)
agentbox target add staging --host user@staging --cwd /srv/app --readonly
# Or toggle read-only on an existing target:
agentbox target staging --readonly
agentbox target staging --off

# Set default target
agentbox target use prod

# Remove target
agentbox target rm dev
```

---

## 2. Task Recipes (`agentbox task`)

Save recurring project commands, migrations, or test commands in `.agentbox.json`. This eliminates complex shell quotes and Windows escaping issues.

```bash
# List available project tasks
agentbox task
# or: agentbox task list

# Run a task
agentbox task test
agentbox task build

# Pass extra arguments ({args} placeholder or appended to command)
agentbox task db "SELECT * FROM users LIMIT 10;"
agentbox task test:verbose -k "test_login"

# Add a new task recipe
agentbox task add test "pytest tests/ -v"
agentbox task add db "psql -U postgres -d mydb -c {args}"

# Associate task with a specific target
agentbox task add deploy "git pull && systemctl restart app" --target prod --desc "Deploy to production"

# Remove a task recipe
agentbox task rm test
```

---

## 3. AI Rules Generator (`agentbox rules`)

Generates or synchronizes anti-token-waste rules for AI coding assistants.

```bash
# Generate AGENTS.md (default for most modern agents)
agentbox rules

# Generate specific rule files:
agentbox rules --type agents    # AGENTS.md
agentbox rules --type cursor    # .cursorrules
agentbox rules --type claude    # CLAUDE.md
agentbox rules --type all       # Generates all three

# Sync target lists and recipes into existing rule files after config changes:
agentbox rules --sync
```

---

## 4. Code Navigation & AST Inspection

Extract definitions and signatures without downloading full multi-thousand-line files.

### `agentbox outline <file>`
Extracts only class, function, and method signatures with line numbers:
```bash
agentbox outline src/gateway.py
```
*Output (~120 tokens vs 3,000):*
```text
=== OUTLINE: gateway.py (350 lines) ===
  12-  45 | class GatewayConfig:
  48- 110 | async def handle_connection(reader, writer) -> bool
 115- 180 | def commit_flash_block(offset: int) -> None
```

### `agentbox get-fn <file> <name>`
Extracts the exact definition and body of a target function or `Class.method`:
```bash
agentbox get-fn src/gateway.py handle_connection
agentbox get-fn src/models.py User.validate_password
```

### `agentbox find-fn <name> [path] [--exact]`
Recursively scans project AST to locate where a function, method, or class is defined without noisy grep output:
```bash
agentbox find-fn get_bank
agentbox find-fn Bank --exact
```

### `agentbox refs <symbol> [path]`
Finds all occurrences and usages of a symbol across the project.

### `agentbox view <file> [--start N --end M] [--tail N]`
Displays an exact line slice with 1-indexed line numbers:
```bash
# Lines 48 to 65:
agentbox view src/gateway.py --start 48 --end 65

# Last 50 lines (supports logs or files):
agentbox view logs/app.log --tail 50
```

### `agentbox tree [path] [--depth N]`
Displays directory tree while filtering out `.git`, `node_modules`, `__pycache__`, `.venv`, and build artifacts:
```bash
agentbox tree --depth 2
```

### `agentbox grep "<query>" [path_or_file] [-F] [--max N] [-l]`
Fast, token-capped search across directories or a single file:
```bash
# Directory search:
agentbox grep "handle_packet" src/ --max 10

# Single file exact fixed-string match:
agentbox grep "tasks.list" src/App.svelte -F

# File names only:
agentbox grep "DatabaseError" src/ -l
```

---

## 5. Safe File Operations & Atomic Patching

All file edits support safe payloads (`--file <path>` or `--base64 <b64>`) to guarantee **zero shell escaping issues** on Windows PowerShell and SSH sessions.

### `agentbox patch-lines <file> --start N --end M [--file <path> | --base64 <b64> | --stdin]`
Replaces line range `[N..M]` with automatic AST syntax validation and automatic backup saved in `.agentbox/backups/`:
```bash
# Via temporary file:
agentbox patch-lines src/main.py --start 10 --end 15 --file /path/to/payload.py

# Via Base64 payload (immune to bash/PowerShell quote escaping):
agentbox patch-lines src/main.py --start 10 --end 15 --base64 <b64_string>
```

### `agentbox write <file> [--file <path> | --base64 <b64> | --stdin] [--append]`
Creates or overwrites a file safely:
```bash
agentbox write src/settings.py --file settings_temp.py
agentbox write logs/audit.log --base64 <b64_string> --append
```

### Batch Uploads with `agentbox write <src>:<dest> ...`
Batch transfers multiple files over a single connection in milliseconds:
```bash
agentbox write local_a.py:scratch/a.py local_b.py:scratch/b.py
```

### `agentbox cp <src> <dest>`
Copies files directly between targets, local workspace, or remote servers (`[target:]path`):
```bash
# Remote target to local:
agentbox cp prod:/var/log/app.log ./debug.log

# Local to remote target:
agentbox cp ./config.json prod:/etc/app/config.json

# Remote to remote (zero direct server-to-server connection required):
agentbox cp dev:/app/dist/app.whl prod:/var/www/dist/
```

### `agentbox patch <file> --old-file <old> --new-file <new>`
Replaces an exact code block with automatic syntax check and backup.

### `agentbox rollback <file>`
Restores previous file version from `.agentbox/backups/`:
```bash
agentbox rollback src/main.py
```

---

## 6. Silent Execution & Process Management

Suppress intermediate noise from commands, redirect stdout/stderr to local log files, and return only high-signal results.

### `agentbox run "<command>" [--tail N] [--timeout T] [--file <path>] [--base64 <b64>]`
Silently executes a command and prints execution time, exit code, and failure tail on error:
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
```

### `agentbox test "<test_command>" [--venv <path>] [--file <path>] [--base64 <b64>]`
Silences passing tests and extracts only actionable failure tracebacks. Supports Python (`pytest`, `unittest`), Rust (`cargo test`), and Frontend (`pnpm check`, `tsc`, `svelte-check`, `vitest`):
```bash
agentbox test "pytest tests/"
agentbox test "pnpm check"
```
*Output on failure:*
```text
FAILED [exit 1, 1.82s] Log: /tmp/agent_logs/test_491823.log
--- High-Signal Failure Traceback ---
>   assert result == 42
E   AssertionError: assert 100 == 42
tests/test_calc.py:15: AssertionError
```

### Detached Background Processes (`spawn`, `status`, `logs`, `kill`)
Runs long processes that survive SSH disconnections:
```bash
# Start background process
agentbox spawn "python3 train_model.py"
# Output: SPAWNED: task_id=bg_849201 pid=4215 log=/tmp/agent_logs/bg_849201.log

# Check status
agentbox status bg_849201
# Output: TASK: bg_849201 | Status: RUNNING | PID: 4215 | Runtime: 1m 24s

# View logs
agentbox logs bg_849201 -n 50
# Or live stream:
agentbox logs bg_849201 -f

# Terminate process
agentbox kill bg_849201
```

### `agentbox pip <args>`
Runs `pip` directly inside the target's virtual environment:
```bash
agentbox pip install fastapi uvicorn
agentbox pip list
```

---

## 7. Token-Efficient Git History & Changes

### `agentbox git-status [path]`
Compact status showing modified and untracked files with change counters (`+add, -del`):
```bash
agentbox git-status
```
*Output (~25 tokens vs 500+):*
```text
=== GIT STATUS: 2 changed files ===
  M   src/auth.py (+12, -3)
  ??  tests/test_auth_new.py
```

### `agentbox diff [path] [--rev <rev>] [--cached] [--max-lines N]`
Token-optimized diff that strips whitespace formatting noise (`-w`), excludes lockfiles (`package-lock.json`, `Cargo.lock`, `poetry.lock`), and caps lines:
```bash
agentbox diff src/auth.py
agentbox diff --rev HEAD~1
```

### `agentbox git-log [path] [-n N]`
Ultra-compact one-line commit history:
```bash
agentbox git-log -n 5
```

### `agentbox git-view <file> [rev] [--start N --end M]`
Extracts an exact slice of lines from any Git revision without downloading entire past files:
```bash
agentbox git-view src/auth.py HEAD~1 --start 20 --end 45
```

### `agentbox git-fn-history <file> <function_name> [-n N]`
Traces the AST modification history of a specific function across Git commits:
```bash
agentbox git-fn-history src/auth.py verify_jwt -n 3
```

---

## 8. Two-Way Project Synchronization (`agentbox sync`)

Bi-directional code sync between local workspace and remote servers using Rsync:

```bash
# Inspect sync status and pending file transfers
agentbox sync status -t prod

# Push local changes to remote target
agentbox sync push -t prod
agentbox sync push -t prod --dry-run
agentbox sync push -t prod --force

# Pull remote changes to local workspace
agentbox sync pull -t prod
```

---

## 9. Knowledge Graph & Architecture (`graphify`)

AgentBox integrates with `graphifyy` to build and navigate deep code knowledge graphs without blowing LLM context budgets:

```bash
# Install or upgrade graphify engine
agentbox graphify-install

# Build knowledge graph on target host
agentbox graphify-build
# Output: OK: Knowledge graph built in 4.2s (180 nodes, 420 edges). Location: graphify-out

# Query graph structure, relationships, and God nodes directly on host (~150 tokens)
agentbox graphify-query "Authentication and Token flow"

# Open interactive knowledge graph in local browser (Remote-Compute, Local-Artifact)
agentbox -t prod graphify-open
```

---

## 10. Persistent Daemon Bridge (`agentbox daemon`)

AgentBox maintains a transparent, persistent SSH connection with in-memory worker execution:
* **Sub-millisecond latency**: Commands execute in 2–5 ms instead of incurring 500–1500 ms SSH handshake overhead.
* **Auto-teardown**: Automatically terminates after 30 minutes of inactivity.
* **Fallback guarantee**: Automatically falls back to standard SSH IPC if background daemons are restricted.

```bash
# Inspect active daemon status
agentbox daemon status

# Stop daemon bridge manually
agentbox daemon stop
```
