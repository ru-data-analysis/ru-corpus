#!/usr/bin/env python3
"""Реестр инсайтов: validate / ingest / render / list. Только стандартная библиотека."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

MAX_PER_TOPIC = 3
CERT = ("definite", "tentative")
REQUIRED = ("id", "topic", "question", "narrative", "answer", "certainty", "importance", "source_id")


def load(path):
    if not os.path.exists(path):
        return {"version": 1, "insights": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def validate(data):
    errs, seen = [], set()
    per_topic = {}
    for i, it in enumerate(data.get("insights", []), 1):
        for k in REQUIRED:
            if it.get(k) in (None, ""):
                errs.append(f"#{i}: нет поля {k}")
        if it.get("certainty") not in CERT:
            errs.append(f"#{i}: certainty ∈ {CERT}")
        if it.get("importance") not in (1, 2, 3, 4, 5):
            errs.append(f"#{i}: importance — целое 1–5")
        if it.get("id") in seen:
            errs.append(f"#{i}: дубликат id {it.get('id')}")
        seen.add(it.get("id"))
        per_topic[it.get("topic")] = per_topic.get(it.get("topic"), 0) + 1
    for t, n in per_topic.items():
        if n > MAX_PER_TOPIC:
            errs.append(f"тема «{t}»: {n} записей, максимум {MAX_PER_TOPIC}")
    return errs


def parse_report(path):
    text = open(path, encoding="utf-8").read()
    m0 = re.search(r"^##\s+0\.[^\n]*\n(.*?)(?=^##\s+\d+\.)", text, re.S | re.M)
    if not m0:
        sys.exit("в отчёте нет §0")
    src = re.search(r"`(s-[^`\s]+)`", m0.group(1))
    hyp = re.search(r"`(h-[^`\s]+)`", m0.group(1))
    if not src or not hyp:
        sys.exit("§0: нет id спеки или гипотезы")
    m5 = re.search(r"^##\s+5\.[^\n]*\n(.*)", text, re.S | re.M)
    if not m5:
        sys.exit("в отчёте нет §5")
    verdict = re.search(r"→[^\n]*?\*\*(supported|refuted|open)\*\*", m5.group(1))
    blocks = re.findall(r"```json\s*\n(.*?)```", m5.group(1), re.S)
    if len(blocks) != 1:
        sys.exit("§5.2: нужен ровно один блок json")
    return hyp.group(1), src.group(1), (verdict.group(1) if verdict else None), json.loads(blocks[0])


def cmd_ingest(a):
    data = load(a.registry)
    hyp, source_id, verdict, new = parse_report(a.report)
    source_id = f"{hyp}/{source_id}"
    kept = [it for it in data["insights"] if it.get("source_id") != source_id]
    replaced = len(data["insights"]) - len(kept)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    added = []
    for n, it in enumerate(new, 1):
        rec = {
            "id": f"i-{source_id.replace('/', '-')}-{n}",
            "topic": a.topic,
            "question": it["question"], "narrative": it["narrative"], "answer": it["answer"],
            "certainty": it["certainty"], "importance": it["importance"],
            "source_id": source_id, "verdict": verdict,
            "evidence": it.get("evidence", []), "updated": now,
        }
        added.append(rec)
    probe = {"insights": kept + added}
    # лимит по теме: сообщаем, что вытеснять
    in_topic = [r for r in probe["insights"] if r["topic"] == a.topic]
    if len(in_topic) > MAX_PER_TOPIC:
        weakest = min((r for r in in_topic if r["source_id"] != source_id), key=lambda r: r["importance"], default=None)
        sys.exit(f"тема «{a.topic}» превысит лимит {MAX_PER_TOPIC}; обновите или объедините запись "
                 f"{weakest['id'] if weakest else '?'} (минимальная важность)")
    errs = validate(probe)
    if errs:
        sys.exit("после загрузки реестр невалиден:\n - " + "\n - ".join(errs))
    old = {r["id"]: r for r in data["insights"] if r.get("source_id") == source_id}
    for r in added:  # updated не должен менять идемпотентность: берём прежнюю дату, если запись не изменилась
        o = old.get(r["id"])
        if o and {k: v for k, v in o.items() if k != "updated"} == {k: v for k, v in r.items() if k != "updated"}:
            r["updated"] = o["updated"]
    changed = {k: v for k, v in sorted((r["id"], r) for r in added)} != {k: v for k, v in sorted(old.items())}
    print(f"источник {source_id}: заменено {replaced}, записей из отчёта {len(added)}, "
          f"{'есть изменения' if changed else 'без изменений'}")
    if a.dry_run or not changed:
        return
    data["insights"] = kept + added
    save(a.registry, data)


def cmd_render(a):
    data = load(a.registry)
    errs = validate(data)
    if errs:
        sys.exit("реестр невалиден:\n - " + "\n - ".join(errs))
    out = ["<!-- АВТОГЕНЕРАЦИЯ: не править руками, файл перезаписывается registry.py render -->",
           "# База знаний", ""]
    topics = sorted({r["topic"] for r in data["insights"]})
    for t in topics:
        out += [f"## {t}", "", "| Вопрос | Ответ | Точность | Важность | Источник |", "|---|---|---|---|---|"]
        for r in sorted((r for r in data["insights"] if r["topic"] == t), key=lambda r: -r["importance"]):
            mark = "предварительно" if r["certainty"] == "tentative" else "точно"
            if r.get("status") == "needs_recheck":
                mark += " ⚠ перепроверить"
            out.append(f"| {r['question']} | {r['narrative']} | {mark} | {r['importance']} | `{r['source_id']}` |")
        out.append("")
    if a.knowledge_dir and os.path.isdir(a.knowledge_dir):
        out += ["## Курируемые документы", ""]
        for fn in sorted(os.listdir(a.knowledge_dir)):
            if not fn.endswith(".md"):
                continue
            lines = open(os.path.join(a.knowledge_dir, fn), encoding="utf-8").read().splitlines()
            title = next((l[2:].strip() for l in lines if l.startswith("# ")), fn)
            summary = ""
            seen_title = False
            for l in lines:
                if l.startswith("# "):
                    seen_title = True
                elif seen_title and l.strip() and not l.startswith("#"):
                    summary = l.strip()
                    break
            out.append(f"- [{title}]({a.knowledge_dir}/{fn}) — {summary}")
        out.append("")
    with open(a.output, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"записан {a.output}: тем {len(topics)}, записей {len(data['insights'])}")


def cmd_list(a):
    for r in load(a.registry)["insights"]:
        if a.topic and r["topic"] != a.topic:
            continue
        print(f"{r['id']} [{r['certainty']}, {r['importance']}] {r['topic']}: {r['question']}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    v = sp.add_parser("validate"); v.add_argument("registry")
    i = sp.add_parser("ingest"); i.add_argument("registry"); i.add_argument("report")
    i.add_argument("--topic", required=True); i.add_argument("--dry-run", action="store_true")
    r = sp.add_parser("render"); r.add_argument("registry"); r.add_argument("output")
    r.add_argument("--knowledge-dir")
    l = sp.add_parser("list"); l.add_argument("registry"); l.add_argument("--topic")
    a = p.parse_args()
    if a.cmd == "validate":
        errs = validate(load(a.registry))
        print("OK" if not errs else "НАРУШЕНИЯ:\n - " + "\n - ".join(errs))
        sys.exit(1 if errs else 0)
    {"ingest": cmd_ingest, "render": cmd_render, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
