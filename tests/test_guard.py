"""Права по этапам: что закрыто, что открыто и всегда ли есть текст отказа."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import sub

guard = sub("sdlc_guard")
stage_mod = sub("sdlc_stage")


class GuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "design.md").write_text("# План\n", encoding="utf-8")

    def allowed(self, stage: str, tool: str, args: dict | None = None, **kwargs) -> bool:
        return guard.check(stage, tool, args or {}, self.root, self.root, **kwargs).allowed

    def test_design_blocks_execution_tools(self) -> None:
        for tool in ("terminal", "execute_code", "browser_exec", "computer_use"):
            self.assertFalse(self.allowed(stage_mod.DESIGN, tool), tool)

    def test_design_allows_reading(self) -> None:
        for tool in ("read_file", "search_files", "todo_list", "clarify", "delegate_task"):
            self.assertTrue(self.allowed(stage_mod.DESIGN, tool), tool)

    def test_design_allows_writing_the_plan(self) -> None:
        self.assertTrue(self.allowed(stage_mod.DESIGN, "write_file", {"path": "design.md"}))
        self.assertTrue(self.allowed(
            stage_mod.DESIGN, "patch", {"path": str(self.root / "design.md")}))

    def test_design_blocks_code_writes(self) -> None:
        for path in ("src/app.py", "notes.py", "tests/test_new.py"):
            self.assertFalse(self.allowed(stage_mod.DESIGN, "write_file", {"path": path}), path)

    def test_design_blocks_path_escaping_the_project(self) -> None:
        self.assertFalse(self.allowed(
            stage_mod.DESIGN, "write_file", {"path": "../../design.md"}))
        self.assertFalse(self.allowed(stage_mod.DESIGN, "write_file", {"path": "/tmp/design.md"}))

    def test_missing_path_is_allowed_and_left_to_the_tool(self) -> None:
        self.assertTrue(self.allowed(stage_mod.DESIGN, "write_file", {}))

    def test_code_allows_writes_and_terminal(self) -> None:
        self.assertTrue(self.allowed(stage_mod.CODE, "write_file", {"path": "src/app.py"}))
        self.assertTrue(self.allowed(stage_mod.CODE, "terminal"))

    def test_code_still_blocks_unlisted_tools(self) -> None:
        self.assertFalse(self.allowed(stage_mod.CODE, "browser_exec"))

    def test_extra_tools_extend_the_list(self) -> None:
        self.assertFalse(self.allowed(stage_mod.DESIGN, "mcp_query"))
        self.assertTrue(self.allowed(stage_mod.DESIGN, "mcp_query",
                                     extra_tools=frozenset({"mcp_query"})))

    def test_every_refusal_has_a_message(self) -> None:
        """Блок без текста ядро отбрасывает молча: пустой `message` равен выключенной защите."""
        cases = [("terminal", {}), ("write_file", {"path": "src/app.py"}),
                 ("browser_exec", {}), ("mcp_query", {})]
        for tool, args in cases:
            verdict = guard.check(stage_mod.DESIGN, tool, args, self.root, self.root)
            self.assertFalse(verdict.allowed, tool)
            self.assertGreater(len(verdict.message), 40, tool)
            self.assertNotIn("  ", verdict.message)


if __name__ == "__main__":
    unittest.main()
