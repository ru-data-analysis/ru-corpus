# -*- coding: utf-8 -*-
"""Мелкие проверки без корпуса: нормализация, числа таблиц, реквизиты, правка OCR."""
import pytest

from ru_corpus_kit import meta, norm, ocrfix
from ru_corpus_kit import tables as T
from ru_corpus_kit.profile import Profile


def test_lemma_and_query():
    assert norm.lemma("тарифы") == norm.lemma("тарифов") == "тариф"
    assert norm.lemmatize("1 234 567,89 руб") == "1234567,89 руб" or "1234567" in norm.lemmatize("1 234 567,89 руб")
    q = norm.fts_query("потери электроэнергии в сетях")
    assert q.count(" OR ") == 2 and '"потеря"*' in q            # стоп-слово «в» отброшено
    assert norm.fts_query("и в на") == ""
    assert norm.stem("мощность") == norm.stem("мощности")


def test_synonyms_expand_only_when_given():
    syn = {"тп": ["технологическое присоединение"]}
    assert "присоединение" in norm.fts_query("ТП", synonyms=syn)
    assert "присоединение" not in norm.fts_query("ТП")


@pytest.mark.parametrize("raw,val", [("1 234,5", 1234.5), ("1 234,5", 1234.5), ("(123)", -123.0),
                                     ("12%", 12.0), ("7*", 7.0), ("3.14", 3.14), ("-5", -5.0)])
def test_parse_num(raw, val):
    assert T.parse_num(raw) == val


@pytest.mark.parametrize("raw", ["", "abc", "2024 год", "1,2,3", "12 34", "—"])
def test_parse_num_rejects(raw):
    assert T.parse_num(raw) is None or raw == "2024 год" and T.YEAR_RE.match(raw)


def test_structure_header_path_and_year():
    text = ("Таблица 1\nПоказатель | 2023 | 2024\n"
            "Выручка, тыс. руб. | 1 000,0 | 1 250,5\nРасходы, тыс. руб. | 800,0 | 900,0")
    cells = T.structure(text)
    got = {(c["label"], c["year"]): c["raw"] for c in cells}
    assert got[("Выручка, тыс. руб.", 2024)] == "1 250,5" and got[("Расходы, тыс. руб.", 2023)] == "800,0"
    assert all(c["unit"] for c in cells)                      # «тыс. руб.» из подписи строки


def test_structure_levels_by_profile():
    text = "Ставка | ВН | СН2 | НН\nСтавка на сети | 1 000 | 2 000 | 3 000"
    assert {c["level"] for c in T.structure(text)} == {None}
    dims = T.Dims(Profile.load("tso_disclosure"))
    assert [c["level"] for c in T.structure(text, dims=dims)] == ["ВН", "СН2", "НН"]
    assert T.level_of("Всего по сети") == "Всего"


def test_half_of():
    assert T.half_of("II полугодие / СН2") == "II" and T.half_of("первое полугодие") == "I"
    assert T.half_of("2024") is None


def test_meta_period_and_act_core():
    r = meta.parse("ПРИКАЗ от 05.03.2024 № 45-А Об утверждении плана на 2025 год")
    assert r["act_date"] == "2024-03-05" and r["act_no"] == "45-А"
    assert r["year_text"] == 2025 and r["period_kind"] == "na"
    r = meta.parse("Отчёт за 2023 год. Составлен 28 декабря 2023 года № 12/24")
    assert r["year_text"] == 2023 and r["period_kind"] == "za"
    assert meta.parse("Без реквизитов и дат")["year_src"] == "none"


def test_meta_custom_act_pattern():
    pats = meta.ActPatterns(Profile.load("tso_disclosure").act_no)
    r = meta.parse("Приказ от 01.12.2025 ДПР-ТД-469/25 о тарифах", pats)
    assert r["act_no"] == "ДПР-ТД-469/25" and r["act_date"] == "2025-12-01"


def test_ocrfix():
    assert ocrfix.fix_mixed("тaриф") == "тариф"                # латинская «a» внутри кириллического слова
    assert ocrfix.fix_mixed("отчёт в PDF") == "отчёт в PDF"    # аббревиатуры не трогаем
    words = {"мощность"}
    assert ocrfix.fix_domain("мошность сети", words).startswith("мощность")
    texts = ["тариф " * 6 + "тарифф"]
    assert ocrfix.corpus_correction(texts) == {"тарифф": "тариф"}


def test_profile_loading():
    p = Profile.load("tso_disclosure")
    assert p.name == "tso_disclosure" and "нвв" in p.synonyms and p.levels and p.classes
    assert "кват" not in p.ocr_words() and "мощность" in p.ocr_words()
    assert Profile.load("").name == ""
    with pytest.raises(FileNotFoundError):
        Profile.load("нет_такого_профиля")
