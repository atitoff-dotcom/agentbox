# -*- coding: utf-8 -*-
"""
Tests for agentbox project tasks and recipes.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from unittest.mock import patch

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import config
from agentbox import cli


class TestTasks(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)
        # Point config files to temp dir
        self.orig_local_file = config.LOCAL_CONFIG_FILE
        self.orig_global_file = config.GLOBAL_CONFIG_FILE
        self.orig_global_dir = config.GLOBAL_CONFIG_DIR

        config.LOCAL_CONFIG_FILE = Path(".agentbox.json")
        config.GLOBAL_CONFIG_DIR = Path(self.test_dir.name) / ".agentbox"
        config.GLOBAL_CONFIG_FILE = config.GLOBAL_CONFIG_DIR / "config.json"

    def tearDown(self):
        config.LOCAL_CONFIG_FILE = self.orig_local_file
        config.GLOBAL_CONFIG_FILE = self.orig_global_file
        config.GLOBAL_CONFIG_DIR = self.orig_global_dir
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    def test_add_and_get_tasks(self):
        self.assertEqual(config.get_tasks(), {})

        config.add_task("migrate", "alembic upgrade head")
        tasks = config.get_tasks()
        self.assertEqual(tasks, {"migrate": "alembic upgrade head"})

        # Add second task
        config.add_task("db", "psql -U test {args}")
        tasks = config.get_tasks()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks["db"], "psql -U test {args}")

        # Verify .agentbox.json content
        data = json.loads(Path(".agentbox.json").read_text(encoding="utf-8"))
        self.assertIn("tasks", data)
        self.assertEqual(data["tasks"]["migrate"], "alembic upgrade head")

    def test_global_tasks_fallback(self):
        config.GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config.GLOBAL_CONFIG_FILE.write_text(json.dumps({"tasks": {"global-check": "pytest"}}), encoding="utf-8")
        tasks = config.get_tasks()
        self.assertEqual(tasks.get("global-check"), "pytest")

        # Local task overrides global task
        config.add_task("global-check", "pytest -v")
        tasks = config.get_tasks()
        self.assertEqual(tasks.get("global-check"), "pytest -v")

    def test_remove_task(self):
        config.add_task("db", "psql -U test")
        self.assertTrue(config.remove_task("db"))
        self.assertFalse(config.remove_task("nonexistent"))
        self.assertEqual(config.get_tasks(), {})

    def test_cli_task_list_empty(self):
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["task"])
            self.assertEqual(ret, 0)
            self.assertIn("No tasks defined", out.getvalue())

    def test_cli_task_add_and_list(self):
        # 1. Add task via CLI
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["task", "add", "migrate", "alembic upgrade head"])
            self.assertEqual(ret, 0)
            self.assertIn("OK: Task 'migrate' saved to .agentbox.json", out.getvalue())

        # 2. Add task with {args}
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["task", "add", "db", "psql -U user -c {args}"])
            self.assertEqual(ret, 0)
            self.assertIn("OK: Task 'db' saved to .agentbox.json", out.getvalue())

        # 3. List tasks via 'agentbox task'
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["task"])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("PROJECT TASKS (2)", output)
            self.assertIn("migrate", output)
            self.assertIn("alembic upgrade head", output)
            self.assertIn("db", output)

        # 4. List tasks via 'agentbox task list'
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["task", "list"])
            self.assertEqual(ret, 0)
            self.assertIn("PROJECT TASKS (2)", out.getvalue())

    def test_cli_task_remove(self):
        config.add_task("foo", "echo bar")
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["task", "rm", "foo"])
            self.assertEqual(ret, 0)
            self.assertIn("OK: Task 'foo' removed from .agentbox.json", out.getvalue())

        self.assertEqual(config.get_tasks(), {})

        # Removing again should fail
        with patch("sys.stderr", new=StringIO()) as err:
            ret = cli.main(["task", "remove", "foo"])
            self.assertEqual(ret, 1)
            self.assertIn("not found", err.getvalue())

    def test_cli_task_execution_without_args(self):
        config.add_task("test-echo", "echo 'recipe executed'")
        with patch("agentbox.cli.execute_action") as mock_exec:
            mock_exec.return_value = 0
            ret = cli.main(["task", "test-echo"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once()
            call_action = mock_exec.call_args[0][2]
            call_payload = mock_exec.call_args[0][3]
            self.assertEqual(call_action, "run")
            self.assertEqual(call_payload["cmd"], "echo 'recipe executed'")

    def test_cli_task_execution_with_placeholder_args(self):
        config.add_task("query", "psql -d mydb -c {args}")
        with patch("agentbox.cli.execute_action") as mock_exec:
            mock_exec.return_value = 0
            ret = cli.main(["task", "query", "SELECT", "1;"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once()
            call_payload = mock_exec.call_args[0][3]
            self.assertEqual(call_payload["cmd"], "psql -d mydb -c SELECT 1;")

    def test_cli_task_execution_with_dollar_at_placeholder(self):
        config.add_task("run-script", "python script.py $@")
        with patch("agentbox.cli.execute_action") as mock_exec:
            mock_exec.return_value = 0
            ret = cli.main(["task", "run-script", "--verbose", "--fast"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once()
            call_payload = mock_exec.call_args[0][3]
            self.assertEqual(call_payload["cmd"], "python script.py --verbose --fast")

    def test_cli_task_execution_with_appended_args(self):
        config.add_task("lint", "flake8")
        with patch("agentbox.cli.execute_action") as mock_exec:
            mock_exec.return_value = 0
            ret = cli.main(["task", "lint", "src/"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once()
            call_payload = mock_exec.call_args[0][3]
            self.assertEqual(call_payload["cmd"], "flake8 src/")

    def test_cli_task_not_found(self):
        with patch("sys.stderr", new=StringIO()) as err:
            ret = cli.main(["task", "unknown_task"])
            self.assertEqual(ret, 1)
            self.assertIn("ERROR: Task 'unknown_task' not found", err.getvalue())

    def test_sync_rules_with_tasks(self):
        # Create dummy AGENTS.md and .cursorrules
        agents_file = Path("AGENTS.md")
        agents_file.write_text(config.RULE_TEMPLATE, encoding="utf-8")
        cursor_file = Path(".cursorrules")
        cursor_file.write_text(config.RULE_TEMPLATE, encoding="utf-8")

        # Add a task
        config.add_task("db", "psql -U user -d db {args}")

        # Check that both files were automatically injected with the new task
        agents_content = agents_file.read_text(encoding="utf-8")
        self.assertIn("agentbox task db", agents_content)
        self.assertIn("psql -U user -d db {args}", agents_content)

        cursor_content = cursor_file.read_text(encoding="utf-8")
        self.assertIn("agentbox task db", cursor_content)

        # Remove task
        config.remove_task("db")
        updated_agents = agents_file.read_text(encoding="utf-8")
        self.assertNotIn("agentbox task db", updated_agents)


if __name__ == "__main__":
    unittest.main()
