#!/usr/bin/env python3
"""Синхронизация копий навыков в плагине Claude Code.

Источник правды — skills/ в корне репозитория. Плагин Claude Code лежит в отдельной папке
plugins/claude-ru-corpus/, чтобы при установке из маркетплейса не копировался весь репозиторий
(демо-корпус, пакеты, тесты). Копии навыков в плагине создаёт этот скрипт.

    python3 scripts/sync_claude_plugin.py           # обновить копии из skills/
    python3 scripts/sync_claude_plugin.py --check   # только проверить; код 1, если копии разошлись (CI)
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "skills"
DST = ROOT / "plugins" / "claude-ru-corpus" / "skills"
SKILLS = ["russian-corpus-search", "corpus-analytics-ru"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def files(base: Path) -> set[str]:
    if not base.is_dir():
        return set()
    return {
        str(p.relative_to(base))
        for p in base.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != ".DS_Store"
    }


def diff(name: str) -> list[str]:
    a, b = SRC / name, DST / name
    fa, fb = files(a), files(b)
    out = [f"{name}/{f}: нет в плагине" for f in sorted(fa - fb)]
    out += [f"{name}/{f}: лишний файл в плагине" for f in sorted(fb - fa)]
    out += [
        f"{name}/{f}: содержимое отличается"
        for f in sorted(fa & fb)
        if not filecmp.cmp(a / f, b / f, shallow=False)
    ]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="не копировать, только проверить")
    args = ap.parse_args()

    missing = [n for n in SKILLS if not (SRC / n / "SKILL.md").is_file()]
    if missing:
        print("нет навыка в skills/: " + ", ".join(missing))
        return 1

    problems = [d for n in SKILLS for d in diff(n)]
    extra = sorted(p.name for p in DST.iterdir() if p.is_dir() and p.name not in SKILLS) if DST.is_dir() else []
    problems += [f"{n}: лишний навык в плагине" for n in extra]

    if args.check:
        if problems:
            print("копии навыков в plugins/claude-ru-corpus разошлись с skills/:\n  " + "\n  ".join(problems))
            print("исправить: python3 scripts/sync_claude_plugin.py")
            return 1
        print("копии навыков в плагине совпадают с skills/")
        return 0

    if not problems:
        print("копии уже актуальны")
        return 0
    for n in SKILLS:
        target = DST / n
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SRC / n, target, ignore=IGNORE)
    for n in extra:
        shutil.rmtree(DST / n)
    print("обновлено:\n  " + "\n  ".join(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
