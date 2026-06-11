from hypothesis import given
from hypothesis import strategies as st

from autoresearch.literature import AcademicPaper, deduplicate_papers


def _paper(title: str, *, doi: str | None = None, source: str = "arxiv") -> AcademicPaper:
    return AcademicPaper(
        title=title,
        authors=["A. Researcher"],
        abstract="A study.",
        doi=doi,
        url="https://example.com/paper",
        citation_count=1,
        source=source,
    )


@given(
    doi_suffix=st.from_regex(r"10\.[0-9]{4}/[a-z0-9.-]{3,16}", fullmatch=True),
    title=st.sampled_from(
        [
            "Efficient Evidence Graphs for Automated Research",
            "Robust Sandbox Execution for Scientific Agents",
            "Obsidian Knowledge Bases for Self-Evolving Research Loops",
        ]
    ),
)
def test_deduplicate_papers_removes_case_insensitive_doi_duplicates(
    doi_suffix: str, title: str
) -> None:
    papers = [
        _paper(title, doi=doi_suffix, source="arxiv"),
        _paper(f"{title} extended", doi=f"DOI:{doi_suffix.upper()}", source="semantic_scholar"),
    ]

    deduplicated = deduplicate_papers(papers)

    assert deduplicated == [papers[0]]


@given(
    title=st.sampled_from(
        [
            "Evidence First Automated Research Workflow",
            "Trusted Execution Loop for AI Research",
            "Knowledge Vaults for Scientific Agent Memory",
        ]
    )
)
def test_deduplicate_papers_removes_high_similarity_title_duplicates(title: str) -> None:
    papers = [
        _paper(title, doi=None, source="arxiv"),
        _paper(f"{title}.", doi=None, source="semantic_scholar"),
        _paper("A Clearly Different Research Topic", doi=None, source="arxiv"),
    ]

    deduplicated = deduplicate_papers(papers)

    assert deduplicated == [papers[0], papers[2]]
