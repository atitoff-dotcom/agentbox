# -*- coding: utf-8 -*-
"""
Tests for agentbox multi-target and SSH management.
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from unittest.mock import patch, MagicMock

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import config
from agentbox import cli


class TestTargets(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)

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

    def test_add_and_get_targets(self):
        self.assertEqual(config.get_targets(), {})
        self.assertEqual(config.get_default_target_name(), "")

        # Add target
        config.add_target("dev", host="user@dev-server", cwd="/opt/dev", venv="/opt/dev/venv")
        targets = config.get_targets()
        self.assertIn("dev", targets)
        self.assertEqual(targets["dev"]["host"], "user@dev-server")
        self.assertEqual(targets["dev"]["cwd"], "/opt/dev")
        self.assertEqual(targets["dev"]["venv"], "/opt/dev/venv")
        # First added target becomes default automatically
        self.assertEqual(config.get_default_target_name(), "dev")

        # Add second target with is_default=True
        config.add_target("prod", host="admin@prod-server", cwd="/var/www/app", is_default=True)
        targets = config.get_targets()
        self.assertIn("prod", targets)
        self.assertEqual(config.get_default_target_name(), "prod")

    def test_set_default_target_and_remove(self):
        config.add_target("stage", host="user@stage")
        config.add_target("prod", host="user@prod")

        self.assertTrue(config.set_default_target("prod"))
        self.assertEqual(config.get_default_target_name(), "prod")

        # Non-existent target fails
        self.assertFalse(config.set_default_target("unknown"))

        # Remove default target switches to next
        self.assertTrue(config.remove_target("prod"))
        self.assertNotIn("prod", config.get_targets())
        self.assertEqual(config.get_default_target_name(), "stage")

        # Remove last target
        self.assertTrue(config.remove_target("stage"))
        self.assertEqual(config.get_targets(), {})
        self.assertEqual(config.get_default_target_name(), "")

    def test_resolve_target(self):
        # 1. Zero-config / no targets defined -> local
        res = config.resolve_target()
        self.assertEqual(res["name"], "local")
        self.assertEqual(res["host"], "")

        # 2. Configured targets
        config.add_target("stage", host="deploy@stage.internal", cwd="/app/stage")
        res = config.resolve_target("stage")
        self.assertEqual(res["name"], "stage")
        self.assertEqual(res["host"], "deploy@stage.internal")
        self.assertEqual(res["cwd"], "/app/stage")

        # 3. Explicit 'local' keyword
        res = config.resolve_target("local")
        self.assertEqual(res["name"], "local")
        self.assertEqual(res["host"], "")

        # 4. Ad-hoc target (not in config)
        res = config.resolve_target("root@10.0.0.99")
        self.assertEqual(res["name"], "root@10.0.0.99")
        self.assertEqual(res["host"], "root@10.0.0.99")
        self.assertEqual(res["cwd"], "")

    def test_cli_target_commands(self):
        # agentbox target (show)
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["target"])
            self.assertEqual(ret, 0)
            self.assertIn("=== ACTIVE TARGET ===", out.getvalue())
            self.assertIn("(local)", out.getvalue())

        # agentbox target add dev --host user@dev --cwd /app
        ret = cli.main(["target", "add", "dev", "--host", "user@dev", "--cwd", "/app"])
        self.assertEqual(ret, 0)

        # agentbox target add prod --host user@prod --cwd /var/app
        ret = cli.main(["target", "add", "prod", "--host", "user@prod", "--cwd", "/var/app"])
        self.assertEqual(ret, 0)

        # agentbox target list
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["target", "list"])
            self.assertEqual(ret, 0)
            val = out.getvalue()
            self.assertIn("dev", val)
            self.assertIn("prod", val)

        # agentbox target use prod
        ret = cli.main(["target", "use", "prod"])
        self.assertEqual(ret, 0)
        self.assertEqual(config.get_default_target_name(), "prod")

        # agentbox target rm dev
        ret = cli.main(["target", "rm", "dev"])
        self.assertEqual(ret, 0)
        self.assertNotIn("dev", config.get_targets())

    @patch("agentbox.cli.execute_action")
    def test_cli_target_flag_routing(self, mock_exec):
        mock_exec.return_value = 0
        config.add_target("prod", host="admin@prod.example.com", cwd="/srv/app", venv="/srv/app/.venv")

        # 1. Without flag: uses active default target (prod)
        cli.main(["run", "echo hi"])
        mock_exec.assert_called_with("admin@prod.example.com", "/srv/app", "run", {
            "cmd": "echo hi",
            "cwd": "/srv/app",
            "tail": 15,
            "timeout": 300,
            "venv": "/srv/app/.venv"
        })

        # 2. With -t local: overrides to local execution
        cli.main(["-t", "local", "run", "echo hi"])
        mock_exec.assert_called_with("", "", "run", {
            "cmd": "echo hi",
            "cwd": "",
            "tail": 15,
            "timeout": 300,
            "venv": ""
        })

        # 3. With -t ad-hoc SSH host
        cli.main(["-t", "root@edge-node", "run", "uptime"])
        mock_exec.assert_called_with("root@edge-node", "", "run", {
            "cmd": "uptime",
            "cwd": "",
            "tail": 15,
            "timeout": 300,
            "venv": ""
        })

    @patch("agentbox.cli.execute_action")
    def test_cli_multi_target_batch(self, mock_exec):
        mock_exec.return_value = 0
        config.add_target("dev", host="user@dev", cwd="/dev/app")
        config.add_target("prod", host="user@prod", cwd="/prod/app")

        batch_steps = json.dumps([
            {"action": "run", "args": {"cmd": "pytest"}, "target": "local"},
            {"action": "run", "args": {"cmd": "systemctl restart app"}, "target": "prod"}
        ])

        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["batch", batch_steps])
            self.assertEqual(ret, 0)
            val = out.getvalue()
            self.assertIn("run on local", val)
            self.assertIn("run on prod", val)

        self.assertEqual(mock_exec.call_count, 2)
        # Call 1: on local
        self.assertEqual(mock_exec.call_args_list[0][0][0], "")
        # Call 2: on prod
        self.assertEqual(mock_exec.call_args_list[1][0][0], "user@prod")
    def test_format_and_sync_targets_rule(self):
        # 1. Format markdown with no targets -> local (active)
        md = config.format_targets_markdown({})
        self.assertIn("* `local` (active)", md)
        self.assertNotIn("host", md)
        self.assertNotIn("cwd", md)

        # 2. Format markdown with multiple targets -> no paths, only names
        config.add_target("dev", host="user@dev.local", cwd="/opt/dev")
        config.add_target("prod", host="user@prod.local", cwd="/var/prod")
        config.set_default_target("prod")
        md = config.format_targets_markdown()
        self.assertIn("* `prod` (active)", md)
        self.assertIn("* `dev`", md)
        self.assertNotIn("user@dev.local", md)
        self.assertNotIn("/opt/dev", md)

        # 3. Test rules command generation and sync
        ret = cli.main(["rules", "--type", "agents"])
        self.assertEqual(ret, 0)
        agents_file = Path("AGENTS.md")
        self.assertTrue(agents_file.exists())
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("* `prod` (active)", content)
        self.assertIn("* `dev`", content)
        self.assertIn("DO NOT read or edit `.agentbox.json` directly", content)

        # 4. Switch default target and verify auto-sync
        config.set_default_target("dev")
        synced_content = agents_file.read_text(encoding="utf-8")
        self.assertIn("* `dev` (active)", synced_content)

    def test_readonly_target_config(self):
        # 1. Add target with readonly=True
        config.add_target("prod", host="admin@prod", cwd="/var/prod", readonly=True)
        targets = config.get_targets()
        self.assertTrue(targets["prod"]["readonly"])

        # 2. Resolve target preserves readonly
        res = config.resolve_target("prod")
        self.assertTrue(res["readonly"])

        # 3. Toggle readonly with set_target_readonly
        self.assertTrue(config.set_target_readonly("prod", False))
        self.assertFalse(config.get_targets()["prod"]["readonly"])
        self.assertFalse(config.resolve_target("prod")["readonly"])

        self.assertTrue(config.set_target_readonly("prod", True))
        self.assertTrue(config.get_targets()["prod"]["readonly"])

        # 4. Markdown format includes read-only
        md = config.format_targets_markdown()
        self.assertIn("* `prod` (active, read-only)", md)

        config.add_target("backup", host="user@backup", readonly=True)
        md2 = config.format_targets_markdown()
        self.assertIn("* `backup` (read-only)", md2)

    @patch("agentbox.cli.execute_action")
    def test_readonly_cli_blocking(self, mock_exec):
        mock_exec.return_value = 0
        config.add_target("prod", host="admin@prod", cwd="/var/prod", readonly=True)

        # 1. Target list and show
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["target", "list"])
            self.assertEqual(ret, 0)
            self.assertIn("[READ-ONLY]", out.getvalue())

        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["-t", "prod", "target"])
            self.assertEqual(ret, 0)
            self.assertIn("Readonly : yes", out.getvalue())

        # 2. Blocking write commands
        for forbidden_cmd in [
            ["-t", "prod", "write", "foo.txt", "--file", "tests/test_targets.py"],
            ["-t", "prod", "run", "rm -rf /"],
            ["-t", "prod", "py", "--code", "import os; print('hi')"],
            ["-t", "prod", "pip", "install", "requests"],
        ]:
            with patch("sys.stderr", new=StringIO()) as err:
                ret = cli.main(forbidden_cmd)
                self.assertEqual(ret, 1)
                self.assertIn("READ-ONLY", err.getvalue())
        self.assertEqual(mock_exec.call_count, 0)

        # 3. Blocking task execution on readonly target
        config.add_task("deploy", "echo deploy")
        with patch("sys.stderr", new=StringIO()) as err:
            ret = cli.main(["-t", "prod", "task", "deploy"])
            self.assertEqual(ret, 1)
            self.assertIn("READ-ONLY", err.getvalue())
        self.assertEqual(mock_exec.call_count, 0)

        # 4. Allowing safe read-only commands
        test_file = Path("dummy.txt")
        test_file.write_text("line 1\nline 2", encoding="utf-8")
        ret = cli.main(["-t", "prod", "view", "dummy.txt"])
        self.assertEqual(ret, 0)
        self.assertGreaterEqual(mock_exec.call_count, 1)

        # 5. Blocking mutating batch actions on readonly target
        batch_forbidden = json.dumps([
            {"action": "view", "path": "dummy.txt"},
            {"action": "write", "path": "new.txt", "content": "bad"}
        ])
        with patch("sys.stderr", new=StringIO()) as err:
            ret = cli.main(["-t", "prod", "batch", batch_forbidden])
            self.assertEqual(ret, 1)
            self.assertIn("READ-ONLY", err.getvalue())
            self.assertIn("write", err.getvalue())

        # 6. Target readonly CLI command toggle
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["target", "readonly", "prod", "--off"])
            self.assertEqual(ret, 0)
            self.assertIn("READ-WRITE", out.getvalue())
        self.assertFalse(config.resolve_target("prod")["readonly"])

        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["target", "readonly", "prod"])
            self.assertEqual(ret, 0)
            self.assertIn("READ-ONLY", out.getvalue())
        self.assertTrue(config.resolve_target("prod")["readonly"])


if __name__ == "__main__":
    unittest.main()
