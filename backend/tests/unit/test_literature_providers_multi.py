"""多文献源 Provider 解析单测（无网络，仅验证解析与领域门控）。"""

from __future__ import annotations

from app.integrations.literature._util import is_medical_query, reconstruct_inverted_index, strip_tags
from app.integrations.literature.anyresearch import AnyResearchProvider
from app.integrations.literature.crossref import CrossrefProvider
from app.integrations.literature.openalex import OpenAlexProvider
from app.integrations.literature.pubmed import PubmedProvider
from app.integrations.literature.semantic_scholar import SemanticScholarProvider


def test_is_medical_query() -> None:
    assert is_medical_query("covid vaccine efficacy trial") is True
    assert is_medical_query("癌症靶向药物临床疗效") is True
    assert is_medical_query("protein ligand binding affinity") is True  # 药物发现/生化属医药范畴
    assert is_medical_query("transformer attention mechanism") is False
    assert is_medical_query("quantum error correction codes") is False


def test_reconstruct_inverted_index() -> None:
    assert reconstruct_inverted_index({"hello": [0], "world": [1]}) == "hello world"
    assert reconstruct_inverted_index(None) == ""


def test_strip_tags() -> None:
    assert strip_tags("<jats:p>Hello <b>world</b></jats:p>") == "Hello world"


def test_openalex_parse() -> None:
    payload = {
        "results": [
            {
                "title": "BindingDB",
                "doi": "https://doi.org/10.1093/nar/gkw1072",
                "publication_year": 2016,
                "primary_location": {"source": {"display_name": "Nucleic Acids Research"}},
                "abstract_inverted_index": {"Binding": [0], "affinity": [1], "data": [2]},
                "id": "https://openalex.org/W123",
            }
        ]
    }
    results = OpenAlexProvider()._parse(payload)
    assert len(results) == 1
    assert results[0].title == "BindingDB"
    assert results[0].doi == "https://doi.org/10.1093/nar/gkw1072"
    assert results[0].venue == "Nucleic Acids Research"
    assert results[0].abstract == "Binding affinity data"
    assert results[0].source == "openalex"


def test_crossref_parse() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "title": ["A Test Paper"],
                    "DOI": "10.1234/test",
                    "abstract": "<jats:p>A <jats:italic>great</jats:italic> abstract.</jats:p>",
                    "container-title": ["Journal of Tests"],
                    "published-print": {"date-parts": [[2020, 1, 1]]},
                }
            ]
        }
    }
    results = CrossrefProvider()._parse(payload)
    assert len(results) == 1
    assert results[0].title == "A Test Paper"
    assert results[0].doi == "10.1234/test"
    assert results[0].publication_year == 2020
    assert results[0].venue == "Journal of Tests"
    assert results[0].abstract == "A great abstract."


def test_semantic_scholar_parse() -> None:
    payload = {
        "data": [
            {
                "title": "Attention Is All You Need",
                "year": 2017,
                "venue": "NeurIPS",
                "paperId": "abc123",
                "externalIds": {"DOI": "10.5555/123", "CorpusId": "999"},
                "abstract": "We propose Transformer.",
            }
        ]
    }
    results = SemanticScholarProvider()._parse(payload)
    assert len(results) == 1
    assert results[0].title == "Attention Is All You Need"
    assert results[0].doi == "10.5555/123"
    assert results[0].publication_year == 2017


def test_pubmed_parse() -> None:
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation>
      <PMID>42597254</PMID>
      <Article>
        <Journal><Title>Nature</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
        <ArticleTitle>A vaccine study</ArticleTitle>
        <Abstract><AbstractText>First sentence.</AbstractText><AbstractText>Second sentence.</AbstractText></Abstract>
      </Article>
      <ArticleIdList><ArticleId IdType="doi">10.1000/vaccine</ArticleId></ArticleIdList>
    </MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    results = PubmedProvider()._parse(xml)
    assert len(results) == 1
    assert results[0].title == "A vaccine study"
    assert results[0].publication_year == 2024
    assert results[0].venue == "Nature"
    assert results[0].doi == "10.1000/vaccine"
    assert results[0].abstract == "First sentence. Second sentence."
    assert results[0].external_id == "42597254"


def test_anyresearch_parse_markdown() -> None:
    text = (
        "## Search Results (2 results, 100ms)\n\n"
        "### 1. Attention Is All You Need\n"
        "- **URL**: https://doi.org/10.5555/123\n"
        "- We propose Transformer.\n\n"
        "### 2. BERT\n"
        "- **URL**: https://doi.org/10.18653/v1/N19-1423\n"
        "- Bidirectional encoders.\n"
    )
    results = AnyResearchProvider._parse_markdown(text)
    assert len(results) == 2
    assert results[0].title == "Attention Is All You Need"
    assert results[0].doi == "10.5555/123"
    assert results[0].abstract == "We propose Transformer."
    assert results[1].title == "BERT"
    assert results[1].doi == "10.18653/v1/N19-1423"
