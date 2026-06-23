"""Loop Engineering campaign records, optimizer, and report artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.schemas import ResearchCandidate, ValidationStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _record_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class LoopDecisionPolicy(str, Enum):
    """Allowed candidate-selection policies for the closed loop."""

    DOE_GRID = "doe_grid"
    EVIDENCE_GAIN = "evidence_gain"
    REPAIR_OR_FREEZE = "repair_or_freeze"


class LoopFailureCategory(str, Enum):
    """Loop Engineering failure categories."""

    SOURCE = "source"
    PROTOCOL = "protocol"
    EXECUTION = "execution"
    METRIC = "metric"
    VALIDATION = "validation"
    REVIEW = "review"
    COST = "cost"
    SAFETY = "safety"


class LoopCandidateArm(BaseModel):
    """One candidate arm in the campaign search space."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    expected_gain: float = Field(default=0.0, ge=-1.0, le=1.0)
    estimated_cost: float = Field(default=1.0, ge=0.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


class ClosedLoopCampaign(BaseModel):
    """Protocol-as-code campaign envelope for one autonomous research loop."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(default_factory=lambda: _record_id("loop_campaign"))
    project_id: str = Field(min_length=1)
    cycle_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    target_metric: str = Field(min_length=1)
    baseline_metric: float | None = Field(default=None, ge=0.0)
    budget: dict[str, int | float] = Field(default_factory=dict)
    candidate_space: list[LoopCandidateArm] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    approval_policy: str = Field(min_length=1)
    evidence_requirements: list[str] = Field(min_length=1)
    protocol_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    status: str = "active"


class LoopSelectionDecision(BaseModel):
    """Auditable selector output for the next loop iteration."""

    model_config = ConfigDict(extra="forbid")

    selected_candidate_id: str = Field(min_length=1)
    decision_policy: LoopDecisionPolicy
    decision_rationale: str = Field(min_length=1)
    score: float
    frozen_dimensions: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)


class LoopIterationRecord(BaseModel):
    """One closed-loop iteration with evidence and metadata bindings."""

    model_config = ConfigDict(extra="forbid")

    iteration_id: str = Field(default_factory=lambda: _record_id("loop_iter"))
    campaign_id: str = Field(min_length=1)
    cycle_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    decision_policy: LoopDecisionPolicy
    decision_rationale: str = Field(min_length=1)
    baseline_metric: float | None = Field(default=None, ge=0.0)
    result_metric: float | None = Field(default=None, ge=0.0)
    validation_status: ValidationStatus
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    run_id: str | None = Field(default=None, min_length=1)
    config_hash: str | None = Field(default=None, min_length=1)
    data_hash: str | None = Field(default=None, min_length=1)
    source_hash: str | None = Field(default=None, min_length=1)
    reproduction_delta: float = Field(default=1.0, ge=0.0)
    failure_category: LoopFailureCategory | None = None
    retry_allowed: bool = False
    repair_hypothesis: str | None = Field(default=None, min_length=1)
    frozen_dimensions: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None


class LoopMetrics(BaseModel):
    """Metrics used by publication and strategy gates."""

    model_config = ConfigDict(extra="forbid")

    acceleration_factor: float = Field(ge=0.0)
    enhancement_factor: float = Field(ge=0.0)
    experiment_count: int = Field(ge=0)
    failure_recovery_rate: float = Field(ge=0.0, le=1.0)
    reproduction_delta: float = Field(ge=0.0)
    metadata_completeness: float = Field(ge=0.0, le=1.0)
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    reward: float


class LoopQualityGate(BaseModel):
    """Deterministic gate for campaign promotion and publication use."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class LoopReportArtifact:
    """Paths and gate results written for one loop campaign."""

    json_path: Path
    markdown_path: Path
    vault_path: Path | None
    metrics: LoopMetrics
    quality_gate: LoopQualityGate

    def to_summary(self) -> dict[str, Any]:
        return {
            "json_path": self.json_path.as_posix(),
            "markdown_path": self.markdown_path.as_posix(),
            "vault_path": self.vault_path.as_posix() if self.vault_path is not None else None,
            "metrics": self.metrics.model_dump(mode="json"),
            "quality_gate": self.quality_gate.model_dump(mode="json"),
        }


FAILURE_CATEGORY_TERMS: dict[LoopFailureCategory, tuple[str, ...]] = {
    LoopFailureCategory.SOURCE: ("source", "rate limit", "429", "api", "retrieval", "doi"),
    LoopFailureCategory.PROTOCOL: ("protocol", "config", "schema", "plan", "entrypoint"),
    LoopFailureCategory.EXECUTION: ("runtime", "timeout", "exception", "exit", "subprocess"),
    LoopFailureCategory.METRIC: ("metric", "metrics.json", "bounds", "nan", "score"),
    LoopFailureCategory.VALIDATION: ("validation", "validator", "evidence", "reproduction"),
    LoopFailureCategory.REVIEW: ("review", "audit", "needs_revision", "publication"),
    LoopFailureCategory.COST: ("budget", "cost", "token", "gpu", "quota"),
    LoopFailureCategory.SAFETY: ("permission", "approval", "secret", "sandbox", "license"),
}


def build_closed_loop_campaign(
    *,
    candidate: ResearchCandidate,
    project_id: str,
    cycle_id: str,
    research_plan: Mapping[str, Any],
) -> ClosedLoopCampaign:
    """Build the campaign envelope after the research-plan gate passes."""

    plan_payload = _dict(research_plan.get("plan"))
    metric = _target_metric(plan_payload)
    objective = _text(plan_payload.get("problem_statement")) or candidate.description
    evidence_refs = _string_list(plan_payload.get("evidence_refs")) or candidate.evidence_refs
    protocol_refs = [
        ref
        for ref in (
            _text(research_plan.get("json_path")),
            _text(research_plan.get("markdown_path")),
            _text(research_plan.get("tex_path")),
        )
        if ref
    ]
    candidate_space = _candidate_space(candidate, plan_payload, evidence_refs)
    return ClosedLoopCampaign(
        project_id=project_id,
        cycle_id=cycle_id,
        objective=objective,
        target_metric=metric,
        baseline_metric=_baseline_metric(candidate, plan_payload),
        budget={
            "max_iterations": 3,
            "max_failed_retries": 1,
            "manual_baseline_iterations": 6,
        },
        candidate_space=candidate_space,
        constraints=[
            "LLM proposals cannot override evidence, budget, safety, or approval gates.",
            "Every claim must bind to run, validation, literature, or review artifacts.",
            "Only computational experiments are in scope for v1; wet-lab/cloud-lab execution is future work.",
        ],
        stop_conditions=[
            "budget exhausted",
            "no improvement after configured iterations",
            "reproduction_delta above threshold",
            "metadata_completeness below threshold",
            "repeated source/API/executor failures",
            "human approval required",
        ],
        approval_policy="approve-dangerous for online retrieval, local execution, and strategy promotion",
        evidence_requirements=[
            "candidate record",
            "research plan",
            "literature summary",
            "similarity summary",
            "run record",
            "validation report",
            "evidence map",
            "reproduction report",
        ],
        protocol_refs=protocol_refs,
    )


def select_loop_candidate(
    campaign: ClosedLoopCampaign,
    previous_iterations: Iterable[LoopIterationRecord] = (),
) -> LoopSelectionDecision:
    """Select the next arm with DOE first, then evidence-gain scoring."""

    previous = tuple(previous_iterations)
    tried = {iteration.selected_candidate_id for iteration in previous}
    remaining = [
        candidate for candidate in campaign.candidate_space if candidate.candidate_id not in tried
    ]
    if not previous:
        selected = campaign.candidate_space[0]
        return LoopSelectionDecision(
            selected_candidate_id=selected.candidate_id,
            decision_policy=LoopDecisionPolicy.DOE_GRID,
            decision_rationale=(
                "Initial DOE arm establishes the protocol baseline before LLM-generated "
                "or optimizer-ranked variants can be trusted."
            ),
            score=_candidate_score(selected),
            rejected_candidate_ids=[
                candidate.candidate_id for candidate in campaign.candidate_space[1:]
            ],
        )

    failed = [iteration for iteration in previous if iteration.failure_category is not None]
    if failed:
        last_failure = failed[-1]
        failure_category = last_failure.failure_category or LoopFailureCategory.EXECUTION
        selected = remaining[0] if remaining else _candidate_by_id(campaign, last_failure.selected_candidate_id)
        return LoopSelectionDecision(
            selected_candidate_id=selected.candidate_id,
            decision_policy=LoopDecisionPolicy.REPAIR_OR_FREEZE,
            decision_rationale=(
                f"Previous iteration hit {failure_category.value}; retry only "
                "after recording a repair hypothesis or freezing the failing dimension."
            ),
            score=_candidate_score(selected),
            frozen_dimensions=last_failure.frozen_dimensions or ["failed-dimension"],
            rejected_candidate_ids=[
                candidate.candidate_id
                for candidate in campaign.candidate_space
                if candidate.candidate_id != selected.candidate_id
            ],
        )

    candidates = remaining or list(campaign.candidate_space)
    selected = max(candidates, key=_candidate_score)
    return LoopSelectionDecision(
        selected_candidate_id=selected.candidate_id,
        decision_policy=LoopDecisionPolicy.EVIDENCE_GAIN,
        decision_rationale=(
            "Selected by expected evidence gain after subtracting cost and risk penalties."
        ),
        score=_candidate_score(selected),
        rejected_candidate_ids=[
            candidate.candidate_id
            for candidate in campaign.candidate_space
            if candidate.candidate_id != selected.candidate_id
        ],
    )


def classify_loop_failure(text: str) -> LoopFailureCategory:
    """Classify a failure using Loop Engineering categories."""

    normalized = text.casefold()
    for category, terms in FAILURE_CATEGORY_TERMS.items():
        if any(term in normalized for term in terms):
            return category
    return LoopFailureCategory.EXECUTION


def create_loop_iteration_from_cycle_summary(
    *,
    campaign: ClosedLoopCampaign,
    decision: LoopSelectionDecision,
    summary: Mapping[str, Any],
    base_dir: Path | str,
) -> LoopIterationRecord:
    """Convert a cycle summary into a physical loop iteration record."""

    root = Path(base_dir)
    demo = _dict(summary.get("demo"))
    reproduction = _dict(summary.get("reproduction_check"))
    run_record_path = _resolve_path(demo.get("run_record_path"), root)
    run_record = _read_json_if_exists(run_record_path)
    run_payload = _dict(run_record.get("run"))
    metrics = _dict(_dict(run_record.get("metrics")).get("values"))
    validation_report = _dict(run_record.get("validation_report"))
    validation_status = _validation_status(_text(validation_report.get("status")))
    result_metric = _metric_value(metrics, campaign.target_metric)
    baseline_metric = _baseline_from_metrics(metrics, campaign.baseline_metric)
    reproduction_delta = 0.0 if _text(reproduction.get("status")) == "passed" else 1.0
    failure_category = None
    repair_hypothesis = None
    if validation_status is not ValidationStatus.PASSED:
        failure_text = " ".join(
            [
                _text(run_payload.get("status")),
                _text(run_payload.get("error_type")),
                _text(validation_report.get("status")),
                "validation",
            ]
        )
        failure_category = classify_loop_failure(failure_text)
        repair_hypothesis = (
            f"Investigate {failure_category.value} failure before retrying this arm."
        )
    artifact_refs = _artifact_refs(summary, run_record_path)
    evidence_refs = _evidence_refs(summary, artifact_refs)
    return LoopIterationRecord(
        campaign_id=campaign.campaign_id,
        cycle_id=campaign.cycle_id,
        selected_candidate_id=decision.selected_candidate_id,
        decision_policy=decision.decision_policy,
        decision_rationale=decision.decision_rationale,
        baseline_metric=baseline_metric,
        result_metric=result_metric,
        validation_status=validation_status,
        evidence_refs=evidence_refs,
        artifact_refs=artifact_refs,
        run_id=_text(run_payload.get("id")) or None,
        config_hash=_text(run_payload.get("config_hash")) or None,
        data_hash=_text(run_payload.get("data_hash")) or None,
        source_hash=_text(run_payload.get("data_hash")) or None,
        reproduction_delta=reproduction_delta,
        failure_category=failure_category,
        retry_allowed=failure_category is not None,
        repair_hypothesis=repair_hypothesis,
        frozen_dimensions=decision.frozen_dimensions,
        completed_at=_utc_now(),
    )


def compute_loop_metrics(
    campaign: ClosedLoopCampaign,
    iterations: Iterable[LoopIterationRecord],
) -> LoopMetrics:
    """Compute Loop Engineering metrics for gates and reports."""

    records = tuple(iterations)
    experiment_count = len(records)
    if experiment_count == 0:
        return LoopMetrics(
            acceleration_factor=0.0,
            enhancement_factor=0.0,
            experiment_count=0,
            failure_recovery_rate=0.0,
            reproduction_delta=1.0,
            metadata_completeness=0.0,
            evidence_coverage=0.0,
            reward=-1.0,
        )
    latest = records[-1]
    baseline_metric = latest.baseline_metric or campaign.baseline_metric or 0.0
    result_metric = latest.result_metric or 0.0
    enhancement_factor = _enhancement_factor(baseline_metric, result_metric)
    manual_iterations = float(campaign.budget.get("manual_baseline_iterations", experiment_count))
    acceleration_factor = manual_iterations / max(float(experiment_count), 1.0)
    reproduction_delta = max(iteration.reproduction_delta for iteration in records)
    metadata_completeness = _metadata_completeness(records)
    evidence_coverage = _evidence_coverage(campaign, records)
    failure_recovery_rate = _failure_recovery_rate(records)
    quality_gain = max(enhancement_factor - 1.0, 0.0)
    reward = (
        quality_gain
        + 0.25 * evidence_coverage
        + 0.25 * metadata_completeness
        + 0.15 * failure_recovery_rate
        - 0.20 * reproduction_delta
    )
    return LoopMetrics(
        acceleration_factor=round(acceleration_factor, 6),
        enhancement_factor=round(enhancement_factor, 6),
        experiment_count=experiment_count,
        failure_recovery_rate=round(failure_recovery_rate, 6),
        reproduction_delta=round(reproduction_delta, 6),
        metadata_completeness=round(metadata_completeness, 6),
        evidence_coverage=round(evidence_coverage, 6),
        reward=round(reward, 6),
    )


def evaluate_loop_quality_gate(
    campaign: ClosedLoopCampaign,
    iterations: Iterable[LoopIterationRecord],
    metrics: LoopMetrics,
) -> LoopQualityGate:
    """Block campaign use when loop evidence is not publication-safe."""

    records = tuple(iterations)
    issues: list[str] = []
    warnings: list[str] = []
    if not records:
        issues.append("campaign has no executed loop iterations")
    if metrics.metadata_completeness < 0.90:
        issues.append("metadata_completeness below 0.90")
    if metrics.evidence_coverage < 0.80:
        issues.append("evidence_coverage below 0.80")
    if metrics.reproduction_delta > 0.05:
        issues.append("reproduction_delta above 0.05")
    if any(record.validation_status is not ValidationStatus.PASSED for record in records):
        issues.append("one or more loop iterations failed validation")
    if not campaign.protocol_refs:
        warnings.append("campaign has no protocol_refs")
    if metrics.enhancement_factor < 1.0:
        warnings.append("latest result does not exceed baseline metric")
    return LoopQualityGate(
        passed=not issues,
        issues=list(dict.fromkeys(issues)),
        warnings=list(dict.fromkeys(warnings)),
    )


def write_loop_report_artifact(
    *,
    campaign: ClosedLoopCampaign,
    iterations: Iterable[LoopIterationRecord],
    output_dir: Path | str,
    vault_root: Path | str | None = None,
    project_id: str | None = None,
) -> LoopReportArtifact:
    """Write campaign JSON, Markdown report, and optional Obsidian progress note."""

    records = tuple(iterations)
    metrics = compute_loop_metrics(campaign, records)
    gate = evaluate_loop_quality_gate(campaign, records, metrics)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "loop-campaign.json"
    markdown_path = root / "loop-report.md"
    payload = {
        "campaign": campaign.model_dump(mode="json"),
        "iterations": [record.model_dump(mode="json") for record in records],
        "metrics": metrics.model_dump(mode="json"),
        "quality_gate": gate.model_dump(mode="json"),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    markdown = render_loop_report_markdown(
        campaign=campaign,
        iterations=records,
        metrics=metrics,
        gate=gate,
        json_path=json_path,
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    vault_path: Path | None = None
    if vault_root is not None and project_id:
        store = MarkdownKnowledgeStore(Path(vault_root))
        relative_path = (
            Path("projects")
            / project_id
            / "progress"
            / f"loop-report-{_slug(campaign.cycle_id)}.md"
        )
        entry = KnowledgeEntry(
            entry_type=KnowledgeEntryType.PROJECT_PROGRESS,
            zone=KnowledgeZone.PROJECT,
            title=f"Loop Engineering report {campaign.cycle_id}",
            project_id=project_id,
            tags=["loop-engineering", "closed-loop", "campaign", gate_status(gate)],
            keywords=[
                "loop-engineering",
                campaign.project_id,
                campaign.cycle_id,
                campaign.target_metric,
            ],
            source_refs=[json_path.as_posix(), markdown_path.as_posix(), *campaign.protocol_refs],
            body=markdown,
        )
        vault_path = store.write_entry(relative_path, entry)

    return LoopReportArtifact(
        json_path=json_path,
        markdown_path=markdown_path,
        vault_path=vault_path,
        metrics=metrics,
        quality_gate=gate,
    )


def gate_status(gate: LoopQualityGate) -> str:
    return "passed" if gate.passed else "blocked"


def render_loop_report_markdown(
    *,
    campaign: ClosedLoopCampaign,
    iterations: Iterable[LoopIterationRecord],
    metrics: LoopMetrics,
    gate: LoopQualityGate,
    json_path: Path | str,
) -> str:
    """Render a compact Obsidian-readable loop report."""

    records = tuple(iterations)
    lines = [
        f"# Loop Engineering Report {campaign.cycle_id}",
        "",
        f"- Campaign: `{campaign.campaign_id}`",
        f"- Project: `{campaign.project_id}`",
        f"- Objective: {campaign.objective}",
        f"- Target metric: `{campaign.target_metric}`",
        f"- Gate: `{gate_status(gate)}`",
        f"- JSON: `{Path(json_path).as_posix()}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| AF | {metrics.acceleration_factor:.6f} |",
        f"| EF | {metrics.enhancement_factor:.6f} |",
        f"| Experiment count | {metrics.experiment_count} |",
        f"| Failure recovery rate | {metrics.failure_recovery_rate:.6f} |",
        f"| Reproduction delta | {metrics.reproduction_delta:.6f} |",
        f"| Metadata completeness | {metrics.metadata_completeness:.6f} |",
        f"| Evidence coverage | {metrics.evidence_coverage:.6f} |",
        f"| Reward | {metrics.reward:.6f} |",
        "",
        "## Quality Gate",
        "",
        "### Issues",
        "",
        *(_list_items(gate.issues)),
        "",
        "### Warnings",
        "",
        *(_list_items(gate.warnings)),
        "",
        "## Candidate Selection",
        "",
        "| Arm | Expected gain | Cost | Risk | Rationale |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for arm in campaign.candidate_space:
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{arm.candidate_id}`",
                    f"{arm.expected_gain:.3f}",
                    f"{arm.estimated_cost:.3f}",
                    f"{arm.risk_score:.3f}",
                    _table(arm.rationale),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Iterations",
            "",
            "| Iteration | Policy | Candidate | Result | Baseline | Reproduction delta | Validation | Evidence |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | ---: |",
        ]
    )
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{record.iteration_id}`",
                    f"`{record.decision_policy.value}`",
                    f"`{record.selected_candidate_id}`",
                    _number(record.result_metric),
                    _number(record.baseline_metric),
                    f"{record.reproduction_delta:.6f}",
                    f"`{record.validation_status.value}`",
                    str(len(record.evidence_refs) + len(record.artifact_refs)),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Stop Conditions",
            "",
            *[f"- {item}" for item in campaign.stop_conditions],
            "",
            "## Evidence Requirements",
            "",
            *[f"- {item}" for item in campaign.evidence_requirements],
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _candidate_space(
    candidate: ResearchCandidate,
    plan_payload: Mapping[str, Any],
    evidence_refs: list[str],
) -> list[LoopCandidateArm]:
    method = _metadata_value(candidate.metadata, "method", "planned method")
    baseline = _metadata_value(candidate.metadata, "baseline", "baseline control")
    experiments = _string_list(plan_payload.get("experiments"))
    return [
        LoopCandidateArm(
            candidate_id="arm_baseline_reproduction",
            label="Baseline reproduction",
            parameters={"protocol": "baseline", "baseline": baseline},
            expected_gain=0.0,
            estimated_cost=1.0,
            risk_score=0.05,
            evidence_refs=evidence_refs,
            rationale="Reproduce the baseline before changing the method.",
        ),
        LoopCandidateArm(
            candidate_id="arm_proposed_method",
            label="Proposed method",
            parameters={"protocol": "proposed_method", "method": method},
            expected_gain=0.12,
            estimated_cost=1.25,
            risk_score=0.20,
            evidence_refs=evidence_refs,
            rationale="Evaluate the main planned method under the same metric contract.",
        ),
        LoopCandidateArm(
            candidate_id="arm_ablation",
            label="Ablation",
            parameters={"protocol": "ablation", "step_count": len(experiments)},
            expected_gain=0.04,
            estimated_cost=0.80,
            risk_score=0.10,
            evidence_refs=evidence_refs,
            rationale="Isolate whether the claimed mechanism explains the metric change.",
        ),
    ]


def _target_metric(plan_payload: Mapping[str, Any]) -> str:
    text = " ".join(
        _text(value)
        for value in (
            plan_payload.get("technical_details"),
            plan_payload.get("methods"),
            " ".join(_string_list(plan_payload.get("experiments"))),
        )
    ).casefold()
    for metric in (
        "macro_f1",
        "macro f1",
        "accuracy",
        "auc",
        "mae",
        "rmse",
        "evidence coverage",
        "reviewer pass rate",
    ):
        if metric in text:
            return metric.replace(" ", "_")
    return "primary_metric"


def _baseline_metric(candidate: ResearchCandidate, plan_payload: Mapping[str, Any]) -> float | None:
    for source in (candidate.metadata, plan_payload.get("metadata")):
        if isinstance(source, Mapping):
            value = source.get("baseline_metric")
            parsed = _float_or_none(value)
            if parsed is not None and parsed >= 0.0:
                return parsed
    return None


def _metadata_value(metadata: Mapping[str, Any], key: str, default: str) -> str:
    value = metadata.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _candidate_score(candidate: LoopCandidateArm) -> float:
    return round(candidate.expected_gain - 0.05 * candidate.estimated_cost - candidate.risk_score, 6)


def _candidate_by_id(campaign: ClosedLoopCampaign, candidate_id: str) -> LoopCandidateArm:
    for candidate in campaign.candidate_space:
        if candidate.candidate_id == candidate_id:
            return candidate
    return campaign.candidate_space[0]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item)]


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _resolve_path(path_value: object, base_dir: Path) -> Path | None:
    text = _text(path_value)
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([base_dir / path, Path.cwd() / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _read_json_if_exists(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _validation_status(value: str) -> ValidationStatus:
    normalized = value.strip().casefold()
    for status in ValidationStatus:
        if status.value == normalized:
            return status
    if normalized in {"pass", "success", "ok"}:
        return ValidationStatus.PASSED
    return ValidationStatus.FAILED


def _metric_value(metrics: Mapping[str, Any], target_metric: str) -> float | None:
    target = target_metric.casefold()
    candidates = [target, target.replace("_", " "), "accuracy", "macro_f1", "f1"]
    for key in candidates:
        for metric_name, value in metrics.items():
            if metric_name.casefold() == key:
                parsed = _float_or_none(value)
                if parsed is not None:
                    return parsed
    for value in metrics.values():
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _baseline_from_metrics(
    metrics: Mapping[str, Any],
    campaign_baseline: float | None,
) -> float | None:
    for key in (
        "baseline_accuracy",
        "ablation_accuracy_first8",
        "zscore_centroid_accuracy",
        "baseline_metric",
    ):
        parsed = _float_or_none(metrics.get(key))
        if parsed is not None:
            return parsed
    return campaign_baseline


def _artifact_refs(summary: Mapping[str, Any], run_record_path: Path | None) -> list[str]:
    refs = [
        _text(run_record_path.as_posix() if run_record_path is not None else ""),
        _text(_dict(summary.get("demo")).get("report_path")),
        _text(_dict(summary.get("demo")).get("validation_json_path")),
        _text(_dict(summary.get("demo")).get("evidence_map_path")),
        _text(_dict(summary.get("reproduction_check")).get("json_path")),
        _text(_dict(summary.get("research_plan")).get("json_path")),
    ]
    return sorted({ref for ref in refs if ref})


def _evidence_refs(summary: Mapping[str, Any], artifact_refs: list[str]) -> list[str]:
    refs = [
        *_string_list(_dict(summary.get("candidate")).get("evidence_refs")),
        _text(_dict(summary.get("literature")).get("summary_path")),
        _text(_dict(summary.get("similarity")).get("summary_path")),
        *artifact_refs,
    ]
    return sorted({ref for ref in refs if ref})


def _enhancement_factor(baseline_metric: float, result_metric: float) -> float:
    if baseline_metric > 0.0:
        return max(result_metric / baseline_metric, 0.0)
    if result_metric > 0.0:
        return 1.0 + result_metric
    return 0.0


def _metadata_completeness(records: tuple[LoopIterationRecord, ...]) -> float:
    required = (
        "run_id",
        "config_hash",
        "data_hash",
        "decision_rationale",
        "decision_policy",
        "selected_candidate_id",
        "baseline_metric",
        "result_metric",
        "validation_status",
        "evidence_refs",
        "artifact_refs",
        "failure_review",
    )
    scores: list[float] = []
    for record in records:
        present = 0
        for field in required:
            if field == "failure_review":
                if record.failure_category is None or record.repair_hypothesis or record.frozen_dimensions:
                    present += 1
                continue
            value = getattr(record, field)
            if value not in (None, "", [], ()):
                present += 1
        scores.append(present / len(required))
    return sum(scores) / len(scores)


def _evidence_coverage(
    campaign: ClosedLoopCampaign,
    records: tuple[LoopIterationRecord, ...],
) -> float:
    refs = {
        ref
        for record in records
        for ref in (*record.evidence_refs, *record.artifact_refs)
        if ref
    }
    required_count = max(len(campaign.evidence_requirements), 1)
    return min(1.0, len(refs) / required_count)


def _failure_recovery_rate(records: tuple[LoopIterationRecord, ...]) -> float:
    failures = [record for record in records if record.failure_category is not None]
    if not failures:
        return 1.0
    recoverable = [
        record
        for record in failures
        if record.repair_hypothesis or record.frozen_dimensions or record.retry_allowed
    ]
    return len(recoverable) / len(failures)


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _list_items(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return slug or "loop"
