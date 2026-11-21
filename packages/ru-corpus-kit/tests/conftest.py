# -*- coding: utf-8 -*-
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import synth  # noqa: E402
from ru_corpus_kit import cli, config, extract, indexer  # noqa: E402
from ru_corpus_kit.kit import Kit  # noqa: E402

PREFIX = "demo/"
try:
    import docx  # noqa: F401
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False
OCR_WHY = extract.ocr_ready("rus+eng")


def make_project(base: Path, profile: str = "", prefix: str = PREFIX, scan: bool = True):
    """Проект: base/docs — корпус, base/corpus.toml — настройки. -> (cfg, файлы корпуса)."""
    files = synth.make_corpus(base / "docs", scan=scan, docx_ok=HAVE_DOCX)
    cfg_path = base / "corpus.toml"
    config.write_template(cfg_path, "docs", prefix, profile)
    return config.load(cfg_path), files


def build(cfg, **kw):
    return indexer.run(cfg, log=lambda m: None, **kw)


def doc_id(kit, needle):
    """id документа по подстроке названия."""
    return next(k for k, r in kit.registry().items() if needle in r["rel_path"])


def cli_json(cfg, *args):
    """Запуск `ru-corpus` в процессе: -> (код, JSON из stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["--config", str(cfg.path), *args])
    return code, json.loads(buf.getvalue().strip().splitlines()[-1])


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Индекс синтетического корпуса без профиля (только ядро)."""
    base = tmp_path_factory.mktemp("core")
    cfg, files = make_project(base)
    stats = build(cfg)
    kit = Kit(cfg)
    yield {"cfg": cfg, "kit": kit, "files": files, "stats": stats}
    kit.close()


@pytest.fixture(scope="module")
def built_profile(tmp_path_factory):
    """Тот же корпус с профилем tso_disclosure."""
    base = tmp_path_factory.mktemp("profiled")
    cfg, files = make_project(base, profile="tso_disclosure")
    stats = build(cfg)
    kit = Kit(cfg)
    yield {"cfg": cfg, "kit": kit, "files": files, "stats": stats}
    kit.close()
