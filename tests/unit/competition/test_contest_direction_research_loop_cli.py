from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import autoresearch.competition.contest_direction_research_loop_cli as loop_cli
from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    ContestDirectScientificPlan,
)
from autoresearch.competition.contest_direct_plan_render import ContestDirectPlanArtifacts
from autoresearch.competition.contest_direction_context_runtime import (
    ContestDirectionContextRuntime,
)
from autoresearch.competition.contest_direction_focus_literature import (
    run_contest_direction_focus_selection,
)
from autoresearch.competition.contest_direction_literature import (
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_direction_research_loop_cli import (
    ContestDirectionResearchLoopError,
    run_contest_direction_research_loop,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    replayable_stage_completion,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.model_authorship import record_model_authorship_receipt
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.llm.model_capabilities import OfficialModelCapability
from autoresearch.llm.task_context import AutonomousTaskContextSession

_DIRECTION = "有限尺度素数间隙序列中模算术约束与高阶顺序结构的信息论检验"
_V4_BROAD_QUERY_PLAN = (
    '("consecutive prime gaps" OR "prime spacing") AND '
    '("ordinal entropy" OR "residue transitions")',
    '("permutation entropy" OR "ordinal analysis") AND ("finite sample" OR validation)',
    '("consecutive prime gaps" OR "prime spacing") AND ("arithmetic null model" OR "residue bias")',
    '("consecutive prime gaps" OR "prime spacing") AND '
    '("null result" OR "alternative explanation")',
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skills(tmp_path: Path) -> tuple[Path, str, str]:
    path = tmp_path / "skills" / "prime-structure-computational-number-theory" / "SKILL.md"
    path.parent.mkdir(parents=True)
    content = (
        "---\n"
        "name: prime-structure-computational-number-theory\n"
        "description: 素数间隙的可证伪计算数论与信息论对照方法。\n"
        "---\n"
        "使用分段筛、排列熵和条件置换零模型。\n"
    )
    path.write_text(content, encoding="utf-8")
    return path.parent.parent, content, hashlib.sha256(content.encode()).hexdigest()


class _Literature:
    direction = _DIRECTION
    artifact_hash = "1" * 64
    literature_catalog_hash = "0" * 64
    merged_catalog_hash = "2" * 64
    broad_literature_artifact_hash = "1" * 64
    focus_artifact_hash = "2" * 64
    selected_focus_id = "direction-focus-0123456789abcdef"
    targeted_retrieval_binding_hash = "3" * 64
    targeted_literature_artifact_hash = "4" * 64
    retrieval_semantics = "two_distinct_searches_not_one_retrieval"
    merged_record_count = 5
    cross_stage_deduplicated_count = 0
    method_skills: tuple[Any, ...] = ()
    query_model_calls = 1
    queries = ("prime gaps permutation entropy residue null model",)
    retrieved_records = tuple(
        SimpleNamespace(record_id=f"direction-paper-{index:016d}") for index in range(1, 6)
    )

    def objective_retrieval_catalog(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "record_id": f"direction-paper-{index:016d}",
                "title": f"Ordinal structure in prime gaps study {index}",
                "authors": [f"Author {index}"],
                "abstract": (
                    "Permutation entropy and residue-conditioned null models for prime gap "
                    f"sequences, computational study {index}."
                ),
                "doi": f"10.1000/prime.gap.{index}",
                "url": f"https://doi.org/10.1000/prime.gap.{index}",
                "source_url": f"https://doi.org/10.1000/prime.gap.{index}",
                "retrieved_from": "arxiv" if index % 2 else "openalex",
                "retrieved_at": "2026-08-12T00:00:00+00:00",
            }
            for index in range(1, 6)
        )

    def objective_literature_catalog(self) -> tuple[str, ...]:
        return tuple(
            f"[{index}] Ordinal structure in prime gaps study {index}. "
            f"https://doi.org/10.1000/prime.gap.{index}\n"
            "完整摘要：Permutation entropy and residue-conditioned null models for prime "
            f"gap sequences, computational study {index}."
            for index in range(1, 6)
        )


def _plan(*, references: tuple[str, ...], pilot: bool) -> ContestDirectPlanArtifact:
    scientific = ContestDirectScientificPlan(
        problem_statement="检验有限尺度连续素数的有序间隙是否包含可区分的顺序结构。",
        rationale="以残基路径条件置换和局部分块置换区分模约束与额外顺序信号。",
        technical_details="用分段筛生成连续整数素数并计算含并列处理的五阶排列熵。",
        datasets="五个冻结有限整数区间上的连续素数间隙序列。",
        source="确定性分段筛生成的原始连续整数素数。",
        target="有序相邻素数间隙和条件零模型下的排列熵。",
        paper_title="有限尺度素数间隙的条件排列熵研究计划",
        paper_abstract="本计划以真实探索性预实验约束后续研究。",
        methods="冻结区间、随机种子、指标与多个条件零模型。",
        experiments="先完成探索性预实验，再扩大独立区间进行正式验证。",
        baselines="残基路径条件置换、局部分块置换、全局置换与wheel-210。",
        metrics="含并列处理的五阶排列熵及经验概率。",
        results=(
            "预实验已执行；真实数字由证据修订阶段读取。"
            if pilot
            else "尚未执行预实验；不报告观察数值。"
        ),
        references=references,
    )
    input_hash = ("3" if pilot else "2") * 64
    payload: dict[str, Any] = {
        "schema_version": "contest-direct-research-plan-v1",
        "document_type": "科学假设与研究计划",
        "plan_id": f"direct-plan-{input_hash[:16]}",
        "status": "research_plan_generated",
        "scientific_problem": _DIRECTION,
        "literature_context_provided": True,
        "preexperiment_context_status": "provided_as_input_context" if pilot else "not_provided",
        "plan": scientific.model_dump(mode="json"),
        "provider": "test",
        "model_name": "test-model",
        "generation_calls": 1,
        "json_repair_applied": False,
        "input_hash": input_hash,
        "model_response_hash": "4" * 64,
    }
    payload["artifact_hash"] = canonical_model_hash(payload)
    return ContestDirectPlanArtifact.model_validate(payload)


@pytest.mark.parametrize(
    ("revision_physical_attempts", "expected_physical_total"),
    [(1, 12), (2, 13)],
)
def test_full_mock_loop_uses_scientific_order_and_real_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revision_physical_attempts: int,
    expected_physical_total: int,
) -> None:
    calls: list[str] = []
    skills_root, skill_content, skill_hash = _skills(tmp_path)
    literature = _Literature()
    status_calls: list[str] = []
    recalled_contexts: list[dict[str, Any]] = []
    review_artifacts: list[Any] = []

    def verify_status(paper: Any) -> Any:
        status_calls.append(str(paper.url))
        return paper

    evidence_context = SimpleNamespace(
        subset_hash="e" * 64,
        model_dump=lambda **_kwargs: {"subset_hash": "e" * 64},
    )
    monkeypatch.setattr(
        loop_cli,
        "_skill_routing_two_stage_literature_evidence",
        lambda _literature, _catalog, **_kwargs: evidence_context,
    )
    monkeypatch.setattr(loop_cli, "_verify_rendered_pdf", lambda _rendered: (6, "test"))
    context_completions: list[Any] = []

    class ContextStage:
        def __enter__(self) -> Any:
            def completion(**_kwargs: Any) -> Any:
                pytest.fail("mock leaf runner must not invoke its injected completion")

            context_completions.append(completion)
            return completion

        def __exit__(self, *_args: Any) -> None:
            return None

    class ContextRuntime:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def stage(self, _stage: str, *, input_hash: str) -> ContextStage:
            assert len(input_hash) == 64
            return ContextStage()

        def checkpointed_stage(
            self, _stage: str, *, input_hash: str, checkpoint_root: Path
        ) -> ContextStage:
            assert len(input_hash) == 64
            assert checkpoint_root.name == "run"
            return ContextStage()

        def verify_official_capability(self, **_kwargs: Any) -> dict[str, Any]:
            return {"capability_hash": "0" * 64}

    monkeypatch.setattr(loop_cli, "ContestDirectionContextRuntime", ContextRuntime)

    state_holder: dict[str, Any] = {}

    def prepare_two_stage(**kwargs: Any) -> Any:
        calls.extend(["broad-retrieval", "focus-selection", "targeted-retrieval"])
        root = Path(kwargs["root"])
        paths = {
            "broad": root / "literature" / "broad" / "direction-literature.json",
            "focus": root / "literature" / "refinement" / "direction-focus.json",
            "targeted": root / "literature" / "refinement" / "targeted-literature.json",
            "binding": (root / "literature" / "refinement" / "direction-targeted-retrieval.json"),
            "merged": root / "literature" / "merged-literature.json",
            "coverage": root / "literature" / "planning-literature-coverage.json",
            "planning": root / "literature" / "planning-literature.json",
        }
        for name, path in paths.items():
            _write_json(path, {"artifact_hash": hashlib.sha256(name.encode()).hexdigest()})
        status_path = root / "literature" / "finalist-status-verification.json"
        status_payload = loop_cli._write_finalist_status_verification(status_path, records=())
        planning_payload = {
            "artifact_hash": "a" * 64,
        }
        _write_json(paths["planning"], planning_payload)
        coverage = SimpleNamespace(
            receipt_hash="b" * 64,
            passed=True,
            selected_role_counts=SimpleNamespace(
                model_dump=lambda **_kwargs: {
                    "direct_core": 2,
                    "method_foundation": 1,
                    "mechanism_or_null": 1,
                    "counterevidence": 1,
                    "method_transfer": 0,
                    "off_topic": 0,
                }
            ),
            thresholds=SimpleNamespace(
                model_dump=lambda **_kwargs: {
                    "direct_core": 2,
                    "method_foundation": 1,
                    "mechanism_or_null": 1,
                    "counterevidence": 1,
                    "method_transfer_must_not_be_majority": True,
                }
            ),
        )
        _write_json(paths["coverage"], {"receipt_hash": coverage.receipt_hash})
        broad = literature
        targeted = SimpleNamespace(
            artifact_hash=literature.targeted_literature_artifact_hash,
            literature_catalog_hash="4" * 64,
            query_model_calls=1,
            queries=("prime gaps permutation entropy",),
            method_skills=(),
            retrieved_records=literature.retrieved_records,
        )
        focus = SimpleNamespace(
            artifact_hash=literature.focus_artifact_hash,
            selected_focus_id=literature.selected_focus_id,
            focused_direction_cn=_DIRECTION,
            model_call_count_at_creation=2,
            selected_candidate=SimpleNamespace(
                nearest_work_queries=(),
                methods_baselines_queries=(),
                counterevidence_queries=(),
            ),
        )
        binding = SimpleNamespace(artifact_hash=literature.targeted_retrieval_binding_hash)
        state = loop_cli._TwoStageLiteratureState(
            broad=broad,
            broad_path=paths["broad"],
            focus=focus,
            focus_path=paths["focus"],
            targeted_binding=binding,
            targeted_binding_path=paths["binding"],
            targeted=targeted,
            targeted_path=paths["targeted"],
            merged=literature,
            merged_path=paths["merged"],
            planning_catalog=tuple(literature.objective_retrieval_catalog()),
            planning_context=tuple(literature.objective_literature_catalog()),
            excluded_records=[],
            finalist_status_path=status_path,
            finalist_status_payload=status_payload,
            planning_coverage_path=paths["coverage"],
            planning_coverage=coverage,
            planning_lock_path=paths["planning"],
            planning_lock_payload=planning_payload,
        )
        for stage, artifacts in (
            ("broad-literature-query", (paths["broad"],)),
            ("focus-selection", (paths["focus"],)),
            ("targeted-literature-query", (paths["targeted"], paths["binding"])),
            (
                "planning-literature-lock",
                (paths["merged"], status_path, paths["coverage"], paths["planning"]),
            ),
        ):
            kwargs["memory_stages"][stage] = loop_cli._capture_stage_memory(
                kwargs["memory_bridge"], stage=stage, artifact_paths=artifacts
            )
        state_holder["state"] = state
        return state

    monkeypatch.setattr(loop_cli, "_prepare_two_stage_literature", prepare_two_stage)

    def load_completed(_root: Path) -> Any:
        state = state_holder["state"]
        status = loop_cli._load_finalist_status_verification(state.finalist_status_path)
        assert status["artifact_hash"] == state.finalist_status_payload["artifact_hash"]
        return state

    monkeypatch.setattr(loop_cli, "_load_completed_two_stage_literature", load_completed)

    def retrieve(**kwargs: Any) -> _Literature:
        calls.append("legacy-retrieval-seam-unused")
        assert kwargs["selected_method_skills"] == {}
        assert kwargs["max_results_per_search"] == 20
        assert callable(kwargs["llm_call"])
        _write_json(Path(kwargs["output_path"]), {"artifact_hash": literature.artifact_hash})
        return literature

    def route(**kwargs: Any) -> Any:
        calls.append("literature-aware-skill-route")
        assert kwargs["literature_evidence_context"].subset_hash == "e" * 64
        assert callable(kwargs["llm_call"])
        output = Path(kwargs["output_path"])
        _write_json(output, {"artifact_hash": "5" * 64})
        return SimpleNamespace(
            schema_version="contest-direct-skill-routing-v3",
            literature_retrieval_artifact_hash=None,
            literature_evidence_context=evidence_context,
            merged_literature_artifact_hash=literature.artifact_hash,
            skill_bodies_visible_to_selector=False,
            selected_skill_ids=("prime-structure-computational-number-theory",),
            selected_skill_hashes={"prime-structure-computational-number-theory": skill_hash},
            artifact_hash="5" * 64,
            model_calls=1,
        )

    hypothesis_hash = "6" * 64
    candidate = {
        "candidate_id": "candidate-1",
        "hypothesis_cn": "强条件零模型后仍可能存在有限尺度顺序信号。",
        "research_objective_cn": "区分模约束与额外顺序结构。",
        "falsification_cn": "条件置换后差异消失即否决宽假设。",
        "nearest_work_difference_cn": "相邻工作描述残基偏差，本候选检验条件化后的顺序残差。",
        "transferred_method_baseline_cn": "迁移残基条件思想并加入局部置换对照。",
        "strongest_counterevidence_cn": "强约束后残差消失将反驳额外顺序结构。",
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "metric": "tie_aware_normalized_permutation_entropy_m5",
        "null_models": ["residue_path_conditioned_permutation"],
        "reference_indices": [1],
    }

    def brainstorm(**kwargs: Any) -> Any:
        calls.append("candidate-brainstorm")
        assert calls[:5] == [
            "broad-retrieval",
            "focus-selection",
            "targeted-retrieval",
            "literature-aware-skill-route",
            "candidate-brainstorm",
        ]
        assert kwargs["executable_adapters"][0]["adapter_id"] == ("prime-gap-information-theory-v1")
        assert callable(kwargs["completion"])
        kwargs["capability"].revoke()
        relative = "hypotheses/artifact.json"
        _write_json(
            Path(kwargs["output_dir"]) / relative,
            {"artifact_hash": hypothesis_hash, "candidates": [candidate]},
        )
        _write_json(
            Path(kwargs["output_dir"]) / "direction-hypothesis-brainstorm.json",
            {"artifact_hash": hypothesis_hash, "candidates": [candidate]},
        )
        return SimpleNamespace(
            direction=_DIRECTION,
            artifact_hash=hypothesis_hash,
            artifact_relative_path=relative,
            candidates=(candidate,),
            model_call_count=3,
        )

    references = literature.objective_literature_catalog()
    pilot_method_references = (
        "Permutation method. https://doi.org/10.1000/permutation.method",
        "Prime-gap method. https://doi.org/10.1000/prime-gap.method",
    )
    final_references = references[:5]

    def provisional(**kwargs: Any) -> ContestDirectPlanArtifact:
        calls.append("internal-provisional")
        assert kwargs["preexperiment_context"] is None
        assert kwargs["thinking_mode"] == "disabled"
        assert kwargs["thinking_budget"] is None
        assert callable(kwargs["llm_call"])
        artifact = _plan(references=references, pilot=False)
        _write_json(Path(kwargs["output_path"]), artifact.model_dump(mode="json"))
        return artifact

    pilot_holder: dict[str, Any] = {}

    def run_pilot(**kwargs: Any) -> Any:
        calls.append("real-pilot")
        root = Path(kwargs["output_dir"])
        root.mkdir(parents=True)
        brief = Path(kwargs["source_plan_path"])
        pilot = SimpleNamespace(
            artifact_hash="7" * 64,
            run_id="prime-pilot-0123456789abcdef",
            status="completed",
            study_phase="exploratory_pilot",
            source_plan_sha256=_sha256(brief),
            formal_experiment_executed=False,
            mathematical_proof_claimed=False,
            metrics_sha256="8" * 64,
            manifest_sha256="9" * 64,
            references=pilot_method_references,
            aggregate_results=[
                {
                    "null_model": "residue_path_conditioned_permutation",
                    "interval_count": 1,
                    "draw_count": 199,
                    "observed_mean_entropy": 0.91,
                    "null_mean_entropy": 0.912,
                    "delta_observed_minus_null": -0.002,
                    "one_sided_empirical_p_lower": 0.02,
                    "holm_adjusted_p_across_null_models": 0.04,
                    "fixed_interval_resampling_delta_ci95": [-0.003, -0.001],
                }
            ],
            interval_results=[
                {
                    "interval_index": 1,
                    "start": 100,
                    "stop": 200,
                    "prime_count": 25,
                    "gap_count": 24,
                    "mean_gap": 4.1,
                    "observed_metrics": {"tie_aware_normalized_permutation_entropy_m5": 0.91},
                }
            ],
            plan_context_payload=lambda: {"真实预实验": "已执行并有哈希证据"},
        )
        _write_json(root / "prime-preexperiment.json", {"artifact_hash": pilot.artifact_hash})
        pilot_holder["pilot"] = pilot
        return pilot

    def load_pilot(_path: Path, *, verify_files: bool) -> Any:
        assert verify_files is True
        return pilot_holder["pilot"]

    post_hash = "a" * 64

    def postpilot(**kwargs: Any) -> Any:
        calls.append("postpilot-feedback-and-objective-review")
        assert calls.index("real-pilot") < calls.index("postpilot-feedback-and-objective-review")
        assert callable(kwargs["completion"])
        recalled_contexts.append(kwargs["derived_memory_context"])
        kwargs["capability"].revoke()
        relative = "postpilot/artifact.json"
        _write_json(
            Path(kwargs["output_dir"]) / relative,
            {"artifact_hash": post_hash, "plan_context": {"结论": "收窄假设"}},
        )
        _write_json(
            Path(kwargs["output_dir"]) / "postpilot-objective-review.json",
            {"artifact_hash": post_hash, "plan_context": {"结论": "收窄假设"}},
        )
        return SimpleNamespace(
            artifact_hash=post_hash,
            artifact_relative_path=relative,
            model_call_count=1,
            plan_context_payload=lambda: {"结论": "收窄假设"},
        )

    class Revision:
        document_type = "含真实预实验结果的科学假设与研究计划"
        status = "revised_from_verified_preexperiment"
        revision_id = "direct-plan-revision-0123456789abcdef"
        provider = "test"
        model_name = "test-model"
        generation_calls = 1
        input_hash = "b" * 64
        model_response_hash = "c" * 64
        artifact_hash = "d" * 64
        plan = SimpleNamespace(
            results="预实验真实执行后，主假设被收窄。",
            references=final_references,
        )

        def flat_payload(self) -> dict[str, Any]:
            return {
                "title": "真实预实验反馈后的素数间隙研究计划",
                "abstract": "根据真实探索性预实验收窄假设。",
                "problem_statement": "区分模约束与额外顺序结构。",
                "rationale": "用强条件零模型检验。",
                "technical_details": "分段筛、排列熵与条件置换。",
                "datasets": {
                    "description": "连续素数间隙",
                    "source": "分段筛",
                    "target": "有序间隙",
                },
                "methods": "冻结协议。",
                "experiments": {"steps": "扩大区间", "baselines": "条件置换", "metrics": "排列熵"},
                "results": "预实验已执行并据此收窄。",
                "references": list(final_references),
            }

    def revise(**kwargs: Any) -> Any:
        calls.append("evidence-guarded-final-revision")
        assert "独立目标评审上下文" in "\n".join(kwargs["requirements"])
        assert tuple(kwargs["reference_catalog"]) == references
        assert not set(pilot_method_references).intersection(kwargs["reference_catalog"])
        assert callable(kwargs["llm_call"])
        recalled_contexts.append(kwargs["derived_memory_context"])
        artifact = Revision()
        _write_json(Path(kwargs["output_path"]), {"artifact_hash": artifact.artifact_hash})
        return artifact

    def materialize(**kwargs: Any) -> ContestDirectPlanArtifacts:
        calls.append("materialize-final")
        embedded = kwargs["payload"]["embedded_evidence"]
        assert len(embedded["tables"]) == 2
        assert len(embedded["figures"]) == 1
        assert kwargs["evidence_bindings"]
        assert ".json" not in json.dumps(embedded, ensure_ascii=False)
        root = Path(kwargs["output_dir"])
        root.mkdir(parents=True)
        paths = {
            "json": root / "research-plan.json",
            "markdown": root / "research-plan.md",
            "tex": root / "research-plan.tex",
            "pdf": root / "research-plan.pdf",
            "manifest": root / "research-plan-manifest.json",
        }
        _write_json(paths["json"], kwargs["payload"])
        paths["markdown"].write_text("# 计划\n", encoding="utf-8")
        paths["tex"].write_text("\\documentclass{article}\n", encoding="utf-8")
        paths["pdf"].write_bytes(b"%PDF-1.4\nmock\n%%EOF\n")
        _write_json(paths["manifest"], {"status": "compiled"})
        return ContestDirectPlanArtifacts(
            output_dir=root,
            json_path=paths["json"],
            markdown_path=paths["markdown"],
            tex_path=paths["tex"],
            pdf_path=paths["pdf"],
            manifest_path=paths["manifest"],
            source_payload_sha256=canonical_model_hash(kwargs["payload"]),
            page_count=6,
            pdf_text_verified=True,
        )

    def final_review(**kwargs: Any) -> Any:
        calls.append("independent-final-review")
        assert callable(kwargs["llm_call"])
        recalled_contexts.append(kwargs["derived_memory_context"])
        root = Path(kwargs["output_dir"])
        root.mkdir(parents=True)
        artifact = SimpleNamespace(
            artifact_hash="f" * 64,
            generation_calls=1,
            plan_rewrite_performed=False,
            independence_scope="fresh_interaction_not_model_family_independence",
            review=SimpleNamespace(recommendation="pass"),
        )
        review_artifacts.append(artifact)
        _write_json(
            root / "system-plan-scientific-review.json",
            {"artifact_hash": artifact.artifact_hash},
        )
        return artifact

    monkeypatch.setattr(
        loop_cli,
        "load_contest_direct_plan_scientific_review",
        lambda *_args, **_kwargs: review_artifacts[-1],
    )
    mock_physical_attempts = {
        "broad-literature-query": 1,
        "focus-selection": 2,
        "targeted-literature-query": 1,
        "planning-literature-gap-repair-query": 0,
        "skill-routing": 1,
        "hypothesis-brainstorm": 3,
        "provisional-plan": 1,
        "postpilot-objective-review": 1,
        "final-plan-revision": revision_physical_attempts,
        "independent-scientific-review": 1,
    }
    monkeypatch.setattr(
        loop_cli,
        "provider_checkpoint_accounting",
        lambda _root, *, stage_name: {
            "attempt_count": mock_physical_attempts[stage_name],
            "completed_count": mock_physical_attempts[stage_name],
            "parse_failed_count": 0,
            "transport_failed_count": 0,
            "terminal_failed_count": 0,
            "outcome_unknown_count": 0,
        },
    )

    report = run_contest_direction_research_loop(
        direction=_DIRECTION,
        output_dir=tmp_path / "run",
        context_vault_root=tmp_path / "vault",
        skills_root=skills_root,
        literature_runner=retrieve,
        skill_router=route,
        hypothesis_stage_runner=brainstorm,
        postpilot_stage_runner=postpilot,
        preexperiment_runner=run_pilot,
        preexperiment_loader=load_pilot,
        plan_generator=provisional,
        plan_revision_runner=revise,
        plan_materializer=materialize,
        scientific_review_runner=final_review,
        arxiv_status_verifier=verify_status,
    )

    assert report["status"] == "completed"
    assert report["preexperiment_executed"] is True
    assert report["plan"]["internal_provisional_plan_delivered"] is False
    assert report["schema_version"] == "contest-direction-research-loop-delivery-v2"
    assert report["literature_protocol"] == "two_stage_literature_v5"
    assert report["source_accounting"]["checkpoint_status"] == ("verified_local_checkpoints")
    assert report["source_accounting"]["paper_status_verifications"]["requested_count"] == 0
    assert (
        report["source_accounting"]["physical_http_attempts"]["accounting_status"]
        == "verified_current_protocol"
    )
    assert report["model_call_accounting"]["total_provenance_provider_request_attempts"] == 12
    assert report["model_call_accounting"]["this_loop_observed_provider_request_attempts"] == 12
    assert (
        report["model_call_accounting"]["physical_provider_attempt_total"]
        == expected_physical_total
    )
    assert (
        report["stage_execution"]["evidence_guarded_final_plan_revision"][
            "provider_request_attempts"
        ]
        == revision_physical_attempts
    )
    assert "planning_literature_coverage_r2" not in report["artifacts"]
    assert report["literature"]["finalist_status_verification_count"] == 0
    assert report["literature"]["finalist_status_excluded_count"] == 0
    assert status_calls == []
    assert len(context_completions) == 6
    assert len(recalled_contexts) == 3
    assert all(
        context["context_kind"] == "optional_rebuildable_dreaming_navigation"
        and context["derived_context_is_evidence"] is False
        and context["model_consumption_proven_by_this_receipt"] is False
        for context in recalled_contexts
    )
    assert set(report["memory"]["completed_stage_captures"]) == {
        "broad-literature-query",
        "focus-selection",
        "targeted-literature-query",
        "planning-literature-lock",
        "skill-routing",
        "hypothesis-brainstorm",
        "provisional-plan",
        "real-pilot",
        "postpilot-objective-review",
        "final-plan-revision",
        "render-plan",
        "independent-scientific-review",
    }
    assert set(report["memory"]["optional_model_recalls"]) == {
        "postpilot-objective-review",
        "final-plan-revision",
        "independent-scientific-review",
    }
    assert all(
        item["context_injected_into_model_stage"] is True
        and item["derived_context_is_evidence"] is False
        for item in report["memory"]["optional_model_recalls"].values()
    )
    raw_records_before_resume = tuple(sorted((tmp_path / "vault").rglob("rawmem_*.json")))
    assert raw_records_before_resume
    status_receipt = json.loads(
        (tmp_path / "run" / "literature" / "finalist-status-verification.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        status_receipt["artifact_hash"]
        == report["literature"]["finalist_status_verification_artifact_hash"]
    )
    assert calls == [
        "broad-retrieval",
        "focus-selection",
        "targeted-retrieval",
        "literature-aware-skill-route",
        "candidate-brainstorm",
        "internal-provisional",
        "real-pilot",
        "postpilot-feedback-and-objective-review",
        "evidence-guarded-final-revision",
        "materialize-final",
        "independent-final-review",
    ]
    resumed = run_contest_direction_research_loop(
        direction=_DIRECTION,
        output_dir=tmp_path / "run",
        context_vault_root=tmp_path / "vault",
        skills_root=skills_root,
        resume_existing=True,
        arxiv_status_verifier=lambda _paper: pytest.fail(
            "completed resume must not verify arXiv status again"
        ),
    )
    assert resumed["resume_action"] == "already_complete_no_model_call"
    assert resumed["delivery_report_sha256"] == report["delivery_report_sha256"]
    assert resumed["memory_resume"]["receipt_replay_count"] == 12
    assert resumed["memory_resume"]["new_capture_count"] == 0
    assert tuple(sorted((tmp_path / "vault").rglob("rawmem_*.json"))) == (raw_records_before_resume)
    delivery_report_path = tmp_path / "run" / "delivery-report.json"
    original_delivery_report = delivery_report_path.read_bytes()
    downgraded_report = json.loads(original_delivery_report)
    downgraded_report.pop("source_accounting")
    downgraded_report["report_hash"] = canonical_model_hash(
        {key: value for key, value in downgraded_report.items() if key != "report_hash"}
    )
    _write_json(delivery_report_path, downgraded_report)
    with pytest.raises(ContestDirectionResearchLoopError, match="source-accounting"):
        run_contest_direction_research_loop(
            direction=_DIRECTION,
            output_dir=tmp_path / "run",
            context_vault_root=tmp_path / "vault",
            skills_root=skills_root,
            resume_existing=True,
        )
    delivery_report_path.write_bytes(original_delivery_report)
    status_receipt["verification_count"] = 1
    _write_json(
        tmp_path / "run" / "literature" / "finalist-status-verification.json",
        status_receipt,
    )
    with pytest.raises(
        ContestDirectionResearchLoopError,
        match="finalist status verification (hash|count) mismatch",
    ):
        run_contest_direction_research_loop(
            direction=_DIRECTION,
            output_dir=tmp_path / "run",
            context_vault_root=tmp_path / "vault",
            skills_root=skills_root,
            resume_existing=True,
            arxiv_status_verifier=lambda _paper: pytest.fail(
                "tampered completed resume must fail before status network access"
            ),
        )


def test_adapter_compatibility_requires_descriptor_and_null_coverage() -> None:
    base = {
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "metric": "tie_aware_normalized_permutation_entropy_m5",
        "null_models": ["residue_path_conditioned_permutation"],
    }
    assert loop_cli._candidate_fits_prime_gap_adapter(base)
    assert not loop_cli._candidate_fits_prime_gap_adapter(
        {**base, "observable": "unordered_gap_histogram"}
    )
    assert not loop_cli._candidate_fits_prime_gap_adapter(
        {**base, "null_models": ["unsupported_null"]}
    )
    assert not loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": "用素数签名之间的ℓ∞距离重新定义间隙，再计算排列熵。",
        }
    )
    assert not loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": "研究梅森素数指数之间的间隙及其排列熵。",
        }
    )
    assert not loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": "以样本熵为主指标研究连续素数间隙。",
        }
    )
    assert not loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": "检验普通连续素数算术差的排列熵。",
            "falsification_cn": "构造素数签名并计算ℓ∞距离后无差异则否决。",
        }
    )
    assert loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": ("不构造素数签名或ℓ∞距离；只分析普通连续素数算术间隙的排列熵。"),
        }
    )
    assert loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": ("将普通连续素数间隙映射为五阶序型，并用排列熵度量顺序复杂度。"),
        }
    )
    assert loop_cli._candidate_fits_prime_gap_adapter(
        {
            **base,
            "hypothesis_cn": "检验普通连续素数算术差的排列熵。",
            "strongest_counterevidence_cn": (
                "另有素数签名ℓ∞距离模型，但它只是本候选不执行的替代解释。"
            ),
        }
    )


