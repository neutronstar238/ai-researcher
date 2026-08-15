from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
)
from autoresearch.competition.system_plan_ideation import ResearchDirectionCandidate
from autoresearch.competition.system_plan_preexperiment import (
    PreexperimentInterpretation,
    SystemPlanPreexperimentError,
    run_system_plan_preexperiment,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from tests.unit.competition.test_system_plan_ideation import (
    _component_experiment_binding,
    _literature,
    _opportunity_binding,
    _portfolio,
)


def _binding_and_direction() -> tuple[Any, ResearchDirectionCandidate]:
    literature = _literature()
    binding = _component_experiment_binding(
        opportunity_map=_opportunity_binding(),
        literature=literature,
        retrieved_catalog=literature,
    )
    direction = ResearchDirectionCandidate.model_validate(
        _portfolio(literature=literature, retrieved_catalog=literature)["directions"][0]
    )
    return binding, direction


def _panel(binding: Any) -> dict[str, Any]:
    return {
        "systems": [
            {
                "system_name": item.system_name,
                "data_type": item.data_type,
                "artifact_paths": {
                    "clean": f"processed/{item.system_name}/clean.npz",
                    "snr_20": f"processed/{item.system_name}/snr_20.npz",
                },
                "artifact_sha256": {"clean": "a" * 64, "snr_20": "b" * 64},
            }
            for item in binding.prospective_components.target_aliases
        ],
        "conditions": ["clean", "snr_20"],
        "seeds": [17, 29],
    }


def _identity(panel: dict[str, Any], output_root: Path) -> OfficialDevelopmentIdentity:
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "1" * 64,
        "development_panel_hash": canonical_model_hash(panel),
        "sealed_confirmation_panel_hash": "2" * 64,
        "runner_sha256": "3" * 64,
        "runtime_environment_hash": "4" * 64,
        "image_id": "sha256:" + "5" * 64,
        "data_root": output_root.as_posix(),
        "initial_candidate_count": 1,
        "pilot_system_count": 2,
        "full_system_count": len(panel["systems"]),
        "conditions": tuple(panel["conditions"]),
        "seeds": tuple(panel["seeds"]),
        "maximum_official_cells_total": 20,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": "2026-08-10T00:00:00Z",
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _install_execution_doubles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    panel: dict[str, Any],
    fail_all: bool = False,
) -> None:
    import autoresearch.competition.system_plan_preexperiment as module

    def fake_freeze(**kwargs: Any) -> tuple[OfficialDevelopmentIdentity, dict[str, Any]]:
        root = Path(kwargs["output_dir"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        (root / "runner").mkdir(exist_ok=True)
        (root / "runner" / "scientific_contract_official_runner.py").write_text(
            "# pinned runner\n", encoding="utf-8"
        )
        return _identity(panel, root), panel

    def fake_build(**kwargs: Any) -> tuple[OfficialCellSpec, ...]:
        specs: list[OfficialCellSpec] = []
        for system in kwargs["systems"]:
            payload = {
                "attempt_id": f"baseline-operon_or_pdefind-{system['system_name']}-clean-17",
                "method_kind": "baseline",
                "candidate_id": "operon_or_pdefind",
                "stage": "baseline",
                "system_name": system["system_name"],
                "data_type": system["data_type"],
                "condition": "clean",
                "seed": 17,
                "data_relative_path": system["artifact_paths"]["clean"],
                "data_sha256": system["artifact_sha256"]["clean"],
                "candidate_source_sha256": None,
            }
            payload["spec_hash"] = canonical_model_hash(payload)
            specs.append(OfficialCellSpec.model_validate(payload))
        return tuple(specs)

    def fake_execute(**kwargs: Any) -> tuple[OfficialCellResult, ...]:
        root = Path(kwargs["output_dir"])
        results: list[OfficialCellResult] = []
        for index, spec in enumerate(kwargs["specs"], 1):
            succeeded = not fail_all
            raw: dict[str, Any] = {
                "status": "succeeded" if succeeded else "failed",
                "derivative_nmse": 0.125 * index if succeeded else None,
                "validation_nmse": 0.0625 * index if succeeded else None,
                "selected_term_count": 3 + index if succeeded else None,
                "equation_changed_on_shuffled_training": True if succeeded else None,
                "maximum_equation_prediction_delta": 0.5 if succeeded else None,
                "wall_time_seconds": 1.25 * index,
                "failure_reason": None if succeeded else "diagnostic failure",
                "spec_hash": spec.spec_hash,
            }
            raw["result_hash"] = canonical_model_hash(raw)
            result_path = root / "cells" / "baseline" / spec.attempt_id / "result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
            results.append(
                OfficialCellResult(
                    attempt_id=spec.attempt_id,
                    method_kind=spec.method_kind,
                    candidate_id=spec.candidate_id,
                    stage=spec.stage,
                    system_name=spec.system_name,
                    data_type=spec.data_type,
                    condition=spec.condition,
                    seed=spec.seed,
                    status=raw["status"],
                    derivative_nmse=raw["derivative_nmse"],
                    validation_nmse=raw["validation_nmse"],
                    selected_term_count=raw["selected_term_count"],
                    equation_changed_on_shuffled_training=raw[
                        "equation_changed_on_shuffled_training"
                    ],
                    maximum_equation_prediction_delta=raw[
                        "maximum_equation_prediction_delta"
                    ],
                    wall_time_seconds=raw["wall_time_seconds"],
                    failure_reason=raw["failure_reason"],
                    result_hash=raw["result_hash"],
                )
            )
        return tuple(results)

    monkeypatch.setattr(module, "freeze_official_identity", fake_freeze)
    monkeypatch.setattr(module, "build_official_cell_specs", fake_build)
    monkeypatch.setattr(module, "execute_official_stage", fake_execute)


class _InterpretationStub:
    def __init__(
        self,
        *,
        invent_number: bool = False,
        reasoning_text: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.invent_number = invent_number
        self.reasoning_text = reasoning_text

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        task = json.loads(kwargs["messages"][-1]["content"])
        lines = task["evidence_lines_zh"]
        extra = "并额外提高百分之九十九。" if self.invent_number else ""
        if self.invent_number:
            extra = "并额外提高99%。"
        supported = task["mechanical_limited_feasibility_supported"]
        payload = {
            "feasibility_conclusion_zh": (
                (
                    "真实沙箱中的固定基线至少完成了一个公开目标单元，因此数据读取、"
                    "指标计算和隔离执行链在该有限范围内具备可运行性。"
                )
                if supported
                else (
                    "真实沙箱中的固定基线没有完成任何公开目标单元，因此当前范围的"
                    "数据读取、指标计算和隔离执行链可行性尚未建立，也不支持继续外推。"
                )
            ),
            "limitations_zh": (
                "该探针没有运行拟议干预，也没有比较处理组与对照组，因此不能判断"
                "科学假设是否成立，更不能据此声称创新或正式实验已经完成。"
            ),
            "plan_results_zh": (
                "本次预实验实际运行固定基线，并保留如下原始记录。\n"
                + "\n".join(lines)
                + (
                    "\n这些结果仅说明公开数据、固定指标和隔离执行链在有限范围内可运行；"
                    if supported
                    else "\n这些失败结果表明当前范围的执行可行性尚未建立；"
                )
                + "拟议干预仍未测量处理效应，不能据此判断新方法有效。"
                + extra
            ),
        }
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={},
            temperature=float(kwargs["temperature"]),
            reasoning_text=(
                self.reasoning_text
                if self.reasoning_text is not None
                else (
                    "先核对每个冻结单元的身份、状态和原始指标，再确认成功门只表示数据、"
                    "指标与容器链路的有限可运行性；随后逐字复制机器证据行，检查解释段"
                    "没有新增任何数字，最后明确拟议处理未运行、处理效应未测量、完整实验"
                    "未完成，不能把可行性探针写成科学假设成立或创新得到证明。"
                )
                * 3
            ),
            reasoning_transport="dashscope_enable_thinking",
        )


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stub: _InterpretationStub,
    fail_all: bool = False,
) -> Any:
    binding, direction = _binding_and_direction()
    panel = _panel(binding)
    _install_execution_doubles(monkeypatch, panel=panel, fail_all=fail_all)
    return run_system_plan_preexperiment(
        lineage_id="lineage-preexperiment",
        selected_direction=direction,
        component_experiment_binding=binding,
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
        public_panel=panel,
        output_dir=tmp_path / "preexperiment",
        completion=stub,
    )


def test_real_cell_bytes_are_bound_before_qwen_writes_chinese_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _InterpretationStub()
    artifact = _run(tmp_path, monkeypatch, stub=stub)

    assert artifact.limited_feasibility_supported is True
    assert artifact.treatment_effect_measured is False
    assert artifact.full_experiment_completed is False
    assert len(artifact.cell_evidence) == 2
    assert all(item.result.status == "succeeded" for item in artifact.cell_evidence)
    assert all(
        item.evidence_line_zh in artifact.interpretation.plan_results_zh
        for item in artifact.cell_evidence
    )
    assert (tmp_path / "preexperiment" / "system-plan-preexperiment.json").is_file()
    assert "results" not in artifact.plan_context()
    assert artifact.plan_context()["plan_results_zh"] == (
        artifact.interpretation.plan_results_zh
    )
    receipt = json.loads(
        (
            tmp_path
            / "preexperiment"
            / artifact.interpretation_receipt_relative_path
        ).read_text(encoding="utf-8")
    )
    assert "evidence_lines_zh" not in receipt["parsed_payload"]
    response_schema = json.loads(
        stub.calls[0]["messages"][-1]["content"]
    )["response_schema"]
    assert "feasibility_status" not in response_schema["properties"]


def test_concise_chinese_interpretation_is_accepted_without_length_quota() -> None:
    interpretation = PreexperimentInterpretation.model_validate(
        {
            "schema_version": "system-plan-preexperiment-interpretation-v1",
            "evidence_lines_zh": ["证据。"],
            "feasibility_status": "limited_scope_supported",
            "feasibility_conclusion_zh": "可行。",
            "limitations_zh": "范围有限。",
            "plan_results_zh": "预实验未测量处理效应。",
            "treatment_effect_measured": False,
            "full_experiment_completed": False,
        }
    )

    assert interpretation.feasibility_conclusion_zh == "可行。"


def test_blank_interpretation_prose_is_rejected_without_length_quota() -> None:
    with pytest.raises(SystemPlanPreexperimentError, match="中文技术散文"):
        PreexperimentInterpretation.model_validate(
            {
                "schema_version": "system-plan-preexperiment-interpretation-v1",
                "evidence_lines_zh": ["证据。"],
                "feasibility_status": "limited_scope_supported",
                "feasibility_conclusion_zh": "可行。",
                "limitations_zh": "   ",
                "plan_results_zh": "预实验未测量处理效应。",
                "treatment_effect_measured": False,
                "full_experiment_completed": False,
            }
        )


def test_concise_nonempty_reasoning_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _run(
        tmp_path,
        monkeypatch,
        stub=_InterpretationStub(reasoning_text="已核对。"),
    )

    assert artifact.authoring_attempts == 1


def test_empty_reasoning_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemPlanPreexperimentError, match="reasoning_content 为空"):
        _run(
            tmp_path,
            monkeypatch,
            stub=_InterpretationStub(reasoning_text=""),
        )


def test_qwen_cannot_add_a_number_outside_exact_machine_evidence_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemPlanPreexperimentError, match="新增了数字"):
        _run(
            tmp_path,
            monkeypatch,
            stub=_InterpretationStub(invent_number=True),
        )


def test_all_failed_cells_are_retained_and_cannot_claim_limited_feasibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _run(
        tmp_path,
        monkeypatch,
        stub=_InterpretationStub(),
        fail_all=True,
    )

    assert artifact.limited_feasibility_supported is False
    assert artifact.interpretation.feasibility_status == "not_supported"
    assert all(item.result.status == "failed" for item in artifact.cell_evidence)
