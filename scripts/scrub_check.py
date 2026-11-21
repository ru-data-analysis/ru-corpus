#!/usr/bin/env python3
"""Проверка вычистки: в публичном репозитории не должно быть привязок к частному корпусу,
путей рабочей машины и секретов. Запускается в CI на каждый push и pull request.

    python3 scripts/scrub_check.py        # код 1 и список нарушений, если что-то найдено
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()
RULES = [
    ("название частной организации", re.compile(r"ОЭК|\bOEK\b|uneco", re.I)),
    ("идентификатор документа частного корпуса", re.compile(r"\bdoc-a?\d{4}\b")),
    ("путь рабочей машины", re.compile(r"/Users/[A-Za-z]|C:\\\\Users\\\\")),
    ("ключ API", re.compile(r"sk-[A-Za-z0-9]{24,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("токен бота Telegram", re.compile(r"\b\d{9,10}:AA[A-Za-z0-9_-]{30,}")),
    ("переменная с секретом", re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}")),
]
BINARY = {".ttf", ".png", ".jpg", ".jpeg", ".pdf", ".xlsx", ".docx", ".zip", ".sqlite", ".gz"}


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [ROOT / p for p in out.decode().split("\0") if p]


def main():
    bad = []
    for p in tracked():
        if p.resolve() == SELF or p.suffix.lower() in BINARY or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in RULES:
                if rx.search(line):
                    bad.append(f"{p.relative_to(ROOT)}:{n}: {name}")
    if bad:
        print("вычистка не пройдена:\n  " + "\n  ".join(bad))
        sys.exit(1)
    print(f"вычистка пройдена: проверено файлов {len(tracked())}")


if __name__ == "__main__":
    main()
