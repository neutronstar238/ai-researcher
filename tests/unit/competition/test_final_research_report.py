"""Task 270.3: observed results may enter only a separate derived final report."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.autonomous_engine import AutonomousModelInteraction
from autoresearch.competition.final_research_report import (
    FinalReportBuildReceipt,
    FinalResearchReport,
    FinalResearchReportError,
    audit_final_report_inputs,
    materialize_final_research_report,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    outcome_authored_fields,
    plan_authored_fields,
    record_model_authorship_receipt,
)
from autoresearch.competition.official_development_search import (
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchPackage,
    SystemEffect,
)
from autoresearch.competition.official_lineage import (
    write_official_development_search_package,
)
from autoresearch.competition.plan_execution_contract import (
    ProspectivePlanExecutionContract,
    audit_candidate_plan_alignment,
    audit_prospective_candidate_plan_alignment,
    build_prospective_candidate_execution_declaration,
    compile_plan_execution_contract,
    compile_system_authored_plan_execution_contract,
    write_plan_execution_contract,
)
from autoresearch.competition.system_authored_outcome import (
    AuthoredInterpretation,
    SystemAuthoredOutcome,
    audit_numeric_relations,
    audit_numeric_traceability,
    collect_evidence_numbers,
)
from autoresearch.competition.system_authored_plan import (
    AuthoredPlanGuardReport,
    PlanScientificLineageBindingV2,
    SystemAuthoredPlanArtifact,
    _build_plan_scientific_lineage_binding,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.plan_confirmation import record_plan_decision
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus, file_hash
from tests.unit.competition import test_system_authored_plan as plan_v2_support

_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def _completion(parsed: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint=(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        ),
        response_text=json.dumps(parsed, ensure_ascii=False, sort_keys=True),
        parsed_json=parsed,
        usage={"completion_tokens_details": {"reasoning_tokens": 2_000}},
        temperature=0.2,
    )


def _research_plan(root: Path) -> ResearchPlan:
    evidence = root / "prior-evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    binding = _build_plan_scientific_lineage_binding(plan_v2_support._v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    base = plan_v2_support._v2_plan(binding)
    literature = [
        {
            "title": f"Prospective intervention evidence {index}",
            "authors": ["Author"],
            "venue": "Archive",
            "publication_date": "2026",
            "doi": f"10.0000/prospective.{index}",
            "url": f"https://doi.org/10.0000/prospective.{index}",
            "retrieved_from": "openalex",
        }
        for index in range(1, 4)
    ]
    payload = base.model_dump(mode="json", warnings=False)
    chinese_execution_contract = (
        "候选代码必须逐字读取正式前瞻干预身份，只改变预注册的单一实现锚点，"
        "并在全部公开拟合与预测接口中到达该锚点；所有冻结维度、目标系统、资源预算、"
        "负对照、敏感性对照和结果盲判据均不得改写，任何合同不一致都必须在执行前拒绝。"
    )
    payload.update(
        {
            "id": "plan-final-report",
            "project_id": root.name,
            "candidate_id": "candidate-final-report",
            "metrics": (
                "每个冻结实验单元的导数归一化均方误差",
                "系统内与跨系统聚合的配对对数效果中位数",
            ),
            "code_agent_brief": chinese_execution_contract * 8 + base.code_agent_brief,
            "references": tuple(
                f"Retrieved literature survey entry {index}"
                for index in range(1, 4)
            ),
            "literature_references": literature,
            "evidence_refs": [evidence.as_posix()],
            "status": ResearchPlanStatus.READY_FOR_APPROVAL,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
    )
    return ResearchPlan.model_validate(payload)


def _write_plan_artifacts(root: Path, plan: ResearchPlan) -> None:
    binding = _build_plan_scientific_lineage_binding(plan_v2_support._v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    attestation = plan_v2_support._v2_attestation(binding)
    guard_payload: dict[str, Any] = {
        "schema_version": "authored-plan-guard-report-v1",
        "quality_gate_passed": True,
        "quality_gate_issues": (),
        "quality_gate_warnings": (),
        "quality_gate_score": 1.0,
        "all_cited_evidence_exists": True,
        "missing_evidence_paths": (),
        "numbers_traceable": True,
        "untraceable_numbers": (),
        "states_falsifiable_expectation": True,
        "claims_no_unobserved_result": True,
        "named_scripts_exist": True,
        "missing_script_paths": (),
        "accepted": True,
        "findings": (),
    }
    guard_payload["report_hash"] = canonical_model_hash(guard_payload)
    guard = AuthoredPlanGuardReport.model_validate(guard_payload)
    plan_payload = plan.model_dump(mode="json")
    receipt = record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id="system-authored-plan-attempt-01",
        attempt=1,
        messages=[
            {"role": "system", "content": "请自主撰写中文研究计划。"},
            {"role": "user", "content": "冻结证据上下文"},
        ],
        completion=_completion(plan_authored_fields(plan_payload)),
        output_dir=root,
        clock=_NOW,
    )
    artifact_payload: dict[str, Any] = {
        "schema_version": "system-authored-research-plan-v2",
        "lineage_id": root.name,
        "plan": plan_payload,
        "plan_hash": canonical_model_hash(plan_payload),
        "guard_report": guard.model_dump(mode="json"),
        "authoring_attempts": 1,
        "model_name": "qwen3.7-max",
        "reasoning_tokens": 2_000,
        "authorship_receipt_relative_path": Path(receipt.output_path)
        .relative_to(root)
        .as_posix(),
        "authorship_receipt_hash": receipt.receipt_hash,
        "scientific_lineage_binding": binding.model_dump(mode="json"),
        "scientific_lineage_attestation": attestation.model_dump(mode="json"),
        "authored_by_model": True,
        "hand_written_prose_field_count": 0,
        "execution_authorized": False,
        "is_evidence": False,
    }
    artifact_payload["artifact_hash"] = canonical_model_hash(artifact_payload)
    artifact_payload["output_path"] = (root / "system-authored-research-plan.json").as_posix()
    artifact = SystemAuthoredPlanArtifact.model_validate(artifact_payload)
    write_json_model(root / "system-authored-research-plan.json", artifact)

    approved_path = root / "plan" / "research-plan.json"
    write_json_model(approved_path, plan)
    record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="human-reviewer",
        notes="Scope approval only; this is not scientific evidence.",
        output_dir=root / "plan",
    )


def _identity() -> OfficialDevelopmentIdentity:
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "1" * 64,
        "development_panel_hash": "2" * 64,
        "sealed_confirmation_panel_hash": "3" * 64,
        "runner_sha256": "4" * 64,
        "runtime_environment_hash": "5" * 64,
        "image_id": "sha256:" + "6" * 64,
        "data_root": "/frozen/data",
        "initial_candidate_count": 1,
        "pilot_system_count": 2,
        "full_system_count": 2,
        "conditions": ("clean", "snr_20"),
        "seeds": (101,),
        "maximum_official_cells_total": 8,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": _NOW.isoformat().replace("+00:00", "Z"),
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _cell(
    *, candidate_id: str, method_kind: str, stage: str, system: str, data_type: str
) -> OfficialCellResult:
    payload: dict[str, Any] = {
        "attempt_id": f"{stage}-{candidate_id}-{system}",
        "method_kind": method_kind,
        "candidate_id": candidate_id,
        "stage": stage,
        "system_name": system,
        "data_type": data_type,
        "condition": "clean",
        "seed": 101,
        "status": "succeeded",
        "derivative_nmse": 0.1 if method_kind == "candidate" else 0.2,
        "validation_nmse": 0.1,
        "selected_term_count": 2,
        "equation_changed_on_shuffled_training": True,
        "maximum_equation_prediction_delta": 0.5,
        "wall_time_seconds": 1.0,
        "failure_reason": None,
    }
    payload["result_hash"] = canonical_model_hash(payload)
    return OfficialCellResult.model_validate(payload)


def _prospective_source(contract: ProspectivePlanExecutionContract) -> str:
    declaration = build_prospective_candidate_execution_declaration(contract)
    anchor = contract.implementation_anchor
    control_helper = f"{anchor}__control"
    treatment_helper = f"{anchor}__treatment"
    identity_guards = (
        "    if payload['prospective_execution_binding']"
        "['plan_execution_contract_hash'] != "
        "PROSPECTIVE_EXECUTION_DECLARATION['plan_execution_contract_hash']:\n"
        "        raise ValueError('plan contract mismatch')\n"
        "    if payload['prospective_execution_binding']"
        "['selected_intervention_hash'] != "
        "PROSPECTIVE_EXECUTION_DECLARATION['selected_intervention_identity']"
        "['intervention_hash']:\n"
        "        raise ValueError('intervention mismatch')\n"
        "    if payload['prospective_execution_binding']['pair_contract_hash'] != "
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']['pair_hash']:\n"
        "        raise ValueError('pair mismatch')\n"
    )
    runtime_value = (
        "payload['prospective_execution_binding']['configuration']["
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']"
        "['intervention_key']]"
    )
    control_value = (
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']"
        "['control_configuration'][PROSPECTIVE_EXECUTION_DECLARATION"
        "['paired_control_treatment']['intervention_key']]"
    )
    treatment_value = (
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']"
        "['treatment_configuration'][PROSPECTIVE_EXECUTION_DECLARATION"
        "['paired_control_treatment']['intervention_key']]"
    )
    selector = (
        f"    if {runtime_value} == {control_value}:\n"
        f"        return {control_helper}(payload)\n"
        f"    if {runtime_value} == {treatment_value}:\n"
        f"        return {treatment_helper}(payload)\n"
        "    raise ValueError('unknown prospective arm')\n"
    )
    hooks = "".join(
        f"def {hook}(payload):\n    return {anchor}(payload)\n\n"
        for hook in contract.public_hooks
    )
    return (
        "PROSPECTIVE_EXECUTION_DECLARATION = "
        f"{declaration.model_dump(mode='python')!r}\n\n"
        f"def {control_helper}(payload):\n"
        "    return payload\n\n"
        f"def {treatment_helper}(payload):\n"
        "    return payload\n\n"
        f"def {anchor}(payload):\n"
        f"{identity_guards}"
        f"{selector}\n"
        f"{hooks}"
    )


def _write_package(root: Path) -> Any:
    artifact = SystemAuthoredPlanArtifact.model_validate_json(
        (root / "system-authored-research-plan.json").read_text(encoding="utf-8")
    )
    contract = compile_system_authored_plan_execution_contract(artifact)
    write_plan_execution_contract(contract=contract, output_dir=root)
    source_path = root / "candidates" / "official-01" / "candidate.py"
    source_path.parent.mkdir(parents=True)
    source = _prospective_source(contract)
    with source_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(source)
    interaction_payload = {
        "response_type": "scientific_contract_source",
        "observation": "观察到噪声条件下导数估计不稳定。",
        "problem": "问题是稀疏支持会被噪声扰动。",
        "hypothesis": "积分贝叶斯筛选可提高支持稳定性。",
        "intervention": "实现积分窗口与贝叶斯支持选择。",
        "expected_effect": "预期降低冻结留出集上的导数误差。",
        "implementation_summary": "严格执行前瞻单因子对照—处理合同的候选实现",
        "source_lines": source.split("\n"),
    }
    interaction = AutonomousModelInteraction.create(
        interaction_id="generation-01",
        stage="scientific_contract_implementation",
        candidate_id="official-01",
        messages=[
            {"role": "system", "content": "自主实现批准计划。"},
            {"role": "user", "content": "执行合同"},
        ],
        completion=_completion(interaction_payload),
        structured_transport_mode="json_schema",
        provider_format_fallback_relative_path=None,
        provider_format_fallback_sha256=None,
        provider_retry_relative_paths=(),
        provider_retry_sha256s=(),
        provider_transport_retry_relative_paths=(),
        provider_transport_retry_sha256s=(),
        max_tokens=12_000,
        thinking_mode="disabled",
        thinking_budget=None,
        created_at=_NOW,
    )
    write_json_model(root / "interactions" / "generation-01.json", interaction)
    alignment = audit_prospective_candidate_plan_alignment(
        candidate_id="official-01", source_text=source, contract=contract
    )
    candidate = OfficialCandidateRecord(
        candidate_id="official-01",
        generation=1,
        interaction_id="generation-01",
        interaction_hash=interaction.interaction_hash,
        source_relative_path="candidates/official-01/candidate.py",
        source_sha256=file_hash(source_path),
        static_review_approved=True,
        implementation_summary="严格执行前瞻单因子对照—处理合同的候选实现",
        approved_plan_hash=contract.approved_plan_hash,
        plan_contract_hash=contract.contract_hash,
        prospective_plan_alignment=alignment,
    )
    effects = [
        SystemEffect(
            system_name="ode-system",
            data_type="ode",
            candidate_median_loss=0.1,
            baseline_median_loss=0.2,
            paired_log_effect=0.2,
            candidate_cell_count=1,
            baseline_cell_count=1,
            candidate_success_count=1,
        ),
        SystemEffect(
            system_name="pde-system",
            data_type="pde",
            candidate_median_loss=0.1,
            baseline_median_loss=0.2,
            paired_log_effect=0.22,
            candidate_cell_count=1,
            baseline_cell_count=1,
            candidate_success_count=1,
        ),
    ]
    cells = [
        _cell(
            candidate_id="official-01",
            method_kind="candidate",
            stage="full",
            system="ode-system",
            data_type="ode",
        ),
        _cell(
            candidate_id="official-01",
            method_kind="candidate",
            stage="full",
            system="pde-system",
            data_type="pde",
        ),
        _cell(
            candidate_id="baseline",
            method_kind="baseline",
            stage="baseline",
            system="ode-system",
            data_type="ode",
        ),
        _cell(
            candidate_id="baseline",
            method_kind="baseline",
            stage="baseline",
            system="pde-system",
            data_type="pde",
        ),
    ]
    gate = {
        "all_candidate_cells_succeeded": True,
        "all_baseline_cells_succeeded": True,
        "overall_median_at_least_minimum": True,
        "bootstrap_lower_above_zero": True,
        "ode_stratum_non_negative": True,
        "pde_stratum_non_negative": True,
        "budget_conformant": True,
    }
    return write_official_development_search_package(
        identity=_identity(),
        candidates=[candidate],
        cell_results=cells,
        stages_executed=["pilot", "baseline", "full"],
        selected_candidate_id="official-01",
        selection_basis="frozen median validation NMSE",
        system_effects=effects,
        summary={
            "overall_median_log_effect": 0.2,
            "bootstrap_lower": 0.1,
            "bootstrap_upper": 0.3,
            "ode_stratum_median": 0.2,
            "pde_stratum_median": 0.22,
        },
        estimand={"minimum_overall_log_effect": 0.05},
        gate_checks=gate,
        output_dir=root,
    )


def _write_outcome(root: Path, package: Any, *, relation_audit: bool = True) -> None:
    interpretation = AuthoredInterpretation(
        verdict="claim_supported",
        what_the_evidence_supports=(
            "观测到的总体对数效果中位数为 0.2，不低于冻结阈值 0.05；固定种子自助区间"
            "[0.1, 0.3] 不包含 0，而且两个数据类型分层门禁均通过。因此，在本次冻结开发"
            "面板与既定基线范围内，预注册的机制主张获得支持。"
        ),
        what_the_evidence_does_not_support=(
            "该开发面板结果不能证明方法在未见基准、其他噪声分布或封存确认面板上仍然有效，"
            "也不能把一次入选实现推广为整个方法族的普遍优势；任何此类外推都需要独立确认"
            "实验，而不能由当前结果替代。"
        ),
        strongest_counter_reading=(
            "最强的反面解释是自助区间下界 0.1 仍接近零效应，而且当前证据只覆盖两个冻结"
            "系统，因此点估计所显示的稳定性可能高于真实的跨系统稳定性。"
        ),
        limitations=(
            "结果只覆盖冻结的开发系统，尚未触碰封存确认面板。",
            "入选实现不能代表该机制下所有可能的算法变体。",
        ),
        claims_frozen_gate_passed=True,
    )
    prose = "\n".join(
        [
            interpretation.what_the_evidence_supports,
            interpretation.what_the_evidence_does_not_support,
            interpretation.strongest_counter_reading,
            *interpretation.limitations,
        ]
    )
    trace = audit_numeric_traceability(
        prose=prose,
        allowed_numbers=collect_evidence_numbers(package.model_dump(mode="json")),
    )
    relation = audit_numeric_relations(prose=prose) if relation_audit else None
    interpretation_payload = interpretation.model_dump(mode="json")
    receipt = record_model_authorship_receipt(
        artifact_kind="outcome_interpretation",
        interaction_id="system-authored-outcome",
        attempt=1,
        messages=[
            {"role": "system", "content": "请仅依据证据自主解释结果。"},
            {"role": "user", "content": "签名结果包"},
        ],
        completion=_completion(outcome_authored_fields(interpretation_payload)),
        output_dir=root,
        clock=_NOW,
    )
    payload: dict[str, Any] = {
        "schema_version": "system-authored-outcome-v1",
        "lineage_id": root.name,
        "package_hash": package.package_hash,
        "interpretation": interpretation_payload,
        "traceability": trace.model_dump(mode="json"),
        "frozen_gate_passed": True,
        "verdict_consistent_with_gate": True,
        "accepted": True,
        "refusal_reasons": (),
        "model_name": "qwen3.7-max",
        "reasoning_tokens": 2_000,
        "authorship_receipt_relative_path": Path(receipt.output_path)
        .relative_to(root)
        .as_posix(),
        "authorship_receipt_hash": receipt.receipt_hash,
        "authored_by_model": True,
        "hand_written_prose_count": 0,
        "is_evidence": False,
        "publication_ready": False,
        "created_at": _NOW.isoformat().replace("+00:00", "Z"),
    }
    if relation is not None:
        payload["relation_audit"] = relation.model_dump(mode="json")
    payload["outcome_hash"] = canonical_model_hash(payload)
    payload["output_path"] = (root / "system-authored-outcome.json").as_posix()
    outcome = SystemAuthoredOutcome.model_validate(payload)
    write_json_model(root / "system-authored-outcome.json", outcome)


def _lineage(tmp_path: Path, *, relation_audit: bool = True) -> Path:
    root = tmp_path / "lineage-final-report"
    root.mkdir()
    plan = _research_plan(root)
    _write_plan_artifacts(root, plan)
    package = _write_package(root)
    _write_outcome(root, package, relation_audit=relation_audit)
    return root


def test_input_audit_accepts_only_the_complete_chain(tmp_path: Path) -> None:
    root = _lineage(tmp_path)
    audit = audit_final_report_inputs(lineage_dir=root)
    assert audit.accepted is True
    assert all(audit.checks.values())
    assert audit.findings == ()


def test_missing_relation_audit_is_fail_closed(tmp_path: Path) -> None:
    root = _lineage(tmp_path, relation_audit=False)
    audit = audit_final_report_inputs(lineage_dir=root)
    assert audit.accepted is False
    assert audit.checks["numeric_relations_passed"] is False
    with pytest.raises(FinalResearchReportError, match="relation audit is absent"):
        materialize_final_research_report(
            lineage_dir=root, output_dir=root / "final", compile_pdf=False
        )


def test_selected_source_tampering_blocks_the_report(tmp_path: Path) -> None:
    root = _lineage(tmp_path)
    source = root / "candidates" / "official-01" / "candidate.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    audit = audit_final_report_inputs(lineage_dir=root)
    assert audit.accepted is False
    assert audit.checks["selected_candidate_source_matches"] is False


def test_materialization_keeps_preregistration_immutable(tmp_path: Path) -> None:
    root = _lineage(tmp_path)
    artifact = root / "system-authored-research-plan.json"
    approved = root / "plan" / "research-plan.json"
    before = (file_hash(artifact), file_hash(approved))
    report = materialize_final_research_report(
        lineage_dir=root, output_dir=root / "final", compile_pdf=False, clock=_NOW
    )
    assert (file_hash(artifact), file_hash(approved)) == before
    assert report.preregistered_plan_hash == canonical_model_hash(
        report.preregistered_plan
    )
    assert report.hand_written_scientific_prose_field_count == 0
    assert report.publication_ready is False
    markdown = (root / "final" / "final-research-report.md").read_text(encoding="utf-8")
    latex = (root / "final" / "final-research-report.tex").read_text(encoding="utf-8")
    for token in ("claim_supported", "0.2", "0.1", "0.3", "0.22", "0.05"):
        assert token in markdown
    assert "claim\\_supported" in latex
    receipt = FinalReportBuildReceipt.model_validate_json(
        (root / "final" / "final-research-report-build.json").read_text(encoding="utf-8")
    )
    assert receipt.pdf_compiled is False
    assert receipt.all_renderings_consistent is False
    assert receipt.consistency_checks["json_key_metrics"] is True
    assert receipt.consistency_checks["markdown_key_metrics"] is True
    assert receipt.consistency_checks["latex_key_metrics"] is True


def test_final_report_schema_itself_rejects_non_chinese_scientific_prose(
    tmp_path: Path,
) -> None:
    root = _lineage(tmp_path)
    report = materialize_final_research_report(
        lineage_dir=root, output_dir=root / "final", compile_pdf=False, clock=_NOW
    )
    payload = report.model_dump(mode="json")
    payload["interpretation"]["what_the_evidence_supports"] = (
        "This English-only scientific conclusion must remain invalid even if a caller "
        "constructs the final report model directly instead of using the audited CLI."
    )

    with pytest.raises(FinalResearchReportError, match="non-Chinese"):
        FinalResearchReport.model_validate(payload)


def test_historical_plan_artifact_v1_cannot_enter_formal_reporting(
    tmp_path: Path,
) -> None:
    root = _lineage(tmp_path)
    artifact_path = root / "system-authored-research-plan.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "system-authored-research-plan-v1"
    payload.pop("scientific_lineage_binding")
    payload.pop("scientific_lineage_attestation")
    payload["artifact_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"artifact_hash", "output_path"}
        }
    )
    legacy = SystemAuthoredPlanArtifact.model_validate(payload)
    write_json_model(artifact_path, legacy)

    audit = audit_final_report_inputs(lineage_dir=root)

    assert audit.accepted is False
    assert audit.checks["system_authored_plan_integrity"] is False
    assert audit.checks["plan_execution_contract_matches"] is False


def test_formal_artifact_cannot_fall_back_to_a_v1_execution_contract(
    tmp_path: Path,
) -> None:
    root = _lineage(tmp_path)
    formal_plan = ResearchPlan.model_validate_json(
        (root / "plan" / "research-plan.json").read_text(encoding="utf-8")
    )
    legacy_plan = formal_plan.model_copy(
        update={
            "code_agent_brief": (
                "仅用于构造历史合同反例。"
                "required_method_tokens=[prospective, component]"
            )
        }
    )
    legacy_contract = compile_plan_execution_contract(legacy_plan)
    write_json_model(root / "plan-execution-contract.json", legacy_contract)

    audit = audit_final_report_inputs(lineage_dir=root)

    assert audit.accepted is False
    assert audit.checks["plan_execution_contract_matches"] is False


@pytest.mark.parametrize("field_name", ("paired_control_treatment", "identity"))
def test_tampered_prospective_identity_or_pair_blocks_the_report(
    tmp_path: Path,
    field_name: str,
) -> None:
    root = _lineage(tmp_path)
    contract_path = root / "plan-execution-contract.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if field_name == "paired_control_treatment":
        pair = payload["paired_control_treatment"]
        anchor = pair["intervention_key"]
        pair["treatment_configuration"][anchor] = "篡改后的处理水平不得进入报告"
        pair["pair_hash"] = canonical_model_hash(
            {key: value for key, value in pair.items() if key != "pair_hash"}
        )
    else:
        payload["selected_intervention_identity"]["implementation_anchor"] = (
            "tampered_anchor"
        )
    payload["contract_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "contract_hash"}
    )
    contract_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    audit = audit_final_report_inputs(lineage_dir=root)

    assert audit.accepted is False
    assert audit.checks["plan_execution_contract_matches"] is False


def test_legacy_candidate_alignment_cannot_replace_prospective_alignment(
    tmp_path: Path,
) -> None:
    root = _lineage(tmp_path)
    package_path = root / "official-development-search-package.json"
    package_payload = json.loads(package_path.read_text(encoding="utf-8"))
    plan = ResearchPlan.model_validate_json(
        (root / "plan" / "research-plan.json").read_text(encoding="utf-8")
    )
    legacy_plan = plan.model_copy(
        update={
            "code_agent_brief": (
                "仅用于构造旧式候选对齐反例。"
                "required_method_tokens=[prospective, component]"
            )
        }
    )
    legacy_contract = compile_plan_execution_contract(legacy_plan)
    candidate_payload = package_payload["candidates"][0]
    source = (root / candidate_payload["source_relative_path"]).read_text(
        encoding="utf-8"
    )
    legacy_alignment = audit_candidate_plan_alignment(
        candidate_id=candidate_payload["candidate_id"],
        source_text=source,
        contract=legacy_contract,
    )
    assert legacy_alignment.passed is True
    candidate_payload["approved_plan_hash"] = legacy_contract.approved_plan_hash
    candidate_payload["plan_contract_hash"] = legacy_contract.contract_hash
    candidate_payload["plan_alignment"] = legacy_alignment.model_dump(mode="json")
    candidate_payload.pop("prospective_plan_alignment")
    package_payload["package_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in package_payload.items()
            if key not in {"package_hash", "output_path"}
        }
    )
    package = OfficialDevelopmentSearchPackage.model_validate(package_payload)
    write_json_model(package_path, package)

    audit = audit_final_report_inputs(lineage_dir=root)

    assert audit.accepted is False
    assert audit.checks["selected_candidate_plan_aligned"] is False


def test_final_report_embeds_exact_v2_artifact_contract_identity_and_pair(
    tmp_path: Path,
) -> None:
    root = _lineage(tmp_path)
    report = materialize_final_research_report(
        lineage_dir=root, output_dir=root / "final", compile_pdf=False, clock=_NOW
    )
    contract = report.prospective_plan_execution_contract

    assert report.schema_version == "final-research-report-v2"
    assert report.system_authored_plan_artifact.schema_version == (
        "system-authored-research-plan-v2"
    )
    assert contract.contract_hash == report.plan_execution_contract_hash
    assert contract.selected_intervention_identity.implementation_anchor == (
        contract.implementation_anchor
    )
    assert contract.paired_control_treatment.changed_keys == (
        contract.implementation_anchor,
    )


@pytest.mark.skipif(
    shutil.which("xelatex") is None or shutil.which("pdftotext") is None,
    reason="XeLaTeX and pdftotext are required for the live PDF rendering check",
)
def test_pdf_contains_the_same_verdict_and_key_metrics(tmp_path: Path) -> None:
    root = _lineage(tmp_path)
    report = materialize_final_research_report(
        lineage_dir=root, output_dir=root / "final", compile_pdf=True, clock=_NOW
    )
    pdf_path = root / "final" / "final-research-report.pdf"
    assert pdf_path.is_file() and pdf_path.stat().st_size > 0
    receipt = FinalReportBuildReceipt.model_validate_json(
        (root / "final" / "final-research-report-build.json").read_text(encoding="utf-8")
    )
    assert receipt.report_hash == report.report_hash
    assert receipt.pdf_compiled is True
    assert receipt.all_renderings_consistent is True
    assert all(receipt.consistency_checks.values())


def test_retained_task2700_is_ineligible_for_a_final_report() -> None:
    retained = Path("runs/manual-live/task2700-latex-plan-lineage-v1")
    if not retained.is_dir():
        pytest.skip("retained task2700 lineage is not present in this checkout")
    audit = audit_final_report_inputs(lineage_dir=retained)
    assert audit.accepted is False
    assert audit.checks["plan_execution_contract_matches"] is False
    assert audit.checks["selected_candidate_plan_aligned"] is False
    assert audit.checks["numeric_relations_passed"] is False
