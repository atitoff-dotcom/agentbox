# 🛡️ MANDATORY PROTOCOL: Remote & Local Execution (AgentBox)

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
