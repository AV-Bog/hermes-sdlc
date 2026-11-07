#!/usr/bin/env python3
"""Один прогон стенда: дом агента, песочница, запуск, вердикт.

Как запускать, что лежит в каталоге прогона и как устроена изоляция — в `bench/README.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent
REPO = BENCH.parent
RUNS = BENCH / "runs"
STATE_ROOT = Path.home() / ".hermes" / "bench"
MAIN_PROFILE_HOME = Path.home() / ".hermes"
ARMS = ("off", "advisory", "enforce")


def sh(cmd: list[str], cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)


def sandbox_profile(run_dir: Path, project: Path, home: Path) -> str:
    """SBPL-профиль прогона: запрет чтения ответов и записи в служебные файлы.

    Пути обязаны быть каноничными (resolve), порядок правил важен — почему, в `bench/README.md`.
    """
    deny_read = [REPO, run_dir, MAIN_PROFILE_HOME / "memories", MAIN_PROFILE_HOME / "skills"]
    # Плагин и конфиг принадлежат экспериментатору, а не субъекту прогона.
    deny_write_dirs = [
        home / "plugins",
        MAIN_PROFILE_HOME / "memories", MAIN_PROFILE_HOME / "skills", MAIN_PROFILE_HOME / "plugins",
        REPO,
    ]
    deny_write_files = [
        home / "config.yaml", home / ".env",
        home.parent / "meta.json", run_dir / "verdict.json", run_dir / "transcript.log",
    ]
    lines = ["(version 1)", "(allow default)"]
    lines += [f'(deny file-read* (subpath "{p}"))' for p in deny_read]
    lines.append(f'(allow file-read* (subpath "{project}"))')
    lines += [f'(deny file-write* (subpath "{p}"))' for p in deny_write_dirs]
    lines += [f'(deny file-write* (literal "{p}"))' for p in deny_write_files]
    return "\n".join(lines) + "\n"


def read_plugin_marker(home: Path) -> dict | None:
    """Отметка плагина о загрузке: `$HERMES_HOME/sdlc-loaded.json`. Зачем — в `bench/README.md`."""
    marker = home / "sdlc-loaded.json"
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"отметка не читается: {exc}"}



def verify_arm(arm: str, home: Path) -> tuple[dict | None, str | None]:
    """Проверка, что прогон действительно идёт в том плече, которое заявлено.

    Возвращает (отметка плагина, причина невалидности или None).
    """
    loaded = read_plugin_marker(home)
    if arm == "off":
        return loaded, None
    if loaded is None:
        return None, "плагин не оставил отметку о загрузке: мерили не то плечо"
    mode = loaded.get("mode")
    if mode is not None and mode != arm:
        return loaded, f"плагин загрузился в режиме {mode!r}, а плечо {arm!r}"
    return loaded, None


def build_home(home: Path, arm: str, env_file: Path, plugin_src: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    tmpl = (BENCH / "home-template" / "config.yaml.tmpl").read_text(encoding="utf-8")
    enabled = "[]" if arm == "off" else "[hermes-sdlc]"
    config = tmpl.replace("__PLUGIN_ENABLED__", enabled).replace("__PLUGIN_MODE__", arm)
    (home / "config.yaml").write_text(config, encoding="utf-8")

    notes: dict = {"plugin_installed": False, "env_copied": False}

    if env_file.exists():
        shutil.copyfile(env_file, home / ".env")
        os.chmod(home / ".env", 0o600)
        notes["env_copied"] = True
    else:
        notes["env_warning"] = f"нет {env_file}: прогон упадёт без ключей"

    if arm != "off":
        target = home / "plugins" / "hermes-sdlc"
        if plugin_src.is_dir():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(plugin_src, target, dirs_exist_ok=True)
            notes["plugin_installed"] = True
        else:
            notes["plugin_warning"] = f"плагина ещё нет ({plugin_src}) — плечо {arm} не на что опирать"

    return notes


def build_project(project: Path, seed: Path) -> None:
    shutil.copytree(seed, project, dirs_exist_ok=True)
    sh(["git", "init", "-q"], cwd=project)
    sh(["git", "add", "-A"], cwd=project)
    sh(["git", "-c", "user.email=bench@local", "-c", "user.name=bench",
        "commit", "-qm", "seed", "--allow-empty"], cwd=project)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="имя каталога в bench/tasks/")
    ap.add_argument("--arm", required=True, choices=ARMS)
    ap.add_argument("--n", type=int, default=1, help="номер повтора")
    ap.add_argument("--timeout", type=int, default=900, help="предел на прогон агента, с")
    ap.add_argument("--dry-run", action="store_true", help="собрать стенд, но агента не запускать")
    ap.add_argument("--no-sandbox", action="store_true", help="без sandbox-exec (только отладка)")
    ap.add_argument("--env-file", type=Path, default=MAIN_PROFILE_HOME / ".env")
    ap.add_argument("--hermes", default=shutil.which("hermes") or "hermes")
    args = ap.parse_args()

    task_dir = BENCH / "tasks" / args.task
    if not (task_dir / "TASK.md").is_file():
        print(f"нет задачи: {task_dir / 'TASK.md'}", file=sys.stderr)
        return 2
    if not (task_dir / "grader.py").is_file():
        print(f"нет grader.py в {task_dir}", file=sys.stderr)
        return 2

    run_dir = (RUNS / args.task / f"{args.arm}-{args.n:02d}").resolve()
    state_dir = (STATE_ROOT / args.task / f"{args.arm}-{args.n:02d}").resolve()
    if run_dir.exists() or state_dir.exists():
        print(f"прогон уже есть: {run_dir} (удали или возьми другой --n)", file=sys.stderr)
        return 2
    home, project = state_dir / "home", run_dir / "project"
    run_dir.mkdir(parents=True)

    prompt = (task_dir / "TASK.md").read_text(encoding="utf-8")
    notes = build_home(home, args.arm, args.env_file.resolve(), REPO / "plugin" / "hermes-sdlc")
    build_project(project, task_dir / "seed")

    meta: dict = {
        "task": args.task,
        "arm": args.arm,
        "repeat": args.n,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hermes": args.hermes,
        "timeout_s": args.timeout,
        "dry_run": args.dry_run,
        "home": str(home),
        **notes,
    }

    cmd = [args.hermes, "-z", prompt, "--in", str(project), "--usage-file", str(run_dir / "usage.json")]
    meta["command"] = " ".join(cmd[:2] + ["<TASK.md>"] + cmd[3:])

    sandboxed = not args.no_sandbox and platform.system() == "Darwin"
    if args.dry_run:
        meta["agent"] = "skipped (dry-run)"
        (run_dir / "transcript.log").write_text("", encoding="utf-8")
    else:
        if sandboxed:
            profile = state_dir / "sandbox.sb"
            profile.write_text(sandbox_profile(run_dir, project, home), encoding="utf-8")
            cmd = ["sandbox-exec", "-f", str(profile)] + cmd
            meta["sandbox"] = str(profile)
        else:
            meta["sandbox_warning"] = "без изоляции: агент может прочитать ответы и meta.json"

        env = {**os.environ, "HERMES_HOME": str(home), "TERM": "dumb"}
        env.pop("HERMES_PROFILE", None)
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=str(project), env=env, capture_output=True,
                                  text=True, timeout=args.timeout)
            (run_dir / "transcript.log").write_text(
                (proc.stdout or "") + ("\n---- STDERR ----\n" + proc.stderr if proc.stderr else ""),
                encoding="utf-8")
            meta.update(agent_exit=proc.returncode, duration_s=round(time.time() - t0, 1))
        except subprocess.TimeoutExpired as exc:
            (run_dir / "transcript.log").write_text(
                exc.stdout if isinstance(exc.stdout, str) else "", encoding="utf-8")
            meta.update(agent_exit=None, timed_out=True, duration_s=round(time.time() - t0, 1))

    # Без отметки `enforce` может тихо измерить `off`.
    if args.dry_run:
        meta["plugin"], meta["valid"] = None, None
    else:
        loaded, reason = verify_arm(args.arm, home)
        meta["plugin"], meta["valid"] = loaded, reason is None
        if reason:
            meta["invalid_reason"] = reason

    verdict = run_dir / "verdict.json"
    g = sh([sys.executable, str(task_dir / "grader.py"), "--project", str(project), "--out", str(verdict)])
    meta["grader_exit"] = g.returncode
    if g.returncode != 0:
        meta["grader_error"] = (g.stderr or g.stdout).strip()[:800]

    diff = sh(["git", "status", "--porcelain"], cwd=project)
    meta["changed_files"] = [line[3:] for line in (diff.stdout or "").splitlines() if line.strip()]
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (state_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    agent_label = meta.get("agent") or f"exit {meta.get('agent_exit')}"
    print(f"прогон: {run_dir.relative_to(REPO)}")
    print(f"дом:    {home}")
    print(f"плечо:  {args.arm}   агент: {agent_label}   изоляция: "
          f"{'sandbox-exec' if meta.get('sandbox') else 'нет'}")
    if meta.get("valid") is True:
        print(f"плагин: загружен {meta['plugin']}")
    elif meta.get("valid") is False:
        print(f"ПРОГОН НЕ ЗАСЧИТАН: {meta['invalid_reason']}")
    for key in ("plugin_warning", "env_warning", "sandbox_warning", "grader_error"):
        if meta.get(key):
            print(f"! {meta[key]}")
    if verdict.exists():
        print("вердикт: " + json.loads(verdict.read_text(encoding="utf-8"))["summary"])
    print(f"изменено файлов: {len(meta['changed_files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
