# -*- coding: utf-8 -*-
"""
Tests for v0.1.7 improvements:
1. Upward search for .agentbox.json.
2. Line ending (CRLF vs LF) preservation during rule syncing.
3. Remote worker SHA-256 caching.
4. CLI write command stdin/content validation.
"""

import os
import sys
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import config
from agentbox import client
from agentbox import cli


class TestImprovements(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    def test_find_local_config_upward(self):
        root = Path(self.test_dir.name)
        cfg_file = root / ".agentbox.json"
        cfg_file.write_text(json.dumps({"host": "remote-server", "cwd": "/app"}), encoding="utf-8")

        sub_dir = root / "src" / "deep" / "nested"
        sub_dir.mkdir(parents=True)
        os.chdir(sub_dir)

        found = config.find_local_config()
        self.assertIsNotNone(found)
        self.assertEqual(found.resolve(), cfg_file.resolve())

        # Test that get_config reads it seamlessly from sub_dir
        loaded = config.get_config()
        self.assertEqual(loaded.get("host"), "remote-server")
        self.assertEqual(loaded.get("cwd"), "/app")

    def test_sync_rules_preserves_crlf(self):
        root = Path(self.test_dir.name)
        agents_file = root / "AGENTS.md"
        # Write file with explicit CRLF endings
        content = "#### 6. Project Tasks & Recipes (.agentbox.json)\r\n\r\n<!-- AGENTBOX_TASKS_START -->\r\n<!-- AGENTBOX_TASKS_END -->\r\n"
        agents_file.write_bytes(content.encode("utf-8"))

        with patch.object(config, "get_tasks", return_value={"test": "pytest"}):
            updated = config.sync_rules_with_tasks(root)
            self.assertIn("AGENTS.md", updated)

            updated_bytes = agents_file.read_bytes()
            # Must strictly contain CRLF and not plain LF
            self.assertIn(b"\r\n", updated_bytes)
            self.assertNotIn(b"\n\n", updated_bytes.replace(b"\r\n", b""))
            self.assertIn(b"agentbox task test", updated_bytes)

    def test_worker_hash_cache(self):
        cache_file = Path(self.test_dir.name) / ".worker_cache.json"
        with patch.object(client, "WORKER_CACHE_FILE", cache_file):
            self.assertEqual(client.load_worker_cache(), {})

            # First run: should call ssh to verify/upload and then save cache
            with patch("subprocess.run") as mock_run:
                # Return remote hash that matches local
                local_bytes = client.get_local_worker_bytes()
                import hashlib
                local_hash = hashlib.sha256(local_bytes).hexdigest()
                mock_run.return_value = MagicMock(returncode=0, stdout=f"{local_hash}  worker.py\n")

                client.ensure_remote_worker("test-host")
                self.assertEqual(mock_run.call_count, 1)

                # Verify cache is populated
                cache = client.load_worker_cache()
                self.assertEqual(cache.get("test-host"), local_hash)

            # Second run: should hit cache and NOT call subprocess.run
            with patch("subprocess.run") as mock_run2:
                client.ensure_remote_worker("test-host")
                mock_run2.assert_not_called()

    def test_cli_write_requires_content_or_stdin(self):
        # 1. Missing both --content and --stdin should return error code 1
        with patch("sys.stderr", new=StringIO()) as err:
            ret = cli.main(["write", "test.txt"])
            self.assertEqual(ret, 1)
            self.assertIn("ERROR: Provide content via --content", err.getvalue())

        # 2. Passing --content works cleanly
        with patch.object(cli, "execute_action", return_value=0) as mock_exec:
            ret = cli.main(["write", "test.txt", "--content", "hello world"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once_with("", "", "write", {"path": "test.txt", "content": "hello world", "append": False})

        # 3. Passing --stdin works cleanly
        with patch("sys.stdin", StringIO("stdin content")):
            with patch.object(cli, "execute_action", return_value=0) as mock_exec:
                ret = cli.main(["write", "test.txt", "--stdin"])
                self.assertEqual(ret, 0)
                mock_exec.assert_called_once_with("", "", "write", {"path": "test.txt", "content": "stdin content", "append": False})


if __name__ == "__main__":
    unittest.main()
