# -*- coding: utf-8 -*-
"""Тесты ядра на синтетическом корпусе «АО «Демо-Сеть»» (корпус генерируется в фикстуре)."""
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from conftest import HAVE_DOCX, OCR_WHY, PREFIX, build, cli_json, doc_id, make_project
from ru_corpus_kit import cli, config, norm, tools, wide
from ru_corpus_kit import tables as T
from ru_corpus_kit.kit import Kit
from ru_corpus_kit.profile import Profile


# ---------------------------------------------------------------- индексация

def test_index_builds(built):
    st, kit = built["stats"], built["kit"]
    n_files = len(built["files"])
    assert st["new"] == n_files and st["docs"] == n_files
    assert st["duplicates"] == 0 and st["errors"] == 0
    methods = {m: n for m, n in kit.db.execute("SELECT method, count(*) FROM docs GROUP BY method")}
    assert methods.get("pdftotext", 0) >= 2            # отчёт и приказ
    assert methods.get("openpyxl") == 1 and methods.get("text") == 1
    assert kit.db.execute("SELECT count(*) FROM pages_lemma").fetchone()[0] >= n_files
    assert kit.db.execute("SELECT count(*) FROM table_cells").fetchone()[0] > 0
    assert kit.bm.db.execute("SELECT count(*) FROM chunks").fetchone()[0] > 0
    assert (built["cfg"].index_dir / "registry.csv").exists()


def test_status(built):
    from ru_corpus_kit import status
    st = status.collect(built["cfg"])
    assert st["indexed"] and st["docs"] == len(built["files"]) and st["own_index"]
    assert st["corpus_changes"] == {"new_files": 0, "changed_files": 0, "removed_files": 0}
    assert st["bm25_chunks"] > 0 and not any(st["pending_stages"].values())
    assert "документов" in status.render(st)


# ---------------------------------------------------------------- search

def test_search_text(built):
    kit = built["kit"]
    r = tools.search(kit, "выручка от передачи электроэнергии")
    assert r["ok"] and r["verdict"] == "есть доказательства"
    first = r["evidence"][0]
    assert first["doc"] == doc_id(kit, "otchet_2024")
    assert first["page"] == "1"
    assert first["file"] == PREFIX + "reports/otchet_2024.pdf"      # префикс из corpus.toml
    assert "выручка" in first["snippet"].lower()
    assert set(first["sources"]) <= {"fts", "bm25"}


@pytest.mark.parametrize("q", ["1 234 567,89", "1234567,89", "1 234 567.89"])
def test_search_number_with_digit_groups(built, q):
    kit = built["kit"]
    r = tools.search(kit, q)
    assert r["mode"] == "number" and r["verdict"] == "есть доказательства"
    assert r["evidence"][0]["doc"] == doc_id(kit, "otchet_2024") and r["evidence"][0]["page"] == "1"
    assert r["evidence"][0]["file"].startswith(PREFIX)


def test_search_number_absent(built):
    r = tools.search(built["kit"], "98 765 432,10")
    assert r["mode"] == "number" and r["verdict"] == "числа в индексе нет" and r["evidence"] == []


def test_trap_not_in_corpus(built):
    r = tools.search(built["kit"], "Курс акций на бирже Токио")
    assert r["ok"] and r["verdict"] == "в корпусе нет"
    assert r["evidence"] == [] and r["facts"] == []
    assert "signals" in r


def test_search_scan_without_term_in_corpus_is_refused(built):
    # половина слов запроса есть в корпусе, половины нет: отказ, а не «лучшее из худшего»
    r = tools.search(built["kit"], "трансформатор динозавр юрского периода космодром")
    assert r["verdict"] == "в корпусе нет"


# ---------------------------------------------------------------- page / number / doc

def test_page(built):
    kit = built["kit"]
    d = doc_id(kit, "otchet_2024")
    r = tools.page(kit, d, "1")
    assert r["ok"] and "Демо-Сеть" in r["text"] and r["method"] == "pdftotext" and not r["ocr"]
    assert r["sha256"] == hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
    assert r["origin"] == f"{PREFIX}reports/otchet_2024.pdf#page=1"
    miss = tools.page(kit, d, "99")
    assert not miss["ok"] and "1" in miss["pages"]


