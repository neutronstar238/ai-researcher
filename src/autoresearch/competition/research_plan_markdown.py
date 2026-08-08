"""把系统撰写的研究计划渲染成给人读的 Markdown。

为什么需要这个模块
------------------
`author_research_plan` 只落盘 `system-authored-research-plan.json`。JSON 是哈希绑定的
凭证：`plan_hash = canonical_model_hash(plan_payload)` 参与审批门禁与 artifact 校验，
所以它必须保持机器规范形态，不能为了可读性重排或省略字段。

但计划的读者是人：审批人要判断范围、复核人要看可反驳性、后续 lineage 要读它的失败归因。
让人去读一份把长段落塞进一行的 JSON，是把可审计性和可读性混为一谈。

所以这里渲染一份**派生视图**，而不是替代品：

* JSON 仍是唯一权威，Markdown 由它单向生成；
* Markdown 头部写明 `plan_hash` 与 `artifact_hash`，任何一段引文都能回溯到确切字节；
* 渲染是纯函数，不读取除传入 payload 以外的任何东西，所以它无法悄悄引入 JSON 里没有的
  内容；
* 未识别的字段不会被丢弃，而是落到“其他字段”一节。一个渲染器如果静默吞掉新增字段，
  读者就会以为计划里没有那部分内容。

渲染器不做任何判断，也不总结。它只重排版。计划的每一句话仍然出自模型。
"""

from __future__ import annotations

import json
from typing import Any

# 按人读的顺序排列，而不是 JSON 的字母序。审批人先要知道“要解决什么问题”，
# 而不是先看到 approval_status。
_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("problem_statement", "问题陈述"),
    ("rationale", "机制假设与依据"),
    ("methods", "方法"),
    ("technical_details", "技术细节"),
    ("experiments", "实验设计"),
    ("expected_results", "预期结果与可反驳条件"),
    ("risks_and_alternatives", "风险与备选方案"),
    ("datasets", "数据与度量"),
    ("references", "引用"),
    ("evidence_refs", "证据文件"),
    ("code_agent_brief", "执行指令"),
)

# 这些字段在头部的元数据表里呈现，不单独开小节。
_META_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "标题"),
    ("project_id", "lineage"),
    ("id", "计划 id"),
    ("candidate_id", "候选 id"),
    ("status", "状态"),
    ("approval_status", "审批状态"),
    ("validation_status", "校验状态"),
    ("created_at", "撰写时间"),
)

# 已经在别处呈现或对读者无意义的字段，不进“其他字段”兜底节。
_HANDLED = (
    {name for name, _ in _SECTION_ORDER}
    | {name for name, _ in _META_FIELDS}
    | {"quality_gate", "metadata", "updated_at"}
)


def _render_value(value: Any) -> str:
    """把一个字段值渲染成 Markdown 正文。

    列表渲染成项目符号，字典渲染成子项，字符串原样输出。刻意不做换行重排：
    模型写的段落边界是它自己的表达，渲染器无权改动。
    """

    if value is None:
        return "_（空）_"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "_（空）_"
    if isinstance(value, list | tuple):
        if not value:
            return "_（空）_"
        lines = []
        for item in value:
            if isinstance(item, str):
                lines.append(f"- {item.strip()}")
            else:
                lines.append(f"- {json.dumps(item, ensure_ascii=False)}")
        return "\n".join(lines)
    if isinstance(value, dict):
        if not value:
            return "_（空）_"
        lines = []
        for key in sorted(value):
            inner = value[key]
            if isinstance(inner, str):
                lines.append(f"- **{key}**：{inner.strip()}")
            else:
                lines.append(f"- **{key}**：{json.dumps(inner, ensure_ascii=False)}")
        return "\n".join(lines)
    return str(value)


def _render_quality_gate(gate: Any) -> list[str]:
    """渲染质量门禁。分数是评审信号，不是计划内容，所以单独成节并标注来源。"""

    if not isinstance(gate, dict) or not gate:
        return []
    lines = ["## 质量门禁", ""]
    verdict = gate.get("verdict")
    score = gate.get("score")
    passed = gate.get("passed")
    lines.append(f"- 结论：**{verdict}**（passed={passed}，score={score}）")
    rubric = gate.get("rubric_scores")
    if isinstance(rubric, dict) and rubric:
        parts = "，".join(f"{k} {v}" for k, v in sorted(rubric.items()))
        lines.append(f"- 细项评分：{parts}")
    for label, key in (("问题", "issues"), ("告警", "warnings")):
        items = gate.get(key)
        if isinstance(items, list | tuple) and items:
            lines.append(f"- {label}：")
            lines.extend(f"  - {item}" for item in items)
    lines.append("")
    return lines


