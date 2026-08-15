from pathlib import Path

import pytest

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


def test_rebuild_indexes_skips_system_templates_and_preserves_unchanged_entries(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    store = MarkdownKnowledgeStore(tmp_path)
    template_path = tmp_path / "_system" / "templates" / "skill-card.md"
    template_path.parent.mkdir(parents=True)
    template_text = """---
entry_id: template_skill
entry_type: skill_card
zone: exploration
title: "{{skill_name}}"
keywords:
  - template-noise
links: []
backlinks: []
created_at: '2026-06-18T00:00:00Z'
updated_at: '2026-06-18T00:00:00Z'
---

# {{skill_name}}
"""
    template_path.write_text(template_text, encoding="utf-8")
    entry_path = tmp_path / "papers" / "paper_1.md"
    entry_path.parent.mkdir(parents=True)
    entry_text = """---
entry_id: paper_1
entry_type: paper_note
zone: exploration
title: Paper One
keywords:
  - alignment
links: []
backlinks: []
created_at: '2026-06-18T00:00:00Z'
updated_at: '2026-06-18T00:00:00Z'
---

Paper body.
"""
    entry_path.write_text(entry_text, encoding="utf-8")

    store.rebuild_indexes()

    topic_index = (tmp_path / "exploration" / "index.md").read_text(encoding="utf-8")
    assert template_path.read_text(encoding="utf-8") == template_text
    assert entry_path.read_text(encoding="utf-8") == entry_text
    assert "## alignment" in topic_index
    assert "template-noise" not in topic_index


def test_rebuild_indexes_never_reads_or_rewrites_private_raw_memory(
    tmp_path: Path,
) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    private_path = tmp_path / "_private" / "raw-memory" / "blobs" / "raw.md"
    private_path.parent.mkdir(parents=True)
    private_entry = KnowledgeEntry(
        entry_id="private-memory-title",
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id="project-001",
        title="绝不能进入公开索引的私有标题",
        keywords=["private-leak-marker"],
        body="[[public-note]]",
    )
    private_path.write_text(private_entry.to_markdown(), encoding="utf-8")
    original = private_path.read_bytes()

    store.rebuild_indexes()

    assert private_path.read_bytes() == original
    index = (tmp_path / "exploration" / "index.md").read_text(encoding="utf-8")
    assert "private-leak-marker" not in index
    assert "绝不能进入公开索引的私有标题" not in index


@pytest.mark.parametrize(
    "relative_path",
    [Path("_private/raw-memory/item.md"), Path("../outside.md")],
)
def test_markdown_store_refuses_private_or_escaping_paths(
    tmp_path: Path, relative_path: Path
) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    entry = KnowledgeEntry(
        entry_type=KnowledgeEntryType.EVIDENCE_NOTE,
        zone=KnowledgeZone.PROJECT,
        project_id="project-001",
        title="公开笔记",
        body="公开内容。",
    )

    with pytest.raises(ValueError, match="public-vault"):
        store.write_entry(relative_path, entry)
