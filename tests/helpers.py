"""Загрузка плагина так же, как это делает Hermes, и поддельный контекст плагина.

Каталог плагина назван с дефисом (`hermes-sdlc`), поэтому обычным `import` его не взять.
Ядро Hermes грузит его как пакет `hermes_plugins.<slug>` (`hermes_cli/plugins_loader.py:436`),
и относительные импорты между модулями работают только при такой загрузке. Тесты повторяют
этот путь, чтобы проверять ровно тот код, который попадёт в Hermes.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO / "plugin" / "hermes-sdlc"
PKG = "hermes_sdlc_under_test"


def load():
    if PKG in sys.modules:
        return sys.modules[PKG]
    spec = importlib.util.spec_from_file_location(
        PKG, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = PKG
    sys.modules[PKG] = module
    spec.loader.exec_module(module)
    return module


def sub(name: str):
    load()
    return importlib.import_module(f"{PKG}.{name}")


class FakeCtx:
    """Минимальный контекст плагина: только то, чем плагин действительно пользуется."""

    def __init__(self, settings: dict | None = None) -> None:
        self.settings = dict(settings or {})
        self.hooks: dict = {}

    def get_config(self, key: str, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name: str, callback) -> None:
        self.hooks[name] = callback


DESIGN_OK = """# План

## Функциональность

Заметки с необязательной категорией: добавить, показать список, фильтр по категории, сводка.

## Требования

- Формат хранения совместим со старым файлом.
- Исходные тесты не меняются.

## Архитектура

Хранилище одно, чтение и запись идут через него; фильтрация в памяти, без индексов.

Файлы:
- `src/store.py`
- src/cli.py  (новый модуль разбора аргументов)
- tests/test_store.py

## Вопросы и допущения

- Категория сравнивается точно, без учёта регистра: уточнить у человека.
"""

DESIGN_NO_FILES = """## Функциональность

Список заметок.

## Требования

Старый формат читается.

## Архитектура

Сервер принимает задачи и складывает в очередь.

## Вопросы и допущения

Нет.
"""
