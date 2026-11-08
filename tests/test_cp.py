# -*- coding: utf-8 -*-
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from agentbox.cli import main, parse_target_path
from agentbox import config, worker


class TestCpCommand(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.td.name).resolve()

    def tearDown(self):
        self.td.cleanup()

    def test_parse_target_path(self):
        # Local paths
        self.assertEqual(parse_target_path("foo.txt"), (None, "foo.txt"))
        self.assertEqual(parse_target_path("local:foo.txt"), (None, "foo.txt"))
        self.assertEqual(parse_target_path(":foo.txt"), (None, "foo.txt"))

        # Named targets
        self.assertEqual(parse_target_path("pyferro:/var/www/app.whl"), ("pyferro", "/var/www/app.whl"))
        self.assertEqual(parse_target_path("stage:dist/pkg.tar.gz"), ("stage", "dist/pkg.tar.gz"))

        # Windows absolute paths with drive letter
        self.assertEqual(parse_target_path(r"C:\Windows\System32"), (None, r"C:\Windows\System32"))
        self.assertEqual(parse_target_path("D:/my/project/file.py"), (None, "D:/my/project/file.py"))

    def test_cp_local_to_local_file(self):
        src = self.test_dir / "source.bin"
        # Binary data test
        binary_payload = b"\x00\xff\xfe\xfd\x01\x02\x03hello\r\nworld\x00"
        src.write_bytes(binary_payload)

        dest = self.test_dir / "dest.bin"

        ret = main(["cp", str(src), str(dest)])
        self.assertEqual(ret, 0)
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), binary_payload)

    def test_cp_local_to_local_directory(self):
        src = self.test_dir / "data.whl"
        src.write_bytes(b"PK\x03\x04wheel_content")

        dest_dir = self.test_dir / "output_dir"
        dest_dir.mkdir()

        ret = main(["cp", str(src), str(dest_dir)])
        self.assertEqual(ret, 0)
        expected_file = dest_dir / "data.whl"
        self.assertTrue(expected_file.is_file())
        self.assertEqual(expected_file.read_bytes(), b"PK\x03\x04wheel_content")

    def test_cp_src_not_found(self):
        missing = self.test_dir / "nonexistent.txt"
        dest = self.test_dir / "dest.txt"
        ret = main(["cp", str(missing), str(dest)])
        self.assertEqual(ret, 1)
        self.assertFalse(dest.exists())

    def test_cp_blocked_by_readonly_target(self):
        src = self.test_dir / "data.txt"
        src.write_text("important data", encoding="utf-8")

        with patch("agentbox.cli.resolve_target") as mock_resolve:
            mock_resolve.return_value = {
                "name": "prod",
                "host": "prod.server",
                "cwd": "/var/app",
                "venv": "",
                "readonly": True
            }
            ret = main(["cp", str(src), "prod:/var/app/data.txt"])
            self.assertEqual(ret, 1)

    def test_cp_remote_to_remote_mocked(self):
        import base64
        test_bytes = b"remote-archive-content-12345"
        b64_data = base64.b64encode(test_bytes).decode("ascii")

        with patch("agentbox.cli.resolve_target") as mock_resolve, \
             patch("agentbox.cli.execute_action") as mock_exec:

            def resolve_side_effect(tgt_name, cfg):
                if tgt_name == "src_tgt":
                    return {"name": "src_tgt", "host": "srv1", "cwd": "/app1", "venv": "", "readonly": False}
                if tgt_name == "dest_tgt":
                    return {"name": "dest_tgt", "host": "srv2", "cwd": "/app2", "venv": "", "readonly": False}
                return {"name": "local", "host": "", "cwd": "", "venv": "", "readonly": False}

            mock_resolve.side_effect = resolve_side_effect

            def exec_side_effect(host, cwd, action, args, capture=False):
                if action == "file_read_b64":
                    return 0, b64_data, ""
                if action == "file_write_b64":
                    self.assertEqual(args["data_b64"], b64_data)
                    return 0, "OK\n", ""
                return 0, "", ""

            mock_exec.side_effect = exec_side_effect

            ret = main(["cp", "src_tgt:dist/app.whl", "dest_tgt:/opt/deploy/"])
            self.assertEqual(ret, 0)
            self.assertEqual(mock_exec.call_count, 2)


if __name__ == "__main__":
    unittest.main()
