# -*- coding: utf-8 -*-
"""Инструменты корпуса с JSON-выводом: search, page, table, doc, number, aggregate, calc.

Каждая функция возвращает словарь (CLI печатает его одним JSON-объектом). Агенту не нужно писать
одноразовые скрипты: цифра берётся инструментом, с документом, страницей и якорем.
"""
from __future__ import annotations

import ast
import hashlib
import re
from decimal import Decimal, getcontext

from . import answer as _answer
from . import tables as T

SP = "\\s\u00a0\u202f"


def norm_num(s):
    return re.sub(r"[\s\u00a0\u202f]+", "", s or "").replace(".", ",")


# ---------------------------------------------------------------- page / doc / table

def page(kit, doc, page_no, max_chars=20000):
    db = kit.db
    r = db.execute("SELECT text FROM pages WHERE doc_id=? AND page=?", (doc, str(page_no))).fetchone()
    if not r:
        pages = [p for (p,) in db.execute("SELECT page FROM pages WHERE doc_id=? LIMIT 400", (doc,))]
        return {"ok": False, "error": f"нет страницы {page_no} у {doc}", "pages": pages[:80]}
    sec = db.execute("SELECT section FROM pages_lemma WHERE doc_id=? AND page=?", (doc, str(page_no))).fetchone()
    reg = kit.registry().get(doc, {})
    meth = db.execute("SELECT method FROM docs WHERE id=?", (doc,)).fetchone()
    text = r[0] or ""
    return {"ok": True, "doc": doc, "page": str(page_no), "file": kit.file_of(doc),
            "title": reg.get("title", ""), "section": (sec[0] if sec and sec[0] else None),
            "method": meth[0] if meth else None, "ocr": bool(meth and meth[0] == "tesseract"),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "chars": len(text),
            "origin": kit.origin_of(doc, page_no), "text": text[:max_chars]}


def table(kit, q, year=None, level=None, half=None, doc=None, page_no=None, n=10):
    rows = T.query(kit.db, q, year, level, half, doc, limit=n, page=page_no, with_method=True)
    return {"ok": True, "cells": [{
        "value": raw, "number": None, "unit": u, "label": lab, "year": y, "level": lv, "half": hf,
        "doc": d, "file": kit.file_of(d), "page": p, "method": meth or "pdfplumber",
        "anchor": f"стр. {p}, таблица {tb}, строка {row}, графа «{h}»"}
        for d, p, tb, row, h, lab, y, lv, hf, u, v, raw, meth in rows]}


def doc(kit, doc_id=None, find=None, n=15):
    db, reg = kit.db, kit.registry()
    has_mt = db.execute("SELECT name FROM sqlite_master WHERE name='docs_meta_text'").fetchone()
    derived = set(kit.cfg.derived_sections)

    def card(did):
        r = reg.get(did, {})
        d = db.execute("SELECT method, pages, chars FROM docs WHERE id=?", (did,)).fetchone()
        m = db.execute("SELECT year_text, year_src, act_date, act_no, period FROM docs_meta_text WHERE doc_id=?",
                       (did,)).fetchone() if has_mt else None
        return {"doc": did, "file": kit.file_of(did), "title": r.get("title"),
                "section": r.get("section"), "type": r.get("type"), "ext": r.get("ext"),
                "indexed": bool(d), "method": d[0] if d else None, "pages": d[1] if d else None,
                "year": m[0] if m else r.get("year"), "year_src": m[1] if m else "filename",
                "act_date": m[2] if m else None, "act_no": m[3] if m else None, "period": m[4] if m else None,
                "derived": r.get("section") in derived, "from_archive": bool(r.get("archive"))}
    if find:
        words = [w.lower() for w in find.split() if len(w) > 2]
        hits = [k for k, r in reg.items()
                if all(w in (r.get("title", "") + " " + r.get("rel_path", "")).lower() for w in words)]
        return {"ok": True, "found": len(hits), "docs": [card(h) for h in hits[:n]]}
    if doc_id not in reg:
        return {"ok": False, "error": f"нет {doc_id} в реестре"}
    return {"ok": True, **card(doc_id)}


# ---------------------------------------------------------------- number

def number(kit, doc_id, page_no, value):
    r = kit.db.execute("SELECT text FROM pages WHERE doc_id=? AND page=?", (doc_id, str(page_no))).fetchone()
    if not r:
        return {"ok": False, "error": f"нет страницы {page_no} у {doc_id}"}
    text = r[0] or ""
    want = norm_num(value)
    pos = norm_num(text).find(want)
    ctx = None
    if pos >= 0:
        for m in re.finditer(r"\d[\d\s\u00a0\u202f.,]*", text):
            if want in norm_num(m.group(0)):
                ctx = re.sub(r"\s+", " ", text[max(0, m.start() - 120): m.end() + 60])
                break
    return {"ok": True, "doc": doc_id, "page": str(page_no), "value": value, "found": pos >= 0, "context": ctx,
            "note": None if pos >= 0 else "числа на странице нет: проверьте страницу, единицы и OCR"}


