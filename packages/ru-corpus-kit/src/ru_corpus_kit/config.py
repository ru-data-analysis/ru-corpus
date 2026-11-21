# -*- coding: utf-8 -*-
"""corpus.toml: путь к корпусу, папка индекса, префикс ссылок, синонимы, профиль."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .profile import Profile, load_synonyms, read_toml

CONFIG_NAME = "corpus.toml"
ENV_CONFIG = "RU_CORPUS_CONFIG"

DEFAULT_EXT = [".pdf", ".docx", ".xlsx", ".xlsm", ".xls", ".pptx", ".doc", ".txt", ".md", ".csv", ".json"]

TEMPLATE = '''# corpus.toml — настройки корпуса для ru-corpus
# Относительные пути считаются от каталога, где лежит этот файл.

[corpus]
# Каталог с документами (PDF, DOCX, XLSX, сканы…)
root = "{root}"
# Префикс, с которого начинаются ссылки на источник в выводе (поля file и origin):
# итог — «<префикс><относительный путь файла>». Можно оставить пустым.
source_prefix = "{prefix}"

[index]
# Куда складывать индекс (kb.sqlite, bm25.sqlite, registry.csv)
dir = ".ru-corpus"
# Готовые реестры CSV (колонки id, rel_path, title, section, type, year, ext, sha256);
# если пусто — реестр строится сам и лежит в registry.csv внутри индекса.
registry = []
# Реестры документов, извлечённых из архивов (в карточке документа from_archive = true)
archive_registry = []
# Явные пути к уже построенным базам (для открытия чужого индекса без переиндексации)
# kb = ""
# bm25 = ""
extensions = [".pdf", ".docx", ".xlsx", ".xlsm", ".xls", ".pptx", ".doc", ".txt", ".md", ".csv", ".json"]
# Маски путей (относительно корня), которые пропускаются
exclude = ["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/~$*"]
max_size_mb = 0            # 0 — без ограничения
ocr = true                 # распознавать сканы (нужен tesseract и extras [ocr])
ocr_dpi = 300
ocr_psm = 4
ocr_workers = 4
ocr_langs = "rus+eng"
tables = true              # таблицы PDF с сеткой (extras [tables])
wide_tables = true         # широкие альбомные таблицы по координатам (extras [tables])
bm25_window = 96           # токенов во фрагменте
bm25_overlap = 16

[search]
# Файл со словарём сокращений (TOML, таблица [synonyms]); пусто — словарь из профиля, если он есть
synonyms = ""
# Пороги «в корпусе нет»: ответ отказывает, когда обе ветки ниже порогов
fts_coverage = 0.75
bm25_best_doc = 0.6
bm25_miss = 0.2
# Разделы корпуса (первая папка), документы которых — производный слой: в выдаче они идут ниже первичных
derived_sections = []
rerank = false             # кросс-энкодер поверх BM25 (extras [rerank])

[profile]
# Отраслевой профиль: встроенный (например "{profile_hint}") или путь к каталогу профиля. Пусто — только ядро.
name = "{profile}"
'''


@dataclass
class Config:
    path: Path | None
    base: Path
    root: Path
    source_prefix: str
    index_dir: Path
    kb_path: Path
    bm25_path: Path
    registries: list = field(default_factory=list)
    archive_registries: list = field(default_factory=list)
    extensions: list = field(default_factory=lambda: list(DEFAULT_EXT))
    exclude: list = field(default_factory=list)
    max_size_mb: float = 0
    ocr: bool = True
    ocr_dpi: int = 300
    ocr_psm: int = 4
    ocr_workers: int = 4
    ocr_langs: str = "rus+eng"
    tables: bool = True
    wide_tables: bool = True
    bm25_window: int = 96
    bm25_overlap: int = 16
    synonyms: dict = field(default_factory=dict)
    fts_coverage: float = 0.75
    bm25_best_doc: float = 0.6
    bm25_miss: float = 0.2
    derived_sections: list = field(default_factory=list)
    rerank: bool = False
    profile: Profile = field(default_factory=Profile.empty)

    @property
    def default_registry(self) -> Path:
        return self.index_dir / "registry.csv"


def find_config(start: Path | None = None) -> Path | None:
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env).expanduser().resolve()
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / CONFIG_NAME).is_file():
            return d / CONFIG_NAME
    return None


def _p(base: Path, v: str) -> Path:
    p = Path(v).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def load(path: str | Path | None = None) -> Config:
    cfg_path = Path(path).expanduser().resolve() if path else find_config()
    if not cfg_path or not cfg_path.is_file():
        raise FileNotFoundError("не найден corpus.toml: выполните `ru-corpus init` или укажите --config")
    base = cfg_path.parent
    d = read_toml(cfg_path)
    c, ix, se, pr = d.get("corpus", {}), d.get("index", {}), d.get("search", {}), d.get("profile", {})
    if not c.get("root"):
        raise ValueError("corpus.toml: не задан [corpus] root")
    index_dir = _p(base, ix.get("dir", ".ru-corpus"))
    profile = Profile.load(pr.get("name", "")) if pr.get("name") else Profile.empty()
    synonyms = dict(profile.synonyms)
    if se.get("synonyms"):
        synonyms = load_synonyms(_p(base, se["synonyms"]))
    return Config(
        path=cfg_path, base=base, root=_p(base, c["root"]), source_prefix=c.get("source_prefix", ""),
        index_dir=index_dir,
        kb_path=_p(base, ix["kb"]) if ix.get("kb") else index_dir / "kb.sqlite",
        bm25_path=_p(base, ix["bm25"]) if ix.get("bm25") else index_dir / "bm25.sqlite",
        registries=[_p(base, x) for x in ix.get("registry", [])],
        archive_registries=[_p(base, x) for x in ix.get("archive_registry", [])],
        extensions=[e.lower() for e in ix.get("extensions", DEFAULT_EXT)],
        exclude=list(ix.get("exclude", ["**/.git/**", "**/node_modules/**", "**/.venv/**", "**/~$*"])),
        max_size_mb=float(ix.get("max_size_mb", 0)), ocr=bool(ix.get("ocr", True)),
        ocr_dpi=int(ix.get("ocr_dpi", 300)), ocr_psm=int(ix.get("ocr_psm", 4)),
        ocr_workers=int(ix.get("ocr_workers", 4)), ocr_langs=str(ix.get("ocr_langs", "rus+eng")),
        tables=bool(ix.get("tables", True)), wide_tables=bool(ix.get("wide_tables", True)),
        bm25_window=int(ix.get("bm25_window", 96)), bm25_overlap=int(ix.get("bm25_overlap", 16)),
        synonyms=synonyms, fts_coverage=float(se.get("fts_coverage", 0.75)),
        bm25_best_doc=float(se.get("bm25_best_doc", 0.6)), bm25_miss=float(se.get("bm25_miss", 0.2)),
        derived_sections=list(se.get("derived_sections", [])), rerank=bool(se.get("rerank", False)),
        profile=profile)


def write_template(dest: Path, root: str, prefix: str = "", profile: str = "") -> None:
    dest.write_text(TEMPLATE.format(root=root.replace("\\", "/"), prefix=prefix, profile=profile,
                                    profile_hint="tso_disclosure"), encoding="utf-8")
