#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Автопроверка контрольных вопросов демо-корпуса инструментами ru-corpus.

По каждому вопросу из demo/questions/questions.json:
  1. `ru-corpus search "<вопрос>"` — документ из doc_hint должен быть в первой пятёрке выдачи
     (для ловушки — вердикт «в корпусе нет»);
  2. `ru-corpus number <док> <страница> "<значение>"` — каждое значение стоит дословно на странице (found: true);
  3. по виду вопроса: wide_table — `ru-corpus table` возвращает ячейку с ожидаемым значением;
     calc — значения по годам берутся через `ru-corpus table`, сумма считается `ru-corpus calc`
     и совпадает с итогом таблицы.
Отчёт пишется в demo/questions/CHECK.md. Код возврата 0 — все вопросы прошли.

    cd demo && ru-corpus index && python3 check_questions.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
QUESTIONS = DEMO / "questions" / "questions.json"
REPORT = DEMO / "questions" / "CHECK.md"
TOP_N = 5


def run(args: list[str]) -> tuple[dict, str]:
    cmd = ["ru-corpus", *args]
    r = subprocess.run(cmd, cwd=DEMO, capture_output=True, text=True)
    line = " ".join(["ru-corpus"] + [a if " " not in a and a else f'"{a}"' for a in args])
    try:
        return json.loads(r.stdout), line
    except json.JSONDecodeError:
        return {"ok": False, "error": (r.stdout + r.stderr)[:300]}, line


def norm(v: str) -> str:
    return v.replace(",", ".").replace(" ", " ").strip()


def resolve_doc(hint: str) -> tuple[str | None, str]:
    stem = hint.rsplit(".", 1)[0]
    res, cmd = run(["doc", "--find", stem])
    for d in res.get("docs", []):
        if d["file"].endswith("/" + hint) or d["file"].endswith(hint):
            return d["doc"], cmd
    return None, cmd


def check(q: dict) -> dict:
    steps, ok = [], True

    def step(cmd: str, passed: bool, detail: str):
        nonlocal ok
        ok = ok and passed
        steps.append({"cmd": cmd, "passed": passed, "detail": detail})

    res, cmd = run(["search", q["q"], "--n", str(TOP_N)])
    if q["kind"] == "trap":
        passed = res.get("verdict") == q["expect"]
        step(cmd, passed, f"вердикт: «{res.get('verdict')}» (ожидалось «{q['expect']}»)")
        if q.get("alt_q"):                      # справочно: другая формулировка той же ловушки
            r2, c2 = run(["search", q["alt_q"], "--n", str(TOP_N)])
            top2 = ", ".join(f"{e.get('doc')} стр. {e.get('page')}" for e in r2.get("evidence", [])[:3]) or "—"
            steps.append({"cmd": c2, "passed": True, "info": True,
                          "detail": f"СПРАВОЧНО (в зачёт не идёт): вердикт «{r2.get('verdict')}», выдача: {top2}. {q.get('note', '')}"})
        return {"id": q["id"], "kind": q["kind"], "ok": ok, "page": "—", "doc": "—", "steps": steps}

    doc_id, dcmd = resolve_doc(q["doc_hint"])
    step(dcmd, doc_id is not None, f"документ: {doc_id}")
    top = [(e.get("doc"), e.get("page")) for e in res.get("evidence", [])[:TOP_N]]
    pos = next((i + 1 for i, (d, _) in enumerate(top) if d == doc_id), None)
    pages = [p for d, p in top if d == doc_id]
    step(cmd, pos is not None,
         f"вердикт «{res.get('verdict')}»; {q['doc_hint']} на месте {pos or 'нет в первой пятёрке'}; страницы выдачи этого документа: {', '.join(pages) or '—'}")
    if not doc_id:
        return {"id": q["id"], "kind": q["kind"], "ok": False, "page": q["page"], "doc": q["doc_hint"], "steps": steps}

    for v in q["values"]:
        r, cmd = run(["number", doc_id, str(q["page"]), v])
        step(cmd, r.get("found") is True, f"found={r.get('found')}; контекст: {(r.get('context') or '')[:110]}")

    if q["kind"] == "wide_table":
        t = q["table"]
        r, cmd = run(["table", "--q", t["q"], "--doc", doc_id, "--page", str(q["page"]), "--n", "60"])
        cells = r.get("cells", [])
        hit = [c for c in cells if norm(c["value"]) == norm(t["expect"])]
        step(cmd, bool(hit), f"ячеек: {len(cells)}; значение {t['expect']}: "
             + (f"{hit[0]['method']}, {hit[0]['anchor'][-170:]}" if hit else "не найдено"))
    if q["kind"] == "calc":
        c = q["calc"]
        vals = []
        for y in c["years"]:
            r, cmd = run(["table", "--q", c["table_q"], "--year", str(y), "--doc", doc_id, "--page", str(q["page"]), "--n", "20"])
            cand = [x for x in r.get("cells", []) if x["label"].startswith(c["label_prefix"]) and c["column_contains"] in x["anchor"]]
            step(cmd, len(cand) >= 1, f"{y}: {cand[0]['value'] if cand else 'нет ячейки'} ({cand[0]['unit'] if cand else ''})")
            if cand:
                vals.append(norm(cand[0]["value"]))
        expr = "+".join(vals)
        r, cmd = run(["calc", expr])
        step(cmd, norm(r.get("result", "")) == norm(c["expect_sum"]), f"{expr} = {r.get('result')} (итог таблицы {c['expect_sum']})")
    return {"id": q["id"], "kind": q["kind"], "ok": ok, "page": q["page"], "doc": q["doc_hint"], "steps": steps}


def main() -> int:
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    results = [check(q) for q in questions]
    n_ok = sum(r["ok"] for r in results)
    md = ["# Проверка контрольных вопросов демо-корпуса", "",
          "Сформировано `demo/check_questions.py` (инструменты `ru-corpus`: search, number, table, calc). "
          "Индекс: `cd demo && ru-corpus index`.", "",
          f"Итог: **{n_ok} из {len(results)}** вопросов прошли проверку.", "",
          "| вопрос | вид | документ | страница | результат |", "|---|---|---|---|---|"]
    for q, r in zip(questions, results):
        md.append(f"| {q['id']} | {r['kind']} | {r['doc']} | {r['page']} | {'найдено' if r['ok'] else 'НЕ ПРОШЁЛ'} |")
    md.append("")
    for q, r in zip(questions, results):
        md += [f"## {q['id']} ({q['kind']})", "", f"Вопрос: {q['q']}", ""]
        if q["values"]:
            md += ["Значения: " + "; ".join(f"`{v}`" for v in q["values"]), ""]
        for s in r["steps"]:
            tag = "ИНФО" if s.get("info") else ("OK" if s["passed"] else "СБОЙ")
            md += [f"- {tag} `{s['cmd'][:240]}`", f"  - {s['detail']}"]
        md.append("")
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"{n_ok}/{len(results)} вопросов прошли; отчёт: {REPORT}")
    for q, r in zip(questions, results):
        print(f"  {q['id']} {'OK ' if r['ok'] else 'FAIL'} {r['kind']}")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
