# -*- coding: utf-8 -*-
"""Синтетический корпус для тестов: вымышленная организация «АО «Демо-Сеть»», вымышленные числа.

Файлы генерируются кодом (PDF — reportlab со шрифтом DejaVu Sans из tests/fonts/, сканы — Pillow,
XLSX — openpyxl, DOCX — python-docx), в репозитории нет ни одного документа.
Координаты в helper-ах — от верхнего левого угла страницы, в пунктах (как в разметке PDF-вьюеров).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import black
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_FILE = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
FONT = "DejaVuSans"
pdfmetrics.registerFont(TTFont(FONT, str(FONT_FILE)))


class Doc:
    """Тонкая обёртка над canvas reportlab: страницы разного размера, y — сверху вниз."""

    def __init__(self, path):
        self.c = canvas.Canvas(str(path))
        self._open = False
        self.w = self.h = 0

    def new_page(self, width=595, height=842, rotate=0):
        if self._open:
            self.c.showPage()
        self.w, self.h = width, height
        self.c.setPageSize((width, height))
        if rotate:
            self.c.setPageRotation(rotate)
        self._open = True
        return self

    def save(self):
        if self._open:
            self.c.showPage()
        self.c.save()


def _text(page, x, y, s, size=11, vertical=False):
    """Строка с базовой линией в (x, y); vertical — текст снизу вверх (повёрнут на 90°)."""
    c = page.c
    c.setFont(FONT, size)
    c.setFillColor(black)
    if vertical:
        c.saveState()
        c.translate(x, page.h - y)
        c.rotate(90)
        c.drawString(0, 0, s)
        c.restoreState()
    else:
        c.drawString(x, page.h - y, s)


def lines_page(doc, lines, size=11, landscape=False):
    page = doc.new_page(width=842 if landscape else 595, height=595 if landscape else 842)
    y = 60
    for ln in lines:
        _text(page, 50, y, ln, size)
        y += size * 1.9
    return page


def grid(page, cells, size=9, vertical_rows=()):
    """cells: [(x0, y0, x1, y1, текст)] — рамка ячейки + текст внутри.
    vertical_rows — набор y0 строк, текст которых пишется повёрнутым (шапка с вертикальными подписями)."""
    page.c.setStrokeColor(black)
    page.c.setLineWidth(0.6)
    for x0, y0, x1, y1, t in cells:
        page.c.rect(x0, page.h - y1, x1 - x0, y1 - y0, stroke=1, fill=0)
        if t:
            if y0 in vertical_rows:
                _text(page, x0 + 9, y1 - 4, t, size, vertical=True)
            else:
                _text(page, x0 + 3, y1 - 6, t, size)


def simple_table(page, x0, y0, widths, row_h, rows, size=9):
    cells, y = [], y0
    for row in rows:
        x = x0
        for w, t in zip(widths, row):
            cells.append((x, y, x + w, y + row_h, t))
            x += w
        y += row_h
    grid(page, cells, size)


def make_report(path: Path):
    """Годовой отчёт: текст со «сложным» числом, таблица с сеткой, таблица со ставками по уровням."""
    doc = Doc(path)
    lines_page(doc, [
        "АО «Демо-Сеть»",
        "Годовой отчёт за 2024 год",
        "Выручка от передачи электроэнергии составила 1 234 567,89 тыс. руб.",
        "Протяжённость кабельных линий 4 321 км, численность персонала 987 человек.",
        "Компания обслуживает подстанции и распределительные пункты города Демоград.",
        "Заключение раздела: показатели надёжности соответствуют плановым значениям.",
    ])
    p2 = lines_page(doc, ["Приложение № 2", "Таблица 1. Потери электроэнергии"])
    simple_table(p2, 50, 130, [220, 90, 90], 24, [
        ["Показатель", "2023", "2024"],
        ["Потери электроэнергии, млн кВт·ч", "112,4", "108,9"],
        ["Отпуск в сеть, млн кВт·ч", "5 400,0", "5 512,3"],
        ["Полезный отпуск, млн кВт·ч", "5 287,6", "5 403,4"],
    ])
    p3 = lines_page(doc, ["Таблица 2. Ставки на содержание сетей"])
    simple_table(p3, 50, 110, [200, 80, 80, 80, 90], 24, [
        ["Ставка", "ВН", "СН2", "НН", "Единица"],
        ["Ставка на содержание сетей", "1 234,5", "2 345,6", "3 456,7", "руб./МВт·мес."],
        ["Ставка на оплату потерь", "456,1", "567,2", "678,3", "руб./МВт·ч"],
    ])
    doc.save()


def make_wide(path: Path, page_rotate: int = 0, vertical_years: bool = False):
    """Приказ с широкой альбомной таблицей: объединённая шапка «Финансирование» над пятью годами.

    page_rotate=90 — таблица на листе с атрибутом /Rotate 90 (в файле лист книжный, показывается альбомным);
    vertical_years — подписи лет в шапке повёрнуты на 90° (в высокой строке шапки)."""
    doc = Doc(path)
    lines_page(doc, [
        "ПРИКАЗ",
        "от 01.12.2024 № 77-ТР",
        "Об утверждении инвестиционной программы АО «Демо-Сеть» на 2025–2029 годы",
        "Приложение № 1. План финансирования мероприятий.",
    ], landscape=True)
    vh = 36 if vertical_years else 0                     # добавочная высота строки лет
    if page_rotate == 90:
        page = doc.new_page(width=842, height=595, rotate=90)   # reportlab принимает размер показанной страницы
        page.c.transform(0, 1, -1, 0, 595, 0)            # дальше рисуем в системе показанной (альбомной) страницы
    else:
        page = doc.new_page(width=842, height=595)
    _text(page, 30, 40, "Таблица 3. План финансирования инвестиционной программы", 10)
    x = 30
    cols = [(x, x + 40), (x + 40, x + 270)]
    year_x0 = x + 270
    years = [str(y) for y in range(2025, 2030)]
    ycols = [(year_x0 + 70 * i, year_x0 + 70 * (i + 1)) for i in range(5)]
    tot = (year_x0 + 350, year_x0 + 430)
    cells = [
        (cols[0][0], 60, cols[0][1], 100 + vh, "№ п/п"),
        (cols[1][0], 60, cols[1][1], 100 + vh, "Наименование мероприятия"),
        (ycols[0][0], 60, ycols[-1][1], 80, "Финансирование, тыс. руб."),
        (tot[0], 60, tot[1], 100 + vh, "Итого"),
    ]
    cells += [(a, 80, b, 100 + vh, y) for (a, b), y in zip(ycols, years)]
    nums = ["1", "2", "3", "4", "5", "6", "7", "8"]
    allc = [cols[0], cols[1]] + ycols + [tot]
    cells += [(a, 100 + vh, b, 116 + vh, n) for (a, b), n in zip(allc, nums)]
    data = [
        ("1.1", "Строительство подстанции ПС-1", ["100,5", "200,0", "300,0", "400,0", "500,0", "1 500,5"]),
        ("1.2", "Реконструкция кабельных линий", ["50,0", "60,0", "70,0", "80,0", "90,0", "350,0"]),
        ("1.3", "Установка приборов учёта", ["10,0", "20,0", "30,0", "40,0", "50,0", "150,0"]),
    ]
    y = 116 + vh
    for no, name, vals in data:
        row = [no, name] + vals
        cells += [(a, y, b, y + 22, t) for (a, b), t in zip(allc, row)]
        y += 22
    grid(page, cells, 9, vertical_rows=(80,) if vertical_years else ())
    doc.save()


def make_scan(path: Path, rotate: int = 0):
    """Скан: страница-картинка без текстового слоя; rotate — повернуть картинку (90/180/270)."""
    from PIL import Image, ImageDraw, ImageFont
    dpi, k = 200, 200 / 72
    img = Image.new("L", (round(595 * k), round(842 * k)), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT_FILE), round(30 * k))
    y = 150
    for ln in ["Договор поставки кабеля", "заключён пятнадцатого июня", "между поставщиком и сетевой компанией"]:
        d.text((round(60 * k), round(y * k)), ln, font=font, fill=0, anchor="ls")
        y += 70
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor=255)
    img.save(str(path), "PDF", resolution=dpi)


def make_xlsx(path: Path, scale: float = 1.0):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Реестр"
    ws.append(["Реестр объектов АО «Демо-Сеть»"])
    ws.append([])
    ws.append(["№", "Наименование объекта", "Мощность, кВт", "Стоимость, тыс. руб."])
    rows = [
        (1, "Подстанция ПС-1", 100, 1000.5),
        (2, "Подстанция ПС-2", 250.5, 2500),
        (3, "Кабельная линия КЛ-1", 75, 750.25),
        (4, "Кабельная линия КЛ-2", 400, 4000),
        (5, "Распределительный пункт РП-5", 124.5, 1249.25),
    ]
    for n, name, p, c in rows:
        ws.append([n, name, p * scale, c])
    ws.append(["Итого", "", sum(r[2] for r in rows) * scale, sum(r[3] for r in rows)])
    ws2 = wb.create_sheet("Пояснения")
    ws2.append(["Реестр составлен по состоянию на конец отчётного периода."])
    wb.save(path)


def make_docx(path: Path):
    import docx
    d = docx.Document()
    d.add_paragraph("Служебная записка. Закупка трансформаторов")
    d.add_paragraph("Договор № 15 от 05.05.2024 на поставку трансформаторов мощностью 630 кВА.")
    t = d.add_table(rows=2, cols=3)
    for i, v in enumerate(["Позиция", "Количество", "Цена, руб."]):
        t.cell(0, i).text = v
    for i, v in enumerate(["Трансформатор ТМГ-630", "4", "2 100 000"]):
        t.cell(1, i).text = v
    d.save(str(path))


def make_corpus(root: Path, scan: bool = True, docx_ok: bool = True) -> dict:
    """Создаёт корпус; возвращает {имя: путь}."""
    files = {}
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "tariffs").mkdir(exist_ok=True)
    (root / "registers").mkdir(exist_ok=True)
    (root / "notes").mkdir(exist_ok=True)
    files["report"] = root / "reports" / "otchet_2024.pdf"
    make_report(files["report"])
    files["wide"] = root / "tariffs" / "prikaz_77_2025.pdf"
    make_wide(files["wide"])
    files["xlsx"] = root / "registers" / "reestr_2024.xlsx"
    make_xlsx(files["xlsx"])
    files["txt"] = root / "notes" / "pamyatka.txt"
    files["txt"].write_text("Памятка. Необходимая валовая выручка организации на 2025 год "
                            "составляет 777 000 тыс. руб. (вымышленное значение).", encoding="utf-8")
    if docx_ok:
        files["docx"] = root / "notes" / "zapiska.docx"
        make_docx(files["docx"])
    if scan:
        (root / "scans").mkdir(exist_ok=True)
        files["scan"] = root / "scans" / "skan_dogovor.pdf"
        make_scan(files["scan"])
    return files
