# Изменения

## Не выпущено

- `packages/dsh-ru-corpus`: плагин DeepSeek Harness (npm `dsh-ru-corpus`) — раздел системного промта с методикой и семь инструментов `corpus_*` поверх команды `ru-corpus`; подсказка «ru-corpus init && ru-corpus index», если нет `corpus.toml`; тест с заглушкой хоста на синтетическом корпусе; CI-задание `plugin` на ubuntu и macos.
- `skills/russian-corpus-search` 1.2.0: обобщённый навык русского поиска (команды `ru-corpus`, `scripts/check_env.py`, справочник по поиску, OCR и оценке); kb-rag — необязательный внешний плагин.
- `skills/corpus-analytics-ru`: общая методика проверяемой аналитики по корпусу и справочник `references/tso-disclosure.md` по раскрытию информации сетевых организаций.
- `.claude-plugin/marketplace.json`: маркетплейс плагинов Claude Code с обоими навыками.
- README: разделы «Для DeepSeek Harness», «Для Claude Code», «Навыки SKILL.md».

- `packages/ru-corpus-kit`: ядро инструментов корпуса — команда `ru-corpus` (init, index, status, search, page, table, doc, number, aggregate, calc), `corpus.toml`, профиль `tso_disclosure`, тесты на синтетическом корпусе, CI с pytest на ubuntu и macos.

- Каркас репозитория: лицензия Apache-2.0, структура, проверка вычистки в CI.