NUM_Q = re.compile(r"^\s*[-−]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})*(?:[.,]\d+)?\s*$|^\s*[-−]?\d+(?:[.,]\d+)?\s*$")


def number_hits(kit, query, n=10):
    """Поиск числа по всем страницам без учёта разделителей тысяч (пробел, неразрывный пробел, без
    пробела) и десятичного знака. FTS режет «12 345,67» на токены и числа не находит — поэтому
    отдельный проход."""
    want = norm_num(query).lstrip("-−")
    core = want[-6:] if len(want) > 6 else want
    core_dot = core.replace(",", ".")
    reg, hits = kit.registry(), []
    for did, pg, text in kit.db.execute(
            "SELECT doc_id, page, text FROM pages WHERE text LIKE ? OR text LIKE ?", (f"%{core}%", f"%{core_dot}%")):
        for m in re.finditer(r"\d[\d\s\u00a0\u202f.,]*", text or ""):
            if want in norm_num(m.group(0)):
                hits.append({"doc": did, "file": kit.file_of(did), "page": pg,
                             "title": reg.get(did, {}).get("title", ""), "sources": ["number"],
                             "snippet": re.sub(r"\s+", " ", text[max(0, m.start() - 160): m.end() + 80])})
                break
        if len(hits) >= n:
            break
    return hits


def search(kit, query, n=5, rerank=None):
    if NUM_Q.match(query):
        hits = number_hits(kit, query, n=max(n, 10))
        return {"ok": True, "q": query, "mode": "number",
                "verdict": "есть доказательства" if hits else "числа в индексе нет",
                "evidence": hits, "facts": [], "scope": "all",
                "note": ("запрос — число: поиск по всем страницам без учёта разделителей тысяч и "
                         "десятичного знака; дальше number на найденной странице")}
    res = _answer.answer(kit, query, n=n, rerank=rerank)
    res["scope"] = "all"
    res["note"] = ("поиск по всему индексу" if res["verdict"] != "в корпусе нет" else
                   "обе ветки поиска отказали: ответа на этот вопрос в корпусе нет")
    return {"ok": True, **res}


# ---------------------------------------------------------------- aggregate
# Агрегаты по графе таблицы, разложенной в тексте страницы как «ячейка | ячейка | …»
# (XLSX/XLSM, XLS, DOCX, CSV). «Итого» не суммируется (двойной счёт), а сверяется.

def _fold(s):
    return re.sub(r"\s+", " ", (s or "").lower().replace("ё", "е")).strip()


def _num(cell):
    c = re.sub(r"[\s\u00a0\u202f]", "", cell or "")
    if not re.fullmatch(r"[-−]?\d+(?:[.,]\d+)?", c):
        return None
    return float(c.replace("−", "-").replace(",", "."))


def _pipe_rows(text):
    """Логические строки таблицы: перенос строки внутри ячейки (шапка) склеивается."""
    lines = (text or "").split("\n")
    counts = [ln.count("|") for ln in lines if ln.count("|") >= 2]
    if not counts:
        return []
    sep = max(set(counts), key=counts.count)          # самое частое число разделителей
    rows, buf = [], ""
    for ln in lines:
        if not buf and "|" not in ln:
            continue                                  # заголовок документа, пояснения
        if buf and re.match(r"\s*\d+\s*\|", ln):     # «130 | …» — новая строка: недобранная уходит как есть
            rows.append([c.strip() for c in buf.split("|")])
            buf = ""
        buf = (buf + " " + ln) if buf else ln
        if buf.count("|") >= sep:
            rows.append([c.strip() for c in buf.split("|")])
            buf = ""
    return rows


def _sheet_rows(path, sheet):
    """Строки листа из исходного XLSX/XLSM (пустые ячейки на своих местах). None — нельзя."""
    if path is None or path.suffix.lower() not in (".xlsx", ".xlsm") or not path.exists():
        return None
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet in wb.sheetnames else None
        if ws is None:
            return None
        rows = []
        for r in ws.iter_rows(values_only=True):
            cells = ["" if v is None else (repr(v) if isinstance(v, float) else str(v)) for v in r]
            while cells and cells[-1] == "":
                cells.pop()
            if any(c.strip() for c in cells):
                rows.append([c.replace("\n", " ").strip() for c in cells])
        wb.close()
        return rows
    except Exception:  # noqa: BLE001
        return None


