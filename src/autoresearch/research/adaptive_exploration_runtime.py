"""Safe production entry points for model-selected adaptive research turns."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.adaptive_skill_router import RepositoryQwenSkillProvider
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchActionEnvironment,
    ResearchOperator,
    create_adaptive_research_seed,
    run_adaptive_research_loop,
)

CompletionCallable = Callable[..., LLMJsonCompletionResult]


class _ConceptualOnlyEnvironment(ResearchActionEnvironment):
    """Unreachable adapter while the public command has zero external budget."""

    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset()

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        del seed, snapshot, proposal
        raise AdaptiveResearchLoopError(
            "conceptual adaptive exploration cannot invoke external capabilities"
        )


def run_conceptual_adaptive_exploration(
    *,
    loop_id: str,
    project_id: str,
    objective_cn: str,
    scope_cn: str,
    output_dir: Path | str,
    vault_root: Path | str = Path("autoresearch-vault"),
    skill_root: Path | str = Path("skills"),
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_steps: int = 4,
    maximum_selected_skills: int = 4,
    thinking_budget: int = 2_000,
) -> AdaptiveResearchLoopSnapshot:
    """Run real Qwen-selected conceptual steps from one non-scientific seed.

    This is intentionally an exploration-only production entry point.  It
    proves the controller can self-loop without intermediate operator prompts,
    while retrieval, temporary agents, sandbox execution, promotion, approval,
    and publication remain unavailable until their concrete adapters are wired.
    """

    output_root = Path(output_dir).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise AdaptiveResearchLoopError(
            "adaptive exploration output directory must be new or empty"
        )
    if max_steps < 1 or max_steps > 100:
        raise AdaptiveResearchLoopError("conceptual adaptive step budget is outside bounds")
    store = RawMemoryStore(vault_root)
    seed = create_adaptive_research_seed(
        loop_id=loop_id,
        project_id=project_id,
        objective_cn=objective_cn,
        scope_cn=scope_cn,
        raw_memory_store=store,
    )
    skill_provider = RepositoryQwenSkillProvider(
        skill_root=skill_root,
        output_dir=output_root,
        raw_memory_store=store,
        config_path=config_path,
        env_path=env_path,
        maximum_selected_skills=maximum_selected_skills,
        thinking_budget=thinking_budget,
    )
    result = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            schema_version="adaptive-sovereign-loop-policy-v3",
            policy_id="conceptual-open-exploration-v3",
            max_steps=max_steps,
            max_model_calls=max_steps * 4,
            max_external_actions=0,
            max_temporary_agents=0,
            thinking_budget=thinking_budget,
        ),
        raw_memory_store=store,
        output_dir=output_root,
        environment=_ConceptualOnlyEnvironment(),
        skill_provider=skill_provider,
        config_path=config_path,
        env_path=env_path,
    )
    _write_runtime_autonomy_audit(output_root, store, result)
    return result


def run_capability_adaptive_exploration(
    *,
    loop_id: str,
    project_id: str,
    objective_cn: str,
    scope_cn: str,
    output_dir: Path | str,
    vault_root: Path | str = Path("autoresearch-vault"),
    skill_root: Path | str = Path("skills"),
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_steps: int = 8,
    max_external_actions: int = 4,
    max_temporary_agents: int = 7,
    maximum_selected_skills: int = 4,
    max_results_per_source: int = 6,
    temporary_max_workers: int = 4,
    thinking_budget: int = 2_000,
    completion: CompletionCallable = run_llm_json_completion,
    literature_clients: Mapping[str, Any] | None = None,
) -> AdaptiveResearchLoopSnapshot:
    """Run one Qwen-controlled loop with only genuinely wired capabilities.

    The main agent selects every operator after the initial Chinese objective and
    scope.  Real literature retrieval, private append-only raw capture,
    rebuildable Dreaming, dynamic repository skill routing, and main-agent-owned
    temporary Qwen dispatch are available.  A separate Qwen reviewer is invoked
    only after the main agent asks to promote a branch and the deterministic
    promotion gate passes.  That reviewer can pause the loop for human scope
    approval, but it cannot authorize an experiment or publication.  Generic
    sandbox execution remains unavailable.
    """

    # Imported lazily so the large competition package used by the temporary
    # pool cannot create a research-package import cycle for conceptual users.
    from autoresearch.research.adaptive_capabilities import (
        AdaptiveResearchCapabilityEnvironment,
        TemporaryQwenResearchDispatcher,
    )
    from autoresearch.research.adaptive_promotion_verifier import (
        IndependentQwenPromotionVerifier,
    )

    output_root = Path(output_dir).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise AdaptiveResearchLoopError(
            "adaptive capability output directory must be new or empty"
        )
    if max_steps < 1 or max_steps > 100:
        raise AdaptiveResearchLoopError("adaptive step budget is outside bounds")
    if max_external_actions < 0 or max_external_actions > max_steps:
        raise AdaptiveResearchLoopError(
            "adaptive external-action budget must be between zero and max_steps"
        )
    if max_temporary_agents < 0 or max_temporary_agents > 49:
        raise AdaptiveResearchLoopError("adaptive temporary-agent budget is outside bounds")
    if temporary_max_workers < 1 or temporary_max_workers > 7:
        raise AdaptiveResearchLoopError("adaptive temporary worker bound is outside policy")

    store = RawMemoryStore(vault_root)
    seed = create_adaptive_research_seed(
        loop_id=loop_id,
        project_id=project_id,
        objective_cn=objective_cn,
        scope_cn=scope_cn,
        raw_memory_store=store,
    )
    skill_provider = RepositoryQwenSkillProvider(
        skill_root=skill_root,
        output_dir=output_root,
        raw_memory_store=store,
        config_path=config_path,
        env_path=env_path,
        maximum_selected_skills=maximum_selected_skills,
        thinking_budget=thinking_budget,
        completion=completion,
    )
    environment = AdaptiveResearchCapabilityEnvironment(
        output_dir=output_root,
        raw_memory_store=store,
        literature_clients=literature_clients,
        max_results_per_source=max_results_per_source,
    )
    temporary_dispatcher = (
        TemporaryQwenResearchDispatcher(
            output_dir=output_root,
            skill_root=skill_root,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
            max_workers=temporary_max_workers,
            thinking_budget=thinking_budget,
        )
        if max_temporary_agents
        else None
    )
    promotion_verifier = IndependentQwenPromotionVerifier(
        output_dir=output_root,
        raw_memory_store=store,
        skill_root=skill_root,
        completion=completion,
        config_path=config_path,
        env_path=env_path,
        thinking_budget=thinking_budget,
    )
    result = run_adaptive_research_loop(
        seed=seed,
        policy=AdaptiveLoopPolicy(
            schema_version="adaptive-sovereign-loop-policy-v3",
            policy_id="capability-open-exploration-v3",
            max_steps=max_steps,
            max_model_calls=max_steps * 4,
            max_external_actions=max_external_actions,
            max_temporary_agents=max_temporary_agents,
            thinking_budget=thinking_budget,
        ),
        raw_memory_store=store,
        output_dir=output_root,
        environment=environment,
        temporary_dispatcher=temporary_dispatcher,
        promotion_verifier=promotion_verifier,
        skill_provider=skill_provider,
        completion=completion,
        config_path=config_path,
        env_path=env_path,
    )
    _write_runtime_autonomy_audit(output_root, store, result)
    return result


def _write_runtime_autonomy_audit(
    output_root: Path,
    store: RawMemoryStore,
    snapshot: AdaptiveResearchLoopSnapshot,
) -> None:
    from autoresearch.research.adaptive_autonomy_audit import (
        audit_adaptive_research_autonomy,
    )
    from autoresearch.research.adaptive_memory_loop_audit import (
        audit_adaptive_memory_loop,
    )

    snapshot_path = output_root / "snapshots" / (
        f"step-{snapshot.next_step_index - 1:04d}-{snapshot.snapshot_hash}.json"
    )
    audit_adaptive_research_autonomy(
        snapshot_path,
        raw_memory_store=store,
        output_path=output_root / "adaptive-autonomy-audit.json",
    )
    audit_adaptive_memory_loop(
        snapshot_path,
        raw_memory_store=store,
        output_path=output_root / "adaptive-memory-loop-audit.json",
    )


__all__ = [
    "run_capability_adaptive_exploration",
    "run_conceptual_adaptive_exploration",
]
