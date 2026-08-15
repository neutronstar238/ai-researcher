from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import autoresearch.competition.continual_plan_cli as plan_cli_module
from autoresearch.competition.continual_plan_loop import (
    CompetitionPlanLoopConfig,
    CompetitionPlanLoopFormatError,
    CompetitionPlanLoopReport,
    CompetitionPlanLoopStatus,
    PlanLoopCheckpoint,
    inspect_plan_loop_checkpoint,
    run_competition_plan_loop,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.competition.official_lineage import (
    LineageStageReport,
    OfficialLineageConfig,
)
from autoresearch.competition.system_plan_review import (
    CriticalPlanAssessment,
    PriorWorkComparison,
    SystemPlanCriticalReview,
)
from autoresearch.knowledge.raw_memory import RawMemorySourceKind
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.runtime.continual_research_harness import (
    ArtifactCompletionEnvelope,
    ContinualResearchHarness,
    ResearchTaskStatus,
    VerifiedArtifactBinding,
    VerifiedModelReceiptProjection,
)
from autoresearch.schemas import file_hash

NOW = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)


def _lineage(tmp_path: Path, *, lineage_id: str = "plan-loop") -> OfficialLineageConfig:
    work_dir = tmp_path / "lineage"
    work_dir.mkdir(parents=True)
    return OfficialLineageConfig(
        lineage_id=lineage_id,
        work_dir=work_dir,
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )


def _config(tmp_path: Path, *, lineage_id: str = "plan-loop") -> CompetitionPlanLoopConfig:
    return CompetitionPlanLoopConfig(
        lineage=_lineage(tmp_path, lineage_id=lineage_id),
        state_dir=tmp_path / "state",
        vault_root=tmp_path / "vault",
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        worker_id="test-main-agent",
    )


def _completion(parsed: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        response_text=json.dumps(parsed, ensure_ascii=False, sort_keys=True),
        parsed_json=parsed,
        usage={"prompt_tokens": 40, "completion_tokens": 20},
        temperature=0.2,
        reasoning_text="配置模型逐项核对冻结证据、预实验和独立评审后形成中文输出。" * 5,
        reasoning_transport="dashscope_enable_thinking",
    )


def _completion_loader(
    config: CompetitionPlanLoopConfig,
    harness: ContinualResearchHarness,
    report: LineageStageReport,
    _resume_root: Path | None,
    now: datetime,
) -> ArtifactCompletionEnvelope:
    root = config.lineage.work_dir
    parsed = {"title": "系统自产中文研究计划", "execution_authorized": False}
    messages = (
        {"role": "system", "content": "只根据冻结证据自主形成中文研究计划。"},
        {"role": "user", "content": "冻结证据与预实验回执。"},
    )
    receipt = record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id="system-authored-plan-attempt-01",
        attempt=1,
        messages=messages,
        completion=_completion(parsed),
        output_dir=root,
        clock=now,
    )
    plan_dir = root / "plan"
    plan_dir.mkdir(exist_ok=True)
    artifact_paths = {
        "official_research_plan": plan_dir / "research-plan.json",
        "system_authored_plan": root / "system-authored-research-plan.json",
        "preexperiment": root / "system-plan-preexperiment.json",
        "critical_review": root / "system-plan-critical-review.json",
    }
    for kind, path in artifact_paths.items():
        path.write_text(
            json.dumps({"kind": kind, "lineage_id": report.lineage_id}, sort_keys=True),
            encoding="utf-8",
        )

    receipt_path = Path(receipt.output_path)
    sources = [
        ("model_authorship_receipt", receipt_path, RawMemorySourceKind.MODEL_TRANSCRIPT),
        *((kind, path, RawMemorySourceKind.LOCAL_FILE) for kind, path in artifact_paths.items()),
    ]
    bindings: list[VerifiedArtifactBinding] = []
    for kind, path, source_kind in sources:
        capture = harness.raw_memory_store.capture_file(
            path,
            project_id=harness.project_id,
            source_kind=source_kind,
            source_label=f"测试制品 {kind}",
            source_ref=f"lineage:{config.lineage.lineage_id}:{kind}",
            media_type="application/json",
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=now,
        )
        bindings.append(
            VerifiedArtifactBinding(
                artifact_kind=kind,
                source_relative_path=path.relative_to(root).as_posix(),
                source_sha256=file_hash(path),
                raw_binding=capture.binding(harness.raw_memory_store.vault_root),
            )
        )
    receipt_binding = bindings[0]
    projection = VerifiedModelReceiptProjection(
        receipt_hash=receipt.receipt_hash,
        receipt_artifact=receipt_binding,
        messages=receipt.messages,
        messages_sha256=receipt.messages_sha256,
        provider=receipt.provider,
        base_url=receipt.base_url,
        model_name=receipt.model_name,
        endpoint=receipt.endpoint,
        response_text=receipt.response_text,
        response_sha256=receipt.response_sha256,
        parsed_payload=receipt.parsed_payload,
        parsed_payload_sha256=receipt.parsed_payload_sha256,
        usage=receipt.usage,
        reasoning_content=receipt.reasoning_content,
        reasoning_transport=receipt.reasoning_transport,
    )
    return ArtifactCompletionEnvelope.create(
        final_model_receipt=projection,
        artifacts=bindings,
        stage_report=report.model_dump(mode="json"),
        completed_at=now,
    )


