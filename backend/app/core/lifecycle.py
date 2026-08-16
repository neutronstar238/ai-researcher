"""Lifecycle state machine primitives (spec §12).

Pure and unit-testable: stage order, legal transitions, and exit-gate rules.
The gate framework returns missing conditions; callers translate those into a
422 ``STAGE_GATE_FAILED`` response — never a silent pass.
"""

from __future__ import annotations

from typing import Literal

StageKey = Literal[
    "topic", "literature", "hypothesis", "experiment",
    "validation", "writing", "reflection", "evolution",
]

StageStatus = Literal[
    "pending", "ready", "running", "waiting_approval",
    "blocked", "completed", "failed", "cancelled",
]

STAGE_ORDER: tuple[StageKey, ...] = (
    "topic", "literature", "hypothesis", "experiment",
    "validation", "writing", "reflection", "evolution",
)

STAGE_LABELS_ZH: dict[str, str] = {
    "topic": "选题",
    "literature": "文献",
    "hypothesis": "假设",
    "experiment": "实验",
    "validation": "验证",
    "writing": "写作",
    "reflection": "复盘",
    "evolution": "进化",
}

ALLOWED_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    "pending": frozenset({"ready"}),
    "ready": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting_approval", "blocked", "completed", "failed", "cancelled"}),
    "waiting_approval": frozenset({"completed", "running", "blocked"}),
    "blocked": frozenset({"running", "cancelled"}),
    "failed": frozenset({"running", "cancelled"}),
    "completed": frozenset({"running"}),  # 仅显式重开
    "cancelled": frozenset(),
}

# 各阶段退出门禁（Phase 2 最小实现：证据数量门槛）。后续 Phase 3/4 会加入
# 候选采纳、复现 Hash、引用完整性等更完整条件。
GATE_REQUIREMENTS: dict[StageKey, tuple[tuple[str, int], ...]] = {
    "literature": (("min_evidence", 1),),
    "hypothesis": (("min_evidence", 1),),
    "experiment": (("min_evidence", 1),),
    "validation": (("min_evidence", 1),),
}


def is_stage_key(value: str) -> bool:
    return value in STAGE_ORDER


def ordinal_of(stage_key: StageKey) -> int:
    return STAGE_ORDER.index(stage_key) + 1


def next_stage(stage_key: StageKey) -> StageKey | None:
    index = STAGE_ORDER.index(stage_key)
    return STAGE_ORDER[index + 1] if index + 1 < len(STAGE_ORDER) else None


def is_allowed_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())  # type: ignore[arg-type]


def gate_missing(stage_key: str, evidence_count: int) -> list[dict]:
    """Return missing exit-gate conditions for a stage (empty = pass)."""
    missing: list[dict] = []
    for kind, threshold in GATE_REQUIREMENTS.get(stage_key, ()):  # type: ignore[arg-type]
        if kind == "min_evidence" and evidence_count < threshold:
            missing.append(
                {"code": "MIN_EVIDENCE_NOT_MET", "threshold": threshold, "actual": evidence_count}
            )
    return missing