@pytest.mark.parametrize("recommendation", ["major_revision", "reject", "unclear"])
def test_final_scientific_review_blocks_delivery_and_replays_receipt_without_rewrite(
    tmp_path: Path,
    recommendation: str,
) -> None:
    root = tmp_path / "run"
    review_path = root / "independent-scientific-review" / "system-plan-scientific-review.json"
    _write_json(review_path, {"artifact_hash": "f" * 64})
    final_review = SimpleNamespace(
        artifact_hash="f" * 64,
        review=SimpleNamespace(
            recommendation=recommendation,
            recommendation_text=f"终审结论：{recommendation}",
        ),
    )

    with pytest.raises(
        ContestDirectionResearchLoopError,
        match="independent scientific review blocked final delivery",
    ):
        loop_cli._enforce_scientific_review_delivery_gate(
            root=root,
            direction="原始问题",
            focused_direction=_DIRECTION,
            final_review=final_review,
            review_path=review_path,
        )

    receipt_path = root / "scientific-review-blocked-receipt.json"
    first_bytes = receipt_path.read_bytes()
    receipt = json.loads(first_bytes)
    assert receipt["status"] == "blocked_by_independent_scientific_review"
    assert receipt["recommendation"] == recommendation
    assert receipt["delivery_report_created"] is False
    assert receipt["automatic_revision_performed"] is False
    assert not (root / "delivery-report.json").exists()

    with pytest.raises(ContestDirectionResearchLoopError, match="blocked final delivery"):
        loop_cli._enforce_scientific_review_delivery_gate(
            root=root,
            direction="原始问题",
            focused_direction=_DIRECTION,
            final_review=final_review,
            review_path=review_path,
        )
    assert receipt_path.read_bytes() == first_bytes


