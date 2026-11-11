"""Права по этапам: закрытый список инструментов и запрет записи вне объявленного.

Права выдаются не списком запретов, а списком разрешений: чёрный список по именам обходится
новым инструментом, и спайк M0 это показал - субагент записал файл через `browser_exec`,
когда `write_file`, `terminal` и `execute_code` были закрыты. Поэтому всё, чего нет в списке
разрешений, блокируется, включая инструменты, которых в Hermes ещё нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, FrozenSet, Mapping, Optional, Tuple

from .sdlc_stage import CODE, DESIGN, DESIGN_FILE

STAGE_LABEL = {DESIGN: "план", CODE: "код"}

# Чтение и планирование: не пишут файлы и не исполняют код, поэтому разрешены на обоих этапах.
READ_TOOLS: FrozenSet[str] = frozenset({
    "read_file", "search_files", "skill_view", "skills_list", "todo_list", "clarify",
    "web_search", "web_extract",
})

# Инструменты с аргументом `path`: на этапе плана правится только `design.md`.
PATH_TOOLS: FrozenSet[str] = frozenset({"write_file", "patch"})

STAGE_TOOLS: Mapping[str, FrozenSet[str]] = {
    DESIGN: READ_TOOLS | PATH_TOOLS | {"delegate_task"},
    CODE: READ_TOOLS | PATH_TOOLS | {"terminal", "execute_code", "delegate_task"},
}

EXPECTATION = {
    DESIGN: "Сейчас ожидается план: design.md с функциональностью, требованиями, "
            "архитектурой и списком файлов.",
    CODE: "План объявлен, идёт реализация файлов из его списка.",
}


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    message: str = ""


def stage_label(stage: str) -> str:
    return STAGE_LABEL.get(stage, stage)


def target_path(raw: str, root: Path, cwd: Path) -> Optional[Path]:
    """Куда указывает аргумент `path`, с учётом относительных путей от рабочего каталога."""
    text = (raw or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        return candidate.resolve()
    except OSError:
        return None


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def check(
    stage: str,
    tool: str,
    args: Optional[Mapping[str, Any]],
    root: Path,
    cwd: Optional[Path] = None,
    extra_tools: FrozenSet[str] = frozenset(),
) -> Verdict:
    """Можно ли вызывать `tool` на этом этапе. Возвращает причину отказа, если нельзя."""
    allowed = STAGE_TOOLS.get(stage, READ_TOOLS) | set(extra_tools)
    label = stage_label(stage)
    if tool not in allowed:
        return Verdict(False, (
            f"Этап «{label}»: вызов {tool} закрыт. Разрешено: {', '.join(sorted(allowed))}. "
            f"{EXPECTATION.get(stage, '')}").strip())

    if stage == DESIGN and tool in PATH_TOOLS:
        raw = str((args or {}).get("path") or "")
        target = target_path(raw, root, Path(cwd or Path.cwd()))
        if target is not None and target != (Path(root) / DESIGN_FILE).resolve():
            return Verdict(False, (
                f"Этап «{label}»: менять можно только {DESIGN_FILE}, а этот вызов меняет "
                f"{_display(target, Path(root))}. Код пишется после плана: сначала опишите "
                f"в {DESIGN_FILE} функциональность, требования, архитектуру с интерфейсами "
                f"и список файлов."))
    return Verdict(True)
