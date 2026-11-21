// Проверка плагина без DeepSeek Harness: заглушки defineTool / ctx.tools / ctx.systemPrompt / subprocess,
// настоящая команда `ru-corpus` и синтетический корпус (тот же генератор, что в тестах ядра).
// Запуск: node test/mock-host.mjs        (нужны python3 и установленный ru-corpus-kit[tables])
import { mkdtempSync, mkdirSync, writeFileSync, cpSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { pathToFileURL, fileURLToPath } from "node:url";

const plugin = resolve(fileURLToPath(new URL("..", import.meta.url)));
const synthDir = resolve(plugin, "../ru-corpus-kit/tests");
const tmp = mkdtempSync(join(tmpdir(), "dsh-ru-corpus-"));
delete process.env.RU_CORPUS_CONFIG;

const run = (cmd, args, cwd) => {
  const r = spawnSync(cmd, args, { cwd, encoding: "utf-8" });
  if (r.status !== 0) { console.error(r.stdout, r.stderr); throw new Error(cmd + " " + args.join(" ") + " -> код " + r.status); }
  return r.stdout;
};

// --- заглушка пакета dsh-tools и копия плагина
mkdirSync(join(tmp, "node_modules/@deepseek-ai/dsh-tools"), { recursive: true });
writeFileSync(join(tmp, "node_modules/@deepseek-ai/dsh-tools/package.json"),
  JSON.stringify({ name: "@deepseek-ai/dsh-tools", type: "module", main: "index.js" }));
writeFileSync(join(tmp, "node_modules/@deepseek-ai/dsh-tools/index.js"), "export const defineTool = (s) => s;\n");
cpSync(join(plugin, "lib"), join(tmp, "node_modules/dsh-ru-corpus/lib"), { recursive: true });
writeFileSync(join(tmp, "node_modules/dsh-ru-corpus/package.json"), JSON.stringify({ name: "dsh-ru-corpus", type: "module" }));
const mod = await import(pathToFileURL(join(tmp, "node_modules/dsh-ru-corpus/lib/index.js")).href);

// --- синтетический корпус + init + index
const project = join(tmp, "project");
mkdirSync(project);
run("python3", ["-c",
  "import sys, pathlib; sys.path.insert(0, sys.argv[1]); import synth; "
  + "synth.make_corpus(pathlib.Path(sys.argv[2]) / 'docs', scan=False, docx_ok=False)", synthDir, project]);
run("ru-corpus", ["init", "--root", "docs", "--prefix", "demo/"], project);
run("ru-corpus", ["index", "--quiet", "--no-ocr"], project);

// --- заглушка хоста
const subprocess = {
  async resolveExecutable(n) { return n; },
  spawn({ argv, cwd }) {
    const p = spawn(argv[0], argv.slice(1), { cwd, env: process.env });
    let out = "", err = "";
    p.stdout.on("data", (d) => (out += d)); p.stderr.on("data", (d) => (err += d));
    p.on("error", (e) => { err += String(e.message); });
    const done = new Promise((r) => p.on("close", (code) => r({ exitCode: code })));
    return { done, collected: { stdout: { readFrom: () => ({ text: out }) }, stderr: { readFrom: () => ({ text: err }) } } };
  },
};
function load(config) {
  const tools = {}; const sections = [];
  const ctx = {
    get: (k) => (k === "subprocess" ? subprocess : undefined),
    effect: (fn) => fn(),
    tools: { register: (t) => { tools[t.name] = t; return () => {}; } },
    systemPrompt: { section: (s) => sections.push(s) },
  };
  mod.apply(ctx, config);
  return { tools, sections };
}
const { tools, sections } = load({});
const at = (cwd) => ({ agent: { session: { header: { cwd } } }, signal: new AbortController().signal });
const exec = at(project);

const fails = [];
const ok = (c, m) => { console.log((c ? "OK   " : "FAIL ") + m); if (!c) fails.push(m); };

// --- регистрация и контракты
ok(mod.name === "ru-corpus" && mod.inject.includes("subprocess"), "экспорт name/inject");
ok(Object.keys(tools).sort().join(",") === "corpus_aggregate,corpus_calc,corpus_doc,corpus_number,corpus_page,corpus_search,corpus_table",
  "зарегистрированы 7 инструментов: " + Object.keys(tools).join(", "));
ok(sections.length === 1 && sections[0].text.includes("Первичка выше производного"), "раздел системного промта");
const PRIVATE = new RegExp(["\u041e\u042d\u041a", "OE" + "K", "doc-" + "\\d{4}"].join("|"));
ok(!PRIVATE.test(sections[0].text), "в промте нет привязок к частному корпусу");
for (const t of Object.values(tools)) ok(t.output && typeof t.output.render === "function" && t.parameters, t.name + ": схема и рендер");
for (const t of Object.values(tools)) {
  for (const v of [{ ok: true, x: 1 }, { ok: false, error: "e" }]) {
    const parts = t.output.render({}, v);
    ok(Array.isArray(parts) && parts.length > 0 && parts.every((p) => p && p.type === "text" && typeof p.text === "string"),
      t.name + ": render -> [{type:'text'}] (" + (v.ok ? "ok" : "ошибка") + ")");
  }
}
ok(load({ enabled: false }).sections.length === 0, "enabled: false — ничего не монтируется");

// --- doc
let r = await tools.corpus_doc.execute({ find: "otchet 2024" }, exec);
ok(r.ok && r.found === 1 && r.docs[0].file === "demo/reports/otchet_2024.pdf", "corpus_doc find: годовой отчёт найден");
const rep = r.docs[0].doc;
r = await tools.corpus_doc.execute({ doc: rep }, exec);
ok(r.ok && r.year === 2024 && r.pages === 3, "corpus_doc: год из шапки, 3 страницы");
r = await tools.corpus_doc.execute({}, exec);
ok(r.ok === false && r.error, "corpus_doc: без doc и find — ошибка");

// --- search
r = await tools.corpus_search.execute({ query: "выручка от передачи электроэнергии" }, exec);
ok(r.ok && r.verdict === "есть доказательства" && r.evidence[0].doc === rep && r.evidence[0].page === "1"
  && r.evidence[0].file && r.evidence[0].section, "corpus_search: отчёт первым, с файлом, страницей и разделом");
r = await tools.corpus_search.execute({ query: "Курс акций на бирже Токио", n: 3 }, exec);
ok(r.ok && r.verdict === "в корпусе нет" && r.evidence.length === 0, "corpus_search: ловушка -> «в корпусе нет»");
r = await tools.corpus_search.execute({ query: "1 234 567,89", n: 3 }, exec);
ok(r.ok && r.mode === "number" && r.evidence.some((e) => e.doc === rep), "corpus_search: число с пробелами разрядов находится");

// --- page, number
r = await tools.corpus_page.execute({ doc: rep, page: "1", max_chars: 1500 }, exec);
ok(r.ok && r.text.includes("Демо-Сеть") && r.origin === "demo/reports/otchet_2024.pdf#page=1" && r.sha256, "corpus_page: текст, origin и sha256");
r = await tools.corpus_page.execute({ doc: rep, page: "99" }, exec);
ok(r.ok === false && r.error, "corpus_page: нет страницы — понятная ошибка");
r = await tools.corpus_number.execute({ doc: rep, page: "1", value: "1 234 567,89" }, exec);
ok(r.ok && r.found === true, "corpus_number находит 1 234 567,89");
r = await tools.corpus_number.execute({ doc: rep, page: "1", value: "9 999 999" }, exec);
ok(r.ok && r.found === false, "corpus_number не находит выдуманное число");

// --- table
r = await tools.corpus_table.execute({ q: "Потери электроэнергии", year: 2024 }, exec);
ok(r.ok && r.cells.length && r.cells[0].value === "108,9" && r.cells[0].anchor.includes("2024"), "corpus_table: потери 2024 = 108,9, якорь с годом");
r = await tools.corpus_table.execute({ q: "Отпуск в сеть", year: 2024, doc: rep, page: "2" }, exec);
ok(r.ok && r.cells[0].value === "5 512,3", "corpus_table: ограничение документом и страницей");

// --- aggregate
r = await tools.corpus_doc.execute({ find: "reestr" }, exec);
const reg = r.docs[0].doc;
r = await tools.corpus_aggregate.execute({ doc: reg, page: "Реестр", column: "Мощность" }, exec);
ok(r.ok && r.column_stats.count === 5 && r.column_stats.sum === 950 && r.total_matches_sum === true,
  "corpus_aggregate: 5 строк, Σ = 950, сверка с «Итого»");
r = await tools.corpus_aggregate.execute({ doc: reg, column: "Мощность", where: "Наименование~Подстанция" }, exec);
ok(r.ok && r.column_stats.sum === 350.5 && r.rows_matched === 2, "corpus_aggregate: фильтр where");
r = await tools.corpus_aggregate.execute({ doc: reg, column: "Стоимость", column2: "Мощность" }, exec);
ok(r.ok && r.ratio_sum === 10, "corpus_aggregate: отношение сумм двух граф");
r = await tools.corpus_aggregate.execute({ doc: reg, column: "нет такой графы" }, exec);
ok(r.ok === false && r.error, "corpus_aggregate: нет графы — понятная ошибка");

// --- calc
r = await tools.corpus_calc.execute({ expr: "1 000,5 + 0,002 + 2 000,25 + 10" }, exec);
ok(r.ok && r.result === "3 010,752", "corpus_calc: сумма в русской записи");
r = await tools.corpus_calc.execute({ expr: "(10 - 4) / 3 * 100", digits: 1 }, exec);
ok(r.ok && r.result === "200,0", "corpus_calc: скобки, деление, digits");
r = await tools.corpus_calc.execute({ expr: "require('fs')" }, exec);
ok(r.ok === false && r.error, "corpus_calc: не выражение — отказ");

// --- нет корпуса / нет команды
const empty = join(tmp, "empty"); mkdirSync(empty);
r = await tools.corpus_search.execute({ query: "что угодно" }, at(empty));
ok(r.ok === false && /ru-corpus init && ru-corpus index/.test(r.error), "вне корпуса — подсказка «ru-corpus init && ru-corpus index»");
r = await tools.corpus_calc.execute({ expr: "2 + 2" }, at(empty));
ok(r.ok && r.result === "4", "corpus_calc работает и без corpus.toml");
r = await load({ command: "ru-corpus-net-takoy-komandy" }).tools.corpus_search.execute({ query: "x" }, exec);
ok(r.ok === false && /pip install ru-corpus-kit/.test(r.error), "нет команды — подсказка по установке ядра");
r = await load({ config: join(project, "corpus.toml") }).tools.corpus_search.execute({ query: "выручка от передачи" }, at(empty));
ok(r.ok && r.evidence.length > 0, "настройка config: корпус открывается из чужой папки");

rmSync(tmp, { recursive: true, force: true });
console.log(fails.length ? `\nпровалено: ${fails.length}` : "\nвсе проверки пройдены");
process.exit(fails.length ? 1 : 0);
