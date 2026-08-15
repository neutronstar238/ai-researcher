from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from autoresearch.knowledge.raw_memory import (
    MemoryClaimVerdict,
    RawMemoryStore,
)
from autoresearch.literature.models import AcademicPaper
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_capabilities import (
    AdaptiveLiteratureRetrievalArtifact,
    AdaptiveResearchCapabilityEnvironment,
    AdaptiveTemporaryMemo,
    TemporaryQwenResearchDispatcher,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ModelResearchActionDraft,
    ResearchOperator,
    TemporaryResearchTask,
    create_adaptive_research_seed,
    initialize_adaptive_research_loop,
)
from autoresearch.research.adaptive_sovereign_recall import SovereignRecallSelection

_NOW = datetime(2026, 8, 10, 2, 0, tzinfo=timezone.utc)
_REASONING = (
    "临时代理首先核对输入引用、任务问题、方法技能和权限边界，然后只针对显式问题形成中文备忘录。"
    "它不执行实验、不提升证据、不审批、不发布，也不会把自身总结冒充外部事实。"
) * 4


class _LiteratureClient:
    def __init__(self, papers: list[AcademicPaper]) -> None:
        self.papers = papers
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        self.calls.append((query, limit))
        return self.papers[:limit]


class _SecretFailingClient:
    def search(self, query: str, *, limit: int = 10) -> list[AcademicPaper]:
        del query, limit
        raise RuntimeError("api_key=NEVER-PERSIST-THIS")


def _state(
    tmp_path: Path,
) -> tuple[RawMemoryStore, AdaptiveResearchSeed, AdaptiveResearchLoopSnapshot]:
    store = RawMemoryStore(tmp_path / "vault")
    seed = create_adaptive_research_seed(
        loop_id="adaptive-capability-test",
        project_id="adaptive_capability_test",
        objective_cn="自主研究长期记忆的状态轨迹正确性与科研假设纠错。",
        scope_cn="只允许检索、派生整理和临时中文内容评审，不执行正式实验。",
        raw_memory_store=store,
        captured_at=_NOW,
    )
    snapshot = initialize_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="adaptive-capability-test",
            max_external_actions=4,
            max_temporary_agents=4,
        ),
        raw_memory_store=store,
    )
    return store, seed, snapshot


def _proposal(
    operator: ResearchOperator,
    *,
    temporary_tasks: list[TemporaryResearchTask] | None = None,
) -> ModelResearchActionDraft:
    action_body_cn = (
        "检索最近先前工作，并寻找原始记忆与派生状态分离可能失败的反例。"
        if operator is ResearchOperator.RETRIEVE_EVIDENCE
        else (
            "围绕主体记忆、状态轨迹、修订和遗忘检索最近先前工作，"
            "并寻找原始记忆与派生状态分离可能失败的反例。"
        )
    )
    return ModelResearchActionDraft(
        step_index=1,
        branch_id="branch_root",
        operator=operator,
        action_title_cn="检验可演化记忆的状态轨迹边界",
        action_body_cn=action_body_cn,
        retrieval_query_terms=(
            ["agent memory", "trajectory update", "forgetting benchmark"]
            if operator is ResearchOperator.RETRIEVE_EVIDENCE
            else []
        ),
        reason_for_choice_cn="外部材料比继续内部自我肯定更能缩小当前不确定性。",
        expected_information_gain_cn="可识别直接重复工作、相邻机制与仍缺少全文支持的主张。",
        selected_skill_ids=[],
        source_refs=[],
        temporary_tasks=temporary_tasks or [],
    )


def test_retrieval_captures_normalized_catalog_and_redacts_transport_error(
    tmp_path: Path,
) -> None:
    store, seed, snapshot = _state(tmp_path)
    openalex = _LiteratureClient(
        [
            AcademicPaper(
                title="Governed Evolving Memory for Long-Term Agents",
                authors=["A. Researcher"],
                abstract="Memory correctness is a property of the state trajectory.",
                publication_date=date(2026, 5, 25),
                doi="10.0000/example",
                url="https://example.org/paper",
                source="openalex",
            )
        ]
    )
    environment = AdaptiveResearchCapabilityEnvironment(
        output_dir=tmp_path / "run",
        raw_memory_store=store,
        literature_clients={
            "openalex": openalex,
            "semantic-scholar": _SecretFailingClient(),
        },
        clock=lambda: _NOW,
    )

    proposal = _proposal(ResearchOperator.RETRIEVE_EVIDENCE).model_copy(
        update={
            "action_body_cn": "寻找状态轨迹、修订和遗忘的直接先前工作与反例。",
            "retrieval_query_terms": ["agent", "memory", "state update"],
        }
    )
    feedback = environment.execute(
        seed=seed,
        snapshot=snapshot,
        proposal=proposal,
    )

    assert environment.supported_operators() == frozenset(
        {
            ResearchOperator.RETRIEVE_EVIDENCE,
            ResearchOperator.CONSOLIDATE_DREAMING,
        }
    )
    assert openalex.calls == [("agent memory state update", 6)]
    assert feedback.status.value == "succeeded"
    assert feedback.source_refs == ["https://example.org/paper"]
    assert feedback.independent_of_action_author
    assert not feedback.is_scientific_evidence
    artifact_path = (
        tmp_path
        / "run"
        / "capabilities"
        / "step-0001"
        / "retrieval"
        / "adaptive-literature-retrieval.json"
    )
    artifact = AdaptiveLiteratureRetrievalArtifact.model_validate_json(artifact_path.read_bytes())
    assert artifact.papers[0].title.startswith("Governed Evolving")
    assert artifact.fetches[1].error_type == "RuntimeError"
    raw = store.load_record(
        artifact.normalized_catalog_binding.record_relative_path,
        project_id=seed.project_id,
    ).blob_path.read_text(encoding="utf-8")
    assert "NEVER-PERSIST-THIS" not in raw
    assert 'transport_bytes_retained":false' in raw


