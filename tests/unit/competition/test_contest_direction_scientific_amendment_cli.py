from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from autoresearch.competition.contest_direct_plan_render import ContestDirectPlanArtifacts
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectRevisedScientificPlan,
)
from autoresearch.competition.contest_direction_scientific_amendment_cli import (
    ContestDirectionScientificAmendmentError,
    _audit_amended_plan,
    _parser,
    _PriorAmendmentAttempt,
    _SourceBundle,
    run_contest_direction_scientific_amendment,
)
from autoresearch.competition.manifest import canonical_model_hash

_HASH = "a" * 64
_REFERENCES = (
    "Bandt, C. & Pompe, B. Permutation entropy: a natural complexity measure.",
    "Bian, C. et al. Modified permutation-entropy analysis for ties.",
    "Lemke Oliver, R. & Soundararajan, K. Unexpected biases in consecutive primes.",
    "Banks, W., Ford, K. & Tao, T. Large prime gaps and admissible tuples.",
    "Phipson, B. & Smyth, G. K. Permutation p-values should never be zero.",
)


class _FakeAmendment:
    def __init__(
        self,
        plan: ContestDirectRevisedScientificPlan,
        context_hash: str,
        *,
        original_plan_id: str,
    ) -> None:
        self.plan = plan
        self.revision_id = "direct-plan-revision-" + "b" * 16
        self.artifact_hash = "b" * 64
        self.original_plan_id = original_plan_id
        self.verified_revision_context_sha256 = context_hash
        self.generation_calls = 1

    def flat_payload(self) -> dict[str, Any]:
        return {
            "title": self.plan.paper_title,
            "abstract": self.plan.paper_abstract,
            "problem_statement": self.plan.problem_statement,
            "rationale": self.plan.rationale,
            "technical_details": self.plan.technical_details,
            "datasets": {
                "description": self.plan.datasets,
                "source": self.plan.source,
                "target": self.plan.target,
            },
            "methods": self.plan.methods,
            "experiments": {
                "steps": self.plan.experiments,
                "baselines": self.plan.baselines,
                "metrics": self.plan.metrics,
            },
            "results": self.plan.results,
            "references": list(self.plan.references),
        }


def _valid_plan() -> ContestDirectRevisedScientificPlan:
    method = (
        "残基路径置换严格使用条件键(segment,left mod30,right mod30)，不是mod210。"
        "wheel-210敏感性零模型在每个100000宽数轴段保持观察点数并固定首末端点，"
        "从与210互素的允许候选点中无放回抽取。"
        "弱序weak-order rank pattern由严格大于关系编码，模式空间为ordered Bell "
        "number Fubini(5)=541，不把并列值随机拆开。"
        "正式实验将另行定义分析单位且不同于预实验；四类零模型各运行999次draws，"
        "使用+1 Monte Carlo p并在四模型family内作Holm校正，目标adjusted p<0.01。"
    )
    result = (
        "真实预实验使用五个数轴宽10^6的固定整数区间，每区间得到56359至70434个"
        "素数间隙。每类零模型执行199 draws，aggregate raw p=0.005，四模型Holm"
        "校正p=0.02，因此只在alpha=0.05（α=0.05）下作探索性描述。"
        "standardized_effect的z仅是有限simulation null SD下的模拟诊断，"
        "非总体效应量。"
    )
    return ContestDirectRevisedScientificPlan(
        problem_statement="研究连续整数素数的有序间隙是否含有超出已知结构的序列信息。",
        rationale=(
            "检验一个可证伪的残差信号；锁定文献用于定义与方法，"
            "这些来源不直接证明本计划的新残差信号。"
        ),
        technical_details=method,
        datasets="使用真实生成并逐项验证的连续素数间隙。",
        source="程序生成的连续整数素数及带哈希的真实预实验原始文件。",
        target="有序间隙弱序模式熵及相对四类零模型的残差。",
        paper_title="连续素数间隙弱序信息的可证伪研究计划",
        paper_abstract=result,
        methods=method,
        experiments=method,
        baselines="四类零模型分别评估排序、局部残基路径、wheel-210和其他结构。",
        metrics="弱序模式熵、+1 Monte Carlo p、Holm校正与模拟z诊断。",
        results=result,
        references=_REFERENCES,
        main_hypothesis="控制已知结构后，有序素数间隙的弱序熵仍显示可复现残差。",
        limitations=("预实验只是探索性计算；五个区间不能外推到总体，z模拟诊断不是总体效应量。"),
    )


