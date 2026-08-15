from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.kernel.contracts import canonical_json, canonical_sha256
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.research.adaptive_capabilities import (
    AdaptiveResearchCapabilityEnvironment,
)
from autoresearch.research.adaptive_loop_benchmark_context import (
    AdaptiveLoopBenchmarkPublicContextAdapter,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    write_adaptive_loop_benchmark_execution_protocol,
)
from autoresearch.research.adaptive_memory_loop_audit import (
    audit_adaptive_memory_loop,
)
from autoresearch.research.adaptive_operator_steering import (
    DevelopmentAdaptiveOperatorCatalogProvider,
    adaptive_operator_steering_development_receipt_filename,
    build_adaptive_operator_steering_policy,
    load_adaptive_operator_steering_development_decision,
)
from autoresearch.research.adaptive_skill_router import RepositoryQwenSkillProvider
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveExternalTurnContext,
    AdaptiveLoopPolicy,
    AdaptiveLoopRunStatus,
    AdaptiveResearchBranch,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchOperator,
    create_adaptive_research_seed,
    run_adaptive_research_loop,
)


class _DreamingOnlyCapabilityEnvironment:
    """Keep the delayed-relevance pilot inside its frozen no-network scope."""

    def __init__(self, delegate: AdaptiveResearchCapabilityEnvironment) -> None:
        self._delegate = delegate

    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset({ResearchOperator.CONSOLIDATE_DREAMING})

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        if proposal.operator is not ResearchOperator.CONSOLIDATE_DREAMING:
            raise AssertionError("delayed-relevance pilot may execute only local Dreaming")
        return self._delegate.execute(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
        )


class _TerminalBoundedPublicContextProvider:
    """Stop public stimulus injection after the frozen scenario terminal turn."""

    def __init__(
        self,
        delegate: AdaptiveLoopBenchmarkPublicContextAdapter,
        *,
        terminal_turn_index: int,
    ) -> None:
        self._delegate = delegate
        self._terminal_turn_index = terminal_turn_index

    def contexts_for_turn(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
    ) -> tuple[AdaptiveExternalTurnContext, ...]:
        if snapshot.next_step_index > self._terminal_turn_index:
            return ()
        return self._delegate.contexts_for_turn(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
        )


