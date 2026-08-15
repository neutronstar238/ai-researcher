"""Shared semantic gate for executable experiment adapters.

Adapter metadata is a closed execution contract, not a bag of keywords. The
generic checks require exact machine-field agreement and complete null-model
coverage. A small adapter-owned scope check then rejects prose that changes the
scientific object while copying those machine fields unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_PRIME_GAP_ADAPTER_ID = "prime-gap-information-theory-v1"
_POSITIVE_SCOPE_FIELDS = (
    "title_cn",
    "focused_direction_cn",
    "hypothesis_cn",
    "research_objective_cn",
    "falsification_cn",
)


@dataclass(frozen=True, slots=True)
class AdapterSemanticCompatibility:
    """Deterministic compatibility result used by every execution boundary."""

    adapter_id: str
    compatible: bool
    reason_codes: tuple[str, ...]


def assess_adapter_semantic_compatibility(
    descriptor: Mapping[str, Any] | Any,
    *,
    scope_texts: Sequence[str] = (),
    candidate: Mapping[str, Any] | Any | None = None,
) -> AdapterSemanticCompatibility:
    """Check exact descriptor coverage plus adapter-specific scientific scope."""

    declared = _as_mapping(descriptor, label="adapter descriptor")
    adapter_id = _text(declared.get("adapter_id"))
    reasons: list[str] = []
    if not adapter_id:
        reasons.append("adapter_id_missing")

    projected_candidate: Mapping[str, Any] | None = None
    if candidate is not None:
        projected_candidate = _as_mapping(candidate, label="adapter candidate")
        selected_adapter = _text(
            projected_candidate.get("adapter_id") or projected_candidate.get("pilot_adapter_id")
        )
        if selected_adapter != adapter_id:
            reasons.append("adapter_id_mismatch")
        if _text(projected_candidate.get("scientific_object")) != _text(
            declared.get("scientific_object")
        ):
            reasons.append("scientific_object_mismatch")
        if _text(projected_candidate.get("observable")) != _text(declared.get("observable")):
            reasons.append("observable_mismatch")

        supported_metrics = set(_string_values(declared.get("supported_metrics")))
        primary_metric = _text(
            projected_candidate.get("metric") or projected_candidate.get("primary_metric")
        )
        if not primary_metric or primary_metric not in supported_metrics:
            reasons.append("metric_not_supported")

        supported_nulls = set(_string_values(declared.get("supported_nulls")))
        requested_nulls = _string_values(projected_candidate.get("null_models"))
        if not requested_nulls:
            reasons.append("null_models_missing")
        elif any(item not in supported_nulls for item in requested_nulls):
            reasons.append("null_model_not_supported")

    positive_scope = [str(item) for item in scope_texts if str(item).strip()]
    if projected_candidate is not None:
        positive_scope.extend(
            _text(projected_candidate.get(field))
            for field in _POSITIVE_SCOPE_FIELDS
            if _text(projected_candidate.get(field))
        )
    if adapter_id == _PRIME_GAP_ADAPTER_ID:
        reasons.extend(_prime_gap_scope_reasons(positive_scope))

    reason_codes = tuple(dict.fromkeys(reasons))
    return AdapterSemanticCompatibility(
        adapter_id=adapter_id,
        compatible=not reason_codes,
        reason_codes=reason_codes,
    )


def _prime_gap_scope_reasons(scope_texts: Sequence[str]) -> tuple[str, ...]:
    text = _affirmative_execution_scope(scope_texts)
    reasons: list[str] = []
    if any(
        marker in text
        for marker in (
            "梅森素数",
            "mersenne prime",
            "素数指数间隙",
            "prime exponent gap",
        )
    ):
        reasons.append("nonconsecutive_integer_prime_object")
    if "素数签名" in text or re.search(r"prime[\s_-]*signature", text):
        reasons.append("derived_prime_signature")
    if any(
        marker in text
        for marker in (
            "ℓ∞",
            "l∞",
            "l_inf",
            "l-infinity",
            "linfinity",
            "infinity norm",
            "无穷范数",
            "无穷度量",
        )
    ):
        reasons.append("linfinity_metric")
    representation = any(
        marker in text
        for marker in (
            "表示",
            "表征",
            "嵌入",
            "映射",
            "representation",
            "embedding",
            "mapping",
        )
    )
    induced_distance = any(marker in text for marker in ("诱导", "距离", "induced", "distance"))
    gap = any(marker in text for marker in ("间隙", "间隔", "gap"))
    if representation and induced_distance and gap:
        reasons.append("derived_gap_representation")
    if any(marker in text for marker in ("样本熵", "sample entropy")) and any(
        marker in text for marker in ("主指标", "主要指标", "primary metric", "计算", "measure")
    ):
        reasons.append("unsupported_primary_metric_in_scope")
    return tuple(reasons)


def _affirmative_execution_scope(scope_texts: Sequence[str]) -> str:
    """Drop clauses that explicitly disclaim a forbidden operation."""

    clauses = re.split(r"[\n。；;，,]+", "\n".join(scope_texts).casefold())
    negative_markers = (
        "不构造",
        "不使用",
        "不采用",
        "不引入",
        "无需",
        "排除",
        "而非",
        "不是",
        "does not use",
        "do not use",
        "without using",
        "exclude",
        "rather than",
    )
    return "\n".join(
        clause.strip()
        for clause in clauses
        if clause.strip() and not any(marker in clause for marker in negative_markers)
    )


def _as_mapping(value: Mapping[str, Any] | Any, *, label: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        projected = dump(mode="json")
        if isinstance(projected, Mapping):
            return projected
    raise TypeError(f"{label} must be a mapping or Pydantic model")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_values(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()
    return tuple(_text(item) for item in value if _text(item))


__all__ = [
    "AdapterSemanticCompatibility",
    "assess_adapter_semantic_compatibility",
]
