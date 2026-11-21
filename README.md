# ru-corpus

Русский поиск и проверяемая аналитика по корпусу документов — массиву данных и информации (PDF, сканы,
таблицы, архивы), по которому работает агент. Каждая цифра — с документом и страницей, а там, где ответа нет,
честное «в корпусе нет».

Состав:

- `packages/ru-corpus-kit` — ядро на Python: индексация и команда `ru-corpus` (init, index, status, search,
  page, table, doc, number, aggregate, calc); см. README пакета;
- `packages/dsh-ru-corpus` — плагин DeepSeek Harness: методика в системном промте и семь инструментов
  `corpus_*` поверх `ru-corpus`;
- `skills/russian-corpus-search` — навык SKILL.md: русский поиск по локальному корпусу (леммы, синонимы,
  OCR сканов, таблицы);
- `skills/corpus-analytics-ru` — навык SKILL.md: методика проверяемой аналитики по корпусу; отраслевой
  справочник по раскрытию информации сетевых организаций лежит в `references/tso-disclosure.md`;
- `.claude-plugin/marketplace.json` — маркетплейс плагинов Claude Code с обоими навыками.

## Начало работы: ядро и корпус

Инструменты агента вызывают команду `ru-corpus`, поэтому ядро нужно установить в любом случае (Python 3.10+):

```bash
git clone https://github.com/ru-data-analysis/ru-corpus && cd ru-corpus
pip install -e "packages/ru-corpus-kit[tables]"      # + [ocr] для сканов (нужен tesseract с rus)

cd папка-проекта
ru-corpus init --root ./документы --prefix "корпус/"   # создаёт corpus.toml
ru-corpus index                                        # индекс документов
ru-corpus search "выручка за 2024 год"                 # проверка
```

Инструменты работают в папке сессии, в которой или выше которой лежит `corpus.toml`.

## Для DeepSeek Harness

Плагин `dsh-ru-corpus` добавляет раздел системного промта с методикой и инструменты `corpus_search`,
`corpus_page`, `corpus_table`, `corpus_doc`, `corpus_number`, `corpus_aggregate`, `corpus_calc`.

```bash
# пока из локальной папки клона
dsh plugin --profile web add link:/путь/к/ru-corpus/packages/dsh-ru-corpus

# после публикации в npm
dsh plugin --profile web add dsh-ru-corpus
```

Настройки (`command`, `config`, `timeoutMs`, `enabled`) и проверка без DSH (`node test/mock-host.mjs`) —
в `packages/dsh-ru-corpus/README.md`.

## Для Claude Code

```text
/plugin marketplace add ru-data-analysis/ru-corpus
/plugin install ru-corpus@ru-corpus
```

Плагин ставит оба навыка: `russian-corpus-search` и `corpus-analytics-ru`. Команды `ru-corpus` навыки
вызывают из консоли, поэтому ядро (раздел выше) должно быть установлено.

## Навыки SKILL.md

Навыки — обычные папки со `SKILL.md`, их читают разные агенты:

```bash
npx skills add ru-data-analysis/ru-corpus
```

Или скопируйте `skills/russian-corpus-search` и `skills/corpus-analytics-ru` в каталог навыков своего агента.

## Лицензия и проверки

Лицензия — Apache-2.0 (см. `LICENSE`, `NOTICE`). Сделано с помощью Claude (Anthropic).

Проверка вычистки: `python3 scripts/scrub_check.py` (запускается в CI на каждый push). Тесты ядра: `pytest packages/ru-corpus-kit/tests`; плагина: `node packages/dsh-ru-corpus/test/mock-host.mjs`.
