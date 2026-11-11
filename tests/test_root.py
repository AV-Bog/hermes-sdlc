"""Корень проекта: порядок источников и разбор путей."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import sub

root_mod = sub("sdlc_root")


class ResolveRootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def test_git_root_found_from_subdirectory(self) -> None:
        (self.base / ".git").mkdir()
        deep = self.base / "src" / "inner"
        deep.mkdir(parents=True)
        self.assertEqual(root_mod.resolve_root(deep, None, {}), self.base)

    def test_git_file_counts_as_root_for_worktree(self) -> None:
        (self.base / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        child = self.base / "pkg"
        child.mkdir()
        self.assertEqual(root_mod.resolve_root(child, None, {}), self.base)

    def test_without_git_the_start_directory_is_the_root(self) -> None:
        deep = self.base / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(root_mod.resolve_root(deep, None, {}), deep)

    def test_config_beats_env_and_git(self) -> None:
        (self.base / ".git").mkdir()
        other = self.base / "other"
        other.mkdir()
        env = {root_mod.ROOT_ENV: str(self.base)}
        self.assertEqual(root_mod.resolve_root(self.base, str(other), env), other)

    def test_env_used_when_config_empty(self) -> None:
        (self.base / ".git").mkdir()
        other = self.base / "other"
        other.mkdir()
        self.assertEqual(root_mod.resolve_root(self.base, "", {root_mod.ROOT_ENV: str(other)}), other)

    def test_relative_config_root_resolves_from_start(self) -> None:
        inner = self.base / "project"
        inner.mkdir()
        self.assertEqual(root_mod.resolve_root(self.base, "project", {}), inner)

    def test_blank_sources_are_ignored(self) -> None:
        self.assertEqual(root_mod.resolve_root(self.base, "   ", {root_mod.ROOT_ENV: "  "}), self.base)


if __name__ == "__main__":
    unittest.main()
