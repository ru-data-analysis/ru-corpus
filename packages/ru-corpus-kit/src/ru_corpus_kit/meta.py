# -*- coding: utf-8 -*-
"""Год и реквизиты документа из текста шапки, а не из имени файла.

Из первых страниц документа извлекается:
  act_date   — дата акта: «01.01.2099 № 12-А», «от 01.12.2025 № …», «28 декабря 2020 года № 428»;
  act_no     — номер акта (общий шаблон «№ …»; отраслевой шаблон задаёт профиль);
  period     — отчётный/плановый период: «за 2023 год», «на 31 декабря 2016 г.», «на 2026–2030 годы»,
               «по состоянию на 1 квартал 2025», «за Август 2026 г.»;
  year_text  — год для фильтра: начало периода, иначе год даты акта;
  year_src   — откуда год: period | title | act_date | filename | none.

Таблица docs_meta_text(doc_id, year_text, year_src, act_date, act_no, period, period_kind,
year_filename).
"""
from __future__ import annotations

import re

MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
          "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
MON_RE = r"(январ[ья]|феврал[ья]|марта?|апрел[ья]|мая|май|июн[ья]|июл[ья]|августа?|" \
         r"сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])"
YEAR = r"(19[89]\d|20[0-4]\d)"

# общий номер акта: 45, 45-А, 123/24, АБ-12/25, ДОК-ТР-5/24
ACT_NO_CORE = r"((?:[A-ZА-ЯЁ]{1,6}-)*\d{1,6}(?:[-/][A-Za-zА-Яа-яЁё0-9]{1,6})*)"
NO_MARK = r"(?:№|N|No)"

PERIOD_PATTERNS = [
    ("range", re.compile(r"на\s+" + YEAR + r"\s*[–—\-]\s*" + YEAR + r"\s*год", re.I)),
    ("za", re.compile(r"\bза\s+" + YEAR + r"\s*(?:год|г\.)", re.I)),
    ("za_month", re.compile(r"\bза\s+(?:[IV]+\s+квартал|" + MON_RE + r")\s+" + YEAR, re.I)),
    ("on_date", re.compile(r"\bна\s+\d{1,2}\s+" + MON_RE + r"\s+" + YEAR, re.I)),
    ("on_date2", re.compile(r"\bна\s+\d{2}\.\d{2}\.(" + r"19[89]\d|20[0-4]\d" + r")", re.I)),
    ("state", re.compile(r"состоянию\s+на\s+(?:\d\s+квартал\s+)?" + YEAR, re.I)),
    ("na", re.compile(r"\bна\s+" + YEAR + r"\s*год", re.I)),
    ("quarter", re.compile(r"\b[1-4IV]+\s+квартал[а-я]*\s+" + YEAR, re.I)),
]


class ActPatterns:
    """Регулярные выражения реквизитов акта; act_no из профиля заменяет общий шаблон."""

    def __init__(self, act_no_regex: str = ""):
        custom = bool(act_no_regex)
        no = act_no_regex or ACT_NO_CORE
        mark = r"(?:№|N|No|ny|nm)?" if custom else NO_MARK
        self.date_no = re.compile(r"(?:от\s+)?(\d{2})\.(\d{2})\.(\d{4})\s*(?:г\.?\s*)?" + mark + r"\s*" + no, re.I)
        self.word_date_no = re.compile(r"(\d{1,2})\s+" + MON_RE + r"\s+" + YEAR + r"\s*(?:г\.|года)?\s*"
                                       + (r"(?:№\s*)?" if custom else NO_MARK + r"\s*") + no, re.I)
        self.annex = re.compile(r"Приложение\s*(?:№\s*\d+)?\s*к\s+(?:приказу|распоряжению|постановлению).{0,120}?"
                                r"от\s+(\d{2})\.(\d{2})\.(\d{4})\s*(?:№|N)\s*" + no, re.I | re.S)
        self.no_only = re.compile(r"№\s*" + no, re.I)


DEFAULT_PATTERNS = ActPatterns()


def norm_no(s):
    return s.upper().replace(" ", "")


