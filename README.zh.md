[Русский](README.md) · [English](README.en.md) · **中文**

# ru-corpus

## 简介

面向俄语文档语料库的搜索与可核验分析工具。语料库（corpus）即 AI 智能体所处理的数据与信息集合（PDF、扫描件、表格、压缩包）。
每个数字都附带文档和页码；没有答案时，智能体会如实回答“语料库中没有”。全部在本地运行，索引就存放在文档旁边。

## 组成

- `packages/ru-corpus-kit`：Python 核心，提供索引和 `ru-corpus` 命令（init、index、status、search、page、table、doc、
  number、aggregate、calc）；基于词元（lemma）的 BM25 搜索、扫描件 OCR、带列和年份的表格；
- `packages/dsh-ru-corpus`：DeepSeek Harness（DSH）插件，在系统提示中加入分析方法，并在 `ru-corpus` 之上提供七个 `corpus_*` 工具；
- `skills/russian-corpus-search` 与 `skills/corpus-analytics-ru`：`SKILL.md` 技能，分别提供俄语搜索和可核验分析的方法；
  电网企业信息披露的行业参考见 `skills/corpus-analytics-ru/references/tso-disclosure.md`；
- `plugins/claude-ru-corpus`：Claude Code 插件，内含两个技能的副本（由 `scripts/sync_claude_plugin.py` 同步）；
  `.claude-plugin/marketplace.json` 为插件市场清单；
- `demo`：演示语料库，包含 15 份官方文件和 6 个检验问题。

## 快速开始

需要 Python 3.10+。处理扫描件需安装带 `rus` 语言包的 `tesseract`；提取 PDF 文本需要 poppler 的 `pdftotext`
（`brew install poppler tesseract tesseract-lang` 或 `apt install poppler-utils tesseract-ocr tesseract-ocr-rus`）。

```bash
pip install "ru-corpus-kit[tables,ocr] @ git+https://github.com/ru-data-analysis/ru-corpus#subdirectory=packages/ru-corpus-kit"
ru-corpus init --root ./文档 --prefix "corpus/"          # 生成 corpus.toml
ru-corpus index                                         # 建立索引：文本、OCR、词元、表格
ru-corpus search "выручка за 2024 год"                  # 证据：文件、页码、片段
ru-corpus number d0001 1 "1 234 567,89"                 # 该数字是否逐字出现在该页
```

PyPI 上的包名为 `ru-corpus-kit`（发布后可直接 `pip install "ru-corpus-kit[tables,ocr]"`）。不带 extras 时只安装核心。
`[tables]` 和 `[ocr]` 引入的是 pdfplumber、pypdfium2 和 Pillow，均为宽松许可证。

### 接入智能体

DeepSeek Harness：

```bash
dsh plugin --profile web add "file:/path/to/ru-corpus/packages/dsh-ru-corpus"
```

Claude Code：

```text
/plugin marketplace add ru-data-analysis/ru-corpus
/plugin install ru-corpus@ru-corpus
```

适用于任意智能体的 `SKILL.md` 技能（skills.sh）：

```bash
npx skills add ru-data-analysis/ru-corpus
```

工具和技能都会调用 `ru-corpus` 命令，因此无论如何都需要先安装核心。它们在会话文件夹中工作，该文件夹本身或其上级目录须有
`corpus.toml`。DSH 插件的设置以及不依赖 DSH 的检查方法见 `packages/dsh-ru-corpus/README.md`。

## 演示语料库与检验

`demo/` 包含 15 份电力和电价领域的官方文件（依据俄罗斯民法典第 1259 条第 6 款，不属于著作权客体；来源与 SHA-256 见
`demo/corpus/MANIFEST.csv`），外加由生成器创建的虚构合成数据集。语料库附有 5 个已核验答案的问题和 1 个陷阱问题（“语料库中没有”）。

```bash
pip install -e "packages/ru-corpus-kit[tables,ocr,test]"
python3 demo/make_synthetic.py                             # 合成数据集
cd demo && ru-corpus index && python3 check_questions.py   # 预期：6/6 个问题通过
```

其他检查：`python3 scripts/scrub_check.py`（脱敏检查）、`python3 scripts/sync_claude_plugin.py --check`（技能副本）、
`pytest packages/ru-corpus-kit/tests`、`node packages/dsh-ru-corpus/test/mock-host.mjs`。

## 限制

- **依赖许可证。** 所有 Python 依赖（含 extras）均采用宽松许可证（MIT、BSD、Apache-2.0），不含 AGPL 组件。
  唯一的 copyleft（GPL）组件是外部程序 poppler，它作为独立进程调用，不包含在发行内容中。
  详情见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)（俄文）。
- OCR 使用 tesseract：质量差的扫描件和手写补充内容会导致数字失真，因此每个数字都要用 `ru-corpus number` 核对。
- “语料库中没有”的判断取决于问题与语料库的词汇重合度：含大量通用词的宽泛提问可能得到错误的“有证据”（已记录在 `demo/README.md`）。
- 内置一个行业配置 `tso_disclosure`（电网企业信息披露）；其他行业需要自行编写配置（`corpus.toml` 中的 `[profile]`）。
- DSH 插件面向 `@deepseek-ai/dsh-tools >=0.2.0-rc.2 <0.3.0`；尚未发布到 npm 和 PyPI。

## 许可证

Apache-2.0（见 `LICENSE`、`NOTICE`）；依赖项的许可证见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)（俄文）。

由 Claude（Anthropic）协助完成。

## 部署与支持

部署、针对您所在行业的配置以及技术支持，请通过本仓库的 issues 联系。
