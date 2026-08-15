"""Derive self-contained report evidence from a verified preexperiment.

The research model authors the scientific narrative, but it must not be asked to
copy numbers into presentation tables or draw figures.  This module projects the
already verified preexperiment bytes into a small, deterministic, JSON-safe
report bundle.  The public bundle contains only data, captions, and bounded
interpretation; file paths and hashes stay in manifest-only bindings.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from autoresearch.competition.manifest import canonical_model_hash

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPLETED_STATUSES = frozenset({"completed", "complete", "succeeded"})
_EXCLUDED_COLUMN_PARTS = (
    "hash",
    "sha",
    "path",
    "file",
    "seed",
    "time",
    "date",
    "id",
)

_FIELD_LABELS_ZH = {
    "null_model": "零模型",
    "interval_index": "区间序号",
    "start": "区间起点（含）",
    "stop": "区间终点（不含）",
    "prime_count": "素数数量",
    "gap_count": "间隙数量",
    "interval_count": "固定分析单元数",
    "sample_count": "样本量",
    "draw_count": "置换抽样次数",
    "observed_mean_entropy": "真实序列平均排列熵",
    "null_mean_entropy": "零模型平均排列熵",
    "observed_entropy": "真实序列排列熵",
    "delta_observed_minus_null": "差值（真实值－零模型）",
    "standardized_effect": "模拟标准化诊断量",
    "one_sided_empirical_p_lower": "单侧经验 p 值",
    "holm_adjusted_p_across_null_models": "跨零模型 Holm 校正 p 值",
    "holm_adjusted_p_across_intervals": "跨区间 Holm 校正 p 值",
    "fixed_interval_resampling_delta_ci95": "五个固定区间重采样范围",
    "tie_aware_normalized_permutation_entropy_m5": "含并列修正的五阶归一化排列熵",
    "mean_gap": "平均素数间隙",
    "metric": "指标",
    "value": "数值",
    "score": "得分",
    "condition": "条件",
    "method": "方法",
    "model": "模型",
}

_PREFERRED_AGGREGATE_FIELDS = (
    "null_model",
    "observed_mean_entropy",
    "null_mean_entropy",
    "delta_observed_minus_null",
    "one_sided_empirical_p_lower",
    "holm_adjusted_p_across_null_models",
    "fixed_interval_resampling_delta_ci95",
)

_PREFERRED_INTERVAL_FIELDS = (
    "interval_index",
    "start",
    "stop",
    "prime_count",
    "gap_count",
    "mean_gap",
    "tie_aware_normalized_permutation_entropy_m5",
)


class ContestPlanEmbeddedEvidenceError(RuntimeError):
    """Raised when declared preexperiment evidence fails byte verification."""


@dataclass(frozen=True)
class ContestPlanEmbeddedEvidenceBundle:
    """Public report content plus private manifest provenance bindings."""

    payload: dict[str, Any]
    manifest_bindings: tuple[dict[str, Any], ...]


def build_contest_plan_embedded_evidence(
    preexperiment_artifact: BaseModel | Mapping[str, Any] | Path | str | object,
    *,
    artifact_path: Path | str | None = None,
    preexperiment_root: Path | str | None = None,
) -> ContestPlanEmbeddedEvidenceBundle | None:
    """Build tables and a plot specification from completed verified evidence.

    ``None`` means that no completed, reportable numeric preexperiment was
    supplied.  A declared hash mismatch is never treated as absence: it raises
    and prevents publication.
    """

    artifact, loaded_artifact_path = _load_artifact(
        preexperiment_artifact,
        explicit_path=artifact_path,
    )
    status = str(artifact.get("status", "")).strip().lower()
    if status not in _COMPLETED_STATUSES:
        return None

    root = _evidence_root(
        artifact=artifact,
        artifact_path=loaded_artifact_path,
        explicit_root=preexperiment_root,
    )
    if loaded_artifact_path is not None:
        _verify_artifact_semantic_hash(artifact)

    metrics, metrics_path = _load_metrics(artifact, root=root)
    if metrics is None:
        return None

    bindings: list[dict[str, Any]] = []
    if loaded_artifact_path is not None:
        bindings.append(_binding("preexperiment_artifact", loaded_artifact_path))
    if metrics_path is not None:
        bindings.append(_binding("preexperiment_metrics", metrics_path))
    bindings.extend(_verified_manifest_bindings(artifact, root=root))
    bindings = _deduplicate_bindings(bindings)

    tables = _derive_tables(metrics)
    if not tables:
        return None
    figures = _derive_figures(tables)
    analysis = _derive_overall_analysis(tables)
    interval_count = _infer_interval_count(metrics)
    study_phase = str(artifact.get("study_phase", "")).strip()
    payload: dict[str, Any] = {
        "schema_version": "contest-plan-embedded-evidence-v1",
        "section_title_zh": "真实预实验数据、图表与分析",
        "execution_label_zh": _study_phase_label(study_phase),
        "summary_zh": (
            f"本节直接汇总已真实执行的{_study_phase_label(study_phase)}结果"
            f"{f'（{interval_count} 个固定分析单元）' if interval_count else ''}。"
            "表格与图中的数值由程序从已核验结果确定性投影，未由语言模型补写。"
        ),
        "tables": tables,
        "figures": figures,
        "analysis_zh": analysis,
        "scope_note_zh": _scope_note(artifact, metrics),
    }
    # Guard the public document against accidentally leaking an implementation
    # file reference.  Provenance belongs only in ``manifest_bindings``.
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if re.search(r"(?:[A-Za-z]:[/\\]|\.\./|(?:^|[/\\])(?:raw|logs?|null)[/\\])", serialized):
        raise ContestPlanEmbeddedEvidenceError(
            "public embedded evidence unexpectedly contains a local artifact path"
        )
    return ContestPlanEmbeddedEvidenceBundle(
        payload=payload,
        manifest_bindings=tuple(bindings),
    )


def _load_artifact(
    value: BaseModel | Mapping[str, Any] | Path | str | object,
    *,
    explicit_path: Path | str | None,
) -> tuple[dict[str, Any], Path | None]:
    path = Path(explicit_path).resolve() if explicit_path is not None else None
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    elif isinstance(value, Path) or (isinstance(value, str) and not value.lstrip().startswith("{")):
        path = Path(value).resolve()
        payload = _read_json(path)
    elif isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ContestPlanEmbeddedEvidenceError("preexperiment artifact must be a JSON object")
        payload = parsed
    elif hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if not isinstance(dumped, dict):
            raise ContestPlanEmbeddedEvidenceError("preexperiment model dump must be an object")
        payload = dumped
    else:
        # Test seams and future adapters may expose only execution metadata.  An
        # incomplete object is absence, never license to invent report data.
        payload = {
            key: _json_compatible(getattr(value, key))
            for key in (
                "status",
                "study_phase",
                "aggregate_results",
                "interval_results",
                "metrics_relative_path",
                "metrics_sha256",
                "manifest_relative_path",
                "manifest_sha256",
            )
            if hasattr(value, key)
        }
    if path is not None:
        disk_payload = _read_json(path)
        if set(disk_payload) - {"output_path"} and _has_reportable_metrics(disk_payload):
            payload = disk_payload
    return payload, path


def _json_compatible(value: Any) -> Any:
    """Normalize lightweight adapter/test objects without inventing fields."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_json_compatible(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_compatible(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return value