def _clock() -> Callable[[], datetime]:
    values = iter(NOW + timedelta(seconds=index) for index in range(20))
    return lambda: next(values)


def test_checkpoint_selection_never_treats_partial_state_as_fresh(tmp_path: Path) -> None:
    root = tmp_path / "lineage"
    root.mkdir()
    assert inspect_plan_loop_checkpoint(root) is PlanLoopCheckpoint.FRESH
    (root / "plan-literature-survey.json").write_text("{}", encoding="utf-8")
    assert inspect_plan_loop_checkpoint(root) is PlanLoopCheckpoint.PARTIAL
    for name in (
        "system-plan-method-skill-selection.json",
        "system-plan-component-atoms.json",
        "system-plan-prospective-atoms.json",
        "system-plan-opportunity-routing.json",
    ):
        (root / name).write_text("{}", encoding="utf-8")
    assert inspect_plan_loop_checkpoint(root) is PlanLoopCheckpoint.RETAINED_ROUTING
    (root / "system-authored-research-plan.json").write_text("{}", encoding="utf-8")
    assert inspect_plan_loop_checkpoint(root) is PlanLoopCheckpoint.PARTIAL
    (root / "plan").mkdir()
    (root / "plan" / "research-plan.json").write_text("{}", encoding="utf-8")
    assert inspect_plan_loop_checkpoint(root) is PlanLoopCheckpoint.COMPLETE


def test_format_failure_continues_exactly_three_claims_without_shadow(tmp_path: Path) -> None:
    config = _config(tmp_path)
    calls = 0

    def format_runner(*_args: Any, **_kwargs: Any) -> LineageStageReport:
        nonlocal calls
        calls += 1
        raise CompetitionPlanLoopFormatError("模型 JSON 缺少闭合括号")

    report = run_competition_plan_loop(
        config,
        plan_runner=format_runner,
        completion_loader=_completion_loader,
        clock=_clock(),
    )
    assert calls == 3
    assert report.status is CompetitionPlanLoopStatus.FORMAT_EXHAUSTED
    assert report.task_status is ResearchTaskStatus.FORMAT_REPAIR
    assert report.format_failure_count == 3
    assert report.proposal is None


def test_partial_checkpoint_is_operational_and_never_calls_a_runner(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.lineage.work_dir / "plan-literature-survey.json").write_text("{}", encoding="utf-8")

    def forbidden(*_args: Any, **_kwargs: Any) -> LineageStageReport:
        pytest.fail("partial checkpoint must not call an official runner")

    report = run_competition_plan_loop(
        config,
        plan_runner=forbidden,
        resume_runner=forbidden,
        completion_loader=_completion_loader,
        clock=_clock(),
    )
    assert report.status is CompetitionPlanLoopStatus.OPERATIONAL_WAIT
    assert report.task_status is ResearchTaskStatus.OPERATIONAL_WAIT
    assert report.proposal is None
    assert report.format_failure_count == 0


