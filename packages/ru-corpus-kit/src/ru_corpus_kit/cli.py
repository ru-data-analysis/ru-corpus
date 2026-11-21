# -*- coding: utf-8 -*-
"""Консольная команда `ru-corpus`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, config as _config
from . import indexer, status as _status, tools
from .kit import Kit


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default=argparse.SUPPRESS, help="путь к corpus.toml (по умолчанию ищется вверх от текущей папки "
                                                             "или берётся из RU_CORPUS_CONFIG)")
    ap = argparse.ArgumentParser(prog="ru-corpus", description="Русский поиск и проверяемая аналитика по корпусу документов",
                                 parents=[common])
    ap.add_argument("--version", action="version", version=f"ru-corpus {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="создать corpus.toml в текущей папке", parents=[common])
    s.add_argument("--root", default=".", help="каталог с документами (по умолчанию текущий)")
    s.add_argument("--prefix", default="", help="префикс ссылок на источник в выводе (поля file и origin)")
    s.add_argument("--profile", default="", help="отраслевой профиль, например tso_disclosure")
    s.add_argument("--path", default=_config.CONFIG_NAME, help="куда записать файл")
    s.add_argument("--force", action="store_true", help="перезаписать существующий файл")

    s = sub.add_parser("index", help="реестр -> текст -> OCR -> леммы -> таблицы -> bm25 (инкрементально по sha256)",
                       parents=[common])
    s.add_argument("--no-ocr", action="store_true", help="не распознавать сканы в этом запуске")
    s.add_argument("--force", action="store_true", help="пересобрать все документы")
    s.add_argument("--stages", default=",".join(indexer.STAGES), help="стадии через запятую")
    s.add_argument("--quiet", action="store_true")

    s = sub.add_parser("status", help="состояние индекса", parents=[common])
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("search", help="доказательства по вопросу или «в корпусе нет»; запрос-число ищется по всем страницам",
                       parents=[common])
    s.add_argument("query")
    s.add_argument("--n", type=int, default=5)
    s.add_argument("--rerank", action="store_true", help="кросс-энкодер поверх BM25 (extras [rerank])")

    s = sub.add_parser("page", help="точный текст страницы + путь + раздел + sha256", parents=[common])
    s.add_argument("doc")
    s.add_argument("page")
    s.add_argument("--max-chars", type=int, default=20000)

    s = sub.add_parser("table", help="ячейки таблиц с измерениями и якорем", parents=[common])
    s.add_argument("--q", required=True, help="подпись строки")
    s.add_argument("--year", type=int)
    s.add_argument("--level")
    s.add_argument("--half")
    s.add_argument("--doc")
    s.add_argument("--page")
    s.add_argument("--n", type=int, default=10)

    s = sub.add_parser("doc", help="карточка документа или поиск по названию", parents=[common])
    s.add_argument("doc", nargs="?")
    s.add_argument("--find")
    s.add_argument("--n", type=int, default=15)

    s = sub.add_parser("number", help="стоит ли число дословно на странице", parents=[common])
    s.add_argument("doc")
    s.add_argument("page")
    s.add_argument("value")

    s = sub.add_parser("aggregate", help="сумма/число/среднее/мин/макс по графе таблицы", parents=[common])
    s.add_argument("doc")
    s.add_argument("--column", required=True, help="слова шапки или номер графы")
    s.add_argument("--page")
    s.add_argument("--column2", help="вторая графа: отношение сумм")
    s.add_argument("--where", help="«графа=значение» или «графа~часть»")

    s = sub.add_parser("calc", help="точная арифметика: + - * / скобки, %", parents=[common])
    s.add_argument("expr")
    s.add_argument("--digits", type=int)
    return ap


def cmd_init(a):
    dest = Path(a.path)
    if dest.exists() and not a.force:
        out({"ok": False, "error": f"{dest} уже есть (--force — перезаписать)"})
        return 1
    _config.write_template(dest, a.root, a.prefix, a.profile)
    out({"ok": True, "config": str(dest.resolve()), "next": "ru-corpus index"})
    return 0


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "calc":                                  # калькулятор не требует корпуса
        try:
            out(tools.calc(a.expr, a.digits))
            return 0
        except Exception as e:  # noqa: BLE001
            out({"ok": False, "error": f"{type(e).__name__}: {e}"})
            return 1
    if a.cmd == "init":
        return cmd_init(a)
    try:
        cfg = _config.load(getattr(a, "config", None))
        if a.cmd == "index":
            stages = tuple(x.strip() for x in a.stages.split(",") if x.strip())
            log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
            stats = indexer.run(cfg, stages=stages, force=a.force, use_ocr=False if a.no_ocr else None, log=log)
            out({"ok": True, **stats})
            return 0
        if a.cmd == "status":
            st = _status.collect(cfg)
            print(_status.as_json(st) if a.json else _status.render(st))
            return 0
        kit = Kit(cfg)
        try:
            if a.cmd == "search":
                res = tools.search(kit, a.query, a.n, rerank=True if a.rerank else None)
            elif a.cmd == "page":
                res = tools.page(kit, a.doc, a.page, a.max_chars)
            elif a.cmd == "table":
                res = tools.table(kit, a.q, a.year, a.level, a.half, a.doc, a.page, a.n)
            elif a.cmd == "doc":
                res = tools.doc(kit, a.doc, a.find, a.n)
            elif a.cmd == "number":
                res = tools.number(kit, a.doc, a.page, a.value)
            elif a.cmd == "aggregate":
                res = tools.aggregate(kit, a.doc, a.column, a.page, a.column2, a.where)
            else:  # pragma: no cover
                raise ValueError(a.cmd)
            out(res)
            return 0
        finally:
            kit.close()
    except Exception as e:  # noqa: BLE001
        out({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
