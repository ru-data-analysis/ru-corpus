# Изменения

## Не выпущено

- README на трёх языках (`README.md`, `README.en.md`, `README.zh.md`) с переключателем; разделы «Демо-корпус и проверка», «Ограничения», «Внедрение и поддержка».
- `THIRD_PARTY_LICENSES.md`: лицензии зависимостей ядра и extras, внешних программ (poppler — GPL, tesseract — Apache-2.0), модели rerank (MIT), npm-зависимостей плагина; оговорка об AGPL-3.0 у PyMuPDF.
- Плагин Claude Code вынесен в `plugins/claude-ru-corpus` (манифест плагина и копии навыков), маркетплейс указывает на него: при установке больше не копируется весь репозиторий с демо-корпусом. `scripts/sync_claude_plugin.py` обновляет копии, `--check` в CI проверяет, что они не разошлись с `skills/`.
- `packages/ru-corpus-kit`: PyMuPDF в extras ограничена версией `<2` (линия 2.x тянет `pymupdf4llm`, `pymupdf-layout`, `onnxruntime`).
- Проверена чистая установка из пути (не `-e`) в новое venv с extras `[tables,ocr]`: демо — 6/6 вопросов; плагин DSH виден в изолированном `DSH_HOME`.

- `packages/dsh-ru-corpus`: плагин DeepSeek Harness (npm `dsh-ru-corpus`) — раздел системного промта с методикой и семь инструментов `corpus_*` поверх команды `ru-corpus`; подсказка «ru-corpus init && ru-corpus index», если нет `corpus.toml`; тест с заглушкой хоста на синтетическом корпусе; CI-задание `plugin` на ubuntu и macos.
- `skills/russian-corpus-search` 1.2.0: обобщённый навык русского поиска (команды `ru-corpus`, `scripts/check_env.py`, справочник по поиску, OCR и оценке); kb-rag — необязательный внешний плагин.
- `skills/corpus-analytics-ru`: общая методика проверяемой аналитики по корпусу и справочник `references/tso-disclosure.md` по раскрытию информации сетевых организаций.
- `.claude-plugin/marketplace.json`: маркетплейс плагинов Claude Code с обоими навыками.
- README: разделы «Для DeepSeek Harness», «Для Claude Code», «Навыки SKILL.md».

- `packages/ru-corpus-kit`: ядро инструментов корпуса — команда `ru-corpus` (init, index, status, search, page, table, doc, number, aggregate, calc), `corpus.toml`, профиль `tso_disclosure`, тесты на синтетическом корпусе, CI с pytest на ubuntu и macos.

- Каркас репозитория: лицензия Apache-2.0, структура, проверка вычистки в CI.