def test_minor_scientific_review_is_an_explicit_nonblocking_completion(
    tmp_path: Path,
) -> None:
    final_review = SimpleNamespace(review=SimpleNamespace(recommendation="minor_revision"))

    assert loop_cli._scientific_completion_status("minor_revision") == (
        "completed_with_minor_issues"
    )
    loop_cli._verify_completed_scientific_delivery_gate(
        root=tmp_path,
        report={
            "status": "completed_with_minor_issues",
            "independent_scientific_review": {"recommendation": "minor_revision"},
        },
        final_review=final_review,
    )
    with pytest.raises(ContestDirectionResearchLoopError, match="status disagrees"):
        loop_cli._verify_completed_scientific_delivery_gate(
            root=tmp_path,
            report={
                "status": "completed",
                "independent_scientific_review": {"recommendation": "minor_revision"},
            },
            final_review=final_review,
        )


def test_blocked_resume_revalidates_receipt_without_a_new_review_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_path = tmp_path / "independent-scientific-review" / "system-plan-scientific-review.json"
    _write_json(review_path, {"artifact_hash": "f" * 64})
    final_review = SimpleNamespace(
        artifact_hash="f" * 64,
        review=SimpleNamespace(
            recommendation="major_revision",
            recommendation_text="需要大修",
        ),
    )
    receipt = loop_cli._scientific_block_receipt_payload(
        direction="原始问题",
        focused_direction=_DIRECTION,
        final_review=final_review,
        review_path=review_path,
    )
    _write_json(tmp_path / "scientific-review-blocked-receipt.json", receipt)
    monkeypatch.setattr(
        loop_cli,
        "_load_completed_two_stage_literature",
        lambda _root: SimpleNamespace(
            focus=SimpleNamespace(focused_direction_cn=_DIRECTION),
        ),
    )
    monkeypatch.setattr(
        loop_cli,
        "load_contest_direct_plan_scientific_review",
        lambda *_args, **_kwargs: final_review,
    )

    with pytest.raises(ContestDirectionResearchLoopError, match="no model call was repeated"):
        loop_cli._raise_if_existing_scientific_review_block(
            root=tmp_path,
            direction="原始问题",
        )


def test_completed_fast_path_rejects_a_blocking_scientific_review(tmp_path: Path) -> None:
    final_review = SimpleNamespace(review=SimpleNamespace(recommendation="major_revision"))

    with pytest.raises(ContestDirectionResearchLoopError, match="forbidden"):
        loop_cli._verify_completed_scientific_delivery_gate(
            root=tmp_path,
            report={
                "status": "completed",
                "independent_scientific_review": {"recommendation": "major_revision"},
            },
            final_review=final_review,
        )


def test_final_bibliography_ranking_uses_focus_and_targeted_queries_only() -> None:
    focus = SimpleNamespace(
        focused_direction_cn="聚焦后的可证伪研究方向",
        selected_candidate=SimpleNamespace(
            nearest_work_queries=(),
            methods_baselines_queries=(),
            counterevidence_queries=(),
        ),
    )
    targeted = SimpleNamespace(queries=("nearest work query", "method baseline query"))

    queries = loop_cli._focused_planning_queries(focus, targeted)

    assert queries == (
        "聚焦后的可证伪研究方向",
        "nearest work query",
        "method baseline query",
    )
    assert "broad homonym query" not in queries


def test_default_two_stage_boundaries_share_arxiv_client_and_rate_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeArxiv:
        def __init__(self) -> None:
            self.rate_limiter = object()
            instances.append(self)

        def search(self, _query: str, *, limit: int) -> list[Any]:  # noqa: ARG002
            return []

        def verify_status(self, paper: Any) -> Any:
            return paper

    class FakeOpenAlex:
        def search(self, _query: str, *, limit: int) -> list[Any]:  # noqa: ARG002
            return []

    monkeypatch.setattr(loop_cli, "ArxivClient", FakeArxiv)
    monkeypatch.setattr(loop_cli, "OpenAlexClient", FakeOpenAlex)
    monkeypatch.setattr(loop_cli, "semantic_scholar_enabled", lambda: False)

    searchers, verifier = loop_cli._shared_literature_boundaries(
        literature_searchers=None,
        arxiv_status_verifier=None,
    )

    assert len(instances) == 1
    assert searchers["arxiv"].__self__ is instances[0]
    assert verifier is not None
    assert verifier.__self__ is instances[0]
    assert searchers["arxiv"].__self__.rate_limiter is verifier.__self__.rate_limiter


def test_focus_prompt_exposes_program_capability_without_skill_and_can_choose_no_adapter(
    tmp_path: Path,
) -> None:
    papers = [
        AcademicPaper(
            title=f"Finite prime structure evidence {index}",
            authors=[f"Author {index}"],
            abstract=(
                "This paper studies finite prime counting structure and falsifiable "
                f"computational comparisons, evidence family {index}."
            ),
            publication_date=date(2024, 1, index),
            doi=f"10.1000/focus-capability.{index}",
            url=f"https://example.org/focus-capability-{index}",
            source="openalex",
        )
        for index in (1, 2)
    ]
    focus_queries = (
        '("finite prime structure" OR "finite prime counting") AND '
        '("computational comparisons" OR evidence)',
        '("computational comparisons" OR "finite sample") AND (validation OR evidence)',
        '("finite prime structure" OR "finite prime counting") AND ("null model" OR mechanism)',
        '("finite prime structure" OR "finite prime counting") AND (limitations OR bias)',
    )
    broad = retrieve_contest_direction_literature(
        direction="素数为何如此特别？",
        selected_method_skills={},
        searchers={"openalex": lambda _query, *, limit: papers[:limit]},
        retrieved_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        llm_call=lambda **_: LLMJsonCompletionResult(
            provider="test",
            base_url="https://provider.example/v1",
            model_name="test-model",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=json.dumps({"queries": list(focus_queries)}),
            parsed_json={"queries": list(focus_queries)},
            temperature=0.2,
        ),
    )
    responses = iter(
        (
            {
                "candidates": [
                    {
                        "title_cn": "素数间隙顺序结构",
                        "focused_direction_cn": "检验连续素数间隙的有限尺度顺序结构。",
                        "problem_gap_cn": "现有证据未区分算术约束与额外顺序依赖。",
                        "falsifiable_objective_cn": "条件零模型后效应消失则否定。",
                        "evidence_rationale_cn": "证据一支持有限尺度比较。",
                        "nearest_work_queries": ["prime gap nearest work"],
                        "methods_baselines_queries": ["prime gap null baseline"],
                        "counterevidence_queries": ["prime gap null result"],
                        "evidence_indices": [1],
                    },
                    {
                        "title_cn": "解析误差项边界",
                        "focused_direction_cn": "研究有限区间素数计数误差项的解析上界与反例。",
                        "problem_gap_cn": "有限计算证据不能给出解析边界。",
                        "falsifiable_objective_cn": "构造反例即可否定候选统一上界。",
                        "evidence_rationale_cn": "证据二提示应独立核对解析替代解释。",
                        "nearest_work_queries": ["prime counting error bound"],
                        "methods_baselines_queries": ["analytic number theory baseline"],
                        "counterevidence_queries": ["prime counting bound counterexample"],
                        "evidence_indices": [1],
                    },
                ]
            },
            {
                "selected_candidate_number": 2,
                "selection_rationale_cn": "解析方向科学价值更高，即使当前没有可执行适配器。",
            },
        )
    )

    def complete(**_: Any) -> LLMJsonCompletionResult:
        payload = next(responses)
        return LLMJsonCompletionResult(
            provider="test",
            base_url="https://provider.example/v1",
            model_name="test-model",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            temperature=0.2,
        )

    focus = run_contest_direction_focus_selection(
        direction=broad.direction,
        broad_literature=broad,
        output_dir=tmp_path / "focus",
        requirements=loop_cli._LOOP_REQUIREMENTS,
        executable_adapter_capabilities=(loop_cli._ADAPTER_DESCRIPTOR,),
        completion=complete,
    )
    receipt = json.loads(
        (tmp_path / "focus" / "direction-focus-brainstorm-response.json").read_text(
            encoding="utf-8"
        )
    )
    prompt = json.dumps(receipt["messages"], ensure_ascii=False)

    assert "executable_pilot_capabilities" in prompt
    assert "prime-gap-information-theory-v1" in prompt
    assert "selected_method_skills" not in prompt
    assert "使用分段筛、排列熵和条件置换零模型。" not in prompt
    assert focus.selected_candidate_number == 2
    assert not loop_cli._direction_fits_prime_gap_adapter(focus.focused_direction_cn)


def test_planning_role_queries_bind_mechanism_and_counter_to_the_direct_object() -> None:
    shared_object = '("aurora units" OR "aurora arrays")'
    targeted = SimpleNamespace(
        queries=(
            f'{shared_object} AND ("phase drift" OR "state drift")',
            '("rank pattern" OR "ordinal measure") AND ("formal definition" OR foundation)',
            f'{shared_object} AND ("null mechanism" OR surrogate)',
            f'{shared_object} AND (failure OR "alternative explanation")',
        )
    )

    role_queries = loop_cli._planning_coverage_role_queries(targeted)

    assert role_queries[0].must_groups[0] == role_queries[2].must_groups[0]
    assert role_queries[0].must_groups[0] == role_queries[3].must_groups[0]


@pytest.mark.parametrize(
    "queries",
    (
        (
            '("aurora units" OR "aurora arrays") AND ("phase drift" OR "state drift")',
            '("rank pattern" OR "ordinal measure") AND ("formal definition" OR foundation)',
            '("foreign objects" OR "foreign arrays") AND ("null mechanism" OR surrogate)',
            '("aurora units" OR "aurora arrays") AND (failure OR "alternative explanation")',
        ),
        (
            '("aurora units" OR "aurora arrays") AND ("phase drift" OR "state drift")',
            '("rank pattern" OR "ordinal measure") AND ("formal definition" OR foundation)',
            '("aurora units" OR "aurora arrays") AND ("null mechanism" OR surrogate)',
            '("foreign objects" OR "foreign arrays") AND (failure OR "alternative explanation")',
        ),
        (
            '(model OR system) AND ("phase drift" OR "state drift")',
            '("rank pattern" OR "ordinal measure") AND ("formal definition" OR foundation)',
            '(model OR system) AND ("null mechanism" OR surrogate)',
            '(model OR system) AND (failure OR "alternative explanation")',
        ),
    ),
)
def test_planning_role_queries_reject_unshared_or_generic_core_objects(
    queries: tuple[str, ...],
) -> None:
    with pytest.raises(ContestDirectionResearchLoopError, match="core object"):
        loop_cli._planning_coverage_role_queries(SimpleNamespace(queries=queries))


def test_coverage_preserves_complementary_role_lineage_within_one_work_family() -> None:
    shared_object = '("aurora units" OR "aurora arrays")'
    raw_queries = (
        f'{shared_object} AND ("phase drift" OR "state drift")',
        '("rank pattern" OR "ordinal measure") AND ("formal definition" OR foundation)',
        f'{shared_object} AND ("null mechanism" OR surrogate)',
        f'{shared_object} AND (failure OR "alternative explanation")',
    )
    role_queries = loop_cli._planning_coverage_role_queries(SimpleNamespace(queries=raw_queries))

    def record(
        record_id: str,
        title: str,
        abstract: str,
        retrieval_queries: tuple[str, ...],
        citation_count: int,
    ) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "title": title,
            "authors": ["A. Author"],
            "abstract": abstract,
            "venue": "Synthetic Evidence Journal",
            "publication_date": "2024-01-01",
            "citation_count": citation_count,
            "publication_status": "published",
            "retrieved_from": "openalex",
            "retrieval_queries": list(retrieval_queries),
            "source_stages": ["targeted_direction"],
        }

    family_title = "Aurora units under phase drift and a null mechanism"
    family_abstract = "Aurora arrays exhibit state drift under a surrogate null mechanism."
    catalog = (
        record("family-direct", family_title, family_abstract, (raw_queries[0],), 100),
        record("family-mechanism", family_title, family_abstract, (raw_queries[2],), 1),
        record(
            "direct-one",
            "Aurelia-like aurora units under phase drift",
            "Aurora arrays exhibit state drift.",
            (raw_queries[0],),
            20,
        ),
        record(
            "direct-two",
            "State drift in aurora arrays",
            "Aurora units exhibit phase drift.",
            (raw_queries[0],),
            10,
        ),
        record(
            "method-anchor",
            "Formal definition of rank pattern measures for aurora units",
            "A foundation for ordinal measure analysis.",
            (raw_queries[1],),
            30,
        ),
        record(
            "counter-anchor",
            "Failure of an aurora units explanation",
            "Aurora arrays admit an alternative explanation for the failure.",
            (raw_queries[3],),
            5,
        ),
    )
    contexts = tuple(f"context for {item['record_id']}" for item in catalog)

    coverage = loop_cli._coverage_select(catalog, contexts, role_queries=role_queries)

    assert coverage.passed is True
    assert coverage.candidate_count == 6
    assert "family-mechanism" in coverage.selected_record_ids
    assert "family-direct" not in coverage.selected_record_ids
    assert len({item.anchor_id for item in coverage.anchor_assignments}) == 5