@pytest.mark.parametrize(
    "failure",
    (
        TimeoutError("lineage lock timeout"),
        ConnectionError("provider connection interrupted"),
    ),
)
def test_lock_and_network_failures_are_operational_without_shadow(
    tmp_path: Path,
    failure: Exception,
) -> None:
    config = _config(tmp_path)

    def unavailable(*_args: Any, **_kwargs: Any) -> LineageStageReport:
        raise failure

    report = run_competition_plan_loop(
        config,
        plan_runner=unavailable,
        completion_loader=_completion_loader,
        clock=_clock(),
    )

    assert report.status is CompetitionPlanLoopStatus.OPERATIONAL_WAIT
    assert report.task_status is ResearchTaskStatus.OPERATIONAL_WAIT
    assert report.format_failure_count == 0
    assert report.proposal is None


def test_retained_routing_calls_only_resume_with_a_new_attempt_root(tmp_path: Path) -> None:
    config = _config(tmp_path)
    for name in (
        "plan-literature-survey.json",
        "system-plan-method-skill-selection.json",
        "system-plan-component-atoms.json",
        "system-plan-prospective-atoms.json",
        "system-plan-opportunity-routing.json",
    ):
        (config.lineage.work_dir / name).write_text("{}", encoding="utf-8")
    seen_roots: list[Path] = []

    def forbidden(*_args: Any, **_kwargs: Any) -> LineageStageReport:
        pytest.fail("retained routing must not replay run_plan_stage")

    def resume(
        lineage: OfficialLineageConfig,
        *,
        output_dir: Path,
        **_kwargs: Any,
    ) -> LineageStageReport:
        seen_roots.append(output_dir)
        return LineageStageReport(
            lineage_id=lineage.lineage_id,
            stage="plan",
            lines=("resumed",),
        )

    report = run_competition_plan_loop(
        config,
        plan_runner=forbidden,
        resume_runner=resume,
        completion_loader=_completion_loader,
        clock=_clock(),
    )
    assert report.status is CompetitionPlanLoopStatus.COMPLETED
    assert seen_roots == [config.lineage.work_dir / "plan-resume-loop-attempt-01"]


