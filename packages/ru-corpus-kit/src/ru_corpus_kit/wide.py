# -*- coding: utf-8 -*-
"""Широкие альбомные таблицы PDF -> ячейки по координатам (нужен PyMuPDF: extras [tables]).

Текст широкой таблицы (pdftotext/pdfplumber) теряет графы: подписи строк видны, числа разных граф
склеены. Здесь таблица восстанавливается по геометрии страницы:

  1. линейки сетки — тонкие закрашенные прямоугольники, линии и рамки (page.get_drawings());
  2. каждое слово относится к ячейке: ближайшие линейки слева/справа/сверху/снизу, перекрывающие
     центр слова (объединённые ячейки шапки получаются сами);
  3. шапка = ячейки выше первой строки данных (строка нумерации граф «1 2 3 …» в путь не идёт);
     путь графы = тексты ячеек шапки, чей x-диапазон накрывает центр ячейки данных, сверху вниз;
  4. подпись строки = «№ пункта + текст графы наименования»; значения — ячейки с числом
     (нд / х / годы / номера пунктов — не значения);
  5. многостраничная таблица: страница без собственной шапки наследует шапку предыдущей,
     если x-границы граф совпадают (>= 80 % ячеек данных накрыты).

Результат кладётся в те же поля, что читает tables.query (table_cells), с method='bbox'.
Страница берётся, только если обычный способ не дал на ней ни одной ячейки с непустой шапкой.
"""
from __future__ import annotations

import re

from . import tables as T

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    try:
        import fitz
    except ImportError:
        fitz = None

TOL = 1.2                      # допуск по линейкам, pt
MAX_SEGS = 2500                # страницы с большим числом линеек — графика, а не таблица
NODATA = {"нд", "х", "x", "-", "—", "–"}
CODE_RE = re.compile(r"^[A-Za-zА-Яа-я]{1,2}[-–]?[A-Za-z]?\d[\w.\-/]*$")
IDX_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.?)$")
HYEAR_RE = re.compile(r"(?<![\d.,])(20[0-4]\d)(?!\d)(?![.,]\d)")
NUMB_RE = re.compile(r"^(\d{1,2})(?:\.(\d{1,2}))?\.?$")


def available() -> bool:
    return fitz is not None


# ---------------------------------------------------------------- геометрия

def page_segments(page):
    """Линейки сетки: вертикальные (x, y0, y1) и горизонтальные (y, x0, x1)."""
    V, H = set(), set()
    pw, ph = page.rect.width, page.rect.height
    for d in page.get_drawings():
        stroke = d.get("color")
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                w, h = r.width, r.height
                if w <= 2.5 and h > 3:
                    V.add((round((r.x0 + r.x1) / 2, 1), round(r.y0, 1), round(r.y1, 1)))
                elif h <= 2.5 and w > 3:
                    H.add((round((r.y0 + r.y1) / 2, 1), round(r.x0, 1), round(r.x1, 1)))
                elif stroke is not None and w * h < 0.5 * pw * ph:   # рамка ячейки
                    V.add((round(r.x0, 1), round(r.y0, 1), round(r.y1, 1)))
                    V.add((round(r.x1, 1), round(r.y0, 1), round(r.y1, 1)))
                    H.add((round(r.y0, 1), round(r.x0, 1), round(r.x1, 1)))
                    H.add((round(r.y1, 1), round(r.x0, 1), round(r.x1, 1)))
            elif it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.x - p2.x) <= 0.8 and abs(p1.y - p2.y) > 3:
                    V.add((round((p1.x + p2.x) / 2, 1), round(min(p1.y, p2.y), 1), round(max(p1.y, p2.y), 1)))
                elif abs(p1.y - p2.y) <= 0.8 and abs(p1.x - p2.x) > 3:
                    H.add((round((p1.y + p2.y) / 2, 1), round(min(p1.x, p2.x), 1), round(max(p1.x, p2.x), 1)))
    return sorted(V), sorted(H)


