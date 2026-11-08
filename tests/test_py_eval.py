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


class TestPyEval(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    def test_py_eval_inline_code(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["py", "--code", "print(40 + 2)"])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("OK [exit 0", out)
        self.assertIn("42", out)

    def test_py_eval_base64(self):
        code = "val = [x * 2 for x in (1, 2, 3)]; print(val)"
        b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["py", "--base64", b64])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("[2, 4, 6]", out)

    def test_py_eval_file(self):
        script_file = self.root / "sample_script.py"
        script_file.write_text("print('HELLO FROM FILE')", encoding="utf-8")
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["py", "--file", str(script_file)])
        self.assertEqual(ret, 0)
        self.assertIn("HELLO FROM FILE", stdout.getvalue())

    def test_py_eval_script_args(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["py", "--code", "import sys; print(f'ARGS={sys.argv[1:]}')", "--", "alpha", "beta with spaces"])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("ARGS=['alpha', 'beta with spaces']", out)

    def test_py_eval_exception_traceback(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["py", "--code", "raise RuntimeError('custom error msg')"])
        self.assertNotEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("FAILED [exit", out)
        self.assertIn("High-Signal Failure Traceback", out)
        self.assertIn("RuntimeError: custom error msg", out)

    def test_py_eval_output_truncation(self):
        code = "for i in range(50): print(f'line_{i}')"
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            ret = cli.main(["py", "--code", code, "--max-lines", "10", "--tail", "5"])
        self.assertEqual(ret, 0)
        out = stdout.getvalue()
        self.assertIn("output truncated: showing last 5 of 50 lines", out)
        self.assertIn("line_49", out)
        self.assertNotIn("line_0", out)

    def test_py_eval_missing_code_hint(self):
        stderr = StringIO()
        with patch("sys.stderr", stderr):
            ret = cli.main(["py"])
        self.assertEqual(ret, 1)
        err = stderr.getvalue()
        self.assertIn("ERROR: No Python code provided", err)
        self.assertIn("💡 AGENT HINT: Use --base64", err)


if __name__ == "__main__":
    unittest.main()
