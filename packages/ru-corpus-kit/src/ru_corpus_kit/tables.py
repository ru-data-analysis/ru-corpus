# -*- coding: utf-8 -*-
"""Таблицы в структуру: ячейки с именованными измерениями.

Таблица PDF приходит текстом «ячейка | ячейка» (страницы «N/тK», таблица table_raw). Для расчётов
нужны поля, а не строки, поэтому каждая таблица разворачивается в «длинный» формат — одна запись
на числовую ячейку:

  table_cells(doc_id, page, tab, row, col, label, year, level, half, unit, header, value, raw,
              ysrc, cls, method)

  label  — подпись строки (с протяжкой вниз: строки-продолжения наследуют подпись);
  year   — год из ячейки строки или из заголовка графы (иначе — из названия документа);
  level  — уровень из заголовка графы или ячейки строки (набор задаёт профиль; «Всего» — в ядре);
  half   — полугодие: I / II;
  unit   — единица измерения из ячеек строки или шапки графы;
  header — путь заголовка графы сверху вниз («II полугодие / СН2»);
  value  — число (пробелы тысяч убраны, запятая -> точка, (123) -> -123).

Якорь для ответа: «стр. N, таблица K, строка r, графа "<header>"».
Отраслевое (уровни, единицы, классы документов) приходит из профиля через Dims.
"""
from __future__ import annotations

import re

SP = "   "                      # пробел, неразрывный, узкий неразрывный
NUM_RE = re.compile(rf"^\(?-?\d{{1,3}}(?:[{SP}]\d{{3}})*(?:[.,]\d+)?\)?$|^\(?-?\d+(?:[.,]\d+)?\)?$")
YEAR_RE = re.compile(r"^(?:за\s+|на\s+)?(19[89]\d|20[0-4]\d)(?:\s*г\.?|\s*год)?$", re.I)
LAT2CYR = str.maketrans("HCBAEKMOPTX", "НСВАЕКМОРТХ")
FOOT_RE = re.compile(r"\s*(?:\*+|<\d+>)$")
INDEX_RE = re.compile(r"^\d+(?:\.\d+)+\.?$")          # номер пункта «1.2.3» в первой графе

_RUB = r"(?<![А-Яа-яЁё])(?:тыс\.?\s*|млн\.?\s*)?руб(?:\.|лей)?(?:\s*/\s*[^\s|]+(?:\s+в\s+месяц)?)?"


class Dims:
    """Отраслевые измерения таблиц: уровни, единицы, классы документов (из профиля)."""

    def __init__(self, profile=None):
        levels = list(profile.levels) if profile else []
        levels.append(("Всего", r"\bВсего\b"))
        self.level_patterns = levels                  # (имя, regex-строка): для разбора вопросов
        self.levels = [(n, re.compile(rx, re.I)) for n, rx in levels]
        cell = (profile.level_cell + "|" if profile and profile.level_cell else "") + "Всего"
        self.level_cell = re.compile(rf"^(?:{cell})\.?$", re.I)
        extra = profile.extra_units if profile else ""
        self.unit = re.compile("(" + _RUB + ("|" + extra if extra else "") + r"|%|процентов|шт\.?)", re.I)
        self.classes = [(n, re.compile(rx)) for n, rx in (profile.classes if profile else [])]


DEFAULT_DIMS = Dims()


