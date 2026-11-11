"""Этап работы выводится из файлов проекта, а не хранится счётчиком.

В M1 два этапа: `design` и `code`. Вход в `code` - `design.md` с обязательными разделами и
списком файлов. Третий этап, `verify`, появится в M2, когда плагин сможет сам сверить
объявленные файлы с диском: пока сверки нет, этап по ней не определить.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

DESIGN = "design"
CODE = "code"

DESIGN_FILE = "design.md"
ARCH_SECTION = "архитектура"

# Разделы, без которых план не считается планом (§5 docs/decisions.md).
SECTIONS: Tuple[str, ...] = ("функциональность", "требования", "архитектура", "вопросы и допущения")

# Расширения, по которым строка списка считается объявленным файлом. Список закрытый: иначе
# строкой пути становится версия вида `0.1.0` или адрес сайта, и этап переключается случайно.
CODE_EXTENSIONS = frozenset({
    ".py", ".pyx", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".rb", ".java",
    ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".php", ".sh", ".sql", ".html",
    ".css", ".scss", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".txt", ".md", ".adoc",
})

_HEADER = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
_BOLD_HEADER = re.compile(r"^\s{0,3}\*\*(.+?)\*\*\s*:?\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_PATH_LIKE = re.compile(r"^[A-Za-z0-9_./-]+$")


@dataclass(frozen=True)
class Inspection:
    """Что показал осмотр проекта: этап, причина и объявленные файлы."""

    stage: str
    reason: str
    files: Tuple[str, ...] = ()
    missing_sections: Tuple[str, ...] = ()


def _normalise(text: str) -> str:
    return " ".join(text.replace("ё", "е").replace("Ё", "Е").split()).strip(" :#").lower()


def sections(text: str) -> Tuple[Tuple[str, int], ...]:
    """Заголовки разделов в порядке появления: (нормализованное имя, номер строки).

    Принимаются и markdown-заголовки (`## Требования`), и выделенная строка (`**Требования**`):
    агент пишет план как ему удобно, и требовать один вид разметки значило бы блокировать
    правильный план из-за оформления.
    """
    found = []
    for index, line in enumerate(text.splitlines()):
        match = _HEADER.match(line)
        name = match.group(2) if match else None
        if name is None:
            bold = _BOLD_HEADER.match(line)
            name = bold.group(1) if bold else None
        if name is None:
            continue
        normalised = _normalise(name)
        if normalised:
            found.append((normalised, index))
    return tuple(found)


def _section_body(text: str, headers: Tuple[Tuple[str, int], ...], name: str) -> str:
    lines = text.splitlines()
    for position, (header, index) in enumerate(headers):
        if header != name:
            continue
        end = headers[position + 1][1] if position + 1 < len(headers) else len(lines)
        return "\n".join(lines[index + 1:end])
    return ""


def _looks_like_path(candidate: str) -> bool:
    if not candidate or candidate.startswith(("http://", "https://")) or ".." in candidate:
        return False
    if not _PATH_LIKE.match(candidate):
        return False
    return Path(candidate).suffix.lower() in CODE_EXTENSIONS


def declared_files(text: str) -> Tuple[str, ...]:
    """Файлы из списка в разделе «Архитектура», в порядке объявления.

    Строка списка - это `- src/parser.py`. Снимаются маркеры списка, обратные кавычки и кавычки;
    хвост после первого пробела отбрасывается, чтобы `- src/app.py (новый)` тоже считался путём.
    """
    headers = sections(text)
    body = _section_body(text, headers, ARCH_SECTION)
    seen, files = set(), []
    for line in body.splitlines():
        match = _BULLET.match(line)
        if not match:
            continue
        raw = match.group(1).strip().strip("`'\"").strip()
        candidate = raw.split()[0].strip("`'\",;").rstrip(".") if raw else ""
        if not _looks_like_path(candidate):
            continue
        normalised = str(Path(candidate))
        if normalised not in seen:
            seen.add(normalised)
            files.append(normalised)
    return tuple(files)


def inspect(text: Optional[str]) -> Inspection:
    """Этап по содержимому `design.md`. `None` значит, что файла нет."""
    if text is None:
        return Inspection(DESIGN, "нет design.md")
    headers = sections(text)
    present = {name for name, _ in headers}
    missing = tuple(section for section in SECTIONS if section not in present)
    if missing:
        return Inspection(DESIGN, "в design.md нет разделов: " + ", ".join(missing),
                          missing_sections=missing)
    files = declared_files(text)
    if not files:
        return Inspection(DESIGN, "в разделе «Архитектура» нет списка файлов")
    return Inspection(CODE, "план объявлен: " + ", ".join(files), files=files)


def detect_stage(root: Path) -> Inspection:
    """Осмотр корня проекта. Читается один файл, поэтому результат кэшируется по времени правки."""
    path = Path(root) / DESIGN_FILE
    try:
        stat = path.stat()
    except OSError:
        _CACHE.pop(str(path), None)
        return inspect(None)
    key = str(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return inspect(None)
    result = inspect(text)
    _CACHE[key] = (stamp, result)
    return result


_CACHE: dict = {}
