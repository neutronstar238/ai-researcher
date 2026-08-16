"""Tests for evidence-bound shadow Skill evolution from a direction delivery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.contest_direction_literature import (
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_direction_skill_evolution import (
    ContestDirectionSkillEvolutionError,
    activate_validated_evolved_skill,
    rollback_activated_evolved_skill,
    run_evidence_to_skill_evolution,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentParameters,
    PrimeIntervalSpec,
    run_contest_prime_preexperiment,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult

_NOW = datetime(2026, 8, 13, 2, 0, tzinfo=timezone.utc)


def _completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="qwen-test",
        base_url="https://provider.example/v1",
        model_name="qwen-test",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=json.dumps(payload, ensure_ascii=False),
        parsed_json=payload,
        usage={"prompt_tokens": 10, "completion_tokens": 10},
        reasoning_text="独立完成方法抽象与证据边界检查。" * 20,
        temperature=0.0,
    )


@pytest.fixture(scope="module")
def completed_direction(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("evidence-skill-direction")
    delivery = base / "delivery"
    skills = base / "skills"
    parent_dir = skills / "prime-method"
    parent_dir.mkdir(parents=True)
    parent_content = (
        "---\n"
        "name: prime-method\n"
        "description: Use finite-scale controls to evaluate prime-sequence hypotheses.\n"
        "---\n\n"
        "# Prime method\n\nCompare observations with discriminating null models.\n"
    )
    (parent_dir / "SKILL.md").write_text(parent_content, encoding="utf-8")
    parent_hash = _sha256(parent_dir / "SKILL.md")
    generic_dir = skills / "research-novelty"
    generic_dir.mkdir(parents=True)
    (generic_dir / "SKILL.md").write_text(
        "---\nname: research-novelty\n"
        "description: Compare a research idea with prior work.\n---\n\n"
        "# Novelty\n\nCompare abstracts and report overlap.\n",
        encoding="utf-8",
    )
    generic_hash = _sha256(generic_dir / "SKILL.md")

    literature_path = delivery / "literature" / "direction-literature.json"
    paper_topics = (
        "Residue path constraints in prime gaps",
        "Permutation entropy of arithmetic sequences",
        "Wheel conditioned null models for primes",
        "Local order statistics of consecutive primes",
        "Information theoretic tests of gap dependence",
        "Prime number races and modular bias",
        "Finite interval resampling for number theory",
        "Ordinal patterns under arithmetic controls",
    )
    papers = [
        AcademicPaper(
            title=paper_topics[index - 1],
            authors=[f"Author {index}"],
            abstract=(
                "We study prime gaps, residue constraints, permutation entropy, "
                "null models and finite-scale mechanism discrimination. "
                f"Independent methodological case {index}."
            ),
            publication_date=date(2010 + index, 1, 1),
            venue="Journal of Number Theory",
            doi=f"10.1000/prime.{index}",
            url=f"https://doi.org/10.1000/prime.{index}",
            citation_count=50 * index,
            citation_count_source="openalex",
            citation_count_as_of=_NOW.date(),
            publication_status="published",
            source="openalex",
        )
        for index in range(1, 9)
    ]
    literature = retrieve_contest_direction_literature(
        direction="有限尺度素数间隙残基约束与排列熵机制检验",
        searchers={"openalex": lambda query, *, limit: papers[:limit]},  # noqa: ARG005
        output_path=literature_path,
        retrieved_at=_NOW,
        max_results_per_search=8,
        llm_call=lambda **_: _completion(
            {
                "queries": [
                    '("prime gaps" OR "prime gap") AND ("residue constraints" OR "modular bias")',
                    '("permutation entropy" OR "ordinal patterns") AND '
                    '("statistical estimation" OR "bias correction")',
                    '("prime gaps" OR "prime gap") AND ("mechanism" OR "null model")',
                    '("prime gaps" OR "prime gap") AND ("limitations" OR "failure modes")',
                ]
            }
        ),
    )

    source_plan = delivery / "preexperiment" / "pilot-brief.json"
    source_plan.parent.mkdir(parents=True, exist_ok=True)
    source_plan.write_text(
        json.dumps({"direction": literature.direction}, ensure_ascii=False),
        encoding="utf-8",
    )
    pilot_dir = delivery / "preexperiment" / "prime-gap-information-theory-v1"
    pilot = run_contest_prime_preexperiment(
        output_dir=pilot_dir,
        source_plan_path=source_plan,
        parameters=ContestPrimePreexperimentParameters(
            intervals=tuple(
                PrimeIntervalSpec(start=start, stop=start + 50_000)
                for start in (100_000, 200_000, 300_000, 400_000, 500_000)
            ),
            null_draws=199,
            fixed_interval_resampling_draws=1_000,
            wheel_density_segment_width=10_000,
        ),
    )
    selected: dict[str, Any] = {
        "schema_version": "contest-direction-evidence-routed-skills-v1",
        "routing_artifact_path": "skill-routing.json",
        "routing_artifact_hash": "1" * 64,
        "literature_artifact_hash": literature.artifact_hash,
        "literature_visible_before_skill_metadata": True,
        "skill_bodies_visible_to_selector": False,
        "skills": [
            {
                "skill_id": "research-novelty",
                "path": (generic_dir / "SKILL.md").as_posix(),
                "content_sha256": generic_hash,
            },
            {
                "skill_id": "prime-method",
                "path": (parent_dir / "SKILL.md").as_posix(),
                "content_sha256": parent_hash,
            }
        ],
    }
    selected["manifest_hash"] = canonical_model_hash(selected)
    selected_path = delivery / "selected-method-skills.json"
    selected_path.write_text(
        json.dumps(selected, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report = {
        "status": "completed",
        "preexperiment_executed": True,
        "artifacts": {
            "literature": {
                "artifact_hash": literature.artifact_hash,
                "sha256": _sha256(literature_path),
            },
            "prime_preexperiment": {
                "artifact_hash": pilot.artifact_hash,
                "sha256": _sha256(pilot_dir / "prime-preexperiment.json"),
            },
            "selected_method_skills": {"sha256": _sha256(selected_path)},
        },
    }
    (delivery / "delivery-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return delivery, skills


def test_evolution_is_evidence_bound_heldout_validated_and_replayable(
    completed_direction: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    delivery, skills = completed_direction
    calls: list[str] = []

    def complete(**kwargs: Any) -> LLMJsonCompletionResult:
        stage = kwargs["response_schema_name"]
        calls.append(stage)
        if stage == "evidence_to_skill_candidate":
            development = json.loads(kwargs["messages"][2]["content"])
            evidence_ids = [
                development["papers"][0]["case_id"],
                development["pilot_intervals"][0]["case_id"],
            ]
            return _completion(
                {
                    "title_cn": "有限尺度机制判别工作流",
                    "description_cn": (
                        "用于需要从高相关论文与探索性预实验中提出可证伪机制、"
                        "选择判别性对照并依据负面结果转向的研究任务。"
                    ),
                    "trigger_conditions_cn": ["研究问题需要有限尺度可证伪检验"],
                    "workflow_steps_cn": [
                        "先按问题相关性检索并核验论文元数据",
                        "把机制假设编译为观测量与判别性零模型",
                        "运行有界预实验并保留原始数据、日志和指标",
                        "强对照不支持时收缩结论或更换机制",
                    ],
                    "evidence_bound_lessons": [
                        {
                            "lesson_cn": "相关性先于被引次数，预实验解释服从强约束对照",
                            "development_evidence_ids": evidence_ids,
                        }
                    ],
                    "stop_or_pivot_rules_cn": ["强约束对照不支持时停止强化原假设"],
                    "validation_checks_cn": ["逐项回溯指标到原始文件哈希"],
                    "limitations_cn": ["有限区间观察不得外推总体规律"],
                }
            )
        heldout = json.loads(kwargs["messages"][2]["content"])
        return _completion(
            {
                "case_assessments": [
                    {
                        "case_id": case_id,
                        "methodology_transfers": True,
                        "evidence_boundary_preserved": True,
                        "no_unsupported_scientific_claim": True,
                        "assessment_cn": "该候选只迁移判别流程并保留来源与探索性边界。",
                    }
                    for case_id in heldout["case_ids"]
                ],
                "overall_transfer_supported": True,
                "limitations_cn": ["尚未证明跨学科泛化"],
            }
        )

    output = tmp_path / "evolution"
    result = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=complete,
    )

    assert result.resumed_existing is False
    assert result.artifact.promotion_eligible is True
    assert result.artifact.parent_skill_id == "prime-method"
    assert result.artifact.candidate_status == "heldout_passed_shadow"
    assert result.artifact.active_skill_written is False
    assert result.artifact.production_enabled is False
    assert result.artifact.model_calls_at_creation == 2
    assert calls == ["evidence_to_skill_candidate", "evidence_to_skill_heldout_validation"]
    assert not (skills / result.artifact.candidate_skill_id).exists()
    assert all(item.partition == "development" for item in result.artifact.paper_evidence if item.evidence_id in {
        evidence_id
        for lesson in result.artifact.candidate_draft.evidence_bound_lessons
        for evidence_id in lesson.development_evidence_ids
        if evidence_id.startswith("paper:")
    })
    assert any(item.partition == "held_out" for item in result.artifact.paper_evidence)
    assert any(item.partition == "held_out" for item in result.artifact.pilot_evidence)
    assert "期刊影响因子" in result.report_path.read_text(encoding="utf-8")

    quick_validate = Path(
        "C:/Users/Z/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
    )
    if quick_validate.is_file():
        # Machine-local developer tool; the Linux CI runner does not have it,
        # so this external lint is exercised only where it exists.
        validation = subprocess.run(
            [sys.executable, str(quick_validate), str(result.candidate_skill_dir)],
            check=False,
            capture_output=True,
            env={**os.environ, "PYTHONUTF8": "1"},
            text=True,
        )
        assert validation.returncode == 0, validation.stdout + validation.stderr
        assert "Skill is valid" in validation.stdout

    replay = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=lambda **_: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    assert replay.resumed_existing is True
    assert replay.artifact == result.artifact


def test_development_paper_record_id_alias_is_canonicalized_and_replayed(
    completed_direction: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    delivery, skills = completed_direction
    calls: list[str] = []
    raw_record_id = ""
    canonical_case_id = ""

    def complete(**kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal raw_record_id, canonical_case_id
        stage = kwargs["response_schema_name"]
        calls.append(stage)
        payload = json.loads(kwargs["messages"][2]["content"])
        if stage == "evidence_to_skill_candidate":
            raw_record_id = payload["papers"][0]["record_id"]
            canonical_case_id = payload["papers"][0]["case_id"]
            return _completion(
                {
                    "title_cn": "开发文献别名规范化方法",
                    "description_cn": "用于把来源记录别名机械绑定到程序拥有的证据编号。",
                    "trigger_conditions_cn": ["候选引用了开发文献记录编号"],
                    "workflow_steps_cn": ["核对开发分区", "绑定规范证据编号"],
                    "evidence_bound_lessons": [
                        {
                            "lesson_cn": "只复用开发分区内有来源绑定的方法经验",
                            "development_evidence_ids": [
                                raw_record_id,
                                payload["pilot_intervals"][0]["case_id"],
                            ],
                        }
                    ],
                    "stop_or_pivot_rules_cn": ["编号不属于开发分区时停止"],
                    "validation_checks_cn": ["核验规范编号与记录编号一一对应"],
                    "limitations_cn": ["规范化不建立新的科学证据"],
                }
            )
        return _completion(
            {
                "case_assessments": [
                    {
                        "case_id": case_id,
                        "methodology_transfers": True,
                        "evidence_boundary_preserved": True,
                        "no_unsupported_scientific_claim": True,
                        "assessment_cn": "方法可迁移且保持探索性边界。",
                    }
                    for case_id in payload["case_ids"]
                ],
                "overall_transfer_supported": True,
                "limitations_cn": [],
            }
        )

    output = tmp_path / "record-id-alias"
    result = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=complete,
    )

    lesson_ids = result.artifact.candidate_draft.evidence_bound_lessons[
        0
    ].development_evidence_ids
    assert raw_record_id
    assert canonical_case_id == f"paper:{raw_record_id}"
    assert canonical_case_id in lesson_ids
    assert raw_record_id not in lesson_ids
    stored = json.loads(
        (output / "process" / "generation-completion.json").read_text("utf-8")
    )
    assert raw_record_id in stored["parsed_json"]["evidence_bound_lessons"][0][
        "development_evidence_ids"
    ]
    assert calls == ["evidence_to_skill_candidate", "evidence_to_skill_heldout_validation"]
    replay = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=lambda **_: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    assert replay.resumed_existing is True
    assert replay.artifact == result.artifact


@pytest.mark.parametrize("invalid_kind", ["unknown", "heldout"])
def test_unknown_or_heldout_paper_record_alias_is_rejected(
    completed_direction: tuple[Path, Path],
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    delivery, skills = completed_direction
    calls: list[str] = []

    def complete(**kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(kwargs["response_schema_name"])
        development = json.loads(kwargs["messages"][2]["content"])
        if invalid_kind == "unknown":
            invalid_id = "direction-paper-ffffffffffffffff"
        else:
            literature = json.loads(
                (delivery / "literature" / "direction-literature.json").read_text("utf-8")
            )
            development_record_ids = {item["record_id"] for item in development["papers"]}
            invalid_id = next(
                item["record_id"]
                for item in literature["retrieved_records"]
                if item["record_id"] not in development_record_ids
            )
        return _completion(
            {
                "title_cn": "应被拒绝的候选",
                "description_cn": "该候选故意引用不属于开发分区的文献记录编号。",
                "trigger_conditions_cn": ["测试失败关闭"],
                "workflow_steps_cn": ["提交编号", "等待校验"],
                "evidence_bound_lessons": [
                    {
                        "lesson_cn": "不得接受未知或隐藏证据",
                        "development_evidence_ids": [
                            invalid_id,
                            development["pilot_intervals"][0]["case_id"],
                        ],
                    }
                ],
                "stop_or_pivot_rules_cn": ["证据越界即停止"],
                "validation_checks_cn": ["检查开发分区"],
                "limitations_cn": ["测试候选不可晋升"],
            }
        )

    with pytest.raises(
        ContestDirectionSkillEvolutionError,
        match="unknown or held-out evidence IDs",
    ):
        run_evidence_to_skill_evolution(
            delivery_dir=delivery,
            output_dir=tmp_path / f"invalid-{invalid_kind}",
            skills_root=skills,
            completion=complete,
        )
    assert calls == ["evidence_to_skill_candidate"]


def test_failed_heldout_remains_shadow_and_cannot_activate(
    completed_direction: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    delivery, skills = completed_direction

    def complete(**kwargs: Any) -> LLMJsonCompletionResult:
        if kwargs["response_schema_name"] == "evidence_to_skill_candidate":
            development = json.loads(kwargs["messages"][2]["content"])
            return _completion(
                {
                    "title_cn": "候选方法",
                    "description_cn": "用于有限尺度机制判别并保持证据边界的候选方法。",
                    "trigger_conditions_cn": ["有限尺度问题"],
                    "workflow_steps_cn": ["先核验来源", "再运行判别对照"],
                    "evidence_bound_lessons": [
                        {
                            "lesson_cn": "先检查来源",
                            "development_evidence_ids": [
                                development["papers"][0]["case_id"],
                                development["pilot_intervals"][0]["case_id"],
                            ],
                        }
                    ],
                    "stop_or_pivot_rules_cn": ["对照失败则转向"],
                    "validation_checks_cn": ["核验原始哈希"],
                    "limitations_cn": ["不得外推"],
                }
            )
        heldout = json.loads(kwargs["messages"][2]["content"])
        return _completion(
            {
                "case_assessments": [
                    {
                        "case_id": case_id,
                        "methodology_transfers": False,
                        "evidence_boundary_preserved": True,
                        "no_unsupported_scientific_claim": True,
                        "assessment_cn": "该方法未覆盖此隐藏案例的关键判别结构。",
                    }
                    for case_id in heldout["case_ids"]
                ],
                "overall_transfer_supported": False,
                "limitations_cn": ["迁移失败"],
            }
        )

    output = tmp_path / "failed-evolution"
    result = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=complete,
    )
    assert result.artifact.promotion_eligible is False
    assert result.artifact.candidate_status == "heldout_failed_shadow"
    with pytest.raises(ContestDirectionSkillEvolutionError, match="forbidden"):
        activate_validated_evolved_skill(
            evolution_artifact_path=result.artifact_path,
            skills_root=skills,
            activated_by="test",
            activation_note="must stay blocked",
        )


def test_explicit_activation_and_recoverable_rollback(
    completed_direction: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    delivery, skills = completed_direction

    def complete(**kwargs: Any) -> LLMJsonCompletionResult:
        if kwargs["response_schema_name"] == "evidence_to_skill_candidate":
            development = json.loads(kwargs["messages"][2]["content"])
            return _completion(
                {
                    "title_cn": "可回滚研究方法",
                    "description_cn": "用于将来源和探索性观察编译为可回滚研究工作流的方法。",
                    "trigger_conditions_cn": ["需要证据绑定方法"],
                    "workflow_steps_cn": ["绑定来源", "检验隐藏案例"],
                    "evidence_bound_lessons": [
                        {
                            "lesson_cn": "先绑定证据再复用经验",
                            "development_evidence_ids": [
                                development["papers"][0]["case_id"],
                                development["pilot_intervals"][0]["case_id"],
                            ],
                        }
                    ],
                    "stop_or_pivot_rules_cn": ["隐藏案例失败则不晋升"],
                    "validation_checks_cn": ["核验候选文件"],
                    "limitations_cn": ["不等于科学证明"],
                }
            )
        heldout = json.loads(kwargs["messages"][2]["content"])
        return _completion(
            {
                "case_assessments": [
                    {
                        "case_id": case_id,
                        "methodology_transfers": True,
                        "evidence_boundary_preserved": True,
                        "no_unsupported_scientific_claim": True,
                        "assessment_cn": "方法可迁移且没有越过探索性证据边界。",
                    }
                    for case_id in heldout["case_ids"]
                ],
                "overall_transfer_supported": True,
                "limitations_cn": [],
            }
        )

    output = tmp_path / "activation"
    result = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=complete,
    )
    parent_before = (skills / "prime-method" / "SKILL.md").read_bytes()
    activation = activate_validated_evolved_skill(
        evolution_artifact_path=result.artifact_path,
        skills_root=skills,
        activated_by="test-operator",
        activation_note="explicit post-validation activation",
    )
    assert activation.production_enabled is True
    active_dir = skills / result.artifact.candidate_skill_id
    assert active_dir.is_dir()
    assert (skills / "prime-method" / "SKILL.md").read_bytes() == parent_before

    rollback = rollback_activated_evolved_skill(
        activation_receipt_path=output / "promotion" / "activation.json",
        skills_root=skills,
        reason="negative follow-up reward",
    )
    assert rollback.production_enabled is False
    assert not active_dir.exists()
    assert (output / "promotion" / rollback.archived_skill_relative_path).is_dir()
    assert (skills / "prime-method" / "SKILL.md").read_bytes() == parent_before


def test_completed_replay_detects_candidate_tampering(
    completed_direction: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    delivery, skills = completed_direction

    def complete(**kwargs: Any) -> LLMJsonCompletionResult:
        if kwargs["response_schema_name"] == "evidence_to_skill_candidate":
            development = json.loads(kwargs["messages"][2]["content"])
            return _completion(
                {
                    "title_cn": "防篡改候选",
                    "description_cn": "用于检验候选Skill制品与来源绑定完整性的方法。",
                    "trigger_conditions_cn": ["需要来源完整性"],
                    "workflow_steps_cn": ["绑定来源", "重验候选"],
                    "evidence_bound_lessons": [
                        {
                            "lesson_cn": "重验来源",
                            "development_evidence_ids": [
                                development["papers"][0]["case_id"],
                                development["pilot_intervals"][0]["case_id"],
                            ],
                        }
                    ],
                    "stop_or_pivot_rules_cn": ["篡改即停止"],
                    "validation_checks_cn": ["计算文件哈希"],
                    "limitations_cn": ["哈希不证明外部身份"],
                }
            )
        heldout = json.loads(kwargs["messages"][2]["content"])
        return _completion(
            {
                "case_assessments": [
                    {
                        "case_id": case_id,
                        "methodology_transfers": True,
                        "evidence_boundary_preserved": True,
                        "no_unsupported_scientific_claim": True,
                        "assessment_cn": "通过。",
                    }
                    for case_id in heldout["case_ids"]
                ],
                "overall_transfer_supported": True,
                "limitations_cn": [],
            }
        )

    output = tmp_path / "tamper"
    result = run_evidence_to_skill_evolution(
        delivery_dir=delivery,
        output_dir=output,
        skills_root=skills,
        completion=complete,
    )
    skill_path = result.candidate_skill_dir / "SKILL.md"
    skill_path.write_text(skill_path.read_text("utf-8") + "tampered\n", encoding="utf-8")
    with pytest.raises(ContestDirectionSkillEvolutionError, match="changed"):
        run_evidence_to_skill_evolution(
            delivery_dir=delivery,
            output_dir=output,
            skills_root=skills,
            completion=lambda **_: (_ for _ in ()).throw(AssertionError("provider called")),
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
