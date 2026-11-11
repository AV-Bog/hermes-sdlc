"""Определение этапа и разбор списка файлов из `design.md`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import DESIGN_NO_FILES, DESIGN_OK, sub

stage = sub("sdlc_stage")


class InspectTest(unittest.TestCase):
    def test_no_design_file_means_design_stage(self) -> None:
        result = stage.inspect(None)
        self.assertEqual(result.stage, stage.DESIGN)
        self.assertIn("design.md", result.reason)

    def test_missing_sections_keep_design_stage(self) -> None:
        result = stage.inspect("## Функциональность\n\nЗаметки.\n")
        self.assertEqual(result.stage, stage.DESIGN)
        self.assertIn("требования", result.reason)
        self.assertIn("архитектура", result.reason)

    def test_full_plan_switches_to_code(self) -> None:
        result = stage.inspect(DESIGN_OK)
        self.assertEqual(result.stage, stage.CODE)
        self.assertEqual(result.files, ("src/store.py", "src/cli.py", "tests/test_store.py"))

    def test_architecture_without_file_list_keeps_design_stage(self) -> None:
        result = stage.inspect(DESIGN_NO_FILES)
        self.assertEqual(result.stage, stage.DESIGN)
        self.assertIn("нет списка файлов", result.reason)

    def test_bold_section_names_accepted(self) -> None:
        text = ("**Функциональность**\n\nЗаметки.\n\n**Требования**\n\nСтарый файл читается.\n\n"
                "**Архитектура**\n\n- src/app.py\n\n**Вопросы и допущения**\n\nНет.\n")
        result = stage.inspect(text)
        self.assertEqual(result.missing_sections, ())
        self.assertEqual(result.stage, stage.CODE)

    def test_prose_bullets_are_not_files(self) -> None:
        text = DESIGN_NO_FILES.replace(
            "Сервер принимает задачи и складывает в очередь.",
            "Сервер принимает задачи и складывает в очередь.\n\nФайлы:\n- сервер и очередь\n- 0.1.0")
        self.assertEqual(stage.declared_files(text), ())

    def test_backticks_and_trailing_comment_are_stripped(self) -> None:
        text = DESIGN_OK
        self.assertIn("src/cli.py", stage.declared_files(text))

    def test_duplicates_collapse(self) -> None:
        text = DESIGN_OK.replace("- tests/test_store.py", "- src/store.py\n- tests/test_store.py")
        files = stage.declared_files(text)
        self.assertEqual(files.count("src/store.py"), 1)

    def test_links_are_not_paths(self) -> None:
        text = DESIGN_NO_FILES.replace("Сервер принимает задачи и складывает в очередь.",
                                       "- https://example.com/queue.py")
        self.assertEqual(stage.declared_files(text), ())


class DetectStageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_missing_file(self) -> None:
        self.assertEqual(stage.detect_stage(self.root).stage, stage.DESIGN)

    def test_file_appears_and_stage_moves(self) -> None:
        (self.root / "design.md").write_text(DESIGN_OK, encoding="utf-8")
        self.assertEqual(stage.detect_stage(self.root).stage, stage.CODE)

    def test_cache_notices_edited_file(self) -> None:
        path = self.root / "design.md"
        path.write_text(DESIGN_NO_FILES, encoding="utf-8")
        self.assertEqual(stage.detect_stage(self.root).stage, stage.DESIGN)
        path.write_text(DESIGN_OK, encoding="utf-8")
        self.assertEqual(stage.detect_stage(self.root).stage, stage.CODE)


if __name__ == "__main__":
    unittest.main()
