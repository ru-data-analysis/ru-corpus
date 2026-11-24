#!/usr/bin/env python3
"""Детерминированное разбиение документов между воркерами. Только стандартная библиотека.

python partition.py docs.csv "вопрос" [--workers 4] [--out clusters]
docs.csv: doc_id,title,path[,sha256]
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
from datetime import datetime, timezone


def norm_question(q):
    return re.sub(r"\s+", " ", q.strip()).casefold()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def partition(doc_ids, question, workers):
    qhash = hashlib.sha256(norm_question(question).encode("utf-8")).hexdigest()
    n = len(doc_ids)
    k = max(1, min(workers, n)) if n < 3 else max(3, min(4, workers, n))
    ids = sorted(doc_ids)  # порядок не зависит от входного файла
    random.Random(int(qhash[:8], 16)).shuffle(ids)
    buckets = {f"w{i + 1:02d}": [] for i in range(k)}
    names = list(buckets)
    for i, d in enumerate(ids):
        buckets[names[i % k]].append(d)
    return qhash, buckets


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("docs_csv")
    p.add_argument("question")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", default="clusters")
    p.add_argument("--run-id", help="для воспроизведения; по умолчанию хэш вопроса + время UTC")
    a = p.parse_args()

    docs = []
    with open(a.docs_csv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("doc_id"):
                sys.exit("в docs.csv есть строка без doc_id")
            if not row.get("sha256") and row.get("path") and os.path.exists(row["path"]):
                row["sha256"] = file_hash(row["path"])
            docs.append(row)
    ids = [d["doc_id"] for d in docs]
    if len(set(ids)) != len(ids):
        sys.exit("doc_id не уникальны")
    if not ids:
        sys.exit("пустой набор документов")

    qhash, buckets = partition(ids, a.question, a.workers)
    run_id = a.run_id or f"{qhash[:12]}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    root = os.path.join(a.out, run_id)
    os.makedirs(os.path.join(root, "workers"), exist_ok=True)
    manifest = {
        "run_id": run_id, "question": a.question, "question_hash": qhash,
        "seed": int(qhash[:8], 16), "n_docs": len(ids),
        "documents": [{k: d.get(k, "") for k in ("doc_id", "title", "path", "sha256")} for d in docs],
        "assignment": buckets,
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    for w, items in buckets.items():
        with open(os.path.join(root, "workers", f"{w}_assignment.json"), "w", encoding="utf-8") as f:
            json.dump({"worker_id": w, "question": a.question, "doc_ids": items}, f, ensure_ascii=False, indent=2)
    print(f"{run_id}: документов {len(ids)}, воркеров {len(buckets)}, "
          f"размеры {[len(v) for v in buckets.values()]}")


if __name__ == "__main__":
    main()