def parse_num(s):
    s = FOOT_RE.sub("", s.strip())
    if s.endswith("%"):
        s = s[:-1].strip()
    if not s or not NUM_RE.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    for ch in SP:
        s = s.replace(ch, "")
    s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def is_numbering_row(cells):
    """Строка нумерации граф «1 | 2 | 3 | …»."""
    ints = [c for c in cells if re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?", c.strip())]
    return len(ints) >= 4 and len(ints) >= 0.7 * len([c for c in cells if c.strip()])


def is_data_row(cells):
    nums = [c for c in cells if parse_num(c) is not None and not YEAR_RE.match(c.strip())]
    big = [c for c in nums if len(re.sub(r"\D", "", c)) >= 3]
    return len(big) >= 2 or (len(nums) >= 3)


def level_of(h, dims=DEFAULT_DIMS):
    h = h.translate(LAT2CYR)          # OCR/pdfplumber: «HH», «CH-I» латиницей
    for name, rx in dims.levels:
        if rx.search(h):
            return name
    return None


def half_of(h):
    m = re.search(r"\b(I{1,2}|[12])(?:\s*-?\s*[ео]е)?\s*полугоди", h, re.I)
    if not m:
        m2 = re.search(r"\b(перв|втор)\w*\s+полугоди", h, re.I)
        if m2:
            return "I" if m2.group(1).lower() == "перв" else "II"
        return None
    return {"1": "I", "2": "II"}.get(m.group(1), m.group(1))


def cell_level(c, total=False, dims=DEFAULT_DIMS):
    """Ячейка целиком — уровень («ВН», «СН I»); «Всего» — только если total
    (в шапке есть «Уровень напряжения»), иначе это итог бухгалтерской строки."""
    c = c.strip().translate(LAT2CYR)
    lv = level_of(c, dims) if c and len(c) <= 8 and dims.level_cell.match(c) else None
    return None if lv == "Всего" and not total else lv


def is_data_row_relaxed(cells):
    """Строка с хотя бы одним «большим» числом (разреженные таблицы: одно число на строку)."""
    if is_numbering_row(cells):
        return False
    for j, c in enumerate(cells):
        c = c.strip()
        if not c or YEAR_RE.match(c) or (j == 0 and INDEX_RE.match(c)):
            continue
        if parse_num(c) is not None and len(re.sub(r"\D", "", c)) >= 3:
            return True
    return False


def is_section_row(r, dims=DEFAULT_DIMS):
    ne = [c.strip() for c in r if c.strip()]
    if not 1 <= len(ne) <= 2 or not re.match(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.?)(?:\s|$)", ne[0]):
        return False
    j = " ".join(ne)
    return not (half_of(j) or level_of(j, dims) or re.search(r"\b20[0-4]\d\b", j))


def structure(text, ctx_year=None, dims=DEFAULT_DIMS):
    rows = [[c.strip() for c in ln.split("|")] for ln in text.splitlines() if "|" in ln]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    first = next((i for i, r in enumerate(rows) if is_data_row(r)), None)
    first_rx = next((i for i, r in enumerate(rows) if is_data_row_relaxed(r)), None)
    if first is None or (first_rx is not None and first_rx < first):
        first = first_rx
    if first is None:
        return []
    num_row = next((i for i, r in enumerate(rows[:first]) if is_numbering_row(r)), None)
    head = [r for r in rows[:(num_row if num_row is not None else first)] if not is_numbering_row(r)]
    head = [r for k, r in enumerate(head) if k == 0 or not is_section_row(r, dims)]
    filled = []                                    # протяжка объединённых ячеек шапки вправо
    for r in head:
        out, last = [], ""
        for j, c in enumerate(r):
            if c:
                last = c
            out.append(c or (last if j > 0 else ""))
        filled.append(out)
    headers = [" / ".join(dict.fromkeys(fr[j] for fr in filled if fr[j])) for j in range(width)]
    cells = []
    idx_col = [bool(re.search(r"№|п/п", h)) for h in headers]
    total_ok = bool(re.search(r"уровень\s+напряжения", " ".join(headers), re.I))
    label, unit, row_half = "", None, None
    for i, r in enumerate(rows):
        if i < first or is_numbering_row(r):
            continue
        rh = next((half_of(c) for c in r if half_of(c)), None)
        if rh and not is_data_row(r):
            row_half = rh
        texts = [c for c in r if c and parse_num(c) is None and not YEAR_RE.match(c)
                 and c not in ("х", "x", "-", "—")]
        row_lv = next((cell_level(t, total_ok, dims) for t in texts if cell_level(t, total_ok, dims)), None)
        lab = [t for t in texts if not dims.unit.fullmatch(t) and not re.fullmatch(r"[\d.]+", t)
               and not cell_level(t, total_ok, dims)]
        if lab:
            label = max(lab, key=len)
        u = next((dims.unit.search(t).group(0) for t in texts if len(t) <= 40 and dims.unit.search(t)), None)
        if u:
            unit = u
        year = next((int(YEAR_RE.match(c).group(1)) for c in r if YEAR_RE.match(c.strip())), None)
        for j, c in enumerate(r):
            v = parse_num(c)
            if v is None or YEAR_RE.match(c.strip()):
                continue
            h = headers[j] if j < len(headers) else ""
            if (j < len(idx_col) and idx_col[j]) or (j == 0 and INDEX_RE.match(c.strip())):
                continue                      # графа «№ п/п» / номер пункта — не значение
            hy = re.search(r"\b(20[0-4]\d)\b", h)
            hu = dims.unit.search(h)
            cu = u or (hu.group(0) if hu else None) or unit
            if cu is None and c.strip().endswith("%"):
                cu = "%"
            cells.append({"row": i, "col": j, "label": label, "unit": cu, "header": h,
                          "year": year or (int(hy.group(1)) if hy else None),
                          "ysrc": "row" if year else ("header" if hy else None),
                          "level": level_of(h, dims) or row_lv, "half": half_of(h) or row_half,
                          "value": v, "raw": c})
    if ctx_year and cells and not any(c["year"] for c in cells):    # год только в названии документа
        for c in cells:
            c["year"], c["ysrc"] = ctx_year, "doc"
    return cells


def doc_class(title_text, dims=DEFAULT_DIMS):
    t = re.sub(r"\s+", " ", (title_text or "").lower())
    for name, rx in dims.classes:
        if rx.search(t):
            return name
    return None


COLS = ("doc_id", "page", "tab", "row", "col", "label", "year", "level", "half", "unit", "header",
        "value", "raw", "ysrc", "cls", "method")

SCHEMA = """
CREATE TABLE IF NOT EXISTS table_raw(doc_id TEXT, page TEXT, tab INT, text TEXT);
CREATE TABLE IF NOT EXISTS table_raw_docs(doc_id TEXT PRIMARY KEY, n INT, err TEXT);
CREATE TABLE IF NOT EXISTS table_cells(doc_id TEXT, page TEXT, tab INT, row INT, col INT,
    label TEXT, year INT, level TEXT, half TEXT, unit TEXT, header TEXT, value REAL, raw TEXT,
    ysrc TEXT, cls TEXT, method TEXT);
CREATE TABLE IF NOT EXISTS table_cells_bbox(doc_id TEXT, page TEXT, tab INT, row INT, col INT,
    label TEXT, year INT, level TEXT, half TEXT, unit TEXT, header TEXT, value REAL, raw TEXT,
    ysrc TEXT, cls TEXT, method TEXT);
CREATE INDEX IF NOT EXISTS ix_tc ON table_cells(doc_id, year, level, half);
CREATE INDEX IF NOT EXISTS ix_tc_doc_page ON table_cells(doc_id, page);
CREATE INDEX IF NOT EXISTS ix_tcb ON table_cells_bbox(doc_id, page);
"""


def rebuild_doc_cells(db, doc_id, dims=DEFAULT_DIMS):
    """Ячейки обычных таблиц документа из table_raw (method NULL). -> число ячеек."""
    db.execute("DELETE FROM table_cells WHERE doc_id=?", (doc_id,))
    ctx = None
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='docs_meta_text'").fetchone():
        r = db.execute("SELECT year_text FROM docs_meta_text WHERE doc_id=? AND period_kind IN ('za','na') "
                       "AND year_text IS NOT NULL", (doc_id,)).fetchone()
        ctx = r[0] if r else None
    r1 = db.execute("SELECT text FROM pages WHERE doc_id=? AND page='1'", (doc_id,)).fetchone()
    cls = doc_class((r1[0] or "")[:600] if r1 else "", dims)
    n = 0
    for page, text in db.execute("SELECT page, text FROM table_raw WHERE doc_id=?", (doc_id,)).fetchall():
        m = re.match(r"^(\d+)/т(\d+)$", page)
        if not m:
            continue
        cells = structure(text or "", ctx if cls else None, dims)
        db.executemany(
            f"INSERT INTO table_cells({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})",
            [(doc_id, m.group(1), int(m.group(2)), c["row"], c["col"], c["label"], c["year"], c["level"],
              c["half"], c["unit"], c["header"], c["value"], c["raw"], c.get("ysrc"), cls, None)
             for c in cells])
        n += len(cells)
    return n


def _norm_label(x):
    x = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[ivx]+\.?)\s+", "", (x or "").lower())
    return re.sub(r"[^а-яёa-z0-9]+", " ", x).strip()


