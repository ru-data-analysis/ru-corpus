# -*- coding: utf-8 -*-
"""Индексация одной командой: реестр -> текст -> OCR -> леммы -> таблицы -> bm25.

Инкрементально: у каждого документа есть подпись «sha256|метод|символов»; стадия пересчитывает
только документы, у которых её отметка в kit_meta не совпадает с подписью. Изменённый файл
(другой sha256) проходит все стадии заново, удалённый — убирается из всех таблиц и из bm25.
Прерванный запуск продолжается с того места, где остановился.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from . import bm25 as _bm25
from . import extract as _extract
from . import meta as _meta
from . import norm, ocrfix
from . import pdftables, registry, store, wide
from . import tables as T
from .config import Config

STAGES = ("registry", "text", "ocr", "lemma", "tables", "bm25")

HEAD_RE = [
    (re.compile(r"Приложение\s*№\s*([0-9]+(?:\.[0-9]+)?)", re.I), "Приложение № "),
    (re.compile(r"^\s*Раздел\s*([0-9IVX]+)", re.I | re.M), "Раздел "),
    (re.compile(r"^\s*Таблица\s*([0-9]+(?:\.[0-9]+)?)", re.I | re.M), "Таблица "),
    (re.compile(r"^\s*Пункт\s*([0-9]+(?:\.[0-9]+)*)", re.I | re.M), "Пункт "),
]


def detect_section(text, previous):
    """Раздел страницы по русским заголовкам; переносится на следующие страницы до нового заголовка."""
    for rx, prefix in HEAD_RE:
        m = rx.search(text or "")
        if m:
            return prefix + m.group(1)
    return previous


def _sig(sha, method, chars):
    return f"{sha}|{method}|{chars}"


class Indexer:
    def __init__(self, cfg: Config, log=None, force=False, use_ocr=None):
        self.cfg = cfg
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.force = force
        self.use_ocr = cfg.ocr if use_ocr is None else use_ocr
        self.dims = T.Dims(cfg.profile)
        self.pats = _meta.ActPatterns(cfg.profile.act_no)
        self.stats = {"docs": 0, "new": 0, "changed": 0, "unchanged": 0, "removed": 0, "duplicates": 0,
                      "ocr": 0, "lemma": 0, "tables": 0, "bm25": 0, "errors": 0, "notes": []}
        self.rows: list[dict] = []
        self.db = None

    # --- служебные отметки стадий
    def _marker(self, stage, doc):
        r = self.db.execute("SELECT v FROM kit_meta WHERE k=?", (f"{stage}:{doc}",)).fetchone()
        return r[0] if r else None

    def _set_marker(self, stage, doc, sig):
        self.db.execute("INSERT OR REPLACE INTO kit_meta VALUES(?,?)", (f"{stage}:{doc}", sig))

    def _doc_sigs(self):
        return {i: _sig(sha, m, c) for i, sha, m, c in
                self.db.execute("SELECT id, sha256, method, chars FROM docs")}

    def _pending(self, stage):
        sigs = self._doc_sigs()
        if self.force:
            return sorted(sigs)
        return sorted(i for i, s in sigs.items() if self._marker(stage, i) != s)

    def _note(self, msg):
        if msg not in self.stats["notes"]:
            self.stats["notes"].append(msg)
        self.log("  ! " + msg)

    # --- запуск
    def run(self, stages=STAGES):
        cfg = self.cfg
        if cfg.kb_path.exists():
            import sqlite3
            probe = sqlite3.connect(f"file:{cfg.kb_path}?mode=ro", uri=True)
            has_kit = probe.execute("SELECT 1 FROM sqlite_master WHERE name='kit_meta'").fetchone()
            has_docs = probe.execute("SELECT 1 FROM sqlite_master WHERE name='docs'").fetchone()
            probe.close()
            if has_docs and not has_kit:
                raise RuntimeError(f"{cfg.kb_path} построен не ru-corpus: переиндексация запрещена "
                                   "(такой индекс только читается инструментами search/page/table…)")
        cfg.index_dir.mkdir(parents=True, exist_ok=True)
        self.db = store.open_rw(cfg.kb_path)
        t0 = time.time()
        try:
            if "registry" in stages:
                self.stage_registry()
            else:
                self.rows = registry.read_csv(cfg.default_registry) if cfg.default_registry.exists() else []
            if "text" in stages:
                self.stage_text()
            if "ocr" in stages:
                self.stage_ocr()
            if "lemma" in stages:
                self.stage_lemma()
            if "tables" in stages:
                self.stage_tables()
            self.db.commit()
            if "bm25" in stages:
                self.stage_bm25()
        finally:
            self.db.commit()
            self.db.close()
        self.stats["docs"] = self._count_docs()
        self.stats["seconds"] = round(time.time() - t0, 1)
        return self.stats

    def _count_docs(self):
        import sqlite3
        db = sqlite3.connect(f"file:{self.cfg.kb_path}?mode=ro", uri=True)
        n = db.execute("SELECT count(*) FROM docs").fetchone()[0]
        db.close()
        return n

    # --- 1. реестр
    def stage_registry(self):
        cfg = self.cfg
        if cfg.registries:                       # готовые реестры: используются как есть
            seen, rows = set(), []
            for p in cfg.registries:
                for r in registry.read_csv(p):
                    if str(r.get("exists", "1")) == "0" or r.get("ext", "").lower() not in cfg.extensions:
                        continue
                    if r.get("sha256") in seen:
                        continue
                    seen.add(r.get("sha256"))
                    rows.append(r)
            self.rows, dups = rows, []
        else:
            old = registry.read_csv(cfg.default_registry) if cfg.default_registry.exists() else []
            self.rows, dups = registry.scan(cfg, old)
            registry.write_csv(cfg.default_registry, self.rows)
        self.stats["duplicates"] = len(dups)
        self.log(f"реестр: файлов {len(self.rows)}, дубликатов по sha256 {len(dups)}")

    # --- 2. текст
    def stage_text(self):
        db, cfg = self.db, self.cfg
        have = {i: (sha, m) for i, sha, m in db.execute("SELECT id, sha256, method FROM docs")}
        ids = {r["id"] for r in self.rows}
        for gone in sorted(set(have) - ids):
            store.delete_doc(db, gone)
            db.execute("DELETE FROM kit_meta WHERE k LIKE ?", (f"%:{gone}",))
            self.stats["removed"] += 1
        db.commit()
        for r in self.rows:
            did = r["id"]
            same = did in have and have[did][0] == r["sha256"] and not str(have[did][1]).startswith("error")
            if same and not self.force:
                db.execute("UPDATE docs SET path=?, section=?, title=? WHERE id=?",
                           (r["rel_path"], r.get("section", ""), r["rel_path"], did))
                self.stats["unchanged"] += 1
                continue
            self.stats["changed" if did in have else "new"] += 1
            path = cfg.root / r["rel_path"]
            self.log(f"[{did}] {r['rel_path'][:70]}")
            store.delete_doc(db, did)
            db.execute("DELETE FROM kit_meta WHERE k LIKE ?", (f"%:{did}",))
            try:
                pages, method, _need = _extract.extract(path)
            except Exception as e:  # noqa: BLE001
                self.log(f"  ! {e}")
                pages, method = [], f"error: {e}"
                self.stats["errors"] += 1
            self._write_doc(r, pages, method)
            db.commit()

    def _write_doc(self, r, pages, method):
        db = self.db
        did = r["id"]
        chars = sum(len(t) for _, t in pages)
        db.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (did, did, r.get("section", ""), r["ext"], r["rel_path"], r["sha256"], len(pages), chars,
                    method, r["rel_path"]))
        db.execute("DELETE FROM pages WHERE doc_id=?", (did,))
        db.execute("DELETE FROM pages_fts WHERE doc_id=?", (did,))
        for page, text in pages:
            db.execute("INSERT INTO pages VALUES (?,?,?)", (did, page, text))
            db.execute("INSERT INTO pages_fts (text, doc_id, page) VALUES (?,?,?)", (text, did, page))

    # --- 3. OCR
    def stage_ocr(self):
        db, cfg = self.db, self.cfg
        cand = [(i, p, sha) for i, p, sha in db.execute(
            "SELECT id, path, sha256 FROM docs WHERE method='no-text' AND lower(ext)='.pdf'")
            if self.force or self._marker("ocr", i) != sha]
        if not cand:
            return
        why = None if self.use_ocr else "OCR выключен (ocr = false или --no-ocr)"
        why = why or _extract.ocr_ready(cfg.ocr_langs)
        if why:
            self._note(f"сканов без текста: {len(cand)}; OCR пропущен — {why}")
            return
        words = cfg.profile.ocr_words()
        done_texts = {}
        for did, rel, sha in cand:
            self.log(f"[{did}] OCR {rel[:70]}")
            try:
                texts = _extract.ocr_pdf(cfg.root / rel, dpi=cfg.ocr_dpi, psm=cfg.ocr_psm,
                                         workers=cfg.ocr_workers, langs=cfg.ocr_langs,
                                         words_path=cfg.profile.ocr_words_path,
                                         tmp_dir=cfg.index_dir / ".ocr_tmp", log=None)
            except Exception as e:  # noqa: BLE001
                self._note(f"OCR {did}: {e}")
                self.stats["errors"] += 1
                continue
            texts = [ocrfix.fix(t, words) for t in texts]
            self._set_marker("ocr", did, sha)
            if sum(len(t) for t in texts) == 0:
                continue                                 # распознать нечего: остаётся текстовый слой
            done_texts[did] = texts
        if done_texts:                                   # корпусная правка редких словоформ по всем OCR-страницам
            fixes = ocrfix.corpus_correction([t for ts in done_texts.values() for t in ts])
            for did, texts in done_texts.items():
                texts = [ocrfix.apply_fixes(t, fixes) for t in texts]
                d = db.execute("SELECT section, ext, path, sha256 FROM docs WHERE id=?", (did,)).fetchone()
                r = {"id": did, "section": d[0], "ext": d[1], "rel_path": d[2], "sha256": d[3]}
                self._write_doc(r, [(str(i + 1), t) for i, t in enumerate(texts)], "tesseract")
                self.stats["ocr"] += 1
            db.commit()

    # --- 4. леммы, разделы, реквизиты
    def stage_lemma(self):
        db = self.db
        regm = {r["id"]: r for r in self.rows}
        sigs = self._doc_sigs()
        for did in self._pending("lemma"):
            db.execute("DELETE FROM pages_lemma WHERE doc_id=?", (did,))
            db.execute("DELETE FROM pages_lemma_fts WHERE doc_id=?", (did,))
            rows = db.execute("SELECT page, text FROM pages WHERE doc_id=? ORDER BY CAST(page AS INTEGER), rowid",
                              (did,)).fetchall()
            section = None
            for page, text in rows:
                section = detect_section(text, section)
                lm = norm.lemmatize(text or "")
                db.execute("INSERT INTO pages_lemma VALUES (?,?,?,?)", (did, page, section, lm))
                db.execute("INSERT INTO pages_lemma_fts (text_lemma, doc_id, page, section) VALUES (?,?,?,?)",
                           (lm, did, page, section))
            r = regm.get(did, {})
            _meta.build_doc(db, did, r.get("title", ""), r.get("year", ""), self.pats)
            self._set_marker("lemma", did, sigs[did])
            self.stats["lemma"] += 1
            if self.stats["lemma"] % 200 == 0:
                db.commit()
                self.log(f"  леммы: {self.stats['lemma']} документов")
        db.commit()

    # --- 5. таблицы
    def stage_tables(self):
        db, cfg = self.db, self.cfg
        if not cfg.tables:
            return
        sigs = self._doc_sigs()
        pending = self._pending("tables")
        todo = set(pending)
        pdfs = [(i, p, m, c) for i, p, m, c in db.execute(
            "SELECT id, path, method, chars FROM docs WHERE lower(ext)='.pdf'") if i in todo]
        have_plumber = pdftables.available()
        if pdfs and not have_plumber:
            self._note("таблицы PDF пропущены: pip install 'ru-corpus-kit[tables]'")
        for did, rel, method, chars in pdfs:
            if method not in ("pdftotext", "no-text") or not chars:
                self._set_marker("tables", did, sigs[did])           # скан/ошибка: таблиц по тексту нет
                continue
            if not have_plumber:
                continue
            path = cfg.root / rel
            db.execute("DELETE FROM table_raw WHERE doc_id=?", (did,))
            err = None
            try:
                tabs = pdftables.extract_doc(path)
            except Exception as e:  # noqa: BLE001
                tabs, err = [], str(e)
                self.log(f"  ! таблицы {did}: {e}")
            db.executemany("INSERT INTO table_raw VALUES (?,?,?,?)",
                           [(did, f"{p}/т{t}", t, f"Таблица {t}\n{x}") for p, t, x in tabs])
            db.execute("INSERT OR REPLACE INTO table_raw_docs VALUES (?,?,?)", (did, len(tabs), err))
            n = T.rebuild_doc_cells(db, did, self.dims)
            if cfg.wide_tables and wide.available():
                try:
                    _pa, nw = wide.add_doc_wide(db, did, path, self.dims)
                    n += nw
                except Exception as e:  # noqa: BLE001
                    self.log(f"  ! широкие таблицы {did}: {e}")
            self._set_marker("tables", did, sigs[did])
            self.stats["tables"] += 1
            db.commit()
        for did in set(pending) - {d for d, *_ in pdfs}:               # не PDF: таблиц стадии нет
            self._set_marker("tables", did, sigs[did])
        db.commit()

    # --- 6. bm25
    def stage_bm25(self):
        import sqlite3
        cfg = self.cfg
        db = sqlite3.connect(cfg.kb_path)
        try:
            sigs = {i: _sig(sha, m, c) for i, sha, m, c in db.execute("SELECT id, sha256, method, chars FROM docs")}
            if not cfg.bm25_path.exists():
                db.execute("DELETE FROM kit_meta WHERE k LIKE 'bm25:%'")
                db.commit()
            marked = {k[5:]: v for k, v in db.execute("SELECT k, v FROM kit_meta WHERE k LIKE 'bm25:%'")}
            pending = sorted(i for i, s in sigs.items() if (self.force or marked.get(i) != s))
            have = set()
            if cfg.bm25_path.exists():
                bm = sqlite3.connect(cfg.bm25_path)
                have = {i for (i,) in bm.execute("SELECT DISTINCT doc_id FROM chunks")}
                bm.close()
            gone = sorted(have - set(sigs))
            if not pending and not gone and cfg.bm25_path.exists():
                return
            if not cfg.bm25_path.exists() or self.force:
                _bm25.build_full(cfg.kb_path, cfg.bm25_path, cfg.bm25_window, cfg.bm25_overlap, log=self.log)
            else:
                _bm25.sync(cfg.kb_path, cfg.bm25_path, pending, gone, cfg.bm25_window, cfg.bm25_overlap, log=self.log)
            for did in pending:
                db.execute("INSERT OR REPLACE INTO kit_meta VALUES(?,?)", (f"bm25:{did}", sigs[did]))
            for did in gone:
                db.execute("DELETE FROM kit_meta WHERE k=?", (f"bm25:{did}",))
            db.commit()
            self.stats["bm25"] = len(pending)
        finally:
            db.close()


def run(cfg: Config, **kw):
    stages = kw.pop("stages", STAGES)
    return Indexer(cfg, **kw).run(stages)
