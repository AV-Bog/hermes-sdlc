"""Спайк M0: плагин-пробник. Ничего не решает, только пишет журнал и блокирует.

Отвечает на вопросы из `docs/decisions.md` §14: работает ли `block` из `pre_tool_call` в `-z`,
доходит ли `pre_llm_call` до модели (по телу запроса в `pre_api_request`), снимает ли `--yolo`
хуки, закрывает ли белый список обход через `browser_exec`.

Управление - переменными окружения: `SDLC_SPIKE_BLOCK` (чёрный список), `SDLC_SPIKE_ALLOW`
(белый список, если задан, отменяет чёрный), `SDLC_SPIKE_MARKER`, `SDLC_SPIKE_NUDGE`,
`SDLC_SPIKE_JOURNAL`. Журнал - JSONL, по строке на событие. Плагин не падает: ошибки
глотаются, потому что цена падения - сорванный прогон.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PLUGIN_ID = "sdlc-spike"


def _home() -> Path:
    raw = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    return Path(raw)


def _journal_path() -> Path:
    override = os.environ.get("SDLC_SPIKE_JOURNAL")
    if override:
        return Path(override)
    return _home() / "spike" / "journal.jsonl"


def _blocked_tools() -> set[str]:
    raw = os.environ.get("SDLC_SPIKE_BLOCK", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _allowed_tools() -> set[str]:
    """Белый список: если задан - разрешено ровно перечисленное, остальное блокируется."""
    raw = os.environ.get("SDLC_SPIKE_ALLOW", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _marker() -> str:
    return os.environ.get("SDLC_SPIKE_MARKER", "SPIKE-MARKER")


def _nudge_budget() -> int:
    try:
        return max(0, int(os.environ.get("SDLC_SPIKE_NUDGE", "0") or 0))
    except ValueError:
        return 0


_NUDGES: Dict[str, int] = {}


def _log(hook: str, **fields: Any) -> None:
    """Одна строка журнала. Ошибки записи не должны ломать прогон."""
    try:
        path = _journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record: Dict[str, Any] = {"ts": round(time.time(), 3), "pid": os.getpid(), "hook": hook}
        record.update({key: value for key, value in fields.items() if value not in (None, "")})
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 - журнал не должен ронять ход
        pass


def _text_of(node: Any) -> str:
    """Текст из структуры сообщений любого вида: строка, список частей, объект."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(_text_of(item) for item in node)
    if isinstance(node, dict):
        return "\n".join(_text_of(value) for value in node.values())
    return ""


# --- хуки -------------------------------------------------------------------


def on_session_start(**kwargs: Any) -> None:
    _log("on_session_start", session_id=kwargs.get("session_id"),
         platform=kwargs.get("platform"), model=kwargs.get("model"))


def pre_llm_call(**kwargs: Any) -> Optional[Dict[str, str]]:
    """Вставка в контекст. Возвращается `{"context": ...}` - это официальная форма."""
    marker = _marker()
    _log("pre_llm_call", is_first_turn=kwargs.get("is_first_turn"),
         session_id=kwargs.get("session_id"), injected=marker)
    return {"context": f"Метка спайка: {marker}. Повтори её в ответе."}


def pre_api_request(**kwargs: Any) -> None:
    """Проверка, что метка действительно ушла в модель: смотрим на тело запроса."""
    marker = _marker()
    messages: List[Any] = kwargs.get("request_messages") or []
    history: List[Any] = kwargs.get("conversation_history") or []
    system_prompt = kwargs.get("system_prompt") or ""
    _log("pre_api_request",
         message_count=kwargs.get("message_count"),
         marker_in_request=marker in _text_of(messages),
         marker_in_history=marker in _text_of(history),
         marker_in_system=marker in _text_of(system_prompt))


def pre_tool_call(tool_name: str = "", args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Optional[Dict[str, str]]:
    allowed = _allowed_tools()
    blocked = _blocked_tools()
    args = args if isinstance(args, dict) else {}
    if allowed:
        deny = tool_name not in allowed
        reason = f"разрешено только: {', '.join(sorted(allowed))}"
    else:
        deny = tool_name in blocked
        reason = f"инструмент {tool_name} в списке запрещённых"
    _log("pre_tool_call", tool=tool_name, task_id=kwargs.get("task_id"),
         session_id=kwargs.get("session_id"), blocked=deny, mode=("allow" if allowed else "deny"),
         arg_keys=",".join(sorted(args))[:120])
    if deny:
        return {"action": "block",
                "message": f"[{_marker()}] вызов {tool_name} заблокирован плагином {PLUGIN_ID}: {reason}"}
    return None


def post_tool_call(tool_name: str = "", result: Any = None, **kwargs: Any) -> None:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    _log("post_tool_call", tool=tool_name, task_id=kwargs.get("task_id"),
         result_head=(text or "")[:160])


def pre_verify(**kwargs: Any) -> Optional[Dict[str, str]]:
    """Проверяет, что хук вызывается и что `continue` продлевает работу. Бюджет продолжений
    свой на каждую задачу: у родителя и субагента разные `task_id`."""
    task = str(kwargs.get("task_id") or "main")
    left = _NUDGES.setdefault(task, _nudge_budget())
    _log("pre_verify", task_id=kwargs.get("task_id"), session_id=kwargs.get("session_id"),
         nudges_left=left)
    if left > 0:
        _NUDGES[task] = left - 1
        _log("pre_verify_nudge", task_id=kwargs.get("task_id"), nudges_left=left - 1)
        return {"action": "continue",
                "message": "СПАЙК: проверка не выполнена - продолжи работу и покажи вывод проверки."}
    return None


def subagent_start(**kwargs: Any) -> None:
    _log("subagent_start", task_id=kwargs.get("task_id"), session_id=kwargs.get("session_id"))


def subagent_stop(**kwargs: Any) -> None:
    _log("subagent_stop", task_id=kwargs.get("task_id"), session_id=kwargs.get("session_id"))


def register(ctx) -> None:
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("pre_api_request", pre_api_request)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("pre_verify", pre_verify)
    ctx.register_hook("subagent_start", subagent_start)
    ctx.register_hook("subagent_stop", subagent_stop)
