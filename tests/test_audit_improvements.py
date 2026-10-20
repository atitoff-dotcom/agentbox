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


if __name__ == "__main__":
    unittest.main()