def group_cells(words, V, H):
    """Слова -> ячейки сетки. Слово вне замкнутой ячейки (заголовок документа) пропускается."""
    cells = {}
    for w in words:
        x0, y0, x1, y1, txt = w[:5]
        if not txt.strip():
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        left = [x for x, a, b in V if x <= cx and a - TOL <= cy <= b + TOL]
        right = [x for x, a, b in V if x >= cx and a - TOL <= cy <= b + TOL]
        top = [y for y, a, b in H if y <= cy and a - TOL <= cx <= b + TOL]
        bot = [y for y, a, b in H if y >= cy and a - TOL <= cx <= b + TOL]
        if not (left and right and top and bot):
            continue
        key = (round(max(left)), round(max(top)), round(min(right)), round(min(bot)))
        cells.setdefault(key, []).append(w)
    out = []
    for (l, t, r, b), ws in cells.items():
        ws = sorted(ws, key=lambda w: (w[5], w[6], w[7]))     # порядок потока страницы
        text = " ".join(w[4] for w in ws)
        out.append({"l": l, "t": t, "r": r, "b": b, "text": re.sub(r"\s+", " ", text).strip()})
    return out


# ---------------------------------------------------------------- таблица

def _is_nodata(t):
    return t.strip().lower() in NODATA


def _numbering(texts_by_l):
    """Строка нумерации граф: >= 4 ячеек «N», «N.N» (>= 80 %), неубывающих слева направо."""
    texts = [t.strip() for _, t in sorted(texts_by_l) if t.strip()]
    if len(texts) < 4:
        return False
    vals = []
    for t in texts:
        m = NUMB_RE.match(t)
        if m:
            vals.append((int(m.group(1)), int(m.group(2) or 0)))
    return len(vals) >= 0.8 * len(texts) and all(a <= b for a, b in zip(vals, vals[1:]))


def _val(c, numbering_ids):
    t = c["text"]
    if id(c) in numbering_ids or not t or _is_nodata(t) or T.YEAR_RE.match(t.strip()):
        return None
    return T.parse_num(t)


def path_for(cx, hdr):
    hs = sorted((h for h in hdr if h["l"] - TOL <= cx <= h["r"] + TOL), key=lambda h: (h["t"], h["l"]))
    parts = []
    for h in hs:
        if h["text"] and h["text"] not in parts:
            parts.append(h["text"])
    return " / ".join(parts)


def _level(h, dims):
    """Уровень/признак из пути графы (по профилю) плюс «Общий объём…» и «Итого …» -> «Всего»."""
    lv = T.level_of(h, dims)
    if lv:
        return lv
    parts = h.split(" / ")
    leaf = parts[-1]
    if re.match(r"(?i)\s*(?:общий объ[её]м|итого)\b", leaf):
        return "Всего"
    if any(re.match(r"(?i)\s*итого\b", x) for x in parts) and \
            re.match(r"(?i)^(?:утвержд\w+ )?план\w*$", leaf.strip()):
        return "Всего"
    return None


def coverage(vcells, hdr):
    if not vcells:
        return 0.0
    ok = sum(1 for c in vcells if any(h["l"] - TOL <= (c["l"] + c["r"]) / 2 <= h["r"] + TOL for h in hdr))
    return ok / len(vcells)


