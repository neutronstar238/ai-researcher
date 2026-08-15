from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from autoresearch.competition.contest_direct_plan_render import ContestDirectPlanArtifacts
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionArtifact,
    ContestDirectRevisedScientificPlan,
)
from autoresearch.competition.contest_direction_scientific_amendment_cli import (
    _PriorAmendmentAttempt,
    _SourceBundle,
)
from autoresearch.competition.contest_direction_targeted_scientific_repair_cli import (
    _ALL_PLAN_FIELDS,
    _FROZEN_FIELDS,
    _REPAIR_FIELDS,
    _RT06_REPAIR_FIELDS,
    _merge_frozen_plan,
    _repair_response_schema,
    _RepairSources,
    run_contest_direction_targeted_scientific_repair,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.llm.client import LLMJsonCompletionResult

_HASH = "a" * 64
_REFERENCES = (
    "Bandt, C. & Pompe, B. Permutation entropy: a natural complexity measure.",
    "Bian, C. et al. Modified permutation-entropy analysis for ties.",
    "Lemke Oliver, R. & Soundararajan, K. Unexpected biases in consecutive primes.",
    "Banks, W., Ford, K. & Tao, T. Large prime gaps and admissible tuples.",
    "Phipson, B. & Smyth, G. K. Permutation p-values should never be zero.",
)


def _write(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _base_plan() -> ContestDirectRevisedScientificPlan:
    return ContestDirectRevisedScientificPlan(
        problem_statement="冻结问题：连续整数素数的有序间隙是否含有可检验的残余序列信息？",
        rationale="冻结理由：锁定来源只定义方法，不直接证明本计划的新残差信号。",
        technical_details="旧技术细节需要定向修复，但不会用于最终审计。",
        datasets="冻结数据：程序生成并逐项验证的连续素数间隙。",
        source="冻结来源：确定性筛法与带哈希的真实预实验文件。",
        target="冻结目标：有序间隙弱序模式熵相对四类零模型的残差。",
        paper_title="冻结标题：连续素数间隙弱序信息的可证伪研究计划",
        paper_abstract="旧摘要只说明真实预实验已经执行，现需修复统计边界。",
        methods="旧方法需要定向修复。",
        experiments="旧实验设计需要定向修复。",
        baselines="旧基线描述需要定向修复。",
        metrics="冻结指标：弱序模式熵、加一蒙特卡洛概率、Holm校正与模拟诊断。",
        results="旧预实验结果需要定向修复。",
        references=_REFERENCES,
        main_hypothesis="冻结假设：控制已知结构后仍可能存在可复现的弱序残差。",
        limitations="旧预实验局限需要定向修复。",
    )


def _valid_replacements() -> dict[str, str]:
    method = (
        "残基路径置换严格使用条件键(segment,left mod30,right mod30)，不是mod210。"
        "wheel-210敏感性零模型在每个100000宽数轴段保持观察点数并固定首末端点，"
        "从与210互素的允许候选点中无放回抽取。"
        "弱序weak-order rank pattern由严格大于关系编码，模式空间为ordered Bell "
        "number Fubini(5)=541，不把并列值随机拆开。"
        "正式实验另行定义每块10^6个连续素数作为分析单位，该单位不同于预实验；"
        "四类零模型各运行999次draws，使用+1 Monte Carlo p并在四模型family内作"
        "Holm校正，目标adjusted p<0.01。"
    )
    result = (
        "真实探索性预实验使用五个数轴宽10^6的固定整数区间，每区间得到56359至"
        "70434个素数间隙。每类零模型执行199 draws，aggregate raw p=0.005，"
        "四模型Holm校正p=0.02，因此只在alpha=0.05（α=0.05）下作探索性描述。"
        "standardized_effect的z仅是有限simulation null SD下的模拟诊断，非总体效应量。"
    )
    return {
        "paper_abstract": result,
        "technical_details": method,
        "methods": method,
        "experiments": method,
        "baselines": "分别比较全局置换、残基路径、wheel-210敏感性和固定区间重采样。",
        "results": result,
        "limitations": "预实验仅为探索性计算；五个区间不能外推总体，z模拟诊断非总体效应量。",
    }


def _revision_artifact(
    plan: ContestDirectRevisedScientificPlan,
    *,
    input_digit: str,
) -> ContestDirectPlanRevisionArtifact:
    input_hash = input_digit * 64
    verified_files = [
        {
            "role": "metrics",
            "path": "metrics.json",
            "sha256": "b" * 64,
            "size_bytes": 2,
            "media_type": "application/json",
            "text_supplied_to_model": True,
        }
    ]
    payload: dict[str, Any] = {
        "schema_version": "contest-direct-plan-revision-v1",
        "document_type": "含真实预实验结果的科学假设与研究计划",
        "revision_id": f"direct-plan-revision-{input_hash[:16]}",
        "status": "revised_from_verified_preexperiment",
        "scientific_problem": "素数之间有何关系？",
        "original_plan_id": "prior-plan",
        "original_plan_artifact_hash": "c" * 64,
        "preexperiment_artifact_sha256": "d" * 64,
        "preexperiment_metrics_sha256": "e" * 64,
        "verified_files": verified_files,
        "verified_files_sha256": canonical_model_hash({"files": verified_files}),
        "plan": plan.model_dump(mode="json"),
        "provider": "openai-compatible",
        "model_name": "qwen-test",
        "generation_calls": 1,
        "input_hash": input_hash,
        "model_response_hash": "f" * 64,
        "raw_response_relative_path": "responses/source.txt",
        "authorship_receipt_relative_path": "interactions/source.json",
        "authorship_receipt_hash": "1" * 64,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return ContestDirectPlanRevisionArtifact.model_validate(payload)


def _prior_attempt(
    tmp_path: Path, name: str, plan: ContestDirectPlanRevisionArtifact
) -> _PriorAmendmentAttempt:
    root = tmp_path / name
    return _PriorAmendmentAttempt(
        root=root,
        input_path=_write(root / "amendment-input.json"),
        plan_path=_write(root / "system-authored-amended-research-plan.json"),
        plan=plan,
        audit_path=_write(root / "scientific-amendment-audit.json"),
        audit={
            "artifact_hash": ("2" if name == "v2" else "3") * 64,
            "checks": [
                {"finding_id": "RT-02", "passed": False},
                {"finding_id": "RT-05", "passed": False},
                {"finding_id": "RT-06", "passed": False},
            ],
        },
        findings_path=_write(root / "scientific-red-team-findings.json"),
        findings={"artifact_hash": "4" * 64},
        review_response_path=_write(
            root / "independent-scientific-review" / "responses" / "review.txt",
            f"preserved {name} review",
        ),
        review_interaction_path=_write(
            root / "independent-scientific-review" / "interactions" / "review.json"
        ),
    )


def _sources(tmp_path: Path) -> _RepairSources:
    source = tmp_path / "v1"
    pilot_root = source / "preexperiment" / "prime-pilot-test"
    metrics_payload = {
        "aggregate_results": [
            {
                "null_model": "residue_path_conditioned_permutation",
                "observed_mean_entropy": 0.91,
                "null_mean_entropy": 0.912,
                "delta_observed_minus_null": -0.002,
                "one_sided_empirical_p_lower": 0.005,
                "holm_adjusted_p_across_null_models": 0.02,
            }
        ],
        "interval_results": [
            {
                "interval_index": 1,
                "start": 0,
                "stop": 10**6,
                "gap_count": 56_359,
                "observed_metrics": {
                    "tie_aware_normalized_permutation_entropy_m5": 0.91
                },
            }
        ],
    }
    metrics_path = _write(
        pilot_root / "metrics.json",
        json.dumps(metrics_payload, ensure_ascii=False),
    )
    pilot_path = _write(source / "preexperiment" / "system-plan-preexperiment.json", "{}")
    v1_plan = _revision_artifact(_base_plan(), input_digit="5")
    v2_plan = _revision_artifact(_base_plan(), input_digit="6")
    v3_plan = _revision_artifact(_base_plan(), input_digit="7")
    pilot = SimpleNamespace(
        status="completed",
        run_id="prime-pilot-1234567890abcdef",
        artifact_hash="8" * 64,
        metrics_sha256=hashlib.sha256(metrics_path.read_bytes()).hexdigest(),
        manifest_sha256="9" * 64,
        metrics_relative_path=metrics_path.name,
        study_phase="exploratory_preexperiment",
        parameters=SimpleNamespace(
            null_draws=199,
            alpha=0.05,
            wheel_modulus=210,
            wheel_density_segment_width=100_000,
            residue_path_segment_size=4096,
            ordinal_dimension=5,
        ),
        aggregate_results=[
            SimpleNamespace(
                one_sided_empirical_p_lower=0.005,
                holm_adjusted_p_across_null_models=0.02,
            )
            for _ in range(4)
        ],
        interval_results=[
            SimpleNamespace(start=i * 10**6, stop=(i + 1) * 10**6, gap_count=count)
            for i, count in enumerate((56_359, 60_000, 63_000, 68_000, 70_434))
        ],
    )
    v1 = _SourceBundle(
        root=source,
        report_path=_write(source / "delivery-report.json"),
        report={"file_inventory_hash": _HASH},
        direction="素数之间有何关系？",
        plan_path=_write(source / "system-authored-final-research-plan.json"),
        plan=v1_plan,
        pilot_root=pilot_root,
        pilot_path=pilot_path,
        pilot=pilot,  # type: ignore[arg-type]
        references=_REFERENCES,
        skill_contexts=({"skill_id": "number-theory", "content": "计算数论方法技能"},),
        source_code_sha256="a" * 64,
    )
    return _RepairSources(
        v1=v1,
        v2=_prior_attempt(tmp_path, "v2", v2_plan),
        v3=_prior_attempt(tmp_path, "v3", v3_plan),
        v3_review=SimpleNamespace(artifact_hash="b" * 64),  # type: ignore[arg-type]
    )


def _completion(payload: dict[str, str]) -> LLMJsonCompletionResult:
    response = json.dumps(payload, ensure_ascii=False)
    return LLMJsonCompletionResult(
        provider="openai-compatible",
        base_url="https://provider.example/v1",
        model_name="qwen-test",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=response,
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.1,
    )


def _materializer(calls: list[str], **kwargs: Any) -> ContestDirectPlanArtifacts:
    calls.append("render")
    root = Path(kwargs["output_dir"])
    payload = kwargs["payload"]
    assert len(payload["embedded_evidence"]["tables"]) == 2
    assert len(payload["embedded_evidence"]["figures"]) == 1
    assert kwargs["evidence_bindings"]
    files = {
        "json": _write(root / "research-plan.json", json.dumps(payload, ensure_ascii=False)),
        "markdown": _write(root / "research-plan.md", "# 研究计划"),
        "tex": _write(root / "research-plan.tex", "研究计划"),
        "pdf": _write(root / "research-plan.pdf", "%PDF-mock"),
        "manifest": _write(root / "research-plan-manifest.json"),
    }
    return ContestDirectPlanArtifacts(
        output_dir=root,
        json_path=files["json"],
        markdown_path=files["markdown"],
        tex_path=files["tex"],
        pdf_path=files["pdf"],
        manifest_path=files["manifest"],
        source_payload_sha256=hashlib.sha256(b"mock").hexdigest(),
        page_count=1,
        pdf_text_verified=True,
    )


def test_targeted_repair_mock_e2e_freezes_other_fields_and_calls_each_model_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path)
    output = tmp_path / "v4"
    replacements = _valid_replacements()
    calls: list[str] = []
    loaded_roots: list[tuple[Path, Path, Path]] = []

    def sources_loader(v1: Path, v2: Path, v3: Path) -> _RepairSources:
        loaded_roots.append((v1, v2, v3))
        return sources

    def repair_completion(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append("repair")
        assert set(kwargs["response_schema"]["required"]) == set(_REPAIR_FIELDS)
        assert kwargs["response_schema"]["additionalProperties"] is False
        assert set(replacements) == set(_REPAIR_FIELDS)
        return _completion(replacements)

    def review_runner(**kwargs: Any) -> Any:
        calls.append("review")
        assert [item["finding_id"] for item in kwargs["required_audit_findings"]] == [
            "RT-02",
            "RT-05",
            "RT-06",
        ]
        _write(Path(kwargs["output_dir"]) / "system-plan-scientific-review.json")
        return SimpleNamespace(
            generation_calls=1,
            plan_rewrite_performed=False,
            prior_audit_context_supplied=True,
            review=SimpleNamespace(recommendation="pass"),
            artifact_hash="c" * 64,
        )

    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_targeted_scientific_repair_cli._guard_observed_numbers",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_targeted_scientific_repair_cli._verify_rendered_pdf",
        lambda _rendered: (1, "mock"),
    )
    report = run_contest_direction_targeted_scientific_repair(
        source_delivery_dir=tmp_path / "v1",
        v2_attempt_dir=tmp_path / "v2",
        v3_attempt_dir=tmp_path / "v3",
        output_dir=output,
        sources_loader=sources_loader,
        repair_completion=repair_completion,
        plan_materializer=lambda **kwargs: _materializer(calls, **kwargs),
        review_runner=review_runner,
    )

    assert calls == ["repair", "render", "review"]
    assert len(loaded_roots) == 1
    assert report["status"] == "completed"
    assert report["model_call_accounting"] == {
        "targeted_repair_calls": 1,
        "fresh_independent_review_calls": 1,
        "total_new_provider_requests": 2,
        "content_retry_calls": 0,
    }
    assert all(
        report["source_lineage"][key] is False
        for key in (
            "retrieval_rerun",
            "skill_routing_rerun",
            "hypothesis_rerun",
            "preexperiment_rerun",
        )
    )
    audit = json.loads((output / "targeted-scientific-repair-audit.json").read_text("utf-8"))
    assert audit["all_required_corrections_passed"] is True
    assert audit["frozen_fields_verified"] is True
    assert [item["finding_id"] for item in audit["checks"]] == [
        f"RT-{index:02d}" for index in range(1, 8)
    ]
    assert all(item["passed"] for item in audit["checks"])
    repaired = ContestDirectPlanRevisionArtifact.model_validate_json(
        (output / "system-authored-targeted-research-plan.json").read_text("utf-8")
    ).plan
    original = sources.v3.plan.plan
    assert all(getattr(repaired, field) == getattr(original, field) for field in _FROZEN_FIELDS)
    assert all(getattr(repaired, field) == replacements[field] for field in _REPAIR_FIELDS)


def test_failed_program_audit_stops_before_render_and_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _sources(tmp_path)
    output = tmp_path / "v4-blocked"
    invalid = _valid_replacements()
    invalid.update(
        {
            "technical_details": "方法仅说明将比较若干零模型。",
            "methods": "方法仅说明将比较若干零模型。",
            "experiments": "正式实验另行定义分析单位，但未给出零模型实现。",
            "baselines": "使用若干未细化的对照模型。",
        }
    )
    calls: list[str] = []

    def repair_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        calls.append("repair")
        return _completion(invalid)

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("render/review must not run after deterministic audit failure")

    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_targeted_scientific_repair_cli._guard_observed_numbers",
        lambda *_args, **_kwargs: None,
    )
    report = run_contest_direction_targeted_scientific_repair(
        source_delivery_dir=tmp_path / "v1",
        v2_attempt_dir=tmp_path / "v2",
        v3_attempt_dir=tmp_path / "v3",
        output_dir=output,
        sources_loader=lambda _v1, _v2, _v3: sources,
        repair_completion=repair_completion,
        plan_materializer=forbidden,
        review_runner=forbidden,
    )

    assert calls == ["repair"]
    assert report["status"] == "blocked_after_targeted_scientific_audit"
    assert report["model_call_accounting"]["total_new_provider_requests"] == 1
    assert report["model_call_accounting"]["fresh_independent_review_calls"] == 0
    assert not (output / "plan").exists()
    assert not (output / "independent-scientific-review").exists()
    audit = json.loads((output / "targeted-scientific-repair-audit.json").read_text("utf-8"))
    assert audit["all_required_corrections_passed"] is False
    assert any(not item["passed"] for item in audit["checks"])


def test_v5_schema_and_merge_freeze_every_field_except_rt06_prose() -> None:
    original = _base_plan()
    replacements = {
        "paper_abstract": "修订摘要明确模拟z诊断不是总体效应估计。",
        "results": "真实预实验结果保留，并说明替代解释；模拟z诊断非总体效应量。",
        "limitations": "预实验局限明确，模拟z诊断不是population effect size。",
    }
    frozen = tuple(field for field in _ALL_PLAN_FIELDS if field not in _RT06_REPAIR_FIELDS)

    schema = _repair_response_schema(repair_fields=_RT06_REPAIR_FIELDS)
    merged = _merge_frozen_plan(original, replacements, frozen_fields=frozen)

    assert schema["required"] == list(_RT06_REPAIR_FIELDS)
    assert set(schema["properties"]) == set(_RT06_REPAIR_FIELDS)
    assert all(getattr(merged, field) == getattr(original, field) for field in frozen)
    assert all(getattr(merged, field) == value for field, value in replacements.items())
