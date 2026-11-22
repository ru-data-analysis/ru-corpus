#!/usr/bin/env python3
"""Классы источников: classify / summary / gate. Только стандартная библиотека."""
import argparse
import csv
import json
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES = os.path.join(HERE, "..", "references", "classes.default.json")
PATH_COLS = ("файл", "rel_path", "path", "file")
URL_COLS = ("url_источника", "url")
TEXT_COLS = ("текстовый_слой", "text_layer")
OUT_COLS = ["path", "origin_class", "quality", "host", "reason", "registry_path", "resolved"]
EXT_TEXT = {".html", ".htm", ".xls", ".xlsx", ".docx", ".doc", ".rtf", ".txt", ".csv", ".json", ".xml"}
EXT_SCAN = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif"}


def pick(row, cols):
    for c in cols:
        if c in row:
            return row[c]
    return ""


def host_class(host, rules):
    host = host.lower()
    for cls in ("A", "B", "C"):
        for suffix in rules["origin"].get(cls, []):
            if host == suffix or host.endswith("." + suffix):
                return cls, f"хост {host} входит в список {cls} ({suffix})"
    return "?", f"хост «{host or 'нет url'}» не входит ни в один список"


def quality_of(text, path=""):
    """Качество по колонке текстового слоя; если колонки нет, по расширению. PDF и архивы остаются «?»:
    наличие текстового слоя у PDF по расширению не узнать."""
    t = (text or "").strip().lower()
    if not t:
        ext = os.path.splitext(path)[1].lower()
        return "T" if ext in EXT_TEXT else "O" if ext in EXT_SCAN else "?"
    if t.startswith("нет"):
        return "O"
    if t.startswith("да"):
        return "N" if "шумн" in t else "T"
    return "?"


def load_rules(path):
    with open(path or DEFAULT_RULES, encoding="utf-8") as f:
        return json.load(f)


def load_overrides(path):
    out = {}
    if not path:
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f), 2):
            if r.get("class") not in ("A", "B", "C", "?") or not r.get("path"):
                sys.exit(f"{path}: строка {i}: нужны path и class ∈ A,B,C,?")
            if not (r.get("reason") or "").strip():
                sys.exit(f"{path}: строка {i}: причина решения обязательна")
            out[r["path"]] = (r["class"], f"вручную: {r['reason'].strip()}")
    return out


def cmd_classify(a):
    rules, over = load_rules(a.rules), load_overrides(a.overrides)
    with open(a.registry, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("пустой реестр")
    if not any(c in rows[0] for c in PATH_COLS):
        sys.exit(f"нет колонки пути ({', '.join(PATH_COLS)})")
    index = None
    if a.root:  # реестры отстают от диска: сопоставляем путь из реестра с файлом по имени
        index = {}
        for d, dirs, files in os.walk(a.root):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            for fn in files:
                if not fn.startswith("."):
                    rel = os.path.relpath(os.path.join(d, fn), a.root).replace(os.sep, "/")
                    index.setdefault(fn, []).append(rel)
    out, skipped = [], 0
    for r in rows:
        reg_path = pick(r, PATH_COLS).strip().replace("\\", "/")
        if not reg_path:
            skipped += 1  # загрузка не удалась: файла нет
            continue
        path, resolved = reg_path, ""
        if index is not None:
            if os.path.isfile(os.path.join(a.root, reg_path)):
                resolved = "exact"
            else:
                hits = index.get(os.path.basename(reg_path), [])
                if len(hits) == 1:
                    path, resolved = hits[0], "basename"
                else:
                    resolved = "ambiguous" if hits else "missing"
        host = urlparse(pick(r, URL_COLS)).hostname or ""
        cls, why = over.get(reg_path) or over.get(path) or host_class(host, rules)
        out.append({"path": path, "origin_class": cls, "quality": quality_of(pick(r, TEXT_COLS), path),
                    "host": host, "reason": why, "registry_path": reg_path, "resolved": resolved})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(out)
    unknown = sum(1 for o in out if o["origin_class"] == "?")
    msg = f"{a.out}: документов {len(out)}, не определено {unknown}, строк без файла {skipped}"
    if index is not None:
        counts = {k: sum(1 for o in out if o["resolved"] == k) for k in ("exact", "basename", "ambiguous", "missing")}
        msg += f"; сопоставление с диском: {counts}"
    print(msg)


def read_classes(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["path"]: r for r in csv.DictReader(f)}


def cmd_summary(a):
    table = {}
    for r in read_classes(a.classes).values():
        key = (r["origin_class"], r["quality"])
        table[key] = table.get(key, 0) + 1
    for (o, q), n in sorted(table.items()):
        print(f"происхождение {o}, качество {q}: {n}")


def cmd_gate(a):
    classes = read_classes(a.classes)
    allowed_origin = {"A"} | set(a.allow_class or [])
    allowed_quality = {"T"} | ({"O"} if a.allow_ocr else set())
    with open(a.registry, encoding="utf-8") as f:
        insights = json.load(f).get("insights", [])
    bad, warn = [], []
    for it in insights:
        ev = it.get("evidence") or []
        definite = it.get("certainty") == "definite"
        if definite and not ev:
            bad.append(f"{it['id']}: certainty=definite без evidence")
        for e in ev:
            c = classes.get(e.get("path"))
            if c is None:
                (bad if definite else warn).append(f"{it['id']}: документа {e.get('path')} нет в классах")
                continue
            o, q = c["origin_class"], c["quality"]
            if definite and (o not in allowed_origin or q not in allowed_quality):
                bad.append(f"{it['id']}: definite опирается на {e['path']} (происхождение {o}, качество {q})")
            elif not definite and (o in ("?", "C") or q == "N"):
                warn.append(f"{it['id']}: слабый источник {e['path']} (происхождение {o}, качество {q})")
    for w in warn:
        print("предупреждение:", w)
    if bad:
        print("НАРУШЕНИЯ:\n - " + "\n - ".join(bad))
        sys.exit(1)
    print(f"OK: проверено выводов {len(insights)}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("classify"); c.add_argument("registry"); c.add_argument("--out", required=True)
    c.add_argument("--rules"); c.add_argument("--overrides")
    c.add_argument("--root", help="каталог корпуса: пути реестра сопоставляются с файлами на диске по имени")
    s = sp.add_parser("summary"); s.add_argument("classes")
    g = sp.add_parser("gate"); g.add_argument("registry"); g.add_argument("classes")
    g.add_argument("--allow-ocr", action="store_true"); g.add_argument("--allow-class", action="append", choices=["B", "C"])
    a = p.parse_args()
    {"classify": cmd_classify, "summary": cmd_summary, "gate": cmd_gate}[a.cmd](a)


if __name__ == "__main__":
    main()
