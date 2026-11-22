#!/usr/bin/env python3
"""Журнал затрат прогона: run / summary / line. Только стандартная библиотека."""
import argparse
import csv
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    import resource
except ImportError:  # Windows
    resource = None

COLS = ["ts_utc", "label", "cmd", "exit", "wall_s", "cpu_s", "max_rss_mb", "docs", "pages", "model", "note"]


def rss_mb(ru_maxrss):
    # Linux отдаёт килобайты, macOS — байты
    return ru_maxrss / (1024 * 1024) if platform.system() == "Darwin" else ru_maxrss / 1024


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cmd_run(a):
    if not a.command:
        sys.exit("после -- нужна команда")
    cmd = a.command[1:] if a.command[0] == "--" else a.command
    before = resource.getrusage(resource.RUSAGE_CHILDREN) if resource else None
    t0 = time.monotonic()
    try:
        code = subprocess.call(cmd)
    except FileNotFoundError:
        sys.exit(f"команда не найдена: {cmd[0]}")
    wall = time.monotonic() - t0
    cpu = rss = ""
    if resource:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = f"{(after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime):.2f}"
        rss = f"{rss_mb(after.ru_maxrss):.1f}"
    row = {"ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "label": a.label,
           "cmd": " ".join(cmd), "exit": code, "wall_s": f"{wall:.2f}", "cpu_s": cpu, "max_rss_mb": rss,
           "docs": a.docs if a.docs is not None else "", "pages": a.pages if a.pages is not None else "",
           "model": a.model or "", "note": a.note or ""}
    os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
    new = not os.path.exists(a.log)
    with open(a.log, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"[cost-log] {a.label}: wall {row['wall_s']} с, cpu {row['cpu_s'] or '—'} с, "
          f"память {row['max_rss_mb'] or '—'} МБ, код {code}", file=sys.stderr)
    sys.exit(code)


def cmd_summary(a):
    rows = [r for r in read(a.log) if not a.label or r["label"] == a.label]
    if not rows:
        sys.exit("в журнале нет подходящих строк")
    groups = {}
    for r in rows:
        groups.setdefault(r["label"], []).append(r)
    for label, rs in sorted(groups.items()):
        wall = sum(fnum(r["wall_s"]) or 0 for r in rs)
        cpu = sum(fnum(r["cpu_s"]) or 0 for r in rs)
        docs = sum(fnum(r["docs"]) or 0 for r in rs)
        pages = sum(fnum(r["pages"]) or 0 for r in rs)
        fails = sum(1 for r in rs if r["exit"] != "0")
        s = f"{label}: запусков {len(rs)} (с ошибкой {fails}), wall {wall:.1f} с (среднее {wall / len(rs):.1f}), cpu {cpu:.1f} с"
        if docs:
            s += f", {wall / docs:.2f} с/документ"
        if pages:
            s += f", {wall / pages:.3f} с/страница"
        print(s)


def cmd_line(a):
    rows = [r for r in read(a.log) if r["label"] == a.label]
    if not rows:
        sys.exit(f"нет записей с меткой {a.label}")
    r = rows[-1]
    parts = [f"wall_s={r['wall_s']}"]
    if r["cpu_s"]:
        parts.append(f"cpu_s={r['cpu_s']}")
    if r["max_rss_mb"]:
        parts.append(f"max_rss_mb={r['max_rss_mb']}")
    if r["docs"]:
        parts.append(f"docs={r['docs']}")
    if r["pages"]:
        parts.append(f"pages={r['pages']}")
    if r["model"]:
        parts.append(f"model={r['model']}")
    print("cost: " + "; ".join(parts))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--log", required=True); r.add_argument("--label", required=True)
    r.add_argument("--docs", type=int); r.add_argument("--pages", type=int)
    r.add_argument("--model"); r.add_argument("--note"); r.add_argument("command", nargs=argparse.REMAINDER)
    s = sp.add_parser("summary"); s.add_argument("log"); s.add_argument("--label")
    l = sp.add_parser("line"); l.add_argument("log"); l.add_argument("--label", required=True)
    a = p.parse_args()
    {"run": cmd_run, "summary": cmd_summary, "line": cmd_line}[a.cmd](a)


if __name__ == "__main__":
    main()