def test_real_qwen_development_policy_recalls_and_consumes_sovereign_memory() -> None:
    """One fresh, nonconfirmatory run; never a benchmark or benefit claim."""

    if os.getenv("RUN_LIVE_ADAPTIVE_OPERATOR_STEERING") != "1":
        pytest.skip("set RUN_LIVE_ADAPTIVE_OPERATOR_STEERING=1 for the fresh development pilot")
    run_id = os.getenv("ADAPTIVE_OPERATOR_STEERING_LIVE_RUN_ID")
    if not run_id or run_id.strip() != run_id:
        pytest.fail("ADAPTIVE_OPERATOR_STEERING_LIVE_RUN_ID must name one fresh retained run")

    root = Path("runs/manual-live") / run_id
    if root.exists():
        pytest.fail(f"adaptive operator-steering run already exists: {root}")
    root.mkdir(parents=True)
    loop_root = root / "loop"
    decision_root = loop_root / "operator-steering-decisions"
    decision_root.mkdir(parents=True)
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        root / "delayed-relevance-protocol",
        randomization_seed=27_132_026,
    )
    scenario = bundle.protocol.public_scenarios[0]
    assert scenario.challenge_kind == "delayed_relevance"
    blinded_cell = next(
        cell for cell in bundle.blinded_cells.cells if cell.scenario_id == scenario.scenario_id
    )
    store = RawMemoryStore(root / "autoresearch-vault")
    public_context = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=blinded_cell,
        raw_memory_store=store,
    )

    objective_cn = scenario.objective_cn
    scope_cn = scenario.scope_cn
    seed = create_adaptive_research_seed(
        loop_id=f"{run_id}-loop",
        project_id=run_id.replace("-", "_"),
        objective_cn=objective_cn,
        scope_cn=scope_cn,
        raw_memory_store=store,
    )
    loop_policy = AdaptiveLoopPolicy(
        schema_version="adaptive-sovereign-loop-policy-v3",
        policy_id="adaptive-operator-steering-fresh-development-v3",
        max_steps=15,
        max_model_calls=45,
        max_external_actions=15,
        max_temporary_agents=0,
        max_active_branches=12,
        max_consecutive_stalls=20,
        maximum_skill_contexts=3,
        thinking_budget=2_000,
    )
    steering_policy = build_adaptive_operator_steering_policy(
        policy_id="adaptive-operator-steering-posterior-development-v1",
        recent_branch_window=4,
        consecutive_family_repetition_threshold=3,
        # The generic prompt contains the most recent eight events.  Nine is
        # therefore the first horizon at which an event can be outside it.
        memory_review_debt_horizon=9,
    )
    config = ConfigParser().parse_file("config.yaml", model_type=SystemConfig)
    assert isinstance(config, SystemConfig)
    _write_pilot_protocol_once(
        root / "adaptive-operator-steering-live-protocol.json",
        {
            "schema_version": "adaptive-operator-steering-live-protocol-v1",
            "run_id": run_id,
            "public_scenario_hash": scenario.public_scenario_hash,
            "blinded_cell_binding_hash": canonical_sha256(blinded_cell.model_dump(mode="json")),
            "objective_cn": objective_cn,
            "scope_cn": scope_cn,
            "configured_model_name": config.deployment.llm.model_name,
            "loop_policy": loop_policy.model_dump(mode="json"),
            "steering_policy": steering_policy.model_dump(mode="json"),
            "source_hashes": _pilot_source_hashes(),
            "success_checks_frozen_before_first_model_call": [
                "至少一个目录决策实际改变开放候选集",
                "每次干预仍保留多动作、多家族以及停止、放弃和晋级边界",
                "逐轮只注入冻结公共场景的一条刺激且不暴露隐藏判定",
                "主Agent自主选择Dreaming并召回离开最近八轮窗口的原始记录",
                "Dreaming反馈逐字进入后续模型请求",
                "后续原始模型JSON包含与暴露记录精确绑定的结构化消费声明",
                "启动后人工和编排器科研散文计数保持为零",
            ],
            "ordinary_client_transport_is_independent_identity_evidence": False,
            "nonconfirmatory": True,
            "scientific_result": False,
            "causal_memory_benefit_verified": False,
            "innovation_verified": False,
            "production_adoption_authorized": False,
        },
    )

    steering = DevelopmentAdaptiveOperatorCatalogProvider(
        steering_policy,
        decision_receipt_path_provider=lambda decision: decision_root
        / adaptive_operator_steering_development_receipt_filename(decision),
    )
    skills = RepositoryQwenSkillProvider(
        skill_root=Path("skills"),
        output_dir=loop_root,
        raw_memory_store=store,
        maximum_selected_skills=3,
        thinking_budget=2_000,
    )
    capabilities = _DreamingOnlyCapabilityEnvironment(
        AdaptiveResearchCapabilityEnvironment(
            output_dir=loop_root,
            raw_memory_store=store,
            max_results_per_source=3,
        )
    )

    delayed_relevance_contexts = _TerminalBoundedPublicContextProvider(
        public_context,
        terminal_turn_index=scenario.terminal_turn_index,
    )

    snapshot = run_adaptive_research_loop(
        seed=seed,
        policy=loop_policy,
        raw_memory_store=store,
        output_dir=loop_root,
        environment=capabilities,
        operator_catalog_provider=steering,
        external_turn_context_provider=delayed_relevance_contexts,
        skill_provider=skills,
    )

    assert snapshot.status in {
        AdaptiveLoopRunStatus.PAUSED_BUDGET,
        AdaptiveLoopRunStatus.STOPPED_BY_MODEL,
        AdaptiveLoopRunStatus.PAUSED_HUMAN_SCOPE,
        AdaptiveLoopRunStatus.PAUSED_VERIFIER_REQUIRED,
    }
    assert steering.decisions
    assert len(steering.decisions) == len(snapshot.events)
    assert len(steering.sealed_receipt_paths) == len(steering.decisions)
    assert any(decision.controller_intervened for decision in steering.decisions)
    for decision, receipt_path in zip(
        steering.decisions,
        steering.sealed_receipt_paths,
        strict=True,
    ):
        assert load_adaptive_operator_steering_development_decision(receipt_path) == (decision)
        assert decision.candidate_applied is True
        assert decision.nonconfirmatory is True
        assert decision.production_adoption_authorized is False
        if decision.controller_intervened:
            assert len(decision.candidate_continuing_research_ids) >= 4
            assert len(decision.candidate_non_memory_continuing_ids) >= 3
            assert len(decision.candidate_non_memory_continuing_families) >= 2
            assert all(
                boundary in decision.candidate_catalog_ids
                for boundary in (
                    ResearchOperator.PROMOTE_BRANCH,
                    ResearchOperator.ABANDON_BRANCH,
                    ResearchOperator.STOP_EXPLORATION,
                )
                if boundary in decision.mechanical_input_ids
            )

    assert all(
        event.interaction.model_name == config.deployment.llm.model_name
        and event.interaction.reasoning_character_count >= 200
        and event.interaction.hand_written_scientific_prose_count == 0
        and event.interaction.proposal.human_authored_scientific_prose_count == 0
        and event.orchestrator_scientific_prose_count == 0
        and not event.execution_authorized
        and not event.publication_authorized
        for event in snapshot.events
    )
    skill_messages = [
        json.loads(message["content"])
        for event in snapshot.events
        for message in event.interaction.messages
        if message["role"] == "user"
        and '"context_kind": "selected_project_method_skill"' in message["content"]
    ]
    assert snapshot.skill_routing_model_call_count == len(snapshot.events)
    assert all(
        message["context_kind"] == "selected_project_method_skill"
        and isinstance(message["skill_id"], str)
        and message["skill_id"]
        for message in skill_messages
    )
    assert all(
        "# Agent记忆评估" not in event.interaction.messages[0]["content"]
        for event in snapshot.events
    )

    final_snapshot_path = (
        loop_root / "snapshots" / f"step-{len(snapshot.events):04d}-{snapshot.snapshot_hash}.json"
    )
    assert final_snapshot_path.is_file()
    memory_audit = audit_adaptive_memory_loop(
        final_snapshot_path,
        raw_memory_store=store,
        output_path=root / "adaptive-memory-loop-audit.json",
    )
    assert memory_audit.controller_memory_transport_verified is True
    assert memory_audit.older_than_recent_event_window_recalled is True
    assert memory_audit.exact_recall_exposed_to_later_model is True
    assert any(event.interaction.proposal.memory_consumption_claims for event in snapshot.events)
    assert memory_audit.causal_memory_benefit_verified is False
    assert memory_audit.scientific_correctness_verified is False
    assert memory_audit.innovation_verified is False


def _pilot_source_hashes() -> dict[str, str]:
    paths = [
        Path(__file__),
        Path("config.yaml"),
        Path("src/autoresearch/research/adaptive_operator_steering.py"),
        Path("src/autoresearch/research/adaptive_sovereign_loop.py"),
        Path("src/autoresearch/research/adaptive_capabilities.py"),
        Path("src/autoresearch/research/adaptive_loop_benchmark_context.py"),
        Path("src/autoresearch/research/adaptive_loop_benchmark_execution_protocol.py"),
        Path("src/autoresearch/research/adaptive_skill_router.py"),
        *sorted(Path("skills").glob("*/SKILL.md")),
    ]
    return {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _write_pilot_protocol_once(path: Path, payload: dict[str, object]) -> None:
    bound = {**payload, "protocol_hash": canonical_sha256(payload)}
    serialized = (canonical_json(bound) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(serialized)