def test_two_stage_literature_fresh_then_resume_replays_artifacts_and_outer_escrow(
    tmp_path: Path,
) -> None:
    broad_titles = (
        "Residue transitions in consecutive prime gaps",
        "Permutation entropy of ordered prime spacings",
        "Finite interval heterogeneity for prime gaps",
        "Wheel constraints on neighboring prime differences",
        "Block resampling for arithmetic point processes",
        "Counterevidence to stationary local prime spacing models",
    )
    broad_papers = [
        AcademicPaper(
            title=broad_titles[index - 1],
            authors=[f"Broad Author {index}"],
            abstract=(
                "Consecutive prime gaps, residue constraints, ordinal entropy and finite "
                f"interval uncertainty are compared in broad evidence family {index}."
            ),
            publication_date=date(2018 + index, 1, 1),
            doi=f"10.1000/broad-prime-gap.{index}",
            url=f"https://example.org/broad-prime-gap-{index}",
            citation_count=index * 10,
            citation_count_source="openalex",
            citation_count_as_of=date(2026, 8, 13),
            publication_status="published",
            source="openalex",
        )
        for index in range(1, 7)
    ]
    targeted_titles = (
        "Nearest work on residue-aware prime-gap transitions",
        "Ordinal patterns in consecutive prime spacing",
        "Tie handling and finite-sample permutation entropy",
        "Arithmetic null models for consecutive prime gaps",
        "Null results and alternative explanations for prime spacing",
        "Cross-interval stability of prime-gap ordinal patterns",
    )
    targeted_abstracts = (
        "Consecutive prime gaps and residue transitions define ordinal patterns.",
        "Prime spacing sequences are compared through residue transitions and ordinal patterns.",
        "Prime spacing permutation entropy estimation requires explicit tie handling and finite sample checks.",
        "Consecutive prime gaps require arithmetic null models for residue bias.",
        "Prime spacing studies report a null result and an alternative explanation.",
        "Consecutive prime gaps retain ordinal patterns across finite intervals.",
    )
    targeted_papers = [
        AcademicPaper(
            title=targeted_titles[index - 1],
            authors=[f"Target Author {index}"],
            abstract=targeted_abstracts[index - 1],
            publication_date=date(2020 + index, 2, 1),
            doi=f"10.1000/targeted-prime-gap.{index}",
            url=f"https://example.org/targeted-prime-gap-{index}",
            citation_count=index * 7,
            citation_count_source="openalex",
            citation_count_as_of=date(2026, 8, 13),
            publication_status="published",
            source="openalex",
        )
        for index in range(1, 7)
    ]
    provider_calls: list[str] = []
    search_calls: list[str] = []
    focus_call_count = 0

    def provider(stage: str, **_kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal focus_call_count
        provider_calls.append(stage)
        if stage == "broad-literature-query":
            payload: dict[str, Any] = {"queries": list(_V4_BROAD_QUERY_PLAN)}
        elif stage == "focus-selection":
            focus_call_count += 1
            if focus_call_count == 1:
                payload = {
                    "candidates": [
                        {
                            "title_cn": "残基条件化后的顺序结构",
                            "focused_direction_cn": (
                                "检验连续素数间隙在残基路径条件化后是否仍保留信息论顺序结构。"
                            ),
                            "problem_gap_cn": "宽检索尚未区分模约束与额外顺序依赖。",
                            "falsifiable_objective_cn": (
                                "若条件零模型下差异消失则否定额外顺序结构。"
                            ),
                            "evidence_rationale_cn": "宽检索证据支持间隙、残基与熵的联合核对。",
                            "nearest_work_queries": ["prime gap residue nearest work"],
                            "methods_baselines_queries": [
                                "prime gap conditional permutation baseline"
                            ],
                            "counterevidence_queries": ["prime gap entropy null result"],
                            "evidence_indices": [1, 2],
                            "pilot_adapter_id": "prime-gap-information-theory-v1",
                            "pilot_feasibility_cn": "当前注册pilot可在冻结有限区间执行该比较。",
                        },
                        {
                            "title_cn": "解析边界替代方向",
                            "focused_direction_cn": "研究素数计数误差项的解析边界。",
                            "problem_gap_cn": "计算证据不能直接给出解析证明。",
                            "falsifiable_objective_cn": "构造反例则否定统一边界。",
                            "evidence_rationale_cn": "宽检索提示需核对替代解释。",
                            "nearest_work_queries": ["prime counting analytic bound"],
                            "methods_baselines_queries": ["analytic number theory method"],
                            "counterevidence_queries": ["prime counting counterexample"],
                            "evidence_indices": [2],
                            "pilot_adapter_id": "no_adapter",
                            "pilot_feasibility_cn": "当前没有可执行解析证明适配器。",
                        },
                    ]
                }
            else:
                payload = {
                    "selected_candidate_number": 1,
                    "selection_rationale_cn": "方向可证伪且有真实低成本pilot，但创新仍待定向检索。",
                }
        elif stage == "targeted-literature-query":
            payload = {
                "queries": [
                    "(consecutive prime gaps OR prime spacing) AND (residue transitions OR ordinal patterns)",
                    "(permutation entropy OR ordinal analysis) AND (tie handling OR finite sample)",
                    "(consecutive prime gaps OR prime spacing) AND (arithmetic null model OR residue bias)",
                    "(consecutive prime gaps OR prime spacing) AND (null result OR alternative explanation)",
                ]
            }
        else:  # pragma: no cover - protects the test dispatcher
            raise AssertionError(stage)
        return LLMJsonCompletionResult(
            provider="test",
            base_url="https://provider.example/v1",
            model_name="test-model",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            temperature=0.2,
        )

    class EscrowContextRuntime:
        @contextmanager
        def checkpointed_stage(self, stage: str, *, input_hash: str, checkpoint_root: Path) -> Any:
            completion = replayable_stage_completion(
                root=checkpoint_root,
                stage_name=stage,
                stage_input_hash=input_hash,
                completion=lambda **kwargs: provider(stage, **kwargs),
            )
            yield completion

    def search(query: str, *, limit: int) -> list[AcademicPaper]:
        search_calls.append(query)
        papers = broad_papers if len(search_calls) <= 4 else targeted_papers
        return papers[:limit]

    root = tmp_path / "two-stage"
    memory_stages: dict[str, dict[str, Any]] = {}
    fresh = loop_cli._prepare_two_stage_literature(
        parent_direction="素数为何如此特别？",
        direction_input_hash="1" * 64,
        root=root,
        context_runtime=EscrowContextRuntime(),
        memory_bridge=None,
        memory_stages=memory_stages,
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        timeout_seconds=30,
        max_results_per_search=10,
        retrieval_max_tokens=768,
        shared_searchers={"openalex": search},
        shared_status_verifier=None,
        literature_runner=loop_cli.retrieve_contest_direction_literature,
        focus_selection_runner=loop_cli.run_contest_direction_focus_selection,
        targeted_retrieval_runner=loop_cli.run_contest_direction_targeted_retrieval,
        merged_literature_builder=loop_cli.merge_contest_direction_literature,
        resume=False,
    )

    assert 5 <= len(fresh.planning_catalog) <= 10
    assert fresh.planning_lock_payload["work_family_duplicate_suppressions"] == []
    assert "identity_preserved" in fresh.planning_lock_payload["selection_semantics"]
    assert fresh.planning_coverage.passed is True
    assert fresh.planning_coverage.selected_role_counts.direct_core >= 2
    assert fresh.planning_coverage.selected_role_counts.method_foundation >= 1
    assert fresh.planning_coverage.selected_role_counts.mechanism_or_null >= 1
    assert fresh.planning_coverage.selected_role_counts.counterevidence >= 1
    assert fresh.focus.focused_direction_cn.startswith("检验连续素数间隙")
    assert provider_calls == [
        "broad-literature-query",
        "focus-selection",
        "focus-selection",
        "targeted-literature-query",
    ]
    assert len(search_calls) == 8
    assert loop_cli.provider_checkpoint_count(root, stage_name="broad-literature-query") == 1
    assert loop_cli.provider_checkpoint_count(root, stage_name="focus-selection") == 2
    assert loop_cli.provider_checkpoint_count(root, stage_name="targeted-literature-query") == 1
    assert {path.name for path in (root / "checkpoints" / "completed-stages").glob("*.json")} == {
        "01-broad-literature-query.json",
        "02-focus-selection.json",
        "03-targeted-literature-query.json",
        "04-planning-literature-lock.json",
    }

    completed_without_status_verifier = loop_cli._load_completed_two_stage_literature(root)
    assert completed_without_status_verifier.planning_lock_payload == fresh.planning_lock_payload

    provider_calls.clear()
    search_calls.clear()
    resumed = loop_cli._prepare_two_stage_literature(
        parent_direction="素数为何如此特别？",
        direction_input_hash="1" * 64,
        root=root,
        context_runtime=EscrowContextRuntime(),
        memory_bridge=None,
        memory_stages={},
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        timeout_seconds=30,
        max_results_per_search=10,
        retrieval_max_tokens=768,
        shared_searchers={
            "openalex": lambda _query, *, limit: pytest.fail(  # noqa: ARG005
                "resume must not call a literature provider"
            )
        },
        shared_status_verifier=None,
        literature_runner=loop_cli.retrieve_contest_direction_literature,
        focus_selection_runner=loop_cli.run_contest_direction_focus_selection,
        targeted_retrieval_runner=loop_cli.run_contest_direction_targeted_retrieval,
        merged_literature_builder=loop_cli.merge_contest_direction_literature,
        resume=True,
    )

    assert resumed.merged == fresh.merged
    assert resumed.planning_lock_payload == fresh.planning_lock_payload
    assert provider_calls == []
    assert search_calls == []


def test_two_stage_literature_runs_one_bounded_gap_repair_and_replays_it(
    tmp_path: Path,
) -> None:
    broad_papers = [
        AcademicPaper(
            title=title,
            authors=[f"Broad Author {index}"],
            abstract=(
                "Aurora arrays, borealis arrays, ordered responses and rank measures "
                "are compared with finite-sample uncertainty."
            ),
            publication_date=date(2018 + index, 1, 1),
            doi=f"10.1000/bounded-gap-broad.{index}",
            url=f"https://example.org/bounded-gap-broad-{index}",
            citation_count=index * 10,
            citation_count_source="openalex",
            citation_count_as_of=date(2026, 8, 15),
            publication_status="published",
            source="openalex",
        )
        for index, title in enumerate(
            (
                "Phase transitions in aurora arrays",
                "Rank measures of ordered array responses",
                "Bounded oscillations in replicated aurora arrays",
                "Normalized transitions under fixed sampling",
                "Block resampling for synthetic point processes",
                "Counterevidence to stationary borealis array models",
            ),
            start=1,
        )
    ]
    repository_direct = [
        AcademicPaper(
            title=f"Repository note {index} on phase transitions in aurora arrays",
            authors=[f"Repository Author {index}"],
            abstract="Borealis array ordered responses are reported as a repository result.",
            publication_date=date(2025, 1, index),
            doi=f"10.5281/zenodo.{9000 + index}",
            url=f"https://zenodo.org/records/{9000 + index}",
            publication_status="published",
            source="openalex",
        )
        for index in (1, 2)
    ]
    method_papers = [
        AcademicPaper(
            title="Rank measures for aurora arrays",
            authors=["Method Author"],
            abstract="Ordinal analysis requires formal definition and finite sample validation.",
            publication_date=date(2023, 1, 1),
            doi="10.1000/bounded-gap-method",
            url="https://example.org/bounded-gap-method",
            publication_status="published",
            source="openalex",
        )
    ]
    mechanism_papers = [
        AcademicPaper(
            title="Drift mechanisms for aurora arrays",
            authors=["Mechanism Author"],
            abstract="Borealis array comparisons isolate a null mechanism and surrogate drift.",
            publication_date=date(2022, 1, 1),
            doi="10.1000/bounded-gap-mechanism",
            url="https://example.org/bounded-gap-mechanism",
            publication_status="published",
            source="openalex",
        )
    ]
    counter_papers = [
        AcademicPaper(
            title="Limitations of an aurora array explanation",
            authors=["Counter Author"],
            abstract="Borealis arrays admit bias and an alternative explanation.",
            publication_date=date(2021, 1, 1),
            doi="10.1000/bounded-gap-counter",
            url="https://example.org/bounded-gap-counter",
            publication_status="published",
            source="openalex",
        )
    ]
    repaired_direct = [
        AcademicPaper(
            title="Bounded oscillations in aurora arrays",
            authors=["Repair Author One"],
            abstract="Borealis arrays show bounded oscillations across fixed samples.",
            publication_date=date(2024, 1, 1),
            doi="10.1000/bounded-gap-repair-one",
            url="https://example.org/bounded-gap-repair-one",
            publication_status="published",
            source="openalex",
        ),
        AcademicPaper(
            title="Normalized transitions in aurora arrays",
            authors=["Repair Author Two"],
            abstract="Borealis arrays are compared through normalized transitions.",
            publication_date=date(2024, 2, 1),
            doi="10.1000/bounded-gap-repair-two",
            url="https://example.org/bounded-gap-repair-two",
            publication_status="published",
            source="openalex",
        ),
    ]
    provider_calls: list[str] = []
    search_calls: list[str] = []
    focus_call_count = 0

    def provider(stage: str, **kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal focus_call_count
        provider_calls.append(stage)
        if stage == "broad-literature-query":
            payload: dict[str, Any] = {"queries": list(_V4_BROAD_QUERY_PLAN)}
        elif stage == "focus-selection":
            focus_call_count += 1
            if focus_call_count == 1:
                payload = {
                    "candidates": [
                        {
                            "title_cn": "合成阵列中的有界顺序结构",
                            "focused_direction_cn": "检验合成阵列是否具有可区分的顺序结构。",
                            "problem_gap_cn": "现有证据尚未区分采样效应与额外结构。",
                            "falsifiable_objective_cn": "若条件零模型下差异消失则否定额外结构。",
                            "evidence_rationale_cn": "宽检索给出阵列、采样与顺序模式证据。",
                            "nearest_work_queries": ["aurora array nearest work"],
                            "methods_baselines_queries": ["rank measure baseline"],
                            "counterevidence_queries": ["aurora array limitations"],
                            "evidence_indices": [1, 2, 3, 4],
                            "pilot_adapter_id": "no_adapter",
                            "pilot_feasibility_cn": "本测试只验证通用检索闭环，不执行预实验。",
                        },
                        {
                            "title_cn": "无适配器的替代方向",
                            "focused_direction_cn": "研究一个当前不可执行的解析问题。",
                            "problem_gap_cn": "缺少可执行适配器。",
                            "falsifiable_objective_cn": "找到反例则否定。",
                            "evidence_rationale_cn": "保留为备选。",
                            "nearest_work_queries": ["analytic nearest work"],
                            "methods_baselines_queries": ["analytic method"],
                            "counterevidence_queries": ["analytic counterexample"],
                            "evidence_indices": [1],
                            "pilot_adapter_id": "no_adapter",
                            "pilot_feasibility_cn": "当前无可执行适配器。",
                        },
                    ]
                }
            else:
                payload = {
                    "selected_candidate_number": 1,
                    "selection_rationale_cn": "该方向可证伪并有真实pilot，需定向检索。",
                }
        elif stage == "targeted-literature-query":
            payload = {
                "queries": [
                    "(aurora arrays OR borealis arrays) AND (phase transitions OR ordered responses)",
                    "(rank measures OR ordinal analysis) AND (formal definition OR finite sample)",
                    "(aurora arrays OR borealis arrays) AND (drift mechanism OR null mechanism)",
                    "(aurora arrays OR borealis arrays) AND (limitations OR alternative explanation)",
                ]
            }
        elif stage == "planning-literature-gap-repair-query":
            evidence_payload = json.loads(kwargs["messages"][2]["content"])
            evidence = evidence_payload["evidence_inputs"]
            terms: list[dict[str, str]] = []
            for phrase in ("bounded oscillations", "normalized transitions"):
                match = next(item for item in evidence if phrase in item["title"].casefold())
                terms.append(
                    {
                        "term": phrase,
                        "evidence_hash": match["evidence_hash"],
                        "matched_field": "title",
                    }
                )
            payload = {"repairs": [{"role": "direct_core", "replacement_terms": terms}]}
        else:  # pragma: no cover
            raise AssertionError(stage)
        return LLMJsonCompletionResult(
            provider="test",
            base_url="https://provider.example/v1",
            model_name="test-model",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            temperature=0.2,
        )

    class EscrowContextRuntime:
        @contextmanager
        def checkpointed_stage(self, stage: str, *, input_hash: str, checkpoint_root: Path) -> Any:
            yield replayable_stage_completion(
                root=checkpoint_root,
                stage_name=stage,
                stage_input_hash=input_hash,
                completion=lambda **kwargs: provider(stage, **kwargs),
            )

    def search(query: str, *, limit: int) -> list[AcademicPaper]:
        search_calls.append(query)
        if len(search_calls) <= 4:
            return broad_papers[:limit]
        lowered = query.casefold()
        if "bounded oscillations" in lowered or "normalized transitions" in lowered:
            return repaired_direct[:limit]
        if "phase transitions" in lowered:
            return repository_direct[:limit]
        if "formal definition" in lowered:
            return method_papers[:limit]
        if "drift mechanism" in lowered:
            return mechanism_papers[:limit]
        if "limitations" in lowered:
            return counter_papers[:limit]
        raise AssertionError(query)

    root = tmp_path / "bounded-gap-repair"
    kwargs = {
        "parent_direction": "合成阵列为何呈现有序响应？",
        "direction_input_hash": "2" * 64,
        "root": root,
        "context_runtime": EscrowContextRuntime(),
        "memory_bridge": None,
        "memory_stages": {},
        "config_path": tmp_path / "config.yaml",
        "env_path": tmp_path / ".env",
        "timeout_seconds": 30,
        "max_results_per_search": 10,
        "retrieval_max_tokens": 768,
        "shared_searchers": {"openalex": search},
        "shared_status_verifier": None,
        "literature_runner": loop_cli.retrieve_contest_direction_literature,
        "focus_selection_runner": loop_cli.run_contest_direction_focus_selection,
        "targeted_retrieval_runner": loop_cli.run_contest_direction_targeted_retrieval,
        "merged_literature_builder": loop_cli.merge_contest_direction_literature,
    }
    fresh = loop_cli._prepare_two_stage_literature(**kwargs, resume=False)

    assert fresh.r1_planning_coverage is not None
    assert fresh.r1_planning_coverage.passed is False
    assert fresh.r1_planning_coverage.eligible_role_family_counts.direct_core == 0
    assert fresh.gap_diagnosis is not None
    assert tuple(item.value for item in fresh.gap_diagnosis.repairable_roles) == ("direct_core",)
    assert fresh.gap_response is not None and fresh.gap_response.model_calls == 1
    assert fresh.gap_retrieval is not None and fresh.gap_retrieval.fetch_pair_count == 1
    assert fresh.merged.schema_version == "contest-direction-layered-literature-v1"
    assert fresh.planning_coverage.passed is True
    assert fresh.planning_coverage.method_focus_basis_queries == (
        fresh.r1_planning_coverage.method_focus_basis_queries
    )
    assert fresh.planning_lock_payload["gap_repair_chain"]["repair_round_count"] == 1
    assert provider_calls.count("planning-literature-gap-repair-query") == 1
    assert len(search_calls) == 9
    assert (
        loop_cli.provider_checkpoint_count(
            root,
            stage_name="planning-literature-gap-repair-query",
        )
        == 1
    )
    assert (root / "literature" / "planning-literature-coverage-r1.json").is_file()
    assert (root / "literature" / "planning-literature-coverage-r2.json").is_file()
    assert (root / "literature" / "layered-literature.json").is_file()

    completed = loop_cli._load_completed_two_stage_literature(root)
    assert completed.planning_lock_payload == fresh.planning_lock_payload
    assert completed.merged == fresh.merged

    provider_calls.clear()
    search_calls.clear()
    resumed = loop_cli._prepare_two_stage_literature(
        **{
            **kwargs,
            "memory_stages": {},
            "shared_searchers": {
                "openalex": lambda _query, *, limit: pytest.fail(  # noqa: ARG005
                    "resume must not call a literature source"
                )
            },
        },
        resume=True,
    )
    assert resumed.merged == fresh.merged
    assert resumed.planning_lock_payload == fresh.planning_lock_payload
    assert provider_calls == []
    assert search_calls == []


def test_partial_focus_inner_receipt_resumes_without_double_charge_and_promotes_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability_payload: dict[str, Any] = {
        "schema_version": "official-model-capability-v1",
        "provider": "qwen-dashscope",
        "model_name": "qwen3.7-max",
        "official_source_url": "https://help.aliyun.com/zh/model-studio/qwen3-7-max",
        "official_source_last_modified": "2026-08-03T15:41:58+08:00",
        "fetched_at": "2026-08-13T00:00:00Z",
        "source_sha256": "a" * 64,
        "source_size_bytes": 1,
        "parser_version": "aliyun-model-page-v1",
        "context_window_tokens": 100_000,
        "maximum_input_tokens": 99_000,
        "maximum_output_tokens": 20_000,
        "maximum_input_tokens_thinking": 98_000,
        "maximum_output_tokens_thinking": 20_000,
        "maximum_reasoning_tokens": 20_000,
    }
    capability_payload["capability_hash"] = canonical_sha256(capability_payload)
    capability = OfficialModelCapability.model_validate(capability_payload)
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )

    paper_titles = (
        "Residue transitions in consecutive prime gaps",
        "Permutation entropy for ordered prime spacings",
        "Finite interval heterogeneity in prime-gap statistics",
        "Wheel constraints on neighboring prime differences",
        "Block resampling for arithmetic point processes",
        "Counterevidence to stationary local prime spacing models",
    )
    papers = [
        AcademicPaper(
            title=paper_titles[index - 1],
            authors=[f"Evidence Author {index}"],
            abstract=(
                "Consecutive prime gaps, residue paths, ordinal entropy, conditional "
                f"permutation nulls and finite-interval uncertainty, family {index}."
            ),
            publication_date=date(2020 + index, 1, 1),
            doi=f"10.1000/focus-crash.{index}",
            url=f"https://example.org/focus-crash-{index}",
            citation_count=index * 5,
            source="openalex",
        )
        for index in range(1, 7)
    ]
    broad = retrieve_contest_direction_literature(
        direction=_DIRECTION,
        requirements=loop_cli._LOOP_REQUIREMENTS,
        selected_method_skills={},
        searchers={"openalex": lambda _query, *, limit: papers[:limit]},
        retrieved_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        llm_call=lambda **_: LLMJsonCompletionResult(
            provider="test",
            base_url="https://provider.example/v1",
            model_name="test-model",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=json.dumps({"queries": list(_V4_BROAD_QUERY_PLAN)}),
            parsed_json={"queries": list(_V4_BROAD_QUERY_PLAN)},
            temperature=0.2,
        ),
    )
    brainstorm_marker = "ABORTED_BRAINSTORM_RESPONSE_ONLY_MARKER"
    brainstorm = {
        "brainstorm_only_marker": brainstorm_marker,
        "candidates": [
            {
                "title_cn": "残基条件化后的顺序结构",
                "focused_direction_cn": (
                    "检验连续素数间隙在残基路径条件化后是否仍保留信息论顺序结构。"
                ),
                "problem_gap_cn": "宽检索尚未区分模约束与额外顺序依赖。",
                "falsifiable_objective_cn": "条件零模型下差异消失则否定额外结构。",
                "evidence_rationale_cn": "宽检索证据支持间隙、残基与熵的联合核对。",
                "nearest_work_queries": ["prime gap residue nearest work"],
                "methods_baselines_queries": ["prime gap conditional permutation"],
                "counterevidence_queries": ["prime gap entropy null result"],
                "evidence_indices": [1, 2],
                "pilot_adapter_id": "prime-gap-information-theory-v1",
                "pilot_feasibility_cn": "注册pilot可执行冻结有限区间比较。",
            },
            {
                "title_cn": "解析边界替代方向",
                "focused_direction_cn": "研究素数计数误差项的解析边界与反例。",
                "problem_gap_cn": "有限计算证据不能直接给出解析证明。",
                "falsifiable_objective_cn": "构造反例即可否定候选统一边界。",
                "evidence_rationale_cn": "宽检索提示应独立核对解析替代解释。",
                "nearest_work_queries": ["prime counting analytic bound"],
                "methods_baselines_queries": ["analytic number theory method"],
                "counterevidence_queries": ["prime counting counterexample"],
                "evidence_indices": [2],
                "pilot_adapter_id": "no_adapter",
                "pilot_feasibility_cn": "当前没有可执行解析证明适配器。",
            },
        ],
    }
    selection_marker = "RESUMED_SELECTION_PROMOTED_MARKER"
    selection = {
        "selected_candidate_number": 1,
        "selection_rationale_cn": (
            f"{selection_marker}：方向可证伪且有真实低成本pilot，创新仍待定向检索。"
        ),
    }
    provider_events: list[str] = []
    delivered_probe: list[str] = []
    mode = "interrupted"
    interrupted_calls = 0

    def provider(**kwargs: Any) -> LLMJsonCompletionResult:
        nonlocal interrupted_calls
        rendered = json.dumps(kwargs["messages"], ensure_ascii=False)
        if mode == "probe":
            provider_events.append("probe")
            delivered_probe.append(rendered)
            payload: dict[str, Any] = {"result": "context probe complete"}
        elif mode == "resumed":
            provider_events.append("selection-resumed")
            payload = selection
        else:
            interrupted_calls += 1
            if interrupted_calls == 1:
                provider_events.append("brainstorm")
                payload = brainstorm
            else:
                provider_events.append("selection-failed")
                raise TimeoutError("simulated focus selection interruption")
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={"prompt_tokens": 20, "completion_tokens": 8},
            temperature=0.2,
        )

    root = tmp_path / "run"
    refinement_root = root / "literature" / "refinement"
    stage_input_hash = canonical_model_hash(
        {
            "literature_protocol": loop_cli._LITERATURE_PROTOCOL,
            "broad_literature_artifact_hash": broad.artifact_hash,
            "broad_literature_catalog_hash": broad.literature_catalog_hash,
            "executable_adapter_capabilities": [loop_cli._ADAPTER_DESCRIPTOR],
        }
    )
    runtime = ContestDirectionContextRuntime(
        direction_id="direction-loop-focus-crash",
        output_dir=root / "context-memory",
        vault_root=tmp_path / "vault",
        completion=provider,
        capability_cache_dir=tmp_path / "capability-cache",
    )
    with (
        pytest.raises(TimeoutError, match="selection interruption"),
        runtime.checkpointed_stage(
            "focus-selection",
            input_hash=stage_input_hash,
            checkpoint_root=root,
        ) as completion,
    ):
        run_contest_direction_focus_selection(
            direction=broad.direction,
            broad_literature=broad,
            output_dir=refinement_root,
            requirements=loop_cli._LOOP_REQUIREMENTS,
            executable_adapter_capabilities=(loop_cli._ADAPTER_DESCRIPTOR,),
            completion=completion,
        )

    brainstorm_receipt = refinement_root / "direction-focus-brainstorm-response.json"
    brainstorm_bytes = brainstorm_receipt.read_bytes()
    assert provider_events == ["brainstorm", "selection-failed"]
    assert brainstorm_receipt.is_file()
    assert not (refinement_root / "direction-focus-selection-response.json").exists()
    assert loop_cli.provider_checkpoint_count(root, stage_name="focus-selection") == 1
    assert not list((root / "context-memory" / "completed-tasks").glob("*.json"))

    mode = "resumed"
    with runtime.checkpointed_stage(
        "focus-selection",
        input_hash=stage_input_hash,
        checkpoint_root=root,
    ) as completion:
        focus = run_contest_direction_focus_selection(
            direction=broad.direction,
            broad_literature=broad,
            output_dir=refinement_root,
            requirements=loop_cli._LOOP_REQUIREMENTS,
            executable_adapter_capabilities=(loop_cli._ADAPTER_DESCRIPTOR,),
            completion=completion,
        )

    assert focus.selected_candidate_number == 1
    assert brainstorm_receipt.read_bytes() == brainstorm_bytes
    assert provider_events == ["brainstorm", "selection-failed", "selection-resumed"]
    assert loop_cli.provider_checkpoint_count(root, stage_name="focus-selection") == 2
    assert (
        loop_cli.provider_checkpoint_count(refinement_root, stage_name="direction-focus-brainstorm")
        == 0
    )
    assert (
        loop_cli.provider_checkpoint_count(refinement_root, stage_name="direction-focus-selection")
        == 0
    )
    completed = list((root / "context-memory" / "completed-tasks").glob("*.json"))
    assert len(completed) == 1
    completed_payload = json.loads(completed[0].read_text(encoding="utf-8"))
    assert completed_payload["task_group_id"].startswith("focus-selection-")
    assert selection_marker in completed_payload["response_text"]
    assert brainstorm_marker not in completed_payload["response_text"]

    mode = "probe"
    with runtime.stage("after-focus-probe", input_hash="f" * 64) as completion:
        completion(
            messages=[{"role": "user", "content": "AFTER_FOCUS_CONTEXT_PROBE"}],
            config_path=tmp_path / "missing.yaml",
            max_tokens=64,
        )
    assert len(delivered_probe) == 1
    assert selection_marker in delivered_probe[0]
    assert brainstorm_marker not in delivered_probe[0]
    raw_records = list(
        (tmp_path / "vault" / "_private" / "raw-memory").glob("**/records/**/*.json")
    )
    assert len(raw_records) == 3


