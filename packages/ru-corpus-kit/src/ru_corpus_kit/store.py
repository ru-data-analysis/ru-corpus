# -*- coding: utf-8 -*-
"""Схема kb.sqlite. Она совпадает со схемой индекса, который строил прототип, поэтому уже
построенный индекс открывается через corpus.toml без переиндексации.

  docs(id, sample_id, section, ext, path, sha256, pages, chars, method, title)
  pages(doc_id, page, text)                   pages_fts — FTS5 по тексту страниц
  pages_lemma(doc_id, page, section, text_lemma)   pages_lemma_fts — FTS5 по леммам
  docs_meta_text(...)   см. meta.py
  table_raw / table_cells / table_cells_bbox   см. tables.py
  kit_meta(k, v)        служебное (версия схемы, время сборки)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import meta, tables

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (id TEXT PRIMARY KEY, sample_id TEXT, section TEXT, ext TEXT,
    path TEXT, sha256 TEXT, pages INT, chars INT, method TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS pages (doc_id TEXT, page TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_pages_doc ON pages(doc_id, page);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(text, doc_id UNINDEXED, page UNINDEXED,
    tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS pages_lemma (doc_id TEXT, page TEXT, section TEXT, text_lemma TEXT);
CREATE INDEX IF NOT EXISTS ix_pages_lemma_doc ON pages_lemma(doc_id, page);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_lemma_fts USING fts5(text_lemma, doc_id UNINDEXED,
    page UNINDEXED, section UNINDEXED, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS kit_meta (k TEXT PRIMARY KEY, v TEXT);
"""


def open_rw(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA + meta.SCHEMA + ";" + tables.SCHEMA)
    db.execute("INSERT OR REPLACE INTO kit_meta VALUES('schema', ?)", (SCHEMA_VERSION,))
    db.commit()
    return db


def open_ro(path: Path) -> sqlite3.Connection:
    if not Path(path).exists():
        raise FileNotFoundError(f"нет индекса {path}: выполните `ru-corpus index`")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.create_function("lower", 1, lambda s: (s or "").lower())
    return db


def delete_doc(db: sqlite3.Connection, doc_id: str, keep_docs_row: bool = False) -> None:
    """Удаляет документ из всех таблиц индекса."""
    for t in ("pages_fts", "pages", "pages_lemma_fts", "pages_lemma", "docs_meta_text", "table_raw",
              "table_raw_docs", "table_cells", "table_cells_bbox"):
        col = "doc_id"
        db.execute(f"DELETE FROM {t} WHERE {col}=?", (doc_id,))
    if not keep_docs_row:
        db.execute("DELETE FROM docs WHERE id=?", (doc_id,))
