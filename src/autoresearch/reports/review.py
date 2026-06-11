"""Conservative review simulation for evidence-backed paper drafts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from autoresearch.config.parser import ConfigParser
from autoresearch.evidence import EvidenceGraph, EvidenceGraphError
from autoresearch.schemas import ValidationStatus

VALID_EVIDENCE_STATUSES = {ValidationStatus.PASSED, ValidationStatus.WARNING}
DEFAULT_MAX_DIMENSION_SCORE = 0.95
REQUIRED_SECTIONS = (
    "abstract",
    "introduction",
    "related_work",
    "method",
    "experiments",
    "results",
    "limitations",
    "conclusion",
)


class ReviewDimension(str, Enum):
    """Dimensions used by the conservative review simulator."""

    NOVELTY = "novelty"
    TECHNICAL_SOUNDNESS = "technical_soundness"
    EXPERIMENTAL_RIGOR = "experimental_rigor"
    REPRODUCIBILITY = "reproducibility"
    WRITING_QUALITY = "writing_quality"
    COMPLIANCE = "compliance"


DEFAULT_DIMENSION_WEIGHTS: dict[ReviewDimension, float] = {
    ReviewDimension.NOVELTY: 1.0,
    ReviewDimension.TECHNICAL_SOUNDNESS: 1.0,
    ReviewDimension.EXPERIMENTAL_RIGOR: 1.0,
    ReviewDimension.REPRODUCIBILITY: 1.0,
    ReviewDimension.WRITING_QUALITY: 1.0,
    ReviewDimension.COMPLIANCE: 1.0,
}


class ReviewCriteriaError(ValueError):
    """Raised when review criteria cannot be loaded or validated."""


class _ReviewCriteriaDefinition(BaseModel):
    display_name: str | None = None
    acceptance_threshold: float = Field(ge=0.0, le=1.0)
    dimension_weights: dict[str, float] = Field(default_factory=dict)
    rubric: dict[str, str] = Field(default_factory=dict)
    formatting_requirements: list[str] = Field(default_factory=list)
    content_policies: list[str] = Field(default_factory=list)


class _ReviewCriteriaCatalog(BaseModel):
    venues: dict[str, _ReviewCriteriaDefinition] = Field(default_factory=dict)


@dataclass(frozen=True)
class ReviewCriteria:
    """Venue criteria used by the review simulator."""

    venue: str
    display_name: str
    acceptance_threshold: float
    dimension_weights: dict[ReviewDimension, float]
    rubric: dict[ReviewDimension, str]
    formatting_requirements: tuple[str, ...] = ()
    content_policies: tuple[str, ...] = ()
    source: str = "built-in"
    requested_venue: str | None = None
    is_fallback: bool = False

    @property
    def required_compliance_checks(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.formatting_requirements, *self.content_policies)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "display_name": self.display_name,
            "acceptance_threshold": self.acceptance_threshold,
            "dimension_weights": {
                dimension.value: weight
                for dimension, weight in self.dimension_weights.items()
            },
            "rubric": {
                dimension.value: description
                for dimension, description in self.rubric.items()
            },
            "formatting_requirements": list(self.formatting_requirements),
            "content_policies": list(self.content_policies),
            "source": self.source,
            "requested_venue": self.requested_venue,
            "is_fallback": self.is_fallback,
        }


@dataclass(frozen=True)
class ReviewFinding:
    """One actionable review finding."""

    dimension: ReviewDimension
    severity: str
    message: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "dimension": self.dimension.value,
            "severity": self.severity,
            "message": self.message,
            "action": self.action,
        }


@dataclass(frozen=True)
class ReviewDimensionScore:
    """Score and rationale for one review dimension."""

    dimension: ReviewDimension
    score: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "score": self.score,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PaperReviewContext:
    """Inputs for a conservative deterministic paper review."""

    title: str
    target_venue: str | None = None
    criteria_path: Path | str | None = None
    evidence_graph: EvidenceGraph | None = None
    core_claim_ids: list[str] = field(default_factory=list)
    novelty_refs: list[str] = field(default_factory=list)
    has_baseline: bool = False
    has_ablation: bool = False
    has_statistical_sanity: bool = False
    reproducibility_artifacts: list[str] = field(default_factory=list)
    section_text: dict[str, str] = field(default_factory=dict)
    compliance_checks: dict[str, bool] = field(default_factory=dict)
    max_dimension_score: float = DEFAULT_MAX_DIMENSION_SCORE


@dataclass(frozen=True)
class PaperReviewReport:
    """Deterministic review report with conservative scores and findings."""

    title: str
    criteria: ReviewCriteria
    scores: tuple[ReviewDimensionScore, ...]
    findings: tuple[ReviewFinding, ...]

    @property
    def overall_score(self) -> float:
        if not self.scores:
            return 0.0
        total_weight = sum(
            self.criteria.dimension_weights.get(score.dimension, 0.0)
            for score in self.scores
        )
        if total_weight <= 0.0:
            return round(sum(score.score for score in self.scores) / len(self.scores), 4)
        weighted_total = sum(
            score.score * self.criteria.dimension_weights.get(score.dimension, 0.0)
            for score in self.scores
        )
        return round(weighted_total / total_weight, 4)

    @property
    def meets_acceptance_threshold(self) -> bool:
        return self.overall_score >= self.criteria.acceptance_threshold

    def score_for(self, dimension: ReviewDimension) -> float:
        for score in self.scores:
            if score.dimension is dimension:
                return score.score
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "criteria": self.criteria.to_dict(),
            "overall_score": self.overall_score,
            "meets_acceptance_threshold": self.meets_acceptance_threshold,
            "scores": [score.to_dict() for score in self.scores],
            "findings": [finding.to_dict() for finding in self.findings],
        }


def simulate_paper_review(context: PaperReviewContext) -> PaperReviewReport:
    """Score a paper draft conservatively using available evidence and metadata."""

    criteria = load_review_criteria(
        target_venue=context.target_venue,
        criteria_path=context.criteria_path,
    )
    coverage = _evidence_coverage(context)
    findings = _findings(context, coverage, criteria)
    scores = (
        _score_novelty(context, coverage),
        _score_technical_soundness(context, coverage),
        _score_experimental_rigor(context),
        _score_reproducibility(context, coverage),
        _score_writing_quality(context),
        _score_compliance(context, criteria),
    )
    capped_scores = tuple(_cap_score(score, context.max_dimension_score) for score in scores)
    return PaperReviewReport(
        title=context.title,
        criteria=criteria,
        scores=capped_scores,
        findings=tuple(findings),
    )


def load_review_criteria(
    target_venue: str | None = None,
    criteria_path: Path | str | None = None,
) -> ReviewCriteria:
    """Load built-in or custom venue criteria with generic fallback."""

    catalog = _builtin_criteria_catalog()
    if criteria_path is not None:
        catalog.update(_load_custom_criteria(criteria_path))
    venue_key = _normalize_venue_key(target_venue) if target_venue else "generic"
    venue_key = _BUILTIN_VENUE_ALIASES.get(venue_key, venue_key)
    if venue_key in catalog:
        return catalog[venue_key]
    return _fallback_criteria(target_venue or venue_key, catalog["generic"])


def _evidence_coverage(context: PaperReviewContext) -> float:
    if not context.core_claim_ids:
        return 0.0
    if context.evidence_graph is None:
        return 0.0
    supported_count = 0
    for claim_id in context.core_claim_ids:
        try:
            traces = context.evidence_graph.trace_claim(claim_id)
        except EvidenceGraphError:
            continue
        if any(
            trace.evidence.supports_claim
            and trace.validation_status in VALID_EVIDENCE_STATUSES
            for trace in traces
        ):
            supported_count += 1
    return supported_count / len(context.core_claim_ids)


def _findings(
    context: PaperReviewContext,
    coverage: float,
    criteria: ReviewCriteria,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    if criteria.is_fallback and criteria.requested_venue:
        findings.append(
            ReviewFinding(
                ReviewDimension.COMPLIANCE,
                "medium",
                "Venue-specific criteria were not found, so generic standards were applied.",
                "Define custom review criteria before treating venue compliance as complete.",
            )
        )
    if coverage < 1.0:
        findings.append(
            ReviewFinding(
                ReviewDimension.TECHNICAL_SOUNDNESS,
                "high",
                "Not every core claim has validated evidence coverage.",
                "Attach validated evidence traces to all core claims before promotion.",
            )
        )
        findings.append(
            ReviewFinding(
                ReviewDimension.REPRODUCIBILITY,
                "medium",
                "Reproducibility is weakened because some claims cannot be traced.",
                "Link every quantitative and methodological claim to source artifacts.",
            )
        )
    if not context.has_baseline:
        findings.append(
            ReviewFinding(
                ReviewDimension.EXPERIMENTAL_RIGOR,
                "medium",
                "Baseline reproduction is missing.",
                "Run and validate at least one baseline before claiming improvement.",
            )
        )
    if not context.reproducibility_artifacts:
        findings.append(
            ReviewFinding(
                ReviewDimension.REPRODUCIBILITY,
                "medium",
                "No reproducibility artifacts were provided.",
                "Provide run commands, configs, data hashes, and validation artifacts.",
            )
        )
    missing_compliance = _missing_compliance_checks(context, criteria)
    if missing_compliance:
        findings.append(
            ReviewFinding(
                ReviewDimension.COMPLIANCE,
                "medium",
                "Venue compliance checks are incomplete: "
                + ", ".join(missing_compliance),
                "Run or record every required formatting, ethics, and reproducibility check.",
            )
        )
    return findings


def _score_novelty(
    context: PaperReviewContext,
    coverage: float,
) -> ReviewDimensionScore:
    score = 0.45 + min(len(context.novelty_refs), 3) * 0.08 + coverage * 0.08
    return ReviewDimensionScore(
        ReviewDimension.NOVELTY,
        round(score, 4),
        "Novelty is scored from cited novelty references and evidence coverage.",
    )


def _score_technical_soundness(
    context: PaperReviewContext,
    coverage: float,
) -> ReviewDimensionScore:
    score = 0.25 + coverage * 0.55
    if context.has_statistical_sanity:
        score += 0.08
    return ReviewDimensionScore(
        ReviewDimension.TECHNICAL_SOUNDNESS,
        round(score, 4),
        "Technical soundness depends primarily on validated evidence coverage.",
    )


def _score_experimental_rigor(context: PaperReviewContext) -> ReviewDimensionScore:
    score = 0.35
    if context.has_baseline:
        score += 0.18
    if context.has_ablation:
        score += 0.16
    if context.has_statistical_sanity:
        score += 0.14
    return ReviewDimensionScore(
        ReviewDimension.EXPERIMENTAL_RIGOR,
        round(score, 4),
        "Experimental rigor reflects baseline, ablation, and statistical checks.",
    )


def _score_reproducibility(
    context: PaperReviewContext,
    coverage: float,
) -> ReviewDimensionScore:
    artifact_score = min(len(set(context.reproducibility_artifacts)), 5) * 0.08
    score = 0.30 + artifact_score + coverage * 0.18
    return ReviewDimensionScore(
        ReviewDimension.REPRODUCIBILITY,
        round(score, 4),
        "Reproducibility reflects artifacts plus traceability from claims to evidence.",
    )


def _score_writing_quality(context: PaperReviewContext) -> ReviewDimensionScore:
    present_sections = sum(
        1
        for section in REQUIRED_SECTIONS
        if context.section_text.get(section, "").strip()
    )
    score = 0.35 + (present_sections / len(REQUIRED_SECTIONS)) * 0.40
    return ReviewDimensionScore(
        ReviewDimension.WRITING_QUALITY,
        round(score, 4),
        "Writing quality is based on required section coverage only.",
    )


def _score_compliance(
    context: PaperReviewContext,
    criteria: ReviewCriteria,
) -> ReviewDimensionScore:
    required_checks = criteria.required_compliance_checks
    if not required_checks and not context.compliance_checks:
        score = 0.55
        rationale = "No venue compliance checks were supplied; score is capped conservatively."
    elif required_checks:
        passed = sum(
            1
            for required_check in required_checks
            if context.compliance_checks.get(required_check, False)
        )
        score = 0.35 + (passed / len(required_checks)) * 0.45
        rationale = (
            f"Compliance is scored against {criteria.display_name} formatting and "
            "content checks."
        )
    else:
        passed = sum(1 for passed_check in context.compliance_checks.values() if passed_check)
        score = 0.35 + (passed / len(context.compliance_checks)) * 0.45
        rationale = "Compliance is scored from explicit venue or project checks."
    return ReviewDimensionScore(
        ReviewDimension.COMPLIANCE,
        round(score, 4),
        rationale,
    )


def _cap_score(
    score: ReviewDimensionScore,
    max_dimension_score: float,
) -> ReviewDimensionScore:
    safe_cap = min(max(max_dimension_score, 0.0), DEFAULT_MAX_DIMENSION_SCORE)
    return ReviewDimensionScore(
        score.dimension,
        round(min(score.score, safe_cap), 4),
        score.rationale,
    )


def _missing_compliance_checks(
    context: PaperReviewContext,
    criteria: ReviewCriteria,
) -> tuple[str, ...]:
    return tuple(
        required_check
        for required_check in criteria.required_compliance_checks
        if not context.compliance_checks.get(required_check, False)
    )


def _builtin_criteria_catalog() -> dict[str, ReviewCriteria]:
    return {
        venue: _criteria_from_definition(
            venue=venue,
            definition=_ReviewCriteriaDefinition.model_validate(definition),
            source="built-in",
        )
        for venue, definition in _BUILTIN_CRITERIA_DEFINITIONS.items()
    }


def _load_custom_criteria(criteria_path: Path | str) -> dict[str, ReviewCriteria]:
    path = Path(criteria_path)
    try:
        catalog = cast(
            _ReviewCriteriaCatalog,
            ConfigParser().parse_file(path, model_type=_ReviewCriteriaCatalog),
        )
    except ValueError as exc:
        raise ReviewCriteriaError(f"Could not load review criteria from {path}: {exc}") from exc
    return {
        _normalize_venue_key(venue): _criteria_from_definition(
            venue=_normalize_venue_key(venue),
            definition=definition,
            source=path.as_posix(),
        )
        for venue, definition in catalog.venues.items()
    }


def _criteria_from_definition(
    venue: str,
    definition: _ReviewCriteriaDefinition,
    source: str,
) -> ReviewCriteria:
    return ReviewCriteria(
        venue=venue,
        display_name=definition.display_name or venue,
        acceptance_threshold=definition.acceptance_threshold,
        dimension_weights=_dimension_weights(definition.dimension_weights),
        rubric=_rubric(definition.rubric),
        formatting_requirements=tuple(definition.formatting_requirements),
        content_policies=tuple(definition.content_policies),
        source=source,
    )


def _fallback_criteria(requested_venue: str, generic: ReviewCriteria) -> ReviewCriteria:
    return ReviewCriteria(
        venue=generic.venue,
        display_name=generic.display_name,
        acceptance_threshold=generic.acceptance_threshold,
        dimension_weights=dict(generic.dimension_weights),
        rubric=dict(generic.rubric),
        formatting_requirements=generic.formatting_requirements,
        content_policies=generic.content_policies,
        source=generic.source,
        requested_venue=requested_venue,
        is_fallback=True,
    )


def _dimension_weights(raw_weights: Mapping[str, float]) -> dict[ReviewDimension, float]:
    weights = dict(DEFAULT_DIMENSION_WEIGHTS)
    for raw_dimension, weight in raw_weights.items():
        if weight < 0.0:
            raise ReviewCriteriaError("Review criteria dimension weights must be non-negative.")
        weights[_parse_dimension(raw_dimension)] = weight
    if sum(weights.values()) <= 0.0:
        raise ReviewCriteriaError("Review criteria must include at least one positive weight.")
    return weights


def _rubric(raw_rubric: Mapping[str, str]) -> dict[ReviewDimension, str]:
    return {
        _parse_dimension(raw_dimension): description
        for raw_dimension, description in raw_rubric.items()
    }


def _parse_dimension(raw_dimension: str) -> ReviewDimension:
    try:
        return ReviewDimension(raw_dimension)
    except ValueError as exc:
        valid = ", ".join(dimension.value for dimension in ReviewDimension)
        raise ReviewCriteriaError(
            f"Unknown review dimension '{raw_dimension}'. Expected one of: {valid}."
        ) from exc


def _normalize_venue_key(value: str | None) -> str:
    if value is None:
        return "generic"
    return value.strip().lower().replace("_", "-").replace(" ", "-")


_BUILTIN_VENUE_ALIASES = {
    "ccfb": "ccf-b",
    "ccf-b": "ccf-b",
    "ccf-b-level": "ccf-b",
    "generic": "generic",
}


_BUILTIN_CRITERIA_DEFINITIONS: dict[str, dict[str, Any]] = {
    "generic": {
        "display_name": "Generic Academic Quality",
        "acceptance_threshold": 0.70,
        "dimension_weights": {
            "novelty": 1.0,
            "technical_soundness": 1.0,
            "experimental_rigor": 1.0,
            "reproducibility": 1.0,
            "writing_quality": 1.0,
            "compliance": 0.8,
        },
        "rubric": {
            "novelty": "Contribution is clearly positioned against prior work.",
            "technical_soundness": "Core claims are backed by validated evidence.",
            "experimental_rigor": "Baselines and ablations support the conclusion.",
            "reproducibility": "Artifacts make the result independently checkable.",
            "writing_quality": "The paper has the expected academic structure.",
            "compliance": "Required limitations and references are present.",
        },
        "formatting_requirements": ["has_limitations", "has_references"],
        "content_policies": [],
    },
    "ccf-b": {
        "display_name": "CCF-B Quality Target",
        "acceptance_threshold": 0.82,
        "dimension_weights": {
            "novelty": 1.2,
            "technical_soundness": 1.3,
            "experimental_rigor": 1.2,
            "reproducibility": 1.0,
            "writing_quality": 0.8,
            "compliance": 0.8,
        },
        "rubric": {
            "novelty": "Innovation significance is clear for a CCF-B-level venue.",
            "technical_soundness": "Technical depth and claim evidence are strong.",
            "experimental_rigor": "Datasets, baselines, ablations, and sanity checks are convincing.",
            "reproducibility": "Commands, configs, data hashes, and evidence maps are complete.",
            "writing_quality": "Organization and presentation are ready for external review.",
            "compliance": "Ethics, reproducibility, limitations, and references are documented.",
        },
        "formatting_requirements": ["has_limitations", "has_references"],
        "content_policies": [
            "has_ethics_statement",
            "has_reproducibility_statement",
        ],
    },
}
