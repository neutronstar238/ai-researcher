"""Literature provider unit tests (arXiv Atom parsing, no network)."""

from __future__ import annotations

from app.integrations.literature.arxiv import ArxivProvider

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <updated>2023-01-05T00:00:00Z</updated>
    <published>2023-01-05T00:00:00Z</published>
    <title>Deep Multimodal Learning for Drug Discovery</title>
    <summary>An abstract about multimodal learning.</summary>
    <arxiv:doi>10.0000/test.multimodal</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2302.00002v1</id>
    <published>2023-02-10T00:00:00Z</published>
    <title>Graph Neural Networks for Molecular Property Prediction</title>
    <summary>Another abstract.</summary>
  </entry>
</feed>
"""


def test_arxiv_parse_extracts_fields() -> None:
    results = ArxivProvider()._parse(SAMPLE)
    assert len(results) == 2
    first = results[0]
    assert first.title == "Deep Multimodal Learning for Drug Discovery"
    assert first.publication_year == 2023
    assert first.doi == "10.0000/test.multimodal"
    assert first.external_id == "http://arxiv.org/abs/2301.00001v1"
    assert first.source == "arxiv"
    assert results[1].doi is None


def test_arxiv_parse_skips_empty_title() -> None:
    xml = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><title>  </title></entry>
      <entry><title>Valid Title</title></entry>
    </feed>"""
    results = ArxivProvider()._parse(xml)
    assert len(results) == 1
    assert results[0].title == "Valid Title"


def test_get_provider_unknown_raises() -> None:
    from app.api.errors import ProviderNotConfiguredError
    from app.integrations.literature.arxiv import get_provider

    try:
        get_provider("does-not-exist")
        raise AssertionError("should have raised")
    except ProviderNotConfiguredError:
        pass


def test_get_provider_arxiv() -> None:
    from app.integrations.literature.arxiv import get_provider

    provider = get_provider("arxiv")
    assert provider.name == "arxiv"
