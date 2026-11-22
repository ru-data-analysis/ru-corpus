#!/usr/bin/env python3
"""Проверка, что каждая дословная цитата из находок есть в тексте источника.

python verify_quotes.py clusters/<run_id> [--text-dir texts]
Тексты документов: <text-dir>/<doc_id>.txt (UTF-8). По умолчанию — путь из manifest.json,
если это .txt/.md. Для PDF и сканов сначала извлечь текст отдельно.
Код возврата 1, если есть цитаты, не найденные в источнике, или документ назначен двум воркерам.
"""
import argparse
import glob
import json
import os
import re
import sys


def norm(s):
    s = s.replace(" ", " ").replace("«", '"').replace("»", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir")
    p.add_argument("--text-dir")
    a = p.parse_args()
    man = json.load(open(os.path.join(a.run_dir, "manifest.json"), encoding="utf-8"))
    paths = {d["doc_id"]: d["path"] for d in man["documents"]}
    bad, checked, owner = [], 0, {}
    for w, items in man["assignment"].items():
        for d in items:
            if d in owner:
                bad.append(f"документ {d} назначен {owner[d]} и {w}")
            owner[d] = w
    texts = {}

    def get_text(doc_id):
        if doc_id in texts:
            return texts[doc_id]
        cands = []
        if a.text_dir:
            cands.append(os.path.join(a.text_dir, f"{doc_id}.txt"))
        if paths.get(doc_id, "").lower().endswith((".txt", ".md")):
            cands.append(paths[doc_id])
        for c in cands:
            if os.path.exists(c):
                texts[doc_id] = norm(open(c, encoding="utf-8", errors="replace").read())
                return texts[doc_id]
        texts[doc_id] = None
        return None

    for fn in sorted(glob.glob(os.path.join(a.run_dir, "workers", "w*_findings.json"))):
        data = json.load(open(fn, encoding="utf-8"))
        w = data.get("worker_id")
        for f in data.get("findings", []):
            doc = f["doc_id"]
            if owner.get(doc) != w:
                bad.append(f"{w}: документ {doc} не назначен этому воркеру")
            if f.get("not_found"):
                continue
            if not f.get("quotes"):
                bad.append(f"{w}/{doc}: ответ без цитат")
            for q in f.get("quotes", []):
                checked += 1
                if not q.get("locator"):
                    bad.append(f"{w}/{doc}: цитата без места")
                t = get_text(doc)
                if t is None:
                    bad.append(f"{w}/{doc}: нет текста для проверки")
                elif norm(q["text"]) not in t:
                    bad.append(f"{w}/{doc}: цитата не найдена: «{q['text'][:60]}…»")
    print(f"проверено цитат: {checked}")
    if bad:
        print("НАРУШЕНИЯ:")
        for b in bad:
            print(" -", b)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
