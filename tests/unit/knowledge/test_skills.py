from pathlib import Path

import pytest

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    SkillRetrievalQuery,
    SuccessfulPatternExample,
    audit_skill_polish_candidate,
    create_skill_evolution_candidate,
    default_external_research_skill_candidates,
    extract_reusable_skill_card,
    retrieve_relevant_skills,
    write_external_skill_watchlist,
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


def test_write_external_skill_watchlist_keeps_candidates_quarantined(
    tmp_path: Path,
) -> None:
    candidates = default_external_research_skill_candidates()

    watchlist = write_external_skill_watchlist(
        vault_root=tmp_path,
        candidates=candidates,
        source_note="User screenshot and web source review.",
    )

    markdown = watchlist.path.read_text(encoding="utf-8")
    store = MarkdownKnowledgeStore(tmp_path)
    entry = store.read_entry(watchlist.relative_path)

    assert watchlist.relative_path == "exploration/skills/external-research-skill-watchlist.md"
    assert entry.entry_id == "external_research_skill_watchlist"
    assert entry.entry_type is KnowledgeEntryType.REVIEW_NOTE
    assert "quarantine" in entry.tags
    assert "external-skill" in entry.keywords
    assert "CCFA-Skill" in markdown
    assert "Question-Validator" in markdown
    assert "Omni-SimpleMem / SimpleMem" in markdown
    assert "SkillClaw" in markdown
    assert "oh-my-openagent / LazyCodex" in markdown
    assert "reference-only-license-risk" in markdown
    assert "Do not copy, vendor, adapt, or enable third-party skill text" in markdown
    assert "https://github.com/aiming-lab/SimpleMem" in entry.source_refs
    assert "https://github.com/AMAP-ML/SkillClaw" in entry.source_refs
    assert "https://github.com/code-yeongyu/oh-my-openagent" in entry.source_refs
    assert len(watchlist.candidate_ids) >= 13


