# -*- coding: utf-8 -*-
"""
Tests for agentbox worker and client operations.
"""

import os
import sys
import json
import tempfile
import subprocess
import unittest
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import worker
from agentbox import config


class TestWorker(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_patch_and_rollback(self):
        sample = self.dir_path / "sample.py"
        sample.write_text("def hello():\n    return 42\n", encoding="utf-8")

        # Patch
        worker.cmd_patch(str(sample), "return 42", "return 100")
        self.assertIn("return 100", sample.read_text(encoding="utf-8"))
        self.assertTrue(sample.with_suffix(".py.bak").is_file())

        # Rollback
        worker.cmd_rollback(str(sample))
        self.assertIn("return 42", sample.read_text(encoding="utf-8"))
        self.assertFalse(sample.with_suffix(".py.bak").is_file())

    def test_patch_duplicate_error(self):
        sample = self.dir_path / "dup.txt"
        sample.write_text("foo\nfoo\n", encoding="utf-8")

        # Must exit with error because 'foo' is not unique
        with self.assertRaises(SystemExit):
            worker.cmd_patch(str(sample), "foo", "bar", replace_all=False)

    def test_run_success(self):
        # Silent run echo command
        worker.cmd_run("echo 'AgentBox Test'", cwd=str(self.dir_path), tail=5)

    def test_run_failure(self):
        # Exits with non-zero on failure
        with self.assertRaises(SystemExit):
            worker.cmd_run("exit 42", cwd=str(self.dir_path), tail=5)

    def test_grep(self):
        f = self.dir_path / "code.py"
        f.write_text("def find_me_secret():\n    pass\n", encoding="utf-8")
        # Should not raise exception
        worker.cmd_grep("find_me_secret", path=str(self.dir_path), max_results=10)

    def test_logs_read(self):
        # Create a dummy task log and meta
        log_dir = Path("/tmp/agent_logs") if os.name != "nt" else Path(os.environ.get("TEMP", ".")) / "agent_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        task_id = "test_task_999"
        log_file = log_dir / f"{task_id}.log"
        log_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

        try:
            worker.cmd_logs(task_id, lines=2, follow=False)
        finally:
            if log_file.is_file():
                log_file.unlink()

    def test_write_and_append(self):
        new_file = self.dir_path / "created.txt"
        worker.cmd_write(str(new_file), content="Hello AgentBox\n")
        self.assertEqual(new_file.read_text(encoding="utf-8"), "Hello AgentBox\n")

        # Test append
        worker.cmd_write(str(new_file), content="Second Line\n", append=True)
        self.assertEqual(new_file.read_text(encoding="utf-8"), "Hello AgentBox\nSecond Line\n")

    def test_test_runner_success(self):
        # A test command that succeeds
        worker.cmd_test("python -c \"print('42 passed')\"", cwd=str(self.dir_path))

    def test_test_runner_failure(self):
        # A test command that fails
        with self.assertRaises(SystemExit):
            worker.cmd_test("python -c \"import sys; print('FAILURES: test_foo assert False'); sys.exit(1)\"", cwd=str(self.dir_path))

    def test_graphify_query_mock(self):
        # Create a mock graphify-out/graph.json
        out_dir = self.dir_path / "graphify-out"
        out_dir.mkdir(parents=True, exist_ok=True)
        graph_data = {
            "nodes": [
                {"id": "AuthModule", "label": "AuthModule", "type": "class", "source_location": "auth.py:10"},
                {"id": "UserDB", "label": "UserDB", "type": "class", "source_location": "db.py:20"}
            ],
            "edges": [
                {"source": "AuthModule", "target": "UserDB", "relation": "queries"}
            ]
        }
        (out_dir / "graph.json").write_text(json.dumps(graph_data), encoding="utf-8")

        # Query should match and execute without errors
        worker.cmd_graphify_query("AuthModule", path=str(self.dir_path))

    def test_venv_auto_detect_cwd(self):
        venv_dir = self.dir_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

        found = worker.find_virtualenv(self.dir_path)
        self.assertIsNotNone(found)
        self.assertEqual(found.resolve(), venv_dir.resolve())

    def test_venv_auto_detect_parent(self):
        venv_dir = self.dir_path / "venv"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

        child_dir = self.dir_path / "services" / "api"
        child_dir.mkdir(parents=True)

        found = worker.find_virtualenv(child_dir)
        self.assertIsNotNone(found)
        self.assertEqual(found.resolve(), venv_dir.resolve())

    def test_venv_explicit(self):
        custom_venv = self.dir_path / "custom_env"
        (custom_venv / "bin").mkdir(parents=True)
        (custom_venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

        found = worker.find_virtualenv(self.dir_path, explicit_venv=str(custom_venv))
        self.assertIsNotNone(found)
        self.assertEqual(found.resolve(), custom_venv.resolve())

    def test_prepare_env_for_cmd(self):
        venv_dir = self.dir_path / ".venv"
        bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
        bin_dir.mkdir(parents=True)
        (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

        env, resolved_venv = worker.prepare_env_for_cmd(self.dir_path)
        self.assertIsNotNone(resolved_venv)
        self.assertEqual(resolved_venv.resolve(), venv_dir.resolve())
        self.assertEqual(env["VIRTUAL_ENV"], str(venv_dir))
        self.assertTrue(env["PATH"].startswith(str(bin_dir)))


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = config.get_config()
        self.assertIn("host", cfg)
        self.assertIn("cwd", cfg)
        self.assertIn("venv", cfg)

    def test_generate_rules(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            orig = os.getcwd()
            try:
                os.chdir(td)
                config.generate_rules("all")
                self.assertTrue(Path(".cursorrules").is_file())
                self.assertTrue(Path("AGENTS.md").is_file())
                self.assertTrue(Path("CLAUDE.md").is_file())
                content = Path("AGENTS.md").read_text(encoding="utf-8")
                self.assertIn("MANDATORY PROTOCOL", content)
                self.assertIn("agentbox", content)
                self.assertIn("agentbox task", content)
                self.assertIn("Task Auto-Memoization", content)
            finally:
                os.chdir(orig)


class TestCli(unittest.TestCase):
    def test_cli_venv_parsing(self):
        from agentbox.cli import create_parser
        cfg = {"host": "", "cwd": "", "venv": ""}
        parser = create_parser(cfg)

        # 1. Global --venv before subcommand
        args1 = parser.parse_args(["--venv", "/opt/venv", "test", "pytest"])
        v1 = getattr(args1, "cmd_venv", None) or getattr(args1, "venv", None)
        self.assertEqual(v1, "/opt/venv")

        # 2. Subcommand --venv after subcommand
        args2 = parser.parse_args(["test", "pytest", "--venv", "/opt/sub_venv"])
        v2 = getattr(args2, "cmd_venv", None) or getattr(args2, "venv", None)
        self.assertEqual(v2, "/opt/sub_venv")

        # 3. Subcommand overrides global
        args3 = parser.parse_args(["--venv", "/opt/global", "test", "pytest", "--venv", "/opt/local"])
        v3 = getattr(args3, "cmd_venv", None) or getattr(args3, "venv", None)
        self.assertEqual(v3, "/opt/local")

    def test_cli_git_parsing(self):
        from agentbox.cli import create_parser
        cfg = {"host": "", "cwd": "", "venv": ""}
        parser = create_parser(cfg)

        a1 = parser.parse_args(["git-status"])
        self.assertEqual(a1.cmd, "git-status")

        a2 = parser.parse_args(["diff", "--rev", "HEAD~1", "--cached", "--max-lines", "50"])
        self.assertEqual(a2.cmd, "diff")
        self.assertEqual(a2.rev, "HEAD~1")
        self.assertTrue(a2.cached)
        self.assertEqual(a2.max_lines, 50)

        a3 = parser.parse_args(["git-log", "-n", "10"])
        self.assertEqual(a3.cmd, "git-log")
        self.assertEqual(a3.limit, 10)

        a4 = parser.parse_args(["git-view", "src/main.py", "HEAD~2", "--start", "5", "--end", "20"])
        self.assertEqual(a4.cmd, "git-view")
        self.assertEqual(a4.path, "src/main.py")
        self.assertEqual(a4.rev, "HEAD~2")
        self.assertEqual(a4.start, 5)
        self.assertEqual(a4.end, 20)

        a5 = parser.parse_args(["git-fn-history", "src/main.py", "my_func", "-n", "4"])
        self.assertEqual(a5.cmd, "git-fn-history")
        self.assertEqual(a5.path, "src/main.py")
        self.assertEqual(a5.name, "my_func")
        self.assertEqual(a5.limit, 4)


class TestGit(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.test_dir.name)
        subprocess.run(["git", "init"], cwd=str(self.repo_dir), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@agentbox.dev"], cwd=str(self.repo_dir), capture_output=True)
        subprocess.run(["git", "config", "user.name", "AgentBox Tester"], cwd=str(self.repo_dir), capture_output=True)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_git_operations(self):
        # 1. Clean repo status
        worker.cmd_git_status(str(self.repo_dir))

        # 2. Add and commit initial file
        f = self.repo_dir / "app.py"
        f.write_text("def hello():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=str(self.repo_dir), capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(self.repo_dir), capture_output=True)

        # 3. Modify file and add noisy lockfile
        f.write_text("def hello():\n    return 42\n", encoding="utf-8")
        lock = self.repo_dir / "package-lock.json"
        lock.write_text('{"lock": "noise"}', encoding="utf-8")

        # Test git-status
        worker.cmd_git_status(str(self.repo_dir))

        # Test diff (ignores package-lock.json)
        worker.cmd_diff(path=str(self.repo_dir))

        # Test git-log
        worker.cmd_git_log(path=str(self.repo_dir), limit=2)

        # Test git-view
        worker.cmd_git_view(path=str(f), rev="HEAD", start=1, end=2)

        # Test git-fn-history
        worker.cmd_git_fn_history(path=str(f), name="hello", limit=2)


class TestFrontendCheckers(unittest.TestCase):
    def test_extract_svelte_check(self):
        sample = [
            "====================================",
            "Loading svelte-check in workspace: /project",
            "Getting Svelte diagnostics...",
            "",
            "/project/src/lib/Counter.svelte:14:12",
            "Error: Type 'number' is not assignable to type 'string'. (ts)",
            "    let count: string = $state(0);",
            "",
            "/project/src/lib/Header.svelte:45:5",
            "Warn: A11y: <img> element should have an alt attribute (a11y-missing-attribute)",
            "",
            "====================================",
            "svelte-check found 1 error and 1 warning"
        ]
        res = worker._extract_test_failures(sample, max_lines=30)
        self.assertIn("Error: Type 'number'", res)
        self.assertIn("let count: string = $state(0);", res)
        self.assertIn("svelte-check found 1 error and 1 warning", res)
        self.assertNotIn("Loading svelte-check", res)
        self.assertNotIn("a11y-missing-attribute", res)

    def test_extract_tsc(self):
        sample = [
            "src/routes/+page.svelte.ts:12:5 - error TS2322: Type 'number' is not assignable to type 'string'.",
            "src/api/auth.ts:45:10 - error TS2339: Property 'token' does not exist on type 'UserSession'.",
            "",
            "Found 2 errors in 2 files."
        ]
        res = worker._extract_test_failures(sample, max_lines=30)
        self.assertIn("error TS2322", res)
        self.assertIn("error TS2339", res)
        self.assertIn("Found 2 errors", res)

    def test_extract_eslint(self):
        sample = [
            "/project/src/lib/utils.ts",
            "  12:5  error  'result' is defined but never used  @typescript-eslint/no-unused-vars",
            "  18:1  warning  Unexpected console statement      no-console",
            "",
            "✖ 2 problems (1 error, 1 warning)"
        ]
        res = worker._extract_test_failures(sample, max_lines=30)
        self.assertIn("error  'result' is defined", res)
        self.assertIn("✖ 2 problems", res)
        self.assertNotIn("Unexpected console statement", res)

    def test_extract_vitest(self):
        sample = [
            " ✓ src/Header.test.ts (2)",
            " ❯ src/Counter.test.ts (1)",
            "   × Counter > increments count",
            "     → expected 1 to be 2",
            "",
            " FAIL  src/Counter.test.ts > Counter > increments count",
            "AssertionError: expected 1 to be 2",
            " ❯ src/Counter.test.ts:15:20",
            "",
            " Test Files  1 failed | 1 passed (2)",
            "      Tests  1 failed | 5 passed (6)"
        ]
        res = worker._extract_test_failures(sample, max_lines=30)
        self.assertIn("FAIL  src/Counter.test.ts", res)
        self.assertIn("AssertionError: expected 1 to be 2", res)
        self.assertIn("Test Files  1 failed", res)
        self.assertNotIn("✓ src/Header.test.ts", res)


if __name__ == "__main__":
    unittest.main()

