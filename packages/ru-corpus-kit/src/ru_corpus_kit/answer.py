# -*- coding: utf-8 -*-
"""Пакет доказательств для ответа: гибрид двух веток поиска + ячейки таблиц.

Ответ не пишется без доказательства. Каждое доказательство — файл источника (с префиксом из
corpus.toml), страница, раздел («Приложение № 1», «Таблица 1», лист), ветки поиска и фрагмент.
Ветки:
  fts   — FTS5 по леммам страниц (pages_lemma_fts), OR по словам с синонимами и префиксом;
  bm25  — BM25 по фрагментам (bm25.sqlite).
Слияние — RRF по документам. Если обе ветки отказали (FTS: покрытие лемм < порога; BM25: лучший
документ ниже порога или доля отсутствующих слов >= порога) — ответ «в корпусе нет».
Точная цифра из таблицы — отдельной строкой из table_cells с якорем «стр. N, таблица K, строка r, графа …».
"""
from __future__ import annotations

import re
import sqlite3

from . import norm

RRF_K = 60


def fts_run(db, q, synonyms, limit=200):
    """-> (doc_rank, page_hits[(doc, page)], coverage). Режим «леммы + синонимы»."""
    match = norm.fts_query(q, expand=True, operator="or", synonyms=synonyms)
    if not match:
        return [], [], 0.0
    try:
        hits = db.execute("SELECT f.doc_id, f.page FROM pages_lemma_fts f WHERE pages_lemma_fts MATCH ? "
                          "ORDER BY bm25(pages_lemma_fts) LIMIT ?", (match, limit)).fetchall()
    except sqlite3.OperationalError:
        hits = []
    docs = list(dict.fromkeys(d for d, _p in hits))
    return docs, hits, fts_coverage(db, q, hits[:10])


def fts_coverage(db, q, hits):
    """Доля лемм запроса, найденных на лучшей из первых страниц (0..1)."""
    lem = [norm.lemma(t) for t in norm.tokens(q)]
    lem = [x for x in dict.fromkeys(lem) if x]
    if not lem or not hits:
        return 0.0
    best = 0.0
    for d, p in hits:
        row = db.execute("SELECT text_lemma FROM pages_lemma WHERE doc_id=? AND page=?", (d, p)).fetchone()
        if not row:
            continue
        words = set(row[0].split())
        got = sum(1 for x in lem if x in words or any(w.startswith(x) for w in words
                                                       if len(x) >= 4 and w[:2] == x[:2]))
        best = max(best, got / len(lem))
    return best


def norm_hit_page(p):
    """'12/т1' -> ('12', 'таблица 1'); [5, 5] -> ('5', None), [5, 7] -> ('5–7', None)."""
    if isinstance(p, (list, tuple)):
        if not p:
            return ("?", None)
        a, b = (list(p) + [p[0]])[:2]
        return (str(a) if a == b else f"{a}–{b}", None)
    m = re.match(r"^(\d+)/т(\d+)$", str(p))
    return (m.group(1), f"таблица {m.group(2)}") if m else (str(p), None)


def fuse(fts_res, bm_res, k=RRF_K):
    """RRF по документам + единый список доказательств без дублей (документ + страница)."""
    score = {}
    for docs in (fts_res[0], bm_res[0]):
        for i, d in enumerate(docs[:20]):
            score[d] = score.get(d, 0.0) + 1.0 / (k + i + 1)
    docs = sorted(score, key=lambda d: -score[d])
    ev, seen = [], {}
    for src, hits in (("fts", fts_res[1][:10]), ("bm25", bm_res[1][:10])):
        for d, p in hits:
            pg, extra = norm_hit_page(p)
            key = (d, pg.split("–")[0])
            if key in seen:
                seen[key]["sources"].add(src)
                continue
            e = {"doc": d, "page": pg, "extra": extra, "sources": {src}, "raw_page": p}
            seen[key] = e
            ev.append(e)
    rank = {d: i for i, d in enumerate(docs)}
    ev.sort(key=lambda e: rank.get(e["doc"], 999))
    return docs, ev


def section_of(db, doc, page):
    r = db.execute("SELECT section FROM pages_lemma WHERE doc_id=? AND page=?", (doc, str(page))).fetchone()
    return (r[0] if r and r[0] else None)


