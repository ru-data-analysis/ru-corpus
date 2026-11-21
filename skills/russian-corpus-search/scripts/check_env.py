#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Диагностика окружения для русского поиска командой ru-corpus.

Проверяет: версию Python, команду ru-corpus, pymorphy3, необязательные пакеты (таблицы, OCR),
программы pdftotext и tesseract с языком rus, наличие corpus.toml и состояние индекса.

    python3 check_env.py               # проверка от текущей папки
    python3 check_env.py --json        # результат одним JSON

Код возврата 1, если не хватает обязательного (ru-corpus, pymorphy3). Ничего не меняет в системе.
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


def has_module(name):
    return importlib.util.find_spec(name) is not None


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)


def find_config(start: Path):
    for d in [start, *start.parents]:
        if (d / "corpus.toml").is_file():
            return d / "corpus.toml"
    return None


def collect():
    items = []   # (уровень, что, подробности); уровень: ok | warn | fail

    def add(level, what, detail=""):
        items.append({"level": level, "what": what, "detail": detail})

    py = sys.version_info
    add("ok" if py >= (3, 10) else "fail", "Python " + ".".join(map(str, py[:3])), "нужен 3.10+" if py < (3, 10) else "")

    exe = shutil.which("ru-corpus")
    if exe:
        code, out, _ = run([exe, "--version"])
        add("ok", "команда ru-corpus", (out.strip() or exe))
    else:
        add("fail", "команда ru-corpus", "не найдена: pip install -e \"packages/ru-corpus-kit[tables]\"")

    add("ok" if has_module("pymorphy3") else "fail", "pymorphy3 (леммы)",
        "" if has_module("pymorphy3") else "pip install pymorphy3 (ставится вместе с ядром); без него работает грубый стеммер")
    add("ok" if has_module("openpyxl") else "warn", "openpyxl (XLSX)")
    tables = has_module("pdfplumber") and has_module("pypdfium2")
    add("ok" if tables else "warn", "таблицы PDF (pdfplumber, pypdfium2)", "" if tables else "pip install \"ru-corpus-kit[tables]\"")
    ocr_py = has_module("PIL") and has_module("pypdfium2")
    add("ok" if ocr_py else "warn", "OCR, Python-часть (Pillow, pypdfium2)", "" if ocr_py else "pip install \"ru-corpus-kit[ocr]\"")

    add("ok" if shutil.which("pdftotext") else "warn", "pdftotext (poppler)",
        "" if shutil.which("pdftotext") else "нет: текст PDF возьмёт pdfplumber; brew install poppler / apt install poppler-utils")
    tess = shutil.which("tesseract")
    if not tess:
        add("warn", "tesseract", "нет: сканы не распознаются; brew install tesseract tesseract-lang / apt install tesseract-ocr tesseract-ocr-rus")
    else:
        _, out, err = run([tess, "--list-langs"])
        langs = (out + err).split()
        add("ok" if "rus" in langs else "warn", "tesseract с языком rus", "" if "rus" in langs else "нет языка rus")

    cfg = find_config(Path.cwd())
    if not cfg:
        add("warn", "corpus.toml", "не найден выше текущей папки: ru-corpus init --root ./документы")
    else:
        add("ok", "corpus.toml", str(cfg))
        if exe:
            code, out, _ = run([exe, "status", "--json", "--config", str(cfg)])
            try:
                st = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                st = {}
            if not st:
                add("warn", "состояние индекса", "ru-corpus status не ответил")
            elif not st.get("indexed"):
                add("warn", "индекс", st.get("hint", "индекса нет: ru-corpus index"))
            else:
                bad = st.get("errors", 0) or st.get("no_text", 0)
                add("warn" if bad else "ok", "индекс",
                    f"документов {st.get('docs')}, страниц {st.get('pages')}, без текста {st.get('no_text', 0)}, ошибок {st.get('errors', 0)}")
                ch = st.get("corpus_changes") or {}
                if any(ch.values()):
                    add("warn", "корпус изменился после индексации", f"{ch}; выполните ru-corpus index")
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    items = collect()
    failed = any(i["level"] == "fail" for i in items)
    if a.json:
        print(json.dumps({"ok": not failed, "items": items}, ensure_ascii=False))
    else:
        mark = {"ok": "[ok]  ", "warn": "[!]   ", "fail": "[FAIL]"}
        for i in items:
            print(f"{mark[i['level']]} {i['what']}" + (f" — {i['detail']}" if i["detail"] else ""))
        print("\nитог:", "есть обязательные проблемы" if failed else "обязательное на месте")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