def _evidence_root(
    *,
    artifact: Mapping[str, Any],
    artifact_path: Path | None,
    explicit_root: Path | str | None,
) -> Path | None:
    if explicit_root is not None:
        return Path(explicit_root).resolve()
    if artifact_path is not None:
        return artifact_path.parent.resolve()
    output_path = artifact.get("output_path")
    if isinstance(output_path, str) and output_path.strip():
        return Path(output_path).resolve().parent
    return None


def _verify_artifact_semantic_hash(artifact: Mapping[str, Any]) -> None:
    recorded = artifact.get("artifact_hash")
    if recorded is None:
        return
    if not isinstance(recorded, str) or _SHA256.fullmatch(recorded) is None:
        raise ContestPlanEmbeddedEvidenceError("preexperiment artifact hash is invalid")
    candidates = (
        {key: value for key, value in artifact.items() if key != "artifact_hash"},
        {
            key: value
            for key, value in artifact.items()
            if key not in {"artifact_hash", "output_path"}
        },
    )
    if recorded not in {canonical_model_hash(candidate) for candidate in candidates}:
        raise ContestPlanEmbeddedEvidenceError("preexperiment artifact hash does not replay")


def _load_metrics(
    artifact: Mapping[str, Any],
    *,
    root: Path | None,
) -> tuple[dict[str, Any] | None, Path | None]:
    relative = artifact.get("metrics_relative_path")
    if isinstance(relative, str) and relative.strip() and root is not None:
        path = _resolve_under_root(relative, root=root)
        expected = artifact.get("metrics_sha256")
        _verify_declared_file(path, expected_sha256=expected)
        return _read_json(path), path
    for key in ("metrics", "aggregate_metrics", "analysis_metrics"):
        candidate = artifact.get(key)
        if isinstance(candidate, Mapping):
            return dict(candidate), None
    if _has_reportable_metrics(artifact):
        return dict(artifact), None
    return None, None


