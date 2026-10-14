# -*- coding: utf-8 -*-
import io
import sys
import json
import time
import socket
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from agentbox import worker
from agentbox import client


class TestDaemonProtocol(unittest.TestCase):
    def test_daemon_event_writer(self):
        buf = io.StringIO()
        writer = worker.DaemonEventWriter("req-1", "stdout", buf)
        written = writer.write("hello world\n")
        self.assertEqual(written, 12)

        raw = buf.getvalue().strip()
        data = json.loads(raw)
        self.assertEqual(data["id"], "req-1")
        self.assertEqual(data["event"], "stdout")
        self.assertEqual(data["data"], "hello world\n")

    def test_handle_daemon_mode_ping_and_shutdown(self):
        # Prepare mock stdin with ping then shutdown
        req_ping = json.dumps({"id": "p1", "action": "ping"})
        req_shutdown = json.dumps({"id": "s1", "action": "shutdown"})
        mock_stdin = io.StringIO(f"{req_ping}\n{req_shutdown}\n")
        mock_stdout = io.StringIO()

        with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout), patch("sys.__stdout__", mock_stdout):
            worker.handle_daemon_mode(idle_timeout=5)

        lines = [json.loads(line) for line in mock_stdout.getvalue().strip().split("\n") if line]
        self.assertTrue(len(lines) >= 3)
        self.assertEqual(lines[0]["event"], "ready")
        self.assertEqual(lines[1]["id"], "p1")
        self.assertEqual(lines[1]["event"], "pong")
        self.assertEqual(lines[2]["id"], "s1")
        self.assertEqual(lines[2]["event"], "exit")
        self.assertEqual(lines[2]["code"], 0)

    def test_handle_daemon_mode_action_execution(self):
        with tempfile.TemporaryDirectory() as td:
            sample_file = Path(td) / "sample.txt"
            sample_file.write_text("line one\nline two\n", encoding="utf-8")

            req_view = json.dumps({
                "id": "v1",
                "action": "view",
                "args": {"path": str(sample_file), "start": 1, "end": 2}
            })
            req_shutdown = json.dumps({"id": "s2", "action": "shutdown"})
            mock_stdin = io.StringIO(f"{req_view}\n{req_shutdown}\n")
            mock_stdout = io.StringIO()

            with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout), patch("sys.__stdout__", mock_stdout):
                worker.handle_daemon_mode(idle_timeout=5)

            lines = [json.loads(line) for line in mock_stdout.getvalue().strip().split("\n") if line]
            events = [l.get("event") for l in lines]
            self.assertIn("ready", events)
            self.assertIn("stdout", events)
            self.assertIn("exit", events)

            # Check that line one appeared in stdout data
            stdout_texts = "".join(l.get("data", "") for l in lines if l.get("event") == "stdout")
            self.assertIn("line one", stdout_texts)

    def test_cmd_find_fn(self):
        with tempfile.TemporaryDirectory() as td:
            mod_file = Path(td) / "models.py"
            mod_file.write_text("class BankAccount:\n    def get_balance(self) -> int:\n        return 100\n", encoding="utf-8")

            buf = io.StringIO()
            with patch("sys.stdout", buf):
                worker.cmd_find_fn("BankAccount", path=td)
            out = buf.getvalue()
            self.assertIn("FOUND SYMBOLS", out)
            self.assertIn("class BankAccount", out)
            self.assertIn("models.py:1", out)

            buf2 = io.StringIO()
            with patch("sys.stdout", buf2):
                worker.cmd_find_fn("get_balance", path=td)
            out2 = buf2.getvalue()
            self.assertIn("def get_balance", out2)


class TestBridgeClient(unittest.TestCase):
    def test_is_bridge_alive_false_on_closed_port(self):
        # Port 1 is not running our bridge
        alive = client._is_bridge_alive({"port": 1, "token": "abc"})
        self.assertFalse(alive)

    def test_status_and_stop_daemon_when_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("agentbox.client.BRIDGE_RUN_DIR", Path(td)):
                ret_status = client.status_daemon()
                self.assertEqual(ret_status, 0)

                ret_stop = client.stop_daemon()
                self.assertEqual(ret_stop, 0)

    def test_stop_daemon_removes_info_file(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            info_file = run_dir / "bridge_testhost.json"
            info_file.write_text(json.dumps({
                "port": 9999,
                "token": "tok123",
                "pid": 12345,
                "host": "testhost",
                "started": time.time()
            }), encoding="utf-8")

            with patch("agentbox.client.BRIDGE_RUN_DIR", run_dir):
                client.stop_daemon("testhost")
                self.assertFalse(info_file.exists())


if __name__ == "__main__":
    unittest.main()
