"""Регистрация хуков, отметка о загрузке и режимы: advisory молчит, enforce блокирует."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import DESIGN_OK, FakeCtx, load

plugin = load()


class PluginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.root = self.base / "project"
        self.home.mkdir()
        self.root.mkdir()
        patcher = mock.patch.dict(os.environ, {"HERMES_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Хуки берут рабочий каталог процесса: относительный `design.md` в вызове инструмента
        # разрешается от него, как это делает сам инструмент.
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def ctx(self, mode: str, **settings) -> FakeCtx:
        return FakeCtx({"mode": mode, "root": str(self.root), **settings})

    def test_hooks_registered_and_marker_written(self) -> None:
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        self.assertEqual(
            sorted(ctx.hooks), ["on_session_start", "post_tool_call", "pre_llm_call", "pre_tool_call"])
        ctx.hooks["on_session_start"](session_id="s1", model="m", platform="cli")
        marker = json.loads((self.home / plugin.MARKER).read_text(encoding="utf-8"))
        self.assertEqual(marker["mode"], "enforce")
        self.assertEqual(marker["version"], plugin.VERSION)

    def test_off_mode_registers_nothing(self) -> None:
        ctx = self.ctx("off")
        plugin.register(ctx)
        self.assertEqual(ctx.hooks, {})
        self.assertFalse((self.home / plugin.MARKER).exists())

    def test_unknown_mode_falls_back_to_enforce(self) -> None:
        ctx = self.ctx("strict-ish")
        plugin.register(ctx)
        ctx.hooks["on_session_start"]()
        marker = json.loads((self.home / plugin.MARKER).read_text(encoding="utf-8"))
        self.assertEqual(marker["mode"], "enforce")

    def test_enforce_blocks_code_before_plan(self) -> None:
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        result = ctx.hooks["pre_tool_call"](tool_name="write_file", args={"path": "src/app.py"})
        self.assertEqual(result["action"], "block")
        self.assertIn("design.md", result["message"])

    def test_enforce_lets_the_plan_be_written(self) -> None:
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        self.assertIsNone(
            ctx.hooks["pre_tool_call"](tool_name="write_file", args={"path": "design.md"}))
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="read_file", args={"path": "notes.py"}))

    def test_enforce_blocks_execution_before_plan(self) -> None:
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        self.assertEqual(
            ctx.hooks["pre_tool_call"](tool_name="terminal", args={})["action"], "block")

    def test_code_writes_allowed_after_plan(self) -> None:
        (self.root / "design.md").write_text(DESIGN_OK, encoding="utf-8")
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        self.assertIsNone(
            ctx.hooks["pre_tool_call"](tool_name="write_file", args={"path": "src/store.py"}))

    def test_advisory_counts_but_does_not_block(self) -> None:
        ctx = self.ctx("advisory")
        plugin.register(ctx)
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="write_file", args={"path": "a.py"}))
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="terminal", args={}))
        log = (self.home / plugin.LOG).read_text(encoding="utf-8")
        self.assertEqual(log.count('"event": "advisory"'), 2)

    def test_context_carries_stage_line(self) -> None:
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        context = ctx.hooks["pre_llm_call"]()["context"]
        self.assertIn("Этап: план", context)
        self.assertIn("## 1. Разберись в задаче", context)

    def test_context_switches_with_stage(self) -> None:
        (self.root / "design.md").write_text(DESIGN_OK, encoding="utf-8")
        ctx = self.ctx("enforce")
        plugin.register(ctx)
        self.assertIn("Этап: код", ctx.hooks["pre_llm_call"]()["context"])

    def test_extra_tools_from_config(self) -> None:
        ctx = self.ctx("enforce", extra_tools="mcp_query")
        plugin.register(ctx)
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="mcp_query", args={}))

    def test_broken_root_does_not_crash_hooks(self) -> None:
        ctx = FakeCtx({"mode": "enforce", "root": str(self.base / "missing" / "deeper")})
        plugin.register(ctx)
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="read_file", args={}))
        self.assertIn("Этап:", ctx.hooks["pre_llm_call"]()["context"])


if __name__ == "__main__":
    unittest.main()
