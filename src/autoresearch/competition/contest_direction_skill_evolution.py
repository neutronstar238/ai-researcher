"""Evidence-bound Skill evolution for one completed contest direction loop.

The service deliberately evolves methodology rather than scientific claims.  A
configured model may extract a concise candidate from a development partition
of real literature and exploratory-pilot evidence, but it never supplies IDs,
hashes, file paths, promotion state, or rollback state.  A second call sees only
the candidate and a previously hidden evidence partition.  Passing that check
makes the candidate *eligible* for an explicit activation; it never mutates the
active Skill catalogue by itself.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator

from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    ContestDirectionLiteratureRecord,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentArtifact,
    PrimeIntervalResult,
    load_contest_prime_preexperiment,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

CompletionCallable = Callable[..., LLMJsonCompletionResult]

_SHA256 = r"^[0-9a-f]{64}$"
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "analysis",
        "for",
        "in",
        "of",
        "on",
        "the",
        "to",
        "with",
    }
)
_ARTIFACT_NAME = "evidence-to-skill-evolution.json"
_REPORT_NAME = "evidence-to-skill-evolution.md"


class ContestDirectionSkillEvolutionError(RuntimeError):
    """Raised when evidence, isolation, validation, or replay is invalid."""


class SkillEvolutionFileBinding(StrictFrozenModel):
    """Exact local file binding used by the evolution receipt."""

    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    bytes: int = Field(ge=0)
    role: str = Field(min_length=1)

    @field_validator("relative_path")
    @classmethod
    def _safe_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or ":" in normalized:
            raise ValueError("evolution binding path must remain relative")
        return path.as_posix()


class SkillEvolutionPaperEvidence(StrictFrozenModel):
    """Ranked literature item and its frozen development/held-out assignment."""

    evidence_id: str = Field(pattern=r"^paper:direction-paper-[0-9a-f]{16}$")
    record_id: str = Field(pattern=r"^direction-paper-[0-9a-f]{16}$")
    record_hash: str = Field(pattern=_SHA256)
    title: str = Field(min_length=1)
    doi: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    citation_count_source: str | None = None
    relevance_score: float = Field(ge=0.0)
    impact_proxy_score: float = Field(ge=0.0)
    partition: Literal["development", "held_out"]


class SkillEvolutionPilotEvidence(StrictFrozenModel):
    """One verified pilot interval and its raw/null byte bindings."""

    evidence_id: str = Field(pattern=r"^pilot:interval-[0-9]{2}$")
    interval_index: int = Field(ge=1)
    raw_relative_path: str
    raw_sha256: str = Field(pattern=_SHA256)
    null_draws_relative_path: str
    null_draws_sha256: str = Field(pattern=_SHA256)
    partition: Literal["development", "held_out"]


class EvidenceBoundSkillLesson(StrictFrozenModel):
    """One reusable methodological lesson with development-only evidence IDs."""

    lesson_cn: str = Field(min_length=1, max_length=2_000)
    development_evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=16)

    @field_validator("development_evidence_ids")
    @classmethod
    def _unique_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("lesson evidence IDs must be unique and non-empty")
        return normalized


class EvidenceToSkillDraft(StrictFrozenModel):
    """Model-authored methodology; all identity and lifecycle fields stay program-owned."""

    title_cn: str = Field(min_length=1, max_length=160)
    description_cn: str = Field(min_length=1, max_length=1_024)
    trigger_conditions_cn: tuple[str, ...] = Field(min_length=1, max_length=12)
    workflow_steps_cn: tuple[str, ...] = Field(min_length=2, max_length=16)
    evidence_bound_lessons: tuple[EvidenceBoundSkillLesson, ...] = Field(
        min_length=1,
        max_length=12,
    )
    stop_or_pivot_rules_cn: tuple[str, ...] = Field(min_length=1, max_length=12)
    validation_checks_cn: tuple[str, ...] = Field(min_length=1, max_length=12)
    limitations_cn: tuple[str, ...] = Field(min_length=1, max_length=12)


class HeldOutSkillCaseAssessment(StrictFrozenModel):
    """Independent assessment on one case hidden from candidate generation."""

    case_id: str = Field(min_length=1)
    methodology_transfers: bool
    evidence_boundary_preserved: bool
    no_unsupported_scientific_claim: bool
    assessment_cn: str = Field(min_length=1, max_length=2_000)


class HeldOutSkillValidationDraft(StrictFrozenModel):
    """Second-model decision over the frozen held-out cases."""

    case_assessments: tuple[HeldOutSkillCaseAssessment, ...] = Field(min_length=1)
    overall_transfer_supported: bool
    limitations_cn: tuple[str, ...] = Field(default=(), max_length=16)


class StoredSkillEvolutionCompletion(StrictFrozenModel):
    """Write-once response escrow, allowing a partial run to resume for free."""

    schema_version: Literal["evidence-skill-completion-v1"] = "evidence-skill-completion-v1"
    stage: Literal["candidate_generation", "heldout_validation"]
    input_sha256: str = Field(pattern=_SHA256)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    response_text: str
    response_sha256: str = Field(pattern=_SHA256)
    parsed_json: dict[str, Any]
    reasoning_text: str | None = None
    reasoning_sha256: str = Field(pattern=_SHA256)
    usage: dict[str, Any] = Field(default_factory=dict)
    completion_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _verify_hashes(self) -> StoredSkillEvolutionCompletion:
        if self.response_sha256 != _text_sha256(self.response_text):
            raise ValueError("stored evolution response hash mismatch")
        if self.reasoning_sha256 != _text_sha256(self.reasoning_text or ""):
            raise ValueError("stored evolution reasoning hash mismatch")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"completion_hash"}))
        if self.completion_hash != expected:
            raise ValueError("stored evolution completion hash mismatch")
        return self


class EvidenceToSkillEvolutionArtifact(StrictFrozenModel):
    """Replayable outcome of evidence extraction and isolated validation."""

    schema_version: Literal["contest-evidence-to-skill-evolution-v1"] = (
        "contest-evidence-to-skill-evolution-v1"
    )
    direction: str = Field(min_length=1)
    delivery_report_binding: SkillEvolutionFileBinding
    literature_binding: SkillEvolutionFileBinding
    literature_artifact_hash: str = Field(pattern=_SHA256)
    pilot_binding: SkillEvolutionFileBinding
    pilot_artifact_hash: str = Field(pattern=_SHA256)
    selected_skill_manifest_binding: SkillEvolutionFileBinding
    parent_skill_id: str = Field(min_length=1, max_length=64)
    parent_skill_sha256: str = Field(pattern=_SHA256)
    candidate_skill_id: str = Field(min_length=1, max_length=64)
    candidate_status: Literal["heldout_passed_shadow", "heldout_failed_shadow"]
    promotion_eligible: bool
    active_skill_written: Literal[False] = False
    production_enabled: Literal[False] = False
    paper_evidence: tuple[SkillEvolutionPaperEvidence, ...] = Field(min_length=2)
    pilot_evidence: tuple[SkillEvolutionPilotEvidence, ...] = Field(min_length=2)
    candidate_draft: EvidenceToSkillDraft
    heldout_validation: HeldOutSkillValidationDraft
    development_validation_passed: bool
    heldout_validation_passed: bool
    heldout_case_ids: tuple[str, ...] = Field(min_length=1)
    generation_completion_hash: str = Field(pattern=_SHA256)
    heldout_completion_hash: str = Field(pattern=_SHA256)
    model_calls_at_creation: int = Field(ge=0, le=2)
    impact_proxy: Literal[
        "query_tfidf_relevance_then_citation_count_not_journal_impact_factor"
    ] = "query_tfidf_relevance_then_citation_count_not_journal_impact_factor"
    candidate_files: tuple[SkillEvolutionFileBinding, ...] = Field(min_length=3)
    process_files: tuple[SkillEvolutionFileBinding, ...] = Field(min_length=4)
    rollback_target_skill_id: str = Field(min_length=1, max_length=64)
    rollback_target_sha256: str = Field(pattern=_SHA256)
    created_at: datetime
    artifact_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _verify_contract(self) -> EvidenceToSkillEvolutionArtifact:
        if not _SKILL_NAME.fullmatch(self.candidate_skill_id):
            raise ValueError("candidate Skill ID is not canonical hyphen-case")
        if self.rollback_target_skill_id != self.parent_skill_id:
            raise ValueError("candidate rollback target differs from parent Skill")
        if self.rollback_target_sha256 != self.parent_skill_sha256:
            raise ValueError("candidate rollback target hash differs from parent Skill")
        expected_pass = (
            self.development_validation_passed and self.heldout_validation_passed
        )
        if self.promotion_eligible != expected_pass:
            raise ValueError("Skill promotion eligibility contradicts validation")
        expected_status = (
            "heldout_passed_shadow" if expected_pass else "heldout_failed_shadow"
        )
        if self.candidate_status != expected_status:
            raise ValueError("candidate status contradicts validation")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ValueError(
                "evidence-to-Skill artifact hash mismatch: "
                f"expected={expected_hash} actual={self.artifact_hash}"
            )
        return self


class EvidenceToSkillEvolutionRun(StrictFrozenModel):
    """API-friendly return value."""

    artifact: EvidenceToSkillEvolutionArtifact
    artifact_path: Path
    report_path: Path
    candidate_skill_dir: Path
    resumed_existing: bool


class SkillActivationReceipt(StrictFrozenModel):
    """Explicit production activation retaining an exact rollback target."""

    schema_version: Literal["evolved-skill-activation-v1"] = "evolved-skill-activation-v1"
    candidate_skill_id: str
    candidate_artifact_hash: str = Field(pattern=_SHA256)
    candidate_skill_sha256: str = Field(pattern=_SHA256)
    active_skill_relative_path: str
    parent_skill_id: str
    parent_skill_sha256: str = Field(pattern=_SHA256)
    rollback_mode: Literal["remove_candidate_keep_unchanged_parent"] = (
        "remove_candidate_keep_unchanged_parent"
    )
    activated_by: str = Field(min_length=1)
    activation_note: str = Field(min_length=1)
    production_enabled: Literal[True] = True
    activated_at: datetime
    receipt_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _verify_receipt(self) -> SkillActivationReceipt:
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ValueError("Skill activation receipt hash mismatch")
        return self


class SkillRollbackReceipt(StrictFrozenModel):
    """Recoverable removal of an activated candidate while retaining its bytes."""

    schema_version: Literal["evolved-skill-rollback-v1"] = "evolved-skill-rollback-v1"
    activation_receipt_hash: str = Field(pattern=_SHA256)
    candidate_skill_id: str
    archived_skill_relative_path: str
    archived_skill_sha256: str = Field(pattern=_SHA256)
    restored_parent_skill_id: str
    restored_parent_sha256: str = Field(pattern=_SHA256)
    reason: str = Field(min_length=1)
    production_enabled: Literal[False] = False
    rolled_back_at: datetime
    receipt_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _verify_receipt(self) -> SkillRollbackReceipt:
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ValueError("Skill rollback receipt hash mismatch")
        return self


def run_evidence_to_skill_evolution(
    *,
    delivery_dir: Path | str,
    output_dir: Path | str,
    skills_root: Path | str,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    completion: CompletionCallable = run_llm_json_completion,
    maximum_ranked_papers: int = 8,
) -> EvidenceToSkillEvolutionRun:
    """Extract, independently validate, and retain one shadow Skill candidate.

    Existing completed output is fully revalidated and returned without model
    calls.  Partial output replays write-once completion escrows where present.
    Passing validation never writes into ``skills_root``.
    """

    delivery = Path(delivery_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    skill_root = Path(skills_root).expanduser().resolve()
    artifact_path = output / _ARTIFACT_NAME
    report_path = output / _REPORT_NAME
    if artifact_path.is_file():
        artifact = _load_and_verify_existing(
            artifact_path=artifact_path,
            report_path=report_path,
            delivery=delivery,
            output=output,
            skills_root=skill_root,
        )
        return EvidenceToSkillEvolutionRun(
            artifact=artifact,
            artifact_path=artifact_path,
            report_path=report_path,
            candidate_skill_dir=output / "shadow" / "candidates" / artifact.candidate_skill_id,
            resumed_existing=True,
        )
    if maximum_ranked_papers < 2 or maximum_ranked_papers > 32:
        raise ContestDirectionSkillEvolutionError(
            "maximum_ranked_papers must be between 2 and 32"
        )
    evidence = _load_delivery_evidence(delivery, skill_root, maximum_ranked_papers)
    output.mkdir(parents=True, exist_ok=True)

    generation_messages = _generation_messages(evidence)
    generation_input = output / "process" / "generation-input.json"
    _write_same_or_fail(generation_input, _json_bytes({"messages": generation_messages}))
    generation = _complete_or_replay(
        stage="candidate_generation",
        messages=generation_messages,
        response_schema=EvidenceToSkillDraft.model_json_schema(),
        schema_name="evidence_to_skill_candidate",
        escrow_path=output / "process" / "generation-completion.json",
        completion=completion,
        config_path=config_path,
        env_path=env_path,
    )
    raw_draft = EvidenceToSkillDraft.model_validate(generation.parsed_json)
    draft = _canonicalize_development_evidence_ids(raw_draft, evidence)
    development_ids = {
        item.evidence_id
        for item in evidence.paper_evidence
        if item.partition == "development"
    } | {
        item.evidence_id
        for item in evidence.pilot_evidence
        if item.partition == "development"
    }
    used_ids = {
        evidence_id
        for lesson in draft.evidence_bound_lessons
        for evidence_id in lesson.development_evidence_ids
    }
    if not used_ids or not used_ids.issubset(development_ids):
        raise ContestDirectionSkillEvolutionError(
            "candidate lessons cite unknown or held-out evidence IDs"
        )
    if not any(item.startswith("paper:") for item in used_ids) or not any(
        item.startswith("pilot:") for item in used_ids
    ):
        raise ContestDirectionSkillEvolutionError(
            "candidate lessons must bind both retrieved-paper and real-pilot evidence"
        )
    seed_hash = canonical_model_hash(
        {
            "parent_skill_id": evidence.parent_skill_id,
            "parent_skill_sha256": evidence.parent_skill_sha256,
            "literature_artifact_hash": evidence.literature.artifact_hash,
            "pilot_artifact_hash": evidence.pilot.artifact_hash,
            "draft": draft.model_dump(mode="json"),
        }
    )
    candidate_id = _candidate_skill_id(evidence.parent_skill_id, seed_hash)
    candidate_dir = output / "shadow" / "candidates" / candidate_id
    candidate_skill = _render_candidate_skill(
        candidate_id=candidate_id,
        parent_skill_id=evidence.parent_skill_id,
        draft=draft,
    )
    _write_same_or_fail(candidate_dir / "SKILL.md", candidate_skill.encode("utf-8"))
    _write_same_or_fail(
        candidate_dir / "agents" / "openai.yaml",
        _render_openai_yaml(candidate_id=candidate_id, title=draft.title_cn).encode("utf-8"),
    )
    evidence_bindings_payload = _candidate_evidence_bindings(
        evidence=evidence,
        candidate_id=candidate_id,
        used_development_ids=used_ids,
    )
    _write_same_or_fail(
        candidate_dir / "references" / "evidence-bindings.json",
        _json_bytes(evidence_bindings_payload),
    )
    development_passed = _validate_candidate_directory(
        candidate_dir=candidate_dir,
        candidate_id=candidate_id,
        heldout_evidence=evidence.heldout_payload,
    )

    heldout_messages = _heldout_messages(
        candidate_id=candidate_id,
        candidate_skill=candidate_skill,
        heldout_payload=evidence.heldout_payload,
    )
    heldout_input = output / "process" / "heldout-input.json"
    _write_same_or_fail(heldout_input, _json_bytes({"messages": heldout_messages}))
    heldout = _complete_or_replay(
        stage="heldout_validation",
        messages=heldout_messages,
        response_schema=_heldout_schema(evidence.heldout_case_ids),
        schema_name="evidence_to_skill_heldout_validation",
        escrow_path=output / "process" / "heldout-completion.json",
        completion=completion,
        config_path=config_path,
        env_path=env_path,
    )
    validation = HeldOutSkillValidationDraft.model_validate(heldout.parsed_json)
    actual_case_ids = tuple(item.case_id for item in validation.case_assessments)
    if actual_case_ids != evidence.heldout_case_ids:
        raise ContestDirectionSkillEvolutionError(
            "held-out evaluator did not assess every frozen case exactly once and in order"
        )
    heldout_passed = validation.overall_transfer_supported and all(
        item.methodology_transfers
        and item.evidence_boundary_preserved
        and item.no_unsupported_scientific_claim
        for item in validation.case_assessments
    )
    promotion_eligible = development_passed and heldout_passed
    model_calls = int(not generation.replayed) + int(not heldout.replayed)
    candidate_files = _bind_candidate_files(output, candidate_dir)
    process_files = tuple(
        _file_binding(output, path, role=role)
        for path, role in (
            (generation_input, "candidate_generation_input"),
            (output / "process" / "generation-completion.json", "candidate_generation_completion"),
            (heldout_input, "heldout_validation_input"),
            (output / "process" / "heldout-completion.json", "heldout_validation_completion"),
        )
    )
    created_at = datetime.now(timezone.utc)
    artifact_payload: dict[str, Any] = {
        "schema_version": "contest-evidence-to-skill-evolution-v1",
        "direction": evidence.literature.direction,
        "delivery_report_binding": evidence.delivery_report_binding.model_dump(mode="json"),
        "literature_binding": evidence.literature_binding.model_dump(mode="json"),
        "literature_artifact_hash": evidence.literature.artifact_hash,
        "pilot_binding": evidence.pilot_binding.model_dump(mode="json"),
        "pilot_artifact_hash": evidence.pilot.artifact_hash,
        "selected_skill_manifest_binding": evidence.selected_manifest_binding.model_dump(
            mode="json"
        ),
        "parent_skill_id": evidence.parent_skill_id,
        "parent_skill_sha256": evidence.parent_skill_sha256,
        "candidate_skill_id": candidate_id,
        "candidate_status": (
            "heldout_passed_shadow" if promotion_eligible else "heldout_failed_shadow"
        ),
        "promotion_eligible": promotion_eligible,
        "active_skill_written": False,
        "production_enabled": False,
        "paper_evidence": [item.model_dump(mode="json") for item in evidence.paper_evidence],
        "pilot_evidence": [item.model_dump(mode="json") for item in evidence.pilot_evidence],
        "candidate_draft": draft.model_dump(mode="json"),
        "heldout_validation": validation.model_dump(mode="json"),
        "development_validation_passed": development_passed,
        "heldout_validation_passed": heldout_passed,
        "heldout_case_ids": list(evidence.heldout_case_ids),
        "generation_completion_hash": generation.completion.completion_hash,
        "heldout_completion_hash": heldout.completion.completion_hash,
        "model_calls_at_creation": model_calls,
        "impact_proxy": (
            "query_tfidf_relevance_then_citation_count_not_journal_impact_factor"
        ),
        "candidate_files": [item.model_dump(mode="json") for item in candidate_files],
        "process_files": [item.model_dump(mode="json") for item in process_files],
        "rollback_target_skill_id": evidence.parent_skill_id,
        "rollback_target_sha256": evidence.parent_skill_sha256,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    artifact_payload["artifact_hash"] = canonical_model_hash(artifact_payload)
    artifact = EvidenceToSkillEvolutionArtifact.model_validate(artifact_payload)
    _write_same_or_fail(
        artifact_path,
        _json_bytes(artifact.model_dump(mode="json")),
    )
    _write_same_or_fail(report_path, _render_report(artifact).encode("utf-8"))
    _load_and_verify_existing(
        artifact_path=artifact_path,
        report_path=report_path,
        delivery=delivery,
        output=output,
        skills_root=skill_root,
    )
    return EvidenceToSkillEvolutionRun(
        artifact=artifact,
        artifact_path=artifact_path,
        report_path=report_path,
        candidate_skill_dir=candidate_dir,
        resumed_existing=False,
    )


def activate_validated_evolved_skill(
    *,
    evolution_artifact_path: Path | str,
    skills_root: Path | str,
    activated_by: str,
    activation_note: str,
) -> SkillActivationReceipt:
    """Explicitly copy one held-out-passed candidate into the active catalogue."""

    artifact_path = Path(evolution_artifact_path).expanduser().resolve()
    output = artifact_path.parent
    artifact = EvidenceToSkillEvolutionArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    if not artifact.promotion_eligible:
        raise ContestDirectionSkillEvolutionError(
            "held-out validation did not pass; active promotion is forbidden"
        )
    candidate_dir = output / "shadow" / "candidates" / artifact.candidate_skill_id
    _verify_bindings(output, artifact.candidate_files)
    root = Path(skills_root).expanduser().resolve()
    parent_path = root / artifact.parent_skill_id / "SKILL.md"
    if _sha256_file(parent_path) != artifact.parent_skill_sha256:
        raise ContestDirectionSkillEvolutionError(
            "parent Skill changed after validation; promotion must be repeated"
        )
    active_dir = root / artifact.candidate_skill_id
    receipt_path = output / "promotion" / "activation.json"
    if receipt_path.is_file():
        receipt = SkillActivationReceipt.model_validate_json(receipt_path.read_text("utf-8"))
        _verify_active_receipt(receipt, active_dir, artifact)
        return receipt
    if active_dir.exists():
        raise ContestDirectionSkillEvolutionError(
            "active candidate path already exists without its activation receipt"
        )
    active_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(candidate_dir, active_dir)
    active_skill_hash = _sha256_file(active_dir / "SKILL.md")
    values: dict[str, Any] = {
        "schema_version": "evolved-skill-activation-v1",
        "candidate_skill_id": artifact.candidate_skill_id,
        "candidate_artifact_hash": artifact.artifact_hash,
        "candidate_skill_sha256": active_skill_hash,
        "active_skill_relative_path": (
            Path(artifact.candidate_skill_id) / "SKILL.md"
        ).as_posix(),
        "parent_skill_id": artifact.parent_skill_id,
        "parent_skill_sha256": artifact.parent_skill_sha256,
        "rollback_mode": "remove_candidate_keep_unchanged_parent",
        "activated_by": activated_by.strip(),
        "activation_note": activation_note.strip(),
        "production_enabled": True,
        "activated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    values["receipt_hash"] = canonical_model_hash(values)
    receipt = SkillActivationReceipt.model_validate(values)
    _write_same_or_fail(receipt_path, _json_bytes(receipt.model_dump(mode="json")))
    return receipt


def rollback_activated_evolved_skill(
    *,
    activation_receipt_path: Path | str,
    skills_root: Path | str,
    reason: str,
) -> SkillRollbackReceipt:
    """Recoverably remove an evolved Skill while leaving its parent untouched."""

    activation_path = Path(activation_receipt_path).expanduser().resolve()
    activation = SkillActivationReceipt.model_validate_json(
        activation_path.read_text(encoding="utf-8")
    )
    root = Path(skills_root).expanduser().resolve()
    active_dir = root / activation.candidate_skill_id
    parent_path = root / activation.parent_skill_id / "SKILL.md"
    if _sha256_file(parent_path) != activation.parent_skill_sha256:
        raise ContestDirectionSkillEvolutionError(
            "rollback target parent Skill no longer matches the activation receipt"
        )
    rollback_path = activation_path.parent / "rollback.json"
    archive_dir = (
        activation_path.parent
        / "rollback-archive"
        / f"{activation.candidate_skill_id}-{activation.candidate_skill_sha256[:12]}"
    )
    if rollback_path.is_file():
        receipt = SkillRollbackReceipt.model_validate_json(rollback_path.read_text("utf-8"))
        if not archive_dir.is_dir() or _sha256_file(archive_dir / "SKILL.md") != (
            receipt.archived_skill_sha256
        ):
            raise ContestDirectionSkillEvolutionError("rolled-back Skill archive changed")
        return receipt
    if not active_dir.is_dir() or _sha256_file(active_dir / "SKILL.md") != (
        activation.candidate_skill_sha256
    ):
        raise ContestDirectionSkillEvolutionError(
            "active evolved Skill is absent or changed; safe rollback is impossible"
        )
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    if archive_dir.exists():
        raise ContestDirectionSkillEvolutionError("rollback archive already exists")
    active_dir.replace(archive_dir)
    values: dict[str, Any] = {
        "schema_version": "evolved-skill-rollback-v1",
        "activation_receipt_hash": activation.receipt_hash,
        "candidate_skill_id": activation.candidate_skill_id,
        "archived_skill_relative_path": archive_dir.relative_to(
            activation_path.parent
        ).as_posix(),
        "archived_skill_sha256": activation.candidate_skill_sha256,
        "restored_parent_skill_id": activation.parent_skill_id,
        "restored_parent_sha256": activation.parent_skill_sha256,
        "reason": reason.strip(),
        "production_enabled": False,
        "rolled_back_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    values["receipt_hash"] = canonical_model_hash(values)
    receipt = SkillRollbackReceipt.model_validate(values)
    _write_same_or_fail(rollback_path, _json_bytes(receipt.model_dump(mode="json")))
    return receipt


class _ReplayCompletion:
    def __init__(self, completion: StoredSkillEvolutionCompletion, *, replayed: bool) -> None:
        self.completion = completion
        self.replayed = replayed

    @property
    def parsed_json(self) -> dict[str, Any]:
        return self.completion.parsed_json


class _LoadedDeliveryEvidence:
    def __init__(
        self,
        *,
        literature: ContestDirectionLiteratureArtifact,
        pilot: ContestPrimePreexperimentArtifact,
        delivery_report_binding: SkillEvolutionFileBinding,
        literature_binding: SkillEvolutionFileBinding,
        pilot_binding: SkillEvolutionFileBinding,
        selected_manifest_binding: SkillEvolutionFileBinding,
        parent_skill_id: str,
        parent_skill_sha256: str,
        parent_skill_content: str,
        paper_evidence: tuple[SkillEvolutionPaperEvidence, ...],
        paper_records: Mapping[str, ContestDirectionLiteratureRecord],
        pilot_evidence: tuple[SkillEvolutionPilotEvidence, ...],
        pilot_results: Mapping[int, PrimeIntervalResult],
    ) -> None:
        self.literature = literature
        self.pilot = pilot
        self.delivery_report_binding = delivery_report_binding
        self.literature_binding = literature_binding
        self.pilot_binding = pilot_binding
        self.selected_manifest_binding = selected_manifest_binding
        self.parent_skill_id = parent_skill_id
        self.parent_skill_sha256 = parent_skill_sha256
        self.parent_skill_content = parent_skill_content
        self.paper_evidence = paper_evidence
        self.paper_records = paper_records
        self.pilot_evidence = pilot_evidence
        self.pilot_results = pilot_results

    @property
    def heldout_case_ids(self) -> tuple[str, ...]:
        paper_ids = tuple(
            item.evidence_id
            for item in self.paper_evidence
            if item.partition == "held_out"
        )
        pilot_ids = tuple(
            item.evidence_id
            for item in self.pilot_evidence
            if item.partition == "held_out"
        )
        return paper_ids + pilot_ids

    @property
    def heldout_payload(self) -> dict[str, Any]:
        return {
            "cases": [
                _paper_prompt_payload(item, self.paper_records[item.record_id])
                for item in self.paper_evidence
                if item.partition == "held_out"
            ]
            + [
                _pilot_prompt_payload(item, self.pilot_results[item.interval_index])
                for item in self.pilot_evidence
                if item.partition == "held_out"
            ],
            "case_ids": list(self.heldout_case_ids),
            "boundary_zh": (
                "这些案例在候选生成时不可见，仅用于检验方法迁移与证据边界；"
                "探索性预实验不等于正式实验或总体规律。"
            ),
        }


def _canonicalize_development_evidence_ids(
    draft: EvidenceToSkillDraft,
    evidence: _LoadedDeliveryEvidence,
) -> EvidenceToSkillDraft:
    """Map exact development paper record aliases to program-owned case IDs.

    Literature prompt rows carry both ``case_id`` and the underlying
    ``record_id`` for provenance.  A model may therefore copy the latter even
    though lessons are required to bind the former.  Only an exact alias for a
    paper in this run's development partition is accepted; held-out and unknown
    record IDs deliberately remain unchanged so the caller's subset gate fails
    closed.
    """

    development_paper_aliases = {
        item.record_id: item.evidence_id
        for item in evidence.paper_evidence
        if item.partition == "development"
    }
    normalized_lessons: list[dict[str, Any]] = []
    for lesson in draft.evidence_bound_lessons:
        normalized_ids = tuple(
            development_paper_aliases.get(evidence_id, evidence_id)
            for evidence_id in lesson.development_evidence_ids
        )
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ContestDirectionSkillEvolutionError(
                "candidate lesson evidence IDs collapse to duplicate canonical IDs"
            )
        payload = lesson.model_dump(mode="json")
        payload["development_evidence_ids"] = list(normalized_ids)
        normalized_lessons.append(payload)
    payload = draft.model_dump(mode="json")
    payload["evidence_bound_lessons"] = normalized_lessons
    return EvidenceToSkillDraft.model_validate(payload)


def _load_delivery_evidence(
    delivery: Path,
    skills_root: Path,
    maximum_ranked_papers: int,
) -> _LoadedDeliveryEvidence:
    if not delivery.is_dir():
        raise ContestDirectionSkillEvolutionError("completed direction delivery directory is absent")
    report_path = delivery / "delivery-report.json"
    literature_path = delivery / "literature" / "direction-literature.json"
    selected_path = delivery / "selected-method-skills.json"
    for path in (report_path, literature_path, selected_path):
        if not path.is_file():
            raise ContestDirectionSkillEvolutionError(f"required delivery artifact is absent: {path}")
    report = _load_json_object(report_path)
    if report.get("status") != "completed" or report.get("preexperiment_executed") is not True:
        raise ContestDirectionSkillEvolutionError(
            "Skill evolution requires a completed direction chain with a real pilot"
        )
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ContestDirectionSkillEvolutionError("delivery report lacks artifact bindings")
    literature = ContestDirectionLiteratureArtifact.model_validate_json(
        literature_path.read_text(encoding="utf-8")
    )
    _verify_report_binding(artifacts, "literature", literature_path, literature.artifact_hash)

    pilot_report = artifacts.get("prime_preexperiment")
    if not isinstance(pilot_report, Mapping):
        raise ContestDirectionSkillEvolutionError("delivery report lacks prime pilot binding")
    pilot_candidates: list[tuple[Path, ContestPrimePreexperimentArtifact]] = []
    for path in sorted((delivery / "preexperiment").glob("*/prime-preexperiment.json")):
        try:
            loaded = load_contest_prime_preexperiment(path, verify_files=True)
        except (OSError, ValueError):
            continue
        if (
            loaded.artifact_hash == pilot_report.get("artifact_hash")
            and _sha256_file(path) == pilot_report.get("sha256")
        ):
            pilot_candidates.append((path, loaded))
    if len(pilot_candidates) != 1:
        raise ContestDirectionSkillEvolutionError(
            "delivery does not contain exactly one report-bound verified pilot"
        )
    pilot_path, pilot = pilot_candidates[0]

    selected = _load_json_object(selected_path)
    expected_manifest_hash = canonical_model_hash(
        {key: value for key, value in selected.items() if key != "manifest_hash"}
    )
    if selected.get("manifest_hash") != expected_manifest_hash:
        raise ContestDirectionSkillEvolutionError("selected Skill manifest hash mismatch")
    _verify_report_file_binding(artifacts, "selected_method_skills", selected_path)
    selected_rows = selected.get("skills")
    if not isinstance(selected_rows, list) or not selected_rows:
        raise ContestDirectionSkillEvolutionError("selected Skill manifest is empty")
    parent_id, parent_path, parent_hash, parent_content = _select_parent_skill(
        selected_rows=selected_rows,
        skills_root=skills_root,
        direction=literature.direction,
        pilot=pilot,
    )

    ranked = _rank_relevant_papers(literature, maximum_ranked_papers)
    paper_evidence = _partition_papers(ranked)
    paper_by_id = {record.record_id: record for record in literature.retrieved_records}
    pilot_evidence = tuple(
        SkillEvolutionPilotEvidence(
            evidence_id=f"pilot:interval-{result.interval_index:02d}",
            interval_index=result.interval_index,
            raw_relative_path=result.raw_relative_path,
            raw_sha256=result.raw_sha256,
            null_draws_relative_path=result.null_draws_relative_path,
            null_draws_sha256=result.null_draws_sha256,
            partition=(
                "held_out"
                if result.interval_index == pilot.interval_results[-1].interval_index
                else "development"
            ),
        )
        for result in pilot.interval_results
    )
    return _LoadedDeliveryEvidence(
        literature=literature,
        pilot=pilot,
        delivery_report_binding=_file_binding(delivery, report_path, role="delivery_report"),
        literature_binding=_file_binding(delivery, literature_path, role="literature_artifact"),
        pilot_binding=_file_binding(delivery, pilot_path, role="pilot_artifact"),
        selected_manifest_binding=_file_binding(
            delivery,
            selected_path,
            role="selected_skill_manifest",
        ),
        parent_skill_id=parent_id,
        parent_skill_sha256=parent_hash,
        parent_skill_content=parent_content,
        paper_evidence=paper_evidence,
        paper_records=paper_by_id,
        pilot_evidence=pilot_evidence,
        pilot_results={item.interval_index: item for item in pilot.interval_results},
    )


def _rank_relevant_papers(
    literature: ContestDirectionLiteratureArtifact,
    maximum: int,
) -> tuple[tuple[ContestDirectionLiteratureRecord, float, float], ...]:
    records = [item for item in literature.retrieved_records if item.abstract]
    if len(records) < 2:
        raise ContestDirectionSkillEvolutionError(
            "at least two retrieved papers with abstracts are required for isolated validation"
        )
    query_token_sets = [
        {
            token
            for token in _search_tokens(query)
            if token not in _STOPWORDS
        }
        for query in literature.queries
    ]
    query_terms = {
        token
        for tokens in query_token_sets
        for token in tokens
    }
    query_frequency: Counter[str] = Counter(
        token for tokens in query_token_sets for token in tokens
    )
    maximum_query_frequency = max(query_frequency.values(), default=0)
    core_terms = {
        token
        for token, frequency in query_frequency.items()
        if frequency == maximum_query_frequency
    }
    required_core_matches = min(2, len(core_terms))
    document_frequency: Counter[str] = Counter()
    for record in records:
        document_frequency.update(
            set(_search_tokens(f"{record.title} {record.abstract or ''}")) & query_terms
        )
    ranked: list[tuple[ContestDirectionLiteratureRecord, float, float]] = []
    total = len(records)
    for record in records:
        title_tokens = set(_search_tokens(record.title))
        abstract_tokens = set(_search_tokens(record.abstract or ""))
        core_matches = core_terms & (title_tokens | abstract_tokens)
        if (
            required_core_matches
            and len(core_matches) < required_core_matches
        ) or (core_terms and not (core_terms & title_tokens)):
            continue
        relevance = 0.0
        for token in query_terms & (title_tokens | abstract_tokens):
            idf = math.log((total + 1) / (document_frequency[token] + 1)) + 1.0
            relevance += idf * (3.0 if token in title_tokens else 1.0)
        if relevance <= 0:
            continue
        citation_proxy = math.log1p(record.citation_count or 0)
        doi_bonus = 0.1 if record.doi else 0.0
        ranked.append((record, relevance, citation_proxy + doi_bonus))
    ranked.sort(
        key=lambda item: (
            -item[1],
            -item[2],
            -(item[0].citation_count or 0),
            item[0].title.casefold(),
            item[0].record_id,
        )
    )
    selected: list[tuple[ContestDirectionLiteratureRecord, float, float]] = []
    character_budget = 60_000
    used = 0
    for item in ranked:
        size = len(item[0].title) + len(item[0].abstract or "")
        if used + size > character_budget:
            continue
        selected.append(item)
        used += size
        if len(selected) >= maximum:
            break
    if len(selected) < 2:
        raise ContestDirectionSkillEvolutionError(
            "relevance-first complete-abstract selection produced fewer than two papers"
        )
    return tuple(selected)


def _select_parent_skill(
    *,
    selected_rows: Sequence[Any],
    skills_root: Path,
    direction: str,
    pilot: ContestPrimePreexperimentArtifact,
) -> tuple[str, Path, str, str]:
    """Choose the most domain-relevant verified parent, never catalogue order."""

    context = " ".join(
        (
            direction,
            pilot.scientific_question,
            pilot.hypothesis_zh,
            pilot.primary_metric,
            pilot.primary_null_model,
        )
    ).casefold()
    context_tokens = set(_tokens(context))
    context_markers = {
        marker
        for marker in (
            "素数",
            "数论",
            "间隙",
            "prime",
            "gap",
            "entropy",
            "permutation",
            "residue",
            "number-theory",
        )
        if marker in context
    }
    candidates: list[tuple[float, str, Path, str, str]] = []
    for raw in selected_rows:
        if not isinstance(raw, Mapping):
            raise ContestDirectionSkillEvolutionError("selected parent Skill row is invalid")
        skill_id = str(raw.get("skill_id") or "").strip()
        if not _SKILL_NAME.fullmatch(skill_id):
            raise ContestDirectionSkillEvolutionError("selected parent Skill ID is invalid")
        path = skills_root / skill_id / "SKILL.md"
        if not path.is_file() or path.is_symlink():
            raise ContestDirectionSkillEvolutionError(
                f"selected parent Skill file is absent: {skill_id}"
            )
        digest = _sha256_file(path)
        if digest != raw.get("content_sha256"):
            raise ContestDirectionSkillEvolutionError(
                f"selected parent Skill bytes changed: {skill_id}"
            )
        content = path.read_text(encoding="utf-8")
        searchable = f"{skill_id} {content}".casefold()
        token_overlap = len(context_tokens & set(_tokens(searchable)))
        marker_overlap = sum(1 for marker in context_markers if marker in searchable)
        domain_bonus = 5 if any(
            marker in searchable
            for marker in ("prime", "素数", "number-theory", "数论")
        ) else 0
        score = float(token_overlap + 3 * marker_overlap + domain_bonus)
        candidates.append((score, skill_id, path, digest, content))
    if not candidates:
        raise ContestDirectionSkillEvolutionError("selected Skill manifest is empty")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1:]


def _partition_papers(
    ranked: Sequence[tuple[ContestDirectionLiteratureRecord, float, float]],
) -> tuple[SkillEvolutionPaperEvidence, ...]:
    heldout_indices = {index for index in range(len(ranked)) if index % 4 == 1}
    if not heldout_indices:
        heldout_indices = {len(ranked) - 1}
    if len(heldout_indices) == len(ranked):
        heldout_indices = {len(ranked) - 1}
    return tuple(
        SkillEvolutionPaperEvidence(
            evidence_id=f"paper:{record.record_id}",
            record_id=record.record_id,
            record_hash=record.record_hash,
            title=record.title,
            doi=record.doi,
            citation_count=record.citation_count,
            citation_count_source=record.citation_count_source,
            relevance_score=round(relevance, 8),
            impact_proxy_score=round(impact, 8),
            partition="held_out" if index in heldout_indices else "development",
        )
        for index, (record, relevance, impact) in enumerate(ranked)
    )


def _generation_messages(evidence: _LoadedDeliveryEvidence) -> list[dict[str, str]]:
    development_papers = [
        _paper_prompt_payload(item, evidence.paper_records[item.record_id])
        for item in evidence.paper_evidence
        if item.partition == "development"
    ]
    development_pilot = [
        _pilot_prompt_payload(item, evidence.pilot_results[item.interval_index])
        for item in evidence.pilot_evidence
        if item.partition == "development"
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是科研方法Skill候选提炼器。只从给定开发证据抽象可迁移的研究流程，"
                "不要把论文摘要或探索性预实验观察改写成已证实的科学规律。每条经验必须"
                "引用程序提供的development evidence_id；不得虚构DOI、指标、运行或来源。"
                "保留自由探索，但明确何时停止、转向、扩大对照或缩小结论。输出中文JSON。"
                "候选只进入shadow，不得要求或声称生产启用。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json(
                {
                    "context_kind": "existing_parent_method_skill",
                    "parent_skill_id": evidence.parent_skill_id,
                    "parent_skill_sha256": evidence.parent_skill_sha256,
                    "content": evidence.parent_skill_content,
                    "boundary": "方法论，不是科学证据",
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json(
                {
                    "context_kind": "development_evidence_only",
                    "direction": evidence.literature.direction,
                    "papers_ranked_by": (
                        "query TF-IDF relevance first, then citation-count proxy; "
                        "journal impact factor unavailable"
                    ),
                    "papers": development_papers,
                    "pilot_intervals": development_pilot,
                    "pilot_boundary": evidence.pilot.scientific_boundary_zh,
                    "heldout_visible": False,
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json(
                {
                    "task": "生成一份简洁、方法型、可迁移的候选Skill内容草案",
                    "identity_fields_owned_by_program": True,
                    "long_evidence_must_stay_outside_skill_body": True,
                }
            ),
        },
    ]


def _heldout_messages(
    *,
    candidate_id: str,
    candidate_skill: str,
    heldout_payload: Mapping[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是与候选生成分离的Skill迁移评审。只依据现在提供的held-out案例，"
                "判断候选方法是否适用、是否保持预实验与科学证据边界、是否会产生无来源"
                "科学结论。不要修改候选，不要因为文风或格式否决；实质方法失效才否决。"
                "逐个case_id按输入顺序输出一次，最终给出overall_transfer_supported。"
            ),
        },
        {
            "role": "user",
            "content": _canonical_json(
                {
                    "context_kind": "shadow_candidate_skill",
                    "candidate_skill_id": candidate_id,
                    "candidate_is_active": False,
                    "content": candidate_skill,
                }
            ),
        },
        {
            "role": "user",
            "content": _canonical_json(dict(heldout_payload)),
        },
    ]


def _paper_prompt_payload(
    item: SkillEvolutionPaperEvidence,
    record: ContestDirectionLiteratureRecord,
) -> dict[str, Any]:
    return {
        "case_id": item.evidence_id,
        "kind": "retrieved_paper",
        "record_id": record.record_id,
        "record_hash": record.record_hash,
        "title": record.title,
        "abstract": record.abstract,
        "doi": record.doi,
        "repository_doi": record.repository_doi,
        "citation_count": record.citation_count,
        "citation_count_source": record.citation_count_source,
        "citation_count_as_of": (
            record.citation_count_as_of.isoformat()
            if record.citation_count_as_of is not None
            else None
        ),
        "relevance_score": item.relevance_score,
        "impact_proxy_score": item.impact_proxy_score,
        "boundary": "摘要级来源；被引次数不是方法正确性或期刊影响因子",
    }


def _pilot_prompt_payload(
    item: SkillEvolutionPilotEvidence,
    result: PrimeIntervalResult,
) -> dict[str, Any]:
    return {
        "case_id": item.evidence_id,
        "kind": "real_exploratory_pilot_interval",
        "interval_index": result.interval_index,
        "start": result.start,
        "stop": result.stop,
        "prime_count": result.prime_count,
        "gap_count": result.gap_count,
        "observed_metrics": result.observed_metrics.model_dump(mode="json"),
        "null_summaries": [item.model_dump(mode="json") for item in result.null_summaries],
        "raw_sha256": result.raw_sha256,
        "null_draws_sha256": result.null_draws_sha256,
        "boundary": "固定有限区间探索性预实验；不是总体规律、证明或正式实验",
    }


def _complete_or_replay(
    *,
    stage: Literal["candidate_generation", "heldout_validation"],
    messages: Sequence[Mapping[str, str]],
    response_schema: Mapping[str, Any],
    schema_name: str,
    escrow_path: Path,
    completion: CompletionCallable,
    config_path: Path | str,
    env_path: Path | str,
) -> _ReplayCompletion:
    input_hash = canonical_model_hash({"messages": list(messages), "schema": response_schema})
    if escrow_path.is_file():
        stored = StoredSkillEvolutionCompletion.model_validate_json(
            escrow_path.read_text(encoding="utf-8")
        )
        if stored.stage != stage or stored.input_sha256 != input_hash:
            raise ContestDirectionSkillEvolutionError(
                f"stored {stage} completion belongs to different input"
            )
        return _ReplayCompletion(stored, replayed=True)
    result = completion(
        messages=list(messages),
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=300,
        max_tokens=8_000,
        temperature=0.2 if stage == "candidate_generation" else 0.0,
        response_schema=dict(response_schema),
        response_schema_name=schema_name,
    )
    try:
        visible_payload = json.loads(result.response_text)
    except json.JSONDecodeError as exc:
        raise ContestDirectionSkillEvolutionError(
            f"{stage} visible response is not exact JSON"
        ) from exc
    if visible_payload != result.parsed_json:
        raise ContestDirectionSkillEvolutionError(
            f"{stage} visible response differs from parsed JSON"
        )
    values: dict[str, Any] = {
        "schema_version": "evidence-skill-completion-v1",
        "stage": stage,
        "input_sha256": input_hash,
        "provider": result.provider,
        "model_name": result.model_name,
        "response_text": result.response_text,
        "response_sha256": _text_sha256(result.response_text),
        "parsed_json": result.parsed_json,
        "reasoning_text": result.reasoning_text,
        "reasoning_sha256": _text_sha256(result.reasoning_text or ""),
        "usage": result.usage,
    }
    values["completion_hash"] = canonical_model_hash(values)
    stored = StoredSkillEvolutionCompletion.model_validate(values)
    _write_same_or_fail(escrow_path, _json_bytes(stored.model_dump(mode="json")))
    return _ReplayCompletion(stored, replayed=False)


def _render_candidate_skill(
    *,
    candidate_id: str,
    parent_skill_id: str,
    draft: EvidenceToSkillDraft,
) -> str:
    lines = [
        "---",
        f"name: {json.dumps(candidate_id, ensure_ascii=False)}",
        f"description: {json.dumps(draft.description_cn, ensure_ascii=False)}",
        "---",
        "",
        f"# {draft.title_cn}",
        "",
        "> Shadow candidate extracted from evidence-bound development cases. "
        "It is methodology, not scientific evidence.",
        "",
        "## Triggers",
        "",
        *[f"- {item}" for item in draft.trigger_conditions_cn],
        "",
        "## Workflow",
        "",
        *[f"{index}. {item}" for index, item in enumerate(draft.workflow_steps_cn, start=1)],
        "",
        "## Evidence-bound lessons",
        "",
    ]
    for lesson in draft.evidence_bound_lessons:
        refs = ", ".join(f"`{item}`" for item in lesson.development_evidence_ids)
        lines.append(f"- {lesson.lesson_cn} Sources: {refs}.")
    lines.extend(
        [
            "",
            "## Stop or pivot",
            "",
            *[f"- {item}" for item in draft.stop_or_pivot_rules_cn],
            "",
            "## Validation",
            "",
            *[f"- {item}" for item in draft.validation_checks_cn],
            "",
            "## Limits",
            "",
            *[f"- {item}" for item in draft.limitations_cn],
            "- Never treat citation count, an abstract, a Skill, or an exploratory pilot as proof.",
            "- Keep IDs, hashes, promotion state, and rollback decisions program-owned.",
            "",
            "## Provenance audit",
            "",
            "Read `references/evidence-bindings.json` only when auditing provenance. "
            "It is a compact binding index, not a substitute for the source artifacts.",
            f"The unchanged rollback target is `{parent_skill_id}`.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_openai_yaml(*, candidate_id: str, title: str) -> str:
    display = title[:64].strip() or candidate_id
    short = "从真实高影响论文与预实验中复用可验证、可回滚的研究方法"
    prompt = f"Use ${candidate_id} to design an evidence-bound exploratory research workflow."
    return "\n".join(
        [
            "interface:",
            f"  display_name: {json.dumps(display, ensure_ascii=False)}",
            f"  short_description: {json.dumps(short, ensure_ascii=False)}",
            f"  default_prompt: {json.dumps(prompt, ensure_ascii=False)}",
            "policy:",
            "  allow_implicit_invocation: false",
            "",
        ]
    )


def _candidate_evidence_bindings(
    *,
    evidence: _LoadedDeliveryEvidence,
    candidate_id: str,
    used_development_ids: set[str],
) -> dict[str, Any]:
    return {
        "schema_version": "candidate-skill-evidence-bindings-v1",
        "candidate_skill_id": candidate_id,
        "literature_artifact_hash": evidence.literature.artifact_hash,
        "pilot_artifact_hash": evidence.pilot.artifact_hash,
        "parent_skill_id": evidence.parent_skill_id,
        "parent_skill_sha256": evidence.parent_skill_sha256,
        "papers": [item.model_dump(mode="json") for item in evidence.paper_evidence],
        "pilot_intervals": [item.model_dump(mode="json") for item in evidence.pilot_evidence],
        "candidate_generation_evidence_ids": sorted(used_development_ids),
        "heldout_case_ids": list(evidence.heldout_case_ids),
        "heldout_was_hidden_from_candidate_generation": True,
        "scientific_evidence_established_by_skill": False,
        "production_enabled": False,
    }


def _validate_candidate_directory(
    *,
    candidate_dir: Path,
    candidate_id: str,
    heldout_evidence: Mapping[str, Any],
) -> bool:
    skill_path = candidate_dir / "SKILL.md"
    openai_path = candidate_dir / "agents" / "openai.yaml"
    binding_path = candidate_dir / "references" / "evidence-bindings.json"
    if not all(path.is_file() for path in (skill_path, openai_path, binding_path)):
        return False
    content = skill_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", content, flags=re.DOTALL)
    if match is None:
        return False
    frontmatter = yaml.safe_load(match.group(1))
    if not isinstance(frontmatter, Mapping) or set(frontmatter) != {"name", "description"}:
        return False
    if frontmatter.get("name") != candidate_id or not str(frontmatter.get("description", "")).strip():
        return False
    interface = yaml.safe_load(openai_path.read_text(encoding="utf-8"))
    if not isinstance(interface, Mapping):
        return False
    default_prompt = str(
        (interface.get("interface") or {}).get("default_prompt", "")
        if isinstance(interface.get("interface"), Mapping)
        else ""
    )
    if f"${candidate_id}" not in default_prompt:
        return False
    lowered = content.casefold()
    for case in heldout_evidence.get("cases", []):
        if not isinstance(case, Mapping):
            return False
        hidden_markers = [
            case.get("record_hash"),
            case.get("doi"),
            case.get("raw_sha256"),
            case.get("null_draws_sha256"),
        ]
        if any(
            isinstance(marker, str) and len(marker) >= 12 and marker.casefold() in lowered
            for marker in hidden_markers
        ):
            return False
    return True


def _candidate_skill_id(parent_skill_id: str, seed_hash: str) -> str:
    suffix = f"-evo-{seed_hash[:12]}"
    base = parent_skill_id[: 64 - len(suffix)].rstrip("-")
    return f"{base}{suffix}"


def _heldout_schema(case_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "case_assessments": {
                "type": "array",
                "minItems": len(case_ids),
                "maxItems": len(case_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string", "enum": list(case_ids)},
                        "methodology_transfers": {"type": "boolean"},
                        "evidence_boundary_preserved": {"type": "boolean"},
                        "no_unsupported_scientific_claim": {"type": "boolean"},
                        "assessment_cn": {"type": "string"},
                    },
                    "required": [
                        "case_id",
                        "methodology_transfers",
                        "evidence_boundary_preserved",
                        "no_unsupported_scientific_claim",
                        "assessment_cn",
                    ],
                    "additionalProperties": False,
                },
            },
            "overall_transfer_supported": {"type": "boolean"},
            "limitations_cn": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "case_assessments",
            "overall_transfer_supported",
            "limitations_cn",
        ],
        "additionalProperties": False,
    }


def _load_and_verify_existing(
    *,
    artifact_path: Path,
    report_path: Path,
    delivery: Path,
    output: Path,
    skills_root: Path,
) -> EvidenceToSkillEvolutionArtifact:
    artifact = EvidenceToSkillEvolutionArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    evidence = _load_delivery_evidence(delivery, skills_root, len(artifact.paper_evidence))
    if (
        artifact.direction != evidence.literature.direction
        or artifact.literature_artifact_hash != evidence.literature.artifact_hash
        or artifact.pilot_artifact_hash != evidence.pilot.artifact_hash
        or artifact.parent_skill_id != evidence.parent_skill_id
        or artifact.parent_skill_sha256 != evidence.parent_skill_sha256
        or artifact.paper_evidence != evidence.paper_evidence
        or artifact.pilot_evidence != evidence.pilot_evidence
        or artifact.delivery_report_binding != evidence.delivery_report_binding
        or artifact.literature_binding != evidence.literature_binding
        or artifact.pilot_binding != evidence.pilot_binding
        or artifact.selected_skill_manifest_binding != evidence.selected_manifest_binding
    ):
        raise ContestDirectionSkillEvolutionError(
            "completed Skill evolution no longer matches its source evidence"
        )
    _verify_bindings(output, artifact.candidate_files)
    _verify_bindings(output, artifact.process_files)
    if report_path.read_text(encoding="utf-8") != _render_report(artifact):
        raise ContestDirectionSkillEvolutionError("Skill evolution report changed")
    candidate_dir = output / "shadow" / "candidates" / artifact.candidate_skill_id
    if not _validate_candidate_directory(
        candidate_dir=candidate_dir,
        candidate_id=artifact.candidate_skill_id,
        heldout_evidence=evidence.heldout_payload,
    ):
        raise ContestDirectionSkillEvolutionError("candidate Skill directory failed replay checks")
    generation = StoredSkillEvolutionCompletion.model_validate_json(
        (output / "process" / "generation-completion.json").read_text("utf-8")
    )
    heldout = StoredSkillEvolutionCompletion.model_validate_json(
        (output / "process" / "heldout-completion.json").read_text("utf-8")
    )
    if (
        generation.completion_hash != artifact.generation_completion_hash
        or heldout.completion_hash != artifact.heldout_completion_hash
    ):
        raise ContestDirectionSkillEvolutionError("completion escrow hash mismatch")
    return artifact


def _render_report(artifact: EvidenceToSkillEvolutionArtifact) -> str:
    paper_lines = [
        f"- `{item.partition}` {item.title}；DOI：{item.doi or '未知'}；"
        f"被引：{item.citation_count if item.citation_count is not None else '未知'}；"
        f"相关性分：{item.relevance_score:.3f}"
        for item in artifact.paper_evidence
    ]
    validation_lines = [
        f"- `{item.case_id}`：{'通过' if item.methodology_transfers and item.evidence_boundary_preserved and item.no_unsupported_scientific_claim else '未通过'}；{item.assessment_cn}"
        for item in artifact.heldout_validation.case_assessments
    ]
    return "\n".join(
        [
            "# 证据到候选 Skill 的受控自进化报告",
            "",
            f"- 方向：{artifact.direction}",
            f"- 候选：`{artifact.candidate_skill_id}`",
            f"- 父 Skill：`{artifact.parent_skill_id}`",
            f"- 状态：`{artifact.candidate_status}`",
            f"- 可显式晋升：`{str(artifact.promotion_eligible).lower()}`",
            "- 当前生产启用：`false`",
            "- 影响力代理：先按检索查询 TF-IDF 相关性排序，再参考被引次数；"
            "没有把被引次数冒充期刊影响因子。",
            "",
            "## 文献分区",
            "",
            *paper_lines,
            "",
            "## Held-out 验证",
            "",
            *validation_lines,
            "",
            "## 边界",
            "",
            "候选只抽象研究方法。论文摘要、被引次数和探索性预实验都不能单独建立"
            "科学结论；候选通过 held-out 也只代表具备显式晋升资格，不会自动进入"
            "active Skills。父 Skill 字节保持不变，可作为回滚目标。",
            "",
            f"- Artifact SHA-256：`{artifact.artifact_hash}`",
            "",
        ]
    )


def _bind_candidate_files(root: Path, candidate_dir: Path) -> tuple[SkillEvolutionFileBinding, ...]:
    return tuple(
        _file_binding(root, path, role=role)
        for path, role in (
            (candidate_dir / "SKILL.md", "candidate_skill"),
            (candidate_dir / "agents" / "openai.yaml", "candidate_interface"),
            (
                candidate_dir / "references" / "evidence-bindings.json",
                "candidate_evidence_bindings",
            ),
        )
    )


def _verify_bindings(root: Path, bindings: Sequence[SkillEvolutionFileBinding]) -> None:
    for binding in bindings:
        path = (root / binding.relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ContestDirectionSkillEvolutionError(
                f"bound evolution file is absent: {binding.relative_path}"
            )
        if path.stat().st_size != binding.bytes or _sha256_file(path) != binding.sha256:
            raise ContestDirectionSkillEvolutionError(
                f"bound evolution file changed: {binding.relative_path}"
            )


def _verify_active_receipt(
    receipt: SkillActivationReceipt,
    active_dir: Path,
    artifact: EvidenceToSkillEvolutionArtifact,
) -> None:
    if (
        receipt.candidate_artifact_hash != artifact.artifact_hash
        or receipt.candidate_skill_id != artifact.candidate_skill_id
        or not active_dir.is_dir()
        or _sha256_file(active_dir / "SKILL.md") != receipt.candidate_skill_sha256
    ):
        raise ContestDirectionSkillEvolutionError("existing Skill activation receipt mismatch")


def _verify_report_binding(
    artifacts: Mapping[str, Any],
    key: str,
    path: Path,
    artifact_hash: str,
) -> None:
    row = artifacts.get(key)
    if not isinstance(row, Mapping):
        raise ContestDirectionSkillEvolutionError(f"delivery report lacks {key} binding")
    if row.get("sha256") != _sha256_file(path) or row.get("artifact_hash") != artifact_hash:
        raise ContestDirectionSkillEvolutionError(f"delivery report {key} binding mismatch")


def _verify_report_file_binding(
    artifacts: Mapping[str, Any],
    key: str,
    path: Path,
) -> None:
    row = artifacts.get(key)
    if not isinstance(row, Mapping) or row.get("sha256") != _sha256_file(path):
        raise ContestDirectionSkillEvolutionError(f"delivery report {key} file mismatch")


def _file_binding(root: Path, path: Path, *, role: str) -> SkillEvolutionFileBinding:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ContestDirectionSkillEvolutionError("evolution file escapes its root") from exc
    return SkillEvolutionFileBinding(
        relative_path=relative,
        sha256=_sha256_file(resolved),
        bytes=resolved.stat().st_size,
        role=role,
    )


def _write_same_or_fail(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError as exc:
        if path.read_bytes() != payload:
            raise ContestDirectionSkillEvolutionError(
                f"write-once evolution artifact changed: {path}"
            ) from exc


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestDirectionSkillEvolutionError(f"cannot load JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ContestDirectionSkillEvolutionError(f"JSON artifact is not an object: {path}")
    return value


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(value.casefold()))


def _search_tokens(value: str) -> tuple[str, ...]:
    """Apply a tiny deterministic English plural normalizer for retrieval ranking."""

    normalized: list[str] = []
    for token in _tokens(value):
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        normalized.append(token)
    return tuple(normalized)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ContestDirectionSkillEvolutionError",
    "EvidenceToSkillEvolutionArtifact",
    "EvidenceToSkillEvolutionRun",
    "SkillActivationReceipt",
    "SkillRollbackReceipt",
    "activate_validated_evolved_skill",
    "rollback_activated_evolved_skill",
    "run_evidence_to_skill_evolution",
]
