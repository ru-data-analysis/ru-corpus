# -*- coding: utf-8 -*-
"""Тесты скриптов навыков из skills/ (только стандартная библиотека и pytest).

Данные: синтетические файлы во временном каталоге и открытый демо-реестр demo/corpus/MANIFEST.csv.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SK = ROOT / "skills"
DEMO_MANIFEST = ROOT / "demo" / "corpus" / "MANIFEST.csv"


def run(script, *args, check=None):
    p = subprocess.run([sys.executable, "-I", str(SK / script), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8")
    if check is not None:
        assert p.returncode == check, f"код {p.returncode} вместо {check}:\n{p.stdout}\n{p.stderr}"
    return p


# --------------------------------------------------------------------------- corpus-manifest
MAN = "corpus-manifest/scripts/manifest.py"


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "корпус"
    (root / "а").mkdir(parents=True)
    (root / "а" / "один.txt").write_text("первый документ", encoding="utf-8")
    (root / "а" / "два.txt").write_text("второй документ", encoding="utf-8")
    (root / ".hidden").write_text("скрытый", encoding="utf-8")
    return root


def test_manifest_snapshot_diff_verify(corpus, tmp_path):
    s1, s2 = tmp_path / "s1.json", tmp_path / "s2.json"
    run(MAN, "snapshot", corpus, "--out", s1, check=0)
    snap = json.loads(s1.read_text(encoding="utf-8"))
    assert snap["n_files"] == 2 and [f["path"] for f in snap["files"]] == ["а/два.txt", "а/один.txt"]
    run(MAN, "verify", s1, corpus, check=0)
    assert run(MAN, "hash", s1).stdout.strip() == snap["corpus_hash"]

    (corpus / "а" / "один.txt").write_text("первый документ, правка", encoding="utf-8")
    (corpus / "а" / "два.txt").rename(corpus / "а" / "три.txt")
    (corpus / "новый.txt").write_text("новый", encoding="utf-8")
    run(MAN, "verify", s1, corpus, check=1)
    run(MAN, "snapshot", corpus, "--out", s2, check=0)
    d = json.loads(run(MAN, "diff", s1, s2, "--json", check=1).stdout)
    assert d["changed"] == ["а/один.txt"]
    assert d["added"] == ["новый.txt"]
    assert d["renamed"] == [{"from": "а/два.txt", "to": "а/три.txt"}]
    assert d["removed"] == []
    run(MAN, "diff", s1, s1, check=0)


def test_manifest_refuses_output_inside_corpus(corpus):
    p = run(MAN, "snapshot", corpus, "--out", corpus / "снимок.json")
    assert p.returncode != 0 and "только читается" in (p.stdout + p.stderr)


def test_manifest_hand_edit_detected(corpus, tmp_path):
    s = tmp_path / "s.json"
    run(MAN, "snapshot", corpus, "--out", s, check=0)
    data = json.loads(s.read_text(encoding="utf-8"))
    data["files"][0]["sha256"] = "0" * 64
    s.write_text(json.dumps(data), encoding="utf-8")
    p = run(MAN, "hash", s)
    assert p.returncode != 0 and "правили вручную" in (p.stdout + p.stderr)


def test_manifest_from_demo_csv(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    run(MAN, "from-csv", DEMO_MANIFEST, "--out", a, check=0)
    run(MAN, "from-csv", DEMO_MANIFEST, "--out", b, check=0)
    assert json.loads(a.read_text(encoding="utf-8"))["n_files"] == 15
    run(MAN, "diff", a, b, check=0)
    c = tmp_path / "c.json"
    run(MAN, "from-csv", DEMO_MANIFEST, "--hash-col", "sha256_без_дат_pdf", "--out", c, check=0)
    run(MAN, "diff", a, c, check=1)


def test_manifest_from_csv_rejects_bad_columns(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("rel_path,sha256\nа.pdf,\n", encoding="utf-8")
    p = run(MAN, "from-csv", f, "--out", tmp_path / "o.json")
    assert p.returncode != 0 and "пустой хэш" in (p.stdout + p.stderr)
    p = run(MAN, "from-csv", f, "--hash-col", "нет_такой", "--out", tmp_path / "o.json")
    assert p.returncode != 0 and "нет колонки" in (p.stdout + p.stderr)


# --------------------------------------------------------------------------- period-comparability
CMP = "period-comparability/scripts/comparability.py"
TEMPLATE = SK / "period-comparability" / "references" / "breaks-template.csv"


def test_comparability_template_is_valid():
    run(CMP, "validate", TEMPLATE, check=0)


def test_comparability_codes():
    run(CMP, "check", TEMPLATE, "--metric", "Показатель А (синтетика)", "--from", 2022, "--to", 2025, check=2)
    run(CMP, "check", TEMPLATE, "--metric", "Показатель А (синтетика)", "--from", 2023, "--to", 2025, check=0)
    p = run(CMP, "check", TEMPLATE, "--metric", "показатель б (синтетика)", "--from", 2022, "--to", 2025, check=3)
    assert "0.001" in p.stdout
    run(CMP, "check", TEMPLATE, "--metric", "Другой", "--from", 2022, "--to", 2025, check=0)


def test_comparability_requires_source(tmp_path):
    f = tmp_path / "b.csv"
    f.write_text("показатель,с_периода,тип,что_изменилось,коэффициент,источник\nX,2023,форма,было → стало,,\n",
                 encoding="utf-8")
    p = run(CMP, "validate", f, check=1)
    assert "нет источника" in p.stdout


# --------------------------------------------------------------------------- source-classes
SRC = "source-classes/scripts/source_class.py"


def classify(tmp_path, *extra):
    out = tmp_path / "classes.csv"
    run(SRC, "classify", DEMO_MANIFEST, "--out", out, *extra, check=0)
    import csv
    with open(out, encoding="utf-8", newline="") as f:
        return out, {r["path"]: r for r in csv.DictReader(f)}


def test_source_classify_demo(tmp_path):
    _, rows = classify(tmp_path)
    pp381 = rows["gov/2014-04-28_pravitelstvo_pp-381_standarty-raskrytiya.pdf"]
    assert (pp381["origin_class"], pp381["quality"]) == ("A", "T")
    scan = rows["minenergo/2019-07-22_minenergo_prikaz-745_norma-poter-tes.pdf"]
    assert (scan["origin_class"], scan["quality"]) == ("A", "O")
    noisy = rows["regions/ivanovo/2024-11-08_det-ivanovo_post-41-e1_tarify-naselenie.pdf"]
    assert (noisy["origin_class"], noisy["quality"]) == ("?", "N")  # хост не в списках: решает человек


def test_source_overrides_need_reason(tmp_path):
    ov = tmp_path / "ov.csv"
    ov.write_text("path,class,reason\nregions/ivanovo/2024-11-08_det-ivanovo_post-41-e1_tarify-naselenie.pdf,A,\n",
                  encoding="utf-8")
    p = run(SRC, "classify", DEMO_MANIFEST, "--out", tmp_path / "c.csv", "--overrides", ov)
    assert p.returncode != 0 and "причина" in (p.stdout + p.stderr)
    ov.write_text("path,class,reason\nregions/ivanovo/2024-11-08_det-ivanovo_post-41-e1_tarify-naselenie.pdf,A,"
                  "официальный сайт департамента\n", encoding="utf-8")
    _, rows = classify(tmp_path, "--overrides", ov)
    assert rows["regions/ivanovo/2024-11-08_det-ivanovo_post-41-e1_tarify-naselenie.pdf"]["origin_class"] == "A"


def test_source_classify_crawler_registry_with_root(tmp_path):
    """Реестр краулера: колонка file, BOM, пути отстали от диска, есть строка без файла."""
    root = tmp_path / "корпус"
    (root / "files").mkdir(parents=True)
    (root / "other").mkdir()
    for p in ("files/один.pdf", "files/два.xlsx", "files/скан.png", "files/дубль.doc", "other/дубль.doc"):
        (root / p).write_text("x", encoding="utf-8")
    reg = tmp_path / "manifest.csv"
    reg.write_text("\ufeffn,url,file,ok\n"
                   "1,https://docs.example.test/a,site/один.pdf,true\n"
                   "2,https://docs.example.test/b,site/два.xlsx,true\n"
                   "3,https://docs.example.test/c,site/скан.png,true\n"
                   "4,https://docs.example.test/d,site/дубль.doc,true\n"
                   "5,https://docs.example.test/e,site/нет.pdf,true\n"
                   "6,https://docs.example.test/f,,false\n", encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"origin": {"A": ["example.test"]}}), encoding="utf-8")
    out = tmp_path / "c.csv"
    p = run(SRC, "classify", reg, "--out", out, "--rules", rules, "--root", root, check=0)
    assert "строк без файла 1" in p.stdout
    import csv
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = {r["registry_path"]: r for r in csv.DictReader(f)}
    assert len(rows) == 5
    assert rows["site/один.pdf"]["path"] == "files/один.pdf" and rows["site/один.pdf"]["resolved"] == "basename"
    assert rows["site/один.pdf"]["origin_class"] == "A" and rows["site/один.pdf"]["quality"] == "?"  # PDF: слой неизвестен
    assert rows["site/два.xlsx"]["quality"] == "T" and rows["site/скан.png"]["quality"] == "O"
    assert rows["site/дубль.doc"]["resolved"] == "ambiguous" and rows["site/дубль.doc"]["path"] == "site/дубль.doc"
    assert rows["site/нет.pdf"]["resolved"] == "missing"


def make_registry(tmp_path, insights):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"version": 1, "insights": insights}, ensure_ascii=False), encoding="utf-8")
    return reg


def insight(i, certainty, evidence):
    return {"id": i, "topic": "т", "question": "в", "narrative": "н", "answer": "о", "certainty": certainty,
            "importance": 3, "source_id": "h/s", "evidence": evidence}


def test_source_gate(tmp_path):
    classes, _ = classify(tmp_path)
    good = [{"path": "gov/2014-04-28_pravitelstvo_pp-381_standarty-raskrytiya.pdf", "locator": "стр. 1"}]
    scan = [{"path": "minenergo/2019-07-22_minenergo_prikaz-745_norma-poter-tes.pdf", "locator": "стр. 1"}]
    noisy = [{"path": "regions/ivanovo/2024-11-08_det-ivanovo_post-41-e1_tarify-naselenie.pdf", "locator": "стр. 2"}]
    run(SRC, "gate", make_registry(tmp_path, [insight("i1", "definite", good)]), classes, check=0)
    p = run(SRC, "gate", make_registry(tmp_path, [insight("i2", "definite", scan)]), classes, check=1)
    assert "качество O" in p.stdout
    run(SRC, "gate", make_registry(tmp_path, [insight("i2", "definite", scan)]), classes, "--allow-ocr", check=0)
    run(SRC, "gate", make_registry(tmp_path, [insight("i3", "definite", noisy)]), classes, check=1)
    run(SRC, "gate", make_registry(tmp_path, [insight("i4", "definite", [])]), classes, check=1)
    p = run(SRC, "gate", make_registry(tmp_path, [insight("i5", "tentative", noisy)]), classes, check=0)
    assert "предупреждение" in p.stdout


# --------------------------------------------------------------------------- analysis-spec-first + insight-registry
CHECK = "analysis-spec-first/scripts/check_run_report.py"
REG = "insight-registry/scripts/registry.py"
RECHECK = "insight-registry/scripts/recheck.py"

REPORT = """# Отчёт (синтетика)