def analyse(cells, inherit=None, dims=T.DEFAULT_DIMS):
    """-> (cells_out, info). cells_out — как в tables.structure."""
    info = {"values": 0, "ncols": 0, "nrows": 0, "hdr": "none", "label_ratio": 0.0, "hdr_cells": []}
    if not cells:
        return [], info
    bands = {}
    for c in cells:
        bands.setdefault((c["t"], c["b"]), []).append(c)
    numbering_ids = set()
    for k, cs in bands.items():
        if _numbering([(c["l"], c["text"]) for c in cs]):
            numbering_ids.update(id(c) for c in cs)
    idx_ids = set()                       # номер пункта: самая левая ячейка строки перед подписью
    for k, cs in bands.items():
        cs_s = sorted(cs, key=lambda c: c["l"])
        if len(cs_s) >= 3 and IDX_RE.match(cs_s[0]["text"]) and id(cs_s[0]) not in numbering_ids:
            nxt = cs_s[1]["text"]
            if nxt and T.parse_num(nxt) is None and not _is_nodata(nxt) and len(nxt) > 2:
                idx_ids.add(id(cs_s[0]))
    vals = {}
    for c in cells:
        if id(c) in idx_ids:
            continue
        v = _val(c, numbering_ids)
        if v is not None:
            vals[id(c)] = v
    vcells = [c for c in cells if id(c) in vals]
    if len(vcells) < 4:
        return [], info
    data_top = min([c["t"] for c in vcells] + [c["t"] for c in cells if _is_nodata(c["text"])])
    hdr = [c for c in cells if (c["t"] + c["b"]) / 2 < data_top - 0.5 and id(c) not in numbering_ids
           and c["text"]]
    if len(hdr) >= 3 and coverage(vcells, hdr) >= 0.8:
        info["hdr"] = "own"
    elif inherit and coverage(vcells, inherit) >= 0.8:
        hdr, info["hdr"] = inherit, "inherited"
    elif hdr:
        info["hdr"] = "partial"
    else:
        hdr = []
    rows_sorted = sorted({k for k in bands if any(id(c) in vals for c in bands[k])})
    row_no = {k: i for i, k in enumerate(sorted(bands))}
    lefts = sorted({c["l"] for c in cells})
    col_no = {l: i for i, l in enumerate(lefts)}
    unit_hdr = {m.group(0) for h in hdr for m in [dims.unit.search(h["text"])] if m}
    table_unit = next(iter(unit_hdr)) if len(unit_hdr) == 1 else None
    out, labelled = [], 0
    for k in rows_sorted:
        cs = bands[k]
        cy = (k[0] + k[1]) / 2
        row_vals = [c for c in cs if id(c) in vals]
        first_l = min(c["l"] for c in row_vals)
        left_cells = [c for c in cells if c["t"] - TOL <= cy <= c["b"] + TOL and c["r"] <= first_l + TOL
                      and c["text"] and not _is_nodata(c["text"])]
        idx = next((c["text"] for c in sorted(left_cells, key=lambda c: c["l"]) if id(c) in idx_ids), "")
        cands = [c for c in left_cells if id(c) not in idx_ids and not CODE_RE.match(c["text"])
                 and len(c["text"]) > 1 and T.parse_num(c["text"]) is None]
        named = [c for c in cands if re.search(r"аименован", path_for((c["l"] + c["r"]) / 2, hdr), re.I)]
        pick = sorted(named, key=lambda c: c["l"]) if named else (
            [max(cands, key=lambda c: len(c["text"]))] if cands else [])
        label = " ".join(c["text"] for c in pick)
        label = (idx + " " + label).strip() if idx else label
        if label:
            labelled += 1
        for c in sorted(row_vals, key=lambda c: c["l"]):
            cx = (c["l"] + c["r"]) / 2
            h = path_for(cx, hdr)
            ys = [m.group(1) for hc in sorted((x for x in hdr if x["l"] - TOL <= cx <= x["r"] + TOL),
                                              key=lambda x: (x["t"], x["l"]))
                  for m in [HYEAR_RE.search(hc["text"])] if m]
            hu = dims.unit.search(h) if h else None
            out.append({"row": row_no[k], "col": col_no[c["l"]], "label": label,
                        "unit": hu.group(0) if hu else table_unit, "header": h,
                        "year": int(ys[-1]) if ys else None, "ysrc": "header" if ys else None,
                        "level": _level(h, dims) if h else None, "half": T.half_of(h) if h else None,
                        "value": vals[id(c)], "raw": c["text"]})
    info.update(hdr_cells=hdr if info["hdr"] == "own" else [], values=len(out),
                ncols=len({c["col"] for c in out}), nrows=len(rows_sorted),
                label_ratio=labelled / max(1, len(rows_sorted)))
    return out, info