def test_number_found_and_not_found(built):
    kit = built["kit"]
    d = doc_id(kit, "otchet_2024")
    ok = tools.number(kit, d, "1", "1 234 567,89")
    assert ok["found"] is True and "1 234 567,89" in ok["context"]
    assert tools.number(kit, d, "1", "1234567.89")["found"] is True       # без пробелов, точка
    no = tools.number(kit, d, "1", "9 999 999")
    assert no["found"] is False and no["context"] is None and no["note"]
    assert not tools.number(kit, d, "77", "1")["ok"]


def test_doc_card_meta_from_text(built):
    kit = built["kit"]
    r = tools.doc(kit, doc_id(kit, "otchet_2024"))
    assert r["year"] == 2024 and r["year_src"] == "period" and r["indexed"] and r["pages"] == 3
    w = tools.doc(kit, doc_id(kit, "prikaz_77"))
    assert w["act_no"] == "77-ТР" and w["act_date"] == "2024-12-01" and w["year"] == 2025
    found = tools.doc(kit, find="otchet 2024")
    assert found["found"] == 1 and found["docs"][0]["file"] == PREFIX + "reports/otchet_2024.pdf"
    assert not tools.doc(kit, "d9999")["ok"]


# ---------------------------------------------------------------- таблицы

def test_table_grid(built):
    kit = built["kit"]
    r = tools.table(kit, "Потери электроэнергии", year=2024)
    assert r["ok"] and r["cells"]
    c = r["cells"][0]
    assert c["value"] == "108,9" and c["year"] == 2024 and c["doc"] == doc_id(kit, "otchet_2024")
    assert c["page"] == "2" and "2024" in c["anchor"] and c["file"].startswith(PREFIX)
    prev = tools.table(kit, "Потери электроэнергии", year=2023)["cells"][0]
    assert prev["value"] == "112,4"
    # число с пробелом разрядов разобрано как значение, подпись протянута
    big = tools.table(kit, "Отпуск в сеть", year=2024, doc=c["doc"], page_no="2")["cells"][0]
    assert big["value"] == "5 512,3"


def test_table_wide_columns_and_years(built):
    kit = built["kit"]
    d = doc_id(kit, "prikaz_77")
    r = tools.table(kit, "Строительство подстанции", year=2026, doc=d)
    assert r["cells"], "ячейки широкой таблицы не найдены"
    c = r["cells"][0]
    assert c["value"] == "200,0" and c["year"] == 2026 and "2026" in c["anchor"]
    assert "Финансирование" in c["anchor"]                       # путь графы: объединённая шапка + год
    # графа «Итого» (объединена по вертикали) наследует год соседней графы — это приём протяжки шапки
    by_year = {x["year"]: x["value"] for x in tools.table(kit, "Строительство подстанции", doc=d, n=30)["cells"]
               if x["year"] and "Итого" not in x["anchor"]}
    assert by_year == {2025: "100,5", 2026: "200,0", 2027: "300,0", 2028: "400,0", 2029: "500,0"}
    total = [x for x in tools.table(kit, "Строительство подстанции", doc=d, n=30)["cells"] if "Итого" in x["anchor"]]
    assert total and total[0]["value"] == "1 500,5"


def test_wide_module_geometry(built):
    if not wide.available():
        pytest.skip("нет PyMuPDF")
    res = wide.process_pdf(built["files"]["wide"], dims=T.Dims(Profile.empty()))
    assert res[2]["wide"] and not res.get(1, {"wide": False})["wide"]
    cells = res[2]["cells"]
    got = {(c["label"], c["year"]): c["raw"] for c in cells if c["year"]}
    assert got[("1.2 Реконструкция кабельных линий", 2027)] == "70,0"
    assert any(c["level"] == "Всего" and c["raw"] == "350,0" for c in cells)     # графа «Итого»


