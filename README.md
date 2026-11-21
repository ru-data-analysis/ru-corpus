**Русский** · [English](README.en.md) · [中文](README.zh.md)

# ru-corpus

## Что это

Русский поиск и проверяемая аналитика по корпусу документов — массиву данных и информации (PDF, сканы,
таблицы, архивы), по которому работает ИИ-агент. Каждая цифра приходит с документом и страницей, а там,
где ответа нет, агент честно говорит «в корпусе нет». Всё работает локально: индекс лежит рядом с документами.

## Состав

- `packages/ru-corpus-kit` — ядро на Python: индексация и команда `ru-corpus` (init, index, status, search,
  page, table, doc, number, aggregate, calc); поиск BM25 по леммам, OCR сканов, таблицы с графами и годами;
- `packages/dsh-ru-corpus` — плагин DeepSeek Harness (DSH): методика в системном промте и семь инструментов
  `corpus_*` поверх `ru-corpus`;
- `skills/russian-corpus-search` и `skills/corpus-analytics-ru` — навыки `SKILL.md`: русский поиск и
  методика проверяемой аналитики; отраслевой справочник по раскрытию информации сетевых организаций —
  `skills/corpus-analytics-ru/references/tso-disclosure.md`;
- `plugins/claude-ru-corpus` — плагин Claude Code с копиями навыков (обновляются скриптом
  `scripts/sync_claude_plugin.py`); `.claude-plugin/marketplace.json` — маркетплейс;
- `demo` — демо-корпус из 15 официальных актов и 6 контрольных вопросов.

## Быстрый старт

Нужен Python 3.10+. Для сканов — `tesseract` с языком `rus`, для текста PDF — `pdftotext` из poppler
(`brew install poppler tesseract tesseract-lang` или `apt install poppler-utils tesseract-ocr tesseract-ocr-rus`).

```bash
pip install "ru-corpus-kit[tables,ocr] @ git+https://github.com/ru-data-analysis/ru-corpus#subdirectory=packages/ru-corpus-kit"
ru-corpus init --root ./документы --prefix "корпус/"    # создаёт corpus.toml
ru-corpus index                                         # индекс: текст, OCR, леммы, таблицы
ru-corpus search "выручка за 2024 год"                  # доказательства: файл, страница, фрагмент
ru-corpus number d0001 1 "1 234 567,89"                 # стоит ли число дословно на странице
```

Имя пакета на PyPI — `ru-corpus-kit` (после публикации: `pip install "ru-corpus-kit[tables,ocr]"`). Без extras
ставится только ядро. Об `[tables]` и `[ocr]`: это pdfplumber, pypdfium2 и Pillow, все под пермиссивными лицензиями.

### Подключение к агенту

DeepSeek Harness:

```bash
dsh plugin --profile web add "file:/путь/к/ru-corpus/packages/dsh-ru-corpus"
```

Claude Code:

```text
/plugin marketplace add ru-data-analysis/ru-corpus
/plugin install ru-corpus@ru-corpus
```

Навыки `SKILL.md` для любого агента (skills.sh):

```bash
npx skills add ru-data-analysis/ru-corpus
```

Инструменты и навыки вызывают команду `ru-corpus`, поэтому ядро нужно установить в любом случае. Они работают
в папке сессии, в которой или выше которой лежит `corpus.toml`. Настройки плагина DSH и проверка без DSH —
в `packages/dsh-ru-corpus/README.md`.

## Демо-корпус и проверка

`demo/` — 15 официальных актов органов власти по электроэнергетике и тарифам (не объекты авторского права,
п. 6 ст. 1259 ГК РФ; источники и SHA-256 — в `demo/corpus/MANIFEST.csv`) плюс вымышленный синтетический набор,
который создаёт генератор. К корпусу приложены 5 вопросов с проверенными ответами и одна ловушка («в корпусе нет»).

```bash
pip install -e "packages/ru-corpus-kit[tables,ocr,test]"
python3 demo/make_synthetic.py                             # синтетика
cd demo && ru-corpus index && python3 check_questions.py   # ожидается: 6/6 вопросов прошли
```

Прочие проверки: `python3 scripts/scrub_check.py` (вычистка), `python3 scripts/sync_claude_plugin.py --check`
(копии навыков), `pytest packages/ru-corpus-kit/tests`, `node packages/dsh-ru-corpus/test/mock-host.mjs`.

## Ограничения

- **Лицензии зависимостей.** Все Python-зависимости (включая extras) — под пермиссивными лицензиями (MIT, BSD,
  Apache-2.0); AGPL-компонентов нет. Копилефт (GPL) только у внешней программы poppler, которая вызывается как
  отдельный процесс и не входит в дистрибутив. Подробности — в [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
- OCR — tesseract: на плохих сканах и рукописных вставках числа искажаются, поэтому каждое число проверяется
  командой `ru-corpus number`.
- Отказ «в корпусе нет» зависит от лексического пересечения вопроса с корпусом: широкая формулировка с общими
  словами может получить ложное «есть доказательства» (зафиксировано в `demo/README.md`).
- В комплекте один отраслевой профиль — `tso_disclosure` (раскрытие информации сетевых организаций); для другой
  отрасли нужен свой профиль (`[profile]` в `corpus.toml`).
- Плагин DSH рассчитан на `@deepseek-ai/dsh-tools >=0.2.0-rc.2 <0.3.0`; публикации в npm и PyPI пока нет.

## Лицензия

Apache-2.0 (см. `LICENSE`, `NOTICE`); лицензии зависимостей — в [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

Сделано с помощью Claude (Anthropic).

## Внедрение и поддержка

Помощь с внедрением, настройкой профилей под вашу отрасль и поддержкой — через issues репозитория.