def head_text(db, doc_id, max_chars=6000):
    rows = db.execute("SELECT page, text FROM pages WHERE doc_id=?", (doc_id,)).fetchall()

    def key(r):
        m = re.match(r"^(\d+)", r[0] or "")
        return (0, int(m.group(1))) if m else (1, 0)
    rows = [r for r in rows if "/т" not in (r[0] or "")]
    rows.sort(key=key)
    txt = " ".join((r[1] or "") for r in rows[:3])
    txt = re.sub(r"(?<=\b[А-ЯЁ]) (?=[А-ЯЁ]\b)", "", txt)          # «П Р И К А З» -> «ПРИКАЗ»
    txt = re.sub(r"[  \s]+", " ", txt)
    return txt[:max_chars]


def header_of(text):
    """Шапка: до преамбулы «В соответствии с…» / «На основании…», не длиннее 900 знаков.
    Реквизиты ищутся только здесь — в теле акта стоят ссылки на ЧУЖИЕ акты."""
    m = re.search(r"\b(В соответствии с|На основании|Руководствуясь)", text)
    end = m.start() if m else 900
    return text[:min(end, 900)]


def parse(text, pats: ActPatterns = DEFAULT_PATTERNS):
    res = {"act_date": None, "act_no": None, "period": None, "period_kind": None,
           "year_text": None, "year_src": "none"}
    full, text = text, header_of(text)
    m = pats.date_no.search(text)
    if m:
        d, mo, y, no = m.groups()
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            res["act_date"] = f"{y}-{mo}-{d}"
            res["act_no"] = norm_no(no)
    if not res["act_date"]:
        m = pats.word_date_no.search(text)
        if m:
            d, mon, y, no = m.groups()
            mn = next(v for k, v in MONTHS.items() if mon.lower().startswith(k))
            res["act_date"] = f"{y}-{mn:02d}-{int(d):02d}"
            res["act_no"] = norm_no(no)
    if not res["act_date"]:
        m = pats.annex.search(full[:8000])          # приложение к самому акту: реквизиты родительского
        if m:
            d, mo, y, no = m.groups()
            res["act_date"], res["act_no"] = f"{y}-{mo}-{d}", norm_no(no)
    if not res["act_no"]:
        m = pats.no_only.search(text)
        if m:
            res["act_no"] = norm_no(m.group(1))
    best = None
    for kind, rx in PERIOD_PATTERNS:
        m = rx.search(full[:3000])
        if m and (best is None or m.start() < best[1].start()):
            best = (kind, m)
    if best:
        kind, m = best
        years = [int(g) for g in m.groups() if g and re.fullmatch(r"\d{4}", g)]
        res["period"] = m.group(0)
        res["period_kind"] = kind
        if years:
            res["year_text"] = years[0]
            res["year_src"] = "period"
    if res["year_text"] is None:                    # год в заголовке: «Отчёт 2026 (утв.)»
        m = re.search(r"(?<![\d.])" + YEAR + r"(?![\d.])", full[:200])
        if m:
            res["year_text"], res["year_src"] = int(m.group(1)), "title"
            res["period"], res["period_kind"] = m.group(0), "title"
    if res["year_text"] is None and res["act_date"]:
        res["year_text"] = int(res["act_date"][:4])
        res["year_src"] = "act_date"
    return res


SCHEMA = """CREATE TABLE IF NOT EXISTS docs_meta_text(doc_id TEXT PRIMARY KEY, year_text INT, year_src TEXT,
  act_date TEXT, act_no TEXT, period TEXT, period_kind TEXT, year_filename TEXT)"""


def build_doc(db, doc_id, title, year_filename, pats: ActPatterns = DEFAULT_PATTERNS):
    t = head_text(db, doc_id)
    r = parse((title or "") + " " + t, pats)
    yf = int(year_filename) if year_filename and str(year_filename).isdigit() else None
    if r["year_text"] is None and yf:
        r["year_text"], r["year_src"] = yf, "filename"
    db.execute("INSERT OR REPLACE INTO docs_meta_text VALUES(?,?,?,?,?,?,?,?)",
               (doc_id, r["year_text"], r["year_src"], r["act_date"], r["act_no"],
                r["period"], r["period_kind"], year_filename))
    return r
