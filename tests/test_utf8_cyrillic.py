# -*- coding: utf-8 -*-
"""
Tests for UTF-8 encoding and Cyrillic support across agentbox components.
Validates that Russian / Cyrillic text passes cleanly without turning into '????'.
"""

import io
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentbox import worker
from agentbox import cli


class TestUtf8Cyrillic(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_cyrillic_write_and_append(self):
        target = self.dir_path / "greeting.txt"
        worker.cmd_write(str(target), content="Привет, мир!\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "Привет, мир!\n")

        # Append cyrillic text
        worker.cmd_write(str(target), content="Вторая строка на русском.\n", append=True)
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "Привет, мир!\nВторая строка на русском.\n"
        )

    def test_cyrillic_patch(self):
        target = self.dir_path / "code.py"
        target.write_text('MSG = "русский_текст_1"\n', encoding="utf-8")

        worker.cmd_patch(str(target), "русский_текст_1", "русский_текст_2")
        self.assertEqual(target.read_text(encoding="utf-8"), 'MSG = "русский_текст_2"\n')

        # Check backup file is stored cleanly in backups dir
        bak = worker._get_backup_path(target)
        self.assertTrue(bak.is_file())
        self.assertFalse(target.with_suffix(".py.bak").is_file())
        self.assertEqual(bak.read_text(encoding="utf-8"), 'MSG = "русский_текст_1"\n')
    def test_cyrillic_patch_lines(self):
        target = self.dir_path / "data.txt"
        target.write_text("Заголовок\nСтарый пункт\nКонец\n", encoding="utf-8")

        worker.cmd_patch_lines(str(target), start=2, end=2, content="Новый пункт с кириллицей\n", check_syntax=False)
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "Заголовок\nНовый пункт с кириллицей\nКонец\n"
        )

    def test_cyrillic_batch(self):
        target = self.dir_path / "batch_test.py"
        target.write_text('STATUS = "Черновик"\n', encoding="utf-8")

        batch_steps = [
            {
                "action": "patch",
                "args": {
                    "path": str(target),
                    "old": "Черновик",
                    "new": "Опубликовано",
                    "check_syntax": False
                }
            }
        ]
        worker.cmd_batch(batch_steps)
        self.assertEqual(target.read_text(encoding="utf-8"), 'STATUS = "Опубликовано"\n')

    def test_read_stdin_utf8_from_bytes(self):
        utf8_bytes = "Привет из пайпа".encode("utf-8")
        mock_buffer = io.BytesIO(utf8_bytes)
        mock_stdin = io.StringIO("Привет из пайпа")
        mock_stdin.buffer = mock_buffer

        with patch("sys.stdin", mock_stdin):
            result = worker.read_stdin_utf8()
            self.assertEqual(result, "Привет из пайпа")

    def test_read_stdin_cp1251_fallback(self):
        # Simulate legacy Windows PowerShell 5.1 pipe emitting CP1251 bytes
        cp1251_bytes = "Кириллица в cp1251".encode("cp1251")
        mock_buffer = io.BytesIO(cp1251_bytes)
        mock_stdin = io.StringIO()
        mock_stdin.buffer = mock_buffer

        with patch("sys.stdin", mock_stdin):
            result = worker.read_stdin_utf8()
            self.assertEqual(result, "Кириллица в cp1251")

    def test_prepare_env_utf8_vars(self):
        env, _ = worker.prepare_env_for_cmd(self.dir_path)
        self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")
        self.assertEqual(env.get("LC_ALL"), "C.UTF-8")
        self.assertEqual(env.get("LANG"), "C.UTF-8")

    def test_cli_patch_cyrillic(self):
        target = self.dir_path / "cli_sample.txt"
        target.write_text("старый текст", encoding="utf-8")

        code = cli.main(["patch", str(target), "--old", "старый текст", "--new", "новый текст"])
        self.assertEqual(code, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "новый текст")


if __name__ == "__main__":
    unittest.main()
