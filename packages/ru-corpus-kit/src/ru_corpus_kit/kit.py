# -*- coding: utf-8 -*-
"""Kit — открытый корпус: настройки, индекс (только чтение), реестр, поиск BM25."""
from __future__ import annotations

from pathlib import Path

from . import bm25 as _bm25
from . import registry as _registry
from . import store
from . import tables as T
from .config import Config


class Kit:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dims = T.Dims(cfg.profile)
        self._db = None
        self._reg = None
        self._bm = None

    # --- соединения
    @property
    def db(self):
        if self._db is None:
            self._db = store.open_ro(self.cfg.kb_path)
        return self._db

    @property
    def bm(self) -> _bm25.Bm25:
        if self._bm is None:
            self._bm = _bm25.Bm25(self.cfg.bm25_path, self.cfg.synonyms)
        return self._bm

    def registry(self) -> dict:
        if self._reg is None:
            self._reg = _registry.load(self.cfg)
        return self._reg

    def close(self):
        for c in (self._db, self._bm):
            if c is not None:
                c.close()
        self._db = self._bm = None

    # --- ссылки на источник
    def file_of(self, doc_id: str) -> str:
        return self.cfg.source_prefix + self.registry().get(doc_id, {}).get("rel_path", "?")

    def origin_of(self, doc_id: str, page) -> str:
        rel = self.registry().get(doc_id, {}).get("rel_path", doc_id)
        return f"{self.cfg.source_prefix}{rel}#page={page}"

    def source_path(self, doc_id: str):
        """Путь к исходному файлу документа (для чтения XLSX как есть) или None."""
        r = self.db.execute("SELECT path FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not r or not r[0]:
            return None
        p = Path(r[0])
        if p.is_absolute() and p.exists():
            return p
        q = self.cfg.root / r[0]
        if q.exists():
            return q
        rel = self.registry().get(doc_id, {}).get("rel_path")
        if rel and (self.cfg.root / rel).exists():
            return self.cfg.root / rel
        return p if p.exists() else None