def _verified_manifest_bindings(
    artifact: Mapping[str, Any],
    *,
    root: Path | None,
) -> list[dict[str, Any]]:
    if root is None:
        return []
    relative = artifact.get("manifest_relative_path")
    if not isinstance(relative, str) or not relative.strip():
        return []
    manifest_path = _resolve_under_root(relative, root=root)
    _verify_declared_file(
        manifest_path,
        expected_sha256=artifact.get("manifest_sha256"),
    )
    manifest = _read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, Sequence) or isinstance(files, str | bytes):
        raise ContestPlanEmbeddedEvidenceError("preexperiment manifest lacks a file inventory")
    bindings = [_binding("preexperiment_manifest", manifest_path)]
    for record in files:
        if not isinstance(record, Mapping):
            raise ContestPlanEmbeddedEvidenceError("preexperiment manifest file record is invalid")
        relative_path = record.get("relative_path")
        expected_sha = record.get("sha256")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ContestPlanEmbeddedEvidenceError("preexperiment manifest path is invalid")
        path = _resolve_under_root(relative_path, root=root)
        _verify_declared_file(path, expected_sha256=expected_sha)
        expected_size = record.get("bytes", record.get("size_bytes"))
        if isinstance(expected_size, int) and path.stat().st_size != expected_size:
            raise ContestPlanEmbeddedEvidenceError(
                f"preexperiment evidence size mismatch: {relative_path}"
            )
        bindings.append(
            _binding(
                "preexperiment_" + str(record.get("kind", "evidence")),
                path,
            )
        )
    return bindings


