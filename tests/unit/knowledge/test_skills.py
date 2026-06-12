from pathlib import Path

import pytest

from autoresearch.knowledge import (
    KnowledgeEntryType,
    MarkdownKnowledgeStore,
    SuccessfulPatternExample,
    extract_reusable_skill_card,
)


def test_extract_reusable_skill_card_writes_obsidian_entry(tmp_path: Path) -> None:
    examples = (
        SuccessfulPatternExample(
            project_id="project_a",
            experience_ref="projects/project_a/experience/baseline_first.md",
            summary="Baseline reproduction passed before ablation.",
            trigger_conditions=("new method idea", "public benchmark exists"),
            actions=("run baseline before ablation", "bind metrics to evidence"),
            success_metrics=("reproduction_success_rate > 0.9", "metric evidence coverage = 1.0"),
            evidence_refs=("projects/project_a/results/run_1",),
            related_task_ids=("task_baseline_a",),
            related_run_ids=("run_a_1",),
            tags=("baseline-first",),
        ),
        SuccessfulPatternExample(
            project_id="project_b",
            experience_ref="projects/project_b/experience/baseline_first.md",
            summary="Baseline-first plan avoided unsupported improvement claims.",
            trigger_conditions=("new method idea", "public benchmark exists"),
            actions=("run baseline before ablation", "reject unsupported metric claims"),
            success_metrics=("reproduction_success_rate > 0.9", "validator rejection rate decreases"),
            evidence_refs=("projects/project_b/results/run_2",),
            related_task_ids=("task_baseline_b",),
            related_run_ids=("run_b_2",),
            tags=("evidence-first",),
        ),
    )

    result = extract_reusable_skill_card(
        vault_root=tmp_path,
        name="Baseline-first experiment design",
        examples=examples,
        failure_pattern_refs=("exploration/failure_patterns/recurring_failure_metric",),
        tags=("experiment-design",),
        keywords=("baseline-first",),
    )

    assert result.skill_id == "skill_baseline_first_experiment_design"
    assert result.path == tmp_path / "exploration" / "skills" / (
        "skill_baseline_first_experiment_design.md"
    )

    store = MarkdownKnowledgeStore(tmp_path)
    entry = store.read_entry("exploration/skills/skill_baseline_first_experiment_design.md")
    markdown = result.path.read_text(encoding="utf-8")
    found_by_keyword = store.find_by_keyword("baseline-first")
    topic_index = (tmp_path / "exploration" / "index.md").read_text(encoding="utf-8")

    assert entry.entry_type is KnowledgeEntryType.SKILL_CARD
    assert entry.entry_id == "skill_baseline_first_experiment_design"
    assert {"skill", "skill-card", "reusable", "experiment-design"}.issubset(entry.tags)
    assert "baseline-first" in entry.keywords
    assert "reproduction_success_rate > 0.9" in entry.keywords
    assert entry.related_task_ids == ["task_baseline_a", "task_baseline_b"]
    assert entry.related_run_ids == ["run_a_1", "run_b_2"]
    assert "projects/project_a/experience/baseline_first" in entry.links
    assert "exploration/failure_patterns/recurring_failure_metric" in entry.links
    assert "[[projects/project_a/experience/baseline_first]]" in markdown
    assert "[[exploration/failure_patterns/recurring_failure_metric]]" in markdown
    assert "## Trigger Conditions" in markdown
    assert "## Actions" in markdown
    assert "## Success Metrics" in markdown
    assert {item.entry_id for item in found_by_keyword} == {
        "skill_baseline_first_experiment_design"
    }
    assert (
        "[[skill_baseline_first_experiment_design|Baseline-first experiment design]]"
        in topic_index
    )


def test_extract_reusable_skill_card_requires_repeated_successful_examples(
    tmp_path: Path,
) -> None:
    example = SuccessfulPatternExample(
        project_id="project_a",
        experience_ref="projects/project_a/experience/baseline_first",
        summary="One success is not yet reusable.",
        trigger_conditions=("new method idea",),
        actions=("run baseline",),
        success_metrics=("reproduction_success_rate > 0.9",),
    )

    with pytest.raises(ValueError, match="at least 2 successful examples"):
        extract_reusable_skill_card(
            vault_root=tmp_path,
            name="Baseline-first experiment design",
            examples=(example,),
        )


def test_extract_reusable_skill_card_rejects_incomplete_examples(tmp_path: Path) -> None:
    examples = (
        SuccessfulPatternExample(
            project_id="project_a",
            experience_ref="projects/project_a/experience/baseline_first",
            summary="Missing action.",
            trigger_conditions=("new method idea",),
            actions=(),
            success_metrics=("reproduction_success_rate > 0.9",),
        ),
        SuccessfulPatternExample(
            project_id="project_b",
            experience_ref="projects/project_b/experience/baseline_first",
            summary="Complete example.",
            trigger_conditions=("new method idea",),
            actions=("run baseline",),
            success_metrics=("reproduction_success_rate > 0.9",),
        ),
    )

    with pytest.raises(ValueError, match="at least one action"):
        extract_reusable_skill_card(
            vault_root=tmp_path,
            name="Baseline-first experiment design",
            examples=examples,
        )
