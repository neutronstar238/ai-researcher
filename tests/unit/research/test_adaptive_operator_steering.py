from __future__ import annotations

import inspect
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import autoresearch.research.adaptive_operator_steering as steering_module
from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.adaptive_operator_steering import (
    AdaptiveOperatorFamily,
    AdaptiveOperatorSteeringApplicationMode,
    AdaptiveOperatorSteeringDecision,
    AdaptiveOperatorSteeringError,
    AdaptiveOperatorSteeringShadowInput,
    AdaptiveOperatorSteeringStage,
    AdaptiveOperatorSteeringStructuralObservation,
    DevelopmentAdaptiveOperatorCatalogProvider,
    ShadowAdaptiveOperatorCatalogProvider,
    adaptive_operator_steering_development_receipt_filename,
    audit_adaptive_operator_steering_shadow,
    build_adaptive_operator_steering_decision,
    build_adaptive_operator_steering_policy,
    build_adaptive_operator_steering_shadow_input,
    load_adaptive_operator_steering_development_decision,
    seal_adaptive_operator_steering_development_decision,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchBranch,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ModelResearchActionDraft,
    OperatorCatalogProvider,
    ResearchLoopZone,
    ResearchOperator,
    create_adaptive_research_seed,
    initialize_adaptive_research_loop,
    load_adaptive_research_loop_snapshot,
    run_adaptive_research_loop,
)

_NOW = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
_REASONING = (
    "我只检查当前分支已经发生的结构变化、可用算子和预算边界。"
    "本轮动作仍然只是开放探索中的候选，不构成证据、结论或任何效果证明。"
    "我会保留停止、放弃和晋级边界，也会避免把单一动作变成事实上的唯一选择。"
) * 4

_FULL_CATALOG = [
    ResearchOperator.RETRIEVE_EVIDENCE,
    ResearchOperator.BRANCH_HYPOTHESIS,
    ResearchOperator.ANALOGICAL_TRANSFER,
    ResearchOperator.REFRAME_QUESTION,
    ResearchOperator.DECOMPOSE_UNCERTAINTY,
    ResearchOperator.ADVERSARIAL_CRITIQUE,
    ResearchOperator.MUTATE_WORKFLOW_PROPOSAL,
    ResearchOperator.CONSULT_TEMPORARY_AGENTS,
    ResearchOperator.RUN_SANDBOX_PROBE,
    ResearchOperator.CONSOLIDATE_DREAMING,
    ResearchOperator.PROMOTE_BRANCH,
    ResearchOperator.ABANDON_BRANCH,
    ResearchOperator.STOP_EXPLORATION,
]


class _NoopEnvironment:
    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset()

    def execute(self, *, proposal: ModelResearchActionDraft, **_: Any) -> Any:
        raise AssertionError(f"unexpected external operator: {proposal.operator}")


class _StructuralSequenceCompletion:
    def __init__(self) -> None:
        self.operators = [ResearchOperator.BRANCH_HYPOTHESIS] + [
            ResearchOperator.DECOMPOSE_UNCERTAINTY
        ] * 6

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        task = json.loads(kwargs["messages"][-1]["content"])
        step_index = int(task["step_index"])
        operator = self.operators[step_index - 1]
        payload: dict[str, Any] = {
            "schema_version": "adaptive-research-action-draft-v3",
            "step_index": step_index,
            "branch_id": str(task["selected_branch"]["branch_id"]),
            "operator": operator.value,
            "action_title_cn": "执行一次通用结构动作",
            "action_body_cn": "仅改变分支的结构记录，并保留所有机械边界。",
            "retrieval_query_terms": [],
            "reason_for_choice_cn": "用于形成不含任务语义的算子序列。",
            "expected_information_gain_cn": "仅记录结构变化，不声明任何实际收益。",
            "selected_skill_ids": [],
            "source_refs": [],
            "memory_consumption_claims": [],
            "temporary_tasks": [],
            "scientific_content_generated_by_model": True,
            "human_authored_scientific_prose_count": 0,
            "is_scientific_evidence": False,
            "execution_authorized": False,
            "publication_authorized": False,
        }
        if operator is ResearchOperator.BRANCH_HYPOTHESIS:
            payload["working_hypothesis_cn"] = "这是系统生成的通用占位假设，仅用于建立子分支。"
        return LLMJsonCompletionResult(
            provider="test-provider",
            base_url="https://provider.invalid/v1",
            model_name="test-model",
            endpoint="https://provider.invalid/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            parsed_json=payload,
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            temperature=0.7,
            reasoning_text=_REASONING,
            reasoning_transport="dashscope_enable_thinking",
        )


