from __future__ import annotations

import pytest
from pydantic import ValidationError

from autoresearch.competition.contest_planning_literature_quality import (
    PlanningLiteratureQualityAssessment,
    PlanningLiteratureQualityAssessmentV1,
    PlanningLiteratureQualityTier,
    assess_planning_literature_quality,
    parse_planning_literature_quality_assessment,
)
from autoresearch.competition.manifest import canonical_model_hash


def _record(record_id: str, **updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "record_id": record_id,
        "title": "Phase stability in lumen arrays",
        "authors": ["A. Researcher", "B. Researcher"],
        "abstract": "A controlled study of phase stability under repeated measurements.",
        "publication_status": "published",
        "citation_count": 0,
        "citation_count_source": "scholarly-index",
        "citation_count_as_of": "2026-08-14",
        "retrieved_from": "registry-a,registry-b",
    }
    record.update(updates)
    return record


def test_repository_and_broad_published_claim_are_not_peer_review_evidence() -> None:
    repository = assess_planning_literature_quality(
        _record(
            "repository-record",
            publication_type="repository-record",
            repository_doi="10.9999/archive.123",
            venue="Institutional archive",
        )
    )
    ambiguous_published = assess_planning_literature_quality(
        _record(
            "ambiguous-published",
            publication_doi="10.9999/ambiguous.123",
            venue="Scholarly collection",
        )
    )

    assert repository.quality_tier is PlanningLiteratureQualityTier.PREPRINT_OR_REPOSITORY
    assert ambiguous_published.quality_tier is PlanningLiteratureQualityTier.PUBLISHED_UNVERIFIED
    assert repository.peer_review_evidence == "unknown"
    assert ambiguous_published.peer_review_evidence == "unknown"
    assert repository.quality_score < 0.5
    assert ambiguous_published.quality_score < 0.7


def test_explicit_sourced_peer_review_evidence_outranks_repository_citations() -> None:
    repository = assess_planning_literature_quality(
        _record(
            "repository-record",
            publication_type="repository-record",
            repository_doi="10.9999/archive.123",
            citation_count=10_000_000,
        )
    )
    reviewed = assess_planning_literature_quality(
        _record(
            "reviewed-record",
            publication_type="research-article",
            publication_doi="10.9999/article.123",
            venue="Research proceedings",
            peer_review_status="peer_reviewed",
            peer_review_status_source="publisher-metadata",
            citation_count=0,
        )
    )

    assert reviewed.quality_tier is PlanningLiteratureQualityTier.PEER_REVIEW_SUPPORTED
    assert reviewed.peer_review_evidence == "sourced_positive_claim"
    assert reviewed.quality_score > repository.quality_score


def test_bibliometric_signal_requires_provenance_and_is_bounded() -> None:
    unprovenanced = assess_planning_literature_quality(
        _record(
            "unprovenanced",
            citation_count=99_000_000,
            citation_count_source=None,
            citation_count_as_of=None,
        )
    )
    high = assess_planning_literature_quality(_record("high", citation_count=100))
    extreme = assess_planning_literature_quality(_record("extreme", citation_count=99_000_000))

    assert unprovenanced.citation_evidence == "unknown"
    assert unprovenanced.usable_citation_count is None
    assert high.citation_evidence == "bounded_high"
    assert extreme.citation_evidence == "bounded_high"
    assert high.bibliometric_rank == extreme.bibliometric_rank


def test_quality_assessment_is_content_addressed() -> None:
    assessment = assess_planning_literature_quality(_record("content-addressed"))
    payload = assessment.model_dump(mode="json")
    payload["quality_score"] = 1.0
    payload["assessment_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "assessment_hash"}
    )

    with pytest.raises(ValidationError, match="does not replay"):
        PlanningLiteratureQualityAssessment.model_validate(payload)


def test_repository_namespace_cannot_be_promoted_by_published_status() -> None:
    archived = assess_planning_literature_quality(
        _record(
            "archived-record",
            publication_doi="https://doi.org/10.5281/ZENODO.7654321",
            venue=None,
        )
    )
    preprint = assess_planning_literature_quality(
        _record(
            "preprint-record",
            publication_status="preprint",
            publication_doi=None,
            repository_doi="10.48550/arxiv.2601.01234",
            venue=None,
        )
    )

    assert archived.schema_version == "planning-literature-quality-v2"
    assert archived.publication_identity_evidence == "repository_doi"
    assert archived.repository_namespace == "zenodo"
    assert archived.required_anchor_eligible is False
    assert preprint.publication_identity_evidence == "repository_doi"
    assert preprint.repository_namespace == "arxiv"
    assert preprint.required_anchor_eligible is True


def test_v1_quality_assessment_replays_without_v2_policy_upgrade() -> None:
    current = assess_planning_literature_quality(
        _record(
            "legacy-archive",
            publication_type="repository-record",
            repository_doi="10.7777/archive.12",
        )
    )
    payload = current.model_dump(mode="json")
    payload["schema_version"] = "planning-literature-quality-v1"
    for field in ("identity_doi", "repository_namespace", "required_anchor_eligible"):
        payload.pop(field)
    payload["assessment_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "assessment_hash"}
    )

    replayed = parse_planning_literature_quality_assessment(payload)

    assert isinstance(replayed, PlanningLiteratureQualityAssessmentV1)
    assert replayed.schema_version == "planning-literature-quality-v1"