def test_legacy_v1_resume_is_rejected_before_model_or_api(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    payload: dict[str, Any] = {
        "schema_version": "contest-direction-research-loop-input-v1",
        "input_mode": "specified_direction",
        "direction": _DIRECTION,
        "requirements": list(loop_cli._LOOP_REQUIREMENTS),
        "preexperiment_policy": "required",
    }
    payload["input_hash"] = canonical_model_hash(payload)
    payload["direction_id"] = f"direction-loop-{payload['input_hash'][:20]}"
    _write_json(root / "direction-input.json", payload)

    with pytest.raises(ContestDirectionResearchLoopError, match="legacy.*fresh run"):
        run_contest_direction_research_loop(
            direction=_DIRECTION,
            output_dir=root,
            resume_existing=True,
        )


def test_legacy_v2_literature_protocol_resume_is_rejected_explicitly(tmp_path: Path) -> None:
    direction = "通用可验证研究方向"
    root = tmp_path / "legacy-literature-protocol"
    payload: dict[str, Any] = {
        "schema_version": loop_cli._INPUT_SCHEMA,
        "input_mode": "specified_direction",
        "direction": direction,
        "literature_protocol": "two_stage_literature_v2",
        "requirements": list(loop_cli._LOOP_REQUIREMENTS),
        "preexperiment_policy": "required",
    }
    payload["input_hash"] = canonical_model_hash(payload)
    payload["direction_id"] = f"direction-loop-{payload['input_hash'][:20]}"
    _write_json(root / "direction-input.json", payload)

    with pytest.raises(
        ContestDirectionResearchLoopError,
        match="legacy literature protocol.*fresh run",
    ):
        run_contest_direction_research_loop(
            direction=direction,
            output_dir=root,
            resume_existing=True,
        )


def test_adapter_requires_focused_prime_gap_information_direction() -> None:
    batch_direction = (
        "素数为何如此特别？\n"
        "原始英文问题：What makes prime numbers so special?\n"
        "来源：《125 Questions: Exploration and Discovery》第1题（数学科学）。"
    )

    assert not loop_cli._direction_fits_prime_gap_adapter(batch_direction)
    assert not loop_cli._direction_fits_prime_gap_adapter("What makes prime numbers so special?")
    assert loop_cli._direction_fits_prime_gap_adapter(_DIRECTION)
    assert not loop_cli._direction_fits_prime_gap_adapter("研究素数判定算法的复杂度")
    assert not loop_cli._direction_fits_prime_gap_adapter("素数判定算法为何高效？")
    assert not loop_cli._direction_fits_prime_gap_adapter("蛋白质中的素数间隙编码与信息熵")
    assert not loop_cli._direction_fits_prime_gap_adapter(
        "What makes prime numbers so special? Study protein gap entropy."
    )
    assert not loop_cli._direction_fits_prime_gap_adapter(
        "以素数签名的ℓ∞度量诱导相邻素数间隙，并研究其排列熵"
    )


def test_focus_and_hypothesis_semantic_contradiction_cannot_execute_adapter() -> None:
    candidate = {
        "candidate_id": "candidate-ordinary-gap",
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "metric": "tie_aware_normalized_permutation_entropy_m5",
        "null_models": ["residue_path_conditioned_permutation"],
        "hypothesis_cn": "普通连续素数间隙可能保留高阶顺序信号。",
    }
    incompatible_focus = "以素数签名的ℓ∞距离诱导间隙，并分析排列熵"

    assert loop_cli._candidate_fits_prime_gap_adapter(candidate)
    assert not loop_cli._candidate_fits_prime_gap_adapter(candidate, direction=incompatible_focus)
    assert (
        loop_cli._select_executable_candidate(
            SimpleNamespace(candidates=(candidate,)),
            direction=incompatible_focus,
            selected_skill_ids=("prime-structure-computational-number-theory",),
        )
        is None
    )


def test_broad_q001_cannot_bypass_focused_direction_adapter_gate() -> None:
    direction = "What makes prime numbers so special?"
    base = {
        "candidate_id": "candidate-1",
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "metric": "tie_aware_normalized_permutation_entropy_m5",
        "null_models": ["residue_path_conditioned_permutation"],
    }
    hypotheses = SimpleNamespace(candidates=(base,))

    assert (
        loop_cli._select_executable_candidate(
            hypotheses, direction=direction, selected_skill_ids=()
        )
        is None
    )
    assert (
        loop_cli._select_executable_candidate(
            SimpleNamespace(candidates=({**base, "observable": "protein_gap_encoding"},)),
            direction=direction,
            selected_skill_ids=("prime-structure-computational-number-theory",),
        )
        is None
    )
    assert (
        loop_cli._select_executable_candidate(
            hypotheses,
            direction=direction,
            selected_skill_ids=("prime-structure-computational-number-theory",),
        )
        is None
    )
    assert (
        loop_cli._select_executable_candidate(
            hypotheses,
            direction="研究素数判定算法的复杂度",
            selected_skill_ids=("prime-structure-computational-number-theory",),
        )
        is None
    )


def test_legacy_q001_adapter_receipt_is_not_reassessed_into_support(tmp_path: Path) -> None:
    direction = loop_cli._SCIENCE125_Q001_BATCH_DIRECTION
    candidate = {
        "candidate_id": "candidate-1",
        "adapter_id": "prime-gap-information-theory-v1",
        "scientific_object": "consecutive_integer_primes",
        "observable": "ordered_consecutive_prime_gaps",
        "metric": "tie_aware_normalized_permutation_entropy_m5",
        "null_models": ["residue_path_conditioned_permutation"],
    }
    literature = SimpleNamespace(artifact_hash="1" * 64)
    routing = SimpleNamespace(
        artifact_hash="2" * 64,
        selected_skill_ids=("prime-structure-computational-number-theory",),
    )
    hypotheses = SimpleNamespace(artifact_hash="3" * 64, candidates=(candidate,))
    original_payload = loop_cli._adapter_selection_payload(
        direction=direction,
        routing=routing,
        literature=literature,
        hypotheses=hypotheses,
        selected_candidate=None,
    )
    # Recreate the pre-fix receipt: exact candidate and Skill passed, only the
    # broad direction classifier reported false.
    original_payload["direction_compatible"] = False
    original_payload["direction_compatibility_basis"] = "incompatible"
    original_payload["artifact_hash"] = canonical_model_hash(
        {key: value for key, value in original_payload.items() if key != "artifact_hash"}
    )
    original_path = tmp_path / "preexperiment-adapter-selection.json"
    _write_json(original_path, original_payload)
    original_bytes = original_path.read_bytes()

    with pytest.raises(ContestDirectionResearchLoopError, match="binding mismatch"):
        loop_cli._resume_adapter_selection(
            root=tmp_path,
            direction=direction,
            routing=routing,
            literature=literature,
            hypotheses=hypotheses,
            selected_candidate=candidate,
        )
    assert original_path.read_bytes() == original_bytes
    assert not (tmp_path / "preexperiment-adapter-selection-reassessment.json").exists()


def test_required_policy_writes_blocked_receipt_when_no_adapter(tmp_path: Path) -> None:
    root = tmp_path / "blocked"
    root.mkdir()
    files = []
    for name in (
        "direction-input.json",
        "literature.json",
        "routing.json",
        "skills.json",
        "hypotheses.json",
        "adapter.json",
    ):
        path = root / name
        _write_json(path, {"name": name})
        files.append(path)
    literature = SimpleNamespace(query_model_calls=1, artifact_hash="1" * 64)
    routing = SimpleNamespace(model_calls=1)
    hypotheses = SimpleNamespace(model_call_count=3)
    finalist_status_path = root / "finalist-status.json"
    finalist_status_payload = loop_cli._write_finalist_status_verification(
        finalist_status_path,
        records=(),
    )

    with pytest.raises(ContestDirectionResearchLoopError, match="blocked receipt"):
        loop_cli._finish_without_adapter(
            root=root,
            policy="required",
            direction=_DIRECTION,
            source_accounting=None,
            direction_input_path=files[0],
            literature_path=files[1],
            finalist_status_path=finalist_status_path,
            finalist_status_payload=finalist_status_payload,
            routing_path=files[2],
            skill_manifest_path=files[3],
            hypothesis_path=files[4],
            adapter_receipt_path=files[5],
            routing=routing,
            literature=literature,
            hypotheses=hypotheses,
        )

    payload = json.loads((root / "blocked-receipt.json").read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_no_compatible_real_preexperiment_adapter"
    assert payload["preexperiment_executed"] is False


@pytest.mark.parametrize(
    ("policy", "expected_status", "report_name"),
    (
        (
            "required",
            "blocked_no_compatible_real_preexperiment_adapter",
            "blocked-receipt.json",
        ),
        (
            "if_supported",
            "completed_without_preexperiment_no_compatible_adapter",
            "delivery-report.json",
        ),
    ),
)
def test_one_repair_no_adapter_terminal_accounts_gap_and_binds_complete_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
    expected_status: str,
    report_name: str,
) -> None:
    root = tmp_path / policy
    root.mkdir()

    def artifact(name: str) -> Path:
        path = root / name
        _write_json(path, {"name": name})
        return path

    paths = {
        name: artifact(name)
        for name in (
            "direction-input.json",
            "broad.json",
            "focus.json",
            "targeted.json",
            "targeted-binding.json",
            "base-merged.json",
            "layered.json",
            "planning-lock.json",
            "coverage-r1.json",
            "coverage-r2.json",
            "coverage-final.json",
            "gap-diagnosis.json",
            "gap-response.json",
            "gap-projection.json",
            "gap-retrieval.json",
            "skill-routing.json",
            "selected-method-skills.json",
            "hypothesis-stage/direction-hypothesis-brainstorm.json",
            "preexperiment-adapter-selection.json",
        )
    }
    parent_direction = "合成母问题"
    focused_direction = "合成方向"
    direction_payload: dict[str, Any] = {
        "schema_version": "contest-direction-research-loop-input-v2",
        "input_mode": "specified_direction",
        "direction": parent_direction,
        "literature_protocol": "two_stage_literature_v5",
        "requirements": ["合成的题目中立要求"],
        "preexperiment_policy": policy,
        "source_accounting_protocol": "physical-source-http-attempt-ledger-v1",
    }
    direction_payload["input_hash"] = canonical_model_hash(direction_payload)
    direction_payload["direction_id"] = f"direction-loop-{direction_payload['input_hash'][:20]}"
    _write_json(paths["direction-input.json"], direction_payload)
    finalist_path = root / "finalist-status.json"
    finalist_payload = loop_cli._write_finalist_status_verification(
        finalist_path,
        records=(),
    )
    base = SimpleNamespace(artifact_hash="1" * 64)
    layered = SimpleNamespace(
        artifact_hash="2" * 64,
        retrieval_semantics="layered_base_plus_bounded_gap_repair",
    )
    state = SimpleNamespace(
        broad=SimpleNamespace(query_model_calls=1, artifact_hash="3" * 64),
        broad_path=paths["broad.json"],
        focus=SimpleNamespace(
            model_call_count_at_creation=2,
            artifact_hash="4" * 64,
            selected_focus_id="synthetic-focus",
            focused_direction_cn=focused_direction,
        ),
        focus_path=paths["focus.json"],
        targeted=SimpleNamespace(query_model_calls=1, artifact_hash="5" * 64),
        targeted_path=paths["targeted.json"],
        targeted_binding=SimpleNamespace(artifact_hash="6" * 64),
        targeted_binding_path=paths["targeted-binding.json"],
        base_merged=base,
        base_merged_path=paths["base-merged.json"],
        merged=layered,
        merged_path=paths["layered.json"],
        planning_lock_path=paths["planning-lock.json"],
        planning_lock_payload={"artifact_hash": "d" * 64},
        planning_catalog=({"record_id": "synthetic-record"},),
        finalist_status_path=finalist_path,
        finalist_status_payload=finalist_payload,
        r1_planning_coverage=SimpleNamespace(receipt_hash="7" * 64),
        r1_planning_coverage_path=paths["coverage-r1.json"],
        r2_planning_coverage=SimpleNamespace(receipt_hash="e" * 64),
        r2_planning_coverage_path=paths["coverage-r2.json"],
        planning_coverage=SimpleNamespace(receipt_hash="8" * 64),
        planning_coverage_path=paths["coverage-final.json"],
        gap_diagnosis=SimpleNamespace(diagnosis_hash="9" * 64),
        gap_diagnosis_path=paths["gap-diagnosis.json"],
        gap_response=SimpleNamespace(model_calls=1, receipt_hash="a" * 64),
        gap_response_path=paths["gap-response.json"],
        gap_projection=SimpleNamespace(projection_hash="b" * 64),
        gap_projection_path=paths["gap-projection.json"],
        gap_retrieval=SimpleNamespace(artifact_hash="c" * 64),
        gap_retrieval_path=paths["gap-retrieval.json"],
    )
    routing = SimpleNamespace(
        model_calls=1,
        artifact_hash="f" * 64,
        selected_skill_ids=(),
    )
    hypotheses = SimpleNamespace(
        model_call_count=3,
        artifact_hash="0" * 64,
        direction=focused_direction,
        candidates=(),
    )
    adapter_receipt = loop_cli._adapter_selection_payload(
        direction=focused_direction,
        routing=routing,
        literature=layered,
        hypotheses=hypotheses,
        selected_candidate=None,
    )
    _write_json(paths["preexperiment-adapter-selection.json"], adapter_receipt)
    physical_attempts = {
        **{stage: 0 for stage in loop_cli._OUTER_MODEL_STAGES},
        "broad-literature-query": 1,
        "focus-selection": 2,
        "targeted-literature-query": 1,
        "planning-literature-gap-repair-query": 2,
        "skill-routing": 1,
        "hypothesis-brainstorm": 3,
    }

    def provider_accounting(_root: Path, *, stage_name: str) -> dict[str, int]:
        attempts = physical_attempts[stage_name]
        transport_failures = 1 if stage_name == "planning-literature-gap-repair-query" else 0
        return {
            "attempt_count": attempts,
            "completed_count": attempts - transport_failures,
            "parse_failed_count": 0,
            "transport_failed_count": transport_failures,
            "terminal_failed_count": 0,
            "outcome_unknown_count": 0,
        }

    monkeypatch.setattr(loop_cli, "provider_checkpoint_accounting", provider_accounting)

    def finish() -> dict[str, Any]:
        return loop_cli._finish_without_adapter(
            root=root,
            policy=policy,
            direction=focused_direction,
            parent_direction=parent_direction,
            source_accounting=None,
            direction_input_path=paths["direction-input.json"],
            literature_path=paths["layered.json"],
            finalist_status_path=finalist_path,
            finalist_status_payload=finalist_payload,
            routing_path=paths["skill-routing.json"],
            skill_manifest_path=paths["selected-method-skills.json"],
            hypothesis_path=paths["hypothesis-stage/direction-hypothesis-brainstorm.json"],
            adapter_receipt_path=paths["preexperiment-adapter-selection.json"],
            routing=routing,
            literature=layered,
            literature_state=state,
            hypotheses=hypotheses,
        )

    if policy == "required":
        with pytest.raises(ContestDirectionResearchLoopError, match="blocked receipt"):
            finish()
    else:
        finish()
    report = json.loads((root / report_name).read_text(encoding="utf-8"))

    assert report["status"] == expected_status
    assert report["source_accounting"]["checkpoint_status"] == ("verified_local_checkpoints")
    assert (
        report["source_accounting"]["physical_http_attempts"]["accounting_status"]
        == "verified_current_protocol"
    )
    accounting = report["model_call_accounting"]
    assert accounting["planning_literature_gap_repair_calls"] == 1
    assert accounting["retrieval_query_calls"] == 5
    assert accounting["this_loop_observed_provider_request_attempts"] == 9
    assert accounting["total_provenance_provider_request_attempts"] == 9
    assert accounting["physical_provider_attempt_total"] == 10
    assert accounting["physical_provider_attempts_by_stage"] == physical_attempts
    assert accounting["provider_checkpoint_accounting_by_stage"][
        "planning-literature-gap-repair-query"
    ] == {
        "attempt_count": 2,
        "completed_count": 1,
        "parse_failed_count": 0,
        "transport_failed_count": 1,
        "terminal_failed_count": 0,
        "outcome_unknown_count": 0,
    }
    assert accounting["physical_provider_attempt_semantics"] == (
        "lifetime_durable_attempt_reservations_deduplicated_by_canonical_stage_owner"
    )
    assert accounting["legacy_provider_request_attempt_fields_semantics"] == (
        "logical_scientific_model_calls_v1_compatibility"
    )
    artifacts = report["artifacts"]
    assert {
        "base_merged_literature",
        "effective_merged_literature",
        "layered_literature",
        "planning_literature_coverage_r1",
        "planning_literature_coverage_r2",
        "planning_literature_coverage",
        "planning_literature_gap_diagnosis",
        "planning_literature_gap_query_response",
        "planning_literature_gap_query_projection",
        "planning_literature_gap_retrieval",
    }.issubset(artifacts)
    monkeypatch.setattr(loop_cli, "_load_completed_two_stage_literature", lambda _root: state)
    monkeypatch.setattr(loop_cli, "load_contest_direct_skill_routing", lambda _path: routing)
    import autoresearch.competition.contest_direction_hypothesis_stage as hypothesis_module

    monkeypatch.setattr(
        hypothesis_module,
        "load_contest_direction_hypothesis_brainstorm",
        lambda *_args, **_kwargs: hypotheses,
    )
    monkeypatch.setattr(
        loop_cli,
        "ContestDirectionContextRuntime",
        lambda **_kwargs: pytest.fail("terminal resume must not initialize model context"),
    )
    if policy == "required":
        with pytest.raises(ContestDirectionResearchLoopError, match="remains blocked"):
            run_contest_direction_research_loop(
                direction=parent_direction,
                output_dir=root,
                resume_existing=True,
                preexperiment_policy="required",
            )
    else:
        direct_replay = run_contest_direction_research_loop(
            direction=parent_direction,
            output_dir=root,
            resume_existing=True,
            preexperiment_policy="if_supported",
        )
        assert direct_replay["resume_action"] == "already_complete_no_model_call"
        assert direct_replay["model_call_accounting"] == accounting
        report_path = root / report_name
        original_report = report_path.read_bytes()
        downgraded = json.loads(original_report)
        downgraded.pop("source_accounting")
        downgraded["report_hash"] = canonical_model_hash(
            {key: value for key, value in downgraded.items() if key != "report_hash"}
        )
        _write_json(report_path, downgraded)
        with pytest.raises(ContestDirectionResearchLoopError, match="source-accounting"):
            run_contest_direction_research_loop(
                direction=parent_direction,
                output_dir=root,
                resume_existing=True,
                preexperiment_policy="if_supported",
            )
        report_path.write_bytes(original_report)
        tampered = json.loads(original_report)
        tampered["model_call_accounting"]["physical_provider_attempt_total"] += 1
        tampered["report_hash"] = canonical_model_hash(
            {key: value for key, value in tampered.items() if key != "report_hash"}
        )
        _write_json(report_path, tampered)
        with pytest.raises(ContestDirectionResearchLoopError, match="model-call accounting"):
            run_contest_direction_research_loop(
                direction=parent_direction,
                output_dir=root,
                resume_existing=True,
                preexperiment_policy="if_supported",
            )
        report_path.write_bytes(original_report)

        legacy = json.loads(original_report)
        for key in (
            "physical_provider_attempt_total",
            "physical_provider_attempts_by_stage",
            "provider_checkpoint_accounting_by_stage",
            "physical_provider_attempt_semantics",
            "legacy_provider_request_attempt_fields_semantics",
        ):
            legacy["model_call_accounting"].pop(key)
        legacy["report_hash"] = canonical_model_hash(
            {key: value for key, value in legacy.items() if key != "report_hash"}
        )
        _write_json(report_path, legacy)
        legacy_replay = run_contest_direction_research_loop(
            direction=parent_direction,
            output_dir=root,
            resume_existing=True,
            preexperiment_policy="if_supported",
        )
        assert legacy_replay["resume_action"] == "already_complete_no_model_call"
        assert "physical_provider_attempt_total" not in legacy_replay["model_call_accounting"]
    if policy == "if_supported":
        from autoresearch.competition.science125_batch import (
            _load_unsupported_direction_delivery,
        )

        replayed = _load_unsupported_direction_delivery(root)
        assert replayed is not None
        assert replayed["model_call_accounting"] == legacy["model_call_accounting"]


def test_cli_exposes_source_and_policy() -> None:
    parser = loop_cli._parser()
    help_text = parser.format_help()
    args = parser.parse_args(["--direction", _DIRECTION])

    assert "--source-direction-delivery" in help_text
    assert "--preexperiment-policy" in help_text
    assert "每条查询在每个数据源的一次 API 请求" in help_text
    assert "不增加查询数×数据源数的请求次数" in help_text
    assert args.max_results_per_search == 20


def test_skill_reasoning_subset_is_complementary_not_a_planning_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (
        {
            "record_id": "subject-background-1",
            "title": "Cramer model for prime gaps",
            "abstract": "Prime gap asymptotics and probabilistic foundations.",
            "source_stages": ["targeted_direction"],
        },
        {
            "record_id": "subject-background-2",
            "title": "Large gaps between primes",
            "abstract": "Prime gap bounds and asymptotic density.",
            "source_stages": ["targeted_direction"],
        },
        {
            "record_id": "method-background-1",
            "title": "Permutation entropy in EEG",
            "abstract": "Ordinal pattern entropy for biomedical time series.",
            "source_stages": ["targeted_direction"],
        },
        {
            "record_id": "method-background-2",
            "title": "Surrogate null models for signals",
            "abstract": "Null model and block permutation tests for time series.",
            "source_stages": ["targeted_direction"],
        },
        {
            "record_id": "generic-background",
            "title": "Introduction to number theory",
            "abstract": "A general introduction to prime numbers.",
            "source_stages": ["broad_direction"],
        },
        {
            "record_id": "lucas-lacasa-direct-method",
            "title": "On a dynamical approach to some prime number sequences",
            "abstract": (
                "Symbolic dynamics, Renyi entropy, forbidden block patterns and null models "
                "for prime gap residue sequences."
            ),
            "source_stages": ["targeted_direction"],
        },
    )

    def bounded_context(_literature: Any, *, record_ids: Any) -> Any:
        ids = tuple(record_ids)
        if len(ids) > 3:
            raise ValueError("literature evidence exceeds the 14 KiB UTF-8 routing budget")
        return SimpleNamespace(record_ids=ids)

    monkeypatch.setattr(
        loop_cli,
        "ContestDirectLiteratureEvidenceContext",
        SimpleNamespace(from_two_stage_artifact=bounded_context),
    )
    context = loop_cli._skill_routing_two_stage_literature_evidence(
        SimpleNamespace(),
        catalog,
        queries=("prime gap entropy symbolic dynamics null model",),
        priority_queries=("prime gap residue", "entropy null model prime gaps"),
        priority_query_groups=(
            ("prime gap residue structure",),
            ("symbolic dynamics entropy null model prime gaps",),
        ),
    )

    assert len(context.record_ids) == 3
    assert len(set(context.record_ids)) == 3
    assert "lucas-lacasa-direct-method" in context.record_ids
    assert context.record_ids != tuple(item["record_id"] for item in catalog[:3])


def test_finalist_status_receipt_replay_excludes_withdrawn_and_never_calls_network(
    tmp_path: Path,
) -> None:
    eligible = (
        {
            "record_id": "withdrawn",
            "title": "Prime gaps information theory",
            "abstract": "Prime gaps information theory entropy.",
            "source_url": "https://arxiv.org/abs/2110.15271",
            "retrieved_from": "arxiv",
            "retrieved_at": "2026-08-12T00:00:00+00:00",
            "publication_status": "preprint",
        },
        {
            "record_id": "replacement",
            "title": "Prime gaps residue classes",
            "abstract": "Prime gaps residue classes and null models.",
            "source_url": "https://example.org/replacement",
            "retrieved_from": "openalex",
            "retrieved_at": "2026-08-12T00:00:00+00:00",
            "publication_status": "published",
        },
    )
    contexts = ("withdrawn context", "replacement context")
    status_calls: list[str] = []

    def verify_withdrawn(paper: Any) -> Any:
        status_calls.append(str(paper.url))
        return paper.model_copy(
            update={
                "publication_status": "withdrawn",
                "status_source": "arxiv_abs",
            }
        )

    fresh_catalog, fresh_context, verification_records = (
        loop_cli._select_planning_literature_with_status(
            eligible,
            contexts,
            queries=("prime gaps information theory residue classes",),
            arxiv_status_verifier=verify_withdrawn,
        )
    )
    assert [item["record_id"] for item in fresh_catalog] == ["replacement"]
    assert fresh_context == ("replacement context",)
    assert status_calls == ["https://arxiv.org/abs/2110.15271"]

    receipt_path = tmp_path / "finalist-status-verification.json"
    loop_cli._write_finalist_status_verification(
        receipt_path,
        records=verification_records,
    )

    receipt = loop_cli._load_finalist_status_verification(receipt_path)
    replay_catalog, replay_context = loop_cli._apply_finalist_status_verification(
        eligible,
        contexts,
        receipt,
    )
    selected, selected_context = loop_cli._select_planning_literature(
        replay_catalog,
        replay_context,
        queries=("prime gaps information theory residue classes",),
    )

    assert [item["record_id"] for item in selected] == ["replacement"]
    assert selected_context == ("replacement context",)
    assert receipt["verification_count"] == 1
    assert status_calls == ["https://arxiv.org/abs/2110.15271"]


def test_finalist_status_receipt_replays_dual_identifier_catalog_url(tmp_path: Path) -> None:
    catalog_url = "https://doi.org/10.1000/dual-identifier"
    eligible = (
        {
            "record_id": "dual-identifier",
            "title": "A published dual-identifier method paper",
            "abstract": "A synthetic method record used to test replay identity.",
            "source_url": catalog_url,
            "url": catalog_url,
            "repository_doi": "10.48550/arxiv.2401.01234",
            "retrieved_from": "openalex",
            "retrieved_at": "2026-08-15T00:00:00+00:00",
            "publication_status": "published",
        },
    )
    verified, context, status = loop_cli._verify_arxiv_finalist(
        dict(eligible[0]),
        "synthetic context",
        verifier=lambda _paper: pytest.fail("published OpenAlex record must not be verified"),
    )
    assert verified == eligible[0]
    receipt_path = tmp_path / "finalist-status-verification.json"
    loop_cli._write_finalist_status_verification(receipt_path, records=(status,))
    receipt = loop_cli._load_finalist_status_verification(receipt_path)

    replay_catalog, replay_context = loop_cli._apply_finalist_status_verification(
        eligible,
        (context,),
        receipt,
    )

    assert replay_catalog == eligible
    assert replay_context == ("synthetic context",)
    assert status["source_url"] == catalog_url


def test_legacy_finalist_status_receipt_accepts_only_record_derived_arxiv_url() -> None:
    catalog_url = "https://doi.org/10.1000/legacy-dual-identifier"
    arxiv_url = "https://arxiv.org/abs/2401.04321"
    eligible = (
        {
            "record_id": "legacy-dual-identifier",
            "title": "A legacy dual-identifier method paper",
            "abstract": "A synthetic method record used to test bounded legacy replay.",
            "source_url": catalog_url,
            "url": catalog_url,
            "repository_doi": "10.48550/arxiv.2401.04321",
            "retrieved_from": "openalex",
            "retrieved_at": "2026-08-15T00:00:00+00:00",
            "publication_status": "published",
        },
    )

    def receipt(source_url: str) -> dict[str, Any]:
        return {
            "records": [
                {
                    "record_id": "legacy-dual-identifier",
                    "source_url": source_url,
                    "original_status": "published",
                    "verification_attempted": False,
                    "verified_status": "published",
                    "status_source": "openalex",
                    "status_as_of": "2026-08-15",
                    "outcome": "not_arxiv_or_verifier_disabled",
                    "error": None,
                }
            ]
        }

    replay_catalog, replay_context = loop_cli._apply_finalist_status_verification(
        eligible,
        ("synthetic context",),
        receipt(arxiv_url),
    )
    assert replay_catalog == eligible
    assert replay_context == ("synthetic context",)

    with pytest.raises(
        ContestDirectionResearchLoopError,
        match="finalist status receipt source URL mismatch",
    ):
        loop_cli._apply_finalist_status_verification(
            eligible,
            ("synthetic context",),
            receipt("https://arxiv.org/abs/9999.99999"),
        )


def test_coverage_deduplicates_work_families_and_refills_a_withdrawn_anchor(
    tmp_path: Path,
) -> None:
    shared_object = '("aurora units" OR "aurora arrays")'
    raw_queries = (
        f'{shared_object} AND ("phase drift" OR "state drift")',
        '("rank pattern" OR "ordinal measure") AND ("formal definition" OR foundation)',
        f'{shared_object} AND ("null mechanism" OR surrogate)',
        f'{shared_object} AND (failure OR "alternative explanation")',
    )
    role_queries = loop_cli._planning_coverage_role_queries(SimpleNamespace(queries=raw_queries))

    def record(
        record_id: str,
        *,
        title: str,
        abstract: str,
        retrieval_queries: tuple[str, ...],
        citation_count: int,
        source_url: str,
        retrieved_from: str,
        publication_status: str,
        authors: tuple[str, ...] = ("A. Author",),
        venue: str = "Synthetic Evidence Journal",
        publication_date: str = "2024-01-01",
    ) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "record_sha256": hashlib.sha256(record_id.encode()).hexdigest(),
            "title": title,
            "authors": list(authors),
            "abstract": abstract,
            "venue": venue,
            "publication_date": publication_date,
            "citation_count": citation_count,
            "citation_count_source": "synthetic-index",
            "citation_count_as_of": "2026-08-14",
            "source_url": source_url,
            "url": source_url,
            "retrieved_from": retrieved_from,
            "retrieved_at": "2026-08-14T00:00:00+00:00",
            "publication_status": publication_status,
            "retrieval_queries": list(retrieval_queries),
            "source_stages": ["targeted_direction"],
        }

    family_metadata = {
        "title": "Aurora units under phase drift",
        "abstract": (
            "Aurora arrays show state drift under a null mechanism; a failure and "
            "alternative explanation are evaluated."
        ),
        "retrieval_queries": (raw_queries[0], raw_queries[2], raw_queries[3]),
        "retrieved_from": "arxiv",
        "publication_status": "preprint",
    }
    catalog = (
        record(
            "family-high",
            citation_count=100,
            source_url="https://arxiv.org/abs/2601.00001",
            **family_metadata,
        ),
        record(
            "family-replacement",
            citation_count=50,
            source_url="https://arxiv.org/abs/2601.00002",
            **family_metadata,
        ),
        record(
            "family-low",
            citation_count=1,
            source_url="https://arxiv.org/abs/2601.00003",
            **family_metadata,
        ),
        record(
            "direct-independent",
            title="State drift in aurora arrays",
            abstract="Aurora units exhibit phase drift in an independent cohort.",
            retrieval_queries=(raw_queries[0],),
            citation_count=20,
            source_url="https://example.org/direct",
            retrieved_from="openalex",
            publication_status="published",
        ),
        record(
            "method-independent",
            title="Formal definition of rank pattern measures for aurora units",
            abstract="A foundation for ordinal measure analysis.",
            retrieval_queries=(raw_queries[1],),
            citation_count=30,
            source_url="https://example.org/method",
            retrieved_from="openalex",
            publication_status="published",
        ),
        record(
            "mechanism-independent",
            title="Aurora units and a null mechanism",
            abstract="Aurora arrays are evaluated with a surrogate null mechanism.",
            retrieval_queries=(raw_queries[2],),
            citation_count=10,
            source_url="https://example.org/mechanism",
            retrieved_from="openalex",
            publication_status="published",
        ),
        record(
            "counter-independent",
            title="Failure of an aurora units explanation",
            abstract="Aurora arrays admit an alternative explanation for the failure.",
            retrieval_queries=(raw_queries[3],),
            citation_count=5,
            source_url="https://example.org/counter",
            retrieved_from="openalex",
            publication_status="published",
        ),
    )
    contexts = tuple(f"context for {item['record_id']}" for item in catalog)
    status_calls: list[str] = []

    def verifier(paper: AcademicPaper) -> AcademicPaper:
        url = str(paper.url)
        status_calls.append(url)
        if url.endswith("00001"):
            status = "withdrawn"
        elif url.endswith("00002"):
            status = "published"
        else:
            pytest.fail(f"a lower-quality duplicate must not consume a status request: {url}")
        return paper.model_copy(
            update={
                "publication_status": status,
                "status_source": "synthetic_status",
                "status_as_of": date(2026, 8, 14),
            }
        )

    selected, selected_context, coverage, status_records = (
        loop_cli._select_planning_literature_with_coverage_and_status(
            catalog,
            contexts,
            role_queries=role_queries,
            arxiv_status_verifier=verifier,
        )
    )

    assert status_calls == [
        "https://arxiv.org/abs/2601.00001",
        "https://arxiv.org/abs/2601.00002",
    ]
    assert "family-high" not in {item["record_id"] for item in selected}
    assert "family-low" not in {item["record_id"] for item in selected}
    assert "family-replacement" in {item["record_id"] for item in selected}
    assert coverage.candidate_count == 6
    assert len(coverage.anchor_assignments) == 5

    status_path = tmp_path / "finalist-status-verification.json"
    status_payload = loop_cli._write_finalist_status_verification(
        status_path,
        records=status_records,
    )
    replay_catalog, replay_context = loop_cli._apply_finalist_status_verification(
        catalog,
        contexts,
        status_payload,
    )
    replay_coverage = loop_cli._coverage_select(
        replay_catalog,
        replay_context,
        role_queries=role_queries,
    )
    replay_selected, replay_selected_context = loop_cli._coverage_selected_subset(
        replay_catalog,
        replay_context,
        replay_coverage,
    )
    assert replay_selected == selected
    assert replay_selected_context == selected_context
    assert replay_coverage == coverage
    assert status_calls == [
        "https://arxiv.org/abs/2601.00001",
        "https://arxiv.org/abs/2601.00002",
    ]

    merged = SimpleNamespace(
        broad_literature_artifact_hash="1" * 64,
        targeted_literature_artifact_hash="2" * 64,
        artifact_hash="3" * 64,
        merged_catalog_hash="4" * 64,
    )
    lock = loop_cli._load_or_write_planning_literature_lock(
        tmp_path / "planning-literature.json",
        merged=merged,
        base_merged=merged,
        focus=SimpleNamespace(
            artifact_hash="5" * 64,
            selected_focus_id="direction-focus-0123456789abcdef",
            focused_direction_cn="Synthetic bounded direction",
        ),
        targeted_binding=SimpleNamespace(artifact_hash="6" * 64),
        candidate_catalog=replay_catalog,
        planning_catalog=replay_selected,
        planning_context=replay_selected_context,
        finalist_status_payload=status_payload,
        r1_planning_coverage=replay_coverage,
        r2_planning_coverage=None,
        planning_coverage=replay_coverage,
        gap_state=None,
        require_existing=False,
    )
    suppressions = lock["work_family_duplicate_suppressions"]
    assert [item["suppressed_record_id"] for item in suppressions] == ["family-low"]
    assert suppressions[0]["representative_record_id"] == "family-replacement"
    assessments = lock["candidate_quality_assessments"]
    assert lock["schema_version"] == "contest-direction-planning-literature-v5"
    assert len(assessments) == len(replay_catalog)
    assert lock["candidate_quality_assessments_hash"] == canonical_model_hash(
        {"assessments": assessments}
    )
    assert all(item["assessment_hash"] for item in assessments)