## 0. Привязка

| Поле | Значение |
|---|---|
| Гипотеза | `h-test` |
| Спека | `s-001` v1, хэш `sha256 3f2a9c1d77aa` |
| Хэш корпуса | `corpus_hash 9a8b7c6d5e4f3a2b1c0d` |
| Сопоставимость периодов | не нужна (один период) |

## 1. Что запущено

- Команда: `синтетика`

## 2. Результаты

| выборка | метрика |
|---|---|
| A | 12,4 |

## 3. Проверка правила решения

- Правило из спеки: supported, если рост не менее 10 %; refuted, если меньше 0; иначе open
- Факт: рост 12,4 % (порог 10 %)
- Правило даёт: **supported**

## 4. Чего этот прогон не доказывает

- Один период вместо ряда
- Смена методики между годами не учтена

## 5. Вывод

### 5.1 Вердикт

`h-test` → рост выше порога **supported**

### 5.2 Заявка в реестр

```json
[
  {"question": "Вырос ли показатель за период?",
   "narrative": "Да, примерно на двенадцать процентов, по одному периоду.",
   "answer": "рост 12,4 % (синтетика)",
   "certainty": "tentative", "importance": 4,
   "evidence": [{"path": "а/один.txt", "locator": "стр. 1", "sha256": "SHA_ONE"}]}
]
```
"""


def write_report(tmp_path, sha):
    f = tmp_path / "r.run.md"
    f.write_text(REPORT.replace("SHA_ONE", sha), encoding="utf-8")
    return f


def test_report_gates(tmp_path):
    f = write_report(tmp_path, "a" * 64)
    run(CHECK, f, check=0)
    t = f.read_text(encoding="utf-8")
    bad = tmp_path / "bad1.run.md"
    bad.write_text(t.replace("`h-test` → рост выше порога **supported**", "`h-test` → рост выше порога **open**"),
                   encoding="utf-8")
    assert "не совпадает" in run(CHECK, bad, check=1).stdout
    bad.write_text(t.replace("| Хэш корпуса | `corpus_hash 9a8b7c6d5e4f3a2b1c0d` |\n", ""), encoding="utf-8")
    assert "Хэш корпуса" in run(CHECK, bad, check=1).stdout
    bad.write_text(t.replace("| Сопоставимость периодов | не нужна (один период) |\n", ""), encoding="utf-8")
    assert "Сопоставимость" in run(CHECK, bad, check=1).stdout
    bad.write_text(t.replace("- Смена методики между годами не учтена\n", ""), encoding="utf-8")
    assert "минимум два пункта" in run(CHECK, bad, check=1).stdout


def test_registry_ingest_idempotent_recheck_render(corpus, tmp_path):
    snap = tmp_path / "s.json"
    run(MAN, "snapshot", corpus, "--out", snap, check=0)
    sha = {f["path"]: f["sha256"] for f in json.loads(snap.read_text(encoding="utf-8"))["files"]}["а/один.txt"]
    report, reg = write_report(tmp_path, sha), tmp_path / "reg.json"
    run(REG, "ingest", reg, report, "--topic", "тема", "--dry-run", check=0)
    assert not reg.exists()
    run(REG, "ingest", reg, report, "--topic", "тема", check=0)
    first = reg.read_text(encoding="utf-8")
    run(REG, "ingest", reg, report, "--topic", "тема", check=0)
    assert reg.read_text(encoding="utf-8") == first
    run(REG, "validate", reg, check=0)
    run(RECHECK, reg, snap, check=0)

    (corpus / "а" / "один.txt").write_text("документ изменён", encoding="utf-8")
    snap2 = tmp_path / "s2.json"
    run(MAN, "snapshot", corpus, "--out", snap2, check=0)
    p = run(RECHECK, reg, snap2, check=1)
    assert "документ изменён" in p.stdout
    assert "status" not in json.loads(reg.read_text(encoding="utf-8"))["insights"][0]
    run(RECHECK, reg, snap2, "--write", check=1)
    ins = json.loads(reg.read_text(encoding="utf-8"))["insights"][0]
    assert ins["status"] == "needs_recheck"
    out = tmp_path / "KNOWLEDGE.md"
    run(REG, "render", reg, out, check=0)
    assert "перепроверить" in out.read_text(encoding="utf-8")
    # повторный ingest того же отчёта снимает отметку
    run(REG, "ingest", reg, report, "--topic", "тема", check=0)
    assert "status" not in json.loads(reg.read_text(encoding="utf-8"))["insights"][0]


def test_registry_topic_limit(tmp_path):
    reg = tmp_path / "reg.json"
    for n in range(1, 4):
        f = tmp_path / f"r{n}.run.md"
        f.write_text(REPORT.replace("h-test", f"h-t{n}").replace("SHA_ONE", "b" * 64), encoding="utf-8")
        run(REG, "ingest", reg, f, "--topic", "тема", check=0)
    f = tmp_path / "r4.run.md"
    f.write_text(REPORT.replace("h-test", "h-t4").replace("SHA_ONE", "b" * 64), encoding="utf-8")
    p = run(REG, "ingest", reg, f, "--topic", "тема")
    assert p.returncode != 0 and "превысит лимит" in (p.stdout + p.stderr)
    assert len(json.loads(reg.read_text(encoding="utf-8"))["insights"]) == 3  # реестр не тронут


# --------------------------------------------------------------------------- leak-check
LEAK = "leak-check/scripts/leak_check.py"


def test_leak_check(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    (d / "чисто.md").write_text("Обычный текст отчёта без закрытых сведений.\n", encoding="utf-8")
    run(LEAK, d, check=0)

    (d / "гриф.md").write_text("Документ с грифом: Конфиденциально, не копировать.\n", encoding="utf-8")
    p = run(LEAK, d, check=1)
    assert "гриф" in p.stdout and "Конфиденциально" not in p.stdout  # фрагмент не печатается
    (d / "гриф.md").unlink()

    (d / "путь.md").write_text("лежит в /home/ivan/work/файл\n", encoding="utf-8")
    run(LEAK, d, check=1)
    (d / "путь.md").unlink()

    pat = tmp_path / "pat.txt"
    pat.write_text("# комментарий\nзакрытая организация\tЗакрытАя-Орг\n", encoding="utf-8")
    (d / "имя.md").write_text("Данные ЗАКРЫТАЯ-ОРГ за 2024 год\n", encoding="utf-8")
    assert "закрытая организация" in run(LEAK, d, "--patterns", pat, check=1).stdout
    (d / "имя.md").unlink()

    closed = tmp_path / "closed.txt"
    closed.write_text("закрытый-акт-0042\n", encoding="utf-8")
    (d / "док.md").write_text("см. закрытый-акт-0042.pdf, стр. 3\n", encoding="utf-8")
    assert "закрытого документа" in run(LEAK, d, "--closed", closed, check=1).stdout
    (d / "док.md").unlink()

    long_text = " ".join(["слово"] * 60)
    (d / "находки.json").write_text(json.dumps({"findings": [{"quotes": [{"text": long_text}]}]}, ensure_ascii=False),
                                   encoding="utf-8")
    assert "цитата длиной 60" in run(LEAK, d, check=1).stdout
    run(LEAK, d, "--max-quote-words", 100, check=0)


# --------------------------------------------------------------------------- cost-log
COST = "cost-log/scripts/cost_log.py"


def test_cost_log(tmp_path):
    log = tmp_path / "runs" / "cost.csv"
    p = run(COST, "run", "--log", log, "--label", "проба", "--docs", 10, "--pages", 50, "--model", "локальная",
            "--", sys.executable, "-c", "print('привет')", check=0)
    assert "привет" in p.stdout
    run(COST, "run", "--log", log, "--label", "проба", "--", sys.executable, "-c", "raise SystemExit(3)", check=3)
    s = run(COST, "summary", log, check=0).stdout
    assert "запусков 2 (с ошибкой 1)" in s and "с/документ" in s
    line = run(COST, "line", log, "--label", "проба", check=0).stdout
    assert line.startswith("cost: wall_s=")
    assert run(COST, "line", log, "--label", "нет").returncode != 0


# --------------------------------------------------------------------------- corpus-cluster-orchestrator
PART = "corpus-cluster-orchestrator/scripts/partition.py"
VERIFY = "corpus-cluster-orchestrator/scripts/verify_quotes.py"


def test_partition_and_verify_quotes(tmp_path):
    texts = tmp_path / "texts"
    texts.mkdir()
    rows = ["doc_id,title,path,sha256"]
    for i in range(1, 11):
        (texts / f"d{i}.txt").write_text(f"Акт {i}: порядок присоединения определён в пункте {i}.\n", encoding="utf-8")
        rows.append(f"d{i},Акт {i},{texts / f'd{i}.txt'},")
    docs = tmp_path / "docs.csv"
    docs.write_text("\n".join(rows) + "\n", encoding="utf-8")

    run(PART, docs, "Как определён порядок присоединения?", "--run-id", "t1", "--out", tmp_path / "cl", check=0)
    run(PART, docs, "  как   определён порядок присоединения? ", "--run-id", "t2", "--out", tmp_path / "cl", check=0)
    m1 = json.loads((tmp_path / "cl" / "t1" / "manifest.json").read_text(encoding="utf-8"))
    m2 = json.loads((tmp_path / "cl" / "t2" / "manifest.json").read_text(encoding="utf-8"))
    assert m1["assignment"] == m2["assignment"]
    assigned = [d for v in m1["assignment"].values() for d in v]
    assert sorted(assigned) == sorted(f"d{i}" for i in range(1, 11)) and len(set(assigned)) == 10

    doc = m1["assignment"]["w01"][0]
    wf = tmp_path / "cl" / "t1" / "workers" / "w01_findings.json"
    wf.write_text(json.dumps({"worker_id": "w01", "findings": [{"doc_id": doc, "answer": "x", "quotes": [
        {"text": "порядок  присоединения определён в пункте", "locator": "п. 1", "proves": "x"}]}]},
        ensure_ascii=False), encoding="utf-8")
    run(VERIFY, tmp_path / "cl" / "t1", check=0)
    wf.write_text(json.dumps({"worker_id": "w01", "findings": [{"doc_id": doc, "answer": "x", "quotes": [
        {"text": "выдуманная фраза", "locator": "п. 2", "proves": "x"}]}]}, ensure_ascii=False), encoding="utf-8")
    assert "цитата не найдена" in run(VERIFY, tmp_path / "cl" / "t1", check=1).stdout


# --------------------------------------------------------------------------- признак текстового слоя PDF
def make_pdf(path, pages, compress=False, encrypt=False):
    """pages: список 'text' | 'scan' | 'ocr'. Минимальный PDF без таблицы xref: эвристика её не читает."""
    import zlib
    out = [b"%PDF-1.4\n"]
    for i, kind in enumerate(pages, 1):
        out.append(b"%d 0 obj\n<< /Type /Page /Parent 99 0 R >>\nendobj\n" % i)
        if kind == "scan":
            out.append(b"/Subtype /Image\n")
        body = {"text": b"BT /F1 12 Tf (Tekst) Tj ET", "scan": b"q 100 0 0 100 0 0 cm /Im0 Do Q",
                "ocr": b"BT 3 Tr /F1 12 Tf (Tekst) Tj ET"}[kind]
        if kind == "ocr":
            out.append(b"/Subtype /Image\n")
        if compress:
            body = zlib.compress(body)
        out.append(b"stream\n" + body + b"\nendstream\n")
    out.append(b"trailer << /Encrypt 1 0 R >>\n" if encrypt else b"trailer << >>\n")
    with open(path, "wb") as f:
        f.write(b"".join(out))


def textlayer(tmp_path, files):
    root = tmp_path / "pdfs"
    root.mkdir()
    for name, (pages, kw) in files.items():
        make_pdf(root / name, pages, **kw)
    out = tmp_path / "tl.csv"
    run(SRC, "textlayer", root, "--out", out, "--engine", "heuristic", check=0)
    import csv as _csv
    with open(out, encoding="utf-8", newline="") as f:
        return root, out, {r["path"]: r for r in _csv.DictReader(f)}


def test_textlayer_detects_kinds(tmp_path):
    _, _, tl = textlayer(tmp_path, {
        "text.pdf": (["text", "text"], {}),
        "zip.pdf": (["text", "text"], {"compress": True}),
        "scan.pdf": (["scan", "scan"], {}),
        "mixed.pdf": (["text", "scan"], {}),
        "ocr.pdf": (["ocr", "ocr"], {}),
        "enc.pdf": (["text"], {"encrypt": True}),
    })
    assert {k: v["text_layer"] for k, v in tl.items()} == {
        "text.pdf": "yes", "zip.pdf": "yes", "scan.pdf": "no", "mixed.pdf": "partial",
        "ocr.pdf": "ocr_layer", "enc.pdf": "unknown"}


def test_classify_uses_textlayer_and_gate_modes(tmp_path):
    root, tl_csv, _ = textlayer(tmp_path, {"t.pdf": (["text"], {}), "s.pdf": (["scan"], {}),
                                          "m.pdf": (["text", "scan"], {}), "u.pdf": (["text"], {"encrypt": True})})
    reg = tmp_path / "reg.csv"
    reg.write_text("файл,url_источника\n" + "".join(f"{n},https://government.ru/x\n" for n in
                   ("t.pdf", "s.pdf", "m.pdf", "u.pdf")), encoding="utf-8")
    classes = tmp_path / "cl.csv"
    run(SRC, "classify", reg, "--out", classes, "--root", root, "--textlayer", tl_csv, check=0)
    import csv as _csv
    with open(classes, encoding="utf-8", newline="") as f:
        q = {r["path"]: r["quality"] for r in _csv.DictReader(f)}
    assert q == {"t.pdf": "T", "s.pdf": "X", "m.pdf": "P", "u.pdf": "?"}

    def gate(name, *args, locator="стр. 1"):
        ev = [{"path": name, "locator": locator}]
        return run(SRC, "gate", make_registry(tmp_path, [insight("i", "definite", ev)]), classes, *args, check=None)
    assert gate("t.pdf").returncode == 0
    p = gate("s.pdf", "--allow-ocr")
    assert p.returncode == 1 and "сначала распознайте" in p.stdout          # скан не пускается никогда
    assert gate("m.pdf").returncode == 1
    assert gate("m.pdf", "--allow-ocr").returncode == 0
    assert gate("m.pdf", "--allow-ocr", locator="").returncode == 1          # без страницы нельзя
    assert gate("u.pdf", "--allow-ocr").returncode == 1
    p = gate("u.pdf", "--allow-unknown-quality")
    assert p.returncode == 0 and "предупреждение" in p.stdout


def test_textlayer_goes_stale_when_file_changes(tmp_path):
    root, tl_csv, _ = textlayer(tmp_path, {"t.pdf": (["text"], {})})
    make_pdf(root / "t.pdf", ["scan"])  # файл подменили, признак старый
    reg = tmp_path / "reg.csv"
    reg.write_text("файл,url_источника\nt.pdf,https://government.ru/x\n", encoding="utf-8")
    classes = tmp_path / "cl.csv"
    run(SRC, "classify", reg, "--out", classes, "--root", root, "--textlayer", tl_csv, check=0)
    assert ",?," in classes.read_text(encoding="utf-8") and "устарел" in classes.read_text(encoding="utf-8")


def test_textlayer_engine_pdftotext_required(tmp_path):
    import shutil
    if shutil.which("pdftotext"):
        return
    root = tmp_path / "p"; root.mkdir(); make_pdf(root / "a.pdf", ["text"])
    assert run(SRC, "textlayer", root, "--out", tmp_path / "o.csv", "--engine", "pdftotext", check=1)
    run(SRC, "textlayer", root, "--out", tmp_path / "o.csv", "--engine", "auto", check=0)
