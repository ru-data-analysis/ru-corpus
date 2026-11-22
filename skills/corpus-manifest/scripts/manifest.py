#!/usr/bin/env python3
"""Манифест корпуса: snapshot / from-csv / diff / verify / hash. Только стандартная библиотека.

Корпус только читается: путь --out внутри корпуса отклоняется.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

SKIP_DIRS = {".git", ".kb", ".cache", "index", "__pycache__", "node_modules"}
PATH_COLS = ("rel_path", "файл", "path")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def corpus_hash(files):
    lines = [f"{f['path']}\t{f['sha256']}" for f in sorted(files, key=lambda f: f["path"])]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def make_snapshot(files, source):
    files = sorted(files, key=lambda f: f["path"])
    return {
        "version": 1,
        "source": source,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_files": len(files),
        "corpus_hash": corpus_hash(files),
        "files": files,
    }


def inside(child, parent):
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def write_json(path, data):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def cmd_snapshot(a):
    if not os.path.isdir(a.root):
        sys.exit(f"нет каталога: {a.root}")
    if inside(a.out, a.root):
        sys.exit("--out лежит внутри корпуса: корпус только читается, укажите другой путь")
    exts = {"." + e.strip().lower().lstrip(".") for e in a.ext.split(",")} if a.ext else None
    files = []
    for dirpath, dirnames, filenames in os.walk(a.root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            if exts and os.path.splitext(fn)[1].lower() not in exts:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, a.root).replace(os.sep, "/")
            files.append({"path": rel, "sha256": sha256_file(full), "size": os.path.getsize(full)})
    snap = make_snapshot(files, os.path.abspath(a.root))
    write_json(a.out, snap)
    print(f"снимок {a.out}: файлов {snap['n_files']}, corpus_hash {snap['corpus_hash'][:16]}…")


def cmd_from_csv(a):
    with open(a.csv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("пустой CSV")
    pcol = next((c for c in PATH_COLS if c in rows[0]), None)
    if not pcol:
        sys.exit(f"нет колонки пути ({', '.join(PATH_COLS)})")
    if a.hash_col not in rows[0]:
        sys.exit(f"нет колонки {a.hash_col}")
    files, seen = [], set()
    for r in rows:
        p = r[pcol].replace("\\", "/")
        if p in seen:
            sys.exit(f"путь повторяется: {p}")
        seen.add(p)
        if not r[a.hash_col]:
            sys.exit(f"пустой хэш у {p}")
        size = r.get("size_bytes") or r.get("размер_байт") or ""
        files.append({"path": p, "sha256": r[a.hash_col], "size": int(size) if str(size).isdigit() else None})
    snap = make_snapshot(files, os.path.abspath(a.csv))
    write_json(a.out, snap)
    print(f"снимок {a.out}: файлов {snap['n_files']}, corpus_hash {snap['corpus_hash'][:16]}…")


def load(path):
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    if corpus_hash(snap["files"]) != snap["corpus_hash"]:
        sys.exit(f"{path}: corpus_hash не сходится с содержимым, снимок правили вручную")
    return snap


def diff(old, new):
    o = {f["path"]: f["sha256"] for f in old["files"]}
    n = {f["path"]: f["sha256"] for f in new["files"]}
    changed = sorted(p for p in o.keys() & n.keys() if o[p] != n[p])
    removed = {p: o[p] for p in o.keys() - n.keys()}
    added = {p: n[p] for p in n.keys() - o.keys()}
    renamed = []
    by_hash = {}
    for p, h in added.items():
        by_hash.setdefault(h, []).append(p)
    for p, h in sorted(removed.items()):
        if by_hash.get(h):
            renamed.append((p, by_hash[h].pop(0)))
    ren_old = {a for a, _ in renamed}
    ren_new = {b for _, b in renamed}
    return {
        "added": sorted(p for p in added if p not in ren_new),
        "removed": sorted(p for p in removed if p not in ren_old),
        "changed": changed,
        "renamed": [{"from": a, "to": b} for a, b in renamed],
    }


def cmd_diff(a):
    d = diff(load(a.old), load(a.new))
    total = sum(len(v) for v in d.values())
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        for key, title in (("added", "добавлено"), ("changed", "изменено"), ("removed", "удалено")):
            for p in d[key]:
                print(f"{title}: {p}")
        for r in d["renamed"]:
            print(f"переименовано: {r['from']} → {r['to']}")
        print("корпус тот же" if not total else f"различий: {total}")
    sys.exit(1 if total else 0)


def cmd_verify(a):
    snap = load(a.snapshot)
    bad = []
    for f in snap["files"]:
        full = os.path.join(a.root, f["path"].replace("/", os.sep))
        if not os.path.isfile(full):
            bad.append(f"нет файла: {f['path']}")
        elif sha256_file(full) != f["sha256"]:
            bad.append(f"хэш не совпал: {f['path']}")
    if bad:
        print("НАРУШЕНИЯ:\n - " + "\n - ".join(bad))
        sys.exit(1)
    print(f"OK: {len(snap['files'])} файлов совпадают со снимком")


def cmd_hash(a):
    print(load(a.snapshot)["corpus_hash"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("snapshot"); s.add_argument("root"); s.add_argument("--out", required=True)
    s.add_argument("--ext", help="расширения через запятую, например pdf,docx")
    c = sp.add_parser("from-csv"); c.add_argument("csv"); c.add_argument("--out", required=True)
    c.add_argument("--hash-col", default="sha256")
    d = sp.add_parser("diff"); d.add_argument("old"); d.add_argument("new"); d.add_argument("--json", action="store_true")
    v = sp.add_parser("verify"); v.add_argument("snapshot"); v.add_argument("root")
    h = sp.add_parser("hash"); h.add_argument("snapshot")
    a = p.parse_args()
    {"snapshot": cmd_snapshot, "from-csv": cmd_from_csv, "diff": cmd_diff, "verify": cmd_verify, "hash": cmd_hash}[a.cmd](a)


if __name__ == "__main__":
    main()
