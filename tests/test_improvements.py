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
        self.root = Path(self.test_dir.name)
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

    def test_get_fn_qualified_and_brace_blocks(self):
        from agentbox import worker

        # 1. Qualified Class.method and decorators in Python
        py_file = self.root / "service.py"
        py_file.write_text(
            "class Alpha:\n"
            "    def run(self):\n"
            "        return 'alpha'\n\n"
            "class Beta:\n"
            "    @staticmethod\n"
            "    def run(x: int) -> int:\n"
            "        return x + 1\n",
            encoding="utf-8"
        )
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_get_fn(str(py_file), "Beta.run")
            output = out.getvalue()
            self.assertIn("Beta.run lines 6-8", output)
            self.assertIn("@staticmethod", output)
            self.assertIn("return x + 1", output)
            self.assertNotIn("'alpha'", output)

        # 2. Non-Python brace-balanced block extraction in TypeScript/Rust
        ts_file = self.root / "handler.ts"
        ts_file.write_text(
            "export async function processOrder(id: string) {\n"
            "    const msg = \"brace } in string\";\n"
            "    if (id) {\n"
            "        return true;\n"
            "    }\n"
            "    return false;\n"
            "}\n"
            "export function otherFn() {\n"
            "    return 0;\n"
            "}\n",
            encoding="utf-8"
        )
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_get_fn(str(ts_file), "processOrder")
            output = out.getvalue()
            self.assertIn("lines 1-7", output)
            self.assertIn("return false;", output)
            self.assertNotIn("otherFn", output)

        # 3. Multi-file outline
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_outline([str(py_file), str(ts_file)])
            output = out.getvalue()
            self.assertIn("OUTLINE: service.py", output)
            self.assertIn("OUTLINE: handler.ts", output)
            self.assertIn("1-   7 | export async function processOrder", output)

    def test_refs_ast_and_fallback(self):
        from agentbox import worker

        f1 = self.root / "mod_a.py"
        f1.write_text(
            "def compute_total(items):\n"
            "    return sum(items)\n",
            encoding="utf-8"
        )
        f2 = self.root / "mod_b.py"
        f2.write_text(
            "from mod_a import compute_total\n\n"
            "# compute_total in comment should not duplicate\n"
            "res = compute_total([1, 2, 3])\n",
            encoding="utf-8"
        )
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_refs("compute_total", str(self.root))
            output = out.getvalue()
            self.assertIn("REFERENCES: 'compute_total'", output)
            self.assertIn("[def", output)
            self.assertIn("[import", output)
            self.assertIn("[call", output)

    def test_patch_syntax_guard_and_patch_lines(self):
        from agentbox import worker

        py_file = self.root / "calc.py"
        orig_code = "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return a * b\n"
        py_file.write_text(orig_code, encoding="utf-8")

        # 1. Patch introducing a Python SyntaxError must be rejected and leave file untouched
        with patch("sys.stderr", new=StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                worker.cmd_patch(str(py_file), "return a + b", "return (a + b")
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("SyntaxError", err.getvalue())
        self.assertEqual(py_file.read_text(encoding="utf-8"), orig_code)

        # 2. Trailing-whitespace / CRLF tolerant patch succeeds
        crlf_file = self.root / "crlf.py"
        crlf_file.write_bytes(b"def hello():   \r\n    return 1\r\n")
        with patch("sys.stdout", new=StringIO()):
            worker.cmd_patch(str(crlf_file), "def hello():\n    return 1", "def hello():\n    return 2")
        self.assertEqual(crlf_file.read_bytes(), b"def hello():\r\n    return 2\r\n")

        # 3. cmd_patch_lines replaces exact line range
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_patch_lines(str(py_file), 1, 2, "def add(a, b):\n    return a + b + 10\n")
            self.assertEqual("OK\n", out.getvalue())
        self.assertIn("return a + b + 10", py_file.read_text(encoding="utf-8"))

    def test_hermetic_agentbox_venv_and_sanitization(self):
        import os
        from agentbox import worker

        # 1. .agentbox/venv takes priority over .venv
        dot_venv = self.root / ".venv"
        (dot_venv / "bin").mkdir(parents=True)
        (dot_venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

        ab_venv = self.root / ".agentbox" / "venv"
        bin_name = "Scripts" if os.name == "nt" else "bin"
        (ab_venv / bin_name).mkdir(parents=True)
        (ab_venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

        found = worker.find_virtualenv(self.root)
        self.assertEqual(found.resolve(), ab_venv.resolve())

        # 2. Foreign venvs are stripped from PATH in prepare_env_for_cmd
        foreign_bin = str((dot_venv / "bin").resolve())
        with patch.dict(os.environ, {"PATH": f"{foreign_bin}{os.pathsep}/usr/bin"}):
            env, resolved = worker.prepare_env_for_cmd(self.root)
            self.assertEqual(resolved.resolve(), ab_venv.resolve())
            path_entries = env["PATH"].split(os.pathsep)
            self.assertEqual(Path(path_entries[0]).resolve(), (ab_venv / bin_name).resolve())
            self.assertNotIn(foreign_bin, path_entries)

        # 3. Direct system python calls are rewritten by sanitize_python_cmd
        rewritten = worker.sanitize_python_cmd("/usr/bin/python3 -m pytest", ab_venv)
        self.assertNotIn("/usr/bin/python3", rewritten)
        self.assertIn("-m pytest", rewritten)

    def test_batch_and_stats(self):
        from agentbox import worker

        f = self.root / "sample.py"
        f.write_text("def greet(name: str) -> str:\n    return f'hi {name}'\n", encoding="utf-8")

        # 1. Batch execution
        steps = [
            {"action": "outline", "args": {"path": str(f)}},
            {"action": "get-fn", "args": {"path": str(f), "name": "greet"}}
        ]
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_batch(steps)
            batch_out = out.getvalue()
            self.assertIn("[Batch 1/2: outline]", batch_out)
            self.assertIn("[Batch 2/2: get-fn]", batch_out)
            self.assertIn("def greet(name)", batch_out)

        # 2. Stats output
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_stats()
            self.assertIn("AGENTBOX", out.getvalue())
    def test_get_fn_multiple_functions(self):
        from agentbox import worker, cli

        py_file = self.root / "multi_service.py"
        py_file.write_text(
            "class Service:\n"
            "    def one(self):\n"
            "        return 1\n\n"
            "    def two(self):\n"
            "        return 2\n\n"
            "    def three(self):\n"
            "        return 3\n",
            encoding="utf-8"
        )

        # 1. worker.cmd_get_fn with a list of names
        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_get_fn(str(py_file), ["Service.one", "Service.three"])
            output = out.getvalue()
            self.assertIn("Service.one lines 2-3", output)
            self.assertIn("return 1", output)
            self.assertIn("Service.three lines 8-9", output)
            self.assertIn("return 3", output)
            self.assertNotIn("Service.two", output)

        # 2. cli main with multiple names
        with patch("sys.stdout", new=StringIO()) as out:
            ret = cli.main(["get-fn", str(py_file), "Service.two", "Service.three"])
            self.assertEqual(ret, 0)
            output = out.getvalue()
            self.assertIn("Service.two lines 5-6", output)
            self.assertIn("Service.three lines 8-9", output)
            self.assertNotIn("Service.one", output)

    def test_write_and_patch_lines_from_file(self):
        from agentbox import worker, cli

        src_data = self.root / "source.txt"
        src_data.write_text("Hello from file!\nSecond line.\n", encoding="utf-8")

        target_file = self.root / "target.txt"

        # 1. CLI write --file
        ret = cli.main(["write", str(target_file), "--file", str(src_data)])
        self.assertEqual(ret, 0)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "Hello from file!\nSecond line.\n")

        # 2. CLI patch-lines --file
        patch_data = self.root / "patch.txt"
        patch_data.write_text("Replaced line!\n", encoding="utf-8")
        ret = cli.main(["patch-lines", str(target_file), "--start", "1", "--end", "1", "--file", str(patch_data)])
        self.assertEqual(ret, 0)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "Replaced line!\nSecond line.\n")
    def test_json_syntax_validation(self):
        from agentbox import worker

        json_file = self.root / "config.json"
        json_file.write_text('{\n  "version": 1,\n  "enabled": true\n}\n', encoding="utf-8")

        # 1. Broken patch rejected
        with patch("sys.stderr", new=StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                worker.cmd_patch(str(json_file), '"enabled": true', '"enabled": invalid_json,')
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("JSON SyntaxError", err.getvalue())

        # 2. Valid patch accepted
        worker.cmd_patch(str(json_file), '"enabled": true', '"enabled": false')
        self.assertIn('"enabled": false', json_file.read_text(encoding="utf-8"))

        # 3. Broken patch-lines rejected
        with patch("sys.stderr", new=StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                worker.cmd_patch_lines(str(json_file), 2, 2, '  "version": [broken')
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("JSON SyntaxError", err.getvalue())

        # 4. Valid patch-lines accepted
        worker.cmd_patch_lines(str(json_file), 2, 2, '  "version": 2,')
        self.assertIn('"version": 2', json_file.read_text(encoding="utf-8"))

    def test_parse_file_mapping(self):
        from agentbox.worker import parse_file_mapping

        # Standard mapping
        self.assertEqual(parse_file_mapping("a.py:scratch/a.py"), ("a.py", "scratch/a.py"))
        # Windows drive letter on source
        self.assertEqual(parse_file_mapping(r"C:\Users\test\a.py:scratch/a.py"), (r"C:\Users\test\a.py", "scratch/a.py"))
        self.assertEqual(parse_file_mapping("C:/Users/test/a.py:scratch/a.py"), ("C:/Users/test/a.py", "scratch/a.py"))
        # Windows drive letter on destination
        self.assertEqual(parse_file_mapping(r"a.py:D:\dest\a.py"), ("a.py", r"D:\dest\a.py"))
        # Windows drive letter on both
        self.assertEqual(parse_file_mapping(r"C:\local\a.py:D:\remote\a.py"), (r"C:\local\a.py", r"D:\remote\a.py"))
        # No colon separator
        self.assertEqual(parse_file_mapping("sub/dir/file.py"), ("sub/dir/file.py", "sub/dir/file.py"))
        self.assertEqual(parse_file_mapping(r"C:\single\file.py"), (r"C:\single\file.py", r"C:\single\file.py"))

    def test_batch_write_worker(self):
        from agentbox import worker

        f1 = self.root / "sub1" / "file1.txt"
        f2 = self.root / "sub2" / "file2.txt"

        files_data = [
            {"path": str(f1), "content": "Content of file 1"},
            {"path": str(f2), "base64": "SGVsbG8gZnJvbSBiYXNlNjQ="},
        ]

        with patch("sys.stdout", new=StringIO()) as out:
            worker.cmd_write_files(files_data)
            self.assertIn("OK (2 files written)", out.getvalue())

        self.assertEqual(f1.read_text(encoding="utf-8"), "Content of file 1")
        self.assertEqual(f2.read_text(encoding="utf-8"), "Hello from base64")

    def test_batch_write_cli(self):
        src1 = self.root / "src1.py"
        src2 = self.root / "src2.py"
        src1.write_text("print('one')", encoding="utf-8")
        src2.write_text("print('two')", encoding="utf-8")

        dest1 = self.root / "out1.py"
        dest2 = self.root / "deep" / "out2.py"

        # Multi-file batch write
        ret = cli.main(["write", f"{src1}:{dest1}", f"{src2}:{dest2}"])
        self.assertEqual(ret, 0)
        self.assertEqual(dest1.read_text(encoding="utf-8"), "print('one')")
        self.assertEqual(dest2.read_text(encoding="utf-8"), "print('two')")

        # Single mapping
        dest3 = self.root / "out3.py"
        ret = cli.main(["write", f"{src1}:{dest3}"])
        self.assertEqual(ret, 0)
        self.assertEqual(dest3.read_text(encoding="utf-8"), "print('one')")


if __name__ == "__main__":
    unittest.main()