def _find_col(header, q):
    qf = _fold(q)
    if qf.isdigit() and 1 <= int(qf) <= len(header):          # номер графы с 1
        return int(qf) - 1
    hits = [i for i, h in enumerate(header) if qf in _fold(h)]
    if hits:
        return hits[0]
    words = [w for w in re.findall(r"\w+", qf) if len(w) > 2]
    best = max(range(len(header)), key=lambda i: sum(w[:max(4, len(w) - 2)] in _fold(header[i]) for w in words))
    return best if words and any(w[:max(4, len(w) - 2)] in _fold(header[best]) for w in words) else None


def _stats(vals):
    if not vals:
        return {"count": 0}
    return {"count": len(vals), "sum": round(sum(vals), 6), "avg": round(sum(vals) / len(vals), 6),
            "min": min(vals), "max": max(vals)}


def aggregate(kit, doc_id, column, page_no=None, column2=None, where_expr=None):
    db = kit.db
    if page_no:
        pages = db.execute("SELECT page, text FROM pages WHERE doc_id=? AND page=?", (doc_id, str(page_no))).fetchall()
    else:
        pages = db.execute("SELECT page, text FROM pages WHERE doc_id=?", (doc_id,)).fetchall()
    if not pages:
        return {"ok": False, "error": f"нет страниц у {doc_id}" + (f" (страница {page_no})" if page_no else "")}
    where = None
    if where_expr:
        m = re.match(r"\s*(.+?)\s*(=|~)\s*(.*)$", where_expr)
        if not m:
            return {"ok": False, "error": "where: «графа=значение» (точно) или «графа~часть» (подстрока)"}
        where = m.groups()
    reg = kit.registry().get(doc_id, {})
    per_page, v1, v2, skipped, first, last, header_used = [], [], [], [], None, None, None
    unaligned, totals = [], []
    src = kit.source_path(doc_id)
    mode = None
    for pg, text in pages:
        rows = _sheet_rows(src, pg)
        mode = mode or ("исходный файл (openpyxl)" if rows is not None else "текст индекса")
        if rows is None:
            rows = _pipe_rows(text)
        # шапка — строка ширины таблицы, в основном не числа; точное вхождение слов запроса важнее основ
        width = max((len(r) for r in rows), default=0)
        cand = [i for i, r in enumerate(rows) if len([c for c in r if c]) >= max(3, int(width * 0.6))
                and sum(_num(c) is not None for c in r) < len(r) / 2]
        hi = next((i for i in cand if any(_fold(column) in _fold(c) for c in rows[i])), None)
        if hi is None:
            hi = next((i for i in cand if _find_col(rows[i], column) is not None), None)
        if hi is None:
            continue
        header = rows[hi]
        c1 = _find_col(header, column)
        c2 = _find_col(header, column2) if column2 else None
        cw = _find_col(header, where[0]) if where else None
        if column2 and c2 is None:
            return {"ok": False, "error": f"графа «{column2}» не найдена", "header": header}
        if where and cw is None:
            return {"ok": False, "error": f"графа фильтра «{where[0]}» не найдена", "header": header}
        n_rows, p1, p2 = 0, [], []
        for r in rows[hi + 1:]:
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r)) if mode.startswith("исходный") else r
            if len(r) != len(header):
                unaligned.append({"page": pg, "cells": len(r), "row": r[:4]})
                continue
            if any(re.match(r"(итого|всего)", _fold(c)) for c in r[:3]):
                totals.append({"page": pg, "row": r, "value": r[c1]})   # не суммируем: двойной счёт
                continue
            if where:
                cell = _fold(r[cw])
                if (where[1] == "=" and cell != _fold(where[2])) or (where[1] == "~" and _fold(where[2]) not in cell):
                    continue
            n_rows += 1
            x = _num(r[c1])
            if x is None:
                if len(skipped) < 8:
                    skipped.append({"page": pg, "row": r[:3], "value": r[c1]})
                continue
            if c2 is not None:
                y = _num(r[c2])
                if y is None:
                    if len(skipped) < 8:
                        skipped.append({"page": pg, "row": r[:3], "value2": r[c2]})
                    continue
                p2.append(y)
            p1.append(x)
            first = first or {"page": pg, "row": r}
            last = {"page": pg, "row": r}
        header_used = header_used or {"column": header[c1], "column2": header[c2] if c2 is not None else None,
                                      "where": [header[cw], where[1], where[2]] if where else None,
                                      "header": header}
        per_page.append({"page": pg, "rows": n_rows, "numeric": len(p1), "sum": round(sum(p1), 6)})
        v1 += p1
        v2 += p2
    if not per_page:
        return {"ok": False, "error": f"на страницах {doc_id} нет таблицы «ячейка | ячейка» с графой «{column}»",
                "hint": "таблицы PDF смотрите через table; страницы — через page"}
    if not v1:
        return {"ok": False, "error": f"в графе «{header_used['column']}» нет чисел (строк: "
                f"{sum(p['rows'] for p in per_page)}) — это текстовая графа; для подсчёта строк возьмите числовую графу",
                "column": header_used["column"], "header": header_used["header"]}
    s1 = _stats(v1)
    res = {"ok": True, "doc": doc_id, "file": kit.file_of(doc_id),
           "title": reg.get("title", ""), "pages": [p["page"] for p in per_page],
           "origin": kit.origin_of(doc_id, per_page[0]["page"]),
           **header_used, "rows_matched": sum(p["rows"] for p in per_page), "column_stats": s1,
           "source_mode": mode, "unaligned_rows": len(unaligned), "unaligned_examples": unaligned[:6],
           "skipped_non_numeric": skipped, "first_row": first, "last_row": last, "per_page": per_page,
           "total_row_in_source": None}
    if v2:
        s2 = _stats(v2)
        res["column2_stats"] = s2
        res["ratio_sum"] = round(s1["sum"] / s2["sum"], 8) if s2.get("sum") else None
        res["formula"] = (f"Σ«{header_used['column']}» / Σ«{header_used['column2']}» = "
                          f"{s1['sum']} / {s2['sum']} = {res['ratio_sum']} (по {s1['count']} строкам)")
    else:
        res["formula"] = f"Σ«{header_used['column']}» = {s1.get('sum')} (по {s1['count']} строкам)"
    res["total_row_in_source"] = totals[0] if totals else None     # в сумму не входит: только сверка
    if totals:
        tv = _num(totals[0]["value"])
        res["total_matches_sum"] = (abs(tv - s1.get("sum", 0)) <= max(0.01, abs(tv) * 1e-6)) if tv is not None else None
    if unaligned:
        res["warning"] = (f"{len(unaligned)} строк не совпали с шапкой по числу ячеек (в тексте индекса пустые "
                          "ячейки выброшены) и НЕ вошли в сумму — итог неполный; откройте строки через page")
    res["note"] = ("сумма вычислена по строкам; строки «Итого/Всего» в источнике нет — указывайте это как расчёт"
                   if not res["total_row_in_source"] else
                   "в источнике есть итоговая строка: в сумму не включена, сверка — total_matches_sum")
    return res