@pytest.fixture(scope="module")
def retained_snapshot_case(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[RawMemoryStore, AdaptiveResearchSeed, AdaptiveResearchLoopSnapshot]:
    root = tmp_path_factory.mktemp("operator-steering-retained")
    store = RawMemoryStore(root / "vault")
    seed = create_adaptive_research_seed(
        loop_id="generic-structure-loop",
        project_id="generic_structure_project",
        objective_cn="由系统自主处理一个通用研究目标。",
        scope_cn="仅保留结构记录，不授权正式执行或发布。",
        raw_memory_store=store,
        captured_at=_NOW,
    )
    run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            policy_id="generic-structure-policy",
            max_steps=7,
            max_model_calls=7,
            max_external_actions=1,
            max_temporary_agents=1,
            max_consecutive_stalls=10,
        ),
        raw_memory_store=store,
        output_dir=root / "loop",
        environment=_NoopEnvironment(),
        completion=_StructuralSequenceCompletion(),
        clock=lambda: _NOW,
    )
    retained_path = next((root / "loop" / "snapshots").glob("step-0006-*.json"))
    snapshot = load_adaptive_research_loop_snapshot(
        retained_path,
        raw_memory_store=store,
    )
    return store, seed, snapshot


def _observation(
    *,
    turns_since_memory_review: int,
    zone: ResearchLoopZone = ResearchLoopZone.OPEN_EXPLORATION,
) -> AdaptiveOperatorSteeringStructuralObservation:
    history = [ResearchOperator.DECOMPOSE_UNCERTAINTY] * 5
    return AdaptiveOperatorSteeringStructuralObservation.create(
        zone=zone,
        retained_event_count=max(len(history), turns_since_memory_review),
        branch_operator_ids=history,
        turns_since_memory_review=turns_since_memory_review,
    )


def _shadow_input(
    *,
    observation: AdaptiveOperatorSteeringStructuralObservation,
    mechanical: Sequence[ResearchOperator] = _FULL_CATALOG,
    binding_tag: str = "a",
) -> AdaptiveOperatorSteeringShadowInput:
    return AdaptiveOperatorSteeringShadowInput.create(
        seed_hash=canonical_sha256({"seed-binding": binding_tag}),
        snapshot_hash=canonical_sha256({"snapshot-binding": binding_tag}),
        branch_id=f"branch_{binding_tag}",
        branch_hash=canonical_sha256({"branch-binding": binding_tag}),
        structural_observation=observation,
        structural_observation_hash=observation.observation_hash,
        mechanically_available_operator_ids=list(mechanical),
    )


def _child_branch(snapshot: AdaptiveResearchLoopSnapshot) -> AdaptiveResearchBranch:
    return next(branch for branch in snapshot.branches if branch.parent_branch_id is not None)


