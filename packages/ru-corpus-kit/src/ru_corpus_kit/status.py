# -*- coding: utf-8 -*-
"""Состояние индекса: сколько документов, страниц, ячеек, фрагментов; что устарело относительно корпуса."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import registry
from .config import Config


def _scalar(db, sql, default=0):
    try:
        r = db.execute(sql).fetchone()
        return r[0] if r and r[0] is not None else default
    except sqlite3.Error:
        return default


def collect(cfg: Config) -> dict:
    st = {"config": str(cfg.path) if cfg.path else None, "root": str(cfg.root), "index_dir": str(cfg.index_dir),
          "kb": str(cfg.kb_path), "bm25": str(cfg.bm25_path), "profile": cfg.profile.name or None,
          "source_prefix": cfg.source_prefix, "indexed": cfg.kb_path.exists()}
    if not cfg.kb_path.exists():
        st["hint"] = "индекса нет: выполните `ru-corpus index`"
        return st
    db = sqlite3.connect(f"file:{cfg.kb_path}?mode=ro", uri=True)
    st["docs"] = _scalar(db, "SELECT count(*) FROM docs")
    st["pages"] = _scalar(db, "SELECT count(*) FROM pages")
    st["chars"] = _scalar(db, "SELECT sum(chars) FROM docs")
    st["methods"] = {m: n for m, n in db.execute("SELECT method, count(*) FROM docs GROUP BY method")}
    st["no_text"] = _scalar(db, "SELECT count(*) FROM docs WHERE method='no-text'")
    st["errors"] = _scalar(db, "SELECT count(*) FROM docs WHERE method LIKE 'error%'")
    st["table_cells"] = _scalar(db, "SELECT count(*) FROM table_cells")
    st["table_cells_bbox"] = _scalar(db, "SELECT count(*) FROM table_cells_bbox")
    st["lemma_pages"] = _scalar(db, "SELECT count(*) FROM pages_lemma")
    st["own_index"] = bool(_scalar(db, "SELECT count(*) FROM sqlite_master WHERE name='kit_meta'"))
    pending = {}
    if st["own_index"]:
        sigs = {i: f"{sha}|{m}|{c}" for i, sha, m, c in db.execute("SELECT id, sha256, method, chars FROM docs")}
        marks = {k: v for k, v in db.execute("SELECT k, v FROM kit_meta")}
        for stage in ("lemma", "tables", "bm25"):
            pending[stage] = sum(1 for i, s in sigs.items() if marks.get(f"{stage}:{i}") != s)
        st["pending_stages"] = pending
    db.close()
    if cfg.bm25_path.exists():
        b = sqlite3.connect(f"file:{cfg.bm25_path}?mode=ro", uri=True)
        st["bm25_chunks"] = _scalar(b, "SELECT count(*) FROM chunks")
        b.close()
    else:
        st["bm25_chunks"] = 0
    # что изменилось в корпусе после индексации (по размеру и времени, без хэшей)
    if not cfg.registries and cfg.default_registry.exists() and cfg.root.is_dir():
        old = {r["rel_path"]: r for r in registry.read_csv(cfg.default_registry)}
        seen, new, changed = set(), 0, 0
        for p in cfg.root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in set(cfg.extensions):
                continue
            rel = p.relative_to(cfg.root).as_posix()
            if any(part.startswith(".") for part in rel.split("/")) or registry._excluded(rel, cfg.exclude) \
                    or p.resolve().is_relative_to(cfg.index_dir.resolve()):
                continue
            seen.add(rel)
            o = old.get(rel)
            if o is None:
                new += 1
            elif str(p.stat().st_size) != str(o.get("size_bytes")) or str(p.stat().st_mtime_ns) != str(o.get("mtime_ns")):
                changed += 1
        st["corpus_changes"] = {"new_files": new, "changed_files": changed, "removed_files": len(set(old) - seen)}
    return st


def render(st: dict) -> str:
    if not st.get("indexed"):
        return f"корпус: {st['root']}\nиндекс: нет — {st.get('hint', '')}"
    lines = [f"корпус:      {st['root']}", f"индекс:      {st['kb']}",
             f"профиль:     {st['profile'] or 'нет (только ядро)'}",
             f"документов:  {st['docs']} (страниц {st['pages']}, символов {st['chars']})",
             "методы:      " + ", ".join(f"{m} {n}" for m, n in sorted(st["methods"].items())),
             f"без текста:  {st['no_text']}   ошибок извлечения: {st['errors']}",
             f"таблицы:     ячеек {st['table_cells']} (по координатам {st['table_cells_bbox']})",
             f"bm25:        фрагментов {st['bm25_chunks']}"]
    if st.get("pending_stages") and any(st["pending_stages"].values()):
        lines.append("не досчитано: " + ", ".join(f"{k} {v}" for k, v in st["pending_stages"].items() if v))
    if st.get("corpus_changes"):
        c = st["corpus_changes"]
        lines.append(f"в корпусе:   новых {c['new_files']}, изменённых {c['changed_files']}, удалённых {c['removed_files']}"
                     + ("  -> ru-corpus index" if any(c.values()) else ""))
    if not st["own_index"]:
        lines.append("индекс открыт без отметок ru-corpus (чужой/прежний): только чтение")
    return "\n".join(lines)


def as_json(st: dict) -> str:
    return json.dumps(st, ensure_ascii=False)