def test_wide_cells_written_as_bbox(tmp_path):
    import pymupdf  # noqa: F401
    from ru_corpus_kit import store
    cfg, files = make_project(tmp_path, scan=False)
    db = store.open_rw(tmp_path / "t.sqlite")
    pages, n = wide.add_doc_wide(db, "x1", files["wide"])
    assert pages == 1 and n >= 15
    assert db.execute("SELECT count(*) FROM table_cells WHERE method='bbox'").fetchone()[0] == n
    assert db.execute("SELECT count(*) FROM table_cells_bbox").fetchone()[0] == n


def test_levels_need_profile(built, built_profile):
    q = "Ставка на содержание"
    core = tools.table(built["kit"], q, level="СН2")
    assert core["cells"] == []                                   # ядро уровней не знает
    c = tools.table(built["kit"], q)["cells"]
    assert c and all(x["level"] is None for x in c)
    prof = tools.table(built_profile["kit"], q, level="СН2")["cells"]
    assert prof and prof[0]["value"] == "2 345,6" and prof[0]["level"] == "СН2"
    assert prof[0]["unit"].startswith("руб./")
    assert {x["level"] for x in tools.table(built_profile["kit"], q, n=10)["cells"]} == {"ВН", "СН2", "НН"}


def test_profile_synonyms_only_with_profile(built, built_profile):
    assert built["kit"].cfg.synonyms == {} and "нвв" in built_profile["kit"].cfg.synonyms
    plain = norm.fts_query("НВВ", synonyms=built["kit"].cfg.synonyms)
    rich = norm.fts_query("НВВ", synonyms=built_profile["kit"].cfg.synonyms)
    assert "валовый" not in plain and "валовый" in rich


# ---------------------------------------------------------------- aggregate / calc

def test_aggregate_with_total_row(built):
    kit = built["kit"]
    d = doc_id(kit, "reestr_2024")
    r = tools.aggregate(kit, d, "Мощность", page_no="Реестр")
    assert r["ok"] and r["column_stats"]["sum"] == 950.0 and r["column_stats"]["count"] == 5
    assert r["rows_matched"] == 5 and r["source_mode"].startswith("исходный файл")
    assert r["total_row_in_source"]["row"][0] == "Итого"           # «Итого» не суммируется, а сверяется
    assert r["total_matches_sum"] is True
    assert r["file"] == PREFIX + "registers/reestr_2024.xlsx" and r["origin"].endswith("#page=Реестр")


def test_aggregate_where_and_ratio(built):
    kit = built["kit"]
    d = doc_id(kit, "reestr_2024")
    w = tools.aggregate(kit, d, "Мощность", where_expr="Наименование~Подстанция")
    assert w["column_stats"]["sum"] == 350.5 and w["rows_matched"] == 2
    rt = tools.aggregate(kit, d, "Стоимость", column2="Мощность")
    assert rt["ratio_sum"] == 10.0
    assert not tools.aggregate(kit, d, "Несуществующая графа")["ok"]
    assert not tools.aggregate(kit, d, "Наименование")["ok"]        # текстовая графа


def test_aggregate_from_index_text_when_source_missing(built):
    kit = built["kit"]
    d = doc_id(kit, "reestr_2024")
    saved = kit.source_path
    kit.source_path = lambda _d: None                              # исходника нет: читается текст индекса
    try:
        r = tools.aggregate(kit, d, "Мощность", page_no="Реестр")
    finally:
        kit.source_path = saved
    assert r["source_mode"] == "текст индекса" and r["column_stats"]["sum"] == 950.0


def test_calc(built):
    assert tools.calc("1 234,5 + 0,25 - 10")["result"] == "1 224,75"
    assert tools.calc("(2 + 3) * 4", digits=2)["result"] == "20,00"
    assert tools.calc("10 / 4")["result"] == "2,5000"
    assert tools.calc("50%")["result"] == "0,5000"
    with pytest.raises(Exception):
        tools.calc("__import__('os')")
    with pytest.raises(ZeroDivisionError):
        tools.calc("1 / 0")