def query(db, q, year=None, level=None, half=None, doc=None, limit=10, page=None, with_method=False):
    """Ячейки по подписи строки. Порядок: точное совпадение подписи (без номера пункта), затем начало
    подписи, затем прочие; ячейки с непустым путём графы раньше безымянных; method='bbox' раньше
    старых; далее по (документ, страница, таблица, строка, графа) — ячейки одной строки идут подряд."""
    db.create_function("lower", 1, lambda s: (s or "").lower())       # sqlite lower() не знает кириллицу
    words = [w for w in re.findall(r"[а-яёa-z0-9]+", q.lower()) if len(w) > 3]
    has_m = "method" in [r[1] for r in db.execute("PRAGMA table_info(table_cells)")]
    sql = "SELECT doc_id, page, tab, row, header, label, year, level, half, unit, value, raw, col" \
          + (", method" if has_m else ", NULL") + " FROM table_cells WHERE 1=1"
    args = []
    for w in words:
        sql += " AND lower(label) LIKE ?"
        args.append(f"%{w[:max(4, len(w) - 2)]}%")
    for k, v in (("year", year), ("level", level), ("half", half), ("doc_id", doc), ("page", page)):
        if v is not None:
            sql += f" AND {k} = ?"
            args.append(str(v) if k == "page" else v)
    sql += " LIMIT 20000"
    rows = db.execute(sql, args).fetchall()
    qn = _norm_label(q)

    def tier(lab):
        ln = _norm_label(lab)
        return 0 if ln == qn else (1 if ln.startswith(qn) else 2)
    rows.sort(key=lambda r: (tier(r[5]), 0 if r[4] else 1,
                             0 if r[13] == "bbox" else 1, r[0], int(r[1]) if str(r[1]).isdigit() else 0,
                             r[2], r[3], r[12]))
    return [(r[:12] + (r[13],)) if with_method else r[:12] for r in rows[:limit]]