def test_dreaming_is_unverified_rebuildable_and_leaves_seed_bytes_unchanged(
    tmp_path: Path,
) -> None:
    store, seed, snapshot = _state(tmp_path)
    seed_capture = store.load_record(
        seed.raw_seed_binding.record_relative_path,
        project_id=seed.project_id,
    )
    original_seed_bytes = seed_capture.blob_path.read_bytes()
    environment = AdaptiveResearchCapabilityEnvironment(
        output_dir=tmp_path / "run",
        raw_memory_store=store,
        literature_clients={"openalex": _LiteratureClient([])},
        clock=lambda: _NOW,
    )

    feedback = environment.execute(
        seed=seed,
        snapshot=snapshot,
        proposal=_proposal(ResearchOperator.CONSOLIDATE_DREAMING),
    )

    assert feedback.origin.value == "dreaming_projection"
    assert not feedback.independent_of_action_author
    assert seed_capture.blob_path.read_bytes() == original_seed_bytes
    projection_path = next(
        (tmp_path / "vault" / "projects" / seed.project_id / "knowledge" / "dreaming").glob(
            "dream_*.json"
        )
    )
    projection_id = projection_path.stem
    projection = store.load_dreaming_projection(
        projection_id,
        project_id=seed.project_id,
    ).projection
    assert projection.content.raw_records_mutated is False
    assert projection.content.derived_and_rebuildable is True
    assert projection.content.claim_assessments[0].verdict is MemoryClaimVerdict.UNVERIFIED
    assert len(projection.content.source_bindings) == 2
    selection_path = (
        tmp_path
        / "run"
        / "capabilities"
        / "step-0001"
        / "dreaming"
        / "sovereign-recall-selection.json"
    )
    selection = SovereignRecallSelection.model_validate_json(selection_path.read_bytes())
    assert feedback.artifact_refs[0] == f"artifact:{selection.selection_hash}"
    assert feedback.metrics["recall_from_complete_history"] is True
    assert feedback.metrics["recalled_record_count"] == 1
    assert selection.selected_excerpts[0].binding == seed.raw_seed_binding


def test_main_agent_dispatches_zero_or_selected_skill_workers_then_archives(
    tmp_path: Path,
) -> None:
    store, seed, snapshot = _state(tmp_path)
    skill_dir = tmp_path / "skills" / "counterexample-review"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: counterexample-review
description: 用于寻找候选机制的反例、混杂和替代解释，不提供具体科学结论或审批。
---

# 反例审查

只检查反例、混杂和可证伪条件，不把技能当成事实证据。
""",
        encoding="utf-8",
    )
    tasks = [
        TemporaryResearchTask(
            task_id="temporary-no-skill",
            role_cn="开放问题整理员",
            question_cn="只根据当前分支列出仍未回答的关键问题。",
            selected_skill_ids=[],
        ),
        TemporaryResearchTask(
            task_id="temporary-counterexample",
            role_cn="反例评审员",
            question_cn="寻找该候选机制最可能失败的条件和混杂。",
            selected_skill_ids=["counterexample-review"],
        ),
    ]
    calls: list[list[dict[str, str]]] = []
    lock = threading.Lock()

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        messages = kwargs["messages"]
        task_payload = json.loads(messages[-1]["content"])
        output = AdaptiveTemporaryMemo(
            summary_cn=f"临时任务{task_payload['派工编号']}已完成有界中文审查。",
            findings_cn=["当前候选仍可能受到早期错误派生记忆的混杂影响。"],
            uncertainties_cn=["尚未获得真实长期运行结果。"],
        ).model_dump(mode="json")
        with lock:
            calls.append(messages)
        return LLMJsonCompletionResult(
            provider="qwen-test",
            base_url="https://example.invalid/v1",
            model_name="qwen-test-model",
            endpoint="https://example.invalid/v1/chat/completions",
            response_text=json.dumps(output, ensure_ascii=False),
            parsed_json=output,
            usage={},
            temperature=float(kwargs["temperature"]),
            reasoning_text=_REASONING,
            reasoning_transport="dashscope_enable_thinking",
        )

    dispatcher = TemporaryQwenResearchDispatcher(
        output_dir=tmp_path / "run",
        skill_root=tmp_path / "skills",
        completion=completion,
        max_workers=2,
        clock=lambda: _NOW,
    )
    outcome = dispatcher.dispatch(
        seed=seed,
        snapshot=snapshot,
        proposal=_proposal(
            ResearchOperator.CONSULT_TEMPORARY_AGENTS,
            temporary_tasks=tasks,
        ),
        tasks=tasks,
    )

    assert len(outcome.contributions) == 2
    assert outcome.all_assignments_archived
    assert outcome.all_runtime_identities_removed
    assert outcome.main_agent_retains_stage_control
    assert len(calls) == 2
    assert sorted(len(messages) for messages in calls) == [2, 3]
    archives = list((tmp_path / "run" / "temporary").rglob("archives/*.json"))
    assert len(archives) == 2