def test_coverage_projection_uses_fail_safe_quality_and_bounded_citations() -> None:
    common = {
        "title": "Phase stability in lumen arrays",
        "authors": ["A. Researcher"],
        "abstract": "A controlled study of phase stability under repeated measurements.",
        "publication_status": "published",
        "retrieved_from": "registry-a",
        "citation_count_source": "scholarly-index",
        "citation_count_as_of": "2026-08-14",
    }
    repository = loop_cli._planning_coverage_candidate(
        {
            **common,
            "record_id": "repository-record",
            "publication_type": "repository-record",
            "repository_doi": "10.9999/archive.123",
            "citation_count": 10_000_000,
        },
        "repository context",
    )
    reviewed = loop_cli._planning_coverage_candidate(
        {
            **common,
            "record_id": "reviewed-record",
            "publication_type": "research-article",
            "publication_doi": "10.9999/article.123",
            "venue": "Research proceedings",
            "peer_review_status": "peer_reviewed",
            "peer_review_status_source": "publisher-metadata",
            "citation_count": 0,
        },
        "reviewed context",
    )
    unprovenanced = loop_cli._planning_coverage_candidate(
        {
            **common,
            "record_id": "unprovenanced-record",
            "citation_count": 99_000_000,
            "citation_count_source": None,
            "citation_count_as_of": None,
        },
        "unprovenanced context",
    )

    assert reviewed.quality_score > repository.quality_score
    assert unprovenanced.citation_count is None


