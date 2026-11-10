#!/usr/bin/env python3
"""Заметки: добавить, показать, найти, удалить.

Хранение - файл `notes.json` в текущем каталоге. Только стандартная библиотека.
"""

from __future__ import annotations

import json
import sys

DATA = "notes.json"


def load(path: str = DATA) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"next_id": 1, "notes": []}
    data.setdefault("next_id", 1)
    data.setdefault("notes", [])
    return data


def save(data: dict, path: str = DATA) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _text(args: list[str]) -> str:
    return " ".join(args).strip()


def cmd_add(args: list[str]) -> int:
    text = _text(args)
    if not text:
        print("usage: notes.py add <текст>", file=sys.stderr)
        return 1
    data = load()
    note_id = data["next_id"]
    data["notes"].append({"id": note_id, "text": text})
    data["next_id"] = note_id + 1
    save(data)
    print(f"added {note_id}")
    return 0


def cmd_list(args: list[str]) -> int:
    for note in load()["notes"]:
        print(f"{note['id']}\t{note['text']}")
    return 0


def cmd_search(args: list[str]) -> int:
    word = _text(args).lower()
    if not word:
        print("usage: notes.py search <слово>", file=sys.stderr)
        return 1
    for note in load()["notes"]:
        if word in note["text"].lower():
            print(f"{note['id']}\t{note['text']}")
    return 0


def cmd_delete(args: list[str]) -> int:
    try:
        note_id = int(args[0])
    except (IndexError, ValueError):
        print("usage: notes.py delete <id>", file=sys.stderr)
        return 1
    data = load()
    keep = [n for n in data["notes"] if n["id"] != note_id]
    if len(keep) == len(data["notes"]):
        print(f"not found {note_id}")
        return 2
    data["notes"] = keep
    save(data)
    print(f"deleted {note_id}")
    return 0


COMMANDS = {
    "add": cmd_add,
    "list": cmd_list,
    "search": cmd_search,
    "delete": cmd_delete,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print("usage: notes.py add|list|search|delete ...", file=sys.stderr)
        return 1
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
