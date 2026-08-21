"""Tests for the generic one-shot recovery after a blocking plan review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import autoresearch.competition.contest_direction_review_recovery_cli as review_cli
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    _public_plan_projection,
)
from autoresearch.competition.contest_direction_review_recovery_cli import (
    ContestDirectionReviewRecoveryError,
    _BlockedReviewBundle,
    _replay_v5_gap_chain,
    _revision_requirements,
    _source_block_receipt_payload,
    _stdout_json,
    _validate_v4_reference_lock_payload,
    _validate_v5_reference_lock_payload,
    _verify_provider_escrow_binding,
    main,
    run_contest_direction_review_recovery,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    replayable_stage_completion,
)
from autoresearch.competition.contest_plan_embedded_evidence import (
    ContestPlanEmbeddedEvidenceBundle,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.llm.client import LLMJsonCompletionResult

_REFERENCES = tuple(f"Locked source {index}" for index in range(1, 6))


def test_review_recovery_inherits_verified_result_boundaries() -> None:
    requirements = "\n".join(_revision_requirements())

    assert "不得引入任何新数字" in requirements
    assert "替代解释" in requirements
    assert "Datasets/Source/Target" in requirements


def test_cli_stdout_json_is_ascii_safe_for_non_utf8_windows_consoles() -> None:
    rendered = _stdout_json({"status": "通过", "delta": "−0.001"})

    assert rendered.encode("ascii")
    assert "\\u901a\\u8fc7" in rendered


def test_v4_reference_lock_binds_exact_review_catalog_order() -> None:
    references = tuple(f"[{index}] Locked source {index}" for index in range(1, 6))
    catalog = [
        {"record_id": f"record-{index}", "title": f"Source {index}"} for index in range(1, 6)
    ]
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-planning-literature-v4",
        "literature_protocol": "two_stage_literature_v4",
        "selected_record_ids": [item["record_id"] for item in catalog],
        "planning_catalog": catalog,
        "planning_catalog_hash": canonical_model_hash({"catalog": catalog}),
        "planning_context_hash": canonical_model_hash({"context": list(references)}),
        "planning_coverage_receipt_hash": "a" * 64,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)

    _validate_v4_reference_lock_payload(
        payload,
        references=references,
        coverage_receipt_hash="a" * 64,
        coverage_selected_record_ids=tuple(item["record_id"] for item in catalog),
    )

    with pytest.raises(ContestDirectionReviewRecoveryError, match="differs from the review"):
        _validate_v4_reference_lock_payload(
            payload,
            references=tuple(reversed(references)),
            coverage_receipt_hash="a" * 64,
            coverage_selected_record_ids=tuple(item["record_id"] for item in catalog),
        )


def test_v5_reference_lock_binds_zero_round_chain_and_coverage_bridge() -> None:
    references = tuple(f"[{index}] Locked source {index}" for index in range(1, 6))
    catalog = [
        {"record_id": f"record-{index}", "title": f"Source {index}"} for index in range(1, 6)
    ]
    gap_chain = {
        "repair_round_count": 0,
        "gap_diagnosis_hash": None,
        "gap_query_response_receipt_hash": None,
        "gap_query_projection_hash": None,
        "gap_retrieval_artifact_hash": None,
        "gap_retrieval_catalog_hash": None,
        "layered_literature_artifact_hash": None,
        "r2_pre_status_coverage_receipt_hash": None,
    }
    thresholds = {"minimum_anchor_count": 5}
    role_counts = {"direct_core": 2, "method_precedent": 1}
    eligible_counts = {"direct_core": 2, "method_precedent": 1}
    query_ids = ("r1-direct", "r1-method", "r1-mechanism", "r1-limitations")
    anchors = ({"record_id": "record-1", "role": "direct_core"},)
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-planning-literature-v5",
        "literature_protocol": "two_stage_literature_v5",
        "base_merged_literature_artifact_hash": "1" * 64,
        "base_merged_literature_catalog_hash": "2" * 64,
        "merged_literature_artifact_hash": "1" * 64,
        "merged_literature_catalog_hash": "2" * 64,
        "gap_repair_chain": gap_chain,
        "gap_repair_chain_hash": canonical_model_hash(gap_chain),
        "selected_record_ids": [item["record_id"] for item in catalog],
        "planning_catalog": catalog,
        "planning_catalog_hash": canonical_model_hash({"catalog": catalog}),
        "planning_context_hash": canonical_model_hash({"context": list(references)}),
        "r1_planning_coverage_schema_version": ("contest-planning-literature-coverage-v5"),
        "r1_planning_coverage_receipt_hash": "3" * 64,
        "planning_coverage_schema_version": "contest-planning-literature-coverage-v5",
        "planning_coverage_receipt_hash": "4" * 64,
        "planning_coverage_thresholds": thresholds,
        "planning_coverage_selected_role_counts": role_counts,
        "planning_coverage_role_query_ids": list(query_ids),
        "planning_coverage_method_focus_basis_query_ids": list(query_ids),
        "planning_coverage_eligible_role_family_counts": eligible_counts,
        "planning_coverage_anchor_assignments": list(anchors),
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    arguments = {
        "references": references,
        "base_merged_artifact_hash": "1" * 64,
        "base_merged_catalog_hash": "2" * 64,
        "merged_artifact_hash": "1" * 64,
        "merged_catalog_hash": "2" * 64,
        "r1_coverage_schema_version": "contest-planning-literature-coverage-v5",
        "r1_coverage_receipt_hash": "3" * 64,
        "coverage_schema_version": "contest-planning-literature-coverage-v5",
        "coverage_receipt_hash": "4" * 64,
        "coverage_selected_record_ids": tuple(item["record_id"] for item in catalog),
        "coverage_thresholds": thresholds,
        "coverage_selected_role_counts": role_counts,
        "coverage_role_query_ids": query_ids,
        "method_focus_basis_query_ids": query_ids,
        "eligible_role_family_counts": eligible_counts,
        "coverage_anchor_assignments": anchors,
        "expected_gap_chain": gap_chain,
    }

    _validate_v5_reference_lock_payload(payload, **arguments)

    tampered = dict(payload)
    tampered["gap_repair_chain_hash"] = "f" * 64
    tampered["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in tampered.items() if key != "artifact_hash"}
    )
    with pytest.raises(ContestDirectionReviewRecoveryError, match="review/gap chain"):
        _validate_v5_reference_lock_payload(tampered, **arguments)


def test_v5_zero_round_gap_chain_preserves_complete_r1_query_lineage(
    tmp_path: Path,
) -> None:
    r1_queries = tuple(
        SimpleNamespace(query_id=f"r1-{index}", raw_query=f"exact R1 query {index}")
        for index in range(4)
    )
    r1 = SimpleNamespace(
        passed=True,
        role_queries=r1_queries,
        method_focus_basis_queries=r1_queries,
    )
    final = SimpleNamespace(
        role_queries=r1_queries,
        method_focus_basis_queries=r1_queries,
    )
    base = SimpleNamespace(artifact_hash="1" * 64, merged_catalog_hash="2" * 64)
    lock = {"gap_repair_chain": {"repair_round_count": 0}}

    _replay_v5_gap_chain(
        literature_root=tmp_path,
        lock=lock,
        base_merged=base,
        r1_coverage=r1,
        final_coverage=final,
    )

    for field in ("role_queries", "method_focus_basis_queries"):
        original = getattr(final, field)
        setattr(
            final,
            field,
            tuple(
                SimpleNamespace(query_id=item.query_id, raw_query="mutated query")
                for item in r1_queries
            ),
        )
        with pytest.raises(ContestDirectionReviewRecoveryError, match="exact R1 query"):
            _replay_v5_gap_chain(
                literature_root=tmp_path,
                lock=lock,
                base_merged=base,
                r1_coverage=r1,
                final_coverage=final,
            )
        setattr(final, field, original)


def test_v5_one_round_gap_chain_replays_exact_r1_to_r2_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    literature_root = tmp_path / "literature"
    paths = (
        literature_root / "gap-repair" / "gap-diagnosis.json",
        literature_root / "gap-repair" / "gap-query-response.json",
        literature_root / "gap-repair" / "gap-query-projection.json",
        literature_root / "gap-repair" / "gap-repair-literature.json",
        literature_root / "layered-literature.json",
        literature_root / "planning-literature-coverage-r2.json",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    class PassingCoverage(SimpleNamespace):
        def require_pass(self) -> PassingCoverage:
            return self

    r1_queries = tuple(SimpleNamespace(query_id=f"r1-{index}") for index in range(4))
    r2_queries = tuple(SimpleNamespace(query_id=f"r2-{index}") for index in range(4))
    r1 = SimpleNamespace(
        passed=False,
        receipt_hash="1" * 64,
        method_focus_basis_queries=r1_queries,
    )
    final = SimpleNamespace(
        role_queries=r2_queries,
        method_focus_basis_queries=r1_queries,
    )
    base = SimpleNamespace(artifact_hash="2" * 64, merged_catalog_hash="3" * 64)
    diagnosis = SimpleNamespace(coverage_receipt=r1, diagnosis_hash="4" * 64)
    projection = SimpleNamespace(r2_role_queries=r2_queries, projection_hash="5" * 64)
    projection.diagnosis = diagnosis
    response = SimpleNamespace(projection=projection, receipt_hash="6" * 64)
    retrieval = SimpleNamespace(
        plan=SimpleNamespace(
            trigger_coverage_receipt_hash=r1.receipt_hash,
            gap_repair_projection_hash=projection.projection_hash,
            base_merged_artifact_hash=base.artifact_hash,
            base_merged_catalog_hash=base.merged_catalog_hash,
        ),
        artifact_hash="7" * 64,
        repair_catalog_hash="8" * 64,
    )
    layered = SimpleNamespace(
        base_merged_artifact_hash=base.artifact_hash,
        base_merged_catalog_hash=base.merged_catalog_hash,
        repair_rounds=(SimpleNamespace(round_index=2),),
        artifact_hash="9" * 64,
        merged_catalog_hash="a" * 64,
    )
    r2 = PassingCoverage(
        schema_version="contest-planning-literature-coverage-v5",
        receipt_hash="b" * 64,
        role_queries=r2_queries,
        method_focus_basis_queries=r1_queries,
    )
    module = "autoresearch.competition.contest_direction_review_recovery_cli"
    monkeypatch.setattr(f"{module}.load_planning_literature_gap_diagnosis", lambda _p: diagnosis)
    monkeypatch.setattr(
        f"{module}.load_planning_literature_gap_repair_response", lambda _p: response
    )
    monkeypatch.setattr(
        f"{module}.load_planning_literature_gap_repair_projection", lambda _p: projection
    )
    monkeypatch.setattr(
        f"{module}.build_contest_direction_gap_repair_plan_from_projection",
        lambda **_kwargs: retrieval.plan,
    )
    monkeypatch.setattr(
        f"{module}.load_contest_direction_gap_repair",
        lambda _p, **_kwargs: retrieval,
    )
    monkeypatch.setattr(
        f"{module}.load_contest_direction_layered_literature",
        lambda *_args, **_kwargs: layered,
    )
    monkeypatch.setattr(f"{module}.load_planning_literature_coverage_receipt", lambda _p: r2)
    lock = {"gap_repair_chain": {"repair_round_count": 1}}

    chain, artifact_hash, catalog_hash = _replay_v5_gap_chain(
        literature_root=literature_root,
        lock=lock,
        base_merged=base,
        r1_coverage=r1,
        final_coverage=final,
    )

    assert chain == {
        "repair_round_count": 1,
        "gap_diagnosis_hash": diagnosis.diagnosis_hash,
        "gap_query_response_receipt_hash": response.receipt_hash,
        "gap_query_projection_hash": projection.projection_hash,
        "gap_retrieval_artifact_hash": retrieval.artifact_hash,
        "gap_retrieval_catalog_hash": retrieval.repair_catalog_hash,
        "layered_literature_artifact_hash": layered.artifact_hash,
        "r2_pre_status_coverage_receipt_hash": r2.receipt_hash,
    }
    assert artifact_hash == layered.artifact_hash
    assert catalog_hash == layered.merged_catalog_hash

    same_id_different_role_queries = tuple(
        SimpleNamespace(query_id=item.query_id, raw_query="different structured query")
        for item in r2_queries
    )
    same_id_different_basis = tuple(
        SimpleNamespace(query_id=item.query_id, raw_query="different frozen basis")
        for item in r1_queries
    )
    for target, field, tampered_value, original_value in (
        (r2, "role_queries", same_id_different_role_queries, r2_queries),
        (final, "role_queries", same_id_different_role_queries, r2_queries),
        (r2, "method_focus_basis_queries", same_id_different_basis, r1_queries),
        (final, "method_focus_basis_queries", same_id_different_basis, r1_queries),
    ):
        setattr(target, field, tampered_value)
        with pytest.raises(ContestDirectionReviewRecoveryError, match="exact R1-to-R2"):
            _replay_v5_gap_chain(
                literature_root=literature_root,
                lock=lock,
                base_merged=base,
                r1_coverage=r1,
                final_coverage=final,
            )
        setattr(target, field, original_value)

    monkeypatch.setattr(
        f"{module}.load_planning_literature_gap_repair_response",
        lambda _p: SimpleNamespace(projection=object(), receipt_hash="6" * 64),
    )
    with pytest.raises(ContestDirectionReviewRecoveryError, match="exact R1-to-R2"):
        _replay_v5_gap_chain(
            literature_root=literature_root,
            lock=lock,
            base_merged=base,
            r1_coverage=r1,
            final_coverage=final,
        )


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _embedded_evidence(*_args: Any, **_kwargs: Any) -> ContestPlanEmbeddedEvidenceBundle:
    return ContestPlanEmbeddedEvidenceBundle(
        payload={
            "schema_version": "contest-plan-embedded-evidence-v1",
            "execution_label_zh": "探索性预实验",
            "summary_zh": "仅用于探索性计划修订。",
            "analysis_zh": "该信号需要后续验证。",
            "scope_note_zh": "不是确认性结论。",
            "tables": [],
            "figures": [],
        },
        manifest_bindings=(),
    )


def _completion(payload: dict[str, Any], *, model: str) -> LLMJsonCompletionResult:
    response = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return LLMJsonCompletionResult(
        provider="openai-compatible",
        base_url="https://provider.example/v1",
        model_name=model,
        endpoint="https://provider.example/v1/chat/completions",
        response_text=response,
        parsed_json=payload,
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        temperature=0.2,
    )


def _source_bundle(root: Path) -> _BlockedReviewBundle:
    root.mkdir(parents=True)
    source_file = root / "frozen-source.txt"
    source_file.write_text("immutable source\n", encoding="utf-8")
    pilot_root = root / "pilot"
    pilot_root.mkdir()
    pilot_path = pilot_root / "preexperiment.json"
    pilot = {
        "status": "completed",
        "study_phase": "exploratory_pilot",
        "artifact_hash": "c" * 64,
    }
    pilot_path.write_text(json.dumps(pilot), encoding="utf-8")
    source_plan_path = root / "source-plan.json"
    source_render_manifest_path = root / "source-render-manifest.json"
    prior_review_path = root / "prior-review.json"
    block_receipt_path = root / "scientific-review-blocked-receipt.json"
    source_plan_path.write_text("{}", encoding="utf-8")
    source_render_manifest_path.write_text("{}", encoding="utf-8")
    prior_review_path.write_text("{}", encoding="utf-8")
    block_receipt_path.write_text("{}", encoding="utf-8")
    source_plan = SimpleNamespace(
        revision_id="direct-plan-revision-" + "1" * 16,
        artifact_hash="1" * 64,
        scientific_problem="一种材料响应机制是否可被有限预实验区分？",
        plan=SimpleNamespace(references=_REFERENCES),
    )
    review_content = SimpleNamespace(
        recommendation="major_revision",
        recommendation_text="需要大修",
        problem_restatement="重新界定可证伪问题。",
        strongest_counterevidence="现有信号也可能由测量漂移解释。",
        summary="计划需要收紧证据边界，相关依据见[2]。",
        hypothesis_evidence_assessment="假设强于预实验支持。",
        null_controls_assessment="需要更清楚地区分对照。",
        analysis_unit_assessment="需要冻结分析单位。",
        statistics_assessment="需要保持探索性统计语义。",
        overclaim_assessment="不得外推为确认性发现。",
        reproducibility_assessment="需要补足确定性复现步骤。",
        references_assessment="引用必须保持锁定。",
        strengths=("问题可计算",),
        major_issues=("收窄主张", "明确分析单位"),
        minor_issues=("统一术语",),
        reference_indices=(),
    )
    prior_review = SimpleNamespace(
        review_id="direct-plan-scientific-review-" + "2" * 16,
        artifact_hash="2" * 64,
        input_hash="3" * 64,
        review=review_content,
        locked_reference_catalog=_REFERENCES,
        selected_skill_sha256=("4" * 64,),
        preexperiment_artifact_hash="c" * 64,
        preexperiment_artifact_payload_sha256="d" * 64,
        preexperiment_metrics_payload_sha256="e" * 64,
        verified_files_sha256="f" * 64,
        reference_index_integrity_status="legacy_unverified_against_review_prose",
    )
    return _BlockedReviewBundle(
        root=root,
        direction="输入科学问题",
        focused_direction=source_plan.scientific_problem,
        source_literature_protocol="two_stage_literature_v3",
        source_plan_path=source_plan_path,
        source_plan=source_plan,
        source_render_manifest_path=source_render_manifest_path,
        source_render_source_payload_sha256="5" * 64,
        prior_review_path=prior_review_path,
        prior_review=prior_review,
        block_receipt_path=block_receipt_path,
        block_receipt_hash="6" * 64,
        preexperiment_path=pilot_path,
        preexperiment_root=pilot_root,
        reference_catalog=_REFERENCES,
        selected_skill_contexts=(
            {"skill_id": "generic-mechanism-method", "content": "只提供通用机制检验方法。"},
        ),
        source_inventory=_inventory(root),
    )


def _fake_revision_runner(call_log: list[dict[str, Any]]) -> Any:
    def run(**kwargs: Any) -> Any:
        call_log.append(kwargs)
        completion = kwargs["llm_call"](
            messages=[{"role": "user", "content": "generic revision"}],
            config_path=kwargs["config_path"],
            env_path=kwargs["env_path"],
            timeout_seconds=kwargs["timeout_seconds"],
            max_tokens=kwargs["max_tokens"],
            temperature=kwargs["temperature"],
            response_schema={"type": "object"},
            response_schema_name="generic_revision_test",
        )
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}", encoding="utf-8")
        revision_root = Path(kwargs["output_dir"])
        response_path = revision_root / "responses" / "revision.txt"
        receipt_path = revision_root / "interactions" / "revision.json"
        response_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(completion.response_text, encoding="utf-8")
        receipt_path.write_text("{}", encoding="utf-8")
        plan = SimpleNamespace(
            references=_REFERENCES,
            model_dump=lambda **_: {
                "problem_statement": "可证伪问题",
                "rationale": "根据预实验和终审收窄解释。",
            },
        )
        return SimpleNamespace(
            revision_id="direct-plan-revision-" + "7" * 16,
            artifact_hash="7" * 64,
            input_hash="8" * 64,
            original_plan_id=kwargs["original_plan"].revision_id,
            original_plan_artifact_hash=kwargs["original_plan"].artifact_hash,
            scientific_problem=kwargs["scientific_problem"],
            preexperiment_artifact_sha256="c" * 64,
            verified_revision_context_sha256=canonical_model_hash(
                kwargs["verified_revision_context"]
            ),
            plan=plan,
            generation_calls=1,
            raw_response_relative_path="responses/revision.txt",
            authorship_receipt_relative_path="interactions/revision.json",
            authorship_receipt_hash="9" * 64,
            model_response_hash=hashlib.sha256(response_path.read_bytes()).hexdigest(),
            flat_payload=lambda: {
                "title": "修订后的研究计划",
                "abstract": "这是修订后的完整计划。",
                "problem_statement": "可证伪问题",
                "rationale": "根据预实验和终审收窄解释。",
                "technical_details": "冻结分析单位与对照。",
                "datasets": {
                    "description": "有限预实验数据",
                    "source": "已核验来源",
                    "target": "响应",
                },
                "methods": "机制区分方法",
                "experiments": {
                    "steps": "后续验证",
                    "baselines": "条件对照",
                    "metrics": "区间估计",
                },
                "results": "预实验仅显示探索性信号。",
                "references": list(_REFERENCES),
            },
        )

    return run


def _fake_materializer(**kwargs: Any) -> ContestDirectPlanArtifacts:
    root = Path(kwargs["output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": root / "research-plan.json",
        "source": root / "research-plan-source.json",
        "markdown": root / "research-plan.md",
        "tex": root / "research-plan.tex",
        "pdf": root / "research-plan.pdf",
        "manifest": root / "research-plan-manifest.json",
    }
    public_payload = _public_plan_projection(kwargs["payload"])
    paths["json"].write_text(json.dumps(public_payload, ensure_ascii=False), encoding="utf-8")
    paths["source"].write_text(json.dumps(kwargs["payload"], ensure_ascii=False), encoding="utf-8")
    paths["markdown"].write_text("# 修订后的研究计划\n", encoding="utf-8")
    paths["tex"].write_text("render", encoding="utf-8")
    paths["pdf"].write_bytes(b"%PDF-test")
    bindings = sorted(
        (dict(item) for item in kwargs["evidence_bindings"]),
        key=lambda item: (str(item.get("path")), str(item.get("role"))),
    )
    manifest = {
        "source_payload_sha256": canonical_model_hash(kwargs["payload"]),
        "public_payload_sha256": canonical_model_hash(public_payload),
        "embedded_evidence": {
            "present": True,
            "content_sha256": canonical_model_hash(kwargs["payload"]["embedded_evidence"]),
            "provenance_bindings": bindings,
            "provenance_bindings_sha256": canonical_model_hash({"evidence_bindings": bindings}),
        },
    }
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    return ContestDirectPlanArtifacts(
        output_dir=root,
        json_path=paths["json"],
        source_path=paths["source"],
        markdown_path=paths["markdown"],
        tex_path=paths["tex"],
        pdf_path=paths["pdf"],
        manifest_path=paths["manifest"],
        source_payload_sha256=canonical_model_hash(kwargs["payload"]),
        page_count=4,
        pdf_text_verified=True,
    )


def _fake_review_runner(
    call_log: list[dict[str, Any]],
    recommendation: str,
    *,
    stale_plan_binding: bool = False,
) -> Any:
    def run(**kwargs: Any) -> Any:
        call_log.append(kwargs)
        completion = kwargs["llm_call"](
            messages=[{"role": "user", "content": "fresh independent review"}],
            config_path=kwargs["config_path"],
            env_path=kwargs["env_path"],
            timeout_seconds=kwargs["timeout_seconds"],
            max_tokens=kwargs["max_tokens"],
            temperature=kwargs["temperature"],
            thinking_mode="disabled",
            thinking_budget=None,
            response_schema={"type": "object"},
            response_schema_name="generic_review_test",
        )
        root = Path(kwargs["output_dir"])
        response_path = root / "responses" / "review.txt"
        receipt_path = root / "interactions" / "review.json"
        markdown_path = root / "scientific-review.md"
        json_path = root / "system-plan-scientific-review.json"
        response_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(completion.response_text, encoding="utf-8")
        receipt_path.write_text("{}", encoding="utf-8")
        markdown_path.write_text("# 独立复审\n", encoding="utf-8")
        json_path.write_text("{}", encoding="utf-8")
        final_plan_path = Path(kwargs["final_plan"])
        final_plan_payload = json.loads(final_plan_path.read_text(encoding="utf-8"))
        final_plan_hash = canonical_model_hash(final_plan_payload)
        if stale_plan_binding:
            final_plan_hash = "0" * 64
        return SimpleNamespace(
            review_id="direct-plan-scientific-review-" + "a" * 16,
            artifact_hash="a" * 64,
            input_hash="b" * 64,
            review=SimpleNamespace(
                recommendation=recommendation,
                recommendation_text=recommendation,
                references_assessment="已核对锁定目录[1]。",
                reference_indices=(1,),
            ),
            locked_reference_catalog=_REFERENCES,
            selected_skill_sha256=("4" * 64,),
            reference_index_integrity_status="verified_exact_union",
            scientific_problem=final_plan_payload["problem_statement"],
            final_plan_id=f"materialized-final-plan-{final_plan_hash[:16]}",
            final_plan_source_kind="materialized_final_plan",
            final_plan_artifact_hash=final_plan_hash,
            final_plan_payload_sha256=final_plan_hash,
            final_plan_source_file_sha256=hashlib.sha256(final_plan_path.read_bytes()).hexdigest(),
            preexperiment_artifact_hash="c" * 64,
            preexperiment_artifact_payload_sha256="d" * 64,
            preexperiment_metrics_payload_sha256="e" * 64,
            verified_files_sha256="f" * 64,
            generation_calls=1,
            plan_rewrite_performed=False,
            prior_audit_context_supplied=False,
            required_audit_findings_sha256=None,
            independence_scope="fresh_interaction_not_model_family_independence",
            raw_response_relative_path="responses/review.txt",
            authorship_receipt_relative_path="interactions/review.json",
            markdown_relative_path="scientific-review.md",
        )

    return run


def test_one_shot_recovery_uses_new_root_and_keeps_rereview_blind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    original_source_bytes = (source.root / "frozen-source.txt").read_bytes()
    revision_calls: list[dict[str, Any]] = []
    review_calls: list[dict[str, Any]] = []
    revision_provider_calls = 0
    review_provider_calls = 0

    def revision_completion(**_: Any) -> LLMJsonCompletionResult:
        nonlocal revision_provider_calls
        revision_provider_calls += 1
        return _completion({"stage": "revision"}, model="author-model")

    def review_completion(**_: Any) -> LLMJsonCompletionResult:
        nonlocal review_provider_calls
        review_provider_calls += 1
        return _completion({"stage": "review"}, model="review-model")

    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli._verify_revision_sidecars",
        lambda *_args, **_kwargs: None,
    )
    real_checkpoint_count = review_cli.provider_checkpoint_count

    def provider_accounting(root: Path, *, stage_name: str) -> dict[str, int]:
        completed = real_checkpoint_count(root, stage_name=stage_name)
        transport_failures = 1 if stage_name == review_cli._REVISION_STAGE and completed else 0
        return {
            "attempt_count": completed + transport_failures,
            "completed_count": completed,
            "parse_failed_count": 0,
            "transport_failed_count": transport_failures,
            "terminal_failed_count": 0,
            "outcome_unknown_count": 0,
        }

    monkeypatch.setattr(
        review_cli,
        "provider_checkpoint_accounting",
        provider_accounting,
        raising=False,
    )
    result = run_contest_direction_review_recovery(
        source_blocked_dir=source.root,
        output_dir=tmp_path / "recovery",
        source_loader=lambda _root: source,
        revision_runner=_fake_revision_runner(revision_calls),
        plan_materializer=_fake_materializer,
        review_runner=_fake_review_runner(review_calls, "pass"),
        revision_completion=revision_completion,
        review_completion=review_completion,
        embedded_evidence_builder=_embedded_evidence,
        render_verifier=lambda _rendered: (4, "test"),
    )

    assert result["status"] == "completed"
    assert revision_provider_calls == 1
    assert review_provider_calls == 1
    assert len(revision_calls) == len(review_calls) == 1
    assert revision_calls[0]["original_plan"].artifact_hash == source.source_plan.artifact_hash
    requirements = "\n".join(revision_calls[0]["requirements"])
    assert source.prior_review.artifact_hash not in requirements
    assert "评审批评不是新增科学事实" in requirements
    assert (
        revision_calls[0]["verified_revision_context"]["source_review_artifact_hash"]
        == source.prior_review.artifact_hash
    )
    assert review_calls[0]["required_audit_findings"] == ()
    assert review_calls[0]["derived_memory_context"] is None
    assert source.prior_review.artifact_hash not in json.dumps(
        review_calls[0], ensure_ascii=False, default=str
    )
    assert (source.root / "frozen-source.txt").read_bytes() == original_source_bytes
    assert result["model_call_accounting"]["recovery_lifetime_provider_responses"] == 2
    assert result["model_call_accounting"]["current_invocation_provider_requests"] == 2
    assert result["model_call_accounting"]["provider_physical_attempts_by_stage"] == {
        "review-driven-plan-revision": 2,
        "fresh-independent-scientific-rereview": 1,
    }
    assert result["model_call_accounting"]["provider_physical_attempts_lifetime"] == 3
    assert result["model_call_accounting"]["current_invocation_provider_physical_attempts"] == 3
    assert result["formal_experiment_executed"] is False
    assert result["paper_claimed"] is False
    receipt = json.loads((tmp_path / "recovery" / "review-recovery-input.json").read_text())
    assert (
        receipt["source_review_reference_structure"]["status"]
        == "legacy_unverified_against_review_prose"
    )
    assert result["locked_reference_catalog"] == list(_REFERENCES)


def test_blocking_fresh_rereview_stops_without_a_second_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    revision_calls: list[dict[str, Any]] = []
    review_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli._verify_revision_sidecars",
        lambda *_args, **_kwargs: None,
    )

    common = {
        "source_blocked_dir": source.root,
        "output_dir": tmp_path / "recovery",
        "source_loader": lambda _root: source,
        "revision_runner": _fake_revision_runner(revision_calls),
        "plan_materializer": _fake_materializer,
        "review_runner": _fake_review_runner(review_calls, "major_revision"),
        "revision_completion": lambda **_: _completion({"stage": "revision"}, model="author"),
        "review_completion": lambda **_: _completion({"stage": "review"}, model="reviewer"),
        "embedded_evidence_builder": _embedded_evidence,
        "render_verifier": lambda _rendered: (4, "test"),
    }
    result = run_contest_direction_review_recovery(**common)

    def forbidden(**_: Any) -> LLMJsonCompletionResult:
        raise AssertionError("terminal blocking recovery must not call a provider again")

    resumed = run_contest_direction_review_recovery(
        **{
            **common,
            "resume_existing": True,
            "revision_completion": forbidden,
            "review_completion": forbidden,
        }
    )

    assert result["status"] == "blocked_after_fresh_independent_review"
    assert resumed["resume_action"] == "already_complete_no_model_call"
    assert len(revision_calls) == len(review_calls) == 1
    assert result["automatic_additional_revision_performed"] is False


def test_completed_recovery_resume_is_zero_call_and_source_output_must_be_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "recovery"
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli._verify_revision_sidecars",
        lambda *_args, **_kwargs: None,
    )
    common = {
        "source_blocked_dir": source.root,
        "output_dir": output,
        "source_loader": lambda _root: source,
        "revision_runner": _fake_revision_runner([]),
        "plan_materializer": _fake_materializer,
        "review_runner": _fake_review_runner([], "minor_revision"),
        "revision_completion": lambda **_: _completion({"stage": "revision"}, model="author"),
        "review_completion": lambda **_: _completion({"stage": "review"}, model="reviewer"),
        "embedded_evidence_builder": _embedded_evidence,
        "render_verifier": lambda _rendered: (4, "test"),
    }
    first = run_contest_direction_review_recovery(**common)

    def forbidden(**_: Any) -> LLMJsonCompletionResult:
        raise AssertionError("resume must not call a provider")

    resumed = run_contest_direction_review_recovery(
        **{
            **common,
            "resume_existing": True,
            "revision_completion": forbidden,
            "review_completion": forbidden,
        }
    )

    assert first["status"] == "completed_with_minor_issues"
    assert first["model_call_accounting"]["provider_physical_attempts_lifetime"] == 2
    assert first["model_call_accounting"]["current_invocation_provider_physical_attempts"] == 2
    assert resumed["resume_action"] == "already_complete_no_model_call"
    assert resumed["model_call_accounting"]["current_invocation_provider_requests"] == 0
    assert resumed["model_call_accounting"]["current_invocation_provider_physical_attempts"] == 0
    with pytest.raises(ContestDirectionReviewRecoveryError, match="distinct"):
        run_contest_direction_review_recovery(
            **{**common, "output_dir": source.root, "resume_existing": False}
        )


def test_partial_recovery_resume_counts_only_new_physical_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    output = tmp_path / "recovery"
    revision_calls: list[dict[str, Any]] = []
    review_calls: list[dict[str, Any]] = []
    retained_revisions: list[Any] = []
    monkeypatch.setattr(review_cli, "_verify_revision_sidecars", lambda *_args, **_kwargs: None)
    real_checkpoint_count = review_cli.provider_checkpoint_count

    def provider_accounting(root: Path, *, stage_name: str) -> dict[str, int]:
        completed = real_checkpoint_count(root, stage_name=stage_name)
        transport_failures = 1 if stage_name == review_cli._REVISION_STAGE and completed else 0
        return {
            "attempt_count": completed + transport_failures,
            "completed_count": completed,
            "parse_failed_count": 0,
            "transport_failed_count": transport_failures,
            "terminal_failed_count": 0,
            "outcome_unknown_count": 0,
        }

    monkeypatch.setattr(
        review_cli,
        "provider_checkpoint_accounting",
        provider_accounting,
        raising=False,
    )
    fake_revision = _fake_revision_runner(revision_calls)

    def revision_runner(**kwargs: Any) -> Any:
        revision = fake_revision(**kwargs)
        retained_revisions.append(revision)
        return revision

    common = {
        "source_blocked_dir": source.root,
        "output_dir": output,
        "source_loader": lambda _root: source,
        "revision_runner": revision_runner,
        "review_runner": _fake_review_runner(review_calls, "pass"),
        "revision_completion": lambda **_: _completion({"stage": "revision"}, model="author"),
        "review_completion": lambda **_: _completion({"stage": "review"}, model="reviewer"),
        "embedded_evidence_builder": _embedded_evidence,
        "render_verifier": lambda _rendered: (4, "test"),
    }

    def crash_after_revision(**_kwargs: Any) -> ContestDirectPlanArtifacts:
        raise RuntimeError("synthetic crash after retained revision")

    with pytest.raises(RuntimeError, match="synthetic crash"):
        run_contest_direction_review_recovery(
            **{**common, "plan_materializer": crash_after_revision}
        )

    class RetainedRevisionArtifact:
        @staticmethod
        def model_validate_json(_text: str) -> Any:
            return retained_revisions[0]

    monkeypatch.setattr(
        review_cli,
        "ContestDirectPlanRevisionArtifact",
        RetainedRevisionArtifact,
    )

    resumed = run_contest_direction_review_recovery(
        **{
            **common,
            "resume_existing": True,
            "plan_materializer": _fake_materializer,
        }
    )

    assert len(revision_calls) == len(review_calls) == 1
    assert resumed["model_call_accounting"]["provider_physical_attempts_by_stage"] == {
        "review-driven-plan-revision": 2,
        "fresh-independent-scientific-rereview": 1,
    }
    assert resumed["model_call_accounting"]["provider_physical_attempts_lifetime"] == 3
    assert resumed["model_call_accounting"]["current_invocation_provider_physical_attempts"] == 1
    assert resumed["model_call_accounting"]["current_invocation_provider_requests"] == 1


def test_fresh_review_for_another_rendered_plan_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    review_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli._verify_revision_sidecars",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ContestDirectionReviewRecoveryError, match="rendered public plan"):
        run_contest_direction_review_recovery(
            source_blocked_dir=source.root,
            output_dir=tmp_path / "recovery",
            source_loader=lambda _root: source,
            revision_runner=_fake_revision_runner([]),
            plan_materializer=_fake_materializer,
            review_runner=_fake_review_runner(
                review_calls,
                "pass",
                stale_plan_binding=True,
            ),
            revision_completion=lambda **_: _completion({"stage": "revision"}, model="author"),
            review_completion=lambda **_: _completion({"stage": "review"}, model="reviewer"),
            embedded_evidence_builder=_embedded_evidence,
            render_verifier=lambda _rendered: (4, "test"),
        )

    assert len(review_calls) == 1


def test_source_block_receipt_replay_uses_the_source_declared_v2_through_v5_protocol(
    tmp_path: Path,
) -> None:
    source = _source_bundle(tmp_path / "source")
    receipts = {
        protocol: _source_block_receipt_payload(
            direction=source.direction,
            focused_direction=source.focused_direction,
            final_review=source.prior_review,
            review_path=source.prior_review_path,
            literature_protocol=protocol,
        )
        for protocol in (
            "two_stage_literature_v2",
            "two_stage_literature_v3",
            "two_stage_literature_v4",
            "two_stage_literature_v5",
        )
    }

    for protocol, receipt in receipts.items():
        assert receipt["literature_protocol"] == protocol
        assert receipt["receipt_hash"] == canonical_model_hash(
            {key: value for key, value in receipt.items() if key != "receipt_hash"}
        )
    assert (
        receipts["two_stage_literature_v2"]["receipt_hash"]
        != receipts["two_stage_literature_v3"]["receipt_hash"]
    )
    assert (
        receipts["two_stage_literature_v3"]["receipt_hash"]
        != receipts["two_stage_literature_v4"]["receipt_hash"]
    )
    assert (
        receipts["two_stage_literature_v4"]["receipt_hash"]
        != receipts["two_stage_literature_v5"]["receipt_hash"]
    )


def test_completed_pilot_must_be_embedded_before_fresh_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli._verify_revision_sidecars",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ContestDirectionReviewRecoveryError, match="could not be embedded"):
        run_contest_direction_review_recovery(
            source_blocked_dir=source.root,
            output_dir=tmp_path / "recovery",
            source_loader=lambda _root: source,
            revision_runner=_fake_revision_runner([]),
            plan_materializer=_fake_materializer,
            review_runner=_fake_review_runner([], "pass"),
            revision_completion=lambda **_: _completion({"stage": "revision"}, model="author"),
            embedded_evidence_builder=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        ("completed", 0),
        ("completed_with_minor_issues", 0),
        ("blocked_after_fresh_independent_review", 2),
    ],
)
def test_cli_exit_code_distinguishes_terminal_block(
    status: str,
    expected_exit: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli.run_contest_direction_review_recovery",
        lambda **_kwargs: {"status": status},
    )

    assert (
        main(
            [
                "--source-blocked-dir",
                str(tmp_path / "source"),
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == expected_exit
    )


def test_second_revision_completion_is_rejected_before_a_second_provider_call(
    tmp_path: Path,
) -> None:
    source = _source_bundle(tmp_path / "source")
    provider_calls = 0

    def provider(**_: Any) -> LLMJsonCompletionResult:
        nonlocal provider_calls
        provider_calls += 1
        return _completion({"stage": "revision"}, model="author")

    def double_calling_revision(**kwargs: Any) -> Any:
        llm_call = kwargs["llm_call"]
        common = {
            "config_path": kwargs["config_path"],
            "env_path": kwargs["env_path"],
            "timeout_seconds": kwargs["timeout_seconds"],
            "max_tokens": kwargs["max_tokens"],
            "temperature": kwargs["temperature"],
            "response_schema": {"type": "object"},
            "response_schema_name": "single_call_gate_test",
        }
        llm_call(messages=[{"role": "user", "content": "first"}], **common)
        llm_call(messages=[{"role": "user", "content": "second"}], **common)
        raise AssertionError("the second completion must fail before this line")

    with pytest.raises(ContestDirectionReviewRecoveryError, match="more than one completion"):
        run_contest_direction_review_recovery(
            source_blocked_dir=source.root,
            output_dir=tmp_path / "recovery",
            source_loader=lambda _root: source,
            revision_runner=double_calling_revision,
            revision_completion=provider,
        )

    assert provider_calls == 1


def test_provider_escrow_request_must_equal_authorship_receipt_messages(
    tmp_path: Path,
) -> None:
    stage_hash = "1" * 64
    completion = _completion({"value": "retained"}, model="author")
    escrowed = replayable_stage_completion(
        root=tmp_path,
        stage_name="generic-stage",
        stage_input_hash=stage_hash,
        completion=lambda **_: completion,
    )
    escrowed(
        messages=[{"role": "user", "content": "escrow request"}],
        config_path=Path("config.yaml"),
        env_path=Path(".env"),
        timeout_seconds=30,
        max_tokens=100,
        temperature=0.2,
        response_schema={"type": "object"},
        response_schema_name="escrow_binding_test",
    )
    receipt = record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id="mismatched-request",
        attempt=1,
        messages=[{"role": "user", "content": "different receipt request"}],
        completion=completion,
        output_dir=tmp_path / "authorship",
    )

    with pytest.raises(ContestDirectionReviewRecoveryError, match="provider request differs"):
        _verify_provider_escrow_binding(
            root=tmp_path,
            stage_name="generic-stage",
            stage_input_hash=stage_hash,
            receipt=receipt,
        )


def test_source_mutation_is_detected_immediately_after_revision_callback(
    tmp_path: Path,
) -> None:
    source = _source_bundle(tmp_path / "source")
    review_calls: list[dict[str, Any]] = []
    base_revision = _fake_revision_runner([])

    def mutating_revision(**kwargs: Any) -> Any:
        artifact = base_revision(**kwargs)
        (source.root / "frozen-source.txt").write_text("changed\n", encoding="utf-8")
        return artifact

    with pytest.raises(ContestDirectionReviewRecoveryError, match="blocked source bytes changed"):
        run_contest_direction_review_recovery(
            source_blocked_dir=source.root,
            output_dir=tmp_path / "recovery",
            source_loader=lambda _root: source,
            revision_runner=mutating_revision,
            review_runner=_fake_review_runner(review_calls, "pass"),
            revision_completion=lambda **_: _completion({"stage": "revision"}, model="author"),
        )

    assert review_calls == []


def test_public_render_must_be_the_deterministic_projection_of_private_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_bundle(tmp_path / "source")
    review_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_review_recovery_cli._verify_revision_sidecars",
        lambda *_args, **_kwargs: None,
    )

    def divergent_materializer(**kwargs: Any) -> ContestDirectPlanArtifacts:
        rendered = _fake_materializer(**kwargs)
        public = json.loads(rendered.json_path.read_text(encoding="utf-8"))
        public["title"] = "另一份公开计划"
        rendered.json_path.write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
        manifest = json.loads(rendered.manifest_path.read_text(encoding="utf-8"))
        manifest["public_payload_sha256"] = canonical_model_hash(public)
        rendered.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return rendered

    with pytest.raises(ContestDirectionReviewRecoveryError, match="projections are inconsistent"):
        run_contest_direction_review_recovery(
            source_blocked_dir=source.root,
            output_dir=tmp_path / "recovery",
            source_loader=lambda _root: source,
            revision_runner=_fake_revision_runner([]),
            plan_materializer=divergent_materializer,
            review_runner=_fake_review_runner(review_calls, "pass"),
            revision_completion=lambda **_: _completion({"stage": "revision"}, model="author"),
            embedded_evidence_builder=_embedded_evidence,
            render_verifier=lambda _rendered: (4, "test"),
        )

    assert review_calls == []
