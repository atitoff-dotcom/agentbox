# -*- coding: utf-8 -*-
import os
import sys
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import cli, config


class TestTaskParameters(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    def test_format_task_command_basic(self):
        cmd = "python script.py"
        args = ["arg1", "arg2 with space"]
        res = cli._format_task_command(cmd, args)
        if sys.platform == "win32":
            self.assertEqual(res, 'python script.py arg1 "arg2 with space"')
        else:
            self.assertIn("arg2 with space", res)

    def test_format_task_command_positional_placeholders(self):
        cmd = "git tag -a {1} -m {2}"
        args = ["v1.0.0", "Initial release"]
        res = cli._format_task_command(cmd, args)
        if sys.platform == "win32":
            self.assertEqual(res, 'git tag -a v1.0.0 -m "Initial release"')
        else:
            self.assertIn("v1.0.0", res)
            self.assertIn("Initial release", res)

    def test_format_task_command_positional_with_remaining(self):
        cmd = "echo {1} {2}"
        args = ["first", "second", "third", "fourth with space"]
        res = cli._format_task_command(cmd, args)
        self.assertTrue(res.startswith("echo first second"))
        self.assertIn("third", res)
        self.assertIn("fourth with space", res)

    def test_format_task_command_args_placeholder(self):
        cmd = "pytest {args} --verbose"
        args = ["-k", "test_my_func"]
        res = cli._format_task_command(cmd, args)
        self.assertIn("-k test_my_func", res)
        self.assertTrue(res.endswith("--verbose"))

    def test_task_object_with_target_execution(self):
        cfg_file = self.root / ".agentbox.json"
        cfg_file.write_text(json.dumps({
            "tasks": {
                "custom_task": {
                    "cmd": "echo hello",
                    "target": "local",
                    "desc": "Custom echo task"
                }
            }
        }), encoding="utf-8")

        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["task", "list"])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("custom_task", out)
        self.assertIn("[target: local]", out)
        self.assertIn("Custom echo task", out)


if __name__ == "__main__":
    unittest.main()