# ---------------------------------------------------------------- прочие форматы

@pytest.mark.skipif(not HAVE_DOCX, reason="нет python-docx")
def test_docx_indexed(built):
    kit = built["kit"]
    r = tools.search(kit, "договор на поставку трансформаторов")
    assert r["evidence"][0]["file"] == PREFIX + "notes/zapiska.docx"
    assert "Договор № 15" in tools.page(kit, r["evidence"][0]["doc"], "1")["text"]


@pytest.mark.skipif(OCR_WHY is not None, reason=f"OCR недоступен: {OCR_WHY}")
def test_scan_ocr(built):
    kit = built["kit"]
    d = doc_id(kit, "skan_dogovor")
    assert kit.db.execute("SELECT method FROM docs WHERE id=?", (d,)).fetchone()[0] == "tesseract"
    text = tools.page(kit, d, "1")["text"]
    r = tools.search(kit, "договор поставки кабеля")
    assert r["verdict"] == "есть доказательства" and r["evidence"][0]["doc"] == d, \
        f"OCR дал: {text[:300]!r}; поиск: {r['verdict']}, {[e['doc'] for e in r['evidence'][:3]]}"
    assert tools.page(kit, d, "1")["ocr"] is True


@pytest.mark.skipif(OCR_WHY is not None, reason=f"OCR недоступен: {OCR_WHY}")
@pytest.mark.parametrize("rotate", [0, 180])
def test_ocr_orientation(tmp_path, rotate):
    """Нормальная страница не переворачивается, перевёрнутая — возвращается (ошибка OSD на Linux, 21.11)."""
    import synth
    from ru_corpus_kit import extract
    pdf = tmp_path / f"scan_{rotate}.pdf"
    synth.make_scan(pdf, rotate=rotate)
    text = " ".join(extract.ocr_pdf(pdf, workers=1, tmp_dir=tmp_path / "ocr")).lower()
    assert "кабел" in text and "договор" in text, text[:300]


# ---------------------------------------------------------------- инкрементальность

def test_incremental_reindex(tmp_path):
    from conftest import synth
    cfg, files = make_project(tmp_path, scan=False)
    n = len(files)
    first = build(cfg)
    assert first["new"] == n and first["lemma"] == n and first["bm25"] == n

    again = build(cfg)                                   # ничего не менялось: ничего не пересчитывается
    assert (again["new"], again["changed"], again["removed"], again["unchanged"]) == (0, 0, 0, n)
    assert again["lemma"] == 0 and again["tables"] == 0 and again["bm25"] == 0

    synth.make_xlsx(files["xlsx"], scale=2.0)            # изменился один файл
    upd = build(cfg)
    assert (upd["changed"], upd["new"], upd["unchanged"]) == (1, 0, n - 1)
    assert upd["lemma"] == 1 and upd["bm25"] == 1
    kit = Kit(cfg)
    d = doc_id(kit, "reestr_2024")
    assert tools.aggregate(kit, d, "Мощность", page_no="Реестр")["column_stats"]["sum"] == 1900.0
    kit.close()

    files["txt"].unlink()                                # удалён файл
    rem = build(cfg)
    assert rem["removed"] == 1 and rem["docs"] == n - 1
    kit = Kit(cfg)
    assert tools.search(kit, "Памятка необходимая валовая выручка 777")["verdict"] == "в корпусе нет"
    docs_in_bm = {r[0] for r in kit.bm.db.execute("SELECT DISTINCT doc_id FROM chunks")}
    assert docs_in_bm == {r[0] for r in kit.db.execute("SELECT id FROM docs")}     # bm25 без призраков удалённого
    kit.close()

    new = tmp_path / "docs" / "notes" / "novoe.txt"      # добавлен файл и его копия
    new.write_text("Новая заметка про кабельный лоток и монтаж.", encoding="utf-8")
    (tmp_path / "docs" / "notes" / "novoe_copy.txt").write_text(new.read_text(encoding="utf-8"), encoding="utf-8")
    add = build(cfg)
    assert add["new"] == 1 and add["duplicates"] == 1 and add["docs"] == n
    kit = Kit(cfg)
    r = tools.search(kit, "кабельный лоток монтаж")
    assert r["verdict"] == "есть доказательства" and r["evidence"][0]["file"] == PREFIX + "notes/novoe.txt"
    ids = [r["id"] for r in kit.registry().values()]
    assert len(ids) == len(set(ids))                     # id не переиспользуются
    kit.close()


