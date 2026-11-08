# 🛡️ MANDATORY PROTOCOL: Local & Remote Execution via AgentBox CLI

> [!IMPORTANT]
> **NEED-TO-KNOW & ZERO-ESCAPING PROTOCOL:**
> - DO NOT read or edit `.agentbox.json` directly (Need-to-Know: use `-t <target>` and `agentbox task`).
> - NEVER read full files, run raw grep/find, cat, or dump noisy git diffs/builds. Use `agentbox` tools.
> - **Zero-Escaping on Windows:** NEVER pass code or scripts inside raw CLI quotes (`"..."`). Prefer `agentbox task <name> [args]`, `--file` (write via native `write_file` -> pass path), or `--base64`.
> - **Multi-host:** Add `-t <target>` to run on configured target. Without `-t`, runs 100% locally.
> - **Read-Only Targets:** Targets marked `(read-only)` STRICTLY forbid any modifications (`write`, `patch`, `sync push`, `pip`) and code executions (`run`, `py`, `spawn`, `test`, `task`). Use ONLY Inspect & Navigate tools (`view`, `outline`, `get-fn`, `find-fn`, `refs`, `tree`, `grep`, `diff`, `git-*`, `sync pull`, `graphify-query`).

<!-- AGENTBOX_TARGETS_START -->
##### 🌐 Available Execution Targets:
* `local` (active)
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
##### 📋 Verified Project Recipes (Auto-Memoized):
* `agentbox task build` — `python -m build`
* `agentbox task test` — `python -m unittest discover -s tests`
* `agentbox task test:verbose` — `python -m unittest discover -s tests -v`
<!-- AGENTBOX_TASKS_END -->

### ⚡ Pre-Flight Checklist before execution:
1. Zero-Escaping on Windows: Did you use `agentbox py --base64`, `task`, or `--file` instead of raw shell quotes?
2. Context Guard: Did you use `outline` / `get-fn` / `py` instead of dumping full files into context?
3. Remote Target: Did you pass `-t <target>` if the operation should run on a remote server?
4. Read-Only Guard: Is the target marked `read-only`? If yes, use ONLY Inspect & Navigate tools (no edits/runs/push).
