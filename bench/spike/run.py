#!/usr/bin/env python3
"""Спайк M0: один сценарий - один прогон `hermes -z` с плагином-пробником.

Задача здесь не решается: проверяется только механизм хуков. Сценарий задаёт, что попросить
у агента и какие инструменты заблокировать; после прогона скрипт сводит журнал плагина.

Запуск:
    python3 bench/spike/run.py --scenario block-all
    python3 bench/spike/run.py --all

Результаты: ~/.hermes/bench/spike/<сценарий>/{transcript.log,journal.jsonl,usage.json,meta.json}
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_HOME = Path.home() / ".hermes"
OUT_ROOT = MAIN_HOME / "bench" / "spike"
HERMES = shutil.which("hermes") or "hermes"

SCENARIOS: dict[str, dict] = {
    "block-all": {
        "prompt": ("Создай в текущем каталоге файл hello.txt с текстом «привет». "
                   "Используй инструмент write_file."),
        "block": "write_file,patch,terminal,execute_code",
    },
    "terminal": {
        "prompt": "Выполни в терминале команду: echo привет. Используй инструмент terminal.",
        "block": "terminal,execute_code",
    },
    "subagent": {
        "prompt": ("Передай задачу субагенту через инструмент delegate_task: субагент должен "
                   "создать в текущем каталоге файл sub.txt с текстом «привет»."),
        "block": "write_file,patch,terminal,execute_code",
    },
    "yolo": {
        "prompt": ("Создай в текущем каталоге файл hello.txt с текстом «привет». "
                   "Используй инструмент write_file."),
        "block": "write_file,patch,terminal,execute_code",
        "yolo": True,
    },
    "verify": {
        "prompt": ("Создай в текущем каталоге файл hello.txt с текстом «привет», прочитай его "
                   "обратно и подтверди, что задача выполнена."),
        "block": "",
    },
    "nudge": {
        "prompt": "Создай в текущем каталоге файл hello.txt с текстом «привет» и сообщи, что готово.",
        "block": "",
        "nudge": 2,
    },
    "allowlist": {
        "prompt": ("Передай задачу субагенту через инструмент delegate_task: субагент должен "
                   "создать в текущем каталоге файл sub.txt с текстом «привет»."),
        "block": "",
        "allow": "read_file,search_files,delegate_task",
    },
}


def build_home(home: Path, plugin_src: Path) -> None:
    """Пустой дом: один плагин, без памяти и встроенных скилов."""
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    # Модель и лимиты - те же, что в стенде: иначе `-z` уходит на провайдера с пустым именем.
    (home / "config.yaml").write_text(
        "model:\n"
        "  default: deepseek-flash\n"
        "  provider: deepseek\n"
        "  base_url: https://api.deepseek.com/v1\n"
        "  api_mode: chat_completions\n"
        "agent:\n"
        "  max_turns: 40\n"
        "  reasoning_effort: medium\n"
        "terminal:\n"
        "  backend: local\n"
        "  cwd: .\n"
        "  timeout: 120\n"
        "tool_loop_guardrails:\n"
        "  warnings_enabled: true\n"
        "  hard_stop_enabled: false\n"
        "  non_interactive_hard_stop_enabled: true\n"
        "memory:\n"
        "  memory_enabled: false\n"
        "  user_profile_enabled: false\n"
        "display:\n"
        "  language: ru\n"
        "  show_reasoning: false\n"
        "  streaming: false\n"
        "  tool_progress: all\n"
        "plugins:\n"
        "  enabled:\n"
        "    - sdlc-spike\n",
        encoding="utf-8")
    env_src = MAIN_HOME / ".env"
    if env_src.is_file():
        shutil.copy2(env_src, home / ".env")
    (home / ".no-bundled-skills").write_text(
        "В этом профиле встроенные скилы не разворачиваются.\n", encoding="utf-8")
    shutil.copytree(plugin_src, home / "plugins" / "sdlc-spike")


def run_scenario(name: str, spec: dict) -> dict:
    out_dir = OUT_ROOT / name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    home = out_dir / "home"
    project = out_dir / "project"
    project.mkdir()
    build_home(home, HERE / "sdlc-spike")

    marker = f"SPIKE-{name}-{int(time.time())}"
    usage = out_dir / "usage.json"
    cmd = [HERMES, "-z", spec["prompt"], "--in", str(project), "--usage-file", str(usage)]
    if spec.get("yolo"):
        cmd.append("--yolo")

    env = {**os.environ, "HERMES_HOME": str(home), "SDLC_SPIKE_BLOCK": spec["block"],
           "SDLC_SPIKE_MARKER": marker, "SDLC_SPIKE_NUDGE": str(spec.get("nudge", 0)),
           "SDLC_SPIKE_ALLOW": spec.get("allow", "")}
    started = time.monotonic()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
    elapsed = time.monotonic() - started
    (out_dir / "transcript.log").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr,
                                            encoding="utf-8")

    journal_path = home / "spike" / "journal.jsonl"
    events = []
    if journal_path.is_file():
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        shutil.copy2(journal_path, out_dir / "journal.jsonl")

    hooks = Counter(event["hook"] for event in events)
    tool_calls = [e for e in events if e["hook"] == "pre_tool_call"]
    blocked = [e for e in tool_calls if e.get("blocked")]
    api_checks = [e for e in events if e["hook"] == "pre_api_request"]
    meta = {
        "scenario": name,
        "block": spec["block"],
        "allow": spec.get("allow", ""),
        "nudge": spec.get("nudge", 0),
        "yolo": bool(spec.get("yolo")),
        "marker": marker,
        "exit_code": proc.returncode,
        "seconds": round(elapsed, 1),
        "hook_counts": dict(sorted(hooks.items())),
        "tools_attempted": dict(Counter(e.get("tool") for e in tool_calls)),
        "tools_blocked": dict(Counter(e.get("tool") for e in blocked)),
        "marker_in_request": [e.get("marker_in_request") for e in api_checks],
        "api_requests": len(api_checks),
        "files_created": sorted(p.name for p in project.iterdir()),
        "usage": json.loads(usage.read_text(encoding="utf-8")) if usage.is_file() else None,
        "loaded": (home / "sdlc-loaded.json").is_file(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    return meta


def print_report(meta: dict) -> None:
    print(f"\n=== {meta['scenario']} ===")
    print(f"код выхода {meta['exit_code']}, {meta['seconds']} с, --yolo: {meta['yolo']}")
    print(f"хуки: {meta['hook_counts']}")
    print(f"вызовы инструментов: {meta['tools_attempted']}")
    print(f"заблокировано: {meta['tools_blocked']}")
    print(f"метка в теле запроса: {meta['marker_in_request']} (запросов: {meta['api_requests']})")
    print(f"файлы в проекте: {meta['files_created']}")
    usage = meta.get("usage") or {}
    if usage:
        print(f"usage: {json.dumps(usage, ensure_ascii=False)[:300]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), action="append")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    names = sorted(SCENARIOS) if args.all else (args.scenario or [])
    if not names:
        ap.error("нужен --scenario <имя> или --all")
    for name in names:
        print_report(run_scenario(name, SCENARIOS[name]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
