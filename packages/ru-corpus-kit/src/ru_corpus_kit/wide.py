# -*- coding: utf-8 -*-
"""Широкие альбомные таблицы PDF -> ячейки по координатам (pdfplumber, MIT; extras [tables]).

Текст широкой таблицы (pdftotext/pdfplumber) теряет графы: подписи строк видны, числа разных граф
склеены. Здесь таблица восстанавливается по геометрии страницы:

  1. линейки сетки — тонкие закрашенные прямоугольники, линии и рамки (page.rects, page.lines, page.curves);
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

TOL = 1.2                      # допуск по линейкам, pt
MAX_SEGS = 2500                # страницы с большим числом линеек — графика, а не таблица
NODATA = {"нд", "х", "x", "-", "—", "–"}
CODE_RE = re.compile(r"^[A-Za-zА-Яа-я]{1,2}[-–]?[A-Za-z]?\d[\w.\-/]*$")
IDX_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.?)$")
HYEAR_RE = re.compile(r"(?<![\d.,])(20[0-4]\d)(?!\d)(?![.,]\d)")
NUMB_RE = re.compile(r"^(\d{1,2})(?:\.(\d{1,2}))?\.?$")


def available() -> bool:
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- геометрия

def _seg(V, H, x0, y0, x1, y1):
    """Отрезок пути -> вертикальная (x, y0, y1) или горизонтальная (y, x0, x1) линейка."""
    if abs(x0 - x1) <= 0.8 and abs(y0 - y1) > 3:
        V.add((round((x0 + x1) / 2, 1), round(min(y0, y1), 1), round(max(y0, y1), 1)))
    elif abs(y0 - y1) <= 0.8 and abs(x0 - x1) > 3:
        H.add((round((y0 + y1) / 2, 1), round(min(x0, x1), 1), round(max(x0, x1), 1)))


def page_segments(page):
    """Линейки сетки: вертикальные (x, y0, y1) и горизонтальные (y, x0, x1).
    Координаты pdfplumber — в системе показанной страницы (поворот /Rotate уже учтён), y сверху вниз."""
    V, H = set(), set()
    pw, ph = float(page.width), float(page.height)
    for r in page.rects:
        x0, x1, y0, y1 = r["x0"], r["x1"], r["top"], r["bottom"]
        w, h = x1 - x0, y1 - y0
        if w <= 2.5 and h > 3:
            V.add((round((x0 + x1) / 2, 1), round(y0, 1), round(y1, 1)))
        elif h <= 2.5 and w > 3:
            H.add((round((y0 + y1) / 2, 1), round(x0, 1), round(x1, 1)))
        elif r.get("stroke") and w * h < 0.5 * pw * ph:             # рамка ячейки
            V.add((round(x0, 1), round(y0, 1), round(y1, 1)))
            V.add((round(x1, 1), round(y0, 1), round(y1, 1)))
            H.add((round(y0, 1), round(x0, 1), round(x1, 1)))
            H.add((round(y1, 1), round(x0, 1), round(x1, 1)))
    for ln in page.lines:
        _seg(V, H, ln["x0"], ln["top"], ln["x1"], ln["bottom"])
    for cv in page.curves:                                           # ломаные: отрезки между вершинами
        cur = start = None
        for el in cv.get("path") or []:
            op = el[0]
            if op == "m":
                cur = start = el[1]
            elif op == "l" and cur is not None:
                _seg(V, H, cur[0], cur[1], el[1][0], el[1][1])
                cur = el[1]
            elif op == "c":
                cur = el[3]
            elif op == "h" and cur is not None and start is not None:
                _seg(V, H, cur[0], cur[1], start[0], start[1])
                cur = start
    return sorted(V), sorted(H)


def page_chars(pg, mb, rotation):
    """Символы страницы из PDFium (pypdfium2): [{text, x0, x1, top, bottom, rot, size}] в системе показанной
    страницы (x вправо, y сверху вниз, как у pdfplumber). pdfminer теряет текст шрифтов с встроенной
    кодировкой-CMap (на таких страницах пропадают целые графы), PDFium читает их.
    mb — MediaBox (l, b, r, t); rotation — /Rotate страницы (0/90/180/270). Как и pdfplumber, координаты
    PDF берутся без сдвига на начало MediaBox: сверху вниз считается от высоты MediaBox."""
    import math

    import pypdfium2.raw as pdfium_c
    is_gen = getattr(pdfium_c, "FPDFText_IsGenerated", None)
    tp = pg.get_textpage()
    try:
        W, H = mb[2] - mb[0], mb[3] - mb[1]
        out = []
        for i in range(tp.count_chars()):
            cp = pdfium_c.FPDFText_GetUnicode(tp.raw, i)
            if cp == 2:                                                     # дефис на переносе строки (метка PDFium)
                cp = 45
            if cp < 33 or cp == 0xFFFE or cp == 0xFFFF:                    # пробел, перевод строки, служебные
                gen = bool(is_gen(tp.raw, i)) if is_gen else False         # вставлен PDFium, в потоке PDF его нет
                out.append({"text": "", "gen": gen})
                continue
            l, b, r, t = tp.get_charbox(i, loose=True)
            if rotation == 90:
                x0, x1, top, bot = b, t, l, r
            elif rotation == 180:
                x0, x1, top, bot = W - r, W - l, b, t
            elif rotation == 270:
                x0, x1, top, bot = H - t, H - b, W - r, W - l
            else:
                x0, x1, top, bot = l, r, H - t, H - b
            ang = pdfium_c.FPDFText_GetCharAngle(tp.raw, i) - math.radians(rotation)
            vert = abs(math.sin(ang)) > 0.7                                 # повёрнут на ±90°
            out.append({"text": chr(cp), "x0": x0, "x1": x1, "top": top, "bottom": bot, "rot": vert,
                        "size": (x1 - x0) if vert else (bot - top)})
        return out
    finally:
        tp.close()


def _continues(p, c, gap_k=0.25):
    """Символ c продолжает слово после p (символы идут в порядке потока PDF): та же строка (или та же
    вертикаль у повёрнутого текста) и зазор не больше gap_k кегля."""
    if c["rot"] != p["rot"]:
        return False
    size = max(c["size"], p["size"], 1.0)
    if not c["rot"]:
        # одна строка: рамки по вертикали перекрываются хотя бы наполовину (индекс/сноска «%1» ниже кегля)
        ov = min(c["bottom"], p["bottom"]) - max(c["top"], p["top"])
        if ov < 0.5 * max(0.1, min(c["bottom"] - c["top"], p["bottom"] - p["top"])):
            return False
        gap = c["x0"] - p["x1"]
        return -0.5 * size <= gap <= gap_k * size and c["x0"] > p["x0"] - 0.1
    if abs(c["x0"] - p["x0"]) > max(1.0, 0.35 * size):
        return False
    return max(c["top"] - p["bottom"], p["top"] - c["bottom"]) <= gap_k * size


def raw_words(chars):
    """Слова страницы без привязки к сетке: [(x0, y0, x1, y1, текст, символы)] в системе показанной страницы.
    Слово — цепочка подряд идущих в потоке PDF символов (горизонтальных или повёрнутых, например подписи
    граф «снизу вверх»). Кластеризация строк по всей странице (extract_words) здесь не годится: в плотной
    таблице строки соседних граф сцепляются по вертикали, и слова ячейки перемешиваются.
    Если в потоке есть символы пробела (обычный случай), слова разделяют именно они, а разрядка букв
    (подписи, растянутые по ширине графы) слово не рвёт; без пробельных символов — зазор не больше
    четверти кегля."""
    n_sp = sum(1 for c in chars if not c["text"] and not c.get("gen"))
    gap_k = 1.2 if n_sp >= 0.04 * max(1, len(chars)) else 0.25
    out, cur, soft = [], [], False

    def flush():
        if cur:
            out.append((min(c["x0"] for c in cur), min(c["top"] for c in cur),
                        max(c["x1"] for c in cur), max(c["bottom"] for c in cur),
                        "".join(c["text"] for c in cur), list(cur)))
            cur.clear()

    for c in chars:
        if not c["text"]:
            if c.get("gen"):
                soft = True              # пробел вставил PDFium (разные текстовые объекты): решает зазор
            else:
                flush()
            continue
        if cur and not _continues(cur[-1], c, 0.1 if soft else gap_k):
            flush()
        soft = False
        cur.append(c)
    flush()
    return out


def split_words(words, V=()):
    """Слово, через которое проходит вертикальная линейка сетки, режется по ней (соседние графы с узким
    зазором иначе склеились бы в одно слово). -> [(x0, y0, x1, y1, текст, 0, 0, номер)]."""
    out = []
    for x0, y0, x1, y1, t, ch in words:
        cy = (y0 + y1) / 2
        cuts = sorted(x for x, a, b in V if x0 + 0.5 < x < x1 - 0.5 and a - TOL <= cy <= b + TOL) \
            if ch and len(ch) > 1 else []
        if not cuts:
            out.append((x0, y0, x1, y1, t))
            continue
        parts = [[] for _ in range(len(cuts) + 1)]
        for c in ch:
            parts[sum(1 for x in cuts if x < (c["x0"] + c["x1"]) / 2)].append(c)
        for part in parts:
            if part:
                out.append((min(c["x0"] for c in part), min(c["top"] for c in part),
                            max(c["x1"] for c in part), max(c["bottom"] for c in part),
                            "".join(c["text"] for c in part)))
    return [(*w, 0, 0, i) for i, w in enumerate(out)]


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
    landscape = page.width > page.height * 1.05 or (page.rotation or 0) % 360 in (90, 270)
    return landscape or info["ncols"] >= 8 or (info["label_ratio"] >= 0.5 and info["ncols"] >= 6)


def process_pdf(path, pages=None, dims=T.DEFAULT_DIMS):
    """Страницы PDF -> {page: {cells, info, wide}}. Шапка наследуется между страницами."""
    try:
        import pdfplumber
        import pypdfium2 as pdfium
    except ImportError:
        raise RuntimeError("для широких таблиц нужны pdfplumber и pypdfium2: "
                           "pip install 'ru-corpus-kit[tables]'") from None
    res, inherit = {}, None
    doc = pdfium.PdfDocument(str(path))
    try:
        with pdfplumber.open(path) as pdf:
            for pno in range(len(doc)):
                if pages is not None and (pno + 1) not in pages:
                    continue
                pg = doc[pno]
                try:
                    raw = raw_words(page_chars(pg, pg.get_mediabox(), pg.get_rotation()))
                finally:
                    pg.close()
                if sum(1 for w in raw if T.parse_num(w[4]) is not None) < 8:      # грубый отсев до сетки
                    continue
                page = pdf.pages[pno]                       # линейки сетки — pdfplumber (прямоугольники, линии)
                try:
                    landscape = page.width > page.height * 1.05
                    V, H = page_segments(page)
                    if len(V) < 5 or len(H) < 4:
                        if sum(1 for w in raw if T.parse_num(w[4]) is not None) < 15:
                            continue
                        res[pno + 1] = {"cells": [], "info": {"values": 0, "ncols": 0, "nrows": 0, "hdr": "none",
                                                              "label_ratio": 0.0, "nogrid": True,
                                                              "landscape": landscape}, "wide": False}
                        continue
                    if len(V) + len(H) > MAX_SEGS:
                        continue
                    words = split_words(raw, V)
                    if sum(1 for w in words if T.parse_num(w[4]) is not None) < 15:
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
                    page.flush_cache()
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