def test_force_rebuild_is_idempotent(tmp_path):
    cfg, files = make_project(tmp_path, scan=False)
    build(cfg)
    kit = Kit(cfg)
    before = tools.search(kit, "выручка от передачи электроэнергии")
    kit.close()
    st = build(cfg, force=True)
    assert st["changed"] == len(files)
    kit = Kit(cfg)
    assert tools.search(kit, "выручка от передачи электроэнергии")["evidence"][0]["doc"] == before["evidence"][0]["doc"]
    kit.close()


def test_foreign_index_is_read_only(tmp_path):
    cfg, _ = make_project(tmp_path, scan=False)
    cfg.kb_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cfg.kb_path)
    db.execute("CREATE TABLE docs (id TEXT)")
    db.commit()
    db.close()
    with pytest.raises(RuntimeError, match="не ru-corpus"):
        build(cfg)


# ---------------------------------------------------------------- CLI и конфиг

def test_cli_init_and_commands(tmp_path, monkeypatch, capsys):
    from conftest import synth
    monkeypatch.chdir(tmp_path)
    synth.make_corpus(tmp_path / "docs", scan=False, docx_ok=False)
    assert cli.main(["init", "--root", "docs", "--prefix", PREFIX]) == 0
    capsys.readouterr()
    assert (tmp_path / "corpus.toml").exists()
    assert cli.main(["init"]) == 1                      # повторный init без --force отказывает
    capsys.readouterr()
    assert cli.main(["index", "--quiet", "--no-ocr"]) == 0
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res["ok"] and res["new"] == 4
    assert cli.main(["status"]) == 0
    assert "документов:  4" in capsys.readouterr().out
    for args in (["search", "выручка от передачи электроэнергии", "--n", "3"],
                 ["calc", "2 + 2"],
                 ["number", "d0001", "1", "1"],
                 ["doc", "--find", "reestr"]):
        code = cli.main(args)
        obj = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert code == 0 and "ok" in obj
    code = cli.main(["page", "d0001", "500"])
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_errors_are_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RU_CORPUS_CONFIG", raising=False)
    assert cli.main(["search", "что угодно"]) == 1
    obj = json.loads(capsys.readouterr().out)
    assert obj["ok"] is False and "corpus.toml" in obj["error"]


def test_console_script_module(tmp_path):
    r = subprocess.run([sys.executable, "-m", "ru_corpus_kit.cli", "calc", "3 + 4"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["result"] == "7"


def test_config_defaults_and_overrides(tmp_path):
    (tmp_path / "docs").mkdir()
    config.write_template(tmp_path / "corpus.toml", "docs", "pre/", "")
    cfg = config.load(tmp_path / "corpus.toml")
    assert cfg.root == (tmp_path / "docs").resolve() and cfg.source_prefix == "pre/"
    assert cfg.index_dir == (tmp_path / ".ru-corpus").resolve() and cfg.kb_path.name == "kb.sqlite"
    assert cfg.profile.name == "" and cfg.synonyms == {}
    syn = tmp_path / "syn.toml"
    syn.write_text('[synonyms]\n"аб" = ["альфа бета"]\n', encoding="utf-8")
    txt = (tmp_path / "corpus.toml").read_text(encoding="utf-8").replace('synonyms = ""', 'synonyms = "syn.toml"')
    (tmp_path / "corpus.toml").write_text(txt, encoding="utf-8")
    assert config.load(tmp_path / "corpus.toml").synonyms == {"аб": ["альфа бета"]}
    with pytest.raises(FileNotFoundError):
        config.load(tmp_path / "nope.toml")
