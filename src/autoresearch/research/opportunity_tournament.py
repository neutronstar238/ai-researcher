"""Live, fail-closed tournament evidence for research-track selection.

Task 263.2 defines result-blind research opportunities.  This module binds
those contracts to evidence that can only be established at selection time:
live source/resource probes, an executable baseline smoke, a prospective
power calculation, and a license/data/compute audit.  The tournament uses no
weighted score and may select no track.

Passing this tournament is deliberately weaker than novelty-search admission.
It only selects a track whose strong baseline should be independently
reproduced next.  It does not create a candidate portfolio, reveal a
confirmatory panel, or authorize publication or external submission.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from pathlib import Path
from statistics import NormalDist
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .portfolio import (
    OpportunityAssessment,
    OpportunityStage,
    PortfolioIntegrityError,
    ResearchOpportunity,
    SourceMaturity,
    assess_research_opportunity,
)

TournamentRankingRule = Literal[
    "admitted tracks only; then more peer-reviewed nearest-work sources, "
    "lower frozen baseline-reproduction cost, more confirmatory independent "
    "units, and lexical track ID"
]
TOURNAMENT_RANKING_RULE: TournamentRankingRule = (
    "admitted tracks only; then more peer-reviewed nearest-work sources, "
    "lower frozen baseline-reproduction cost, more confirmatory independent "
    "units, and lexical track ID"
)


def _jsonable(value: Any) -> Any:
    """Convert nested inputs to the same JSON representation used after validation."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        rendered = value.isoformat()
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class ResourceKind(str, Enum):
    """Kinds of remote resources audited independently of scientific claims."""

    LITERATURE = "literature"
    REPOSITORY = "repository"
    DATASET = "dataset"
    LICENSE = "license"


