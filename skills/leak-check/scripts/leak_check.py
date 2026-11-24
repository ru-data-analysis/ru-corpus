#!/usr/bin/env python3
"""Проверка выходных артефактов анализа на утечки. Только стандартная библиотека.

Найденный фрагмент не печатается: выводятся файл, строка и название правила.
"""
import argparse
import json
import os
import re
import sys

TEXT_EXT = {".md", ".txt", ".json", ".csv", ".tsv", ".toml"}
BUILTIN = [
    ("гриф", re.compile(r"конфиденциальн|для\s+служебного\s+пользования|\bДСП\b|коммерческ\w+\s+тайн|не\s+для\s+распространения", re.I)),
    ("путь рабочей машины", re.compile(r"/Users/[A-Za-z]|/home/[a-z][a-z0-9_-]+/|[A-Za-z]:\\+Users\\+")),
    ("ключ или токен", re.compile(r"\bsk-[A-Za-z0-9]{20,}|\bghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}")),
    ("переменная с секретом", re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}")),
]


def iter_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for d, dirs, files in os.walk(p):
                dirs[:] = sorted(x for x in dirs if not x.startswith("."))
                for fn in sorted(files):
                    if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                        yield os.path.join(d, fn)
        else:
            sys.exit(f"нет пути: {p}")


def load_patterns(path):
    rules = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, _, rx = line.partition("\t")
            if not rx:
                name, rx = f"правило владельца {n}", line
            try:
                rules.append((name, re.compile(rx, re.I)))
            except re.error as e:
                sys.exit(f"{path}:{n}: некорректное выражение: {e}")
    return rules


def load_closed(path):
    with open(path, encoding="utf-8") as f:
        items = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    return [i for i in items if len(i) >= 4]  # слишком короткие токены дают шум


def long_quotes(data, limit, where=""):
    """Рекурсивно найти quotes[].text длиннее limit слов."""
    out = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "quotes" and isinstance(v, list):
                for q in v:
                    text = q.get("text", "") if isinstance(q, dict) else str(q)
                    if len(text.split()) > limit:
                        out.append(len(text.split()))
            else:
                out += long_quotes(v, limit)
    elif isinstance(data, list):
        for v in data:
            out += long_quotes(v, limit)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="+")
    p.add_argument("--patterns")
    p.add_argument("--closed")
    p.add_argument("--max-quote-words", type=int, default=40)
    a = p.parse_args()

    rules = list(BUILTIN) + (load_patterns(a.patterns) if a.patterns else [])
    closed = load_closed(a.closed) if a.closed else []
    hits, n_files = [], 0
    for path in iter_files(a.paths):
        n_files += 1
        text = open(path, encoding="utf-8", errors="replace").read()
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in rules:
                if rx.search(line):
                    hits.append(f"{path}:{n}: {name}")
            low = line.lower()
            for item in closed:
                if item.lower() in low:
                    hits.append(f"{path}:{n}: упоминание закрытого документа из списка")
        if path.lower().endswith(".json"):
            try:
                for words in long_quotes(json.loads(text), a.max_quote_words):
                    hits.append(f"{path}: цитата длиной {words} слов (порог {a.max_quote_words})")
            except json.JSONDecodeError:
                pass
    if hits:
        print("НАЙДЕНО (фрагменты не печатаются):\n  " + "\n  ".join(hits))
        sys.exit(1)
    print(f"OK: проверено файлов {n_files}")


if __name__ == "__main__":
    main()
