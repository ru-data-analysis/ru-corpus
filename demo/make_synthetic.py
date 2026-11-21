#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генерирует синтетический корпус «АО «Демо-Сеть»» в demo/corpus/synthetic/.

Файлы вымышленные (числа тоже) и в git не хранятся — создаются генератором из тестов пакета
(packages/ru-corpus-kit/tests/synth.py): PDF отчёта, широкая таблица тарифов, скан, XLSX, DOCX.

    python3 demo/make_synthetic.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent / "packages" / "ru-corpus-kit" / "tests"
OUT = HERE / "corpus" / "synthetic"


def main() -> int:
    sys.path.insert(0, str(TESTS))
    from synth import make_corpus          # noqa: E402  (генератор лежит в тестах пакета)

    OUT.mkdir(parents=True, exist_ok=True)
    files = make_corpus(OUT)
    for name, path in sorted(files.items()):
        print(f"{name:8s} {path.relative_to(HERE.parent)}  {path.stat().st_size} байт")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
