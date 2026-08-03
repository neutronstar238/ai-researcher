"""Deterministic tests for evidence-grounded candidate authoring.

These use a stub completion callable so CI never needs network or credentials.
The live run is recorded separately in `Agent.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from autoresearch.research.candidate_authoring import (
    CandidateAuthoringError,
    author_research_candidate,
)
from autoresearch.schemas import DocumentRecord


def _documents() -> list[DocumentRecord]:
    return [
        DocumentRecord(
            id="doc_a",
            title="Sparse coding for handwritten digit recognition",
            source_uri="https://arxiv.org/abs/1234.5678",
            abstract="We study nearest-centroid classifiers on the UCI Pendigits benchmark.",
            retrieved_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        ),
        DocumentRecord(
            id="doc_b",
            title="Variance calibration in prototype classifiers",
            source_uri="https://arxiv.org/abs/2345.6789",
            doi="10.1000/example",
            abstract="Per-class variance scaling improves macro F1 on tabular benchmarks.",
            retrieved_at=datetime(2026, 8, 3, 12, 5, tzinfo=UTC),
        ),
    ]


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "title": "Variance-calibrated prototype classifiers on UCI Pendigits",
        "description": "Test whether per-class variance calibration improves prototypes.",
        "research_gap": "Prior work reports centroid baselines without variance scaling.",
        "method": "diagonal per-class variance-calibrated nearest-prototype classifier",
        "dataset": "UCI Pendigits",
        "baseline": "z-score nearest centroid classifier",
        "metric": "classification accuracy and macro_f1",
        "target": "official UCI Pendigits train/test split with a recorded seed",
        "limitation": "single tabular benchmark limits external validity",
        "evidence_document_ids": ["doc_a", "doc_b"],
        "grounding": [
            {
                "field": "dataset",
                "document_id": "doc_a",
                "justification": "doc_a evaluates on the UCI Pendigits benchmark.",
            },
            {
                "field": "metric",
                "document_id": "doc_b",
                "justification": "doc_b reports macro F1 for prototype classifiers.",
            },
        ],
    }
    payload.update(overrides)
    return payload


class _StubResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.parsed_json = payload
        self.model_name = "test-model"
        self.provider = "test-provider"


def _stub(payload: dict[str, Any]) -> Any:
    def completion(**_kwargs: Any) -> _StubResult:
        return _StubResult(payload)

    return completion


def test_authored_candidate_carries_plan_ready_metadata_and_provenance() -> None:
    authored = author_research_candidate(
        _documents(),
        project_id="proj",
        research_direction="prototype classifiers on tabular benchmarks",
        completion=_stub(_payload()),
    )

    assert authored.candidate.metadata["dataset"] == "UCI Pendigits"
    assert authored.candidate.metadata["baseline"] == "z-score nearest centroid classifier"
    assert authored.candidate.metadata["metric"] == "classification accuracy and macro_f1"
    assert authored.candidate.metadata["target"].startswith("official UCI Pendigits")
    assert [source.document_id for source in authored.cited_sources] == ["doc_a", "doc_b"]
    # Retrieval timestamps must survive so the evidence trail stays auditable.
    assert authored.cited_sources[0].retrieved_at == "2026-08-03T12:00:00+00:00"
    assert authored.cited_sources[1].doi == "10.1000/example"


def test_authoring_rejects_citation_to_a_document_that_was_never_retrieved() -> None:
    with pytest.raises(CandidateAuthoringError, match="never retrieved"):
        author_research_candidate(
            _documents(),
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(_payload(evidence_document_ids=["doc_a", "doc_fabricated"])),
        )


def test_authoring_rejects_placeholder_dataset_wording() -> None:
    with pytest.raises(CandidateAuthoringError, match="placeholder term"):
        author_research_candidate(
            _documents(),
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(_payload(dataset="available benchmark")),
        )


def test_authoring_rejects_a_metric_that_is_not_measurable() -> None:
    with pytest.raises(CandidateAuthoringError, match="not concrete enough"):
        author_research_candidate(
            _documents(),
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(_payload(metric="general performance improvement")),
        )


def test_authoring_requires_at_least_two_cited_documents() -> None:
    with pytest.raises(CandidateAuthoringError, match="at least"):
        author_research_candidate(
            _documents(),
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(
                _payload(
                    evidence_document_ids=["doc_a"],
                    grounding=[
                        {
                            "field": "dataset",
                            "document_id": "doc_a",
                            "justification": "doc_a uses the benchmark.",
                        }
                    ],
                )
            ),
        )


def test_authoring_rejects_a_title_naming_the_system_instead_of_a_topic() -> None:
    with pytest.raises(CandidateAuthoringError, match="names the system"):
        author_research_candidate(
            _documents(),
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(_payload(title="AutoResearch pipeline improvements")),
        )


def test_authoring_rejects_a_method_too_long_to_splice_grammatically() -> None:
    # plans._build_plan renders "whether <method> can improve...", so a sentence-shaped
    # method produced ungrammatical plan prose in the first live run.
    with pytest.raises(CandidateAuthoringError, match="keep it under"):
        author_research_candidate(
            _documents(),
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(
                _payload(
                    method=(
                        "Train a feed-forward embedding network on tabular features, then "
                        "apply a k-medoids-style prototype selection per class to identify "
                        "a small number of representative training instances."
                    )
                )
            ),
        )


def test_authoring_requires_documents() -> None:
    with pytest.raises(CandidateAuthoringError, match="at least one retrieved document"):
        author_research_candidate(
            [],
            project_id="proj",
            research_direction="prototype classifiers",
            completion=_stub(_payload()),
        )
