"""Conservative review simulation for evidence-backed paper drafts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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
    scores: tuple[ReviewDimensionScore, ...]
    findings: tuple[ReviewFinding, ...]

    @property
    def overall_score(self) -> float:
        if not self.scores:
            return 0.0
        return round(sum(score.score for score in self.scores) / len(self.scores), 4)

    def score_for(self, dimension: ReviewDimension) -> float:
        for score in self.scores:
            if score.dimension is dimension:
                return score.score
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "overall_score": self.overall_score,
            "scores": [score.to_dict() for score in self.scores],
            "findings": [finding.to_dict() for finding in self.findings],
        }


def simulate_paper_review(context: PaperReviewContext) -> PaperReviewReport:
    """Score a paper draft conservatively using available evidence and metadata."""

    coverage = _evidence_coverage(context)
    findings = _findings(context, coverage)
    scores = (
        _score_novelty(context, coverage),
        _score_technical_soundness(context, coverage),
        _score_experimental_rigor(context),
        _score_reproducibility(context, coverage),
        _score_writing_quality(context),
        _score_compliance(context),
    )
    capped_scores = tuple(_cap_score(score, context.max_dimension_score) for score in scores)
    return PaperReviewReport(
        title=context.title,
        scores=capped_scores,
        findings=tuple(findings),
    )


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
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
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


def _score_compliance(context: PaperReviewContext) -> ReviewDimensionScore:
    if not context.compliance_checks:
        score = 0.55
        rationale = "No venue compliance checks were supplied; score is capped conservatively."
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