def _write(path: Path, payload: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return path


def _source_bundle(tmp_path: Path) -> _SourceBundle:
    source = tmp_path / "source-v1"
    report_path = _write(source / "delivery-report.json")
    plan_path = _write(source / "system-authored-final-research-plan.json")
    pilot_path = _write(source / "preexperiment" / "system-plan-preexperiment.json")
    plan = SimpleNamespace(
        revision_id="direct-plan-revision-" + "a" * 16,
        artifact_hash="a" * 64,
    )
    parameters = SimpleNamespace(
        null_draws=199,
        alpha=0.05,
        wheel_modulus=210,
        wheel_density_segment_width=100_000,
        residue_path_segment_size=4096,
        ordinal_dimension=5,
    )
    aggregate = [
        SimpleNamespace(
            one_sided_empirical_p_lower=0.005,
            holm_adjusted_p_across_null_models=0.02,
        )
        for _ in range(4)
    ]
    counts = (56_359, 60_001, 63_200, 68_100, 70_434)
    intervals = [
        SimpleNamespace(start=index * 10**6, stop=(index + 1) * 10**6, gap_count=count)
        for index, count in enumerate(counts)
    ]
    pilot = SimpleNamespace(
        status="completed",
        run_id="prime-pilot-" + "c" * 16,
        artifact_hash="c" * 64,
        metrics_sha256="d" * 64,
        manifest_sha256="e" * 64,
        study_phase="exploratory_preexperiment",
        parameters=parameters,
        aggregate_results=aggregate,
        interval_results=intervals,
    )
    return _SourceBundle(
        root=source,
        report_path=report_path,
        report={"file_inventory_hash": "f" * 64},
        direction="素数之间有何关系？",
        plan_path=plan_path,
        plan=plan,  # type: ignore[arg-type]
        pilot_root=pilot_path.parent,
        pilot_path=pilot_path,
        pilot=pilot,  # type: ignore[arg-type]
        references=_REFERENCES,
        skill_contexts=({"skill_id": "number-theory", "content": "方法技能"},),
        source_code_sha256="1" * 64,
    )


@pytest.mark.parametrize("use_prior", [False, True])
def test_amendment_mock_e2e_uses_exactly_one_revision_and_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_prior: bool,
) -> None:
    bundle = _source_bundle(tmp_path)
    output = tmp_path / ("v3" if use_prior else "v2")
    calls: list[str] = []
    prior: _PriorAmendmentAttempt | None = None
    if use_prior:
        prior_root = tmp_path / "prior-v2"
        prior_plan = SimpleNamespace(
            revision_id="direct-plan-revision-" + "9" * 16,
            artifact_hash="9" * 64,
        )
        prior = _PriorAmendmentAttempt(
            root=prior_root,
            input_path=_write(prior_root / "amendment-input.json"),
            plan_path=_write(prior_root / "system-authored-amended-research-plan.json"),
            plan=prior_plan,  # type: ignore[arg-type]
            audit_path=_write(prior_root / "scientific-amendment-audit.json"),
            audit={
                "artifact_hash": "8" * 64,
                "checks": [
                    {"finding_id": "RT-05", "passed": False},
                    {"finding_id": "RT-06", "passed": False},
                ],
            },
            findings_path=_write(prior_root / "scientific-red-team-findings.json"),
            findings={"artifact_hash": "7" * 64},
            review_response_path=_write(
                prior_root / "independent-scientific-review" / "responses" / "review.txt"
            ),
            review_interaction_path=_write(
                prior_root / "independent-scientific-review" / "interactions" / "review.json"
            ),
        )

    def revision_runner(**kwargs: Any) -> _FakeAmendment:
        calls.append("revision")
        expected_original = prior.plan if prior is not None else bundle.plan
        assert kwargs["original_plan"] is expected_original
        assert kwargs["preexperiment_artifact"] == bundle.pilot_path
        context_hash = canonical_model_hash(kwargs["verified_revision_context"])
        artifact = _FakeAmendment(
            _valid_plan(),
            context_hash,
            original_plan_id=expected_original.revision_id,
        )
        Path(kwargs["output_path"]).write_text(
            json.dumps({"artifact_hash": artifact.artifact_hash}), encoding="utf-8"
        )
        return artifact

    def materializer(**kwargs: Any) -> ContestDirectPlanArtifacts:
        calls.append("materialize")
        assert len(kwargs["payload"]["embedded_evidence"]["tables"]) == 2
        assert kwargs["evidence_bindings"]
        root = Path(kwargs["output_dir"])
        files = {
            name: _write(root / name, "%PDF-test" if name.endswith(".pdf") else "test")
            for name in (
                "research-plan.json",
                "research-plan.md",
                "research-plan.tex",
                "research-plan.pdf",
                "research-plan-manifest.json",
            )
        }
        return ContestDirectPlanArtifacts(
            output_dir=root,
            json_path=files["research-plan.json"],
            markdown_path=files["research-plan.md"],
            tex_path=files["research-plan.tex"],
            pdf_path=files["research-plan.pdf"],
            manifest_path=files["research-plan-manifest.json"],
            source_payload_sha256=hashlib.sha256(b"test").hexdigest(),
            page_count=1,
            pdf_text_verified=True,
        )

    def review_runner(**kwargs: Any) -> Any:
        calls.append("review")
        findings = kwargs["required_audit_findings"]
        assert [item["finding_id"] for item in findings] == (
            ["RT-02", "RT-05", "RT-06"]
            if prior is not None
            else [f"RT-{index:02d}" for index in range(1, 8)]
        )
        _write(
            Path(kwargs["output_dir"]) / "system-plan-scientific-review.json",
            "{}",
        )
        return SimpleNamespace(
            generation_calls=1,
            plan_rewrite_performed=False,
            prior_audit_context_supplied=True,
            review=SimpleNamespace(recommendation="pass"),
            artifact_hash="2" * 64,
        )

    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_scientific_amendment_cli._verify_rendered_pdf",
        lambda _rendered: (1, "mock"),
    )
    report = run_contest_direction_scientific_amendment(
        source_delivery_dir=bundle.root,
        output_dir=output,
        source_loader=lambda _path: bundle,
        prior_amendment_dir=prior.root if prior is not None else None,
        prior_loader=(lambda _path, _bundle: prior) if prior is not None else None,
        revision_runner=revision_runner,
        plan_materializer=materializer,
        review_runner=review_runner,
    )

    assert calls == ["revision", "materialize", "review"]
    assert report["status"] == "completed"
    assert report["model_call_accounting"] == {
        "scientific_amendment_calls": 1,
        "fresh_independent_review_calls": 1,
        "total_new_provider_requests": 2,
        "content_retry_calls": 0,
    }
    assert report["source_v1"]["preexperiment_rerun"] is False
    assert report["amendment_version"] == ("v3" if use_prior else "v2")
    if use_prior:
        assert report["prior_failed_amendment_attempt"]["provider_calls_replayed"] == 0
    audit = json.loads((output / "scientific-amendment-audit.json").read_text("utf-8"))
    assert audit["all_required_corrections_passed"] is True
    assert [item["finding_id"] for item in audit["checks"]] == [
        f"RT-{index:02d}" for index in range(1, 8)
    ]


