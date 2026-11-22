#!/usr/bin/env python3
"""Проверка форматных ворот рабочего отчёта .run.md. Только стандартная библиотека.

Использование: python check_run_report.py report.run.md [--print-insights]
Код возврата 0 — форма корректна, 1 — есть нарушения.
"""
import json
import re
import sys

VERDICTS = ("supported", "refuted", "open")
CERT = ("definite", "tentative")


def section(text, number):
    """Текст раздела '## N.' до следующего '## '."""
    m = re.search(rf"^##\s+{number}\.[^\n]*\n(.*?)(?=^##\s+\d+\.|\Z)", text, re.S | re.M)
    return m.group(1) if m else None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    text = open(argv[1], encoding="utf-8").read()
    errors = []

    s0 = section(text, 0)
    if s0 is None:
        errors.append("нет раздела «## 0. Привязка»")
    else:
        if len(re.findall(r"`h-[^`\s]+`", s0)) < 1:
            errors.append("§0: нет id гипотезы вида `h-…` в обратных кавычках")
        if not re.search(r"`s-[^`\s]+`", s0):
            errors.append("§0: нет id спеки вида `s-…`")
        if not re.search(r"sha256\s+[0-9a-f]{8,}", s0):
            errors.append("§0: нет хэша спеки (sha256 …)")
        if not re.search(r"Хэш корпуса\s*\|[^|\n]*?\b[0-9a-f]{12,}\b", s0):
            errors.append("§0: нет строки «Хэш корпуса» с хэшем (corpus_hash, не короче 12 знаков)")
        if not re.search(r"Сопоставимость периодов\s*\|[^|\n]*(пройдена|после пересчёта|не нужна)", s0):
            errors.append("§0: нет строки «Сопоставимость периодов» (пройдена | после пересчёта | не нужна)")

    s3 = section(text, 3)
    rule_verdict = None
    if s3 is None:
        errors.append("нет раздела «## 3. Проверка правила решения»")
    else:
        if not re.search(r"Правило из спеки\s*:", s3):
            errors.append("§3: нет строки «Правило из спеки:»")
        if not re.search(r"Факт\s*:", s3):
            errors.append("§3: нет строки «Факт:»")
        m = re.search(r"Правило даёт\s*:\s*\**\s*(supported|refuted|open)", s3)
        if not m:
            errors.append("§3: нет строки «Правило даёт: supported|refuted|open»")
        else:
            rule_verdict = m.group(1)

    s4 = section(text, 4)
    if s4 is None:
        errors.append("нет раздела «## 4. Чего этот прогон не доказывает»")
    elif len(re.findall(r"^\s*[-*]\s+\S", s4, re.M)) < 2:
        errors.append("§4: нужно минимум два пункта списка")

    s5 = section(text, 5)
    insights = []
    if s5 is None:
        errors.append("нет раздела «## 5. Вывод»")
    else:
        lines = re.findall(r"`h-[^`\s]+`\s*→[^\n]*?\*\*(supported|refuted|open)\*\*", s5)
        if len(lines) != 1:
            errors.append(f"§5.1: нужна ровно одна строка вердикта, найдено {len(lines)}")
        elif rule_verdict and lines[0] != rule_verdict:
            errors.append(f"§5.1: вердикт «{lines[0]}» не совпадает с §3 «{rule_verdict}»")
        blocks = re.findall(r"```json\s*\n(.*?)```", s5, re.S)
        if len(blocks) != 1:
            errors.append(f"§5.2: нужен ровно один блок ```json, найдено {len(blocks)}")
        else:
            try:
                insights = json.loads(blocks[0])
            except json.JSONDecodeError as e:
                errors.append(f"§5.2: некорректный JSON: {e}")
            else:
                if not isinstance(insights, list) or len(insights) > 3:
                    errors.append("§5.2: ожидается массив из 0–3 объектов")
                    insights = []
                for i, it in enumerate(insights, 1):
                    for k in ("question", "narrative", "answer"):
                        if not str(it.get(k, "")).strip():
                            errors.append(f"§5.2 #{i}: пустое поле {k}")
                    if it.get("certainty") not in CERT:
                        errors.append(f"§5.2 #{i}: certainty ∈ {CERT}")
                    if it.get("importance") not in (1, 2, 3, 4, 5):
                        errors.append(f"§5.2 #{i}: importance — целое 1–5")

    if "--print-insights" in argv and not errors:
        print(json.dumps(insights, ensure_ascii=False, indent=2))
    if errors:
        print("НАРУШЕНИЯ:")
        for e in errors:
            print(" -", e)
        return 1
    print("OK: форматные ворота пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