def is_wide(page, info):
    """Детектор: достаточно числовых граф и (альбомная страница | очень много граф | подписи «N.N …»)."""
    if info["values"] < 8 or info["nrows"] < 2 or info["ncols"] < 5:
        return False
    landscape = page.rect.width > page.rect.height * 1.05 or page.rotation in (90, 270)
    return landscape or info["ncols"] >= 8 or (info["label_ratio"] >= 0.5 and info["ncols"] >= 6)


def process_pdf(path, pages=None, dims=T.DEFAULT_DIMS):
    """Страницы PDF -> {page: {cells, info, wide}}. Шапка наследуется между страницами."""
    if fitz is None:
        raise RuntimeError("для широких таблиц нужен PyMuPDF: pip install 'ru-corpus-kit[tables]'")
    res, inherit = {}, None
    doc = fitz.open(path)
    try:
        for pno in range(doc.page_count):
            if pages is not None and (pno + 1) not in pages:
                continue
            page = doc[pno]
            words = page.get_text("words")
            nums = sum(1 for w in words if T.parse_num(w[4]) is not None)
            if nums < 15:
                continue
            landscape = page.rect.width > page.rect.height * 1.05
            V, H = page_segments(page)
            if len(V) < 5 or len(H) < 4:
                res[pno + 1] = {"cells": [], "info": {"values": 0, "ncols": 0, "nrows": 0, "hdr": "none",
                                                      "label_ratio": 0.0, "nogrid": True,
                                                      "landscape": landscape}, "wide": False}
                continue
            if len(V) + len(H) > MAX_SEGS:
                continue
            grid = group_cells(words, V, H)
            cells, info = analyse(grid, inherit, dims)
            wide = is_wide(page, info)
            info["landscape"] = landscape
            if info["hdr"] == "own":
                inherit = info["hdr_cells"]
            info["hdr_cells"] = []
            res[pno + 1] = {"cells": cells if wide else [], "info": info, "wide": wide}
    finally:
        doc.close()
    return res


def add_doc_wide(db, doc_id, path, dims=T.DEFAULT_DIMS):
    """Дописывает ячейки широких страниц документа (method='bbox') там, где обычный способ
    не дал ячеек с шапкой. -> (страниц добавлено, ячеек)."""
    db.execute("DELETE FROM table_cells WHERE doc_id=? AND method='bbox'", (doc_id,))
    db.execute("DELETE FROM table_cells_bbox WHERE doc_id=?", (doc_id,))
    old_ok, old_tab = {}, {}
    for p, ok, tb in db.execute(
            "SELECT page, max(header IS NOT NULL AND header != ''), max(tab) FROM table_cells "
            "WHERE doc_id=? AND method IS NULL GROUP BY page", (doc_id,)):
        old_ok[p], old_tab[p] = bool(ok), tb or 0
    res = process_pdf(path, None, dims)
    rows, pages_added = [], 0
    for p in sorted(p for p, r in res.items() if r["wide"]):
        r = res[p]
        if r["info"]["hdr"] == "none" or old_ok.get(str(p)):
            continue
        pages_added += 1
        base = old_tab.get(str(p), 0)
        for c in r["cells"]:
            rows.append((doc_id, str(p), base + 1, c["row"], c["col"], c["label"], c["year"], c["level"],
                         c["half"], c["unit"], c["header"], c["value"], c["raw"], c["ysrc"], None, "bbox"))
    ph = ",".join("?" * len(T.COLS))
    db.executemany(f"INSERT INTO table_cells({','.join(T.COLS)}) VALUES({ph})", rows)
    db.executemany(f"INSERT INTO table_cells_bbox({','.join(T.COLS)}) VALUES({ph})", rows)
    return pages_added, len(rows)
