#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Скачивает документы демо-корпуса по demo/corpus/MANIFEST.csv и сверяет SHA-256.

    python3 demo/fetch.py              # скачать недостающие файлы, проверить все
    python3 demo/fetch.py --verify     # только проверить уже лежащие файлы (без сети)
    python3 demo/fetch.py --only tomsk # только строки, где в пути файла есть подстрока

Скачивание идёт через `curl` (на сайте Минэнерго отвечает только curl с представлением клиента;
подмена под браузер не используется). Между запросами — пауза (для minenergo.gov.ru 5 с).
Для PDF, которые сайт генерирует на лету (br.fas.gov.ru), байты отличаются датой создания при каждой
выдаче, поэтому допускается совпадение хеша без /CreationDate и /ModDate (колонка sha256_без_дат_pdf).
Код возврата 0 — все файлы на месте и хеши совпали; 1 — есть расхождения или ошибки.
Если орган обновил или убрал файл, хеш не совпадёт: файл будет сохранён рядом с суффиксом .mismatch,
а строку манифеста нужно обновить осознанно.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

DEMO = Path(__file__).resolve().parent
CORPUS = DEMO / "corpus"
MANIFEST = CORPUS / "MANIFEST.csv"
UA = "ru-corpus-demo/1.0 (public demo corpus fetcher)"
PAUSE = {"minenergo.gov.ru": 5.0}
DEFAULT_PAUSE = 1.5


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_nodates(path: Path) -> str:
    """SHA-256 PDF без /CreationDate и /ModDate: сайты, генерирующие PDF на лету (br.fas.gov.ru),
    при каждой выдаче меняют только дату создания."""
    data = re.sub(rb"/(CreationDate|ModDate) ?\((?:\\.|[^)])*\)", b"", path.read_bytes())
    return hashlib.sha256(data).hexdigest()


def matches(path: Path, row: dict) -> bool:
    return sha256(path) == row["sha256"] or sha256_nodates(path) == row["sha256_без_дат_pdf"]


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    cmd = ["curl", "-sSL", "--fail", "-m", "180", "-A", UA, "-o", str(tmp), url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        print(f"  ошибка загрузки: curl код {r.returncode} {r.stderr.strip()[:200]}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="не ходить в сеть, только сверить хеши")
    ap.add_argument("--only", default="", help="подстрока пути файла")
    a = ap.parse_args()

    with MANIFEST.open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if a.only in r["файл"]]
    bad = 0
    last_host, last_t = "", 0.0
    for r in rows:
        path = CORPUS / r["файл"]
        want = r["sha256"]
        if path.exists() and matches(path, r):
            print(f"ok       {r['файл']}")
            continue
        if a.verify:
            print(f"{'ПОРЧЕНО ' if path.exists() else 'НЕТ      '} {r['файл']}")
            bad += 1
            continue
        host = urlparse(r["url_источника"]).hostname or ""
        wait = PAUSE.get(host, DEFAULT_PAUSE) - (time.time() - last_t if host == last_host else 1e9)
        if wait > 0:
            time.sleep(wait)
        print(f"скачиваю {r['файл']}\n  {r['url_источника']}")
        ok = download(r["url_источника"], path)
        last_host, last_t = host, time.time()
        if not ok:
            bad += 1
            continue
        if not matches(path, r):
            got = sha256(path)
            path.replace(path.with_suffix(path.suffix + ".mismatch"))
            print(f"  ХЕШ НЕ СОВПАЛ: ожидали {want[:16]}…, получили {got[:16]}… (файл сохранён как .mismatch)")
            bad += 1
        else:
            print("  хеш совпал")
    print(f"\nстрок манифеста: {len(rows)}, проблем: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
