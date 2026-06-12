from pathlib import Path

from autoresearch.knowledge import (
    KnowledgeEntryType,
    MarkdownKnowledgeStore,
    create_strategy_candidate,
    write_strategy_card_entry,
)
from autoresearch.schemas import StrategyCard, ValidationStatus


def test_write_strategy_card_entry_creates_linkable_obsidian_card(tmp_path: Path) -> None:
    strategy = StrategyCard(
        id="strategy_tool_router_v2",
        strategy_type="tool_routing_policy",
        version=2,
        content="Prefer cached literature tools before live search unless evidence is stale.",
        parent_strategy_id="strategy_tool_router_v1",
        evaluation_score=0.82,
        golden_test_status=ValidationStatus.PASSED,
        shadow_status=ValidationStatus.WARNING,
        release_status="candidate",
        rollback_target="strategy_tool_router_v1",
        failure_pattern_refs=("exploration/failure_patterns/recurring_failure_tool",),
        skill_card_refs=("exploration/skills/skill_cached_literature_first",),
        replay_result_refs=("projects/project_1/replay/replay_tool_router_v2",),
        golden_test_refs=("evaluation/golden/golden_tool_router_v1",),
        shadow_evaluation_refs=("evaluation/shadow/shadow_tool_router_v2",),
    )

    record = write_strategy_card_entry(
        vault_root=tmp_path,
        strategy=strategy,
        rationale="Reduce failed tool routing while preserving evidence coverage.",
        linked_refs=("exploration/topics/literature_search",),
    )
    relative_path = Path("exploration") / "strategy_cards" / "strategy_tool_router_v2.md"
    entry = MarkdownKnowledgeStore(tmp_path).read_entry(relative_path)
    markdown = record.path.read_text(encoding="utf-8")

    assert record.path == tmp_path / relative_path
    assert entry.entry_type is KnowledgeEntryType.STRATEGY_CARD
    assert "tool_routing_policy" in entry.tags
    assert "version-2" in entry.keywords
    assert "exploration/failure_patterns/recurring_failure_tool" in entry.source_refs
    assert "exploration/skills/skill_cached_literature_first" in entry.source_refs
    assert "evaluation/golden/golden_tool_router_v1" in entry.source_refs
    assert "[[exploration/failure_patterns/recurring_failure_tool]]" in markdown
    assert "[[exploration/skills/skill_cached_literature_first]]" in markdown
    assert "[[evaluation/shadow/shadow_tool_router_v2]]" in markdown
    assert "[[strategy_tool_router_v1]]" in markdown
    assert "Reduce failed tool routing while preserving evidence coverage." in entry.body


def test_create_strategy_candidate_preserves_parent_lineage(tmp_path: Path) -> None:
    parent = StrategyCard(
        id="strategy_retrieval_v1",
        strategy_type="retrieval_policy",
        version=1,
        content="Use conservative query expansion.",
        evaluation_score=0.76,
        golden_test_status=ValidationStatus.PASSED,
        shadow_status=ValidationStatus.PASSED,
        release_status="stable",
        failure_pattern_refs=("exploration/failure_patterns/recurring_failure_query",),
        skill_card_refs=("exploration/skills/skill_query_grounding",),
    )

    candidate = create_strategy_candidate(
        parent,
        candidate_id="strategy_retrieval_v2",
        content="Use gap-aware query expansion with citation validation.",
        evaluation_score=0.84,
        golden_test_status=ValidationStatus.PASSED,
        shadow_status=ValidationStatus.WARNING,
        release_status="shadow",
        replay_result_refs=("projects/project_1/replay/retrieval_v2",),
        golden_test_refs=("evaluation/golden/retrieval_v2",),
        shadow_evaluation_refs=("evaluation/shadow/retrieval_v2",),
    )

    write_strategy_card_entry(vault_root=tmp_path, strategy=parent, rationale="Stable baseline.")
    candidate_record = write_strategy_card_entry(
        vault_root=tmp_path,
        strategy=candidate,
        rationale="Candidate improves cross-check search coverage.",
    )
    entry = MarkdownKnowledgeStore(tmp_path).read_entry(
        "exploration/strategy_cards/strategy_retrieval_v2.md"
    )

    assert candidate.version == 2
    assert candidate.parent_strategy_id == parent.id
    assert candidate.rollback_target == parent.id
    assert candidate.strategy_type == parent.strategy_type
    assert candidate.evaluation_score == 0.84
    assert candidate.golden_test_status is ValidationStatus.PASSED
    assert candidate.shadow_status is ValidationStatus.WARNING
    assert candidate.release_status == "shadow"
    assert candidate.failure_pattern_refs == parent.failure_pattern_refs
    assert candidate.skill_card_refs == parent.skill_card_refs
    assert candidate.replay_result_refs == ("projects/project_1/replay/retrieval_v2",)
    assert candidate_record.path.exists()
    assert "strategy_retrieval_v1" in entry.source_refs
    assert "projects/project_1/replay/retrieval_v2" in entry.source_refs
    assert "evaluation/golden/retrieval_v2" in entry.source_refs
    assert "- Parent strategy: `strategy_retrieval_v1`" in entry.body
    assert "- Rollback target: `strategy_retrieval_v1`" in entry.body
