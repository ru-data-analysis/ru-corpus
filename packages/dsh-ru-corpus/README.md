# dsh-ru-corpus

> Обзор проекта, быстрый старт и лицензии — в корневом [README](../../README.md) ([English](../../README.en.md), [中文](../../README.zh.md)).

Плагин DeepSeek Harness для работы с корпусом документов на русском языке.
Даёт агенту две вещи:

- **раздел системного промта «Методика аналитики по корпусу документов»**: план до поиска, провенанс
  (файл, страница, раздел у каждой цифры), проверка каждой цифры, план/факт и единицы, сканы,
  честное «в корпусе нет», никакой арифметики в уме;
- **семь инструментов** поверх команды `ru-corpus` из [ru-corpus-kit](../ru-corpus-kit): `corpus_search`,
  `corpus_page`, `corpus_table`, `corpus_doc`, `corpus_number`, `corpus_aggregate`, `corpus_calc`.
  Каждый вызов — отдельный процесс, ответ — один JSON.

## Установка

1. Ядро (Python 3.10+):

   ```bash
   pip install -e "packages/ru-corpus-kit[tables]"      # из клона репозитория
   ```

2. Корпус — в папке с документами:

   ```bash
   ru-corpus init --root ./документы --prefix "корпус/"
   ru-corpus index
   ```

3. Плагин (пока из локальной папки):

   ```bash
   dsh plugin --profile web add link:/путь/к/ru-corpus/packages/dsh-ru-corpus
   ```

   Когда пакет будет опубликован: `dsh plugin --profile web add dsh-ru-corpus`.

Инструменты работают, если в папке сессии или выше лежит `corpus.toml`. Иначе они отвечают подсказкой
«ru-corpus init && ru-corpus index», а `corpus_calc` (арифметика) работает и без корпуса.

## Настройки (`cordis.patch.yml`)

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `enabled` | `true` | `false` — не монтировать ничего |
| `command` | `ru-corpus` | команда ядра, можно с аргументами: `python3 -m ru_corpus_kit.cli` |
| `config` | пусто | путь к `corpus.toml`; пусто — поиск вверх от папки сессии или `RU_CORPUS_CONFIG` |
| `timeoutMs` | `180000` | потолок одного вызова |

## Проверка без DSH

```bash
node test/mock-host.mjs
```

Тест создаёт во временной папке синтетический корпус (генератор `packages/ru-corpus-kit/tests/synth.py`),
выполняет `ru-corpus init` и `index`, затем проверяет все семь инструментов, контракт рендера
(`[{type: "text", text}]`), подсказки при отсутствии корпуса и команды. Нужны `node` 22+, `python3` и
установленный `ru-corpus-kit[tables]`.

Лицензия — Apache-2.0.