def render_research_plan_markdown(
    *,
    plan: dict[str, Any],
    plan_hash: str | None = None,
    artifact_hash: str | None = None,
    lineage_id: str | None = None,
    model_name: str | None = None,
    authoring_attempts: int | None = None,
    reasoning_tokens: int | None = None,
) -> str:
    """把计划 payload 渲染成 Markdown。纯函数，只依赖传入的参数。"""

    title = str(plan.get("title") or "研究计划").strip()
    out: list[str] = [f"# {title}", ""]

    # 溯源块放最前面：读者在读任何一句结论之前，先知道这份文档是谁写的、
    # 对应哪份不可变字节、以及它还没有被批准。
    out.append("> 本文档由系统（模型）撰写，并由 Markdown 渲染器排版。")
    out.append(">")
    out.append(
        "> **权威凭证是同目录下的 JSON**，本文件是它的派生视图。"
        "若两者不一致，以 JSON 为准。"
    )
    if plan_hash:
        out.append(">")
        out.append(f"> - `plan_hash`：`{plan_hash}`")
    if artifact_hash:
        out.append(f"> - `artifact_hash`：`{artifact_hash}`")
    if lineage_id:
        out.append(f"> - lineage：`{lineage_id}`")
    if model_name:
        out.append(f"> - 撰写模型：`{model_name}`")
    if authoring_attempts is not None:
        out.append(f"> - 撰写尝试次数：{authoring_attempts}")
    if reasoning_tokens is not None:
        out.append(f"> - 推理 token：{reasoning_tokens}")
    out.append(">")
    out.append("> 人工撰写的散文字段数：0")
    out.append("")

    meta_rows = [(label, plan.get(name)) for name, label in _META_FIELDS]
    meta_rows = [(label, value) for label, value in meta_rows if value not in (None, "")]
    if meta_rows:
        out.append("| 项 | 值 |")
        out.append("| --- | --- |")
        for label, value in meta_rows:
            out.append(f"| {label} | {value} |")
        out.append("")

    for name, label in _SECTION_ORDER:
        if name not in plan:
            continue
        out.append(f"## {label}")
        out.append("")
        out.append(_render_value(plan[name]))
        out.append("")

    out.extend(_render_quality_gate(plan.get("quality_gate")))

    # 兜底：任何未在上面处理过的字段都要出现，否则读者会误以为计划里没有它。
    leftover = sorted(k for k in plan if k not in _HANDLED)
    if leftover:
        out.append("## 其他字段")
        out.append("")
        out.append("_渲染器未单独归类的字段，原样列出以免遗漏。_")
        out.append("")
        for key in leftover:
            out.append(f"### `{key}`")
            out.append("")
            out.append(_render_value(plan[key]))
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_plan_artifact_markdown(artifact_payload: dict[str, Any]) -> str:
    """从落盘的 artifact payload 渲染，自动带上溯源字段。"""

    plan = artifact_payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("artifact payload 缺少 plan 字典，无法渲染")
    return render_research_plan_markdown(
        plan=plan,
        plan_hash=artifact_payload.get("plan_hash"),
        artifact_hash=artifact_payload.get("artifact_hash"),
        lineage_id=artifact_payload.get("lineage_id"),
        model_name=artifact_payload.get("model_name"),
        authoring_attempts=artifact_payload.get("authoring_attempts"),
        reasoning_tokens=artifact_payload.get("reasoning_tokens"),
    )


# ---------------------------------------------------------------------------
# 结果解读（outcome）的 Markdown 渲染
# ---------------------------------------------------------------------------

# 结论小节按“先说支持什么、再说不支持什么、最后自我反驳”的顺序排列。
# 这个顺序不是随意的：先读到 counter-reading 会让读者带着怀疑去读结论，
# 而先读结论再读自我反驳，才能判断这个反驳是否诚实。
_OUTCOME_SECTIONS: tuple[tuple[str, str], ...] = (
    ("what_the_evidence_supports", "证据支持什么"),
    ("what_the_evidence_does_not_support", "证据不支持什么"),
    ("strongest_counter_reading", "最强的反面解读"),
    ("limitations", "局限"),
)

_VERDICT_LABELS: dict[str, str] = {
    "claim_supported": "结论成立",
    "claim_not_supported": "结论不成立",
    "inconclusive_underpowered": "不确定（检验力不足）",
}


