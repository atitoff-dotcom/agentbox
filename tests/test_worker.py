# -*- coding: utf-8 -*-
"""
Tests for agentbox worker and client operations.
"""

import os
import sys
import json
import tempfile
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


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = config.get_config()
        self.assertIn("host", cfg)
        self.assertIn("cwd", cfg)

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
            finally:
                os.chdir(orig)


if __name__ == "__main__":
    unittest.main()
