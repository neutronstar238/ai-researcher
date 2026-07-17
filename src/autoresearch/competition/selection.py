"""Deterministic topic hard filtering, ranking, and feasibility selection."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from autoresearch.competition.models import (
    CompetitionRunSpec,
    CompetitionScorecard,
    TopicCandidate,
    TopicFeasibility,
    TopicMode,
    TopicSelectionReport,
)

MDBENCH_REPOSITORY = "https://github.com/gryaklab/mdbench"
MDBENCH_PAPER = "https://arxiv.org/abs/2509.20529"
MDBENCH_DATASET = "https://doi.org/10.5281/zenodo.17611099"


class TopicSelectionError(RuntimeError):
    """Raised only for invalid selector inputs, never for a scientific no-result."""


FeasibilityProbe = Callable[[TopicCandidate], TopicFeasibility]


class TopicSelectionEngine:
    """Apply hard gates, rubric ranking, and real top-k smoke evidence."""

    def select(
        self,
        *,
        spec: CompetitionRunSpec,
        candidates: Sequence[TopicCandidate],
        probe: FeasibilityProbe,
    ) -> TopicSelectionReport:
        if not candidates:
            return TopicSelectionReport(
                selected_topic_id=None,
                ranked_topic_ids=(),
                hard_filter_failures={},
                feasibility=(),
                decision_policy=_DECISION_POLICY,
                negative_reason="no topic candidates were generated",
            )

        topic_ids = [candidate.topic_id for candidate in candidates]
        if len(set(topic_ids)) != len(topic_ids):
            raise TopicSelectionError("topic candidate IDs must be unique")

        ranked = sorted(candidates, key=_ranking_key)
        failures = {
            candidate.topic_id: candidate.hard_filter_failures()
            for candidate in ranked
        }
        eligible = [candidate for candidate in ranked if not failures[candidate.topic_id]]
        feasibility: list[TopicFeasibility] = []
        for candidate in eligible[: spec.max_feasibility_candidates]:
            try:
                result = probe(candidate)
            except Exception as exc:  # a failed probe is evidence, not a user question
                result = TopicFeasibility(
                    topic_id=candidate.topic_id,
                    passed=False,
                    metric_name="feasibility_probe",
                    failure_reason=f"{type(exc).__name__}: {exc}",
                )
            if result.topic_id != candidate.topic_id:
                raise TopicSelectionError(
                    "feasibility result topic_id does not match the probed candidate"
                )
            feasibility.append(result)

        passed_ids = {result.topic_id for result in feasibility if result.passed}
        selected = next(
            (candidate for candidate in eligible if candidate.topic_id in passed_ids),
            None,
        )
        negative_reason = None
        if selected is None:
            if not eligible:
                negative_reason = "all topic candidates failed hard feasibility gates"
            else:
                negative_reason = "no top-ranked topic passed its executable feasibility smoke"
        return TopicSelectionReport(
            selected_topic_id=selected.topic_id if selected is not None else None,
            ranked_topic_ids=tuple(candidate.topic_id for candidate in ranked),
            hard_filter_failures=failures,
            feasibility=tuple(feasibility),
            decision_policy=_DECISION_POLICY,
            negative_reason=negative_reason,
        )


def competition_topic_candidates(spec: CompetitionRunSpec) -> tuple[TopicCandidate, ...]:
    """Return Gate-A-first candidates for automatic or optionally seeded operation."""

    if spec.topic_mode is TopicMode.SEEDED:
        return (_seeded_candidate(spec), *_gate_a_candidates()[1:])
    return _gate_a_candidates()


def selected_candidate(
    candidates: Sequence[TopicCandidate],
    report: TopicSelectionReport,
) -> TopicCandidate | None:
    """Resolve the selected candidate without silently falling back."""

    if report.selected_topic_id is None:
        return None
    for candidate in candidates:
        if candidate.topic_id == report.selected_topic_id:
            return candidate
    raise TopicSelectionError("selection report references an unknown topic candidate")


def _gate_a_candidates() -> tuple[TopicCandidate, ...]:
    first = TopicCandidate(
        topic_id="topic_mdbench_noise_robust_sparse",
        title="Noise-robust sparse equation discovery on MDBench",
        problem_statement=(
            "Discover governing equations from clean and noisy dynamical-system trajectories "
            "while preserving exact execution and equation-level evidence."
        ),
        innovation_claim=(
            "Use evidence-bound threshold calibration and repeated-seed stability to "
            "select a compact equation without hiding negative benchmark outcomes."
        ),
        literature_evidence=(MDBENCH_PAPER, MDBENCH_REPOSITORY),
        dataset_refs=(MDBENCH_DATASET,),
        baseline_methods=("SINDy", "PySR", "Operon"),
        metrics=(
            "derivative_nmse",
            "equation_structure_f1",
            "trajectory_extrapolation_rmse",
            "model_complexity",
            "runtime_seconds",
        ),
        falsification_conditions=(
            "candidate derivative NMSE does not improve over the constant baseline",
            "the discovered active terms disagree with the known governing equation",
            "three seeded executions do not reproduce the direction of effect",
        ),
        scorecard=CompetitionScorecard(
            scientific_value=37.0,
            technical_depth=28.0,
            application_potential=27.0,
        ),
        estimated_cost_usd=2.0,
        reproducibility_score=0.96,
        duplicate_risk=0.35,
        data_available=True,
        license_clear=True,
        compute_feasible=True,
        falsifiable=True,
        reproducible=True,
        adapter_ready=True,
        method_parameters={"coefficient_threshold": 0.05, "ridge": 1e-9},
    )
    second = first.model_copy(
        update={
            "topic_id": "topic_mdbench_stability_selection",
            "title": "Seed-stable polynomial library selection on MDBench",
            "innovation_claim": (
                "Promote only terms that remain active across bounded independent runs and "
                "report instability as a negative result."
            ),
            "scorecard": CompetitionScorecard(
                scientific_value=36.0,
                technical_depth=27.0,
                application_potential=26.0,
            ),
            "estimated_cost_usd": 1.5,
            "reproducibility_score": 0.97,
            "method_parameters": {"coefficient_threshold": 0.08, "ridge": 1e-8},
        }
    )
    third = first.model_copy(
        update={
            "topic_id": "topic_mdbench_complexity_calibrated",
            "title": "Complexity-calibrated model discovery on MDBench",
            "innovation_claim": (
                "Use an explicit complexity penalty and falsification gate to prevent a "
                "low-error but unnecessarily complex equation from being promoted."
            ),
            "scorecard": CompetitionScorecard(
                scientific_value=35.0,
                technical_depth=26.0,
                application_potential=25.0,
            ),
            "estimated_cost_usd": 1.0,
            "reproducibility_score": 0.95,
            "method_parameters": {"coefficient_threshold": 0.12, "ridge": 1e-7},
        }
    )
    return (
        first,
        second,
        third,
    )


def _seeded_candidate(spec: CompetitionRunSpec) -> TopicCandidate:
    base = _gate_a_candidates()[0]
    guidance = "; ".join(spec.guidance) or "No additional guidance supplied."
    references = tuple(dict.fromkeys((*spec.reference_uris, *base.literature_evidence)))
    return base.model_copy(
        update={
            "topic_id": "topic_seeded_mdbench",
            "title": spec.topic or "Seeded MDBench equation-discovery study",
            "problem_statement": (
                f"Seed constraint: {spec.topic or 'MDBench model discovery'}. "
                f"Guidance: {guidance}"
            ),
            "literature_evidence": references,
            "duplicate_risk": 0.5,
        }
    )


def _ranking_key(candidate: TopicCandidate) -> tuple[float, float, float, str]:
    return (
        -candidate.scorecard.total,
        candidate.estimated_cost_usd,
        -candidate.reproducibility_score,
        candidate.topic_id,
    )


_DECISION_POLICY = (
    "hard filters -> 40/30/30 descending -> top-3 executable smoke -> "
    "lower cost -> stronger reproducibility"
)