def test_shadow_is_nonintervening_and_development_seals_before_applying(
    retained_snapshot_case: tuple[
        RawMemoryStore,
        AdaptiveResearchSeed,
        AdaptiveResearchLoopSnapshot,
    ],
    tmp_path: Path,
) -> None:
    _, seed, snapshot = retained_snapshot_case
    branch = _child_branch(snapshot)
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    mechanical = [item.value for item in _FULL_CATALOG]

    shadow: OperatorCatalogProvider = ShadowAdaptiveOperatorCatalogProvider(policy)
    shadow_output = list(
        shadow(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            mechanically_available_operator_ids=mechanical,
        )
    )
    assert shadow_output == mechanical
    assert isinstance(shadow, ShadowAdaptiveOperatorCatalogProvider)
    shadow_decision = shadow.last_decision
    assert shadow_decision is not None
    assert shadow_decision.candidate_catalog_ids != shadow_decision.baseline_catalog_ids
    assert shadow_decision.candidate_applied is False
    assert shadow_decision.controller_intervened is False
    assert shadow_decision.provider_returned_catalog_ids == shadow_decision.baseline_catalog_ids

    receipts = tmp_path / "receipts"
    receipts.mkdir()
    development: OperatorCatalogProvider = DevelopmentAdaptiveOperatorCatalogProvider(
        policy,
        decision_receipt_path_provider=lambda decision: receipts
        / adaptive_operator_steering_development_receipt_filename(decision),
    )
    development_output = list(
        development(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            mechanically_available_operator_ids=mechanical,
        )
    )
    assert isinstance(development, DevelopmentAdaptiveOperatorCatalogProvider)
    development_decision = development.last_decision
    assert development_decision is not None
    assert development_output == [item.value for item in development_decision.candidate_catalog_ids]
    assert development_decision.candidate_applied is True
    assert development_decision.controller_intervened is True
    assert development_decision.nonconfirmatory is True
    assert development_decision.production_adoption_authorized is False
    assert development_decision.formal_evidence_generated is False
    assert len(development.sealed_receipt_paths) == 1
    assert (
        load_adaptive_operator_steering_development_decision(development.sealed_receipt_paths[0])
        == development_decision
    )
    with pytest.raises(AdaptiveOperatorSteeringError, match="overwrite is forbidden"):
        development(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            mechanically_available_operator_ids=mechanical,
        )
    assert development.decisions == (development_decision,)
    assert len(development.sealed_receipt_paths) == 1


def test_candidate_is_ordered_subset_with_choice_and_family_floors() -> None:
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    decision = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(observation=_observation(turns_since_memory_review=6)),
        application_mode=(AdaptiveOperatorSteeringApplicationMode.DEVELOPMENT_EVALUATION_ONLY),
    )

    candidate = decision.candidate_catalog_ids
    candidate_set = set(candidate)
    assert candidate == [item for item in _FULL_CATALOG if item in candidate_set]
    assert set(candidate).issubset(_FULL_CATALOG)
    assert len(candidate) >= 2
    assert len(decision.candidate_continuing_research_ids) >= 4
    assert len(decision.candidate_non_memory_continuing_ids) >= 3
    assert len(decision.candidate_non_memory_continuing_families) >= 3
    assert ResearchOperator.CONSOLIDATE_DREAMING in candidate
    assert all(
        item in candidate
        for item in {
            ResearchOperator.PROMOTE_BRANCH,
            ResearchOperator.ABANDON_BRANCH,
            ResearchOperator.STOP_EXPLORATION,
        }
    )


def test_repetition_is_branch_local_and_projection_contains_no_research_text(
    retained_snapshot_case: tuple[
        RawMemoryStore,
        AdaptiveResearchSeed,
        AdaptiveResearchLoopSnapshot,
    ],
) -> None:
    _, seed, snapshot = retained_snapshot_case
    child = _child_branch(snapshot)
    root = next(branch for branch in snapshot.branches if branch.parent_branch_id is None)
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    child_input = build_adaptive_operator_steering_shadow_input(
        seed=seed,
        snapshot=snapshot,
        branch=child,
        mechanically_available_operator_ids=[item.value for item in _FULL_CATALOG],
    )
    root_input = build_adaptive_operator_steering_shadow_input(
        seed=seed,
        snapshot=snapshot,
        branch=root,
        mechanically_available_operator_ids=[item.value for item in _FULL_CATALOG],
    )
    child_decision = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=child_input,
    )
    root_decision = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=root_input,
    )

    assert child_decision.stage is AdaptiveOperatorSteeringStage.MEMORY_REVIEW_DEBT_RELIEF
    assert child_decision.repeated_family is AdaptiveOperatorFamily.SHORT_HORIZON_INTROSPECTION
    assert root_decision.stage is AdaptiveOperatorSteeringStage.OBSERVE_IDENTITY
    assert root_decision.repeated_family is None
    projected = json.dumps(child_input.model_dump(mode="json"), ensure_ascii=False)
    assert seed.objective_cn not in projected
    assert seed.scope_cn not in projected
    assert child.title_cn not in projected
    assert child.working_hypothesis_cn not in projected
    assert set(AdaptiveOperatorSteeringShadowInput.model_fields) == {
        "schema_version",
        "seed_hash",
        "snapshot_hash",
        "branch_id",
        "branch_hash",
        "structural_observation",
        "structural_observation_hash",
        "mechanically_available_operator_ids",
        "input_hash",
    }