# ---------------------------------------------------------------- calc
# Точная десятичная арифметика по выражению с числами в русской записи.

getcontext().prec = 40
NUM_IN_EXPR = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def _dec_eval(node):
    if isinstance(node, ast.Expression):
        return _dec_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return Decimal(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _dec_eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        l, r = _dec_eval(node.left), _dec_eval(node.right)
        if isinstance(node.op, ast.Add):
            return l + r
        if isinstance(node.op, ast.Sub):
            return l - r
        if isinstance(node.op, ast.Mult):
            return l * r
        if r == 0:
            raise ZeroDivisionError("деление на ноль")
        return l / r
    raise ValueError("допустимы только числа, + - * / и скобки")


def _fmt_ru(d, digits):
    q = d.quantize(Decimal(1).scaleb(-digits)) if digits is not None else d.normalize()
    sign = "-" if q < 0 else ""
    txt = format(abs(q), "f")
    ip, _, fp = txt.partition(".")
    ip = re.sub(r"(?<=\d)(?=(\d{3})+$)", " ", ip)
    return sign + ip + ("," + fp if fp else "")


def calc(expr, digits=None):
    e = expr.replace("−", "-").replace("×", "*").replace("÷", "/").replace("%", "/100")
    nums = []

    def sub(m):
        nums.append(m.group(0))
        return repr(norm_num(m.group(0)).replace(",", "."))
    py = NUM_IN_EXPR.sub(sub, e)
    val = _dec_eval(ast.parse(py, mode="eval"))
    if digits is None:   # знаков после запятой — как у самого точного операнда (для + и -)
        digits = max((len(x.replace(".", ",").split(",")[1]) if "," in x.replace(".", ",") else 0)
                     for x in nums) if nums else 0
        if any(op in expr for op in "*/×÷%"):
            digits = max(digits, 4)
    return {"ok": True, "expr": expr, "operands": nums, "result": _fmt_ru(val, digits),
            "exact": format(val.normalize(), "f"), "digits": digits,
            "note": "в ответ — выражение и результат; операнды берутся из инструментов с doc и страницей"}