class LiveResourceProbe(KernelContract):
    """Bounded live HTTP observation without copying a complete remote work."""

    schema_version: Literal["live-resource-probe-v1"] = "live-resource-probe-v1"
    resource_id: StableId
    kind: ResourceKind
    requested_url: NonEmptyText
    resolved_url: NonEmptyText
    status_code: int = Field(ge=0, le=599)
    sample_bytes: int = Field(ge=0)
    sample_sha256: Sha256
    reachable: bool
    checked_at: datetime
    error: NonEmptyText | None = None
    probe_hash: Sha256

    @model_validator(mode="after")
    def _validate_probe(self) -> LiveResourceProbe:
        expected_reachable = (
            200 <= self.status_code < 400
            and self.sample_bytes > 0
            and self.error is None
        )
        if self.reachable != expected_reachable:
            raise ValueError("resource reachability does not match HTTP evidence")
        if not self.reachable and self.error is None:
            raise ValueError("an unreachable resource probe requires an error")
        if self.probe_hash != self.calculated_hash():
            raise PortfolioIntegrityError("live resource probe_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> LiveResourceProbe:
        """Normalize one probe and attach its canonical digest."""

        payload = dict(values)
        payload["schema_version"] = "live-resource-probe-v1"
        payload["probe_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the probe digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"probe_hash"}))

    def verify_integrity(self) -> None:
        """Reject in-memory probe mutation."""

        if self.probe_hash != self.calculated_hash():
            raise PortfolioIntegrityError("live resource probe_hash mismatch")


def probe_web_resource(
    *,
    resource_id: str,
    kind: ResourceKind,
    url: str,
    checked_at: datetime,
    session: requests.Session | None = None,
    timeout_seconds: float = 30.0,
    max_sample_bytes: int = 65_536,
) -> LiveResourceProbe:
    """Read a bounded response prefix and retain only reachability metadata.

    A Range header is advisory: if a server ignores it, streaming still stops
    after ``max_sample_bytes``.  The digest therefore identifies the observed
    prefix, not an unobserved complete remote object.
    """

    if max_sample_bytes < 1:
        raise ValueError("max_sample_bytes must be positive")
    client = session or requests.Session()
    try:
        response = client.get(
            url,
            headers={
                "Range": f"bytes=0-{max_sample_bytes - 1}",
                "User-Agent": "AutoResearch/1.0 task-263.3 opportunity-tournament",
            },
            timeout=timeout_seconds,
            stream=True,
            allow_redirects=True,
        )
        sample = bytearray()
        for chunk in response.iter_content(chunk_size=8_192):
            if not chunk:
                continue
            remaining = max_sample_bytes - len(sample)
            sample.extend(chunk[:remaining])
            if len(sample) >= max_sample_bytes:
                break
        response.close()
        error = (
            None
            if 200 <= response.status_code < 400 and sample
            else f"HTTP {response.status_code} or empty response"
        )
        return LiveResourceProbe.create(
            resource_id=resource_id,
            kind=kind,
            requested_url=url,
            resolved_url=str(response.url),
            status_code=response.status_code,
            sample_bytes=len(sample),
            sample_sha256=hashlib.sha256(sample).hexdigest(),
            reachable=error is None,
            checked_at=checked_at,
            error=error,
        )
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"[:1_024]
        return LiveResourceProbe.create(
            resource_id=resource_id,
            kind=kind,
            requested_url=url,
            resolved_url=url,
            status_code=0,
            sample_bytes=0,
            sample_sha256=hashlib.sha256(b"").hexdigest(),
            reachable=False,
            checked_at=checked_at,
            error=error,
        )


class BaselineExecutionSmoke(KernelContract):
    """One bounded baseline command or an explicit pre-execution denial."""

    schema_version: Literal["baseline-execution-smoke-v1"] = (
        "baseline-execution-smoke-v1"
    )
    track_id: StableId
    baseline_id: StableId
    command: list[NonEmptyText] = Field(min_length=1)
    command_hash: Sha256
    environment_hash: Sha256
    attempted: bool
    exit_code: int | None
    timed_out: bool
    passed: bool
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    artifact_hashes: list[Sha256] = Field(min_length=1)
    checked_at: datetime
    blocked_reason: NonEmptyText | None = None
    smoke_hash: Sha256

    @field_validator("artifact_hashes")
    @classmethod
    def _normalize_artifact_hashes(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("baseline smoke artifact hashes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_smoke(self) -> BaselineExecutionSmoke:
        if self.command_hash != canonical_sha256(self.command):
            raise PortfolioIntegrityError("baseline smoke command_hash mismatch")
        if self.attempted and self.exit_code is None and not self.timed_out:
            raise ValueError("an attempted non-timeout smoke requires an exit code")
        if not self.attempted and (
            self.exit_code is not None or self.timed_out or self.blocked_reason is None
        ):
            raise ValueError("a denied smoke requires only a blocked reason")
        expected_passed = (
            self.attempted and not self.timed_out and self.exit_code == 0
        )
        if self.passed != expected_passed:
            raise ValueError("baseline smoke passed does not match command evidence")
        if self.passed and self.blocked_reason is not None:
            raise ValueError("a passing smoke cannot have a blocked reason")
        if self.smoke_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline execution smoke_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BaselineExecutionSmoke:
        """Normalize command evidence and attach its digest."""

        payload = dict(values)
        payload["schema_version"] = "baseline-execution-smoke-v1"
        payload["command"] = list(payload["command"])
        payload["command_hash"] = canonical_sha256(payload["command"])
        payload["artifact_hashes"] = sorted(payload["artifact_hashes"])
        payload["smoke_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the smoke digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"smoke_hash"}))

    def verify_integrity(self) -> None:
        """Reject command, result, or artifact mutation."""

        if self.command_hash != canonical_sha256(self.command):
            raise PortfolioIntegrityError("baseline smoke command_hash mismatch")
        if self.smoke_hash != self.calculated_hash():
            raise PortfolioIntegrityError("baseline execution smoke_hash mismatch")


def run_baseline_command_smoke(
    *,
    track_id: str,
    baseline_id: str,
    command: Sequence[str],
    cwd: Path,
    environment_hash: str,
    checked_at: datetime,
    artifact_hashes: Sequence[str],
    timeout_seconds: float = 120.0,
) -> BaselineExecutionSmoke:
    """Run one bounded, non-shell baseline command and hash its observations."""

    normalized_command = list(command)
    try:
        completed = subprocess.run(
            normalized_command,
            cwd=cwd,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return BaselineExecutionSmoke.create(
            track_id=track_id,
            baseline_id=baseline_id,
            command=normalized_command,
            environment_hash=environment_hash,
            attempted=True,
            exit_code=completed.returncode,
            timed_out=False,
            passed=completed.returncode == 0,
            stdout_sha256=hashlib.sha256(completed.stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(completed.stderr).hexdigest(),
            artifact_hashes=list(artifact_hashes),
            checked_at=checked_at,
            blocked_reason=(
                None
                if completed.returncode == 0
                else f"baseline command exited {completed.returncode}"
            ),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        return BaselineExecutionSmoke.create(
            track_id=track_id,
            baseline_id=baseline_id,
            command=normalized_command,
            environment_hash=environment_hash,
            attempted=True,
            exit_code=None,
            timed_out=True,
            passed=False,
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            artifact_hashes=list(artifact_hashes),
            checked_at=checked_at,
            blocked_reason=f"baseline command exceeded {timeout_seconds:g} seconds",
        )


def blocked_baseline_smoke(
    *,
    track_id: str,
    baseline_id: str,
    command: Sequence[str],
    environment_hash: str,
    checked_at: datetime,
    artifact_hashes: Sequence[str],
    reason: str,
) -> BaselineExecutionSmoke:
    """Record a license/safety/availability denial instead of executing code."""

    return BaselineExecutionSmoke.create(
        track_id=track_id,
        baseline_id=baseline_id,
        command=list(command),
        environment_hash=environment_hash,
        attempted=False,
        exit_code=None,
        timed_out=False,
        passed=False,
        stdout_sha256=hashlib.sha256(b"").hexdigest(),
        stderr_sha256=hashlib.sha256(reason.encode("utf-8")).hexdigest(),
        artifact_hashes=list(artifact_hashes),
        checked_at=checked_at,
        blocked_reason=reason,
    )


class PowerSensitivityAudit(KernelContract):
    """Prospective task-level sensitivity under explicit variance assumptions."""

    schema_version: Literal["power-sensitivity-audit-v1"] = (
        "power-sensitivity-audit-v1"
    )
    track_id: StableId
    analysis_unit: NonEmptyText
    independent_unit_count: int = Field(ge=6)
    alpha: float = Field(gt=0, le=0.05)
    target_power: float = Field(ge=0.8, lt=1)
    minimum_detectable_effect: float = Field(gt=0)
    assumed_unit_sd: float = Field(gt=0)
    calculation_method: Literal[
        "two-sided normal approximation over independent paired unit effects"
    ] = "two-sided normal approximation over independent paired unit effects"
    achieved_power: float = Field(ge=0, le=1)
    sensitivity_by_effect: dict[NonEmptyText, float] = Field(min_length=3)
    power_sufficient: bool
    prospective: Literal[True] = True
    seed_repeats_are_independent_units: Literal[False] = False
    audit_hash: Sha256

    @model_validator(mode="after")
    def _validate_power(self) -> PowerSensitivityAudit:
        if list(self.sensitivity_by_effect) != sorted(self.sensitivity_by_effect):
            raise ValueError("power sensitivity keys must be sorted")
        expected = _normal_approximation_power(
            independent_unit_count=self.independent_unit_count,
            effect=self.minimum_detectable_effect,
            assumed_unit_sd=self.assumed_unit_sd,
            alpha=self.alpha,
        )
        if not math.isclose(self.achieved_power, expected, abs_tol=1e-12):
            raise ValueError("achieved power does not match the frozen calculation")
        if self.power_sufficient != (self.achieved_power >= self.target_power):
            raise ValueError("power_sufficient does not match achieved power")
        for effect_text, observed in self.sensitivity_by_effect.items():
            expected_sensitivity = _normal_approximation_power(
                independent_unit_count=self.independent_unit_count,
                effect=float(effect_text),
                assumed_unit_sd=self.assumed_unit_sd,
                alpha=self.alpha,
            )
            if not math.isclose(observed, expected_sensitivity, abs_tol=1e-12):
                raise ValueError("sensitivity table does not match the calculation")
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("power sensitivity audit_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        track_id: str,
        analysis_unit: str,
        independent_unit_count: int,
        alpha: float,
        target_power: float,
        minimum_detectable_effect: float,
        assumed_unit_sd: float,
        sensitivity_effects: Sequence[float],
    ) -> PowerSensitivityAudit:
        """Calculate, normalize, and hash a prospective sensitivity artifact."""

        effects = sorted({*sensitivity_effects, minimum_detectable_effect})
        if len(effects) < 3 or any(effect <= 0 for effect in effects):
            raise ValueError("power sensitivity requires at least three positive effects")
        achieved = _normal_approximation_power(
            independent_unit_count=independent_unit_count,
            effect=minimum_detectable_effect,
            assumed_unit_sd=assumed_unit_sd,
            alpha=alpha,
        )
        payload: dict[str, Any] = {
            "schema_version": "power-sensitivity-audit-v1",
            "track_id": track_id,
            "analysis_unit": analysis_unit,
            "independent_unit_count": independent_unit_count,
            "alpha": alpha,
            "target_power": target_power,
            "minimum_detectable_effect": minimum_detectable_effect,
            "assumed_unit_sd": assumed_unit_sd,
            "calculation_method": (
                "two-sided normal approximation over independent paired unit effects"
            ),
            "achieved_power": achieved,
            "sensitivity_by_effect": {
                format(effect, ".12g"): _normal_approximation_power(
                    independent_unit_count=independent_unit_count,
                    effect=effect,
                    assumed_unit_sd=assumed_unit_sd,
                    alpha=alpha,
                )
                for effect in effects
            },
            "power_sufficient": achieved >= target_power,
            "prospective": True,
            "seed_repeats_are_independent_units": False,
        }
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the power artifact digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))

    def verify_integrity(self) -> None:
        """Reject in-memory power evidence mutation."""

        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("power sensitivity audit_hash mismatch")


def _normal_approximation_power(
    *,
    independent_unit_count: int,
    effect: float,
    assumed_unit_sd: float,
    alpha: float,
) -> float:
    if independent_unit_count < 1 or effect <= 0 or assumed_unit_sd <= 0:
        raise ValueError("power inputs must be positive")
    normal = NormalDist()
    critical = normal.inv_cdf(1 - alpha / 2)
    noncentrality = effect * math.sqrt(independent_unit_count) / assumed_unit_sd
    upper = 1 - normal.cdf(critical - noncentrality)
    lower = normal.cdf(-critical - noncentrality)
    return min(1.0, max(0.0, upper + lower))


class TrackFeasibilityAudit(KernelContract):
    """Non-scientific resource gates for one candidate research track."""

    schema_version: Literal["track-feasibility-audit-v1"] = (
        "track-feasibility-audit-v1"
    )
    track_id: StableId
    repository_probe_ids: list[StableId] = Field(min_length=1)
    dataset_probe_ids: list[StableId] = Field(min_length=1)
    license_probe_ids: list[StableId] = Field(min_length=1)
    code_license_id: NonEmptyText
    data_license_id: NonEmptyText
    code_license_verified: bool
    data_license_verified: bool
    data_access_verified: bool
    required_compute: NonEmptyText
    available_compute: NonEmptyText
    compute_feasible: bool
    estimated_baseline_cost_usd: float = Field(ge=0)
    estimated_baseline_walltime_minutes: int = Field(ge=1)
    audit_hash: Sha256

    @field_validator(
        "repository_probe_ids",
        "dataset_probe_ids",
        "license_probe_ids",
    )
    @classmethod
    def _normalize_probe_ids(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("feasibility probe IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_feasibility(self) -> TrackFeasibilityAudit:
        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track feasibility audit_hash mismatch")
        return self

    @property
    def license_clear(self) -> bool:
        """Return the non-compensating code-and-data license result."""

        return self.code_license_verified and self.data_license_verified

    @classmethod
    def create(cls, **values: Any) -> TrackFeasibilityAudit:
        """Normalize one feasibility audit and attach its digest."""

        payload = dict(values)
        payload["schema_version"] = "track-feasibility-audit-v1"
        for field in (
            "repository_probe_ids",
            "dataset_probe_ids",
            "license_probe_ids",
        ):
            payload[field] = sorted(payload[field])
        payload["estimated_baseline_cost_usd"] = float(
            payload["estimated_baseline_cost_usd"]
        )
        payload["audit_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the feasibility digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))

    def verify_integrity(self) -> None:
        """Reject in-memory feasibility mutation."""

        if self.audit_hash != self.calculated_hash():
            raise PortfolioIntegrityError("track feasibility audit_hash mismatch")


class TournamentTrackAssessment(KernelContract):
    """Conjunctive live overlay on a Task 263.2 opportunity assessment."""

    schema_version: Literal["tournament-track-assessment-v1"] = (
        "tournament-track-assessment-v1"
    )
    opportunity_assessment: OpportunityAssessment
    checks: dict[StableId, bool]
    blockers: list[StableId]
    admitted: bool
    weighted_score_used: Literal[False] = False
    llm_review_can_override: Literal[False] = False
    novelty_search_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    assessment_hash: Sha256

    @model_validator(mode="after")
    def _validate_assessment(self) -> TournamentTrackAssessment:
        self.opportunity_assessment.verify_integrity()
        if self.opportunity_assessment.stage is not OpportunityStage.TRACK_SELECTION:
            raise ValueError("tournament assessment must use track-selection stage")
        if list(self.checks) != sorted(self.checks):
            raise ValueError("tournament checks must be sorted")
        expected_blockers = sorted(
            check_id for check_id, passed in self.checks.items() if not passed
        )
        if self.blockers != expected_blockers:
            raise ValueError("tournament blockers do not match failed checks")
        if self.admitted != all(self.checks.values()):
            raise ValueError("tournament admission must be the conjunction of checks")
        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "tournament track assessment_hash mismatch"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        opportunity_assessment: OpportunityAssessment,
        checks: dict[str, bool],
    ) -> TournamentTrackAssessment:
        """Normalize live hard checks and attach their digest."""

        normalized = dict(sorted(checks.items()))
        payload: dict[str, Any] = {
            "schema_version": "tournament-track-assessment-v1",
            "opportunity_assessment": opportunity_assessment.model_dump(mode="json"),
            "checks": normalized,
            "blockers": sorted(
                check_id for check_id, passed in normalized.items() if not passed
            ),
            "admitted": all(normalized.values()),
            "weighted_score_used": False,
            "llm_review_can_override": False,
            "novelty_search_authorized": False,
            "external_submission_authorized": False,
        }
        payload["assessment_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the tournament-track assessment digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"assessment_hash"})
        )

    def verify_integrity(self) -> None:
        """Reject in-memory assessment mutation."""

        self.opportunity_assessment.verify_integrity()
        if self.assessment_hash != self.calculated_hash():
            raise PortfolioIntegrityError(
                "tournament track assessment_hash mismatch"
            )


class OpportunityTournamentEntry(KernelContract):
    """One fully evidenced candidate track and its fail-closed decision."""

    schema_version: Literal["opportunity-tournament-entry-v1"] = (
        "opportunity-tournament-entry-v1"
    )
    track_id: StableId
    opportunity: ResearchOpportunity
    source_probes: list[LiveResourceProbe] = Field(min_length=3)
    resource_probes: list[LiveResourceProbe] = Field(min_length=3)
    baseline_smoke: BaselineExecutionSmoke
    power_audit: PowerSensitivityAudit
    feasibility_audit: TrackFeasibilityAudit
    assessment: TournamentTrackAssessment
    entry_hash: Sha256

    @model_validator(mode="after")
    def _validate_entry(self) -> OpportunityTournamentEntry:
        self.opportunity.verify_integrity()
        self.baseline_smoke.verify_integrity()
        self.power_audit.verify_integrity()
        self.feasibility_audit.verify_integrity()
        self.assessment.verify_integrity()
        if self.track_id != self.baseline_smoke.track_id:
            raise ValueError("baseline smoke belongs to another track")
        if self.track_id != self.power_audit.track_id:
            raise ValueError("power audit belongs to another track")
        if self.track_id != self.feasibility_audit.track_id:
            raise ValueError("feasibility audit belongs to another track")
        if self.opportunity.opportunity_id != self.track_id:
            raise ValueError("opportunity ID must equal tournament track ID")
        if (
            self.assessment.opportunity_assessment.opportunity_hash
            != self.opportunity.opportunity_hash
        ):
            raise ValueError("assessment belongs to another opportunity")
        if self.baseline_smoke.baseline_id != self.opportunity.baseline_plan.baseline_id:
            raise ValueError("baseline smoke does not bind the baseline plan")
        if (
            self.baseline_smoke.command_hash
            != self.opportunity.baseline_plan.exact_command_hash
        ):
            raise ValueError("baseline command does not bind the baseline plan")
        if (
            self.baseline_smoke.environment_hash
            != self.opportunity.baseline_plan.environment_hash
        ):
            raise ValueError("baseline environment does not bind the baseline plan")
        if self.baseline_smoke.passed != self.opportunity.baseline_smoke_passed:
            raise ValueError("baseline smoke result differs from the opportunity")
        certificate = self.opportunity.certificate
        if self.power_audit.audit_hash != certificate.power_plan.analysis_artifact_hash:
            raise ValueError("power audit does not bind the certificate")
        if (
            self.power_audit.independent_unit_count
            != certificate.power_plan.confirmatory_independent_unit_count
        ):
            raise ValueError("power audit independent-unit count mismatch")
        if not math.isclose(
            self.power_audit.minimum_detectable_effect,
            certificate.power_plan.minimum_detectable_effect,
        ):
            raise ValueError("power audit effect does not bind the certificate")
        if self.feasibility_audit.data_access_verified != self.opportunity.data_available:
            raise ValueError("data feasibility differs from the opportunity")
        if self.feasibility_audit.license_clear != self.opportunity.license_clear:
            raise ValueError("license feasibility differs from the opportunity")
        if self.feasibility_audit.compute_feasible != self.opportunity.compute_feasible:
            raise ValueError("compute feasibility differs from the opportunity")

        _verify_sorted_unique_probes(self.source_probes, label="source")
        _verify_sorted_unique_probes(self.resource_probes, label="resource")
        source_by_id = {probe.resource_id: probe for probe in self.source_probes}
        if set(source_by_id) != {
            source.source_id for source in self.opportunity.sources
        }:
            raise ValueError("live source probes do not cover opportunity sources")
        for source in self.opportunity.sources:
            probe = source_by_id[source.source_id]
            probe.verify_integrity()
            if probe.kind is not ResourceKind.LITERATURE:
                raise ValueError("source probes must be literature probes")
            if probe.requested_url != source.source_url:
                raise ValueError("source probe URL differs from the source record")
            if probe.sample_sha256 != source.source_fingerprint:
                raise ValueError("source fingerprint differs from the live probe")

        resource_by_id = {probe.resource_id: probe for probe in self.resource_probes}
        required_probe_ids = {
            *self.feasibility_audit.repository_probe_ids,
            *self.feasibility_audit.dataset_probe_ids,
            *self.feasibility_audit.license_probe_ids,
        }
        if not required_probe_ids.issubset(resource_by_id):
            raise ValueError("feasibility audit references missing resource probes")
        for probe in self.resource_probes:
            probe.verify_integrity()
            if probe.kind is ResourceKind.LITERATURE:
                raise ValueError("resource probes cannot duplicate literature probes")
        if self.entry_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity tournament entry_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        track_id: str,
        opportunity: ResearchOpportunity,
        source_probes: Sequence[LiveResourceProbe],
        resource_probes: Sequence[LiveResourceProbe],
        baseline_smoke: BaselineExecutionSmoke,
        power_audit: PowerSensitivityAudit,
        feasibility_audit: TrackFeasibilityAudit,
    ) -> OpportunityTournamentEntry:
        """Assess, normalize, and hash one live candidate track."""

        normalized_sources = sorted(source_probes, key=lambda probe: probe.resource_id)
        normalized_resources = sorted(
            resource_probes, key=lambda probe: probe.resource_id
        )
        all_resources = {probe.resource_id: probe for probe in normalized_resources}
        base = assess_research_opportunity(
            opportunity,
            stage=OpportunityStage.TRACK_SELECTION,
        )
        source_reachable = all(probe.reachable for probe in normalized_sources)
        repository_reachable = all(
            all_resources.get(probe_id) is not None
            and all_resources[probe_id].reachable
            for probe_id in feasibility_audit.repository_probe_ids
        )
        dataset_reachable = all(
            all_resources.get(probe_id) is not None
            and all_resources[probe_id].reachable
            for probe_id in feasibility_audit.dataset_probe_ids
        )
        license_reachable = all(
            all_resources.get(probe_id) is not None
            and all_resources[probe_id].reachable
            for probe_id in feasibility_audit.license_probe_ids
        )
        time_cut_respected = all(
            source.year <= opportunity.certificate.literature_cutoff.year
            for source in opportunity.sources
        )
        assessment = TournamentTrackAssessment.create(
            opportunity_assessment=base,
            checks={
                **{
                    f"opportunity.{check_id}": passed
                    for check_id, passed in base.checks.items()
                },
                "baseline_smoke_evidence_bound": (
                    baseline_smoke.passed == opportunity.baseline_smoke_passed
                    and baseline_smoke.command_hash
                    == opportunity.baseline_plan.exact_command_hash
                ),
                "data_probe_reachable": dataset_reachable,
                "license_evidence_reachable": license_reachable,
                "live_sources_reachable": source_reachable,
                "power_target_met": power_audit.power_sufficient,
                "repository_reachable": repository_reachable,
                "time_cut_respected": time_cut_respected,
            },
        )
        payload: dict[str, Any] = {
            "schema_version": "opportunity-tournament-entry-v1",
            "track_id": track_id,
            "opportunity": opportunity.model_dump(mode="json"),
            "source_probes": [
                probe.model_dump(mode="json") for probe in normalized_sources
            ],
            "resource_probes": [
                probe.model_dump(mode="json") for probe in normalized_resources
            ],
            "baseline_smoke": baseline_smoke.model_dump(mode="json"),
            "power_audit": power_audit.model_dump(mode="json"),
            "feasibility_audit": feasibility_audit.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
        }
        payload["entry_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the complete entry digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"entry_hash"}))

    def verify_integrity(self) -> None:
        """Reject nested or top-level tournament evidence mutation."""

        self.opportunity.verify_integrity()
        self.baseline_smoke.verify_integrity()
        self.power_audit.verify_integrity()
        self.feasibility_audit.verify_integrity()
        self.assessment.verify_integrity()
        for probe in [*self.source_probes, *self.resource_probes]:
            probe.verify_integrity()
        if self.entry_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity tournament entry_hash mismatch")


def _verify_sorted_unique_probes(
    probes: Sequence[LiveResourceProbe],
    *,
    label: str,
) -> None:
    probe_ids = [probe.resource_id for probe in probes]
    if probe_ids != sorted(probe_ids) or len(probe_ids) != len(set(probe_ids)):
        raise ValueError(f"{label} probes must be unique and resource-id sorted")


class OpportunityTournamentReport(KernelContract):
    """A no-score tournament that may select one or zero tracks."""

    schema_version: Literal["opportunity-tournament-report-v1"] = (
        "opportunity-tournament-report-v1"
    )
    tournament_id: StableId
    created_at: datetime
    entries: list[OpportunityTournamentEntry] = Field(min_length=3)
    eligible_track_ids: list[StableId]
    ranked_track_ids: list[StableId]
    selected_track_id: StableId | None
    ranking_rule: TournamentRankingRule = TOURNAMENT_RANKING_RULE
    weighted_score_used: Literal[False] = False
    hardcoded_winner_used: Literal[False] = False
    all_tracks_may_fail: Literal[True] = True
    novelty_search_started: Literal[False] = False
    confirmatory_evidence_revealed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_report(self) -> OpportunityTournamentReport:
        track_ids = [entry.track_id for entry in self.entries]
        if track_ids != sorted(track_ids) or len(track_ids) != len(set(track_ids)):
            raise ValueError("tournament entries must be unique and track-id sorted")
        for entry in self.entries:
            entry.verify_integrity()
        expected_eligible = sorted(
            entry.track_id for entry in self.entries if entry.assessment.admitted
        )
        if self.eligible_track_ids != expected_eligible:
            raise ValueError("eligible tracks do not match conjunctive assessments")
        expected_ranked = _rank_admitted_tracks(self.entries)
        if self.ranked_track_ids != expected_ranked:
            raise ValueError("ranked tracks do not match the frozen ranking rule")
        expected_selected = expected_ranked[0] if expected_ranked else None
        if self.selected_track_id != expected_selected:
            raise ValueError("selected track does not match deterministic ranking")
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity tournament report_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        tournament_id: str,
        created_at: datetime,
        entries: Sequence[OpportunityTournamentEntry],
    ) -> OpportunityTournamentReport:
        """Normalize entries, rank only admissions, and attach a digest."""

        normalized = sorted(entries, key=lambda entry: entry.track_id)
        eligible = sorted(
            entry.track_id for entry in normalized if entry.assessment.admitted
        )
        ranked = _rank_admitted_tracks(normalized)
        payload: dict[str, Any] = {
            "schema_version": "opportunity-tournament-report-v1",
            "tournament_id": tournament_id,
            "created_at": created_at,
            "entries": [entry.model_dump(mode="json") for entry in normalized],
            "eligible_track_ids": eligible,
            "ranked_track_ids": ranked,
            "selected_track_id": ranked[0] if ranked else None,
            "ranking_rule": TOURNAMENT_RANKING_RULE,
            "weighted_score_used": False,
            "hardcoded_winner_used": False,
            "all_tracks_may_fail": True,
            "novelty_search_started": False,
            "confirmatory_evidence_revealed": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        }
        payload["report_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the report digest."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    def verify_integrity(self) -> None:
        """Reject nested or top-level report mutation."""

        for entry in self.entries:
            entry.verify_integrity()
        if self.report_hash != self.calculated_hash():
            raise PortfolioIntegrityError("opportunity tournament report_hash mismatch")


def _rank_admitted_tracks(
    entries: Sequence[OpportunityTournamentEntry],
) -> list[str]:
    admitted = [entry for entry in entries if entry.assessment.admitted]

    def ranking_key(entry: OpportunityTournamentEntry) -> tuple[int, float, int, str]:
        peer_reviewed = sum(
            source.maturity is SourceMaturity.PEER_REVIEWED
            for source in entry.opportunity.sources
        )
        confirmatory_units = len(
            entry.opportunity.certificate.data_split.confirmatory_unit_ids
        )
        return (
            -peer_reviewed,
            entry.feasibility_audit.estimated_baseline_cost_usd,
            -confirmatory_units,
            entry.track_id,
        )

    return [entry.track_id for entry in sorted(admitted, key=ranking_key)]


class TournamentArtifactManifest(KernelContract):
    """Digest inventory for the JSON and reader-facing Markdown artifacts."""

    schema_version: Literal["tournament-artifact-manifest-v1"] = (
        "tournament-artifact-manifest-v1"
    )
    tournament_id: StableId
    report_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> TournamentArtifactManifest:
        if list(self.files) != sorted(self.files):
            raise ValueError("tournament artifact files must be sorted")
        if self.manifest_hash != self.calculated_hash():
            raise PortfolioIntegrityError("tournament artifact manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> TournamentArtifactManifest:
        """Normalize the artifact inventory and attach its digest."""

        payload = dict(values)
        payload.update(
            {
                "schema_version": "tournament-artifact-manifest-v1",
                "external_submission_authorized": False,
            }
        )
        payload["files"] = dict(sorted(payload["files"].items()))
        payload["manifest_hash"] = canonical_sha256(_jsonable(payload))
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the manifest digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


def render_opportunity_tournament_markdown(
    report: OpportunityTournamentReport,
) -> str:
    """Render a compact reader view without turning selection into a claim."""

    report.verify_integrity()
    rows = [
        "# Research Opportunity Tournament",
        "",
        f"- Tournament: `{report.tournament_id}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Selected for baseline reproduction: "
        f"`{report.selected_track_id or 'none'}`",
        "- Novelty search started: `false`",
        "- Confirmatory evidence revealed: `false`",
        "- External submission authorized: `false`",
        "",
        "| Track | Track gate | Baseline smoke | Data | License | Compute | "
        "Power | Blockers |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    detail_rows: list[str] = []
    for entry in report.entries:
        opportunity = entry.opportunity
        feasibility = entry.feasibility_audit
        blockers = ", ".join(entry.assessment.blockers) or "none"
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{entry.track_id}`",
                    str(entry.assessment.admitted).lower(),
                    str(entry.baseline_smoke.passed).lower(),
                    str(opportunity.data_available).lower(),
                    str(opportunity.license_clear).lower(),
                    str(opportunity.compute_feasible).lower(),
                    str(entry.power_audit.power_sufficient).lower(),
                    blockers,
                ]
            )
            + " |"
        )
        if detail_rows:
            detail_rows.append("")
        detail_rows.extend(
            [
                f"## {entry.track_id}",
                "",
                f"- Main claim: {opportunity.certificate.main_claim}",
                f"- Publication endpoint: "
                f"`{opportunity.certificate.publication_endpoint.value}`",
                f"- Baseline: `{opportunity.baseline_plan.baseline_id}`",
                f"- Independent confirmatory units: "
                f"`{len(opportunity.certificate.data_split.confirmatory_unit_ids)}`",
                f"- Achieved prospective power: "
                f"`{entry.power_audit.achieved_power:.6f}`",
                f"- Baseline cost envelope: "
                f"`${feasibility.estimated_baseline_cost_usd:.2f}`, "
                f"`{feasibility.estimated_baseline_walltime_minutes}` minutes",
                f"- Required compute: {feasibility.required_compute}",
                f"- Available compute: {feasibility.available_compute}",
                f"- Decision: "
                f"`{'admit to baseline reproduction' if entry.assessment.admitted else 'blocked'}`",
                f"- Blockers: `{blockers}`",
                "",
                "### Time-cut nearest-work matrix",
                "",
                "| Source | Shared scope | Claimed delta | Overlap risk | Decisive comparison |",
                "|---|---|---|---|---|",
            ]
        )
        sources = {source.source_id: source for source in opportunity.sources}
        for delta in opportunity.nearest_work:
            source = sources[delta.source_id]
            detail_rows.append(
                "| "
                + " | ".join(
                    [
                        f"[{source.title}]({source.source_url}) ({source.year})",
                        delta.shared_scope,
                        delta.claimed_delta,
                        delta.overlap_risk,
                        delta.decisive_comparison,
                    ]
                )
                + " |"
            )
        detail_rows.extend(
            [
                "",
                "This is a track-selection result only. A passing track still requires "
                "independent clean-room baseline reproduction before novelty search.",
                "",
            ]
        )
    rows.extend(["", *detail_rows])
    return "\n".join(rows).rstrip() + "\n"


def write_opportunity_tournament(
    output_dir: Path,
    report: OpportunityTournamentReport,
) -> TournamentArtifactManifest:
    """Write verified JSON, Markdown, and their content-addressed inventory."""

    report.verify_integrity()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "opportunity-tournament.json"
    markdown_path = output_dir / "opportunity-tournament.md"
    _write_text_atomic(json_path, report.model_dump_json(indent=2) + "\n")
    _write_text_atomic(
        markdown_path,
        render_opportunity_tournament_markdown(report),
    )
    manifest = TournamentArtifactManifest.create(
        tournament_id=report.tournament_id,
        report_hash=report.report_hash,
        files={
            json_path.name: _file_sha256(json_path),
            markdown_path.name: _file_sha256(markdown_path),
        },
    )
    _write_text_atomic(
        output_dir / "artifact-manifest.json",
        manifest.model_dump_json(indent=2) + "\n",
    )
    return manifest


def load_opportunity_tournament(path: Path) -> OpportunityTournamentReport:
    """Load and recursively verify a persisted tournament report."""

    report = OpportunityTournamentReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    report.verify_integrity()
    return report


TOURNAMENT_CONTRACT_MODELS = (
    BaselineExecutionSmoke,
    LiveResourceProbe,
    OpportunityTournamentEntry,
    OpportunityTournamentReport,
    PowerSensitivityAudit,
    TournamentArtifactManifest,
    TournamentTrackAssessment,
    TrackFeasibilityAudit,
)


def opportunity_tournament_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic schemas for every public tournament artifact."""

    return {
        model.__name__: model.model_json_schema()
        for model in TOURNAMENT_CONTRACT_MODELS
    }


def environment_fingerprint(
    *,
    lockfile_hash: str,
    python_version: str,
    platform: str,
) -> str:
    """Create a portable environment identifier without recording private paths."""

    return canonical_sha256(
        {
            "lockfile_hash": lockfile_hash,
            "platform": platform,
            "python_version": python_version,
        }
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