def test_memory_debt_and_non_debt_suppression_are_stage_local() -> None:
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=8)
    debt = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=_observation(turns_since_memory_review=10),
            binding_tag="debt",
        ),
    )
    recent_only = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=_observation(turns_since_memory_review=5),
            binding_tag="recent",
        ),
    )
    non_exploration = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=_observation(
                turns_since_memory_review=10,
                zone=ResearchLoopZone.FORMAL_VERIFICATION,
            ),
            binding_tag="formal-zone",
        ),
    )

    assert debt.stage is AdaptiveOperatorSteeringStage.MEMORY_REVIEW_DEBT_RELIEF
    assert set(debt.suppressed_ids) == {
        ResearchOperator.REFRAME_QUESTION,
        ResearchOperator.DECOMPOSE_UNCERTAINTY,
        ResearchOperator.ADVERSARIAL_CRITIQUE,
        ResearchOperator.MUTATE_WORKFLOW_PROPOSAL,
    }
    assert recent_only.stage is AdaptiveOperatorSteeringStage.DIVERSITY_RELIEF
    assert recent_only.suppressed_ids == [ResearchOperator.DECOMPOSE_UNCERTAINTY]
    assert non_exploration.stage is AdaptiveOperatorSteeringStage.NON_EXPLORATION_IDENTITY
    assert non_exploration.candidate_catalog_ids == non_exploration.baseline_catalog_ids


def test_safety_fallback_preserves_continuing_choices_and_singleton_compatibility() -> None:
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    narrow = [
        ResearchOperator.DECOMPOSE_UNCERTAINTY,
        ResearchOperator.BRANCH_HYPOTHESIS,
        ResearchOperator.RETRIEVE_EVIDENCE,
        ResearchOperator.CONSOLIDATE_DREAMING,
        ResearchOperator.PROMOTE_BRANCH,
        ResearchOperator.ABANDON_BRANCH,
        ResearchOperator.STOP_EXPLORATION,
    ]
    fallback = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=_observation(turns_since_memory_review=8),
            mechanical=narrow,
            binding_tag="fallback",
        ),
    )
    assert fallback.stage is AdaptiveOperatorSteeringStage.MINIMUM_CHOICE_FALLBACK
    assert fallback.proposed_suppressed_ids == [ResearchOperator.DECOMPOSE_UNCERTAINTY]
    assert fallback.suppressed_ids == []
    assert fallback.candidate_catalog_ids == narrow

    memory_and_boundaries = [
        ResearchOperator.CONSOLIDATE_DREAMING,
        ResearchOperator.PROMOTE_BRANCH,
        ResearchOperator.ABANDON_BRANCH,
        ResearchOperator.STOP_EXPLORATION,
    ]
    unchanged = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=_observation(turns_since_memory_review=8),
            mechanical=memory_and_boundaries,
            binding_tag="boundary-only",
        ),
    )
    assert unchanged.candidate_catalog_ids == memory_and_boundaries

    singleton = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=_observation(turns_since_memory_review=8),
            mechanical=[ResearchOperator.STOP_EXPLORATION],
            binding_tag="singleton",
        ),
    )
    assert singleton.candidate_catalog_ids == [ResearchOperator.STOP_EXPLORATION]
    assert singleton.controller_intervened is False


