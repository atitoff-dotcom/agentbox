# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox.sync import (
    build_manifest,
    should_ignore,
    parse_gitignore,
    pack_sync_tar,
    unpack_sync_tar,
    compute_sync_diff,
)


class TestSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_ignore_rules_safety(self):
        # Strict protection of venvs, git, and agentbox
        self.assertTrue(should_ignore(".git", is_dir=True))
        self.assertTrue(should_ignore(".git/config", is_dir=False))
        self.assertTrue(should_ignore(".venv", is_dir=True))
        self.assertTrue(should_ignore(".venv/bin/python", is_dir=False))
        self.assertTrue(should_ignore(".agentbox/config.json", is_dir=False))
        self.assertTrue(should_ignore("__pycache__/module.cpython-312.pyc", is_dir=False))
        self.assertTrue(should_ignore("node_modules/package/index.js", is_dir=False))
        # Normal files should not be ignored
        self.assertFalse(should_ignore("src/main.py", is_dir=False))
        self.assertFalse(should_ignore("README.md", is_dir=False))

    def test_gitignore_parsing_and_matching(self):
        gi = self.root / ".gitignore"
        gi.write_text("*.log\ntmp/\nsecret_*.txt\n", encoding="utf-8")
        patterns = parse_gitignore(self.root)
        self.assertIn("*.log", patterns)
        self.assertIn("tmp", patterns)
        self.assertTrue(should_ignore("app.log", extra_patterns=patterns))
        self.assertTrue(should_ignore("tmp/data.csv", extra_patterns=patterns))
        self.assertTrue(should_ignore("secret_key.txt", extra_patterns=patterns))
        self.assertFalse(should_ignore("src/app.py", extra_patterns=patterns))

    def test_build_manifest(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "pyvenv.cfg").write_text("home = ...", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

        manifest = build_manifest(self.root)
        self.assertIn("src/app.py", manifest)
        self.assertNotIn(".venv/pyvenv.cfg", manifest)
        self.assertNotIn(".git/HEAD", manifest)
        self.assertEqual(manifest["src/app.py"]["size"], len("print('hello')"))
        self.assertTrue(len(manifest["src/app.py"]["sha256"]) == 64)

    def test_pack_and_unpack_in_memory_tar(self):
        (self.root / "f1.txt").write_text("file 1 content", encoding="utf-8")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "f2.txt").write_text("file 2 content", encoding="utf-8")

        tar_bytes = pack_sync_tar(self.root, ["f1.txt", "sub/f2.txt"])
        self.assertTrue(len(tar_bytes) > 0)

        dest_dir = Path(tempfile.mkdtemp())
        try:
            unpacked = unpack_sync_tar(dest_dir, tar_bytes)
            self.assertIn("f1.txt", unpacked)
            self.assertIn("sub/f2.txt", unpacked)
            self.assertEqual((dest_dir / "f1.txt").read_text(encoding="utf-8"), "file 1 content")
            self.assertEqual((dest_dir / "sub" / "f2.txt").read_text(encoding="utf-8"), "file 2 content")
        finally:
            import shutil
            shutil.rmtree(dest_dir, ignore_errors=True)

    def test_crlf_to_lf_normalization(self):
        crlf_file = self.root / "script.sh"
        crlf_file.write_bytes(b"#!/bin/bash\r\necho hello\r\n")

        tar_bytes = pack_sync_tar(self.root, ["script.sh"], to_lf=True)
        dest_dir = Path(tempfile.mkdtemp())
        try:
            unpack_sync_tar(dest_dir, tar_bytes)
            content = (dest_dir / "script.sh").read_bytes()
            self.assertEqual(content, b"#!/bin/bash\necho hello\n")
            self.assertNotIn(b"\r\n", content)
        finally:
            import shutil
            shutil.rmtree(dest_dir, ignore_errors=True)

    def test_compute_sync_diff(self):
        loc = {
            "common.py": {"size": 10, "mtime": 100.0, "sha256": "same_hash"},
            "local_ahead.py": {"size": 20, "mtime": 150.0, "sha256": "new_hash"},
            "conflict.py": {"size": 30, "mtime": 100.0, "sha256": "loc_hash"}
        }
        rem = {
            "common.py": {"size": 10, "mtime": 100.0, "sha256": "same_hash"},
            "remote_ahead.py": {"size": 50, "mtime": 120.0, "sha256": "rem_hash"},
            "conflict.py": {"size": 35, "mtime": 200.0, "sha256": "rem_newer_hash"}
        }

        diff = compute_sync_diff(loc, rem)
        self.assertIn("common.py", diff["in_sync"])
        self.assertIn("local_ahead.py", diff["to_push"])
        self.assertIn("remote_ahead.py", diff["to_pull"])
        self.assertIn("conflict.py", diff["conflicts_push"])  # remote is newer


if __name__ == "__main__":
    unittest.main()
