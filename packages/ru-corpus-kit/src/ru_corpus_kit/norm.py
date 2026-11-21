# -*- coding: utf-8 -*-
"""Русская нормализация для поиска: леммы, стеммер, синонимы, разбор запроса.

FTS5 с токенайзером unicode61 различает «тариф» и «тарифы». Поэтому текст и запрос
приводятся к леммам (pymorphy3) одним и тем же алгоритмом. Без pymorphy3 работает
упрощённый стеммер (один проход по самому длинному окончанию).

Словарь синонимов/аббревиатур в ядре пустой: его передают снаружи (файл из corpus.toml
или профиль), поэтому ядро не привязано к отрасли.
"""
from __future__ import annotations

import re
from functools import lru_cache

try:
    import pymorphy3
    _MORPH = pymorphy3.MorphAnalyzer()
except Exception:                       # лемматизатор необязателен: есть стеммер
    _MORPH = None

ENDINGS = [
    "вшись", "ившись", "ывшись", "вши", "ивши", "ывши",
    "иями", "ями", "ами", "ией", "иям", "ием", "иях", "ими", "ыми",
    "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий", "ый",
    "ой", "ем", "им", "ым", "ом", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею",
    "ила", "ыла", "ена", "ейте", "уйте", "ите", "или", "ыли", "ило", "ыло",
    "ено", "ует", "уют", "ены", "ить", "ыть", "ишь", "ете", "йте", "ешь", "нно",
    "ев", "ов", "ье", "еи", "ии", "ям", "ам", "ах", "ях", "ию", "ью", "ия", "ья",
    "ят", "ит", "ыт", "ую", "ла", "на", "ли", "ло", "но", "ет", "ют", "ны",
    "ть", "й", "л", "н", "ю", "а", "е", "и", "о", "у", "ы", "я", "ь",
]

# служебные слова, которые не должны попадать в запрос
RU_STOP = set("""и в во не на по с со к у за из от до для при как что это или а но
об о же ли бы то так все еще уже где когда какой какая какие чем чего чему
свой своя свои этот эта эти тот та те весь вся которые который которая которое
которых котором также том числе""".split())

TOKEN_RE = re.compile(r"[a-zа-я0-9]+(?:[./·\-][a-zа-я0-9]+)*", re.I)
DIGIT_GAP = re.compile(r"(?<=\d)[   ]+(?=\d)")


def has_morph() -> bool:
    return _MORPH is not None


def stem(word: str) -> str:
    """Основа русской словоформы. Числа и латиница возвращаются как есть."""
    w = word.lower().replace("ё", "е")
    if not re.search(r"[а-я]", w) or len(w) <= 3:
        return w
    for suffix in ("ся", "сь"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[:-len(suffix)]
    w = re.sub(r"(ость|ости|остью|остей)$", "ост", w)
    hit = None
    for suffix in sorted(ENDINGS, key=len, reverse=True):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            hit = suffix
            break
    if hit:
        w = w[:-len(hit)]
    if w.endswith("ь") and len(w) > 3:
        w = w[:-1]
    return w


@lru_cache(maxsize=300_000)
def lemma(word: str) -> str:
    """Нормальная форма слова; без pymorphy3 — основа из стеммера."""
    w = word.lower().replace("ё", "е")
    if not re.search(r"[а-я]", w):
        return w
    if _MORPH is not None:
        return _MORPH.parse(w)[0].normal_form
    return stem(w)


def lemmatize(text: str) -> str:
    """Текст -> леммы через пробел (основной режим индексации)."""
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = DIGIT_GAP.sub("", text)
    return " ".join(lemma(t) for t in TOKEN_RE.findall(text))


def normalize(text: str) -> str:
    """Текст -> основы через пробел (запасной режим без лемматизатора)."""
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = DIGIT_GAP.sub("", text)
    return " ".join(stem(t) for t in TOKEN_RE.findall(text))


def tokens(query: str, drop_stop: bool = True):
    out = []
    for t in TOKEN_RE.findall(query.replace("ё", "е")):
        low = t.lower()
        if len(low) < 2:
            continue
        if drop_stop and low in RU_STOP:
            continue
        out.append(low)
    return out


@lru_cache(maxsize=10_000)
def _phrase_lemma(phrase: str) -> str:
    return " ".join(lemma(w) for w in TOKEN_RE.findall(phrase.replace("ё", "е")))


def query_groups(query: str, expand: bool = True, mode: str = "lemma", synonyms=None):
    """Список OR-групп. Элемент группы — слово (префиксный поиск) либо фраза-синоним."""
    synonyms = synonyms or {}
    groups = []
    fn = lemma if mode == "lemma" else stem
    for low in tokens(query):
        alts = [("term", fn(low))]
        if expand and low in synonyms:
            for phrase in synonyms[low]:
                alts.append(("phrase", _phrase_lemma(phrase)))
        groups.append(alts)
    return groups


def fts_query(query: str, expand: bool = True, mode: str = "lemma", operator: str = "or",
              synonyms=None) -> str:
    """Запрос для FTS5. По умолчанию OR по словам: BM25 сам поднимает наверх страницы,
    где совпало больше слов. operator="and" — строгий режим."""
    parts = []
    for group in query_groups(query, expand, mode, synonyms):
        alts = []
        for kind, val in group:
            if not val:
                continue
            alts.append(f'"{val}"*' if kind == "term" else f'"{val}"')
        if alts:
            parts.append("(" + " OR ".join(dict.fromkeys(alts)) + ")")
    joiner = " AND " if operator == "and" else " OR "
    return joiner.join(parts)