def _derive_tables(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    aggregate_rows = _mapping_rows(metrics.get("aggregate_results"))
    if aggregate_rows:
        columns = _available_columns(aggregate_rows, _PREFERRED_AGGREGATE_FIELDS)
        if len(columns) >= 2:
            interval_counts = {
                int(value)
                for row in aggregate_rows
                if (value := _finite_number(row.get("interval_count"))) is not None
            }
            draw_counts = {
                int(value)
                for row in aggregate_rows
                if (value := _finite_number(row.get("draw_count"))) is not None
            }
            sampling_note = ""
            if len(interval_counts) == 1 and len(draw_counts) == 1:
                sampling_note = (
                    f" 汇总覆盖 {next(iter(interval_counts))} 个固定分析单元，"
                    f"每类零模型使用 {next(iter(draw_counts))} 次抽样。"
                )
            tables.append(
                _table(
                    table_id="aggregate-comparison",
                    title="预实验总体对照结果",
                    columns=columns,
                    rows=aggregate_rows,
                    caption=(
                        "真实观测与各零模型的汇总比较。差值定义为真实观测值减零模型均值；"
                        "负值表示真实序列的指标低于相应零模型。" + sampling_note
                    ),
                    analysis=_aggregate_analysis(aggregate_rows),
                )
            )

    interval_rows = _flatten_interval_rows(_mapping_rows(metrics.get("interval_results")))
    if interval_rows:
        columns = _available_columns(interval_rows, _PREFERRED_INTERVAL_FIELDS)
        if len(columns) >= 2:
            tables.append(
                _table(
                    table_id="analysis-unit-summary",
                    title="各固定分析单元的原始观测摘要",
                    columns=columns,
                    rows=interval_rows,
                    caption="每行对应一个预先固定的分析单元，直接列出样本规模与主要观测指标。",
                    analysis=_interval_analysis(interval_rows),
                )
            )

    if tables:
        return tables
    generic = _generic_rows(metrics)
    if generic:
        columns = _generic_columns(generic)
        if columns:
            tables.append(
                _table(
                    table_id="verified-metric-summary",
                    title="预实验核验指标摘要",
                    columns=columns,
                    rows=generic,
                    caption="程序从已核验预实验结果中投影的主要标量指标。",
                    analysis="这些数值仅描述本次已执行的探索性预实验，不自动构成总体推断。",
                )
            )
    return tables


def _derive_figures(tables: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    aggregate = next(
        (table for table in tables if table.get("table_id") == "aggregate-comparison"),
        None,
    )
    if aggregate is None:
        return []
    rows = aggregate.get("rows")
    if not isinstance(rows, Sequence):
        return []
    series: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        value = _finite_number(raw.get("delta_observed_minus_null"))
        label = raw.get("null_model")
        if value is None or not isinstance(label, str) or not label.strip():
            continue
        item: dict[str, Any] = {"label": label, "value": value}
        interval = raw.get("fixed_interval_resampling_delta_ci95")
        if (
            isinstance(interval, Sequence)
            and not isinstance(interval, str | bytes)
            and len(interval) == 2
        ):
            lower = _finite_number(interval[0])
            upper = _finite_number(interval[1])
            if lower is not None and upper is not None and lower <= value <= upper:
                item.update({"lower": lower, "upper": upper})
        series.append(item)
    if not series:
        return []
    return [
        {
            "figure_id": "observed-minus-null-interval-plot",
            "kind": "horizontal_interval_plot",
            "title_zh": "真实观测与零模型差值",
            "x_label_zh": "真实观测值－零模型均值",
            "series": series,
            "caption_zh": (
                "点表示各零模型下的汇总差值，横线表示固定分析单元重采样得到的描述性范围；"
                "竖直零线表示真实值与零模型均值无差异。"
            ),
            "analysis_zh": _aggregate_analysis(
                [row for row in rows if isinstance(row, Mapping)]
            ),
        }
    ]


def _table(
    *,
    table_id: str,
    title: str,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    caption: str,
    analysis: str,
) -> dict[str, Any]:
    projected_rows = [
        {key: _json_scalar_or_pair(row.get(key)) for key in columns}
        for row in rows[:12]
    ]
    return {
        "table_id": table_id,
        "title_zh": title,
        "columns": [{"key": key, "label_zh": _field_label(key)} for key in columns],
        "rows": projected_rows,
        "caption_zh": caption,
        "analysis_zh": analysis,
    }


def _flatten_interval_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        observed = item.pop("observed_metrics", None)
        if isinstance(observed, Mapping):
            item.update(
                {
                    str(key): value
                    for key, value in observed.items()
                    if _is_scalar(value)
                }
            )
        flattened.append(item)
    return flattened


def _mapping_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _available_columns(
    rows: Sequence[Mapping[str, Any]],
    preferred: Sequence[str],
) -> list[str]:
    return [key for key in preferred if any(_is_reportable_value(row.get(key)) for row in rows)]


def _generic_rows(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[tuple[int, list[dict[str, Any]]]] = []
    for _key, value in metrics.items():
        rows = _mapping_rows(value)
        if not rows:
            continue
        score = sum(
            1
            for row in rows
            for field, item in row.items()
            if _is_reportable_column(field) and _is_scalar(item)
        )
        candidates.append((score, rows))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    scalar = {
        str(key): value
        for key, value in metrics.items()
        if _is_reportable_column(str(key)) and _is_scalar(value)
    }
    return [scalar] if scalar else []


def _generic_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    frequencies: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if _is_reportable_column(str(key)) and _is_scalar(value):
                frequencies[str(key)] = frequencies.get(str(key), 0) + 1
    ordered = sorted(
        frequencies,
        key=lambda key: (-frequencies[key], key),
    )
    return ordered[:8]


def _aggregate_analysis(rows: Sequence[Mapping[str, Any]]) -> str:
    comparisons: list[tuple[str, float]] = []
    raw_ps: list[float] = []
    adjusted_ps: list[float] = []
    for row in rows:
        label = row.get("null_model")
        delta = _finite_number(row.get("delta_observed_minus_null"))
        if isinstance(label, str) and delta is not None:
            comparisons.append((label, delta))
        raw_p = _finite_number(row.get("one_sided_empirical_p_lower"))
        adjusted_p = _finite_number(row.get("holm_adjusted_p_across_null_models"))
        if raw_p is not None:
            raw_ps.append(raw_p)
        if adjusted_p is not None:
            adjusted_ps.append(adjusted_p)
    if not comparisons:
        return "表中数值是本次预实验的直接汇总，解释范围不得超出已执行设计。"
    strongest = max(comparisons, key=lambda item: abs(item[1]))
    weakest = min(comparisons, key=lambda item: abs(item[1]))
    directions = {"负" if value < 0 else "正" if value > 0 else "零" for _, value in comparisons}
    direction_text = (
        "所有差值方向一致且为负"
        if directions == {"负"}
        else "所有差值方向一致且为正"
        if directions == {"正"}
        else "不同对照的差值方向并不完全一致"
    )
    p_text = ""
    if raw_ps:
        p_text = f"；单侧经验 p 值范围为 {_format_number(min(raw_ps))}–{_format_number(max(raw_ps))}"
    if adjusted_ps:
        p_text += f"，跨零模型 Holm 校正 p 值范围为 {_format_number(min(adjusted_ps))}–{_format_number(max(adjusted_ps))}"
    return (
        f"{direction_text}。绝对差值最大的是{_human_value(strongest[0])}"
        f"（{_format_number(strongest[1])}），最接近零的是{_human_value(weakest[0])}"
        f"（{_format_number(weakest[1])}）{p_text}。差值缩小只能说明相应对照解释了更多"
        "已观察结构，不能单凭预实验推出新的普适机制。"
    )


def _interval_analysis(rows: Sequence[Mapping[str, Any]]) -> str:
    values = [
        number
        for row in rows
        if (
            number := _finite_number(
                row.get("tie_aware_normalized_permutation_entropy_m5")
                or row.get("observed_entropy")
            )
        )
        is not None
    ]
    counts = [
        number
        for row in rows
        if (number := _finite_number(row.get("gap_count", row.get("sample_count"))))
        is not None
    ]
    parts = [f"共汇总 {len(rows)} 个固定分析单元。"]
    if values:
        parts.append(
            f"主要观测指标范围为 {_format_number(min(values))}–{_format_number(max(values))}。"
        )
    if counts:
        parts.append(
            f"各单元样本量范围为 {int(min(counts)):,}–{int(max(counts)):,}。"
        )
    parts.append("这些单元是固定计算基准而非从总体随机抽样，跨单元变化只作描述性解释。")
    return "".join(parts)


def _derive_overall_analysis(tables: Sequence[Mapping[str, Any]]) -> str:
    analyses = [
        str(table.get("analysis_zh", "")).strip()
        for table in tables
        if str(table.get("analysis_zh", "")).strip()
    ]
    return " ".join(analyses)


def _scope_note(artifact: Mapping[str, Any], metrics: Mapping[str, Any]) -> str:
    for source in (artifact, metrics):
        value = source.get("scientific_boundary_zh")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return (
        "本节仅报告已执行的探索性预实验。未执行的正式实验、总体外推、因果解释或数学证明"
        "均不属于这些表图能够支持的结论。"
    )


def _study_phase_label(value: str) -> str:
    labels = {
        "exploratory_pilot": "探索性预实验",
        "pilot": "预实验",
        "preexperiment": "预实验",
    }
    return labels.get(value, "预实验")


def _infer_interval_count(metrics: Mapping[str, Any]) -> int | None:
    rows = _mapping_rows(metrics.get("interval_results"))
    if rows:
        return len(rows)
    aggregate = _mapping_rows(metrics.get("aggregate_results"))
    counts = {
        int(value)
        for row in aggregate
        if (value := _finite_number(row.get("interval_count"))) is not None
    }
    return next(iter(counts)) if len(counts) == 1 else None


def _field_label(key: str) -> str:
    if key in _FIELD_LABELS_ZH:
        return _FIELD_LABELS_ZH[key]
    tokens = [token for token in re.split(r"[_\-]+", key) if token]
    words = {
        "observed": "观测",
        "null": "零模型",
        "mean": "均值",
        "median": "中位数",
        "entropy": "熵",
        "effect": "效应",
        "adjusted": "校正",
        "empirical": "经验",
        "lower": "下界",
        "upper": "上界",
        "count": "数量",
        "rate": "比例",
        "accuracy": "准确率",
        "loss": "损失",
        "score": "得分",
    }
    translated = [words.get(token.lower()) for token in tokens]
    if not translated or any(token is None for token in translated):
        # A future adapter may use domain-specific machine field names.  Keep
        # those exact keys in the JSON evidence schema, but never leak an
        # untranslated implementation token into the Chinese report header.
        return "预实验数值指标"
    return "".join(token for token in translated if token is not None)


def _human_value(value: str) -> str:
    labels = {
        "global_permutation": "全局置换零模型",
        "local_block_permutation": "局部分块置换零模型",
        "residue_path_conditioned_permutation": "残基路径条件置换零模型",
        "wheel_210": "wheel-210 可除性约束零模型",
        "hardy_littlewood_ktuple_generative_null": "Hardy–Littlewood k-tuple 生成式零模型",
    }
    return labels.get(value, value.replace("_", " "))


def _json_scalar_or_pair(value: Any) -> Any:
    if _is_scalar(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes) and len(value) == 2:
        pair = [_finite_number(value[0]), _finite_number(value[1])]
        return pair if all(item is not None for item in pair) else None
    return None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _is_reportable_value(value: Any) -> bool:
    return _is_scalar(value) or (
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and len(value) == 2
        and all(_finite_number(item) is not None for item in value)
    )


def _is_reportable_column(key: str) -> bool:
    normalized = key.lower()
    return not any(part in normalized for part in _EXCLUDED_COLUMN_PARTS)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _format_number(value: float) -> str:
    absolute = abs(value)
    if absolute != 0 and (absolute < 0.0001 or absolute >= 1_000_000):
        return f"{value:.3e}"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _has_reportable_metrics(value: Mapping[str, Any]) -> bool:
    return any(
        bool(_mapping_rows(value.get(key)))
        for key in ("aggregate_results", "interval_results")
    ) or any(
        isinstance(value.get(key), Mapping)
        for key in ("metrics", "aggregate_metrics", "analysis_metrics")
    )


def _resolve_under_root(value: str | Path, *, root: Path) -> Path:
    candidate = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContestPlanEmbeddedEvidenceError(
            "preexperiment evidence path escapes its root"
        ) from exc
    return candidate


def _verify_declared_file(path: Path, *, expected_sha256: Any) -> None:
    if not path.is_file():
        raise ContestPlanEmbeddedEvidenceError(f"declared preexperiment file is missing: {path}")
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise ContestPlanEmbeddedEvidenceError(f"declared SHA-256 is invalid: {path.name}")
    if _sha256_file(path) != expected_sha256:
        raise ContestPlanEmbeddedEvidenceError(f"preexperiment file SHA-256 mismatch: {path.name}")


def _binding(role: str, path: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": path.resolve().as_posix(),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _deduplicate_bindings(bindings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        path = str(binding["path"])
        existing = by_path.get(path)
        candidate = dict(binding)
        if existing is None or str(candidate["role"]) < str(existing["role"]):
            by_path[path] = candidate
    return [by_path[path] for path in sorted(by_path)]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestPlanEmbeddedEvidenceError(f"invalid preexperiment JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ContestPlanEmbeddedEvidenceError(f"preexperiment JSON must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ContestPlanEmbeddedEvidenceBundle",
    "ContestPlanEmbeddedEvidenceError",
    "build_contest_plan_embedded_evidence",
]
