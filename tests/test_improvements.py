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

    def test_cli_run_test_spawn_multi_tokens(self):
        # 1. Multi-token command with flags in run
        with patch.object(cli, "execute_action", return_value=0) as mock_exec:
            ret = cli.main(["run", "python", "-c", "import pyferro; print(pyferro.__file__)"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once_with(
                "", "", "run",
                {"cmd": "python -c import pyferro; print(pyferro.__file__)", "cwd": "", "tail": 15, "timeout": 300, "venv": ""}
            )

        # 2. Multi-token command with flags in test
        with patch.object(cli, "execute_action", return_value=0) as mock_exec:
            ret = cli.main(["test", "pytest", "-k", "test_foo", "-v"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once_with(
                "", "", "test",
                {"cmd": "pytest -k test_foo -v", "cwd": "", "timeout": 300, "max_lines": 30, "venv": ""}
            )

        # 3. Multi-token command in spawn
        with patch.object(cli, "execute_action", return_value=0) as mock_exec:
            ret = cli.main(["spawn", "python", "server.py", "--port", "8080"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once_with(
                "", "", "spawn",
                {"cmd": "python server.py --port 8080", "cwd": "", "venv": ""}
            )

        # 4. run with agentbox options preceding command
        with patch.object(cli, "execute_action", return_value=0) as mock_exec:
            ret = cli.main(["run", "--tail", "25", "pytest", "-v"])
            self.assertEqual(ret, 0)
            mock_exec.assert_called_once_with(
                "", "", "run",
                {"cmd": "pytest -v", "cwd": "", "tail": 25, "timeout": 300, "venv": ""}
            )

        # 5. Missing command returns error code 1
        with patch("sys.stderr", new=StringIO()) as err:
            ret = cli.main(["run"])
            self.assertEqual(ret, 1)
            self.assertIn("ERROR: Missing command to execute", err.getvalue())

    def test_win_no_window_kwargs(self):
        import sys
        import subprocess
        from agentbox.worker import win_no_window_kwargs as worker_win_kw
        from agentbox.client import win_no_window_kwargs as client_win_kw

        expected_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        with patch("sys.platform", "win32"):
            kw_w = worker_win_kw()
            kw_c = client_win_kw()
            self.assertEqual(kw_w, {"creationflags": expected_flag})
            self.assertEqual(kw_c, {"creationflags": expected_flag})

            # Check combining extra flags
            combined = worker_win_kw(subprocess.CREATE_NEW_PROCESS_GROUP)
            self.assertEqual(combined, {"creationflags": expected_flag | subprocess.CREATE_NEW_PROCESS_GROUP})

        with patch("sys.platform", "linux"):
            self.assertEqual(worker_win_kw(), {})
            self.assertEqual(client_win_kw(), {})


if __name__ == "__main__":
    unittest.main()
