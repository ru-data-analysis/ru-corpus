# claude-ru-corpus

Плагин Claude Code `ru-corpus`: навыки поиска и аналитики (`russian-corpus-search`, `corpus-analytics-ru`)
и навыки процесса анализа (`analysis-spec-first`, `insight-registry`, `corpus-cluster-orchestrator`,
`corpus-manifest`, `period-comparability`, `source-classes`, `leak-check`, `cost-log`).

Установка:

```text
/plugin marketplace add ru-data-analysis/ru-corpus
/plugin install ru-corpus@ru-corpus
```

Папка `skills/` здесь — копии из `skills/` в корне репозитория; не правьте их вручную.
Обновление: `python3 scripts/sync_claude_plugin.py` (в CI — `--check`).
Ядро (`pip install ru-corpus-kit`) и описание — в [корневом README](../../README.md).