def render_outcome_markdown(outcome_payload: dict[str, Any]) -> str:
    """把系统对自己结果的解读渲染成 Markdown。

    与计划渲染同样的边界：JSON 是权威（`outcome_hash` 绑定它的规范字节），这里只重排版。
    渲染器不评价这份解读是否正确，那是 grader 的职责，其结论已经在 `accepted` 和
    `refusal_reasons` 里，如实呈现即可。
    """

    interp = outcome_payload.get("interpretation")
    if not isinstance(interp, dict):
        raise ValueError("outcome payload 缺少 interpretation 字典，无法渲染")

    verdict = str(interp.get("verdict") or "")
    verdict_label = _VERDICT_LABELS.get(verdict, verdict)
    lineage = outcome_payload.get("lineage_id") or "未知 lineage"

    out: list[str] = [f"# 结果解读：{lineage}", ""]
    out.append("> 本文档由系统（模型）对自己的结果撰写，并由渲染器排版。")
    out.append(">")
    out.append(
        "> **权威凭证是同目录下的 JSON**，本文件是它的派生视图。"
        "若两者不一致，以 JSON 为准。"
    )
    out.append(">")
    # 标识符名用反引号，中文说明文字不用：反引号是代码标记，不是强调标记。
    for key, caption, is_identifier in (
        ("outcome_hash", "outcome_hash", True),
        ("package_hash", "package_hash", True),
        ("model_name", "撰写模型", False),
        ("reasoning_tokens", "推理 token", False),
    ):
        value = outcome_payload.get(key)
        if value in (None, ""):
            continue
        caption_text = f"`{caption}`" if is_identifier else caption
        out.append(f"> - {caption_text}：`{value}`")
    out.append("")

    # 判定与门禁的一致性是这份文档最要紧的信息，放在正文最前面。
    accepted = outcome_payload.get("accepted")
    gate_passed = outcome_payload.get("frozen_gate_passed")
    consistent = outcome_payload.get("verdict_consistent_with_gate")
    out.append("## 判定")
    out.append("")
    out.append("| 项 | 值 |")
    out.append("| --- | --- |")
    out.append(f"| 系统自评判定 | **{verdict_label}** |")
    out.append(f"| 冻结门禁是否通过 | {'通过' if gate_passed else '**未通过**'} |")
    out.append(f"| 判定与门禁是否一致 | {'一致' if consistent else '**不一致**'} |")
    out.append(f"| 解读是否被 grader 接受 | {'接受' if accepted else '**拒收**'} |")
    trace = outcome_payload.get("traceability")
    if isinstance(trace, dict):
        checked = trace.get("checked_number_count")
        traceable = trace.get("traceable_number_count")
        out.append(f"| 数字可溯源 | {traceable}/{checked} |")
    relation_audit = outcome_payload.get("relation_audit")
    if isinstance(relation_audit, dict):
        relation_checked = relation_audit.get("checked_relation_count")
        relation_passed = relation_audit.get("passed")
        relation_verdict = "通过" if relation_passed else "**存在算术矛盾**"
        out.append(f"| 数值关系复算 | {relation_verdict}（复算 {relation_checked} 项） |")
    out.append(
        f"| 人工撰写的散文字段数 | {outcome_payload.get('hand_written_prose_count', 0)} |"
    )
    out.append("")

    refusals = outcome_payload.get("refusal_reasons")
    if isinstance(refusals, list | tuple) and refusals:
        out.append("### grader 拒收理由")
        out.append("")
        out.extend(f"- {item}" for item in refusals)
        out.append("")

    if isinstance(trace, dict):
        untraceable = trace.get("untraceable_numbers")
        if isinstance(untraceable, list | tuple) and untraceable:
            out.append("### 无法溯源的数字")
            out.append("")
            out.append("_以下数字未能在证据中找到出处，可能是模型自行编造的。_")
            out.append("")
            out.extend(f"- `{item}`" for item in untraceable)
            out.append("")

    if isinstance(relation_audit, dict):
        contradictions = relation_audit.get("contradictions")
        if isinstance(contradictions, list | tuple) and contradictions:
            out.append("### 算术矛盾")
            out.append("")
            out.append("_以下数值关系由确定性审计器复算为假。_")
            out.append("")
            out.extend(f"- `{item}`" for item in contradictions)
            out.append("")

    for name, heading in _OUTCOME_SECTIONS:
        if name not in interp:
            continue
        out.append(f"## {heading}")
        out.append("")
        out.append(_render_value(interp[name]))
        out.append("")

    handled = {name for name, _ in _OUTCOME_SECTIONS} | {
        "verdict",
        "schema_version",
        "claims_frozen_gate_passed",
    }
    leftover = sorted(k for k in interp if k not in handled)
    if leftover:
        out.append("## 其他字段")
        out.append("")
        out.append("_渲染器未单独归类的字段，原样列出以免遗漏。_")
        out.append("")
        for key in leftover:
            out.append(f"### `{key}`")
            out.append("")
            out.append(_render_value(interp[key]))
            out.append("")

    return "\n".join(out).rstrip() + "\n"