def test_deterministic_audit_rejects_unreachable_formal_protocol() -> None:
    plan = _valid_plan().model_copy(
        update={
            "methods": "正式实验对四类零模型只做100 draws，并在alpha=0.01检验。",
            "experiments": "正式实验每模型只做100次。",
        }
    )
    amendment = SimpleNamespace(plan=plan)

    checks = _audit_amended_plan(amendment)  # type: ignore[arg-type]

    assert next(item for item in checks if item.finding_id == "RT-03").passed is False


def test_unit_boundary_accepts_substantive_noninterchangeable_wording() -> None:
    plan = _valid_plan().model_copy(
        update={
            "methods": _valid_plan().methods.replace(
                "正式实验将另行定义分析单位且不同于预实验",
                "正式实验使用每块连续素数，pilot使用固定数轴区间，二者定义不同，不可混同",
            )
        }
    )

    checks = _audit_amended_plan(SimpleNamespace(plan=plan))  # type: ignore[arg-type]

    assert next(item for item in checks if item.finding_id == "RT-05").passed is True


def test_z_boundary_accepts_the_plan_metric_definition() -> None:
    plan = _valid_plan().model_copy(
        update={
            "paper_abstract": "预实验保留真实统计结果，但此处不重复指标定义。",
            "results": "预实验保留真实统计结果，并报告替代解释。",
            "limitations": "预实验仍只是有限尺度探索性计算。",
            "metrics": (
                "每个standardized_effect的z仅为相对于有限simulation null SD的"
                "模拟诊断，非总体效应量，不是population effect size。"
            ),
        }
    )

    checks = _audit_amended_plan(SimpleNamespace(plan=plan))  # type: ignore[arg-type]

    assert next(item for item in checks if item.finding_id == "RT-06").passed is True


def test_cli_defaults_are_versioned_and_non_overwriting() -> None:
    args = _parser().parse_args([])

    assert args.source_delivery.name.endswith("live-v1")
    assert args.output_dir.name.endswith("live-v2")
    assert args.plan_max_tokens == 12_000
    assert args.review_max_tokens == 8_000


def test_nonempty_output_is_rejected_before_source_loading(tmp_path: Path) -> None:
    output = tmp_path / "v2"
    _write(output / "existing.txt", "do not overwrite")

    with pytest.raises(ContestDirectionScientificAmendmentError, match="must be empty"):
        run_contest_direction_scientific_amendment(
            source_delivery_dir=tmp_path / "source-v1",
            output_dir=output,
            source_loader=lambda _path: (_ for _ in ()).throw(AssertionError("not called")),
        )
