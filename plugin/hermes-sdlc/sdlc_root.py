"""Корень проекта: каталог, где лежат `design.md` и `.sdlc/`.

Порядок источников: настройка `root` в конфиге плагина, переменная `HERMES_SDLC_ROOT`, корень
git, текущий каталог. Первый ответ побеждает.

Корень считает плагин, а не агент: плагин обязан давать одинаковый ответ на каждом вызове
сессии, иначе состояние и журнал расползутся по каталогам, а субагент уедет в проект, где
правил не видно. Почему ещё - `docs/decisions.md` §10.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

ROOT_ENV = "HERMES_SDLC_ROOT"


def git_root(start: Path) -> Optional[Path]:
    """Ближайший каталог вверх по дереву, где есть `.git` (каталог или файл worktree)."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _as_dir(value: str, start: Path) -> Optional[Path]:
    text = (value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = start / candidate
    return candidate.resolve()


def resolve_root(
    start: Path,
    config_root: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    """Корень проекта от каталога `start`."""
    environ = os.environ if env is None else env
    start = Path(start).resolve()
    for value in (config_root, environ.get(ROOT_ENV)):
        found = _as_dir(value or "", start)
        if found is not None:
            return found
    found = git_root(start)
    return found if found is not None else start
