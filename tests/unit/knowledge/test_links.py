from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    extract_wiki_links,
)


def test_extract_wiki_links_supports_entry_ids_and_path_labels() -> None:
    body = "See [[paper_1]] and [[skills/review|review skill]]."

    assert extract_wiki_links(body) == ["paper_1", "skills/review"]


def test_store_maintains_backlinks_and_topic_index(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = MarkdownKnowledgeStore(tmp_path)
    paper = KnowledgeEntry(
        entry_id="paper_1",
        entry_type=KnowledgeEntryType.PAPER_NOTE,
        zone=KnowledgeZone.EXPLORATION,
        title="Paper One",
        keywords=[
            "alignment",
            "are",
            "adds",
            "candidate_deepseek_live_similarity",
            "autopilot_ai_researcher_task118_20260615023141",
            (
                "nearest-centroid baselines are reproducible and interpretable, but a publication "
                "claim requires checking whether variance-calibrated prototype distance has already "
                "been covered"
            ),
        ],
        body="A paper note.",
    )
    skill = KnowledgeEntry(
        entry_id="skill_review",
        entry_type=KnowledgeEntryType.SKILL_CARD,
        zone=KnowledgeZone.EXPLORATION,
        title="Review Skill",
        keywords=[
            "alignment",
            "review",
            "similarity_classification_coverage",
            "source-circuit-breakers.json.lock",
            "source-preflight",
        ],
        body="A skill card.",
    )
    experiment = KnowledgeEntry(
        entry_id="experiment_1",
        entry_type=KnowledgeEntryType.EXPERIMENT_RECORD,
        zone=KnowledgeZone.PROJECT,
        title="Experiment One",
        project_id="project-001",
        keywords=["experiment"],
        body="Uses [[paper_1]] and [[skills/review|review skill]].",
    )

    store.write_entry("papers/paper_1.md", paper)
    store.write_entry("skills/review.md", skill)
    store.write_entry("projects/project-001/experiments/experiment_1.md", experiment)

    loaded_paper = store.read_entry("papers/paper_1.md")
    loaded_skill = store.read_entry("skills/review.md")
    loaded_experiment = store.read_entry("projects/project-001/experiments/experiment_1.md")
    alignment_entries = store.find_by_keyword("alignment")
    topic_index = (tmp_path / "exploration" / "index.md").read_text(encoding="utf-8")

    assert loaded_experiment.links == ["paper_1", "skills/review"]
    assert loaded_paper.backlinks == ["experiment_1"]
    assert loaded_skill.backlinks == ["experiment_1"]
    assert {entry.entry_id for entry in alignment_entries} == {"paper_1", "skill_review"}
    assert "## alignment" in topic_index
    assert "## similarity classification coverage" in topic_index
    assert "## source-preflight" in topic_index
    assert "## adds" not in topic_index
    assert "## are" not in topic_index
    assert "nearest-centroid baselines are reproducible" not in topic_index
    assert "autopilot_ai_researcher_task118_20260615023141" not in topic_index
    assert "candidate_deepseek_live_similarity" not in topic_index
    assert "source-circuit-breakers.json.lock" not in topic_index
    assert "[[paper_1|Paper One]]" in topic_index
    assert "[[skill_review|Review Skill]]" in topic_index
