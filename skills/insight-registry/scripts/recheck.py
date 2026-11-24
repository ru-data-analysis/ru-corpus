#!/usr/bin/env python3
"""Пометка выводов, чьи документы изменились или исчезли: recheck REGISTRY SNAPSHOT [--write].

SNAPSHOT — снимок корпуса из skills/corpus-manifest (поля files[].path и files[].sha256).
Вывод проверяется по списку evidence: у каждого элемента должны быть path и sha256 на момент прогона.
Код возврата 1, если найдены затронутые выводы (удобно для CI и ритуала «после обновления корпуса»).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("registry")
    p.add_argument("snapshot")
    p.add_argument("--write", action="store_true", help="записать status=needs_recheck в реестр")
    a = p.parse_args()

    with open(a.snapshot, encoding="utf-8") as f:
        snap = {x["path"]: x["sha256"] for x in json.load(f)["files"]}
    with open(a.registry, encoding="utf-8") as f:
        data = json.load(f)

    stale, unverifiable = [], []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for it in data.get("insights", []):
        reasons = []
        for e in it.get("evidence") or []:
            path, old = e.get("path"), e.get("sha256")
            if not old:
                unverifiable.append(f"{it['id']}: у evidence {path} нет sha256")
                continue
            now = snap.get(path)
            if now is None:
                reasons.append(f"документ удалён или переименован: {path}")
            elif now != old:
                reasons.append(f"документ изменён: {path}")
        if not (it.get("evidence") or []):
            unverifiable.append(f"{it['id']}: нет evidence")
        if reasons:
            stale.append((it, reasons))

    for it, reasons in stale:
        print(f"ПЕРЕПРОВЕРИТЬ {it['id']} ({it['topic']}): " + "; ".join(reasons))
    for u in unverifiable:
        print("не проверяется:", u)
    if not stale:
        print(f"затронутых выводов нет (проверено {len(data.get('insights', []))})")
    if a.write and stale:
        for it, reasons in stale:
            it["status"] = "needs_recheck"
            it["recheck_reason"] = reasons
            it["recheck_date"] = today
        tmp = a.registry + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, a.registry)
        print(f"помечено выводов: {len(stale)}")
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
