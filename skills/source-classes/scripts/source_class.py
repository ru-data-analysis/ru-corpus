#!/usr/bin/env python3
"""Классы источников: textlayer / classify / summary / gate. Только стандартная библиотека."""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zlib
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


TL_QUALITY = {"yes": "T", "partial": "P", "no": "X", "ocr_layer": "N", "unknown": "?"}
TL_COLS = ["path", "sha256", "text_layer", "pages", "text_streams", "images", "method"]
MAX_PDF = 300 * 1024 * 1024
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_PAGE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")
_COUNT = re.compile(rb"/Count\s+(\d+)")
_TEXT_OP = re.compile(rb"\bBT\b.*?(?:\)\s*Tj|\]\s*TJ|>\s*Tj)", re.S)
_HIDDEN = re.compile(rb"\b3\s+Tr\b")


def pdf_textlayer(data):
    """Эвристика по самому файлу, без распознавания. Возвращает (text_layer, pages, text_streams, images)."""
    if b"/Encrypt" in data[-2048:] or b"/Encrypt" in data[:2048]:
        return "unknown", 0, 0, 0
    pages = len(_PAGE.findall(data))
    images = len(re.findall(rb"/Subtype\s*/Image", data))
    text_streams = hidden = 0
    for m in _STREAM.finditer(data):
        blob = m.group(1)
        try:
            blob = zlib.decompress(blob)
        except zlib.error:
            pass
        pages += len(_PAGE.findall(blob)) if blob[:2] != b"BT" and b"/Type" in blob[:4096] else 0
        if _TEXT_OP.search(blob):
            text_streams += 1
            if _HIDDEN.search(blob):
                hidden += 1
    if pages == 0:
        counts = [int(x) for x in _COUNT.findall(data)]
        pages = max(counts) if counts else 0
    if pages == 0:
        return "unknown", 0, text_streams, images
    if text_streams == 0:
        return ("no" if images else "unknown"), pages, 0, images
    if images and hidden * 2 >= text_streams:
        return "ocr_layer", pages, text_streams, images
    return ("yes" if text_streams >= 0.9 * pages else "partial"), pages, text_streams, images


def cmd_textlayer(a):
    rows = []
    for d, dirs, files in os.walk(a.root):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for fn in sorted(files):
            if fn.startswith(".") or not fn.lower().endswith(".pdf"):
                continue
            full = os.path.join(d, fn)
            rel = os.path.relpath(full, a.root).replace(os.sep, "/")
            row = {"path": rel, "sha256": "", "text_layer": "unknown", "pages": 0, "text_streams": 0, "images": 0,
                   "method": "эвристика по потокам PDF"}
            try:
                if os.path.getsize(full) > MAX_PDF:
                    row["method"] = "файл больше 300 МБ, не разобран"
                else:
                    with open(full, "rb") as f:
                        data = f.read()
                    row["sha256"] = hashlib.sha256(data).hexdigest()
                    row["text_layer"], row["pages"], row["text_streams"], row["images"] = pdf_textlayer(data)
            except Exception as e:  # битый файл не должен ронять обход
                row["method"] = f"ошибка разбора: {type(e).__name__}"
            rows.append(row)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TL_COLS)
        w.writeheader()
        w.writerows(rows)
    c = {}
    for r in rows:
        c[r["text_layer"]] = c.get(r["text_layer"], 0) + 1
    print(f"{a.out}: PDF {len(rows)}; по признаку: {c}")


def load_textlayer(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["path"]: r for r in csv.DictReader(f)}


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
    tl = load_textlayer(a.textlayer) if a.textlayer else {}
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
        quality = quality_of(pick(r, TEXT_COLS), path)
        t = tl.get(path)
        if t is not None and path.lower().endswith(".pdf"):
            quality = TL_QUALITY.get(t["text_layer"], "?")
            if a.root and t.get("sha256"):  # признак относится к другой версии файла: не верим
                try:
                    with open(os.path.join(a.root, path), "rb") as fh:
                        now = hashlib.sha256(fh.read()).hexdigest()
                except OSError:
                    now = ""
                if now != t["sha256"]:
                    quality = "?"
                    why += "; признак текстового слоя устарел (хэш файла изменился), перезапустите textlayer"
        elif tl and path.lower().endswith(".pdf"):
            why += "; PDF нет в таблице текстового слоя"
        out.append({"path": path, "origin_class": cls, "quality": quality,
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


QUALITY_WHY = {
    "X": "нет текстового слоя (скан), сначала распознайте документ",
    "N": "встроенный слой распознавания шумный",
    "P": "слой неполный, нужен --allow-ocr и страница в evidence.locator",
    "O": "текст получен распознаванием, нужен --allow-ocr и страница в evidence.locator",
    "?": "слой не определён, запустите textlayer или задайте --allow-unknown-quality",
}


def cmd_gate(a):
    classes = read_classes(a.classes)
    allowed_origin = {"A"} | set(a.allow_class or [])
    allowed_quality = {"T"} | ({"O", "P"} if a.allow_ocr else set()) | ({"?"} if a.allow_unknown_quality else set())
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
            if definite and o not in allowed_origin:
                bad.append(f"{it['id']}: definite опирается на {e['path']} (происхождение {o}: нужен класс A)")
            elif definite and q not in allowed_quality:
                bad.append(f"{it['id']}: definite опирается на {e['path']} (качество {q}: {QUALITY_WHY.get(q, q)})")
            elif definite and q in ("O", "P") and not (e.get("locator") or "").strip():
                bad.append(f"{it['id']}: {e['path']} качество {q}, а в evidence нет locator (страница или фрагмент)")
            elif definite and q == "?":
                warn.append(f"{it['id']}: {e['path']} пропущен с неопределённым качеством (--allow-unknown-quality)")
            elif not definite and (o in ("?", "C") or q in ("N", "X")):
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
    c.add_argument("--textlayer", help="таблица признака текстового слоя PDF (команда textlayer)")
    c.add_argument("--root", help="каталог корпуса: пути реестра сопоставляются с файлами на диске по имени")
    t = sp.add_parser("textlayer", help="определить текстовый слой у PDF корпуса без распознавания")
    t.add_argument("root"); t.add_argument("--out", required=True)
    s = sp.add_parser("summary"); s.add_argument("classes")
    g = sp.add_parser("gate"); g.add_argument("registry"); g.add_argument("classes")
    g.add_argument("--allow-ocr", action="store_true"); g.add_argument("--allow-class", action="append", choices=["B", "C"])
    g.add_argument("--allow-unknown-quality", action="store_true", help="аварийно: пускать качество «?» с предупреждением")
    a = p.parse_args()
    {"textlayer": cmd_textlayer, "classify": cmd_classify, "summary": cmd_summary, "gate": cmd_gate}[a.cmd](a)


if __name__ == "__main__":
    main()
