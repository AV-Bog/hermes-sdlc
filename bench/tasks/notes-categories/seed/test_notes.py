"""Тесты утилиты заметок: поведение, которое должно сохраниться.

Запуск: python3 -m unittest -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

import notes


class NotesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self) -> None:
        os.chdir(self.previous)
        self.tmp.cleanup()

    def cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = notes.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_empty_list(self) -> None:
        code, out, _ = self.cli("list")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_add_prints_id(self) -> None:
        code, out, _ = self.cli("add", "купить", "хлеб")
        self.assertEqual(code, 0)
        self.assertEqual(out, "added 1\n")

    def test_add_keeps_spaces(self) -> None:
        self.cli("add", "позвонить", "в", "банк")
        _, out, _ = self.cli("list")
        self.assertEqual(out, "1\tпозвонить в банк\n")

    def test_ids_grow(self) -> None:
        self.cli("add", "первая")
        self.cli("add", "вторая")
        _, out, _ = self.cli("list")
        self.assertEqual(out, "1\tпервая\n2\tвторая\n")

    def test_add_without_text(self) -> None:
        code, out, err = self.cli("add")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("usage", err)

    def test_search_case_insensitive(self) -> None:
        self.cli("add", "Купить", "Молоко")
        self.cli("add", "позвонить", "маме")
        code, out, _ = self.cli("search", "молок")
        self.assertEqual(code, 0)
        self.assertEqual(out, "1\tКупить Молоко\n")

    def test_search_without_word(self) -> None:
        code, _, err = self.cli("search")
        self.assertEqual(code, 1)
        self.assertIn("usage", err)

    def test_delete_existing(self) -> None:
        self.cli("add", "удалить", "меня")
        code, out, _ = self.cli("delete", "1")
        self.assertEqual(code, 0)
        self.assertEqual(out, "deleted 1\n")
        _, listing, _ = self.cli("list")
        self.assertEqual(listing, "")

    def test_delete_missing(self) -> None:
        code, out, _ = self.cli("delete", "7")
        self.assertEqual(code, 2)
        self.assertEqual(out, "not found 7\n")

    def test_unknown_command(self) -> None:
        code, _, err = self.cli("печатать")
        self.assertEqual(code, 1)
        self.assertIn("usage", err)

    def test_data_survives_between_runs(self) -> None:
        self.cli("add", "заметка")
        with open("notes.json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["next_id"], 2)
        self.assertEqual(data["notes"], [{"id": 1, "text": "заметка"}])

    def test_notes_file_is_readable_json(self) -> None:
        self.cli("add", "текст")
        with open("notes.json", encoding="utf-8") as fh:
            json.load(fh)


if __name__ == "__main__":
    unittest.main()
