# -*- coding: utf-8 -*-
"""Ключевой поиск BM25 на SQLite FTS5 по леммам фрагментов.

Источник — kb.sqlite (pages, pages_lemma). Страницы нарезаются на фрагменты окном по леммам и
складываются в отдельный файл bm25.sqlite:

  chunks(id, doc_id, page, section, tok0, tok1, lemma, orig)
      tok0..tok1 — смещение фрагмента в последовательности токенов страницы;
      lemma — леммы фрагмента, orig — исходный текст (для реранкера и сниппета);
  chunks_fts — FTS5 (внешнее содержимое chunks), токенайзер unicode61, ранжирование bm25();
  chunks_v   — fts5vocab: частоты слов, по ним считается «доля отсутствующих слов».

Окно по умолчанию — 96 токенов с перекрытием 16; фрагмент не пересекает границу страницы.

Сигналы «в корпусе нет»:
  miss      доля слов запроса, которых нет в корпусе вообще;
  best_doc  доля (взвешенная по IDF) слов запроса, найденных в лучшем документе среди первых 50 фрагментов.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

from . import norm

WINDOW = 96
OVERLAP = 16
MIN_TAIL = 24          # хвост короче — приклеивается к предыдущему фрагменту
RERANK_MODEL = "DiTy/cross-encoder-russian-msmarco"
RERANK_CHARS = 1000
BEST_DOC_TOPK = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, doc_id TEXT, page TEXT, section TEXT,
                     tok0 INT, tok1 INT, lemma TEXT, orig TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""
FTS_SCHEMA = """
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(lemma, content='chunks', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_v USING fts5vocab(chunks_fts, 'row');
"""


# ---------------------------------------------------------------- сборка

def _windows(n, window, overlap, tail):
    """Границы окон [(a, b)) по n токенам; короткий хвост приклеивается к предыдущему."""
    if n <= window:
        return [(0, n)] if n else []
    step = window - overlap
    out, a = [], 0
    while a < n:
        b = min(a + window, n)
        out.append((a, b))
        if b >= n:
            break
        a += step
    if len(out) > 1 and out[-1][1] - out[-1][0] < tail:
        a0, _ = out[-2]
        out[-2:] = [(a0, n)]
    return out


def page_chunks(doc, page, section, lem_text, text, window, overlap):
    """-> (строки для chunks, выровнены ли токены страницы с леммами)."""
    lem = lem_text.split()
    pre = norm.DIGIT_GAP.sub("", (text or "").replace("ё", "е").replace("Ё", "Е"))
    spans = [m.span() for m in norm.TOKEN_RE.finditer(pre)]
    aligned = len(spans) == len(lem)
    rows = []
    for a, b in _windows(len(lem), window, overlap, MIN_TAIL):
        orig = pre[spans[a][0]:spans[b - 1][1]] if aligned else " ".join(lem[a:b])
        rows.append((doc, page, section, a, b, " ".join(lem[a:b]), orig))
    return rows, aligned


INS = "INSERT INTO chunks(doc_id,page,section,tok0,tok1,lemma,orig) VALUES (?,?,?,?,?,?,?)"
SRC_Q = ("SELECT l.doc_id, l.page, l.section, l.text_lemma, p.text FROM pages_lemma l "
         "JOIN pages p ON p.doc_id=l.doc_id AND p.page=l.page")


def _write_meta(d, src, window, overlap):
    n_chunks = d.execute("SELECT count(*) FROM chunks").fetchone()[0]
    n_pages = d.execute("SELECT count(DISTINCT doc_id || '|' || page) FROM chunks").fetchone()[0]
    meta = {"window": window, "overlap": overlap, "min_tail": MIN_TAIL, "pages": n_pages,
            "chunks": n_chunks, "source": Path(src).name, "built": time.strftime("%Y-%m-%d %H:%M:%S")}
    d.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                  [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
    return meta


def build_full(src, dst, window=WINDOW, overlap=OVERLAP, log=print):
    """Строит bm25.sqlite с нуля во временный файл и переименовывает по готовности."""
    dst = Path(dst)
    tmp = dst.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    t0 = time.time()
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(tmp)
    d.execute("PRAGMA journal_mode=OFF")
    d.execute("PRAGMA synchronous=OFF")
    d.executescript(SCHEMA)
    rows, n = [], 0
    for doc, page, section, lem_text, text in s.execute(SRC_Q):
        rs, _ = page_chunks(doc, page, section, lem_text, text, window, overlap)
        rows += rs
        if len(rows) >= 20000:
            d.executemany(INS, rows)
            n += len(rows)
            rows = []
            d.commit()
            log(f"  фрагментов {n}, {time.time() - t0:.0f} с")
    if rows:
        d.executemany(INS, rows)
    d.commit()
    d.executescript(FTS_SCHEMA)
    d.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    meta = _write_meta(d, src, window, overlap)
    d.commit()
    d.close()
    s.close()
    os.replace(tmp, dst)
    log(f"bm25: фрагментов {meta['chunks']}, {time.time() - t0:.1f} с")
    return meta


def sync(src, dst, refresh, remove, window=WINDOW, overlap=OVERLAP, log=print):
    """Инкрементально: фрагменты документов refresh пересобираются, remove — удаляются."""
    refresh, remove = list(refresh), list(remove)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    d.executescript(SCHEMA + FTS_SCHEMA)
    for doc in refresh + remove:
        old = d.execute("SELECT id, lemma FROM chunks WHERE doc_id=?", (doc,)).fetchall()
        for cid, lem in old:      # внешнее содержимое: FTS удаляется командой delete с прежним значением
            d.execute("INSERT INTO chunks_fts(chunks_fts, rowid, lemma) VALUES('delete', ?, ?)", (cid, lem))
        d.execute("DELETE FROM chunks WHERE doc_id=?", (doc,))
    n = 0
    for doc in refresh:
        for page, section, lem_text, text in s.execute(
                "SELECT l.page, l.section, l.text_lemma, p.text FROM pages_lemma l "
                "JOIN pages p ON p.doc_id=l.doc_id AND p.page=l.page WHERE l.doc_id=?", (doc,)).fetchall():
            rs, _ = page_chunks(doc, page, section, lem_text, text, window, overlap)
            for r in rs:
                cur = d.execute(INS, r)
                d.execute("INSERT INTO chunks_fts(rowid, lemma) VALUES(?, ?)", (cur.lastrowid, r[5]))
                n += 1
    meta = _write_meta(d, src, window, overlap)
    d.commit()
    d.close()
    s.close()
    log(f"bm25: обновлено документов {len(refresh)}, удалено {len(remove)}, новых фрагментов {n}")
    return meta


# ---------------------------------------------------------------- поиск

def _subtokens(term):
    """Как FTS5 unicode61 режет слово: «16888.72» -> 16888, 72; «а-б» -> а, б."""
    return [t for t in re.split(r"[^0-9a-zа-я]+", term.lower()) if t]


class Bm25:
    """Поиск по bm25.sqlite (только чтение). Соединение живёт столько же, сколько объект."""

    def __init__(self, path, synonyms=None):
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"нет {p}: выполните `ru-corpus index`")
        self.path = p
        self.db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        self.synonyms = synonyms or {}
        self._ce = None

    def close(self):
        self.db.close()

    def _term_exists(self, term):
        """Слово (с префиксом) есть в словаре корпуса; составное — все части."""
        for t in _subtokens(term):
            hi = t[:-1] + chr(ord(t[-1]) + 1)
            if not self.db.execute("SELECT 1 FROM chunks_v WHERE term>=? AND term<? LIMIT 1", (t, hi)).fetchone():
                return False
        return True

    def _term_idf(self, term, n):
        df = 0
        for t in _subtokens(term):
            r = self.db.execute("SELECT doc FROM chunks_v WHERE term=?", (t,)).fetchone()
            df = max(df, r[0] if r else 0)
        df = df or 1
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def _n_chunks(self):
        r = self.db.execute("SELECT v FROM meta WHERE k='chunks'").fetchone()
        return int(json.loads(r[0])) if r else 1

    def signals(self, query, rows):
        """-> (best_doc, miss, n_terms). rows — [(doc_id, lemma_text)] первых фрагментов выдачи."""
        terms = list(dict.fromkeys(x for x in (norm.lemma(t) for t in norm.tokens(query)) if x))
        if not terms:
            return None, 0.0, 0
        n = self._n_chunks()
        present = [t for t in terms if self._term_exists(t)]
        miss = (len(terms) - len(present)) / len(terms)
        if not present:
            return 0.0, miss, len(terms)
        w = {t: self._term_idf(t, n) for t in present}
        total = sum(w.values())
        per_doc = {}
        for doc, lem in rows:
            words = set(lem.split())
            got = per_doc.setdefault(doc, set())
            for t in present:
                subs = _subtokens(t)
                if t in words or (len(t) >= 3 and any(x.startswith(t) for x in words)) or \
                        (len(subs) > 1 and all(s in words for s in subs)):
                    got.add(t)
        best = max((sum(w[t] for t in g) for g in per_doc.values()), default=0.0)
        return (round(best / total, 4) if total > 0 else 0.0), miss, len(terms)

    def _ce_model(self):
        if self._ce is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError:
                raise RuntimeError("для --rerank нужен sentence-transformers: pip install 'ru-corpus-kit[rerank]'")
            self._ce = CrossEncoder(RERANK_MODEL, local_files_only=True, device="cpu")
        return self._ce

    def search(self, query, n=10, doc_ids=None, rerank=False, pool=30):
        """Поиск фрагментов. -> dict(hits, miss, best_doc, n_terms, no_hit, ms).

        hit = {doc, page, section, tok0, tok1, score, bm25, text}; score = -bm25() (больше — лучше),
        после реранкера score — оценка кросс-энкодера, bm25 остаётся в своём поле."""
        t0 = time.time()
        match = norm.fts_query(query, expand=True, mode="lemma", operator="or", synonyms=self.synonyms)
        if not match:
            return {"hits": [], "miss": 0.0, "best_doc": None, "n_terms": 0, "no_hit": True, "ms": 0}
        limit = max(BEST_DOC_TOPK, pool if rerank else 0, n)
        sql = ("SELECT c.id, c.doc_id, c.page, c.section, c.tok0, c.tok1, c.lemma, c.orig, bm25(chunks_fts) s "
               "FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid WHERE chunks_fts MATCH ?")
        args = [match]
        if doc_ids:
            ids = sorted(doc_ids)
            sql += " AND c.doc_id IN (%s)" % ",".join("?" * len(ids))
            args += ids
        try:
            rows = self.db.execute(sql + " ORDER BY s LIMIT ?", args + [limit]).fetchall()
        except sqlite3.OperationalError:
            rows = []
        best, miss, n_terms = self.signals(query, [(r[1], r[6]) for r in rows[:BEST_DOC_TOPK]])
        hits = [{"doc": r[1], "page": r[2], "section": r[3], "tok0": r[4], "tok1": r[5],
                 "score": round(-r[8], 4), "bm25": round(-r[8], 4), "text": r[7]} for r in rows]
        if rerank and hits:
            top = hits[:pool]
            sc = self._ce_model().predict([(query, h["text"][:RERANK_CHARS]) for h in top],
                                          show_progress_bar=False)
            for h, v in zip(top, sc):
                h["score"] = round(float(v), 4)
            hits = sorted(top, key=lambda h: -h["score"]) + hits[pool:]
        return {"hits": hits[:max(n, 0)], "miss": round(miss, 4), "best_doc": best, "n_terms": n_terms,
                "no_hit": not rows, "ms": round((time.time() - t0) * 1000)}

    def branch(self, query, doc_ids=None, rerank=False, n=10):
        """Ветка для гибрида: (docs, hits[(doc, page)], (best_doc, miss), verdict, no_hit)."""
        r = self.search(query, n=n, doc_ids=doc_ids, rerank=rerank)
        hits = [(h["doc"], h["page"]) for h in r["hits"]]
        docs = list(dict.fromkeys(d for d, _p in hits))
        return docs, hits, (r["best_doc"], r["miss"]), None, r["no_hit"]
