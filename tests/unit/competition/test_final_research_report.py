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
    SystemEffect,
)
from autoresearch.competition.official_lineage import (
    write_official_development_search_package,
)
from autoresearch.competition.plan_execution_contract import (
    audit_candidate_plan_alignment,
    compile_plan_execution_contract,
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
    SystemAuthoredPlanArtifact,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.plan_confirmation import record_plan_decision
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus, file_hash

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
    return ResearchPlan(
        id="plan-final-report",
        project_id=root.name,
        candidate_id="candidate-final-report",
        title="基于证据绑定的积分贝叶斯方程发现",
        abstract=(
            "本研究在冻结的无噪声与含噪声开发面板上检验预注册的积分贝叶斯稀疏恢复机制，"
            "并以完全相同单元上的固定基线作为对照。"
        ),
        problem_statement=(
            "导数估计会放大观测噪声并破坏稀疏方程发现的稳定性，因此研究检验积分形式能否"
            "提高时间隔离留出数据上的结构恢复能力。"
        ),
        rationale=(
            "积分约束可能削弱数值微分噪声，而贝叶斯项支持选择可能阻止不稳定项进入冻结"
            "方程；二者结合形成可由配对效果直接反驳的机制假设。"
        ),
        technical_details=(
            "候选方法仅在训练切分上拟合，随后冻结并哈希绑定数值方程制品，再在时间隔离的"
            "目标切分上直接预测，禁止重新拟合或读取目标标签。"
        ),
        datasets={
            "source": "冻结的无噪声与 SNR-20 MDBench 开发轨迹",
            "target": "按时间隔离的留出导数字段",
        },
        methods=(
            "在单次拟合、冻结、预测接口下，先使用积分贝叶斯项支持选择，再进行受约束的"
            "稀疏系数估计，并保留可复算的数值方程。"
        ),
        experiments=[
            "在每个冻结实验单元上运行入选候选方法与固定基线，并完整保留失败状态。",
            "先在系统内聚合配对对数效果，再跨系统聚合并计算固定种子的自助区间。",
        ],
        baselines=["在完全相同实验单元上运行固定且已调优的符号回归基线"],
        metrics=[
            "每个实验单元的导数 NMSE",
            "配对对数效果中位数及固定种子的自助置信区间",
        ],
        expected_results=(
            "预注册预期为总体对数效果中位数不低于 0.05，且自助区间下界高于 0.0；若任一"
            "条件未达到，则机制假设被反驳，负结果同样是有效结果并必须报告。"
        ),
        code_agent_brief=(
            "实现冻结的拟合与预测接口，保留可复算的数值方程并运行既定测试。"
            "required_method_tokens=[integral, bayesian]"
        ),
        risks_and_alternatives=[
            "积分窗口可能过度平滑短轨迹，因此失败时应检查窗口尺度与有效样本长度。",
            "贝叶斯项支持选择在强噪声下可能不稳定，因此应完整保留后验与失败案例。",
        ],
        references=["Retrieved literature survey entry 1"],
        literature_references=[
            {
                "title": "Sparse identification of nonlinear dynamics with control",
                "authors": ["Brunton", "Proctor", "Kutz"],
                "venue": "IFAC-PapersOnLine",
                "publication_date": "2016",
                "doi": "10.1016/j.ifacol.2016.10.249",
                "url": "https://doi.org/10.1016/j.ifacol.2016.10.249",
                "retrieved_from": "openalex",
            }
        ],
        evidence_refs=[evidence.as_posix()],
        status=ResearchPlanStatus.READY_FOR_APPROVAL,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _write_plan_artifacts(root: Path, plan: ResearchPlan) -> None:
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
        "schema_version": "system-authored-research-plan-v1",
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


def _write_package(root: Path, plan: ResearchPlan) -> Any:
    contract = compile_plan_execution_contract(plan)
    write_plan_execution_contract(contract=contract, output_dir=root)
    source_path = root / "candidates" / "official-01" / "candidate.py"
    source_path.parent.mkdir(parents=True)
    source = """\
def integral_bayesian_solver(x):
    return x

def fit_equations(x, y):
    return integral_bayesian_solver(x)

def predict_derivative(model, x):
    return integral_bayesian_solver(x)
"""
    with source_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(source)
    interaction_payload = {
        "response_type": "scientific_contract_source",
        "observation": "观察到噪声条件下导数估计不稳定。",
        "problem": "问题是稀疏支持会被噪声扰动。",
        "hypothesis": "积分贝叶斯筛选可提高支持稳定性。",
        "intervention": "实现积分窗口与贝叶斯支持选择。",
        "expected_effect": "预期降低冻结留出集上的导数误差。",
        "implementation_summary": "Integral Bayesian support-selection implementation",
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
    alignment = audit_candidate_plan_alignment(
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
        implementation_summary="Integral Bayesian support-selection implementation",
        approved_plan_hash=contract.approved_plan_hash,
        plan_contract_hash=contract.contract_hash,
        plan_alignment=alignment,
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
    package = _write_package(root, plan)
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
