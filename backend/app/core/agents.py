"""Agent system primitives (spec §16): tool registry, risk levels, budget (pure)."""

from __future__ import annotations

from dataclasses import dataclass

# 风险级别（§16.4）
TOOL_RISK_LEVELS = ("read", "write_low", "write_high", "external_side_effect")

TASK_STATUSES = ("queued", "running", "waiting_approval", "succeeded", "failed", "cancelled")

TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting_approval", "succeeded", "failed", "cancelled"}),
    "waiting_approval": frozenset({"running", "failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset({"queued"}),  # retry
    "cancelled": frozenset(),
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_level: str
    requires_approval: bool


# 内置工具注册（§16.1 主要工具）
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "project.read": ToolSpec("project.read", "只读项目数据", "read", False),
    "evidence.propose": ToolSpec("evidence.propose", "建议证据节点/关系", "write_low", False),
    "evidence.write": ToolSpec("evidence.write", "写入证据节点/边", "write_high", True),
    "experiment.run": ToolSpec("experiment.run", "创建实验运行", "write_high", True),
    "document.suggest": ToolSpec("document.suggest", "生成文档建议 Diff", "write_low", False),
    "document.publish": ToolSpec("document.publish", "发布正式文档", "write_high", True),
    "external.send": ToolSpec("external.send", "外部发信/发布", "external_side_effect", True),
}


def tool_spec(tool_name: str) -> ToolSpec:
    from app.api.errors import ValidationAppError

    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        raise ValidationAppError(f"未知工具: {tool_name}", code="UNKNOWN_TOOL")
    return spec


def tool_risk_level(tool_name: str) -> str:
    return tool_spec(tool_name).risk_level


def tool_requires_approval(tool_name: str) -> bool:
    return tool_spec(tool_name).requires_approval


def is_allowed_task_transition(current: str, target: str) -> bool:
    return target in TASK_TRANSITIONS.get(current, frozenset())


@dataclass(frozen=True)
class Budget:
    max_tokens: int | None = None
    max_cost: float | None = None
    max_tool_calls: int | None = None


@dataclass(frozen=True)
class Usage:
    tokens: int = 0
    cost: float = 0.0
    tool_calls: int = 0


def budget_exceeded(usage: Usage, budget: Budget) -> bool:
    return (
        (budget.max_tokens is not None and usage.tokens >= budget.max_tokens)
        or (budget.max_cost is not None and usage.cost >= budget.max_cost)
        or (budget.max_tool_calls is not None and usage.tool_calls >= budget.max_tool_calls)
    )


def budget_warning(usage: Usage, budget: Budget) -> bool:
    """是否达到 80% 预算（spec §16.8）。"""
    ratios = []
    if budget.max_tokens:
        ratios.append(usage.tokens / budget.max_tokens)
    if budget.max_cost:
        ratios.append(usage.cost / budget.max_cost)
    if budget.max_tool_calls:
        ratios.append(usage.tool_calls / budget.max_tool_calls)
    return bool(ratios) and max(ratios) >= 0.8
