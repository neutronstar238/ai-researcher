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

研究计划面向的读者是人（审批人、复核人），所以要有 **Markdown 版本**。

但 **JSON 仍是唯一权威**，不能删除或替代：

- `plan_hash = canonical_model_hash(plan_payload)` 绑定 JSON 的规范字节，参与审批门禁与
  artifact 校验。为可读性重排字段会改变哈希，使凭证失效。
- Markdown 由 JSON **单向派生**，通过
  `src/autoresearch/competition/research_plan_markdown.py` 渲染。
- `author_research_plan` 已自动在 JSON 旁落盘同名 `.md`，无需手动调用。

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
