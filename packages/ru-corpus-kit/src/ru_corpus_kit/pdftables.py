# -*- coding: utf-8 -*-
"""Таблицы PDF с сеткой -> текст «ячейка | ячейка» (pdfplumber; extras [tables]).

Таблица кладётся в table_raw под номером страницы «N/тK» (K — номер таблицы на странице); оттуда её
разворачивает tables.rebuild_doc_cells в ячейки с измерениями.
"""
from __future__ import annotations


def available() -> bool:
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


def rows_to_text(rows):
    lines = []
    for row in rows:
        cells = [(c or "").replace("\n", " ").strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def extract_doc(path, max_pages=200):
    """-> [(страница, номер_таблицы, текст)]."""
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages[:max_pages], 1):
            try:
                tables = page.extract_tables()
            except Exception:
                continue
            for t_no, rows in enumerate(tables, 1):
                if not rows or len(rows) < 2 or max(len(r) for r in rows) < 2:
                    continue
                text = rows_to_text(rows)
                if len(text) < 40:
                    continue
                out.append((page_no, t_no, text))
    return out
