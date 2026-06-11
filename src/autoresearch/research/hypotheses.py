"""Hypothesis generation from approved research candidates."""

from __future__ import annotations

from dataclasses import dataclass

from autoresearch.schemas import CandidateStatus, Hypothesis, ResearchCandidate, TaskStatus


@dataclass(frozen=True)
class HypothesisGenerationConfig:
    """Defaults for deterministic hypothesis generation."""

    default_baseline: str = "best retrieved baseline"
    max_hypotheses: int = 1


def generate_hypotheses(
    candidate: ResearchCandidate,
    *,
    config: HypothesisGenerationConfig = HypothesisGenerationConfig(),
) -> list[Hypothesis]:
    """Convert an approved research candidate into measurable hypotheses."""

    if candidate.status is not CandidateStatus.APPROVED:
        msg = "candidate must be approved before hypothesis generation"
        raise PermissionError(msg)

    method = str(candidate.metadata.get("method", "candidate method"))
    dataset = str(candidate.metadata.get("dataset", "target benchmark"))
    limitation = str(candidate.metadata.get("limitation", candidate.research_gap))
    metric = _metric_for_limitation(limitation)
    baseline = str(candidate.metadata.get("baseline", config.default_baseline))

    hypothesis = Hypothesis(
        candidate_id=candidate.id,
        statement=(
            f"{method} can improve {metric} for {limitation} on {dataset} "
            "relative to the selected baseline."
        ),
        prediction=f"{metric} improves against {baseline}.",
        metric=metric,
        baseline=baseline,
        dataset_ref=dataset,
        evidence_refs=candidate.evidence_refs,
        status=TaskStatus.DRAFT,
        metadata={
            "source_candidate_title": candidate.title,
            "method": method,
            "limitation": limitation,
            "dataset": dataset,
        },
    )
    return [hypothesis][: config.max_hypotheses]


def _metric_for_limitation(limitation: str) -> str:
    normalized = limitation.casefold()
    if "reproducibility" in normalized:
        return "reproducibility_rate"
    if "cost" in normalized:
        return "cost_per_successful_run"
    if "latency" in normalized:
        return "latency_seconds"
    if "weak evidence" in normalized or "citation hallucination" in normalized:
        return "evidence_precision"
    if "generalization" in normalized:
        return "generalization_score"
    return "primary_validation_score"
