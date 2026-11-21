#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка демо-корпуса: размеры, хеши по манифесту и отсутствие запрещённых привязок в тексте.

    python3 demo/check_corpus.py        # нужен собранный индекс (cd demo && ru-corpus index)

Проверяется (синтетика в demo/corpus/synthetic не учитывается):
  * файл ≤ 8 МБ, весь корпус ≤ 30 МБ;
  * каждый файл из MANIFEST.csv на месте, SHA-256 и размер совпадают; лишних файлов нет;
  * в тексте каждого документа (из индекса, для сканов — результат OCR) нет упоминаний организации, чьи
    данные в демо-корпус попасть не должны (наименование и сокращение, домен), и московского регулятора
    (ДЭПиР, Правительство Москвы). Шаблоны собраны из частей, чтобы сам скрипт не содержал этих названий.
"""
from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
CORPUS = DEMO / "corpus"
MAX_FILE, MAX_TOTAL = 8 * 1024 * 1024, 30 * 1024 * 1024
_ABBR = "О" + "ЭК"                       # сокращение организации (собрано из частей)
_DOMAIN = "un" + "eco"                   # её домен
FORBIDDEN = [
    re.compile(r"(?<![А-Яа-яЁё])" + _ABBR + r"(?![А-Яа-яЁё])", re.I),
    re.compile(r"Объедин[её]нн\w*\s+энергетическ\w*\s+компани", re.I),
    re.compile(_DOMAIN, re.I),
    re.compile(r"ДЭПиР"),
    re.compile(r"Департамент\w*\s+(?:\w+\s+){0,4}города\s+Москвы", re.I),
    re.compile(r"Правительств\w*\s+Москвы", re.I),
]


def main() -> int:
    bad: list[str] = []
    with (CORPUS / "MANIFEST.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    listed = {r["файл"] for r in rows}
    on_disk = {p.relative_to(CORPUS).as_posix() for p in CORPUS.rglob("*")
               if p.is_file() and not p.relative_to(CORPUS).as_posix().startswith("synthetic/")
               and p.name not in ("MANIFEST.csv", "README.md")}
    for extra in sorted(on_disk - listed):
        bad.append(f"файл не в манифесте: {extra}")
    total = 0
    for r in rows:
        p = CORPUS / r["файл"]
        if not p.exists():
            bad.append(f"нет файла: {r['файл']}")
            continue
        size = p.stat().st_size
        total += size
        if size > MAX_FILE:
            bad.append(f"больше 8 МБ: {r['файл']} ({size} байт)")
        data = p.read_bytes()
        nodates = re.sub(rb"/(CreationDate|ModDate) ?\((?:\\.|[^)])*\)", b"", data)
        if hashlib.sha256(data).hexdigest() != r["sha256"] and hashlib.sha256(nodates).hexdigest() != r["sha256_без_дат_pdf"]:
            bad.append(f"не совпал размер/хеш: {r['файл']}")
    if total > MAX_TOTAL:
        bad.append(f"корпус больше 30 МБ: {total} байт")
    print(f"файлов в манифесте: {len(rows)}, всего {total / 1048576:.2f} МБ (лимит 30), "
          f"крупнейший {max((CORPUS / r['файл']).stat().st_size for r in rows) / 1048576:.2f} МБ (лимит 8)")

    db = DEMO / ".index" / "kb.sqlite"
    if not db.exists():
        bad.append("нет индекса: выполните `cd demo && ru-corpus index`, чтобы проверить текст")
    else:
        con = sqlite3.connect(db)
        paths = {rel: None for rel in listed}
        for did, path in con.execute("select id, path from docs"):
            for rel in listed:
                if path.endswith(rel) or path == rel:
                    paths[rel] = did
        for rel, did in sorted(paths.items()):
            if did is None:
                bad.append(f"нет в индексе: {rel}")
                continue
            text = "\n".join(t for (t,) in con.execute("select text from pages where doc_id=?", (did,)))
            hits = [rx.pattern for rx in FORBIDDEN if rx.search(text)]
            print(f"  текст {len(text):>8} зн.  запрещённых упоминаний: {len(hits)}  {rel}")
            bad += [f"запрещённая привязка {h!r} в {rel}" for h in hits]
    for b in bad:
        print("ОШИБКА:", b)
    print("ИТОГ:", "всё в порядке" if not bad else f"проблем: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