def test_locked_planning_context_is_renumbered_once_in_selected_order() -> None:
    catalog = (
        {"record_id": "record-a"},
        {"record_id": "record-b"},
    )
    contexts = (
        "[17] record_id=record-a\nTitle: First source",
        "[3] record_id=record-b\nTitle: Second source",
    )
    receipt = SimpleNamespace(selected_record_ids=("record-b", "record-a"))

    selected, locked_contexts = loop_cli._coverage_selected_subset(
        catalog,
        contexts,
        receipt,
    )
    selected_again, locked_again = loop_cli._coverage_selected_subset(
        selected,
        locked_contexts,
        receipt,
    )

    assert tuple(item["record_id"] for item in selected) == ("record-b", "record-a")
    assert locked_contexts[0].startswith("[1] record_id=record-b\n")
    assert locked_contexts[1].startswith("[2] record_id=record-a\n")
    assert selected_again == selected
    assert locked_again == locked_contexts


def test_preserved_revision_replay_reuses_exact_receipt_without_provider(
    tmp_path: Path,
) -> None:
    revision_root = tmp_path / "revision"
    messages = [
        {"role": "system", "content": "通用科研方法。"},
        {"role": "user", "content": "依据真实预实验修订计划。"},
    ]
    parsed = {"results": "预实验观察值保持不变。"}
    response_text = json.dumps(parsed, ensure_ascii=False)
    completion = LLMJsonCompletionResult(
        provider="test-provider",
        base_url="https://provider.example/v1",
        model_name="test-model",
        endpoint="https://provider.example/v1/chat/completions",
        response_text=response_text,
        parsed_json=parsed,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        temperature=0.2,
    )
    interaction_id = "direct-plan-revision-0123456789abcdef-0123456789ab"
    response_path = revision_root / "responses" / f"{interaction_id}.txt"
    response_path.parent.mkdir(parents=True)
    response_path.write_text(response_text, encoding="utf-8")
    record_model_authorship_receipt(
        artifact_kind="research_plan",
        interaction_id=interaction_id,
        attempt=1,
        messages=messages,
        completion=completion,
        output_dir=revision_root,
    )

    replay = loop_cli._load_preserved_revision_replay(revision_root)

    assert replay is not None
    assert replay(messages=messages).response_text == response_text
    with pytest.raises(
        ContestDirectionResearchLoopError,
        match="inputs differ from the preserved provider call",
    ):
        replay(messages=[{"role": "user", "content": "不同输入"}])


