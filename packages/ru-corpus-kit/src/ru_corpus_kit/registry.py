# -*- coding: utf-8 -*-
"""Реестр источников: какие файлы лежат в корпусе, их sha256, раздел, год, название.

Свой реестр строится обходом корпуса и хранится в <индекс>/registry.csv. Готовые реестры CSV
(колонки id, rel_path, title, section, type, year, ext, …) можно подключить в corpus.toml —
так открывается чужой индекс без переиндексации.
"""
from __future__ import annotations

import csv
import fnmatch
import hashlib
import re
from pathlib import Path

COLS = ["id", "section", "type", "year", "ext", "size_bytes", "size_mb", "rel_path", "exists",
        "sha256", "title", "mtime_ns"]
YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def load(cfg) -> dict:
    """id -> строка реестра. Реестры из corpus.toml читаются по порядку (первый id побеждает);
    у строк из archive_registry флаг archive=True. Без них — registry.csv индекса."""
    reg = {}
    sources = [(p, False) for p in cfg.registries] + [(p, True) for p in cfg.archive_registries]
    if not sources and cfg.default_registry.exists():
        sources = [(cfg.default_registry, False)]
    for p, archive in sources:
        if not p.exists():
            continue
        for r in read_csv(p):
            r.setdefault("section", "")
            r["archive"] = archive
            reg.setdefault(r["id"], r)
    return reg


def _excluded(rel: str, patterns) -> bool:
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch("/" + rel, pat) for pat in patterns)


def scan(cfg, old_rows: list[dict] | None = None):
    """Обход корпуса -> (строки реестра, дубликаты [(путь, совпадает с путём)]).

    id стабильны: файл, уже бывший в реестре, сохраняет id; новые получают следующий номер.
    Копия файла с тем же sha256 не регистрируется (её документ уже есть)."""
    root = cfg.root
    if not root.is_dir():
        raise FileNotFoundError(f"каталог корпуса не найден: {root}")
    old_by_path = {r["rel_path"]: r for r in (old_rows or [])}
    used = [int(m.group(1)) for r in (old_rows or []) for m in [re.search(r"(\d+)$", r["id"])] if m]
    nxt = max(used, default=0) + 1
    exts = set(cfg.extensions)
    rows, dups, seen = [], [], {}
    for p in sorted(root.rglob("*"), key=lambda x: x.as_posix()):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        rel = p.relative_to(root).as_posix()
        if _excluded(rel, cfg.exclude) or any(part.startswith(".") for part in rel.split("/")) \
                or p.resolve().is_relative_to(cfg.index_dir.resolve()):
            continue
        st = p.stat()
        if cfg.max_size_mb and st.st_size > cfg.max_size_mb * 1024 * 1024:
            continue
        old = old_by_path.get(rel)
        if old and old.get("sha256") and str(st.st_mtime_ns) == str(old.get("mtime_ns")) \
                and str(st.st_size) == str(old.get("size_bytes")):
            sha = old["sha256"]                     # файл не менялся: хэш не пересчитываем
        else:
            sha = sha256_file(p)
        if sha in seen:
            dups.append((rel, seen[sha]))
            continue
        seen[sha] = rel
        if old:
            did = old["id"]
        else:
            did = f"d{nxt:04d}"
            nxt += 1
        y = YEAR_RE.search(p.stem)
        rows.append({"id": did, "section": rel.split("/")[0] if "/" in rel else "", "type": "",
                     "year": y.group(1) if y else "", "ext": p.suffix.lower(), "size_bytes": st.st_size,
                     "size_mb": round(st.st_size / 1048576, 2), "rel_path": rel, "exists": 1,
                     "sha256": sha, "title": p.stem, "mtime_ns": st.st_mtime_ns})
    return rows, dups