def snippet(db, doc, page, q, width=160):
    r = db.execute("SELECT text FROM pages WHERE doc_id=? AND page=?", (doc, str(page))).fetchone()
    if not r:
        return ""
    t = re.sub(r"\s+", " ", r[0])
    lem = {norm.lemma(w) for w in norm.tokens(q)}
    for m in norm.TOKEN_RE.finditer(t):
        if norm.lemma(m.group(0)) in lem:
            return "…" + t[max(0, m.start() - width // 2): m.end() + width // 2] + "…"
    return t[:width] + "…"


def table_facts(db, q, docs, dims, limit=3):
    """Ячейки таблиц: год и уровень из вопроса, подпись — по словам вопроса."""
    if not docs or not db.execute("SELECT name FROM sqlite_master WHERE name='table_cells'").fetchone():
        return []
    y = re.search(r"\b(20[0-4]\d)\b", q)
    lv = next((n for n, rx in dims.level_patterns if n != "Всего" and re.search(rx, q)), None)
    hf = "II" if re.search(r"втор\w* полугоди|II полугоди", q, re.I) else \
        ("I" if re.search(r"перв\w* полугоди|\bI полугоди", q, re.I) else None)
    words = [w for w in norm.tokens(q) if len(w) > 4 and not w.isdigit()][:4]
    if not words or not (y or lv):
        return []
    sql = ("SELECT doc_id, page, tab, row, header, label, year, level, half, unit, raw FROM table_cells "
           "WHERE doc_id IN (%s)" % ",".join("?" * len(docs)))
    args = list(docs)
    for w in words:
        sql += " AND lower(label) LIKE ?"
        args.append("%" + w[:max(4, len(w) - 2)] + "%")
    for col, v in (("year", int(y.group(1)) if y else None), ("level", lv), ("half", hf)):
        if v is not None:
            sql += f" AND {col}=?"
            args.append(v)
    return db.execute(sql + " LIMIT ?", args + [limit]).fetchall()


def answer(kit, q, n=5, primary_first=True, rerank=None):
    """Доказательства по вопросу или «в корпусе нет»."""
    cfg, db = kit.cfg, kit.db
    fd, fh, cov = fts_run(db, q, cfg.synonyms)
    rr = cfg.rerank if rerank is None else rerank
    kd, kh, (b, miss), _v, _nh = kit.bm.branch(q, rerank=rr)
    docs, ev = fuse((fd, fh), (kd, kh))
    f_ab = (not fd) or cov < cfg.fts_coverage
    k_ab = (not kd) or b is None or b < cfg.bm25_best_doc or miss >= cfg.bm25_miss
    if f_ab and k_ab:
        return {"q": q, "verdict": "в корпусе нет", "evidence": [], "facts": [],
                "signals": {"fts_coverage": round(cov, 2), "bm25_best_doc": b, "bm25_missing": round(miss, 2)}}
    reg = kit.registry()
    if primary_first and cfg.derived_sections:
        # первичные документы — выше производного слоя (отчёты, своды): ссылка идёт на первичный файл
        ev = sorted(ev, key=lambda e: reg.get(e["doc"], {}).get("section") in cfg.derived_sections)
    out = []
    for e in ev[:n]:
        pg = e["page"].split("–")[0]
        raw = e["raw_page"] if not isinstance(e["raw_page"], list) else pg
        sec = section_of(db, e["doc"], raw)
        sec = sec or e["extra"] or ("лист «%s»" % pg if not pg.isdigit() else "основной текст")
        out.append({"doc": e["doc"], "file": kit.file_of(e["doc"]), "page": e["page"], "section": sec,
                    "sources": sorted(e["sources"]), "snippet": snippet(db, e["doc"], raw, q)})
    facts = [{"doc": f[0], "file": kit.file_of(f[0]),
              "anchor": f"стр. {f[1]}, таблица {f[2]}, строка {f[3]}, графа «{f[4]}»",
              "label": f[5], "value": f[10], "unit": f[9]} for f in table_facts(db, q, docs[:5], kit.dims)]
    return {"q": q, "verdict": "есть доказательства", "evidence": out, "facts": facts}