def test_memory_review_presence_is_noninterfering() -> None:
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    observation = _observation(turns_since_memory_review=8)
    with_memory = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=observation,
            binding_tag="with-memory",
        ),
    )
    without_memory_catalog = [
        item for item in _FULL_CATALOG if item is not ResearchOperator.CONSOLIDATE_DREAMING
    ]
    without_memory = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=_shadow_input(
            observation=observation,
            mechanical=without_memory_catalog,
            binding_tag="without-memory",
        ),
    )

    assert [
        item
        for item in with_memory.candidate_catalog_ids
        if item is not ResearchOperator.CONSOLIDATE_DREAMING
    ] == without_memory.candidate_catalog_ids
    assert with_memory.suppressed_ids == without_memory.suppressed_ids
    assert len(with_memory.candidate_non_memory_continuing_ids) >= 3
    assert len(with_memory.candidate_non_memory_continuing_families) >= 2


def test_policy_disabled_and_text_or_binding_changes_do_not_change_catalog_logic(
    tmp_path: Path,
) -> None:
    observation = _observation(turns_since_memory_review=10)
    enabled_policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    disabled_policy = build_adaptive_operator_steering_policy(
        enabled=False,
        memory_review_debt_horizon=4,
    )
    first_input = _shadow_input(observation=observation, binding_tag="first")
    second_input = _shadow_input(observation=observation, binding_tag="second")
    first = build_adaptive_operator_steering_decision(
        policy=enabled_policy,
        shadow_input=first_input,
    )
    second = build_adaptive_operator_steering_decision(
        policy=enabled_policy,
        shadow_input=second_input,
    )
    disabled = build_adaptive_operator_steering_decision(
        policy=disabled_policy,
        shadow_input=first_input,
    )
    assert first.candidate_catalog_ids == second.candidate_catalog_ids
    assert first.stage == second.stage
    assert first.reasons == second.reasons
    assert first.decision_hash != second.decision_hash
    assert disabled.stage is AdaptiveOperatorSteeringStage.DISABLED_IDENTITY
    assert disabled.candidate_catalog_ids == disabled.baseline_catalog_ids

    structural_outputs: list[list[ResearchOperator]] = []
    for suffix, objective, scope in (
        ("one", "系统处理第一组通用目标。", "第一组范围只允许结构观察。"),
        ("two", "系统处理完全不同的通用目标。", "第二组范围仍只允许结构观察。"),
    ):
        store = RawMemoryStore(tmp_path / suffix / "vault")
        seed = create_adaptive_research_seed(
            loop_id=f"loop-{suffix}",
            project_id=f"project_{suffix}",
            objective_cn=objective,
            scope_cn=scope,
            raw_memory_store=store,
            captured_at=_NOW,
        )
        snapshot = initialize_adaptive_research_loop(
            seed=seed,
            policy=AdaptiveLoopPolicy(
                policy_id=f"policy-{suffix}",
                max_steps=2,
                max_model_calls=2,
                max_external_actions=1,
                max_temporary_agents=1,
                max_consecutive_stalls=2,
            ),
            raw_memory_store=store,
        )
        projected = build_adaptive_operator_steering_shadow_input(
            seed=seed,
            snapshot=snapshot,
            branch=snapshot.branches[0],
            mechanically_available_operator_ids=[item.value for item in _FULL_CATALOG],
        )
        structural_outputs.append(
            build_adaptive_operator_steering_decision(
                policy=enabled_policy,
                shadow_input=projected,
            ).candidate_catalog_ids
        )
    assert structural_outputs[0] == structural_outputs[1]


