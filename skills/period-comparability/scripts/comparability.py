#!/usr/bin/env python3
"""Реестр разрывов сопоставимости периодов: check / validate / list. Только стандартная библиотека.

Коды возврата check: 0 — разрывов нет, 2 — есть блокирующий разрыв, 3 — только пересчитываемые единицы.
"""
import argparse
import csv
import re
import sys

COLS = ["показатель", "с_периода", "тип", "что_изменилось", "коэффициент", "источник"]
TYPES = ("методика", "форма", "охват", "единицы")


def year(value):
    m = re.match(r"\s*(\d{4})", str(value))
    if not m:
        raise ValueError(f"не год: {value!r}")
    return int(m.group(1))


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def problems(rows):
    errs = []
    for i, r in enumerate(rows, 2):
        for c in COLS:
            if c not in r:
                errs.append(f"строка {i}: нет колонки {c}")
        if errs:
            return errs
        if not r["показатель"].strip():
            errs.append(f"строка {i}: пустой показатель")
        try:
            year(r["с_периода"])
        except ValueError as e:
            errs.append(f"строка {i}: {e}")
        if r["тип"] not in TYPES:
            errs.append(f"строка {i}: тип ∈ {TYPES}")
        if not r["что_изменилось"].strip():
            errs.append(f"строка {i}: нет описания разрыва")
        if not r["источник"].strip():
            errs.append(f"строка {i}: нет источника (документ и страница)")
        if r["тип"] == "единицы" and r["коэффициент"].strip():
            try:
                float(r["коэффициент"].replace(",", "."))
            except ValueError:
                errs.append(f"строка {i}: коэффициент не число")
        if r["тип"] != "единицы" and r["коэффициент"].strip():
            errs.append(f"строка {i}: коэффициент допустим только для типа «единицы»")
    return errs


def applies(r, metric, lo, hi):
    if r["показатель"].strip() != "*" and metric is not None \
            and r["показатель"].strip().casefold() != metric.strip().casefold():
        return False
    return lo < year(r["с_периода"]) <= hi


def cmd_check(a):
    rows = load(a.breaks)
    errs = problems(rows)
    if errs:
        sys.exit("реестр невалиден:\n - " + "\n - ".join(errs))
    if a.to < a.frm:
        sys.exit("--to меньше --from")
    hit = [r for r in rows if applies(r, a.metric, a.frm, a.to)]
    if not hit:
        print(f"разрывов для «{a.metric}» в интервале {a.frm}–{a.to} нет (реестр не доказывает их отсутствие)")
        return 0
    blocking = False
    for r in hit:
        conv = r["тип"] == "единицы" and r["коэффициент"].strip()
        if conv:
            print(f"пересчитываемый разрыв с {r['с_периода']}: {r['что_изменилось']}; значения до "
                  f"{r['с_периода']} умножить на {r['коэффициент']} [{r['источник']}]")
        else:
            blocking = True
            print(f"РАЗРЫВ с {r['с_периода']} ({r['тип']}): {r['что_изменилось']} [{r['источник']}]")
    return 2 if blocking else 3


def cmd_validate(a):
    errs = problems(load(a.breaks))
    print("OK" if not errs else "НАРУШЕНИЯ:\n - " + "\n - ".join(errs))
    return 1 if errs else 0


def cmd_list(a):
    for r in load(a.breaks):
        if a.metric and r["показатель"].strip() not in ("*", a.metric.strip()):
            continue
        print(f"{r['показатель']}: с {r['с_периода']} [{r['тип']}] {r['что_изменилось']}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("check"); c.add_argument("breaks"); c.add_argument("--metric", required=True)
    c.add_argument("--from", dest="frm", type=int, required=True); c.add_argument("--to", type=int, required=True)
    v = sp.add_parser("validate"); v.add_argument("breaks")
    l = sp.add_parser("list"); l.add_argument("breaks"); l.add_argument("--metric")
    a = p.parse_args()
    sys.exit({"check": cmd_check, "validate": cmd_validate, "list": cmd_list}[a.cmd](a))


if __name__ == "__main__":
    main()
