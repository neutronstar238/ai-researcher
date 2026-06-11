from pathlib import Path

import pytest

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)


@pytest.mark.parametrize("entry_type", list(KnowledgeEntryType))
def test_markdown_store_round_trips_each_knowledge_entry_type(
    tmp_path: Path, entry_type: KnowledgeEntryType
) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    entry = KnowledgeEntry(
        entry_type=entry_type,
        zone=KnowledgeZone.PROJECT,
        title=f"Example {entry_type.value}",
        project_id="project-001",
        tags=["trusted-loop", entry_type.value],
        keywords=["evidence", "obsidian"],
        source_refs=["doc_1"],
        related_task_ids=["task_1"],
        related_run_ids=["run_1"],
        body=f"# Example\n\nBody for {entry_type.value}.",
    )

    path = store.write_entry(Path("project-001") / f"{entry_type.value}.md", entry)
    loaded = store.read_entry(Path("project-001") / f"{entry_type.value}.md")

    assert path.is_file()
    assert loaded == entry


def test_markdown_entry_frontmatter_is_yaml_and_body_stays_readable() -> None:
    entry = KnowledgeEntry(
        entry_id="entry_fixed",
        entry_type=KnowledgeEntryType.SKILL_CARD,
        zone=KnowledgeZone.EXPLORATION,
        title="Failure review skill",
        tags=["skill"],
        keywords=["review"],
        source_refs=["manual"],
        related_task_ids=["task_1"],
        related_run_ids=["run_1"],
        body="Use evidence before claims.\n\nLink to [[entry_fixed]].",
    )

    markdown = entry.to_markdown()
    loaded = KnowledgeEntry.from_markdown(markdown)

    assert markdown.startswith("---\n")
    assert "entry_id: entry_fixed" in markdown
    assert "entry_type: skill_card" in markdown
    assert "zone: exploration" in markdown
    assert "Use evidence before claims." in markdown
    assert loaded == entry


def test_markdown_entry_rejects_missing_frontmatter() -> None:
    with pytest.raises(ValueError):
        KnowledgeEntry.from_markdown("# Missing frontmatter")
