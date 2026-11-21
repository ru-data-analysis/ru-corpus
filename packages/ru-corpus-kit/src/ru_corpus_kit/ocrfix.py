# -*- coding: utf-8 -*-
"""Коррекция OCR-текста под русские документы.

Две беды tesseract на русских сканах:
  1. смешение латиницы и кириллицы внутри слова («тaриф», «Мocква»);
  2. опечатки в терминах («мошность», «тарифф»).

  fix_mixed(text)                — латинские двойники -> кириллица, если слово в основном кириллическое
                                   (аббревиатуры вроде PDF, kWh не трогает);
  fix_domain(text, words)        — слова, которых нет в словаре pymorphy3, правятся на 1 правку
                                   до слова из списка терминов (список даёт профиль);
  corpus_correction(texts)       — редкие словоформы правятся по частотным соседям корпуса.
"""
from __future__ import annotations

import re
from collections import Counter

from . import norm

LAT2CYR = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
    "k": "к", "m": "м", "t": "т", "h": "н", "b": "в", "n": "п", "r": "г",
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О",
    "P": "Р", "C": "С", "T": "Т", "X": "Х", "Y": "У",
})

CYR = re.compile(r"[а-яё]", re.I)
LAT = re.compile(r"[a-z]", re.I)
TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё][\w\-]*")
LETTERS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


def fix_mixed(text: str) -> str:
    def repl(m):
        w = m.group(0)
        cyr = len(CYR.findall(w))
        lat = len(LAT.findall(w))
        if cyr >= 2 and lat and cyr / max(1, cyr + lat) >= 0.6:
            return w.translate(LAT2CYR)
        return w
    return TOKEN.sub(repl, text)


def _edits1(w):
    out = set()
    for i in range(len(w) + 1):
        a, b = w[:i], w[i:]
        if b:
            out.add(a + b[1:])
        if len(b) > 1:
            out.add(a + b[1] + b[0] + b[2:])
        if b:
            for c in LETTERS:
                out.add(a + c + b[1:])
                out.add(a + c + b)
    return out


def fix_domain(text: str, words) -> str:
    morph = norm._MORPH
    if morph is None or not words:
        return text

    def repl(m):
        w = m.group(0)
        low = w.lower()
        if len(low) < 5 or not CYR.search(low) or morph.word_is_known(low) or low in words:
            return w
        cand = _edits1(low) & words
        if len(cand) == 1:
            fixed = cand.pop()
            return fixed.capitalize() if w[:1].isupper() else fixed
        return w
    return TOKEN.sub(repl, text)


def fix(text: str, words=None) -> str:
    return fix_domain(fix_mixed(text or ""), words or set())


def _deletes(w):
    return {w[:i] + w[i + 1:] for i in range(len(w))}


def corpus_correction(texts, min_good=5):
    """Правка редких словоформ по частотным соседям: токен, встретившийся один раз, заменяется
    формой на расстоянии одной правки, которая встретилась >= min_good раз."""
    freq = Counter()
    for t in texts:
        for w in TOKEN.findall(t):
            if CYR.search(w):
                freq[w.lower()] += 1
    index = {}
    for w, n in freq.items():
        if n >= min_good and len(w) >= 4:
            for d in _deletes(w) | {w}:              # и само слово: ловит лишнюю букву в редкой форме
                index.setdefault(d, []).append((n, w))
    fixes = {}
    for w, n in freq.items():
        if n != 1 or len(w) < 5:
            continue
        best = None
        for d in _deletes(w) | {w}:                  # замена, вставка и удаление одной буквы
            for cand_n, cand in index.get(d, ()):
                if cand != w and (best is None or cand_n > best[0]):
                    best = (cand_n, cand)
        if best:
            fixes[w] = best[1]
    return fixes


def apply_fixes(text: str, fixes: dict) -> str:
    return TOKEN.sub(lambda m: fixes.get(m.group(0).lower(), m.group(0)), text)