def test_preserved_revision_replay_validates_context_artifact_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability_payload: dict[str, Any] = {
        "schema_version": "official-model-capability-v1",
        "provider": "qwen-dashscope",
        "model_name": "qwen3.7-max",
        "official_source_url": "https://help.aliyun.com/zh/model-studio/qwen3-7-max",
        "official_source_last_modified": "2026-08-03T15:41:58+08:00",
        "fetched_at": "2026-08-14T00:00:00Z",
        "source_sha256": "a" * 64,
        "source_size_bytes": 1,
        "parser_version": "aliyun-model-page-v1",
        "context_window_tokens": 1_000_000,
        "maximum_input_tokens": 991_808,
        "maximum_output_tokens": 131_072,
        "maximum_input_tokens_thinking": 983_616,
        "maximum_output_tokens_thinking": 131_072,
        "maximum_reasoning_tokens": 262_144,
    }
    capability_payload["capability_hash"] = canonical_sha256(capability_payload)
    capability = OfficialModelCapability.model_validate(capability_payload)
    monkeypatch.setattr(
        "autoresearch.llm.task_context.load_official_model_capability",
        lambda **_kwargs: capability,
    )
    messages = [{"role": "user", "content": "依据真实预实验修订计划。"}]
    parsed = {"results": "预实验观察值保持不变。"}
    response_text = json.dumps(parsed, ensure_ascii=False)

    def provider_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            response_text=response_text,
            parsed_json=parsed,
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            temperature=0.2,
        )

    revision_root = tmp_path / "revision"
    session = AutonomousTaskContextSession(
        project_id="lineage",
        conversation_id="lineage-revision",
        output_dir=tmp_path / "context",
        vault_root=tmp_path / "vault",
        completion=provider_completion,
    )
    with session.task("revision-authoring") as completion_call:
        completion = completion_call(
            messages=messages,
            config_path=tmp_path / "missing.yaml",
            max_tokens=128,
            response_schema_name="contest_direct_plan_revision",
        )
        record_model_authorship_receipt(
            artifact_kind="research_plan",
            interaction_id="direct-plan-revision-fedcba9876543210-fedcba987654",
            attempt=1,
            messages=messages,
            completion=completion,
            output_dir=revision_root,
        )
    response_path = (
        revision_root / "responses" / ("direct-plan-revision-fedcba9876543210-fedcba987654.txt")
    )
    response_path.parent.mkdir(parents=True)
    response_path.write_text(response_text, encoding="utf-8")

    replay = loop_cli._load_preserved_revision_replay(revision_root)

    assert replay is not None
    assert replay(messages=messages).response_text == response_text


def test_postpilot_plan_context_excludes_byte_provenance_summary() -> None:
    artifact = SimpleNamespace(
        plan_context_payload=lambda: {
            "decision": "narrow_once",
            "review_cn": "根据真实预实验收窄假设。",
            "verified_inputs_bundle_sha256": "a" * 64,
        }
    )

    projected = loop_cli._postpilot_plan_context(artifact)

    assert projected == {
        "decision": "narrow_once",
        "review_cn": "根据真实预实验收窄假设。",
    }


def test_memory_sidecar_failures_cannot_block_completed_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "run" / "stage.json"
    _write_json(artifact, {"status": "completed"})

    class BrokenMemory:
        def capture_completed_stage(self, **_kwargs: Any) -> Any:
            raise OSError("capture unavailable")

        def recall_optional_context(self, **_kwargs: Any) -> Any:
            raise OSError("recall unavailable")

    capture = loop_cli._capture_stage_memory(
        BrokenMemory(),
        stage="real-pilot",
        artifact_paths=(artifact,),
    )
    context, recall = loop_cli._recall_stage_memory(
        BrokenMemory(),
        consumer_stage="final-plan-revision",
        source_stages=("real-pilot",),
        requested=True,
    )

    assert artifact.is_file()
    assert capture["status"] == "unavailable"
    assert capture["delivery_blocked_by_memory"] is False
    assert context is None
    assert recall["status"] == "unavailable"
    assert recall["delivery_blocked_by_memory"] is False


def _render_binding(path: Path, *, filename: str | None = None) -> dict[str, Any]:
    return {
        "filename": filename or path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def test_resume_loader_accepts_self_contained_v3_with_private_source(tmp_path: Path) -> None:
    root = tmp_path / "plan"
    public_payload = {"title": "公开自包含研究计划"}
    source_payload = {
        "title": "公开自包含研究计划",
        "generation": {"run_id": "private-run"},
    }
    paths = {
        "json": root / "research-plan.json",
        "markdown": root / "research-plan.md",
        "tex": root / "research-plan.tex",
        "pdf": root / "research-plan.pdf",
        "source": root / "_private" / "research-plan-source.json",
    }
    _write_json(paths["json"], public_payload)
    _write_json(paths["source"], source_payload)
    paths["markdown"].write_text("# 公开自包含研究计划\n", encoding="utf-8")
    paths["tex"].write_text("\\documentclass{article}\n", encoding="utf-8")
    paths["pdf"].write_bytes(b"%PDF-1.4\nself-contained\n%%EOF\n")
    manifest = {
        "schema_version": "contest-direct-plan-render-v3",
        "compile_status": "compiled",
        "pdf_text_verified": True,
        "page_count": 2,
        "source_payload_sha256": canonical_model_hash(source_payload),
        "public_payload_sha256": canonical_model_hash(public_payload),
        "artifacts": {
            "json": _render_binding(paths["json"]),
            "markdown": _render_binding(paths["markdown"]),
            "tex": _render_binding(paths["tex"]),
            "pdf": _render_binding(paths["pdf"]),
            "source": _render_binding(
                paths["source"], filename="_private/research-plan-source.json"
            ),
        },
    }
    _write_json(root / "research-plan-manifest.json", manifest)

    rendered = loop_cli._load_rendered_plan(root)

    assert rendered.source_path == paths["source"]
    assert rendered.source_payload_sha256 == canonical_model_hash(source_payload)
    assert rendered.page_count == 2


def test_resume_loader_rejects_legacy_raw_plan_render(tmp_path: Path) -> None:
    root = tmp_path / "legacy-plan"
    raw_payload = {
        "title": "旧计划",
        "preexperiment": {
            "artifact_path": "E:/private/metrics.json",
            "run_id": "legacy-private-run",
        },
    }
    paths = {
        "json": root / "research-plan.json",
        "markdown": root / "research-plan.md",
        "tex": root / "research-plan.tex",
        "pdf": root / "research-plan.pdf",
    }
    _write_json(paths["json"], raw_payload)
    paths["markdown"].write_text("# 旧计划\n", encoding="utf-8")
    paths["tex"].write_text("\\documentclass{article}\n", encoding="utf-8")
    paths["pdf"].write_bytes(b"%PDF-1.4\nlegacy\n%%EOF\n")
    _write_json(
        root / "research-plan-manifest.json",
        {
            "schema_version": "contest-direct-plan-render-v2",
            "compile_status": "compiled",
            "pdf_text_verified": True,
            "source_payload_sha256": canonical_model_hash(raw_payload),
            "artifacts": {key: _render_binding(path) for key, path in paths.items()},
        },
    )

    with pytest.raises(
        ContestDirectionResearchLoopError,
        match="not a self-contained v3 delivery",
    ):
        loop_cli._load_rendered_plan(root)


def test_doi_verification_enabled_flag_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("AUTORESEARCH_ENABLE_DOI_VERIFICATION", raising=False)
    assert loop_cli._doi_verification_enabled() is False

    monkeypatch.setenv("AUTORESEARCH_ENABLE_DOI_VERIFICATION", "1")
    assert loop_cli._doi_verification_enabled() is True

    monkeypatch.setenv("AUTORESEARCH_ENABLE_DOI_VERIFICATION", "off")
    assert loop_cli._doi_verification_enabled() is False


def test_record_finalist_doi_verification_writes_and_reuses_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autoresearch.literature.doi_verification import (
        DoiVerification,
        ReferenceVerificationReceipt,
    )

    calls: list[int] = []

    def fake_verify(
        records: object,
        *,
        mailto: object = None,
        timeout_seconds: object = 30,
        http_get: object = None,
    ) -> ReferenceVerificationReceipt:
        del mailto, timeout_seconds, http_get
        count = len(records) if isinstance(records, list) else 0
        calls.append(count)
        return ReferenceVerificationReceipt(
            verified=(
                DoiVerification(
                    doi="10.1000/x",
                    status="resolved",
                    resolved_title="T",
                    title_match="match",
                    resolved_authors=(),
                    container_title=None,
                ),
            ),
            skipped_count=1,
        )

    monkeypatch.setattr(loop_cli, "verify_reference_records", fake_verify)

    catalog = [
        {"record_id": "r1", "title": "T", "doi": "10.1000/x"},
        {"record_id": "r2", "title": "Repository only", "repository_doi": "10.48550/arXiv.1"},
    ]
    path = tmp_path / "finalist-doi-verification.json"

    fresh = loop_cli._record_finalist_doi_verification(path, catalog, resume=False)
    assert fresh["schema_version"] == "contest-direction-finalist-doi-verification-v1"
    assert fresh["catalog_record_ids"] == ["r1", "r2"]
    assert fresh["verification_count"] == 1
    assert len(calls) == 1

    resumed = loop_cli._record_finalist_doi_verification(path, catalog, resume=True)
    assert resumed == fresh
    assert len(calls) == 1
