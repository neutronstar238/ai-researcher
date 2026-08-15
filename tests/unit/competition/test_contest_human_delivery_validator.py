from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import autoresearch.competition.contest_human_delivery_validator as validator_module
from autoresearch.competition.contest_human_delivery_validator import (
    HumanDeliveryValidationError,
    validate_human_research_plan_delivery,
    validate_runner_human_delivery,
)
from autoresearch.kernel.contracts import canonical_sha256


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(path: Path, *, filename: str | None = None) -> dict[str, Any]:
    return {
        "filename": filename or path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _evidence() -> dict[str, Any]:
    analysis = "真实值低于零模型，但该探索性差异仅用于收缩后续假设，不能外推为普适规律。"
    return {
        "schema_version": "contest-plan-embedded-evidence-v1",
        "execution_label_zh": "探索性预实验",
        "summary_zh": "本节汇总真实执行的探索性预实验。",
        "analysis_zh": analysis,
        "scope_note_zh": "固定分析单元仅作描述性解释。",
        "tables": [
            {
                "table_id": "summary",
                "title_zh": "预实验总体对照结果",
                "columns": [
                    {"key": "model", "label_zh": "零模型"},
                    {"key": "delta", "label_zh": "差值"},
                ],
                "rows": [{"model": "条件置换零模型", "delta": -0.01}],
                "caption_zh": "真实观测与零模型比较。",
                "analysis_zh": analysis,
            }
        ],
        "figures": [
            {
                "figure_id": "interval",
                "kind": "horizontal_interval_plot",
                "title_zh": "真实观测与零模型差值",
                "x_label_zh": "差值",
                "series": [
                    {
                        "label": "条件置换零模型",
                        "lower": -0.02,
                        "value": -0.01,
                        "upper": -0.005,
                    }
                ],
                "caption_zh": "点为差值，横线为描述性范围。",
                "analysis_zh": analysis,
            }
        ],
    }


def _build_delivery(
    tmp_path: Path,
    *,
    pilot: bool = True,
    reference_count: int = 5,
    mutate_public: Callable[[dict[str, Any]], None] | None = None,
    mutate_source: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, tuple[str, ...]]:
    plan = tmp_path / "delivery" / "plan"
    private = plan / "_private"
    private.mkdir(parents=True)
    references = tuple(
        f"研究者甲. 真实检索论文 {index}. URL：https://example.org/paper-{index}"
        for index in range(1, reference_count + 1)
    )
    evidence = _evidence() if pilot else None
    results = (
        "真实探索性预实验观察到小幅差异，结果只用于修订下一轮研究计划。"
        if pilot
        else "尚未执行预实验；本计划不报告任何观察数值。"
    )
    public: dict[str, Any] = {
        "document_type": "科学假设与研究计划",
        "title": "自包含研究计划验收样例",
        "abstract": "本计划给出可检验问题、方法和边界。",
        "problem_statement": "当前证据不足以区分两个竞争解释。",
        "rationale": "使用真实检索证据和可复核计算进行初步检验。",
        "technical_details": "先计算描述性指标，再用条件零模型比较。",
        "datasets": {"source": "公开数据", "target": "预注册指标"},
        "methods": "采用确定性分析和预注册对照。",
        "experiments": {
            "steps": "按预注册步骤执行。",
            "baselines": "条件置换零模型",
            "metrics": "归一化差值",
        },
        "results": results,
        "references": list(references),
        "preexperiment_summary": {
            "executed": pilot,
            "study_phase_zh": "探索性预实验" if pilot else "尚未执行预实验",
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
        },
    }
    if evidence is not None:
        public["embedded_evidence"] = evidence
    source = dict(public)
    source["references"] = list(references)
    if mutate_public is not None:
        mutate_public(public)
    if mutate_source is not None:
        mutate_source(source)

    json_path = plan / "research-plan.json"
    markdown_path = plan / "research-plan.md"
    tex_path = plan / "research-plan.tex"
    pdf_path = plan / "research-plan.pdf"
    source_path = private / "research-plan-source.json"
    json_path.write_text(json.dumps(public, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    source_path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    if pilot:
        markdown = (
            "# 自包含研究计划验收样例\n\n## 参考论文\n\n"
            "### 表 1 预实验总体对照结果\n\n| 零模型 | 差值 |\n|---|---|\n"
            "| 条件置换零模型 | -0.01 |\n\n**表格分析：** 真实差异只作描述性解释。\n\n"
            "### 图 1 真实观测与零模型差值\n\n<svg><circle /></svg>\n\n"
            "**图形分析：** 图中差异只用于修订假设。\n"
        )
        tex = (
            "自包含研究计划验收样例 参考论文 预实验总体对照结果 "
            r"\begin{table}结果\end{table} "
            "真实观测与零模型差值 "
            r"\begin{tikzpicture}\end{tikzpicture}"
        )
    else:
        markdown = "# 自包含研究计划验收样例\n\n尚未执行预实验。\n\n## 参考论文\n"
        tex = "自包含研究计划验收样例 尚未执行预实验 参考论文"
    markdown_path.write_text(markdown, encoding="utf-8")
    tex_path.write_text(tex, encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-1.7\nvalidator deterministic fixture\n")

    bindings: list[dict[str, Any]] = []
    if pilot:
        evidence_root = tmp_path / "verified-pilot"
        evidence_root.mkdir()
        metrics = evidence_root / "metrics.data"
        artifact = evidence_root / "execution.data"
        metrics.write_text('{"delta":-0.01}\n', encoding="utf-8")
        artifact.write_text('{"status":"completed"}\n', encoding="utf-8")
        bindings = [
            {"role": "preexperiment_metrics", "path": metrics.as_posix(), **_binding(metrics)},
            {
                "role": "preexperiment_artifact",
                "path": artifact.as_posix(),
                **_binding(artifact),
            },
        ]
        for item in bindings:
            item.pop("filename")

    manifest = {
        "schema_version": "contest-direct-plan-render-v3",
        "source_payload_sha256": canonical_sha256(source),
        "public_payload_sha256": canonical_sha256(public),
        "reference_projection_version": "bibliographic-display-v2",
        "display_references": list(references),
        "display_references_sha256": canonical_sha256(
            {"display_references": list(references)}
        ),
        "embedded_evidence": {
            "present": pilot,
            "content_sha256": canonical_sha256(evidence) if evidence is not None else None,
            "table_count": 1 if pilot else 0,
            "figure_count": 1 if pilot else 0,
            "provenance_bindings": bindings,
            "provenance_bindings_sha256": canonical_sha256(
                {"evidence_bindings": bindings}
            ),
        },
        "compile_status": "compiled",
        "pdf_text_verified": True,
        "artifacts": {
            "json": _binding(json_path),
            "markdown": _binding(markdown_path),
            "tex": _binding(tex_path),
            "pdf": _binding(pdf_path),
            "source": _binding(source_path, filename="_private/research-plan-source.json"),
        },
    }
    (plan / "research-plan-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return plan, references


@pytest.fixture
def _pdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validator_module,
        "_extract_pdf_text",
        lambda _path: (
            "自包含研究计划验收样例 参考论文 "
            "预实验总体对照结果 真实观测与零模型差值"
        ),
    )


def test_completed_pilot_delivery_passes_all_human_contracts(
    tmp_path: Path, _pdf_text: None
) -> None:
    plan, references = _build_delivery(tmp_path)

    report = validate_human_research_plan_delivery(
        plan,
        locked_reference_catalog=(*references, "额外真实文献. URL：https://example.org/extra"),
        pilot_executed=True,
    )

    assert report.to_dict() == {
        "schema_version": "contest-human-delivery-validation-v1",
        "status": "accepted",
        "reference_count": 5,
        "pilot_executed": True,
        "table_count": 1,
        "figure_count": 1,
        "provenance_binding_count": 2,
        "bibliography_binding": "caller-locked-catalog",
    }


def test_manifest_projection_is_a_valid_fallback_binding_and_runner_locator_works(
    tmp_path: Path, _pdf_text: None
) -> None:
    plan, _references = _build_delivery(tmp_path)
    result = {
        "status": "completed",
        "preexperiment_executed": True,
        "artifacts": {"rendered_plan": {"pdf": {"path": (plan / "research-plan.pdf").as_posix()}}},
        # A real delivery report also carries inventory-relative filenames.
        # They are metadata, not alternate plan roots resolved against CWD.
        "file_inventory": [{"relative_path": "plan/research-plan.json"}],
    }

    report = validate_runner_human_delivery(output_dir=tmp_path / "delivery", result=result)

    assert report.bibliography_binding == "manifest-source-projection"


def test_sparse_or_unlocked_bibliography_cannot_be_delivered(
    tmp_path: Path, _pdf_text: None
) -> None:
    sparse, _ = _build_delivery(tmp_path / "sparse", reference_count=4)
    with pytest.raises(HumanDeliveryValidationError, match="5–10"):
        validate_human_research_plan_delivery(sparse, pilot_executed=True)

    unlocked, references = _build_delivery(tmp_path / "unlocked")
    with pytest.raises(HumanDeliveryValidationError, match="locked real catalog"):
        validate_human_research_plan_delivery(
            unlocked,
            pilot_executed=True,
            locked_reference_catalog=(*references[:4], "其他文献. URL：https://example.org/other"),
        )


@pytest.mark.parametrize(
    "leak",
    (
        "run_id=secret-run",
        "E:/private/metrics.data",
        "artifact_hash=" + "a" * 64,
        "global_permutation",
        "metrics.json",
    ),
)
def test_public_representations_reject_internal_leaks(
    tmp_path: Path, _pdf_text: None, leak: str
) -> None:
    plan, _ = _build_delivery(
        tmp_path,
        mutate_public=lambda payload: payload.__setitem__(
            "results", f"{payload['results']} {leak}"
        ),
    )

    with pytest.raises(HumanDeliveryValidationError, match="public JSON exposes"):
        validate_human_research_plan_delivery(plan, pilot_executed=True)


def test_completed_pilot_requires_real_table_figure_analysis_and_private_provenance(
    tmp_path: Path, _pdf_text: None
) -> None:
    def remove_figure(payload: dict[str, Any]) -> None:
        payload["embedded_evidence"]["figures"] = []

    plan, _ = _build_delivery(
        tmp_path,
        mutate_public=remove_figure,
        mutate_source=remove_figure,
    )
    manifest_path = plan / "research-plan-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = json.loads((plan / "_private" / "research-plan-source.json").read_text(encoding="utf-8"))
    manifest["embedded_evidence"]["content_sha256"] = canonical_sha256(
        source["embedded_evidence"]
    )
    manifest["embedded_evidence"]["figure_count"] = 0
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(HumanDeliveryValidationError, match="at least one summary table"):
        validate_human_research_plan_delivery(plan, pilot_executed=True)


def test_no_pilot_branch_is_honest_and_never_fabricates_evidence(
    tmp_path: Path, _pdf_text: None
) -> None:
    plan, _ = _build_delivery(tmp_path, pilot=False)
    report = validate_human_research_plan_delivery(plan, pilot_executed=False)
    assert report.pilot_executed is False
    assert report.table_count == report.figure_count == 0

    with pytest.raises(HumanDeliveryValidationError, match="states disagree"):
        validate_human_research_plan_delivery(plan, pilot_executed=True)


def test_tampered_private_source_is_rejected_before_completion(
    tmp_path: Path, _pdf_text: None
) -> None:
    plan, _ = _build_delivery(tmp_path)
    source = plan / "_private" / "research-plan-source.json"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(HumanDeliveryValidationError, match="differs from its manifest binding"):
        validate_human_research_plan_delivery(plan, pilot_executed=True)
