[Русский](README.md) · **English** · [中文](README.zh.md)

# ru-corpus

## What it is

Russian-language search and verifiable analytics over a corpus of documents — the body of data and information
(PDFs, scans, tables, archives) an AI agent works with. Every figure comes with its document and page, and where
there is no answer the agent says so plainly: "not in the corpus". Everything runs locally: the index sits next
to your documents.

## What's inside

- `packages/ru-corpus-kit` — the Python core: indexing and the `ru-corpus` command (init, index, status, search,
  page, table, doc, number, aggregate, calc); BM25 search over lemmas, OCR of scans, tables with columns and years;
- `packages/dsh-ru-corpus` — a DeepSeek Harness (DSH) plugin: an analytics methodology in the system prompt and
  seven `corpus_*` tools on top of `ru-corpus`;
- `skills/russian-corpus-search` and `skills/corpus-analytics-ru` — `SKILL.md` skills: Russian search and a
  methodology for verifiable analytics; a sector reference on grid-company disclosure is in
  `skills/corpus-analytics-ru/references/tso-disclosure.md`;
- `plugins/claude-ru-corpus` — a Claude Code plugin with copies of the skills (refreshed by
  `scripts/sync_claude_plugin.py`); `.claude-plugin/marketplace.json` is the marketplace;
- `demo` — a demo corpus of 15 official acts and 6 control questions.

## Quick start

Python 3.10+ is required. For scans install `tesseract` with the `rus` language; for PDF text, `pdftotext` from
poppler (`brew install poppler tesseract tesseract-lang` or `apt install poppler-utils tesseract-ocr tesseract-ocr-rus`).

```bash
pip install "ru-corpus-kit[tables,ocr] @ git+https://github.com/ru-data-analysis/ru-corpus#subdirectory=packages/ru-corpus-kit"
ru-corpus init --root ./documents --prefix "corpus/"    # creates corpus.toml
ru-corpus index                                         # index: text, OCR, lemmas, tables
ru-corpus search "выручка за 2024 год"                  # evidence: file, page, snippet
ru-corpus number d0001 1 "1 234 567,89"                 # is the number on the page verbatim
```

The PyPI package name is `ru-corpus-kit` (once published: `pip install "ru-corpus-kit[tables,ocr]"`). Without
extras only the core is installed. The `[tables]` and `[ocr]` extras bring pdfplumber, pypdfium2 and Pillow, all under permissive licenses.

### Connecting to an agent

DeepSeek Harness:

```bash
dsh plugin --profile web add "file:/path/to/ru-corpus/packages/dsh-ru-corpus"
```

Claude Code:

```text
/plugin marketplace add ru-data-analysis/ru-corpus
/plugin install ru-corpus@ru-corpus
```

`SKILL.md` skills for any agent (skills.sh):

```bash
npx skills add ru-data-analysis/ru-corpus
```

The tools and skills call the `ru-corpus` command, so the core must be installed in every case. They work in a
session folder that contains, or sits below, a `corpus.toml`. DSH plugin settings and the no-DSH check are in
`packages/dsh-ru-corpus/README.md`.

## Demo corpus and checks

`demo/` holds 15 official acts of government bodies on electric power and tariffs (not subject to copyright under
Art. 1259(6) of the Russian Civil Code; sources and SHA-256 hashes are in `demo/corpus/MANIFEST.csv`) plus a fictional
synthetic set produced by a generator. The corpus comes with 5 questions with verified answers and one trap question
("not in the corpus").

```bash
pip install -e "packages/ru-corpus-kit[tables,ocr,test]"
python3 demo/make_synthetic.py                             # synthetic set
cd demo && ru-corpus index && python3 check_questions.py   # expected: 6/6 questions passed
```

Other checks: `python3 scripts/scrub_check.py` (scrub check), `python3 scripts/sync_claude_plugin.py --check`
(skill copies), `pytest packages/ru-corpus-kit/tests`, `node packages/dsh-ru-corpus/test/mock-host.mjs`.

## Limitations

- **Dependency licenses.** All Python dependencies (extras included) use permissive licenses (MIT, BSD,
  Apache-2.0); there are no AGPL components. The only copyleft (GPL) piece is the external poppler program, which
  is run as a separate process and is not part of the distribution. Details are in
  [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) (Russian).
- OCR uses tesseract: poor scans and handwritten insertions distort numbers, so every number is checked with
  `ru-corpus number`.
- The "not in the corpus" refusal depends on lexical overlap between the question and the corpus: a broad wording
  with common words can get a false "evidence found" (recorded in `demo/README.md`).
- One sector profile is bundled — `tso_disclosure` (disclosure by grid companies); other sectors need their own
  profile (`[profile]` in `corpus.toml`).
- The DSH plugin targets `@deepseek-ai/dsh-tools >=0.2.0-rc.2 <0.3.0`; it is not yet published to npm or PyPI.

## License

Apache-2.0 (see `LICENSE`, `NOTICE`); dependency licenses are in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)
(in Russian).

Made with Claude (Anthropic).

## Adoption and support

Help with adoption, with profiles for your sector, and with support — through the repository's issues.