def test_deterministic_audit_hashes_and_write_once_receipts_fail_closed(
    tmp_path: Path,
) -> None:
    policy = build_adaptive_operator_steering_policy(memory_review_debt_horizon=4)
    first_input = _shadow_input(
        observation=_observation(turns_since_memory_review=8),
        binding_tag="audit-a",
    )
    second_input = _shadow_input(
        observation=_observation(turns_since_memory_review=3),
        binding_tag="audit-b",
    )
    first = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=first_input,
    )
    replayed = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=first_input,
    )
    assert replayed == first
    assert replayed.decision_hash == first.decision_hash

    audit = audit_adaptive_operator_steering_shadow(
        policy=policy,
        retained_inputs=[first_input, second_input],
    )
    assert audit.comparison_count == 2
    assert audit.baseline_catalog_remained_authoritative is True
    assert audit.candidate_catalog_was_not_executed is True
    assert audit.task_outcome_compared is False
    assert audit.task_benefit_verified is False
    assert audit.scientific_benefit_verified is False
    assert audit.innovation_verified is False

    old_input = first_input.model_dump(mode="json")
    old_input["schema_version"] = "adaptive-operator-steering-shadow-input-v0"
    with pytest.raises(ValidationError):
        AdaptiveOperatorSteeringShadowInput.model_validate(old_input)
    tampered = first.model_dump(mode="json")
    tampered["candidate_catalog_ids"] = list(reversed(tampered["candidate_catalog_ids"]))
    with pytest.raises(ValidationError):
        AdaptiveOperatorSteeringDecision.model_validate(tampered)

    development = build_adaptive_operator_steering_decision(
        policy=policy,
        shadow_input=first_input,
        application_mode=(AdaptiveOperatorSteeringApplicationMode.DEVELOPMENT_EVALUATION_ONLY),
    )
    receipt_path = tmp_path / adaptive_operator_steering_development_receipt_filename(development)
    seal_adaptive_operator_steering_development_decision(
        decision=development,
        receipt_path=receipt_path,
    )
    assert load_adaptive_operator_steering_development_decision(receipt_path) == development
    with pytest.raises(AdaptiveOperatorSteeringError, match="overwrite is forbidden"):
        seal_adaptive_operator_steering_development_decision(
            decision=development,
            receipt_path=receipt_path,
        )
    with pytest.raises(AdaptiveOperatorSteeringError, match="filename contract"):
        seal_adaptive_operator_steering_development_decision(
            decision=development,
            receipt_path=tmp_path / "wrong.json",
        )
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(AdaptiveOperatorSteeringError, match="exact canonical JSON"):
        load_adaptive_operator_steering_development_decision(receipt_path)


def test_module_has_no_task_or_hidden_oracle_dependency_and_rejects_extra_controls(
    retained_snapshot_case: tuple[
        RawMemoryStore,
        AdaptiveResearchSeed,
        AdaptiveResearchLoopSnapshot,
    ],
) -> None:
    source = inspect.getsource(steering_module).lower()
    for forbidden in (
        "adaptive_loop_benchmark",
        "hidden_oracle",
        ".objective_cn",
        ".scope_cn",
        ".title_cn",
        ".working_hypothesis_cn",
        "os.environ",
        "getenv(",
        "random.",
        "datetime.now",
    ):
        assert forbidden not in source

    policy = build_adaptive_operator_steering_policy()
    assert policy.reacts_to_research_text is False
    assert policy.reacts_to_system_name is False
    assert policy.may_add_capabilities is False
    assert policy.may_reorder_capabilities is False
    assert policy.may_choose_operator is False
    assert policy.may_force_memory_review is False
    assert policy.posterior_development_candidate is True
    assert policy.frozen_arm_change_authorized is False
    assert policy.production_adoption_authorized is False
    assert policy.formal_evidence_generated is False
    assert policy.task_benefit_verified is False
    assert policy.scientific_benefit_verified is False
    assert policy.innovation_verified is False

    _, seed, snapshot = retained_snapshot_case
    provider = ShadowAdaptiveOperatorCatalogProvider(policy)
    ordinary_kwargs: dict[str, Any] = {
        "seed": seed,
        "snapshot": snapshot,
        "branch": _child_branch(snapshot),
        "mechanically_available_operator_ids": [item.value for item in _FULL_CATALOG],
    }
    untyped_provider: Any = provider
    with pytest.raises(TypeError):
        untyped_provider(**ordinary_kwargs, run_root=Path("forbidden"))
    with pytest.raises(TypeError):
        untyped_provider(**ordinary_kwargs, execution_track="forbidden")
