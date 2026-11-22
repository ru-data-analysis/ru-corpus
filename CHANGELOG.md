# Изменения

## dsh-ru-corpus 0.1.1 — 21.11.2026

- Диапазон `@deepseek-ai/dsh-tools` в peerDependencies принимает предварительные сборки DSH 0.2.x (в т. ч. 0.2.2-rc.*): прежний `>=0.2.0-rc.2 <0.3.0` их исключал.

## Не выпущено

- Навыки процесса анализа поверх корпуса (скрипты на стандартной библиотеке Python, тесты в `tests/skills`, CI-задание `skills`): `analysis-spec-first` (спецификация с правилом решения до прогона, рабочий отчёт `.run.md`, проверка форматных ворот), `insight-registry` (реестр выводов, идемпотентная загрузка из отчёта, автогенерируемый `KNOWLEDGE.md`, отдельный слой курируемых документов, пометка выводов к перепроверке при смене документов), `corpus-cluster-orchestrator` (многоагентная кластеризация набора документов с проверкой цитат), `corpus-manifest` (снимок корпуса с SHA-256, сравнение снимков, проверка неизменности), `period-comparability` (реестр разрывов методики, формы, охвата и единиц между периодами), `source-classes` (класс происхождения и качество текста источника, ворота для точных выводов, признак текстового слоя PDF `textlayer`, режимы `--allow-ocr` и `--allow-unknown-quality`), `leak-check` (проверка выходных артефактов анализа на грифы, закрытые имена, пути и длинные цитаты), `cost-log` (журнал затрат прогона). Навыки добавлены в плагин Claude Code и в `scripts/sync_claude_plugin.py`.

- **PyMuPDF (AGPL-3.0) полностью убрана из пакета** `ru-corpus-kit`: ни в зависимостях, ни в extras, ни в тестах. Широкие таблицы PDF (`wide.py`) разбираются на pdfplumber (линейки и прямоугольники сетки) и pypdfium2 (слова с координатами, учёт /Rotate страницы и повёрнутых подписей граф); алгоритм и формат ячеек прежние. Резервное чтение текста PDF — pdfplumber, растеризация для OCR без poppler — pypdfium2. Extras: `[tables]` — pdfplumber + pypdfium2, `[ocr]` — Pillow + pypdfium2, `[test]` — pytest, reportlab, python-docx, Pillow, pdfplumber, pypdfium2.
- Тесты: PDF генерирует reportlab со шрифтом DejaVu Sans (`tests/fonts/`, лицензия рядом), сканы рисует Pillow; новые проверки — лист с /Rotate 90 и повёрнутые подписи лет в шапке. CI проверяет, что PyMuPDF в окружение не попала.
- `THIRD_PARTY_LICENSES.md` и README (ru/en/zh): оговорка об AGPL заменена описанием пермиссивных зависимостей; добавлены reportlab и шрифт DejaVu.
- README на трёх языках (`README.md`, `README.en.md`, `README.zh.md`) с переключателем; разделы «Демо-корпус и проверка», «Ограничения», «Внедрение и поддержка».
- `THIRD_PARTY_LICENSES.md`: лицензии зависимостей ядра и extras, внешних программ (poppler — GPL, tesseract — Apache-2.0), модели rerank (MIT), npm-зависимостей плагина.
- Плагин Claude Code вынесен в `plugins/claude-ru-corpus` (манифест плагина и копии навыков), маркетплейс указывает на него: при установке больше не копируется весь репозиторий с демо-корпусом. `scripts/sync_claude_plugin.py` обновляет копии, `--check` в CI проверяет, что они не разошлись с `skills/`.
- Проверена чистая установка из пути (не `-e`) в новое venv с extras `[tables,ocr]`: демо — 6/6 вопросов; плагин DSH виден в изолированном `DSH_HOME`.

- `packages/dsh-ru-corpus`: плагин DeepSeek Harness (npm `dsh-ru-corpus`) — раздел системного промта с методикой и семь инструментов `corpus_*` поверх команды `ru-corpus`; подсказка «ru-corpus init && ru-corpus index», если нет `corpus.toml`; тест с заглушкой хоста на синтетическом корпусе; CI-задание `plugin` на ubuntu и macos.
- `skills/russian-corpus-search` 1.2.0: обобщённый навык русского поиска (команды `ru-corpus`, `scripts/check_env.py`, справочник по поиску, OCR и оценке); kb-rag — необязательный внешний плагин.
- `skills/corpus-analytics-ru`: общая методика проверяемой аналитики по корпусу и справочник `references/tso-disclosure.md` по раскрытию информации сетевых организаций.
- `.claude-plugin/marketplace.json`: маркетплейс плагинов Claude Code с обоими навыками.
- README: разделы «Для DeepSeek Harness», «Для Claude Code», «Навыки SKILL.md».

- `packages/ru-corpus-kit`: ядро инструментов корпуса — команда `ru-corpus` (init, index, status, search, page, table, doc, number, aggregate, calc), `corpus.toml`, профиль `tso_disclosure`, тесты на синтетическом корпусе, CI с pytest на ubuntu и macos.

- Каркас репозитория: лицензия Apache-2.0, структура, проверка вычистки в CI.
