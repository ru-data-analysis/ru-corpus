// dsh-ru-corpus — методика аналитики и инструменты корпуса для агента DeepSeek Harness.
//
// Регистрирует раздел системного промта (lib/prompt.js) и семь инструментов corpus_*
// поверх установленной команды `ru-corpus` (пакет ru-corpus-kit). Каждый вызов — отдельный
// процесс, результат — один JSON-объект. Работает в папке сессии, в которой или выше которой
// лежит corpus.toml; иначе инструмент отвечает подсказкой «ru-corpus init && ru-corpus index».
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { METHOD_PROMPT } from "./prompt.js";

const name = "ru-corpus";
const inject = ["tools", "systemPrompt", "subprocess"];

const DEFAULTS = { enabled: true, command: "ru-corpus", config: "", timeoutMs: 180000 };

const HINT_NO_CONFIG = "в папке сессии и выше нет corpus.toml — корпус не подключён. "
  + "Выполните в папке с документами: ru-corpus init && ru-corpus index "
  + "(или задайте путь к corpus.toml в настройке config / переменной RU_CORPUS_CONFIG).";
const HINT_NO_COMMAND = "команда ru-corpus не найдена. Установите ядро: pip install ru-corpus-kit "
  + "(или задайте настройку command, например «python3 -m ru_corpus_kit.cli»).";

function workspaceOf(ctx, exec) {
  try {
    const cwd = exec && exec.agent && exec.agent.session && exec.agent.session.header
      ? exec.agent.session.header.cwd : undefined;
    if (typeof cwd === "string" && cwd.length > 0) return cwd;
  } catch (e) { /* fall through */ }
  const sp = ctx.get ? ctx.get("sandboxPolicy") : undefined;
  if (sp && typeof sp.workspaceRoot === "string" && sp.workspaceRoot.length > 0) return sp.workspaceRoot;
  return process.cwd();
}

// corpus.toml в папке сессии или выше (как ищет сама команда ru-corpus).
function hasCorpusConfig(root, explicit) {
  if (explicit) return existsSync(explicit);
  if (process.env.RU_CORPUS_CONFIG) return existsSync(process.env.RU_CORPUS_CONFIG);
  let dir = root;
  for (;;) {
    if (existsSync(join(dir, "corpus.toml"))) return true;
    const up = dirname(dir);
    if (up === dir) return false;
    dir = up;
  }
}

function readText(handle, key) {
  try { return handle.collected[key] !== undefined ? handle.collected[key].readFrom(0).text : ""; }
  catch (e) { return ""; }
}

// Хост ждёт массив частей [{type:"text", text}], а не строку: со строкой вызов падает
// с «content.some is not a function».
function renderJson(_args, value) {
  const text = value && value.ok === false
    ? "Ошибка: " + (value.error || "неизвестно")
    : "```json\n" + JSON.stringify(value, null, 1).slice(0, 60000) + "\n```";
  return [{ type: "text", text }];
}

