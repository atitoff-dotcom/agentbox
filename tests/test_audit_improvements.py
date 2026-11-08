import unittest
import tempfile
import base64
import json
import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import worker, cli, client


class TestAuditImprovements(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)

    def tearDown(self):
        try:
            os.chdir(self.orig_cwd)
        except Exception:
            pass
        try:
            self.test_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. View --tail and negative start indices
    # -------------------------------------------------------------------------
    def test_view_tail(self):
        sample = self.dir_path / "long.log"
        lines = [f"line_{i}" for i in range(1, 101)]
        sample.write_text("\n".join(lines) + "\n", encoding="utf-8")

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            worker.cmd_view(str(sample), tail=10)
        output = buf.getvalue()
        self.assertIn("[long.log: lines 91-100 of 100]", output)
        self.assertIn("100 | line_100", output)
        self.assertNotIn("line_80", output)

    def test_view_negative_start(self):
        sample = self.dir_path / "app.log"
        lines = [f"entry_{i}" for i in range(1, 51)]
        sample.write_text("\n".join(lines) + "\n", encoding="utf-8")

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            worker.cmd_view(str(sample), start=-10)
        output = buf.getvalue()
        self.assertIn("[app.log: lines 41-50 of 50]", output)
        self.assertIn("50 | entry_50", output)
        self.assertNotIn("entry_35", output)

    # -------------------------------------------------------------------------
    # 2. Grep single file, fixed string and auto-fallback
    # -------------------------------------------------------------------------
    def test_grep_single_file(self):
        sample = self.dir_path / "App.svelte"
        sample.write_text("line 1\nlet task = tasks.list();\nline 3\n", encoding="utf-8")

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            worker.cmd_grep("tasks.list", path=str(sample))
        output = buf.getvalue()
        self.assertIn("App.svelte:2 | let task = tasks.list();", output)

    def test_grep_fixed_and_broken_regex(self):
        sample = self.dir_path / "regex_test.txt"
        sample.write_text("const obj = user[id];\nfoo(bar)\n", encoding="utf-8")

        # Unbalanced bracket [id is an invalid regex, should auto-fallback to literal match
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            worker.cmd_grep("user[id", path=str(sample))
        output = buf.getvalue()
        self.assertIn("user[id];", output)

        # Explicit fixed=True
        buf2 = io.StringIO()
        with patch("sys.stdout", buf2):
            worker.cmd_grep("foo(bar)", path=str(sample), fixed=True)
        self.assertIn("foo(bar)", buf2.getvalue())

    # -------------------------------------------------------------------------
    # 3. Base64 encoding support for CLI / Worker
    # -------------------------------------------------------------------------
    def test_base64_patch_lines(self):
        sample = self.dir_path / "file.py"
        sample.write_text("x = 1\n# старый комментарий\ny = 2\n", encoding="utf-8")

        new_content = "# новый русский комментарий с кавычками \" ' $\n"
        b64 = base64.b64encode(new_content.encode("utf-8")).decode("ascii")

        ret = cli.main(["patch-lines", str(sample), "--start", "2", "--end", "2", "--base64", b64])
        self.assertEqual(ret, 0)
        self.assertIn("новый русский комментарий с кавычками \" ' $", sample.read_text(encoding="utf-8"))

    def test_base64_write(self):
        sample = self.dir_path / "written.txt"
        content = "Тестовая строка UTF-8\n"
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

        ret = cli.main(["write", str(sample), "--base64", b64])
        self.assertEqual(ret, 0)
        self.assertEqual(sample.read_text(encoding="utf-8"), content)

    # -------------------------------------------------------------------------
    # 4. Batch with relative path resolution
    # -------------------------------------------------------------------------
    def test_batch_relative_paths(self):
        sub = self.dir_path / "subfolder"
        sub.mkdir()
        target = sub / "handlers.py"
        target.write_text("def handle():\n    pass\n", encoding="utf-8")

        steps = [
            {
                "action": "patch",
                "path": "subfolder/handlers.py",
                "old": "pass",
                "new": "return True"
            }
        ]
        steps_json = json.dumps(steps)

        # Execute batch with cwd set to project root
        ret = cli.main(["--cwd", str(self.dir_path), "batch", steps_json])
        self.assertEqual(ret, 0)
        self.assertIn("return True", target.read_text(encoding="utf-8"))

    # -------------------------------------------------------------------------
    # 5. Backup storage outside project tree (.agentbox/backups/)
    # -------------------------------------------------------------------------
    def test_clean_workspace_backup(self):
        sample = self.dir_path / "service.py"
        sample.write_text("def serve():\n    return 1\n", encoding="utf-8")

        # Apply patch-lines
        ret = cli.main(["patch-lines", str(sample), "--start", "2", "--end", "2", "--content", "    return 2\n"])
        self.assertEqual(ret, 0)

        # Workspace directory must NOT contain service.py.bak
        self.assertFalse((self.dir_path / "service.py.bak").exists())

        # Backup must exist in backups dir
        bak_file = worker._get_backup_path(sample)
        self.assertTrue(bak_file.is_file())
        self.assertIn("return 1", bak_file.read_text(encoding="utf-8"))

        # Rollback restores content and removes the backup
        ret = cli.main(["rollback", str(sample)])
        self.assertEqual(ret, 0)
        self.assertIn("return 1", sample.read_text(encoding="utf-8"))
        self.assertFalse(bak_file.exists())

    def test_audit_logger(self):
        from agentbox import config
        orig_cwd = os.getcwd()
        os.chdir(self.dir_path)
        try:
            # 1. Clear log
            config.get_audit_summary(clear=True)
            self.assertIn("No recorded actions", config.get_audit_summary())

            # 2. Record actions with enriched metadata
            config.record_audit("view", target="local", path="foo.py", code=0, duration_ms=10, meta={"lines": [1, 25]})
            config.record_audit("run", target="prod", path="", code=1, duration_ms=250, error="not found", arg="pytest tests/")
            config.record_audit("grep", target="local", path="src", code=0, duration_ms=15, query="def test_foo", meta={"fixed": True})
            config.record_audit("patch-lines", target="local", path="app.py", code=0, duration_ms=20, meta={"lines": [10, 30]})

            # 3. Summary
            summary = config.get_audit_summary(tail=4)
            self.assertIn("4 actions recorded", summary)
            self.assertIn("view", summary)
            self.assertIn("run", summary)
            self.assertIn("prod", summary)
            self.assertIn("Recent Failures", summary)
            self.assertIn("not found", summary)
            self.assertIn("lines: 1-25", summary)
            self.assertIn("pytest tests/", summary)
            self.assertIn("query: def test_foo", summary)

            # 4. Check raw JSON records in audit.jsonl
            log_file = config.get_audit_log_path()
            self.assertTrue(log_file.is_file())
            raw_lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(raw_lines), 4)
            
            # Record 0: view
            self.assertEqual(raw_lines[0]["cmd"], "view")
            self.assertEqual(raw_lines[0]["lines"], [1, 25])
            
            # Record 1: run with arg
            self.assertEqual(raw_lines[1]["cmd"], "run")
            self.assertEqual(raw_lines[1]["arg"], "pytest tests/")
            self.assertEqual(raw_lines[1]["err"], "not found")

            # Record 2: grep with query
            self.assertEqual(raw_lines[2]["cmd"], "grep")
            self.assertEqual(raw_lines[2]["query"], "def test_foo")
            self.assertEqual(raw_lines[2]["path"], "src")
            self.assertTrue(raw_lines[2]["fixed"])

            # Record 3: patch-lines
            self.assertEqual(raw_lines[3]["cmd"], "patch-lines")
            self.assertEqual(raw_lines[3]["lines"], [10, 30])

            # 5. CLI audit command
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                ret = cli.main(["audit", "--tail", "4"])
                self.assertEqual(ret, 0)
                self.assertIn("4 actions recorded", buf.getvalue())
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
