"""Pydantic schemas for the AutoResearch lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _record_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ValidationStatus(str, Enum):
    """Validation state shared by results, evidence, papers, and strategies."""

    PENDING = "pending"
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class CandidateStatus(str, Enum):
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    ACTIVE = "active"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class TaskStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class BaseRecord(BaseModel):
    """Common provenance fields for persisted lifecycle records."""

    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(BaseRecord):
    """Structured metadata for a retrieved or imported research document."""

    id: str = Field(default_factory=lambda: _record_id("doc"))
    title: str
    source_uri: str
    source_type: str = "paper"
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    publication_date: datetime | None = None
    venue: str | None = None
    doi: str | None = None
    tags: list[str] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=_utc_now)
    validation_status: ValidationStatus = ValidationStatus.PENDING


class KnowledgeNode(BaseRecord):
    """Obsidian vault node that can link research memory across projects."""

    id: str = Field(default_factory=lambda: _record_id("node"))
    title: str
    node_type: str
    vault_path: str
    zone: str
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    validation_status: ValidationStatus = ValidationStatus.PENDING


class ResearchCandidate(BaseRecord):
    """Research direction candidate generated from literature and knowledge gaps."""

    id: str = Field(default_factory=lambda: _record_id("candidate"))
    title: str
    description: str
    research_gap: str
    novelty_score: float = Field(ge=0.0, le=1.0)
    feasibility_score: float = Field(ge=0.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(min_length=1)
    related_document_ids: list[str] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.DRAFT
    validation_status: ValidationStatus = ValidationStatus.PENDING


class Hypothesis(BaseRecord):
    """A testable hypothesis derived from an approved research candidate."""

    id: str = Field(default_factory=lambda: _record_id("hypothesis"))
    candidate_id: str
    statement: str = Field(min_length=1)
    prediction: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    dataset_ref: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    status: TaskStatus = TaskStatus.DRAFT
    validation_status: ValidationStatus = ValidationStatus.PENDING


class ExperimentTask(BaseRecord):
    """Executable experiment task produced from a hypothesis."""

    id: str = Field(default_factory=lambda: _record_id("task"))
    project_id: str
    hypothesis_id: str
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    config_path: str = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    resource_budget: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=3600, ge=1)
    expected_outputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=0)
    status: TaskStatus = TaskStatus.DRAFT
    validation_status: ValidationStatus = ValidationStatus.PENDING


class CostRecord(BaseRecord):
    """Resource and approval cost summary for one execution run."""

    id: str = Field(default_factory=lambda: _record_id("cost"))
    model_name: str = Field(min_length=1)
    token_input: int = Field(default=0, ge=0)
    token_output: int = Field(default=0, ge=0)
    cpu_time_seconds: float = Field(default=0.0, ge=0.0)
    gpu_hours: float = Field(default=0.0, ge=0.0)
    storage_artifact_bytes: int = Field(default=0, ge=0)
    network_cost_usd_placeholder: float = Field(default=0.0, ge=0.0)
    human_approval_count: int = Field(default=0, ge=0)


class ExecutionRun(BaseRecord):
    """Concrete execution attempt for an experiment task."""

    id: str = Field(default_factory=lambda: _record_id("run"))
    project_id: str
    task_id: str
    status: ExecutionStatus = ExecutionStatus.QUEUED
    start_time: datetime | None = None
    end_time: datetime | None = None
    commit_sha: str | None = None
    config_hash: str | None = None
    data_hash: str | None = None
    metrics_path: str | None = None
    artifact_uri: str | None = None
    cost_record: CostRecord | None = None
    cost_json: dict[str, Any] = Field(default_factory=dict)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    limit_violations: list[str] = Field(default_factory=list)
    error_type: str | None = None
    validator_status: ValidationStatus = ValidationStatus.PENDING


class ResultBundle(BaseRecord):
    """Collected outputs for a completed or failed execution run."""

    id: str = Field(default_factory=lambda: _record_id("result"))
    run_id: str
    metrics: dict[str, float] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    summary: str | None = None
    validation_status: ValidationStatus = ValidationStatus.PENDING


class EvidenceEdge(BaseRecord):
    """Trace from a claim to an artifact-backed piece of evidence."""

    id: str = Field(default_factory=lambda: _record_id("evidence"))
    claim_id: str
    evidence_ref: str
    source_artifact: str
    source_run_id: str | None = None
    metric_name: str | None = None
    supports_claim: bool = True
    validation_status: ValidationStatus = ValidationStatus.PENDING


class PaperDraft(BaseRecord):
    """Versioned paper or report draft derived from validated evidence."""

    id: str = Field(default_factory=lambda: _record_id("paper"))
    project_id: str
    title: str
    draft_path: str
    evidence_map_path: str
    version: int = Field(default=1, ge=1)
    status: TaskStatus = TaskStatus.DRAFT
    validation_status: ValidationStatus = ValidationStatus.PENDING


class StrategyCard(BaseRecord):
    """Versioned strategy candidate for controlled self-evolution."""

    id: str = Field(default_factory=lambda: _record_id("strategy"))
    strategy_type: str
    version: int = Field(default=1, ge=1)
    content: str
    parent_strategy_id: str | None = None
    evaluation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    golden_test_status: ValidationStatus = ValidationStatus.PENDING
    shadow_status: ValidationStatus = ValidationStatus.PENDING
    release_status: str = "draft"
    rollback_target: str | None = None
    validation_status: ValidationStatus = ValidationStatus.PENDING
