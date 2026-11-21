# -*- coding: utf-8 -*-
"""Извлечение текста по страницам: PDF (текстовый слой, OCR сканов), DOCX, XLSX/XLS, PPTX, текст.

PDF: pdftotext (poppler), а без него — pdfplumber. Скан (текстового слоя почти нет) распознаётся
tesseract с определением ориентации страницы (OSD, затем повороты 180/90/270 по «похожести на русский
текст»). Страница XLSX — лист: строки «ячейка | ячейка», пустые ячейки на своих местах.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree as ET

from . import norm

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

MIN_CHARS_PER_PAGE = 100       # меньше — текстовый слой «плохой», страницу нужно распознавать
RU_WORD = re.compile(r"[А-Яа-яЁё]{3,}")
STOP = set("и в во не на по от для или при с со к у за из что это как год года руб".split())


class OcrUnavailable(RuntimeError):
    pass


def run(cmd, **kw):
    # errors="replace": tesseract --psm 0 пишет в stderr байты не в UTF-8
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


def ocr_ready(langs: str = "rus+eng") -> str | None:
    """None — OCR возможен; иначе причина."""
    if not shutil.which("tesseract"):
        return "не найден tesseract"
    have = set(run(["tesseract", "--list-langs"]).stdout.split())
    miss = [x for x in langs.split("+") if x not in have]
    if miss:
        return "у tesseract нет языков: " + ", ".join(miss)
    try:
        import PIL  # noqa: F401
    except ImportError:
        return "нужен Pillow: pip install 'ru-corpus-kit[ocr]'"
    if not shutil.which("pdftoppm"):
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            return "нужен pdftoppm (poppler) или pypdfium2: pip install 'ru-corpus-kit[ocr]'"
    return None


def pdf_text_layer(path: Path):
    """Страницы текстового слоя. -> список строк (без хвостовых пустых)."""
    if shutil.which("pdftotext"):
        r = run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"])
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:200])
        pages = [p.strip() for p in r.stdout.split("\f")]
    else:
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("для PDF нужен pdftotext (poppler) или pdfplumber") from None
        with pdfplumber.open(path) as d:
            pages = [(p.extract_text() or "").strip() for p in d.pages]
    while pages and not pages[-1]:
        pages.pop()
    return pages


def pdf_page_count(path: Path, fallback: int = 1) -> int:
    if shutil.which("pdfinfo"):
        m = re.search(r"^Pages:\s+(\d+)", run(["pdfinfo", str(path)]).stdout, re.M)
        if m:
            return int(m.group(1))
    try:
        import pypdfium2
        d = pypdfium2.PdfDocument(str(path))
        try:
            return len(d)
        finally:
            d.close()
    except Exception:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(path) as d:
            return len(d.pages)
    except Exception:
        return max(1, fallback)


def pdf_text(path: Path):
    """Текстовый слой -> (pages, method, нужен_ли_OCR)."""
    pages = pdf_text_layer(path)
    texty = sum(len(p) for p in pages)
    need = not pages or texty / len(pages) <= MIN_CHARS_PER_PAGE
    return pages, ("no-text" if need else "pdftotext"), need


# ---------------------------------------------------------------- OCR

def _score(txt):
    """«Похожесть на нормальный русский текст»: в перевёрнутом OCR мало частых слов."""
    words = re.findall(r"[а-яё]+", txt.lower())
    return sum(1 for w in words if w in STOP) * 2 + len(words) * 0.2


def _quality(txt):
    """Сравнение вариантов поворота: число слов, известных словарю, плюс частые слова.
    Мусор от перевёрнутого скана тоже содержит кириллицу, но почти не содержит настоящих слов."""
    words = [w.lower() for w in RU_WORD.findall(txt)]
    if norm._MORPH is None:
        return _score(txt)
    known = sum(1 for w in words if len(w) > 2 and norm._MORPH.word_is_known(w))
    return known * 2 + sum(1 for w in words if w in STOP)


def _known_ratio(txt):
    """Доля слов, известных морфологическому словарю: у повёрнутого скана падает ниже 0.6."""
    if norm._MORPH is None:
        return 1.0
    words = [w.lower() for w in RU_WORD.findall(txt)][:80]
    if not words:
        return 0.0
    return sum(1 for w in words if norm._MORPH.word_is_known(w)) / len(words)


def _render_pages(path: Path, td: Path, dpi: int, total: int):
    base = td / "p"
    if shutil.which("pdftoppm"):
        run(["pdftoppm", "-r", str(dpi), "-gray", "-png", "-f", "1", "-l", str(total), str(path), str(base)])
        return sorted(td.glob("p-*.png"))
    import pypdfium2
    out = []
    d = pypdfium2.PdfDocument(str(path))
    try:
        for i in range(min(total, len(d))):
            img = td / f"p-{i + 1:04d}.png"
            d[i].render(scale=dpi / 72).to_pil().convert("L").save(str(img))
            out.append(img)
    finally:
        d.close()
    return out


def ocr_pdf(path: Path, ocr_limit=None, dpi=300, psm=4, workers=4, langs="rus+eng",
            words_path: Path | None = None, tmp_dir: Path | None = None, log=None):
    """OCR PDF постранично -> список строк. 300 dpi + поворот по OSD + psm 4 — лучшая точность цифр."""
    why = ocr_ready(langs)
    if why:
        raise OcrUnavailable(why)
    from PIL import Image
    total = pdf_page_count(path)
    if ocr_limit is not None:
        total = min(total, ocr_limit)
    if tmp_dir:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    base_args = ["-l", langs, "--psm", str(psm), "-c", "preserve_interword_spaces=1"]
    if words_path:
        base_args += ["--user-words", str(words_path)]

    def tess(args, img):
        for k in range(3):                       # «image file not found» бывает плавающим
            r = run(["tesseract", str(img), "stdout"] + args)
            if r.returncode == 0 or "not found" not in (r.stderr or ""):
                return r
            time.sleep(1 + k)
        return r

    def osd_angle(img):
        """Угол по OSD; None, если OSD не уверен (короткий текст — частая ошибка на 180°)."""
        osd = tess(["--psm", "0"], img).stdout or ""
        m = re.search(r"Rotate:\s*(\d+)", osd)
        c = re.search(r"Orientation confidence:\s*([\d.]+)", osd)
        if not m:
            return None
        return int(m.group(1)) if (c is None or float(c.group(1)) >= 2.0) else None

    def ocr_at(img, angle):
        if not angle:
            return tess(base_args, img).stdout.strip()
        with Image.open(img) as im:
            rot = img.with_name(img.stem + f"_rot{angle}.png")
            im.rotate(-angle, expand=True).save(rot)
        try:
            return tess(base_args, rot).stdout.strip()
        finally:
            rot.unlink(missing_ok=True)

    def ocr_one(item):
        i, img = item
        try:
            a = osd_angle(img)
        except Exception:                        # OSD нужен не всегда (мало текста — tesseract отказывает)
            a = None
        # исходная ориентация всегда в кандидатах: OSD иногда ошибается и переворачивает нормальную страницу
        cands = {0: ocr_at(img, 0)}
        if a:
            cands[a] = ocr_at(img, a)
        best = max(cands, key=lambda k: _quality(cands[k]))
        txt = cands[best]
        if _score(txt) < 150 or _known_ratio(txt) < 0.6:
            for angle in (180, 90, 270):
                if angle in cands:
                    continue
                if angle != 180 and _score(txt) >= 60:
                    break
                cands[angle] = ocr_at(img, angle)
                if _quality(cands[angle]) > _quality(txt):
                    txt = cands[angle]
        return i, txt

    with tempfile.TemporaryDirectory(dir=tmp_dir) as td:
        imgs = _render_pages(path, Path(td), dpi, total)
        out = [""] * len(imgs)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for i, txt in ex.map(ocr_one, enumerate(imgs, 1)):
                out[i - 1] = txt
                if log:
                    log(f"    OCR {i}/{len(imgs)}")
    return out


# ---------------------------------------------------------------- офисные форматы

def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(W + "body")
    lines = []
    for el in (body if body is not None else root):
        if el.tag == W + "p":
            txt = "".join(t.text or "" for t in el.iter(W + "t"))
            if txt.strip():
                lines.append(txt.strip())
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                cells = ["".join(t.text or "" for t in tc.iter(W + "t")).strip()
                         for tc in tr.findall(W + "tc")]
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def _rows_to_text(rows):
    out = []
    for row in rows:
        # перенос строки внутри ячейки склеивается пробелом: иначе строка таблицы рвётся надвое
        vals = ["" if v is None else " ".join(str(v).split()) for v in row]
        while vals and vals[-1] == "":
            vals.pop()
        if any(vals):
            out.append(" | ".join(vals))
    return "\n".join(out)


def xlsx_pages(path: Path):
    """{"лист": "строка | ..."} — страница = имя листа; пустые ячейки сохраняются."""
    import openpyxl
    pages = {}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        pages[ws.title] = _rows_to_text(ws.iter_rows(values_only=True))
    wb.close()
    return pages


def xls_pages(path: Path):
    try:
        import xlrd
    except ImportError:
        xlrd = None
    if xlrd is not None:
        wb = xlrd.open_workbook(str(path))
        return {sh.name: _rows_to_text(sh.row_values(i) for i in range(sh.nrows)) for sh in wb.sheets()}
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("для .xls нужен xlrd (pip install 'ru-corpus-kit[office]') или LibreOffice")
    with tempfile.TemporaryDirectory() as td:
        r = run([soffice, "--headless", f"-env:UserInstallation={(Path(td) / 'lo').as_uri()}",
                 "--convert-to", "xlsx", "--outdir", td, str(path)], timeout=300)
        out = Path(td) / (path.stem + ".xlsx")
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("LibreOffice не смог конвертировать .xls")
        return xlsx_pages(out)


def pptx_pages(path: Path):
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("для .pptx нужен python-pptx: pip install 'ru-corpus-kit[office]'")
    pages = []
    for slide in Presentation(str(path)).slides:
        buf = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    txt = "".join(r.text for r in para.runs).strip()
                    if txt:
                        buf.append(txt)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    buf.append(" | ".join(c.text.strip() for c in row.cells))
        pages.append("\n".join(buf))
    return pages


def doc_via_soffice(path: Path) -> str:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("для .doc нужен LibreOffice (soffice)")
    with tempfile.TemporaryDirectory() as td:
        r = run([soffice, "--headless", f"-env:UserInstallation={(Path(td) / 'lo').as_uri()}",
                 "--convert-to", "docx", "--outdir", td, str(path)], timeout=300)
        out = Path(td) / (path.stem + ".docx")
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("LibreOffice не смог конвертировать .doc")
        return docx_text(out)


def extract(path: Path):
    """Файл -> ([(страница, текст)], метод, нужен_ли_OCR). PDF отдаёт текстовый слой; OCR — отдельным шагом."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        pages, method, need = pdf_text(path)
        return [(str(i + 1), p) for i, p in enumerate(pages)], method, need
    if ext == ".docx":
        return [("1", docx_text(path))], "docx-xml", False
    if ext in (".xlsx", ".xlsm"):
        return list(xlsx_pages(path).items()), "openpyxl", False
    if ext == ".xls":
        return list(xls_pages(path).items()), "xls", False
    if ext == ".pptx":
        return [(str(i + 1), p) for i, p in enumerate(pptx_pages(path))], "python-pptx", False
    if ext in (".txt", ".md", ".csv", ".json"):
        return [("1", path.read_text(encoding="utf-8", errors="replace"))], "text", False
    if ext == ".doc":
        return [("1", doc_via_soffice(path))], "libreoffice-docx", False
    raise RuntimeError(f"нет экстрактора для {ext}")
