# 🛡️ MANDATORY PROTOCOL: Remote & Local Execution (AgentBox)

> [!IMPORTANT]
> To eliminate token waste and prevent shell syntax errors, you MUST use `agentbox` for all remote (SSH) and project code operations.
> Direct raw execution of `cat`, `grep`, `find`, or streaming test runners is STRICTLY PROHIBITED.
>
> **🏠 ZERO-CONFIG LOCAL-FIRST GUARANTEE:**
> If there is NO `.agentbox.json` file in the project, `agentbox` automatically runs **100% locally** right in the current directory with zero configuration needed.
> Remote SSH execution is activated ONLY when a local `.agentbox.json` (or explicit `--host`) is present.
### 🚫 STRICTLY BANNED COMMANDS:
1. DO NOT read entire files: never use `cat <file>` or download full 200+ line files -> USE `agentbox outline <file>` or `agentbox view <file>`.
2. DO NOT search files using raw find/grep: never use `find .` or raw `grep` -> USE `agentbox tree`, `agentbox refs <symbol>`, or `agentbox grep "<query>"`.
3. DO NOT stream noisy builds or tests: never run raw `pytest`, `cargo build`, or `npm test` -> USE `agentbox test "<cmd>"` or `agentbox run "<cmd>"`.
4. DO NOT write files via raw shell redirection (`cat << 'EOF'`): bash escaping often breaks quotes and symbols -> USE `agentbox write`, `agentbox patch-lines`, or `agentbox patch`.
5. DO NOT dump raw git diff or log: never run raw `git diff` or `git log -p` -> USE `agentbox diff` or `agentbox git-log` / `agentbox git-view`.

---

### ⚡ PROTOCOL PRIORITY: MCP FIRST, CLI AS SAFE FALLBACK

1. **Native MCP Tools (`call_mcp_tool`, `ServerName: "agentbox"`):**
   When MCP is available, always prioritize `agentbox_*` MCP tools. JSON calls bypass the shell completely — eliminating quote escaping, regex parsing, and terminal encoding issues.
2. **PowerShell / CLI Fallback:**
   When running via PowerShell or SSH CLI, follow the PowerShell Safe Patterns below.

---

### ✅ MANDATORY AGENTBOX TOOLSET:

#### 1. Code Navigation & Slicing
* `agentbox outline <file> [files...]` — extracts AST classes and function signatures with line ranges (~120 tokens vs 3,000).
* `agentbox get-fn <file> <name>` — extracts exact target function, class, or `ClassName.method_name` definition.
* `agentbox find-fn <name> [path]` — scans project AST to locate where a function or class is defined across files.
* `agentbox refs <name> [path]` — finds all symbol references (imports, calls, attributes, inheritance) across the codebase.
* `agentbox view <file> --start N --end M` — views an exact line slice with 1-indexed numbers (supports negative start like `--start -50`).
* `agentbox view <file> --tail N` — views last N lines of a file or log in a single step (no need to check total lines first).

#### 2. Safe File Writing & Atomic Patching (Standard Workflow)
> [!TIP]
> **Preferred Editing Workflow:**
> 1. View target slice: `agentbox view <file> --start N --end M`
> 2. Replace lines: `agentbox patch-lines <file> --start N --end M ...` (far more resilient than matching long `--old` blocks).

* `agentbox patch-lines <file> --start N --end M --content "..."` — replaces 1-indexed line range `[N..M]` with auto-backup and AST check.
* `agentbox patch-lines <file> --start N --end M --base64 <b64>` — **100% immune to PowerShell quotes, variable expansion, and Cyrillic encoding bugs:**
  ```powershell
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(@'
  Любой сложный код с "кавычками", $переменными и кириллицей
  '@))
  agentbox patch-lines file.py --start 10 --end 20 --base64 $b64
  ```
* `agentbox write <file> --content "..." [--base64 <b64>]` — safely writes/overwrites file without quoting bugs.
* `agentbox patch <file> --old "..." --new "..."` — in-place atomic search-and-replace with auto-backup and AST check.
* `agentbox rollback <file>` — restores from `.agentbox/backups/`. All backups are kept outside the project tree to keep `git status` clean.

#### 3. Search, Silent Builds, Tests, Isolated Venv & Batching
* `agentbox grep "<query>" [path_or_file] [-F]` — fast search across directories OR a single file (case-insensitive regex or `-F` literal string).
* `agentbox test "<test_cmd>"` — silent test runner; suppresses passing tests and extracts high-signal failure tracebacks (auto-detects `.agentbox/venv` / `.venv`).
* `agentbox run "<build_cmd>"` — suppresses intermediate noisy terminal stream, buffering to log (auto-detects `.agentbox/venv` / `.venv`).
* `agentbox pip <args>` — runs `pip` inside isolated `.agentbox/venv` (auto-creating it if no virtualenv exists).
* `agentbox batch '<json_steps>'` / `agentbox batch --base64 <b64>` — executes multiple AgentBox actions in 1 turn:
  ```json
  [
    {"action": "view", "path": "examples/showcase/handlers.py", "start": 1, "end": 30},
    {"action": "patch_lines", "path": "examples/showcase/handlers.py", "start": 10, "end": 12, "content": "    return True\n"}
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
##### 📋 Verified Project Recipes (Auto-Memoized):
* `agentbox task test` — `python -m unittest discover -s tests`
* `agentbox task test:verbose` — `python -m unittest discover -s tests -v`
<!-- AGENTBOX_TASKS_END -->

### 🔄 Самообучение и рецепты (Task Auto-Memoization):
Если в процессе работы потребовалось подобрать сложную или неочевидную команду проекта (подключение к БД, вызов внутреннего скрипта, миграция, перезапуск сервиса) — после её успешного выполнения ОБЯЗАТЕЛЬНО сохрани её как рецепт:
`agentbox task add <name> "<command>"`
и используй в дальнейшем `agentbox task <name>`, чтобы не подбирать параметры повторно.
