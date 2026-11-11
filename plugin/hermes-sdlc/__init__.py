"""Плагин hermes-sdlc: этапы разработки и блокировка несовместимых действий.

Этап выводится из файлов проекта (`sdlc_stage.py`), права выдаются закрытым списком
инструментов на этап (`sdlc_guard.py`), корень проекта считается детерминированно
(`sdlc_root.py`). Режимы: `advisory` считает и напоминает, `enforce` блокирует, `off` не
регистрирует хуки.

Правило блокировки: ответ `{"action": "block"}` без непустого `message` ядро Hermes молча
отбрасывает (`hermes_cli/plugins.py:1826`), то есть забытый текст означает выключенную защиту.
Поэтому текст отказа строится всегда и проверяется тестом.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .sdlc_guard import check, stage_label
from .sdlc_root import resolve_root
from .sdlc_stage import DESIGN, DESIGN_FILE, detect_stage

VERSION = "0.1.0"
MARKER = "sdlc-loaded.json"
LOG = "sdlc-log.jsonl"
MODES = ("off", "advisory", "enforce")

_SKILL_BODY: Optional[str] = None
_COUNTERS: Dict[str, int] = {}


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"))


def _log(event: str, **fields: Any) -> None:
    """Одна строка журнала. Ошибка записи не должна ломать ход агента."""
    try:
        path = _home() / LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": round(time.time(), 3), "event": event}
        record.update({key: value for key, value in fields.items() if value not in (None, "")})
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 - журнал не роняет ход
        pass


def _write_marker(mode: str) -> None:
    """Отметка о загрузке: по ней стенд отличает прогон с плагином от пустой базы."""
    try:
        (_home() / MARKER).write_text(
            json.dumps({"mode": mode, "version": VERSION}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _skill_body() -> str:
    """Тело `SKILL.md` без шапки: один и тот же текст в плечах `skill`, `advisory`, `enforce`."""
    global _SKILL_BODY
    if _SKILL_BODY is None:
        try:
            text = (Path(__file__).parent / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4:].lstrip("\n")
        _SKILL_BODY = text
    return _SKILL_BODY


def _stage_line(root: Path) -> str:
    inspection = detect_stage(root)
    label = stage_label(inspection.stage)
    if inspection.stage == DESIGN:
        blocked = (f"запись любых файлов кроме {DESIGN_FILE}, запуск команд, исполнение кода")
    else:
        blocked = "правка тестов, пришедших в проект, и создание файлов вне списка плана"
    return (f"\n\n## Где вы сейчас\n\nЭтап: {label}. Причина: {inspection.reason}.\n"
            f"Закрыто до смены этапа: {blocked}.\n")


def register(ctx: Any) -> None:
    mode = str(ctx.get_config("mode") or "enforce").strip().lower()
    if mode not in MODES:
        _log("mode_unknown", value=mode)
        mode = "enforce"
    if mode == "off":
        _log("disabled")
        return

    root_setting = ctx.get_config("root")
    extra = ctx.get_config("extra_tools") or ""
    extra_tools = frozenset(part.strip() for part in str(extra).split(",") if part.strip())

    def _root() -> Path:
        return resolve_root(Path.cwd(), root_setting)

    def on_session_start(**kwargs: Any) -> None:
        _write_marker(mode)
        _log("session_start", mode=mode, session_id=kwargs.get("session_id"),
             model=kwargs.get("model"), platform=kwargs.get("platform"), root=str(_root()))

    def pre_llm_call(**kwargs: Any) -> Optional[Dict[str, str]]:
        """Строка «этап, что закрыто, чего ждём» в каждый ход: её нельзя не увидеть."""
        try:
            return {"context": _skill_body() + _stage_line(_root())}
        except Exception as exc:  # noqa: BLE001 - подсказка не должна ронять ход
            _log("error", hook="pre_llm_call", error=repr(exc))
            return None

    def pre_tool_call(tool_name: str = "", args: Optional[Dict[str, Any]] = None,
                      **kwargs: Any) -> Optional[Dict[str, str]]:
        try:
            root = _root()
            inspection = detect_stage(root)
            verdict = check(inspection.stage, tool_name, args or {}, root, Path.cwd(), extra_tools)
        except Exception as exc:  # noqa: BLE001 - ошибка своего кода закрывает действие (§9)
            _log("error", hook="pre_tool_call", tool=tool_name, error=repr(exc))
            return {"action": "block",
                    "message": f"Плагин hermes-sdlc упал на проверке {tool_name}: {exc!r}. "
                               f"Это сбой плагина, а не запрет этапа: сообщите о нём человеку."}
        if verdict.allowed:
            return None
        key = f"{inspection.stage}:{tool_name}"
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1
        _log("blocked" if mode == "enforce" else "advisory", tool=tool_name,
             stage=inspection.stage, count=_COUNTERS[key], task_id=kwargs.get("task_id"))
        if mode == "advisory":
            return None
        return {"action": "block", "message": verdict.message}

    def post_tool_call(tool_name: str = "", **kwargs: Any) -> None:
        _COUNTERS["calls"] = _COUNTERS.get("calls", 0) + 1

    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    _log("registered", mode=mode, version=VERSION, extra_tools=sorted(extra_tools))
