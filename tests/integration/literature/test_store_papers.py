from datetime import date, datetime, timezone
from pathlib import Path

from autoresearch.knowledge import KnowledgeEntryType, MarkdownKnowledgeStore
from autoresearch.literature import AcademicPaper, store_paper_notes


def test_store_mocked_retrieved_papers_as_knowledge_entries(tmp_path: Path) -> None:
    store = MarkdownKnowledgeStore(tmp_path)
    retrieved_at = datetime(2026, 6, 11, 10, 0, tzinfo=timezone.utc)
    papers = [
        AcademicPaper(
            title="Evidence First Research",
            authors=["A. Researcher"],
            abstract="Metadata abstract only.",
            publication_date=date(2026, 6, 1),
            venue="ExampleConf",
            doi="10.1234/example",
            url="https://example.com/paper",
            citation_count=3,
            source="arxiv",
        )
    ]

    documents = store_paper_notes(
        store,
        papers,
        project_id="project-001",
        retrieved_at=retrieved_at,
    )
    notes = list((tmp_path / "projects" / "project-001" / "knowledge").glob("*.md"))
    loaded = store.read_entry(notes[0].relative_to(tmp_path))

    assert len(documents) == 1
    assert documents[0].title == "Evidence First Research"
    assert documents[0].source_uri == "https://example.com/paper"
    assert loaded.entry_id == documents[0].id
    assert loaded.entry_type is KnowledgeEntryType.PAPER_NOTE
    assert loaded.source_refs == ["https://example.com/paper", "doi:10.1234/example"]
    assert "Metadata abstract only." in loaded.body
