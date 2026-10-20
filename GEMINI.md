# 🛡️ MANDATORY PROTOCOL: Local & Remote Execution via AgentBox CLI

> [!IMPORTANT]
> **CLI-ONLY EXECUTION PROTOCOL:**
> You MUST use `agentbox` CLI commands for ALL project code analysis, navigation, file editing, searches, and test executions.
> Direct raw execution of `cat`, `grep`, `find`, streaming test runners, or raw file redirections in PowerShell / bash is STRICTLY PROHIBITED.

---

### 🚫 STRICTLY BANNED RAW COMMANDS:
1. **DO NOT read entire files:** Never run `cat <file>`, `Get-Content <file>`, or download full files -> USE `agentbox outline <file>`, `agentbox get-fn <file> <name>`, or `agentbox view <file>`.
2. **DO NOT search using raw shell tools:** Never run `find .`, `grep -r`, `Select-String`, or `dir /s` -> USE `agentbox tree`, `agentbox refs <symbol>`, or `agentbox grep "<query>"`.
3. **DO NOT stream noisy builds or tests:** Never run raw `pytest`, `cargo test`, `npm test`, or `cargo build` directly -> USE `agentbox test "<cmd>"` or `agentbox run "<cmd>"`.
4. **DO NOT write files via shell redirection:** Never use `cat << 'EOF'`, `Set-Content`, or `echo > file` (shell escaping breaks quotes, variables, and encoding) -> USE `agentbox patch-lines`, `agentbox write`, or `agentbox patch`.
5. **DO NOT dump raw git diff or logs:** Never run raw `git diff` or `git log -p` -> USE `agentbox diff`, `agentbox git-log`, or `agentbox git-view`.

---

### ⚡ THE GOLDEN EDITING WORKFLOW: VIEW ➔ PATCH-LINES

> [!TIP]
> **Preferred 2-Step Safe Editing Standard:**
> 1. View target slice: `agentbox view <file> --start N --end M`
> 2. Replace lines atomically: `agentbox patch-lines <file> --start N --end M ...`
> This avoids fragile long search blocks, handles indentation perfectly, and runs automatic AST syntax validation.

---

### 🛡️ POWERSHELL & WINDOWS SAFE PATTERNS (100% IMMUNITY TO BUGS)

#### 1. The `--base64` Pattern (Recommended for any non-trivial code):
PowerShell often breaks on quotes (`"`, `'`), backticks, dollar signs (`$var` variable expansion), and Cyrillic text in pipelines.
Base64 solves this completely:
```powershell
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(@'
Любой сложный код: с кавычками " ' ` , переменными $variable и кириллицей
'@))
agentbox patch-lines path/to/file.py --start 10 --end 20 --base64 $b64
```
*(Also supported on `agentbox write <file> --base64 $b64` and `agentbox batch --base64 $b64`)*

#### 2. Console UTF-8 Setup (if using `--stdin` pipelines):
If piping text into `--stdin`, always ensure PowerShell uses UTF-8:
```powershell
$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
@'
текст
'@ | agentbox patch-lines file.py --start 10 --end 20 --stdin
```

---

### 🧰 COMPLETE AGENTBOX CLI TOOLSET:

#### 1. Code Navigation & Slicing
* `agentbox outline <file> [files...]` — extracts AST classes and function signatures with line ranges (~120 tokens vs 3,000).
* `agentbox get-fn <file> <name>` — extracts exact target function, class, or `ClassName.method_name` definition with line numbers.
* `agentbox find-fn <name> [path]` — scans project AST to locate where a function or class is defined across files.
* `agentbox refs <name> [path]` — finds all symbol references (imports, calls, attributes, inheritance) across the codebase.
* `agentbox view <file> --start N --end M` — views an exact line slice with 1-indexed line numbers (supports negative start like `--start -50`).
* `agentbox view <file> --tail N` — views last N lines of a file or log in a single step (no need to check total line count first).

#### 2. Safe File Writing & Atomic Patching
* `agentbox patch-lines <file> --start N --end M --content "..."` — replaces 1-indexed line range `[N..M]` with auto-backup and AST check.
* `agentbox patch-lines <file> --start N --end M --base64 <b64>` — safe Base64 line replacement (immune to PowerShell bugs).
* `agentbox write <file> --content "..." [--base64 <b64>] [--append]` — safely writes or appends content to file.
* `agentbox patch <file> --old "..." --new "..."` — in-place atomic search-and-replace with auto-backup and AST check.
* `agentbox rollback <file>` — restores from `.agentbox/backups/`. All backups are kept outside the project tree to keep `git status` clean.

#### 3. Search, Silent Builds, Tests, Isolated Venv & Batching
* `agentbox grep "<query>" [path_or_file] [-F]` — fast search across directories OR a single file (case-insensitive regex or `-F` literal string).
* `agentbox tree [path] [--depth N]` — compact directory tree ignoring build artifacts and virtualenvs.
* `agentbox test "<test_cmd>"` — silent test runner; suppresses passing tests and extracts high-signal failure tracebacks (auto-detects `.agentbox/venv` / `.venv`).
* `agentbox run "<build_cmd>"` — suppresses intermediate noisy terminal stream, buffering to log (auto-detects `.agentbox/venv` / `.venv`).
* `agentbox pip <args>` — runs `pip` inside isolated `.agentbox/venv` (auto-creating it if no virtualenv exists).
* `agentbox batch '<json_steps>'` / `agentbox batch --base64 <b64>` — executes multiple actions in 1 turn:
  ```json
  [
    {"action": "view", "path": "examples/showcase/handlers.py", "start": 1, "end": 30},
    {"action": "patch_lines", "path": "examples/showcase/handlers.py", "start": 10, "end": 12, "content": "    return True\n"}
  ]
  ```
* `agentbox stats` — displays token savings and execution statistics dashboard.
* `agentbox spawn "<cmd>"` / `agentbox status <id>` / `agentbox logs <id> -f` / `agentbox kill <id>` — detached background tasks.

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
* `agentbox task <name> [args]` — executes saved task with optional argument substitution (`{args}` or appended).
* `agentbox task add <name> "<cmd>"` — saves or updates a task recipe in project `.agentbox.json`.
* `agentbox task rm <name>` — removes a task from `.agentbox.json`.

<!-- AGENTBOX_TASKS_START -->
##### 📋 Verified Project Recipes (Auto-Memoized):
* `agentbox task test` — `python -m unittest discover -s tests`
* `agentbox task test:verbose` — `python -m unittest discover -s tests -v`
<!-- AGENTBOX_TASKS_END -->

### 🔄 Рецепты и самообучение (Task Auto-Memoization):
Если в процессе работы подобрана сложная или важная команда проекта (тесты, линтеры, миграции, запуск сервиса) — сохрани её как рецепт:
`agentbox task add <name> "<command>"`
и используй в дальнейшем `agentbox task <name>`, чтобы не подбирать параметры повторно.