def test_write_external_skill_watchlist_requires_evidence_fields(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one external skill candidate"):
        write_external_skill_watchlist(vault_root=tmp_path, candidates=())


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


def test_retrieve_relevant_skills_matches_frontmatter_and_obsidian_links(
    tmp_path: Path,
) -> None:
    baseline_skill = _write_baseline_skill(tmp_path)
    extract_reusable_skill_card(
        vault_root=tmp_path,
        name="Citation validation before drafting",
        examples=(
            SuccessfulPatternExample(
                project_id="project_c",
                experience_ref="projects/project_c/experience/citation_validation",
                summary="Citation validation caught unsupported references.",
                trigger_conditions=("paper drafting",),
                actions=("validate DOI and URL evidence",),
                success_metrics=("citation_error_rate < 0.01",),
            ),
            SuccessfulPatternExample(
                project_id="project_d",
                experience_ref="projects/project_d/experience/citation_validation",
                summary="DOI checks prevented fabricated citation claims.",
                trigger_conditions=("paper drafting",),
                actions=("validate DOI and URL evidence",),
                success_metrics=("citation_error_rate < 0.01",),
            ),
        ),
        tags=("citation",),
        keywords=("citation",),
    )
    store = MarkdownKnowledgeStore(tmp_path)
    store.write_entry(
        "exploration/topics/baseline_plan.md",
        KnowledgeEntry(
            entry_id="topic_baseline_plan",
            entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
            zone=KnowledgeZone.EXPLORATION,
            title="Baseline planning topic",
            tags=["topic"],
            keywords=["baseline-first"],
            body=f"Use [[{baseline_skill.skill_id}]] for baseline-first experiment plans.",
        ),
    )

    matches = retrieve_relevant_skills(
        vault_root=tmp_path,
        query=SkillRetrievalQuery(
            title="Plan a baseline-first ablation",
            description="A new method idea has a public benchmark and needs evidence binding.",
            metadata={"trigger": "new method idea", "topic_ref": "exploration/topics/baseline_plan"},
            tags=("experiment-design",),
            keywords=("baseline-first", "reproduction_success_rate > 0.9"),
            links=("exploration/topics/baseline_plan",),
        ),
    )

    assert matches
    assert matches[0].skill_id == baseline_skill.skill_id
    assert any("frontmatter" in reason for reason in matches[0].reasons)
    assert any("Obsidian" in reason for reason in matches[0].reasons)


def test_retrieve_relevant_skills_rejects_invalid_limits(tmp_path: Path) -> None:
    query = SkillRetrievalQuery(title="Any task")

    with pytest.raises(ValueError, match="limit"):
        retrieve_relevant_skills(vault_root=tmp_path, query=query, limit=0)
    with pytest.raises(ValueError, match="min_score"):
        retrieve_relevant_skills(vault_root=tmp_path, query=query, min_score=-1)


def test_create_skill_evolution_candidate_writes_bounded_candidate_and_buffer(
    tmp_path: Path,
) -> None:
    parent = _write_baseline_skill(tmp_path)

    candidate = create_skill_evolution_candidate(
        vault_root=tmp_path,
        parent_skill_id=parent.skill_id,
        change_summary="Require evidence bundle review before treating a demo as reusable.",
        issue_refs=("projects/project_a/issues/llm_review_missing_evidence",),
        failure_pattern_refs=("exploration/failure_patterns/recurring_unsupported_claims",),
        proposed_actions=(
            "include run-record evidence before LLM review",
            "reject reports with unsupported reproduction metadata",
        ),
        validation_checks=(
            "real LLM review score >= 0.85",
            "held-out demo report has zero unsupported reproduction claims",
        ),
    )

    store = MarkdownKnowledgeStore(tmp_path)
    entry = store.read_entry(
        f"exploration/skills/candidates/{candidate.candidate_skill_id}.md"
    )
    buffer_entry = store.read_entry(
        f"exploration/skills/rejected/{candidate.candidate_skill_id}_rejections.md"
    )
    markdown = candidate.path.read_text(encoding="utf-8")

    assert candidate.parent_skill_id == parent.skill_id
    assert candidate.path == tmp_path / "exploration" / "skills" / "candidates" / (
        f"{candidate.candidate_skill_id}.md"
    )
    assert entry.entry_type is KnowledgeEntryType.SKILL_CARD
    assert "skill-evolution" in entry.tags
    assert "shadow-evaluation" in entry.tags
    assert "projects/project_a/issues/llm_review_missing_evidence" in entry.source_refs
    assert "exploration/failure_patterns/recurring_unsupported_claims" in entry.source_refs
    assert "## Validation Gate" in markdown
    assert "## Shadow Evaluation Notes" in markdown
    assert "[[exploration/skills/rejected/" in markdown
    assert buffer_entry.entry_type is KnowledgeEntryType.EVIDENCE_NOTE
    assert "rejected-edit-buffer" in buffer_entry.tags


def test_create_skill_evolution_candidate_requires_evidence_and_validation(
    tmp_path: Path,
) -> None:
    parent = _write_baseline_skill(tmp_path)

    with pytest.raises(ValueError, match="issue_ref or failure_pattern_ref"):
        create_skill_evolution_candidate(
            vault_root=tmp_path,
            parent_skill_id=parent.skill_id,
            change_summary="No evidence should be rejected.",
            issue_refs=(),
            proposed_actions=("do something",),
            validation_checks=("check something",),
        )
    with pytest.raises(ValueError, match="validation check"):
        create_skill_evolution_candidate(
            vault_root=tmp_path,
            parent_skill_id=parent.skill_id,
            change_summary="No validation should be rejected.",
            issue_refs=("projects/project_a/issues/issue",),
            proposed_actions=("do something",),
            validation_checks=(),
        )


def test_audit_skill_polish_candidate_passes_with_luban_style_evidence(
    tmp_path: Path,
) -> None:
    parent = _write_baseline_skill(tmp_path)
    candidate = create_skill_evolution_candidate(
        vault_root=tmp_path,
        parent_skill_id=parent.skill_id,
        change_summary="Add held-out validation and peer positioning before promotion.",
        issue_refs=("projects/project_a/issues/skill_missing_peer_positioning",),
        proposed_actions=("compare peer skills before promotion",),
        validation_checks=("held-out validation report passes",),
    )

    report = audit_skill_polish_candidate(
        vault_root=tmp_path,
        skill_id=candidate.candidate_skill_id,
        peer_refs=("https://github.com/LearnPrompt/luban-skill",),
        live_evidence_refs=("runs/skill-polish/demo-validation.json",),
        install_refs=(".opencode/skills/ai-researcher-evidence-gate/SKILL.md",),
        release_refs=("autoresearch-vault/exploration/skills/rejected/demo_rejections.md",),
    )

    assert report.passed
    assert report.score_ratio == 1.0
    assert {check.check_id for check in report.checks} == {
        "material_challenge",
        "peer_positioning",
        "measurement_gate",
        "bounded_edit",
        "installable_asset",
        "furnace_loop",
    }
    assert "LearnPrompt/luban-skill" in report.to_json_dict()["reference"]
    assert "Skill polish audit" in report.to_markdown()


def test_audit_skill_polish_candidate_blocks_missing_public_evidence(
    tmp_path: Path,
) -> None:
    parent = _write_baseline_skill(tmp_path)
    candidate = create_skill_evolution_candidate(
        vault_root=tmp_path,
        parent_skill_id=parent.skill_id,
        change_summary="Add held-out validation and peer positioning before promotion.",
        issue_refs=("projects/project_a/issues/skill_missing_peer_positioning",),
        proposed_actions=("compare peer skills before promotion",),
        validation_checks=("held-out validation report passes",),
    )

    report = audit_skill_polish_candidate(
        vault_root=tmp_path,
        skill_id=candidate.candidate_skill_id,
        live_evidence_refs=("runs/skill-polish/demo-validation.json",),
    )

    assert not report.passed
    failed = {check.check_id for check in report.checks if not check.passed}
    assert {"peer_positioning", "installable_asset", "furnace_loop"}.issubset(failed)


def test_audit_skill_polish_candidate_rejects_invalid_score(tmp_path: Path) -> None:
    parent = _write_baseline_skill(tmp_path)

    with pytest.raises(ValueError, match="min_score"):
        audit_skill_polish_candidate(
            vault_root=tmp_path,
            skill_id=parent.skill_id,
            min_score=1.5,
        )


def _write_baseline_skill(tmp_path: Path):
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
    return extract_reusable_skill_card(
        vault_root=tmp_path,
        name="Baseline-first experiment design",
        examples=examples,
        failure_pattern_refs=("exploration/failure_patterns/recurring_failure_metric",),
        tags=("experiment-design",),
        keywords=("baseline-first",),
    )