function apply(ctx, config) {
  const cfg = Object.assign({}, DEFAULTS, config || {});
  if (cfg.enabled === false) return;
  const subprocess = ctx.get("subprocess");
  const commandParts = String(cfg.command || DEFAULTS.command).trim().split(/\s+/).filter(Boolean);

  // needsCorpus=false — подкоманда не читает индекс (calc)
  async function run(argv, exec, needsCorpus = true) {
    const root = workspaceOf(ctx, exec);
    const explicit = cfg.config ? (cfg.config.startsWith("/") ? cfg.config : join(root, cfg.config)) : "";
    if (needsCorpus && !hasCorpusConfig(root, explicit)) return { ok: false, error: HINT_NO_CONFIG };
    let exe = commandParts[0];
    try { exe = await subprocess.resolveExecutable(exe, undefined, exec && exec.signal); }
    catch (e) { /* bare name */ }
    const full = commandParts.slice(1).concat(explicit && needsCorpus ? ["--config", explicit] : [], argv);
    let handle;
    try {
      handle = subprocess.spawn({
        argv: [exe].concat(full),
        cwd: root,
        stdio: { stdin: "ignore", stdout: { maxBytes: 8 * 1024 * 1024 }, stderr: { maxBytes: 256 * 1024 } },
        graceMs: cfg.timeoutMs,
      });
    } catch (e) {
      return { ok: false, error: HINT_NO_COMMAND + " (" + String(e && e.message || e) + ")" };
    }
    const outcome = await handle.done;
    const stdout = readText(handle, "stdout").trim();
    const last = stdout.split("\n").filter(Boolean).pop() || "";
    try {
      return JSON.parse(last);
    } catch (e) {
      const err = String(readText(handle, "stderr"));
      const code = outcome && outcome.exitCode;
      const missing = code === 127 || code === -2 || /ENOENT|not found|No such file|не найден/i.test(err) && !last;
      return {
        ok: false,
        error: missing ? HINT_NO_COMMAND : "код " + code + ": " + err.trim().slice(-800),
      };
    }
  }

  const out = { schema: { type: "json" }, render: renderJson };
  const reg = (spec) => ctx.effect(() => ctx.tools.register(defineTool(Object.assign({ output: out }, spec))),
    "ru-corpus: " + spec.name);

  reg({
    name: "corpus_search",
    description: "Поиск по корпусу документов (леммы русского языка, FTS5 + BM25) с единым провенансом: "
      + "файл источника, страница, раздел, фрагмент. "
      + "Если обе ветки поиска отказали — verdict «в корпусе нет». Запрос из одного числа («12 345,67») ищет его по всем страницам "
      + "без учёта разделителей тысяч и десятичного знака. Первичные документы идут выше производных отчётов. "
      + "Первый вызов может занять несколько секунд (открывает индекс).",
    parameters: {
      query: { type: "string", required: true, description: "Вопрос или ключевые слова по-русски." },
      n: { type: "integer", description: "Сколько доказательств вернуть (по умолчанию 5)." },
    },
    async execute(args, exec) {
      return run(["search", String(args.query), "--n", String(args.n || 5)], exec);
    },
  });

  reg({
    name: "corpus_page",
    description: "Точный текст страницы документа корпуса + путь к файлу, раздел, метод извлечения (ocr=true — скан), sha256 и origin. "
      + "Поле text передавай в evidence_add как content, поле origin — как origin.",
    parameters: {
      doc: { type: "string", required: true, description: "Идентификатор документа, например d0001." },
      page: { type: "string", required: true, description: "Метка страницы: номер «3», таблица «3/т1», лист Excel «Реестр»." },
      max_chars: { type: "integer", description: "Обрезать текст до N знаков (по умолчанию 20000)." },
    },
    async execute(args, exec) {
      return run(["page", String(args.doc), String(args.page), "--max-chars", String(args.max_chars || 20000)], exec);
    },
  });

  reg({
    name: "corpus_table",
    description: "Ячейки таблиц с измерениями: подпись строки, год, уровень (если задан профилем), полугодие (I/II), единица, "
      + "якорь «стр. N, таблица K, строка r, графа …». Для точных цифр из таблиц: ставок, показателей, строк отчётности.",
    parameters: {
      q: { type: "string", required: true, description: "Слова из подписи строки, например «ставка на содержание»." },
      year: { type: "integer", description: "Год." },
      level: { type: "string", description: "Уровень из профиля корпуса (например ВН, СН2, НН) или «Всего»." },
      half: { type: "string", description: "Полугодие: I или II." },
      doc: { type: "string", description: "Ограничить документом, например d0001." },
      page: { type: "string", description: "Ограничить страницей документа." },
      n: { type: "integer", description: "Сколько ячеек вернуть (по умолчанию 10)." },
    },
    async execute(args, exec) {
      const argv = ["table", "--q", String(args.q), "--n", String(args.n || 10)];
      if (args.year) argv.push("--year", String(args.year));
      if (args.level) argv.push("--level", String(args.level));
      if (args.half) argv.push("--half", String(args.half));
      if (args.doc) argv.push("--doc", String(args.doc));
      if (args.page) argv.push("--page", String(args.page));
      return run(argv, exec);
    },
  });

  reg({
    name: "corpus_doc",
    description: "Карточка документа: путь, раздел, тип, год из текста шапки, дата и номер акта, период, страниц. "
      + "С параметром find — поиск документов по словам названия (например «отчёт 2024»).",
    parameters: {
      doc: { type: "string", description: "Идентификатор документа." },
      find: { type: "string", description: "Слова из названия файла или документа." },
      n: { type: "integer", description: "Сколько документов вернуть при поиске (по умолчанию 15)." },
    },
    async execute(args, exec) {
      if (args.find) return run(["doc", "--find", String(args.find), "--n", String(args.n || 15)], exec);
      if (!args.doc) return { ok: false, error: "нужен doc или find" };
      return run(["doc", String(args.doc)], exec);
    },
  });

  reg({
    name: "corpus_number",
    description: "Проверка числа: стоит ли значение дословно на странице документа (пробелы тысяч нормализуются). "
      + "Вызывай для каждой цифры перед ответом; found=false — цифру в ответ без пометки не ставить.",
    parameters: {
      doc: { type: "string", required: true, description: "Идентификатор документа." },
      page: { type: "string", required: true, description: "Метка страницы." },
      value: { type: "string", required: true, description: "Число как в источнике, например «1 234,567»." },
    },
    async execute(args, exec) {
      return run(["number", String(args.doc), String(args.page), String(args.value)], exec);
    },
  });

  reg({
    name: "corpus_aggregate",
    description: "Сумма, число строк, среднее, минимум и максимум по графе таблицы документа (реестры XLSX/XLSM, таблицы DOCX/XLS); "
      + "с column2 — отношение сумм двух граф (доля, коэффициент). Используй вместо кода для итогов по таблицам: "
      + "возвращает формулу, первую и последнюю строку, пропущенные нечисловые ячейки и сверку со строкой «Итого», если она есть. "
      + "warning — итог неполный, так в ответе и пиши. Таблицы PDF — через corpus_table.",
    parameters: {
      doc: { type: "string", required: true, description: "Идентификатор документа." },
      column: { type: "string", required: true, description: "Слова из заголовка графы («мощность») или её номер с 1." },
      page: { type: "string", description: "Страница или лист Excel («Реестр»); без него — все страницы документа." },
      column2: { type: "string", description: "Вторая графа: вернётся отношение Σcolumn / Σcolumn2 по строкам, где обе числовые." },
      where: { type: "string", description: "Фильтр строк: «графа=значение» (точно) или «графа~часть» (подстрока), например «Наименование~Подстанция»." },
    },
    async execute(args, exec) {
      const argv = ["aggregate", String(args.doc), "--column", String(args.column)];
      if (args.page) argv.push("--page", String(args.page));
      if (args.column2) argv.push("--column2", String(args.column2));
      if (args.where) argv.push("--where", String(args.where));
      return run(argv, exec);
    },
  });

  reg({
    name: "corpus_calc",
    description: "Точная арифметика: сумма, разность, доля, темп по выражению с числами в русской записи "
      + "(«1 234,5 + 0,25», «(120,5 - 100) / 100 * 100»; + - * / скобки). "
      + "Любое число в ответе, которого нет дословно в источнике, считай только этим инструментом или corpus_aggregate — не в уме. "
      + "В ответ — выражение и result; операнды — из corpus_* с doc и страницей.",
    parameters: {
      expr: { type: "string", required: true, description: "Выражение: числа как в источнике, операции + - * / и скобки." },
      digits: { type: "number", description: "Знаков после запятой в result; без него — как у самого точного операнда (для * и / не меньше 4)." },
    },
    async execute(args, exec) {
      const argv = ["calc", String(args.expr)];
      if (args.digits !== undefined && args.digits !== null) argv.push("--digits", String(Math.trunc(Number(args.digits))));
      return run(argv, exec, false);
    },
  });

  ctx.systemPrompt.section({ name: "dsh-ru-corpus:method", order: 5, text: METHOD_PROMPT });
}

export { apply, inject, name };
