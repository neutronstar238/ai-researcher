"""Provider-neutral, fail-safe quality evidence for planning literature.

Publication databases expose heterogeneous status and type fields.  In
particular, a broad ``published`` label does not prove that a work is a
research article or that it passed peer review.  This module keeps those claims
separate, requires provenance for positive peer-review and citation signals,
and emits a content-addressed assessment suitable for ranking.  It never uses
venue-name allowlists or denylists.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.models import StrictFrozenModel

_SHA256 = r"^[0-9a-f]{64}$"

NormalizedPublicationType = Literal[
    "research_article",
    "review_article",
    "conference_paper",
    "scholarly_book",
    "book_chapter",
    "preprint",
    "thesis",
    "technical_report",
    "dataset_or_software",
    "editorial_or_reference",
    "repository_record",
    "other",
    "unknown",
]
PeerReviewEvidence = Literal[
    "sourced_positive_claim",
    "unsourced_positive_claim",
    "negative_claim",
    "unknown",
]
CitationEvidence = Literal[
    "unknown",
    "known_zero",
    "bounded_low",
    "bounded_medium",
    "bounded_high",
]
PublicationIdentityEvidence = Literal[
    "publication_doi",
    "repository_doi",
    "resolvable_url",
    "none",
]
RepositoryNamespace = Literal["arxiv", "zenodo", "other", "none"]


class PlanningLiteratureQualityTier(str, Enum):
    """Coarse authority tiers; none is a venue-prestige judgment."""

    PEER_REVIEW_SUPPORTED = "peer_review_supported"
    FORMAL_SCHOLARLY_UNVERIFIED = "formal_scholarly_unverified"
    PUBLISHED_UNVERIFIED = "published_unverified"
    PREPRINT_OR_REPOSITORY = "preprint_or_repository"
    UNKNOWN_SCHOLARLY = "unknown_scholarly"
    REPORTED_NON_PEER_REVIEWED = "reported_non_peer_reviewed"
    BLOCKED_STATUS = "blocked_status"


_FORMAL_RESEARCH_TYPES = frozenset(
    {
        "research_article",
        "review_article",
        "conference_paper",
        "scholarly_book",
        "book_chapter",
    }
)
_NON_RESEARCH_TYPES = frozenset({"dataset_or_software", "editorial_or_reference"})
_TYPE_ALIASES: dict[str, NormalizedPublicationType] = {
    "article": "research_article",
    "journal article": "research_article",
    "research article": "research_article",
    "review": "review_article",
    "review article": "review_article",
    "conference paper": "conference_paper",
    "conference proceeding": "conference_paper",
    "proceedings article": "conference_paper",
    "proceedings paper": "conference_paper",
    "book": "scholarly_book",
    "monograph": "scholarly_book",
    "book chapter": "book_chapter",
    "preprint": "preprint",
    "posted content": "preprint",
    "dissertation": "thesis",
    "thesis": "thesis",
    "report": "technical_report",
    "technical report": "technical_report",
    "dataset": "dataset_or_software",
    "software": "dataset_or_software",
    "editorial": "editorial_or_reference",
    "letter": "editorial_or_reference",
    "paratext": "editorial_or_reference",
    "reference entry": "editorial_or_reference",
    "repository": "repository_record",
    "repository record": "repository_record",
    "archive record": "repository_record",
}
_TIER_BASE_SCORE = {
    PlanningLiteratureQualityTier.PEER_REVIEW_SUPPORTED: 0.90,
    PlanningLiteratureQualityTier.FORMAL_SCHOLARLY_UNVERIFIED: 0.70,
    PlanningLiteratureQualityTier.PUBLISHED_UNVERIFIED: 0.55,
    PlanningLiteratureQualityTier.PREPRINT_OR_REPOSITORY: 0.38,
    PlanningLiteratureQualityTier.UNKNOWN_SCHOLARLY: 0.25,
    PlanningLiteratureQualityTier.REPORTED_NON_PEER_REVIEWED: 0.10,
    PlanningLiteratureQualityTier.BLOCKED_STATUS: 0.0,
}
_TIER_SCORE_CAP = {
    PlanningLiteratureQualityTier.PEER_REVIEW_SUPPORTED: 0.96,
    PlanningLiteratureQualityTier.FORMAL_SCHOLARLY_UNVERIFIED: 0.78,
    PlanningLiteratureQualityTier.PUBLISHED_UNVERIFIED: 0.64,
    PlanningLiteratureQualityTier.PREPRINT_OR_REPOSITORY: 0.48,
    PlanningLiteratureQualityTier.UNKNOWN_SCHOLARLY: 0.38,
    PlanningLiteratureQualityTier.REPORTED_NON_PEER_REVIEWED: 0.22,
    PlanningLiteratureQualityTier.BLOCKED_STATUS: 0.0,
}


class _PlanningLiteratureQualityAssessmentBase(StrictFrozenModel):
    """Shared fields for versioned, hash-bound quality assessments."""

    record_id: str = Field(min_length=1)
    publication_status_claim: Literal["unknown", "preprint", "published", "withdrawn", "retracted"]
    work_type_claim: str | None = None
    normalized_publication_type: NormalizedPublicationType
    peer_review_claim: str | None = None
    peer_review_evidence_source: str | None = None
    peer_review_evidence: PeerReviewEvidence
    publication_identity_evidence: PublicationIdentityEvidence
    venue_present: bool
    authors_present: bool
    abstract_present: bool
    retrieval_source_count: int = Field(ge=0)
    citation_count: int | None = Field(default=None, ge=0)
    citation_count_source: str | None = None
    citation_count_as_of: date | None = None
    citation_evidence: CitationEvidence
    quality_tier: PlanningLiteratureQualityTier
    quality_score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    evidence_notes: tuple[str, ...]
    assessment_hash: str = Field(pattern=_SHA256)

    @property
    def usable_citation_count(self) -> int | None:
        """Return a count only when its source and observation date are present."""

        if self.citation_evidence == "unknown":
            return None
        return self.citation_count

    @property
    def bibliometric_rank(self) -> int:
        """Return a capped secondary rank; exact citation magnitude is not a truth score."""

        return {
            "unknown": 0,
            "known_zero": 0,
            "bounded_low": 1,
            "bounded_medium": 2,
            "bounded_high": 3,
        }[self.citation_evidence]


class PlanningLiteratureQualityAssessmentV1(_PlanningLiteratureQualityAssessmentBase):
    """Frozen validator for quality assessments emitted by literature protocol v3."""

    schema_version: Literal["planning-literature-quality-v1"] = "planning-literature-quality-v1"

    @model_validator(mode="after")
    def _validate_replay(self) -> PlanningLiteratureQualityAssessmentV1:
        tier, score, notes = _derive_quality(
            publication_status=self.publication_status_claim,
            publication_type=self.normalized_publication_type,
            peer_review_evidence=self.peer_review_evidence,
            publication_identity=self.publication_identity_evidence,
            venue_present=self.venue_present,
            authors_present=self.authors_present,
            abstract_present=self.abstract_present,
            retrieval_source_count=self.retrieval_source_count,
        )
        citation_evidence = _citation_evidence(
            self.citation_count,
            source=self.citation_count_source,
            as_of=self.citation_count_as_of,
        )
        if (
            self.quality_tier is not tier
            or self.quality_score != score
            or self.evidence_notes != notes
            or self.citation_evidence != citation_evidence
        ):
            raise ValueError("planning literature quality assessment does not replay")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"assessment_hash"})
        )
        if self.assessment_hash != expected_hash:
            raise ValueError("planning literature quality assessment hash mismatch")
        return self


class PlanningLiteratureQualityAssessment(_PlanningLiteratureQualityAssessmentBase):
    """Current assessment with an explicit required-anchor authority decision."""

    schema_version: Literal["planning-literature-quality-v2"] = "planning-literature-quality-v2"
    identity_doi: str | None = None
    repository_namespace: RepositoryNamespace
    required_anchor_eligible: bool

    @model_validator(mode="after")
    def _validate_replay(self) -> PlanningLiteratureQualityAssessment:
        tier, score, notes = _derive_quality(
            publication_status=self.publication_status_claim,
            publication_type=self.normalized_publication_type,
            peer_review_evidence=self.peer_review_evidence,
            publication_identity=self.publication_identity_evidence,
            venue_present=self.venue_present,
            authors_present=self.authors_present,
            abstract_present=self.abstract_present,
            retrieval_source_count=self.retrieval_source_count,
        )
        citation_evidence = _citation_evidence(
            self.citation_count,
            source=self.citation_count_source,
            as_of=self.citation_count_as_of,
        )
        anchor_eligible = _required_anchor_eligible(
            publication_status=self.publication_status_claim,
            publication_type=self.normalized_publication_type,
            publication_identity=self.publication_identity_evidence,
            repository_namespace=self.repository_namespace,
            quality_tier=tier,
        )
        repository_namespace = _repository_namespace(
            self.identity_doi,
            identity=self.publication_identity_evidence,
        )
        if (
            self.quality_tier is not tier
            or self.quality_score != score
            or self.evidence_notes != notes
            or self.citation_evidence != citation_evidence
            or self.repository_namespace != repository_namespace
            or self.required_anchor_eligible is not anchor_eligible
        ):
            raise ValueError("planning literature quality assessment does not replay")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"assessment_hash"})
        )
        if self.assessment_hash != expected_hash:
            raise ValueError("planning literature quality assessment hash mismatch")
        return self


PlanningLiteratureQualityAssessmentAny = (
    PlanningLiteratureQualityAssessment | PlanningLiteratureQualityAssessmentV1
)


def parse_planning_literature_quality_assessment(
    payload: Mapping[str, Any],
) -> PlanningLiteratureQualityAssessmentAny:
    """Replay a frozen v1 assessment or validate a current v2 assessment."""

    version = payload.get("schema_version")
    if version == "planning-literature-quality-v1":
        return PlanningLiteratureQualityAssessmentV1.model_validate(payload)
    if version == "planning-literature-quality-v2":
        return PlanningLiteratureQualityAssessment.model_validate(payload)
    raise ValueError(f"unsupported planning literature quality schema: {version!r}")


def assess_planning_literature_quality(
    record: Mapping[str, Any],
) -> PlanningLiteratureQualityAssessment:
    """Assess one provider-neutral record without inferring peer review from status."""

    record_id = str(record.get("record_id") or "").strip()
    if not record_id:
        raise ValueError("planning literature quality requires a record ID")
    publication_status = _publication_status(record.get("publication_status"))
    work_type_claim = _optional_text(record.get("publication_type") or record.get("work_type"))
    publication_type = _normalize_publication_type(work_type_claim)
    peer_claim_value = (
        record.get("peer_review_status")
        if "peer_review_status" in record
        else record.get("peer_reviewed")
    )
    peer_review_claim = _optional_text(peer_claim_value)
    peer_review_source = _optional_text(
        record.get("peer_review_status_source") or record.get("peer_reviewed_source")
    )
    peer_evidence = _peer_review_evidence(peer_claim_value, peer_review_source)
    identity = _publication_identity(record)
    identity_doi = _identity_doi(record, identity=identity)
    repository_namespace = _repository_namespace(identity_doi, identity=identity)
    citation_count = _valid_citation_count(record.get("citation_count"))
    citation_source = _optional_text(record.get("citation_count_source"))
    citation_as_of = _optional_date(record.get("citation_count_as_of"))
    source_count = len(_retrieval_sources(record))
    venue_present = bool(_optional_text(record.get("venue")))
    authors_present = _authors_present(record.get("authors"))
    abstract_present = bool(_optional_text(record.get("abstract")))
    tier, score, notes = _derive_quality(
        publication_status=publication_status,
        publication_type=publication_type,
        peer_review_evidence=peer_evidence,
        publication_identity=identity,
        venue_present=venue_present,
        authors_present=authors_present,
        abstract_present=abstract_present,
        retrieval_source_count=source_count,
    )
    payload: dict[str, Any] = {
        "schema_version": "planning-literature-quality-v2",
        "record_id": record_id,
        "publication_status_claim": publication_status,
        "work_type_claim": work_type_claim,
        "normalized_publication_type": publication_type,
        "peer_review_claim": peer_review_claim,
        "peer_review_evidence_source": peer_review_source,
        "peer_review_evidence": peer_evidence,
        "publication_identity_evidence": identity,
        "identity_doi": identity_doi,
        "repository_namespace": repository_namespace,
        "venue_present": venue_present,
        "authors_present": authors_present,
        "abstract_present": abstract_present,
        "retrieval_source_count": source_count,
        "citation_count": citation_count,
        "citation_count_source": citation_source,
        "citation_count_as_of": citation_as_of.isoformat() if citation_as_of else None,
        "citation_evidence": _citation_evidence(
            citation_count,
            source=citation_source,
            as_of=citation_as_of,
        ),
        "quality_tier": tier,
        "quality_score": score,
        "evidence_notes": notes,
        "required_anchor_eligible": _required_anchor_eligible(
            publication_status=publication_status,
            publication_type=publication_type,
            publication_identity=identity,
            repository_namespace=repository_namespace,
            quality_tier=tier,
        ),
    }
    payload["assessment_hash"] = canonical_model_hash(payload)
    return PlanningLiteratureQualityAssessment.model_validate(payload)


def _derive_quality(
    *,
    publication_status: str,
    publication_type: NormalizedPublicationType,
    peer_review_evidence: PeerReviewEvidence,
    publication_identity: PublicationIdentityEvidence,
    venue_present: bool,
    authors_present: bool,
    abstract_present: bool,
    retrieval_source_count: int,
) -> tuple[PlanningLiteratureQualityTier, float, tuple[str, ...]]:
    notes: list[str] = []
    if publication_status in {"withdrawn", "retracted"}:
        tier = PlanningLiteratureQualityTier.BLOCKED_STATUS
        notes.append("withdrawn_or_retracted_status_blocks_positive_quality")
    elif peer_review_evidence == "negative_claim" or publication_type in _NON_RESEARCH_TYPES:
        tier = PlanningLiteratureQualityTier.REPORTED_NON_PEER_REVIEWED
        notes.append("record_is_reported_non_peer_reviewed_or_non_research")
    elif peer_review_evidence == "sourced_positive_claim" and publication_type not in {
        "preprint",
        "repository_record",
    }:
        tier = PlanningLiteratureQualityTier.PEER_REVIEW_SUPPORTED
        notes.append("positive_peer_review_claim_has_an_explicit_source")
    elif (
        publication_status == "published"
        and publication_type in _FORMAL_RESEARCH_TYPES
        and (publication_identity == "publication_doi" or venue_present)
    ):
        tier = PlanningLiteratureQualityTier.FORMAL_SCHOLARLY_UNVERIFIED
        notes.append("formal_scholarly_type_is_reported_but_peer_review_is_unverified")
    elif publication_type in {"preprint", "repository_record"} or (
        publication_status == "preprint" or publication_identity == "repository_doi"
    ):
        tier = PlanningLiteratureQualityTier.PREPRINT_OR_REPOSITORY
        notes.append("repository_or_preprint_evidence_is_not_peer_review_evidence")
    elif publication_status == "published" and (
        publication_identity == "publication_doi" or venue_present
    ):
        tier = PlanningLiteratureQualityTier.PUBLISHED_UNVERIFIED
        notes.append("published_status_does_not_establish_type_or_peer_review")
    else:
        tier = PlanningLiteratureQualityTier.UNKNOWN_SCHOLARLY
        notes.append("publication_authority_remains_unknown")

    if peer_review_evidence == "unsourced_positive_claim":
        notes.append("unsourced_positive_peer_review_claim_was_not_promoted")
    if publication_identity == "publication_doi":
        notes.append("publication_doi_present")
    elif publication_identity == "repository_doi":
        notes.append("repository_doi_present")
    if retrieval_source_count > 1:
        notes.append("retrieval_provenance_is_cross_source")

    base = _TIER_BASE_SCORE[tier]
    bonus = 0.0
    if tier is not PlanningLiteratureQualityTier.BLOCKED_STATUS:
        bonus += 0.015 if authors_present else 0.0
        bonus += 0.015 if abstract_present else 0.0
        bonus += 0.02 if retrieval_source_count > 1 else 0.0
        bonus += 0.01 if publication_identity == "publication_doi" else 0.0
        bonus += 0.01 if venue_present else 0.0
    score = round(min(_TIER_SCORE_CAP[tier], base + bonus), 3)
    return tier, score, tuple(notes)


def _publication_status(
    value: Any,
) -> Literal["unknown", "preprint", "published", "withdrawn", "retracted"]:
    normalized = str(value or "unknown").strip().casefold()
    if normalized in {"preprint", "published", "withdrawn", "retracted"}:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _normalize_publication_type(value: str | None) -> NormalizedPublicationType:
    if value is None:
        return "unknown"
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    if not normalized:
        return "unknown"
    return _TYPE_ALIASES.get(normalized, "other")


def _peer_review_evidence(value: Any, source: str | None) -> PeerReviewEvidence:
    if isinstance(value, bool):
        if value:
            return "sourced_positive_claim" if source else "unsourced_positive_claim"
        return "negative_claim"
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
    if normalized in {"peer_reviewed", "reviewed", "verified", "yes", "true"}:
        return "sourced_positive_claim" if source else "unsourced_positive_claim"
    if normalized in {
        "not_peer_reviewed",
        "unreviewed",
        "not_reviewed",
        "no",
        "false",
    }:
        return "negative_claim"
    return "unknown"


def _publication_identity(record: Mapping[str, Any]) -> PublicationIdentityEvidence:
    publication_doi = _optional_text(record.get("publication_doi") or record.get("doi"))
    if publication_doi and not _is_repository_doi(publication_doi):
        return "publication_doi"
    if _optional_text(record.get("repository_doi")) or (
        publication_doi and _is_repository_doi(publication_doi)
    ):
        return "repository_doi"
    url = _optional_text(record.get("source_url") or record.get("url"))
    if url and url.casefold().startswith(("https://", "http://")):
        return "resolvable_url"
    return "none"


def _is_repository_doi(value: str) -> bool:
    normalized = value.strip().casefold()
    normalized = normalized.removeprefix("https://doi.org/")
    normalized = normalized.removeprefix("http://doi.org/")
    normalized = normalized.removeprefix("doi:")
    return normalized.startswith(("10.48550/arxiv.", "10.5281/zenodo."))


def _identity_doi(
    record: Mapping[str, Any],
    *,
    identity: PublicationIdentityEvidence,
) -> str | None:
    if identity == "publication_doi":
        value = _optional_text(record.get("publication_doi") or record.get("doi"))
    elif identity == "repository_doi":
        value = _optional_text(record.get("repository_doi")) or _optional_text(
            record.get("publication_doi") or record.get("doi")
        )
    else:
        return None
    if value is None:
        return None
    normalized = value.casefold()
    normalized = normalized.removeprefix("https://doi.org/")
    normalized = normalized.removeprefix("http://doi.org/")
    normalized = normalized.removeprefix("doi:")
    return normalized or None


def _repository_namespace(
    value: str | None,
    *,
    identity: PublicationIdentityEvidence,
) -> RepositoryNamespace:
    if value is None or identity != "repository_doi":
        return "none"
    if value.startswith("10.48550/arxiv."):
        return "arxiv"
    if value.startswith("10.5281/zenodo."):
        return "zenodo"
    return "other"


def _required_anchor_eligible(
    *,
    publication_status: str,
    publication_type: NormalizedPublicationType,
    publication_identity: PublicationIdentityEvidence,
    repository_namespace: RepositoryNamespace,
    quality_tier: PlanningLiteratureQualityTier,
) -> bool:
    """Allow preprints, but fail closed for repository-only published records."""

    if quality_tier in {
        PlanningLiteratureQualityTier.BLOCKED_STATUS,
        PlanningLiteratureQualityTier.REPORTED_NON_PEER_REVIEWED,
    }:
        return False
    if publication_type in _NON_RESEARCH_TYPES:
        return False
    if publication_identity == "repository_doi" and not (
        repository_namespace == "arxiv" and publication_status == "preprint"
    ):
        return False
    return True


def _citation_evidence(
    count: int | None,
    *,
    source: str | None,
    as_of: date | None,
) -> CitationEvidence:
    if count is None or not source or as_of is None:
        return "unknown"
    if count == 0:
        return "known_zero"
    if count < 10:
        return "bounded_low"
    if count < 100:
        return "bounded_medium"
    return "bounded_high"


def _retrieval_sources(record: Mapping[str, Any]) -> frozenset[str]:
    values: list[str] = []
    for key in ("retrieved_from", "paper_source", "source"):
        raw = record.get(key)
        if isinstance(raw, str):
            values.extend(raw.split(","))
        elif isinstance(raw, Sequence) and not isinstance(raw, bytes | bytearray):
            values.extend(str(item) for item in raw)
    return frozenset(value.strip().casefold() for value in values if value.strip())


def _authors_present(value: Any) -> bool:
    return bool(
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes | bytearray)
        and any(str(item).strip() for item in value)
    )


def _valid_citation_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return int(value)


def _optional_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
