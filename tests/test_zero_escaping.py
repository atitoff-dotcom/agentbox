# -*- coding: utf-8 -*-
import os
import sys
import base64
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import cli, worker


class TestZeroEscaping(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    def test_grep_files_only(self):
        f1 = self.root / "file1.txt"
        f2 = self.root / "file2.txt"
        f1.write_text("hello world\nline 2", encoding="utf-8")
        f2.write_text("another file\nno match", encoding="utf-8")

        stdout = StringIO()
        with patch("sys.stdout", stdout):
            worker.cmd_grep("world", str(self.root), files_only=True)
        out = stdout.getvalue().strip()
        self.assertIn("file1.txt", out)
        self.assertNotIn("file2.txt", out)
        self.assertNotIn(":1 |", out)

    def test_run_base64_execution(self):
        cmd = 'python -c "print(\'b64_ok\')"'
        b64 = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", "--base64", b64])
        self.assertEqual(ret, 0)
        self.assertIn("OK [exit 0", stdout.getvalue())

    def test_run_file_execution(self):
        script_file = self.root / "script.txt"
        script_file.write_text('python -c "print(\'file_ok\')"', encoding="utf-8")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", "--file", str(script_file)])
        self.assertEqual(ret, 0)
        self.assertIn("OK [exit 0", stdout.getvalue())

    def test_test_base64_execution(self):
        cmd = 'python -c "print(\'test_b64_ok\')"'
        b64 = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["test", "--base64", b64])
        self.assertEqual(ret, 0)

    def test_test_file_execution(self):
        script_file = self.root / "test_script.txt"
        script_file.write_text('python -c "print(\'test_file_ok\')"', encoding="utf-8")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["test", "--file", str(script_file)])
        self.assertEqual(ret, 0)

    def test_run_multiline_script(self):
        multiline = self.root / "multiline.txt"
        multiline.write_text("echo Step1\necho Step2\n", encoding="utf-8")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", "--file", str(multiline)])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("OK [exit 0", out)
