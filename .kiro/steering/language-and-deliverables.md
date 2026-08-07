---
inclusion: always
---

# 语言与产出格式约定

## 回复语言

用**中文**回复。技术标识符保持原文，不要翻译：

- 代码符号、文件路径、命令：`run_lineage_stage`、`src/autoresearch/competition/`、`poetry run pytest`
- 缺陷编号与任务号：`P-20260807-090`、任务 `269.4`
- 门禁与字段名：`overall_median_at_least_minimum`、`plan_hash`
- 度量与系统名：NMSE、`reaction_diffusion_cylinder`

理由：这些名字在代码和产物里就是那个字面量，翻译会让读者无法 grep 到对应位置。

## 研究计划的产出格式

研究计划的**正式交付格式是 LaTeX**（《科学假设与研究计划》），由
`src/autoresearch/competition/research_plan_latex.py` 渲染，落盘为 `.tex`。
排版对齐清华本科毕业论文惯例：`ctexart`、黑体分级标题、三线表、GB/T 7714 编号参考文献。

**模板与内容的边界（重要）**：`research_plan_latex.py` 里的文档类、字体、页面、章节标题
是**格式**，已定稿，不再改动。模板之外的每一个字必须来自系统（模型）。渲染器不撰写、
不总结、不改写、不补全——任何需要模型撰写的字段为空时，`assert_all_prose_is_authored`
直接拒绝渲染。宁可失败，也不能用占位套话把不完整的计划伪装成完整的：一份含 agent 代笔
句子的计划已经不是"系统自主产出"。

章节结构对齐榜题《生成结果规范》，不得增删：待研究问题、解决思路、必要的技术手段、
数据集（Source/Target）、标题、摘要、方法论、实验设计（含 Baselines 与 Metrics 独立
小节）、实验结果、参考论文。

**参考文献严禁虚构**。提示词只是请求，不是保证，所以由结构强制：

- 文献必须经 `plan_literature_survey.py` 从 ArXiv / OpenAlex 真实检索获得。
- 检索词由系统撰写（科学判断），但条目只能来自检索响应。模型只能按索引挑选并说明关联，
  越界索引被丢弃而不是被信任——即使模型倾向编造，编造对象也不存在。
- `guard_references` 要求每条有可解析的 DOI 或 http(s) URL，并声明 `retrieved_from`。
  不合格条目在渲染前失败，而不是等人逐条去查。

JSON 与 Markdown 仍然保留，各有职责：

- **JSON 是唯一权威凭证**。`plan_hash = canonical_model_hash(plan_payload)` 绑定其规范
  字节，参与审批门禁与 artifact 校验。为可读性重排字段会改变哈希，使凭证失效。
- **Markdown 是快速阅览视图**，由 `research_plan_markdown.py` 渲染，适合在编辑器里直接
  看，不需要编译。

三者都由 `author_research_plan` 自动落盘（`.json` / `.md` / `.tex`），无需手动调用。

Markdown 必须满足：

1. 头部溯源块写明 `plan_hash` 与 `artifact_hash`，并声明"以 JSON 为准"，避免 Markdown
   被误当成凭证。
2. 不失真——JSON 里每个字段都要出现，未识别字段落到"其他字段"兜底节。静默吞掉字段比不
   渲染更糟，因为读者会误以为计划里没有那部分内容。
3. 不越权——渲染器只重排版，不改写模型写的散文，不对数值做四舍五入（否则引文无法与证据
   比对）。计划的每一句话仍出自模型。

## 同样适用的其他产物

给人读的分析与结论（lineage 结果解读、缺陷分析、评审意见）用 Markdown 组织，配表格呈现
门禁通过/失败这类对照信息。机器校验用的凭证（package、ledger、cell 结果）保持 JSON。
