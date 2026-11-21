# -*- coding: utf-8 -*-
"""Профиль отрасли: подключаемые данные, которых нет в ядре.

Профиль — каталог с profile.toml (и файлами рядом): словарь сокращений, уровни в заголовках
таблиц, классы документов, единицы измерения, шаблон номера акта, слова для правки OCR.
Встроенные профили лежат в ru_corpus_kit/profiles/<имя>; свой можно указать путём к каталогу.
Ядро работает и без профиля (Profile.empty()).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

BUILTIN = Path(__file__).resolve().parent / "profiles"


def read_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


@dataclass
class Profile:
    name: str = ""
    description: str = ""
    synonyms: dict = field(default_factory=dict)          # сокращение -> [фразы]
    ocr_words_path: Path | None = None
    act_no: str = ""                                      # regex номера акта ("" — общий)
    levels: list = field(default_factory=list)            # [(имя, regex)]
    level_cell: str = ""                                  # regex ячейки-уровня (без «Всего»)
    extra_units: str = ""                                 # regex дополнительных единиц
    classes: list = field(default_factory=list)           # [(имя, regex)]

    @classmethod
    def empty(cls) -> "Profile":
        return cls()

    @classmethod
    def load(cls, name_or_path: str) -> "Profile":
        if not name_or_path:
            return cls.empty()
        p = Path(name_or_path).expanduser()
        if not p.is_dir():
            p = BUILTIN / name_or_path
        if not (p / "profile.toml").is_file():
            raise FileNotFoundError(f"профиль «{name_or_path}» не найден (нужен каталог с profile.toml)")
        d = read_toml(p / "profile.toml")
        syn = {}
        if d.get("synonyms") and (p / d["synonyms"]).is_file():
            syn = load_synonyms(p / d["synonyms"])
        ow = p / d["ocr_words"] if d.get("ocr_words") else None
        return cls(
            name=d.get("name", p.name), description=d.get("description", ""), synonyms=syn,
            ocr_words_path=ow if ow and ow.is_file() else None,
            act_no=d.get("act_no", ""),
            levels=[(x["name"], x["regex"]) for x in d.get("levels", [])],
            level_cell=d.get("level_cell", ""), extra_units=d.get("extra_units", ""),
            classes=[(x["name"], x["regex"]) for x in d.get("classes", [])])

    def ocr_words(self) -> set:
        if not self.ocr_words_path:
            return set()
        words = {w.strip().lower() for w in self.ocr_words_path.read_text(encoding="utf-8").splitlines()}
        return {w for w in words if len(w) >= 4}


def load_synonyms(path: Path) -> dict:
    """Файл TOML: таблица [synonyms]  «сокращение» = [«фраза», …]. Ключи приводятся к нижнему регистру."""
    d = read_toml(path)
    raw = d.get("synonyms", d)
    return {str(k).lower(): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in raw.items()}


def compile_rx(pattern: str, flags=0):
    return re.compile(pattern, flags)
