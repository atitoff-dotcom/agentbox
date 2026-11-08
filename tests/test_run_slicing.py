# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import cli, worker


class TestRunSlicing(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)
        self.py = f'"{sys.executable}"' if " " in sys.executable else sys.executable

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    def test_run_short_output_auto_inline(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", f'{self.py} -c "print(1); print(2); print(3)"'])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("OK [exit 0", out)
        self.assertIn("1\n2\n3", out)
        self.assertNotIn("--- Output Tail", out)

    def test_run_long_output_tail_slice(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", "--tail", "5", f'{self.py} -c "for i in range(30): print(f\'line_{{i}}\')"'])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("OK [exit 0", out)
        self.assertIn("--- Output Tail (5 of 30 lines) ---", out)
        self.assertIn("line_29", out)
        self.assertNotIn("line_0", out)

    def test_run_head_slice(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", "--head", "4", f'{self.py} -c "for i in range(25): print(f\'entry_{{i}}\')"'])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("OK [exit 0", out)
        self.assertIn("--- Output Head (4 of 25 lines) ---", out)
        self.assertIn("entry_0", out)
        self.assertIn("entry_3", out)
        self.assertNotIn("entry_24", out)

    def test_run_silent_flag(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["run", "--silent", f'{self.py} -c "print(\'SHOULD_BE_SILENCED\')"'])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("OK [exit 0", out)
        self.assertNotIn("SHOULD_BE_SILENCED", out)


if __name__ == "__main__":
    unittest.main()