def test_valid_new_rejected_review_is_scientific_pending_shadow(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def rejected_runner(
        lineage: OfficialLineageConfig,
        **_kwargs: Any,
    ) -> LineageStageReport:
        comparisons = tuple(
            PriorWorkComparison(
                reference_index=index,
                overlap="与当前机制存在实质重叠。",
                claimed_difference="当前差异尚未被判别实验支持。",
                remaining_novelty_risk="可能只是既有方法换名。",
            )
            for index in range(1, 4)
        )
        assessment = CriticalPlanAssessment(
            overall_assessment="当前机制与替代解释不可识别，暂不应进入范围批准。",
            closest_prior_work=comparisons,
            mechanism_critical_findings=("机制预测无法区别于实现质量变化。",),
            design_critical_findings=(),
            evidence_semantics_critical_findings=(),
            execution_critical_findings=(),
            novelty_critical_findings=(),
            scientific_lineage_critical_findings=(),
            required_revisions=("增加保持数据生成关系的判别性负对照。",),
            mechanism_scientifically_plausible=False,
            design_can_test_the_hypothesis=True,
            evidence_semantics_valid=True,
            execution_contract_feasible=True,
            novelty_plausible_against_retrieved_work=True,
            scientific_lineage_preserved=True,
            ready_for_human_scope_review=False,
        )
        receipt = record_model_authorship_receipt(
            artifact_kind="plan_critical_review",
            interaction_id="system-plan-critical-review-attempt-01",
            attempt=1,
            messages=(
                {"role": "system", "content": "独立审查，不代写计划。"},
                {"role": "user", "content": "候选计划与真实文献。"},
            ),
            completion=_completion(assessment.model_dump(mode="json")),
            output_dir=lineage.work_dir,
            clock=NOW,
        )
        review_path = lineage.work_dir / "reviews" / "system-plan-critical-review-attempt-01.json"
        review_path.parent.mkdir(parents=True)
        payload: dict[str, Any] = {
            "schema_version": "system-plan-critical-review-v1",
            "lineage_id": lineage.lineage_id,
            "plan_hash": "a" * 64,
            "literature_survey_hash": "b" * 64,
            "authoring_attempt": 1,
            "assessment": assessment.model_dump(mode="json"),
            "authorship_receipt_relative_path": Path(receipt.output_path)
            .relative_to(lineage.work_dir)
            .as_posix(),
            "authorship_receipt_hash": receipt.receipt_hash,
            "model_name": receipt.model_name,
            "authored_by_model": True,
            "hand_written_scientific_prose_count": 0,
            "is_scientific_evidence": False,
            "execution_authorized": False,
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        }
        payload["review_hash"] = canonical_model_hash(payload)
        payload["output_path"] = review_path.resolve().as_posix()
        review = SystemPlanCriticalReview.model_validate(payload)
        review_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
        raise RuntimeError("review rejected the plan")

    report = run_competition_plan_loop(
        config,
        plan_runner=rejected_runner,
        completion_loader=_completion_loader,
        clock=_clock(),
    )
    assert report.status is CompetitionPlanLoopStatus.SCIENTIFIC_PENDING_SHADOW
    assert report.task_status is ResearchTaskStatus.SCIENTIFIC_FAILED
    assert report.proposal is not None
    assert report.proposal.status.value == "pending_shadow"
    assert report.format_failure_count == 0


def test_success_registers_artifact_memory_and_rerun_does_not_call_stage(tmp_path: Path) -> None:
    config = _config(tmp_path)
    calls = 0

    def plan_runner(
        lineage: OfficialLineageConfig,
        **_kwargs: Any,
    ) -> LineageStageReport:
        nonlocal calls
        calls += 1
        return LineageStageReport(
            lineage_id=lineage.lineage_id,
            stage="plan",
            lines=("completed",),
        )

    first = run_competition_plan_loop(
        config,
        plan_runner=plan_runner,
        completion_loader=_completion_loader,
        clock=_clock(),
    )
    second = run_competition_plan_loop(
        config,
        plan_runner=plan_runner,
        completion_loader=lambda *_args: pytest.fail("completed memory must be reused"),
        clock=_clock(),
    )
    assert calls == 1
    assert first.status is CompetitionPlanLoopStatus.COMPLETED
    assert first.completed_memory_task_hash
    assert first.artifact_envelope_hash
    assert second.status is CompetitionPlanLoopStatus.COMPLETED
    assert second.completed_memory_task_hash == first.completed_memory_task_hash


def test_missing_real_completion_artifacts_is_operational_not_fake_success(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    def empty_runner(
        lineage: OfficialLineageConfig,
        **_kwargs: Any,
    ) -> LineageStageReport:
        return LineageStageReport(
            lineage_id=lineage.lineage_id,
            stage="plan",
            lines=("claimed success without artifacts",),
        )

    report = run_competition_plan_loop(
        config,
        plan_runner=empty_runner,
        clock=_clock(),
    )
    assert report.status is CompetitionPlanLoopStatus.OPERATIONAL_WAIT
    assert report.completed_memory_task_hash is None
    assert report.proposal is None


def test_independent_python_module_cli_maps_structured_status_to_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = CompetitionPlanLoopReport(
        lineage_id="cli-lineage",
        status=CompetitionPlanLoopStatus.COMPLETED,
        checkpoint=PlanLoopCheckpoint.COMPLETE,
        task_status=ResearchTaskStatus.COMPLETED,
        format_failure_count=0,
        claim_count=1,
        completed_memory_task_hash="a" * 64,
        artifact_envelope_hash="b" * 64,
        message_cn="完成。",
    )
    monkeypatch.setattr(
        plan_cli_module,
        "run_competition_plan_loop",
        lambda _config: report,
    )
    code = plan_cli_module.main(
        [
            "--lineage-id",
            "cli-lineage",
            "--work-dir",
            str(tmp_path / "lineage"),
            "--state-dir",
            str(tmp_path / "state"),
            "--vault",
            str(tmp_path / "vault"),
        ]
    )
    assert code == 0
    assert '"status": "completed"' in capsys.readouterr().out
