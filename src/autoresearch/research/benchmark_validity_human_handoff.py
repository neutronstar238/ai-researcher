"""Result-blind human-review handoff for Task 263.6.7.2.2.

The benchmark-validity census requires two genuinely independent human
reviewers and a third, distinct human adjudicator.  Software can make their
roles, visibility, locks, and ordering auditable; it cannot prove that a JSON
record represents a natural person or truthfully attest consent, expertise,
independence, or conflicts.  This module therefore freezes an empty handoff
ceremony and future digest-only receipt schemas without assigning anyone or
authorizing the census.

Private identity, qualification, conflict, and consent evidence stays outside
the repository.  Public artifacts retain only schemas and, after a real owner-
run enrollment ceremony, content hashes.  The frozen package created here has
zero identities, assignments, reviewer packets, locks, screening/coding
records, adjudicator access, benchmark outcomes, or model calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, TypeAdapter, ValidationInfo, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .benchmark_validity_harness import FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH
from .benchmark_validity_pagination_erratum import (
    BenchmarkValidityPaginationErratumReport,
    PaginationErratumManifest,
)
from .benchmark_validity_protocol import BenchmarkValidityProtocol, HumanCodingPlan
from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

PARENT_ERRATUM_COMMIT = "e61c4c5c55da6a78437484a8012f7681a2670cba"
PARENT_ERRATUM_HASH = "f0ffc351a43eb8ac0176cca787ad53f9af4e343cc2554aca068a20215f81d571"
PARENT_ERRATUM_REPORT_HASH = "3fefa90f73c5e6990f1817c0a06f33707b8a5e553f344a321cab18451f50310b"
PARENT_ERRATUM_PROJECTION_HASH = "b36624099cdda8030548068290596c41411b8e4bbc15611e3db519b2add79e7c"
PARENT_ERRATUM_REPLAY_HASH = "f2e83a372927b8dbebec5c48974c7b6a46d997205d8a67eaf2fe9de2c97d98c8"
PARENT_ERRATUM_MANIFEST_HASH = "a62d742e9466369eb5e573871b413e6c71a9aee3fff1a1e44d178593facc3ffd"
PARENT_ERRATUM_SOURCE_SHA256 = "1d3e3e364a6f3a247d8e5000f78ccc9b55f6bdcd03a096f58f2ac2321c5155d4"
PARENT_INTEGRATED_HARNESS_SOURCE_SHA256 = (
    "f22c9bbc2a528d2ae9ab58a96ca4ddcdb4cc26fb0158deba458251d4e22fe227"
)

HUMAN_HANDOFF_REPORT_FILENAME = "benchmark-human-review-handoff-report.json"
HUMAN_HANDOFF_MARKDOWN_FILENAME = "benchmark-human-review-handoff-report.md"
HUMAN_HANDOFF_PROJECTION_FILENAME = "benchmark-human-review-handoff-projection.json"
HUMAN_HANDOFF_REPLAY_FILENAME = "benchmark-human-review-handoff-replay.json"
HUMAN_HANDOFF_SCHEMA_FILENAME = "benchmark-human-review-handoff-schemas.json"
HUMAN_HANDOFF_ROLE_SLOTS_FILENAME = "benchmark-human-review-role-slots.json"
HUMAN_HANDOFF_PACKET_TEMPLATES_FILENAME = "benchmark-human-review-packet-templates.json"
HUMAN_HANDOFF_OWNER_CHECKLIST_FILENAME = "benchmark-human-review-owner-checklist.md"
HUMAN_HANDOFF_MANIFEST_FILENAME = "benchmark-human-review-handoff-manifest.json"
HUMAN_HANDOFF_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/"
    "frozen_benchmark_validity_human_handoff_probe_v1.py"
)

REQUIRED_ROLE_IDS = {"reviewer-a", "reviewer-b", "adjudicator"}
REQUIRED_PRIVATE_FIELD_IDS = {
    "conflict-disclosure-artifact",
    "identity-evidence-artifact",
    "opaque-person-id",
    "owner-verification-attestation",
    "private-assignment-record",
    "qualification-evidence-artifact",
    "role-consent-artifact",
}
REQUIRED_TRANSITION_IDS = {
    "assign-to-reviewer-packets",
    "dual-lock-to-adjudicator",
    "reviewer-packets-to-dual-lock",
    "unassigned-to-owner-verified",
    "adjudicator-to-synthesis-gate",
}

_JSON_PAYLOAD_ADAPTER = TypeAdapter(dict[str, Any])
_FORBIDDEN_RESULT_KEYS = {
    "actual_identity",
    "actual_human_identity",
    "adjudication_decision",
    "admission_card",
    "benchmark_outcome",
    "candidate_model_output",
    "critical_code",
    "human_name",
    "identity_evidence",
    "model_output",
    "opaque_person_id",
    "person_id",
    "review_lock",
    "reviewer_decision",
    "reviewer_identity",
    "role_assignment",
    "screening_decision",
    "screening_record",
}


class HumanReviewHandoffIntegrityError(ValueError):
    """Raised when a handoff contract or persisted artifact no longer verifies."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _pretty_json_text(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _addressed_payload(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    json_payload = _JSON_PAYLOAD_ADAPTER.dump_python(payload, mode="json")
    normalized = dict(payload)
    normalized[hash_field] = canonical_sha256(json_payload)
    return normalized


def _walk_forbidden(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in _FORBIDDEN_RESULT_KEYS and item not in (None, False, 0, "", [], {}):
                raise ValueError(f"{path}.{raw_key} is forbidden in the result-blind handoff")
            _walk_forbidden(item, path=f"{path}.{raw_key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone aware")
    return value.astimezone(timezone.utc)


class HumanReviewRole(str, Enum):
    REVIEWER_A = "reviewer-a"
    REVIEWER_B = "reviewer-b"
    ADJUDICATOR = "adjudicator"


class HumanHandoffStage(str, Enum):
    UNASSIGNED = "unassigned"
    OWNER_VERIFIED = "owner-verified-assignments"
    REVIEWER_PACKETS_ISSUED = "reviewer-packets-issued"
    DUAL_LOCKED = "dual-reviewer-locked"
    ADJUDICATOR_OPEN = "adjudicator-conflicts-open"
    SYNTHESIS_GATE = "descriptive-synthesis-gate"


class RoleSlotStatus(str, Enum):
    UNASSIGNED = "unassigned"


class PublicProjectionPolicy(str, Enum):
    OMIT_VALUE = "omit-value"
    SHA256_ONLY = "sha256-only"
    OPAQUE_IDENTIFIER_ONLY = "opaque-identifier-only"


class ParentPaginationErratumEvidence(KernelContract):
    """Exact Task 263.6.7.2.1 artifacts authorized as immutable parents."""

    schema_version: Literal["benchmark-human-handoff-parent-erratum-v1"] = (
        "benchmark-human-handoff-parent-erratum-v1"
    )
    focused_parent_commit: StableId
    protocol_hash: Sha256
    erratum_hash: Sha256
    report_hash: Sha256
    projection_sha256: Sha256
    replay_certificate_hash: Sha256
    manifest_hash: Sha256
    erratum_source_sha256: Sha256
    integrated_harness_source_sha256: Sha256
    evidence_hash: Sha256

    @model_validator(mode="after")
    def _validate_parent(self) -> ParentPaginationErratumEvidence:
        expected = {
            "focused_parent_commit": PARENT_ERRATUM_COMMIT,
            "protocol_hash": FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH,
            "erratum_hash": PARENT_ERRATUM_HASH,
            "report_hash": PARENT_ERRATUM_REPORT_HASH,
            "projection_sha256": PARENT_ERRATUM_PROJECTION_HASH,
            "replay_certificate_hash": PARENT_ERRATUM_REPLAY_HASH,
            "manifest_hash": PARENT_ERRATUM_MANIFEST_HASH,
            "erratum_source_sha256": PARENT_ERRATUM_SOURCE_SHA256,
            "integrated_harness_source_sha256": PARENT_INTEGRATED_HARNESS_SOURCE_SHA256,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"parent erratum binding changed: {field_name}")
        if self.evidence_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("parent erratum evidence hash mismatch")
        return self

    @classmethod
    def from_artifacts(
        cls,
        *,
        report: BenchmarkValidityPaginationErratumReport,
        manifest: PaginationErratumManifest,
        focused_parent_commit: str,
    ) -> ParentPaginationErratumEvidence:
        report.erratum.verify_integrity()
        checked_manifest = PaginationErratumManifest.model_validate(
            manifest.model_dump(mode="json")
        )
        if checked_manifest.report_hash != report.report_hash:
            raise HumanReviewHandoffIntegrityError("parent erratum report/manifest mismatch")
        if checked_manifest.erratum_hash != report.erratum.erratum_hash:
            raise HumanReviewHandoffIntegrityError("parent erratum hash/manifest mismatch")
        if checked_manifest.projection_sha256 != report.projection.projection_sha256:
            raise HumanReviewHandoffIntegrityError("parent projection/manifest mismatch")
        if (
            checked_manifest.replay_certificate_hash
            != report.replay_certificate.certificate_hash
        ):
            raise HumanReviewHandoffIntegrityError("parent replay/manifest mismatch")
        payload = {
            "schema_version": "benchmark-human-handoff-parent-erratum-v1",
            "focused_parent_commit": focused_parent_commit,
            "protocol_hash": report.erratum.protocol_hash,
            "erratum_hash": report.erratum.erratum_hash,
            "report_hash": report.report_hash,
            "projection_sha256": report.projection.projection_sha256,
            "replay_certificate_hash": report.replay_certificate.certificate_hash,
            "manifest_hash": checked_manifest.manifest_hash,
            "erratum_source_sha256": report.erratum_source_sha256,
            "integrated_harness_source_sha256": report.integrated_harness_source_sha256,
        }
        return cls.model_validate(_addressed_payload(payload, "evidence_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"evidence_hash"}))


class HumanRoleRequirement(KernelContract):
    """One role's non-automatable enrollment and visibility requirements."""

    role: HumanReviewRole
    natural_person_required: Literal[True] = True
    private_identity_evidence_required: Literal[True] = True
    owner_verification_required: Literal[True] = True
    qualification_evidence_required: Literal[True] = True
    conflict_disclosure_required: Literal[True] = True
    material_conflict_prohibited: Literal[True] = True
    explicit_role_consent_required: Literal[True] = True
    distinct_person_from_other_roles_required: Literal[True] = True
    automation_may_assign_role: Literal[False] = False
    automation_may_attest_natural_personhood: Literal[False] = False
    independent_lock_required: bool
    access_opens_after: Literal["owner-verification", "dual-reviewer-lock"]
    may_view_other_reviewer_work_before_dual_lock: Literal[False] = False
    may_view_locked_conflicts_after_dual_lock: bool
    requirement_hash: Sha256

    @model_validator(mode="after")
    def _validate_requirement(self) -> HumanRoleRequirement:
        reviewer = self.role in {HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B}
        if self.independent_lock_required != reviewer:
            raise ValueError("only reviewers independently lock coding work")
        expected_open = "owner-verification" if reviewer else "dual-reviewer-lock"
        if self.access_opens_after != expected_open:
            raise ValueError("role access boundary changed")
        if self.may_view_locked_conflicts_after_dual_lock != (not reviewer):
            raise ValueError("only the adjudicator may view conflicts after dual lock")
        if self.requirement_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("role requirement hash mismatch")
        return self

    @classmethod
    def create(cls, role: HumanReviewRole) -> HumanRoleRequirement:
        reviewer = role in {HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B}
        payload = {
            "role": role,
            "natural_person_required": True,
            "private_identity_evidence_required": True,
            "owner_verification_required": True,
            "qualification_evidence_required": True,
            "conflict_disclosure_required": True,
            "material_conflict_prohibited": True,
            "explicit_role_consent_required": True,
            "distinct_person_from_other_roles_required": True,
            "automation_may_assign_role": False,
            "automation_may_attest_natural_personhood": False,
            "independent_lock_required": reviewer,
            "access_opens_after": "owner-verification" if reviewer else "dual-reviewer-lock",
            "may_view_other_reviewer_work_before_dual_lock": False,
            "may_view_locked_conflicts_after_dual_lock": not reviewer,
        }
        return cls.model_validate(_addressed_payload(payload, "requirement_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"requirement_hash"}))


class PrivateAssignmentFieldSpec(KernelContract):
    """Field retained privately during owner-controlled human enrollment."""

    field_id: StableId
    definition: str = Field(min_length=1, max_length=2_048)
    required: Literal[True] = True
    stored_in_repository: Literal[False] = False
    automation_may_supply_value: Literal[False] = False
    public_projection_policy: PublicProjectionPolicy
    field_spec_hash: Sha256

    @model_validator(mode="after")
    def _validate_spec(self) -> PrivateAssignmentFieldSpec:
        if self.field_spec_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("private field specification hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PrivateAssignmentFieldSpec:
        payload = {
            "required": True,
            "stored_in_repository": False,
            "automation_may_supply_value": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "field_spec_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"field_spec_hash"}))


class PublicHumanRoleSlot(KernelContract):
    """Result-free public slot; it deliberately contains no person or assignment."""

    role: HumanReviewRole
    status: Literal[RoleSlotStatus.UNASSIGNED] = RoleSlotStatus.UNASSIGNED
    opaque_person_id: None = None
    private_assignment_record_sha256: None = None
    assignment_receipt_hash: None = None
    actual_identity_present: Literal[False] = False
    owner_verified: Literal[False] = False
    slot_hash: Sha256

    @model_validator(mode="after")
    def _validate_slot(self) -> PublicHumanRoleSlot:
        if self.slot_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("public role slot hash mismatch")
        return self

    @classmethod
    def create(cls, role: HumanReviewRole) -> PublicHumanRoleSlot:
        payload = {
            "role": role,
            "status": RoleSlotStatus.UNASSIGNED,
            "opaque_person_id": None,
            "private_assignment_record_sha256": None,
            "assignment_receipt_hash": None,
            "actual_identity_present": False,
            "owner_verified": False,
        }
        return cls.model_validate(_addressed_payload(payload, "slot_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"slot_hash"}))


class BlindedReviewPacketTemplate(KernelContract):
    """Allowed and forbidden artifact classes for one future role packet."""

    packet_id: StableId
    role: HumanReviewRole
    issued_after_stage: HumanHandoffStage
    visible_artifact_classes: list[StableId]
    forbidden_artifact_classes: list[StableId]
    candidate_set_commitment_required: Literal[True] = True
    own_work_only_until_dual_lock: bool
    conflict_only_after_dual_lock: bool
    benchmark_outcomes_visible: Literal[False] = False
    candidate_model_outputs_visible: Literal[False] = False
    publication_decision_visible: Literal[False] = False
    packet_hash: Sha256

    @field_validator("visible_artifact_classes", "forbidden_artifact_classes")
    @classmethod
    def _sort_unique(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("packet artifact classes must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_packet(self) -> BlindedReviewPacketTemplate:
        reviewer = self.role in {HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B}
        expected_stage = (
            HumanHandoffStage.OWNER_VERIFIED if reviewer else HumanHandoffStage.DUAL_LOCKED
        )
        if self.issued_after_stage is not expected_stage:
            raise ValueError("role packet opens at the wrong stage")
        if self.own_work_only_until_dual_lock != reviewer:
            raise ValueError("reviewer packets must remain own-work-only until dual lock")
        if self.conflict_only_after_dual_lock != (not reviewer):
            raise ValueError("adjudicator access must be conflict-only after dual lock")
        if "benchmark-outcomes" not in self.forbidden_artifact_classes:
            raise ValueError("benchmark outcomes must stay outside human handoff packets")
        if "candidate-model-outputs" not in self.forbidden_artifact_classes:
            raise ValueError("candidate model outputs must stay outside handoff packets")
        expected_visible = (
            {
                "bibliographic-metadata",
                "candidate-set-commitment",
                "frozen-codebook",
                "frozen-protocol-and-erratum",
                "frozen-screening-form",
                "own-private-workspace",
                "primary-source-evidence",
            }
            if reviewer
            else {
                "candidate-set-commitment",
                "dual-lock-receipts",
                "frozen-codebook",
                "frozen-protocol-and-erratum",
                "locked-conflict-index",
                "locked-conflict-source-evidence",
            }
        )
        if set(self.visible_artifact_classes) != expected_visible:
            raise ValueError("role packet visibility changed or leaked cross-reviewer work")
        if set(self.visible_artifact_classes) & set(self.forbidden_artifact_classes):
            raise ValueError("role packet cannot expose a forbidden artifact class")
        if self.packet_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("packet template hash mismatch")
        return self

    @classmethod
    def create(cls, *, role: HumanReviewRole) -> BlindedReviewPacketTemplate:
        reviewer = role in {HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B}
        visible = (
            [
                "bibliographic-metadata",
                "candidate-set-commitment",
                "frozen-codebook",
                "frozen-protocol-and-erratum",
                "frozen-screening-form",
                "own-private-workspace",
                "primary-source-evidence",
            ]
            if reviewer
            else [
                "candidate-set-commitment",
                "dual-lock-receipts",
                "frozen-codebook",
                "frozen-protocol-and-erratum",
                "locked-conflict-index",
                "locked-conflict-source-evidence",
            ]
        )
        forbidden = [
            "benchmark-outcomes",
            "candidate-model-outputs",
            "publication-decision",
            "unlocked-reviewer-drafts",
        ]
        if reviewer:
            forbidden.extend(
                [
                    "adjudication-draft",
                    "other-reviewer-codes-before-dual-lock",
                    "other-reviewer-lock-before-dual-lock",
                ]
            )
        else:
            forbidden.extend(
                [
                    "non-conflict-reviewer-codes",
                    "reviewer-work-before-dual-lock",
                ]
            )
        payload = {
            "packet_id": f"packet-template:{role.value}",
            "role": role,
            "issued_after_stage": (
                HumanHandoffStage.OWNER_VERIFIED
                if reviewer
                else HumanHandoffStage.DUAL_LOCKED
            ),
            "visible_artifact_classes": sorted(visible),
            "forbidden_artifact_classes": sorted(forbidden),
            "candidate_set_commitment_required": True,
            "own_work_only_until_dual_lock": reviewer,
            "conflict_only_after_dual_lock": not reviewer,
            "benchmark_outcomes_visible": False,
            "candidate_model_outputs_visible": False,
            "publication_decision_visible": False,
        }
        return cls.model_validate(_addressed_payload(payload, "packet_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"packet_hash"}))


class HumanHandoffTransition(KernelContract):
    """One prospective, non-skippable ceremony transition."""

    transition_id: StableId
    from_stage: HumanHandoffStage
    to_stage: HumanHandoffStage
    precondition: str = Field(min_length=1, max_length=2_048)
    human_action_required: bool
    automation_may_advance_without_human_evidence: Literal[False] = False
    transition_hash: Sha256

    @model_validator(mode="after")
    def _validate_transition(self) -> HumanHandoffTransition:
        if self.transition_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("handoff transition hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HumanHandoffTransition:
        payload = {"automation_may_advance_without_human_evidence": False, **values}
        return cls.model_validate(_addressed_payload(payload, "transition_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"transition_hash"}))


class DualReviewerLockPolicy(KernelContract):
    """Frozen blinding, lock, agreement, and coverage barrier."""

    reviewer_roles: list[Literal[HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B]]
    candidate_set_hash_must_match: Literal[True] = True
    independent_private_workspaces_required: Literal[True] = True
    peer_work_hidden_until_both_locks: Literal[True] = True
    screening_and_critical_code_hashes_required: Literal[True] = True
    locks_append_only_and_irrevocable: Literal[True] = True
    unlock_or_recode_after_peer_reveal_terminal_stop: Literal[True] = True
    title_abstract_dual_screen_fraction: float = Field(ge=1.0, le=1.0)
    full_text_dual_screen_fraction: float = Field(ge=1.0, le=1.0)
    critical_field_dual_code_fraction: float = Field(ge=1.0, le=1.0)
    exact_agreement_threshold: float = Field(ge=0.9, le=0.9)
    cohen_kappa_threshold_when_estimable: float = Field(ge=0.8, le=0.8)
    overall_critical_coverage_threshold: float = Field(ge=0.9, le=0.9)
    per_critical_field_coverage_threshold: float = Field(ge=0.85, le=0.85)
    adjudication_cannot_repair_failed_agreement_or_coverage: Literal[True] = True
    policy_hash: Sha256

    @field_validator("reviewer_roles")
    @classmethod
    def _sort_reviewers(
        cls,
        value: list[Literal[HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B]],
    ) -> list[Literal[HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B]]:
        return sorted(value, key=lambda item: item.value)

    @model_validator(mode="after")
    def _validate_policy(self) -> DualReviewerLockPolicy:
        if set(self.reviewer_roles) != {
            HumanReviewRole.REVIEWER_A,
            HumanReviewRole.REVIEWER_B,
        }:
            raise ValueError("dual lock policy needs both independent reviewers")
        if self.policy_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("dual lock policy hash mismatch")
        return self

    @classmethod
    def from_human_coding_plan(cls, plan: HumanCodingPlan) -> DualReviewerLockPolicy:
        if plan.reviewer_roles != ["reviewer-a", "reviewer-b"]:
            raise ValueError("frozen human coding reviewer roles changed")
        if plan.adjudicator_role != "adjudicator":
            raise ValueError("frozen human coding adjudicator role changed")
        payload = {
            "reviewer_roles": [HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B],
            "candidate_set_hash_must_match": True,
            "independent_private_workspaces_required": True,
            "peer_work_hidden_until_both_locks": True,
            "screening_and_critical_code_hashes_required": True,
            "locks_append_only_and_irrevocable": True,
            "unlock_or_recode_after_peer_reveal_terminal_stop": True,
            "title_abstract_dual_screen_fraction": plan.title_abstract_dual_screen_fraction,
            "full_text_dual_screen_fraction": plan.full_text_dual_screen_fraction,
            "critical_field_dual_code_fraction": plan.critical_field_dual_code_fraction,
            "exact_agreement_threshold": plan.exact_agreement_threshold,
            "cohen_kappa_threshold_when_estimable": (
                plan.cohen_kappa_threshold_when_estimable
            ),
            "overall_critical_coverage_threshold": (
                plan.overall_critical_coverage_threshold
            ),
            "per_critical_field_coverage_threshold": (
                plan.per_critical_field_coverage_threshold
            ),
            "adjudication_cannot_repair_failed_agreement_or_coverage": True,
        }
        return cls.model_validate(_addressed_payload(payload, "policy_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"policy_hash"}))


class HumanRoleAssignmentReceipt(KernelContract):
    """Future hash-only receipt populated only by a human-controlled ceremony."""

    schema_version: Literal["benchmark-human-role-assignment-receipt-v1"] = (
        "benchmark-human-role-assignment-receipt-v1"
    )
    protocol_hash: Sha256
    handoff_hash: Sha256
    role: HumanReviewRole
    role_requirement_hash: Sha256
    packet_template_hash: Sha256
    opaque_person_id: StableId
    private_assignment_record_sha256: Sha256
    identity_evidence_sha256: Sha256
    qualification_evidence_sha256: Sha256
    conflict_disclosure_sha256: Sha256
    role_consent_sha256: Sha256
    owner_verification_attestation_sha256: Sha256
    owner_verified_natural_person: Literal[True] = True
    material_conflict_declared: Literal[False] = False
    automation_claims_natural_personhood: Literal[False] = False
    automation_supplied_private_values: Literal[False] = False
    accepted_at: datetime
    formal_census_authorized: Literal[False] = False
    receipt_hash: Sha256

    @field_validator("accepted_at")
    @classmethod
    def _accepted_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="role acceptance time")

    @model_validator(mode="after")
    def _validate_receipt(self) -> HumanRoleAssignmentReceipt:
        if self.receipt_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("role assignment receipt hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        handoff: BenchmarkHumanReviewHandoff,
        role: HumanReviewRole,
        opaque_person_id: str,
        private_assignment_record_sha256: str,
        identity_evidence_sha256: str,
        qualification_evidence_sha256: str,
        conflict_disclosure_sha256: str,
        role_consent_sha256: str,
        owner_verification_attestation_sha256: str,
        accepted_at: datetime,
    ) -> HumanRoleAssignmentReceipt:
        handoff.verify_integrity()
        requirement = next(item for item in handoff.role_requirements if item.role is role)
        packet = next(item for item in handoff.packet_templates if item.role is role)
        normalized_accepted_at = _utc(accepted_at, label="role acceptance time")
        if normalized_accepted_at < handoff.frozen_at:
            raise ValueError("human role acceptance cannot precede the handoff freeze")
        payload = {
            "schema_version": "benchmark-human-role-assignment-receipt-v1",
            "protocol_hash": handoff.parent_erratum.protocol_hash,
            "handoff_hash": handoff.handoff_hash,
            "role": role,
            "role_requirement_hash": requirement.requirement_hash,
            "packet_template_hash": packet.packet_hash,
            "opaque_person_id": opaque_person_id,
            "private_assignment_record_sha256": private_assignment_record_sha256,
            "identity_evidence_sha256": identity_evidence_sha256,
            "qualification_evidence_sha256": qualification_evidence_sha256,
            "conflict_disclosure_sha256": conflict_disclosure_sha256,
            "role_consent_sha256": role_consent_sha256,
            "owner_verification_attestation_sha256": (
                owner_verification_attestation_sha256
            ),
            "owner_verified_natural_person": True,
            "material_conflict_declared": False,
            "automation_claims_natural_personhood": False,
            "automation_supplied_private_values": False,
            "formal_census_authorized": False,
            "accepted_at": normalized_accepted_at,
        }
        return cls.model_validate(_addressed_payload(payload, "receipt_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"receipt_hash"}))


class HumanRoleStructuralValidation(KernelContract):
    """Automation result that deliberately stops before human authorization."""

    schema_version: Literal["benchmark-human-role-structural-validation-v1"] = (
        "benchmark-human-role-structural-validation-v1"
    )
    protocol_hash: Sha256
    handoff_hash: Sha256
    assignment_receipt_hashes: list[Sha256]
    role_person_ids: dict[HumanReviewRole, StableId]
    schema_hashes_valid: Literal[True] = True
    exact_roles_present: Literal[True] = True
    pairwise_distinct_opaque_ids: Literal[True] = True
    pairwise_distinct_private_records: Literal[True] = True
    automation_can_establish_natural_personhood: Literal[False] = False
    automation_can_establish_truthfulness: Literal[False] = False
    human_owner_authorization_required: Literal[True] = True
    formal_census_authorized: Literal[False] = False
    validation_hash: Sha256

    @field_validator("assignment_receipt_hashes")
    @classmethod
    def _sort_hashes(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("assignment receipt hashes must be unique")
        return normalized

    @field_validator("role_person_ids")
    @classmethod
    def _sort_role_ids(
        cls, value: dict[HumanReviewRole, str]
    ) -> dict[HumanReviewRole, str]:
        return dict(sorted(value.items(), key=lambda item: item[0].value))

    @model_validator(mode="after")
    def _validate_validation(self) -> HumanRoleStructuralValidation:
        if set(self.role_person_ids) != set(HumanReviewRole):
            raise ValueError("structural validation must cover all human roles")
        if len(set(self.role_person_ids.values())) != 3:
            raise ValueError("all three roles must use distinct opaque people")
        if self.validation_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("structural validation hash mismatch")
        return self

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"validation_hash"}))


def validate_human_role_assignments(
    assignments: Sequence[HumanRoleAssignmentReceipt],
    *,
    handoff: BenchmarkHumanReviewHandoff,
) -> HumanRoleStructuralValidation:
    """Validate future receipts structurally without claiming that identities are true."""

    handoff.verify_integrity()
    checked = [
        HumanRoleAssignmentReceipt.model_validate(item.model_dump(mode="json"))
        for item in assignments
    ]
    if {item.role for item in checked} != set(HumanReviewRole) or len(checked) != 3:
        raise ValueError("exactly reviewer-a, reviewer-b, and adjudicator are required")
    if len({item.opaque_person_id for item in checked}) != 3:
        raise ValueError("human roles must use pairwise distinct opaque person IDs")
    if len({item.private_assignment_record_sha256 for item in checked}) != 3:
        raise ValueError("human roles must bind distinct private assignment records")
    if any(item.protocol_hash != handoff.parent_erratum.protocol_hash for item in checked):
        raise ValueError("human assignments are not bound to the frozen protocol")
    if any(item.handoff_hash != handoff.handoff_hash for item in checked):
        raise ValueError("human assignments are not bound to this handoff")
    requirements = {item.role: item.requirement_hash for item in handoff.role_requirements}
    packets = {item.role: item.packet_hash for item in handoff.packet_templates}
    if any(item.role_requirement_hash != requirements[item.role] for item in checked):
        raise ValueError("human assignment role policy binding changed")
    if any(item.packet_template_hash != packets[item.role] for item in checked):
        raise ValueError("human assignment packet binding changed")
    if any(item.accepted_at < handoff.frozen_at for item in checked):
        raise ValueError("human assignment predates the frozen handoff")
    payload = {
        "schema_version": "benchmark-human-role-structural-validation-v1",
        "protocol_hash": handoff.parent_erratum.protocol_hash,
        "handoff_hash": handoff.handoff_hash,
        "assignment_receipt_hashes": sorted(item.receipt_hash for item in checked),
        "role_person_ids": {item.role: item.opaque_person_id for item in checked},
        "schema_hashes_valid": True,
        "exact_roles_present": True,
        "pairwise_distinct_opaque_ids": True,
        "pairwise_distinct_private_records": True,
        "automation_can_establish_natural_personhood": False,
        "automation_can_establish_truthfulness": False,
        "human_owner_authorization_required": True,
        "formal_census_authorized": False,
    }
    return HumanRoleStructuralValidation.model_validate(
        _addressed_payload(payload, "validation_hash")
    )


class ReviewerLockReceipt(KernelContract):
    """Future digest-only lock; reviewer decisions remain in private workspaces."""

    schema_version: Literal["benchmark-reviewer-lock-receipt-v1"] = (
        "benchmark-reviewer-lock-receipt-v1"
    )
    protocol_hash: Sha256
    handoff_hash: Sha256
    role: Literal[HumanReviewRole.REVIEWER_A, HumanReviewRole.REVIEWER_B]
    opaque_person_id: StableId
    assignment_receipt_hash: Sha256
    packet_hash: Sha256
    candidate_set_sha256: Sha256
    screening_work_sha256: Sha256
    critical_coding_work_sha256: Sha256
    peer_work_seen_before_lock: Literal[False] = False
    lock_append_only_and_irrevocable: Literal[True] = True
    locked_at: datetime
    lock_hash: Sha256

    @field_validator("locked_at")
    @classmethod
    def _locked_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="reviewer lock time")

    @model_validator(mode="after")
    def _validate_lock(self) -> ReviewerLockReceipt:
        if self.lock_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("reviewer lock hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        handoff: BenchmarkHumanReviewHandoff,
        assignment: HumanRoleAssignmentReceipt,
        candidate_set_sha256: str,
        screening_work_sha256: str,
        critical_coding_work_sha256: str,
        locked_at: datetime,
    ) -> ReviewerLockReceipt:
        handoff.verify_integrity()
        checked_assignment = HumanRoleAssignmentReceipt.model_validate(
            assignment.model_dump(mode="json")
        )
        if checked_assignment.role not in {
            HumanReviewRole.REVIEWER_A,
            HumanReviewRole.REVIEWER_B,
        }:
            raise ValueError("reviewer lock needs a reviewer assignment")
        if checked_assignment.handoff_hash != handoff.handoff_hash:
            raise ValueError("reviewer assignment is not bound to this handoff")
        expected_packet = next(
            item.packet_hash
            for item in handoff.packet_templates
            if item.role is checked_assignment.role
        )
        if checked_assignment.packet_template_hash != expected_packet:
            raise ValueError("reviewer assignment packet binding changed")
        normalized_locked_at = _utc(locked_at, label="reviewer lock time")
        if normalized_locked_at < checked_assignment.accepted_at:
            raise ValueError("reviewer lock cannot precede role acceptance")
        payload = {
            "schema_version": "benchmark-reviewer-lock-receipt-v1",
            "protocol_hash": handoff.parent_erratum.protocol_hash,
            "handoff_hash": handoff.handoff_hash,
            "role": checked_assignment.role,
            "opaque_person_id": checked_assignment.opaque_person_id,
            "assignment_receipt_hash": checked_assignment.receipt_hash,
            "packet_hash": expected_packet,
            "candidate_set_sha256": candidate_set_sha256,
            "screening_work_sha256": screening_work_sha256,
            "critical_coding_work_sha256": critical_coding_work_sha256,
            "peer_work_seen_before_lock": False,
            "lock_append_only_and_irrevocable": True,
            "locked_at": normalized_locked_at,
        }
        return cls.model_validate(_addressed_payload(payload, "lock_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"lock_hash"}))


class DualLockBarrierReceipt(KernelContract):
    """Future barrier proving both independent digest streams locked first."""

    schema_version: Literal["benchmark-dual-reviewer-lock-barrier-v1"] = (
        "benchmark-dual-reviewer-lock-barrier-v1"
    )
    protocol_hash: Sha256
    handoff_hash: Sha256
    candidate_set_sha256: Sha256
    reviewer_lock_hashes: list[Sha256]
    reviewer_person_ids: list[StableId]
    both_reviewers_locked: Literal[True] = True
    candidate_set_match: Literal[True] = True
    pairwise_distinct_reviewers: Literal[True] = True
    conflicts_may_now_be_derived: Literal[True] = True
    peer_codes_remain_hidden_from_reviewers: Literal[True] = True
    created_at: datetime
    barrier_hash: Sha256

    @field_validator("reviewer_lock_hashes", "reviewer_person_ids")
    @classmethod
    def _sort_unique_barrier_values(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != 2 or len(set(normalized)) != 2:
            raise ValueError("dual lock barrier needs two distinct values")
        return normalized

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="dual lock barrier time")

    @model_validator(mode="after")
    def _validate_barrier(self) -> DualLockBarrierReceipt:
        if self.barrier_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("dual lock barrier hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        locks: Sequence[ReviewerLockReceipt],
        created_at: datetime,
    ) -> DualLockBarrierReceipt:
        checked = [ReviewerLockReceipt.model_validate(item.model_dump(mode="json")) for item in locks]
        if len(checked) != 2 or {item.role for item in checked} != {
            HumanReviewRole.REVIEWER_A,
            HumanReviewRole.REVIEWER_B,
        }:
            raise ValueError("dual lock barrier needs one lock from each reviewer")
        if len({item.opaque_person_id for item in checked}) != 2:
            raise ValueError("reviewer locks must belong to distinct people")
        if len({item.assignment_receipt_hash for item in checked}) != 2:
            raise ValueError("reviewer locks must bind distinct assignments")
        if len({item.protocol_hash for item in checked}) != 1:
            raise ValueError("reviewer locks must bind the same frozen protocol")
        if len({item.handoff_hash for item in checked}) != 1:
            raise ValueError("reviewer locks must bind the same human handoff")
        candidate_sets = {item.candidate_set_sha256 for item in checked}
        if len(candidate_sets) != 1:
            raise ValueError("reviewer locks must cover the same candidate set")
        normalized_created_at = _utc(created_at, label="dual lock barrier time")
        if normalized_created_at < max(item.locked_at for item in checked):
            raise ValueError("dual lock barrier cannot precede either reviewer lock")
        payload = {
            "schema_version": "benchmark-dual-reviewer-lock-barrier-v1",
            "protocol_hash": checked[0].protocol_hash,
            "handoff_hash": checked[0].handoff_hash,
            "candidate_set_sha256": next(iter(candidate_sets)),
            "reviewer_lock_hashes": sorted(item.lock_hash for item in checked),
            "reviewer_person_ids": sorted(item.opaque_person_id for item in checked),
            "both_reviewers_locked": True,
            "candidate_set_match": True,
            "pairwise_distinct_reviewers": True,
            "conflicts_may_now_be_derived": True,
            "peer_codes_remain_hidden_from_reviewers": True,
            "created_at": normalized_created_at,
        }
        return cls.model_validate(_addressed_payload(payload, "barrier_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"barrier_hash"}))


class AdjudicatorAccessReceipt(KernelContract):
    """Future conflict-only access opened after a valid dual-lock barrier."""

    schema_version: Literal["benchmark-adjudicator-access-receipt-v1"] = (
        "benchmark-adjudicator-access-receipt-v1"
    )
    protocol_hash: Sha256
    handoff_hash: Sha256
    adjudicator_person_id: StableId
    adjudicator_assignment_receipt_hash: Sha256
    dual_lock_barrier_hash: Sha256
    conflict_index_sha256: Sha256
    access_before_dual_lock: Literal[False] = False
    non_conflict_codes_visible: Literal[False] = False
    agreement_or_coverage_failure_repair_authorized: Literal[False] = False
    opened_at: datetime
    access_hash: Sha256

    @field_validator("opened_at")
    @classmethod
    def _opened_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="adjudicator access time")

    @model_validator(mode="after")
    def _validate_access(self) -> AdjudicatorAccessReceipt:
        if self.access_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("adjudicator access hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        adjudicator_assignment: HumanRoleAssignmentReceipt,
        barrier: DualLockBarrierReceipt,
        conflict_index_sha256: str,
        opened_at: datetime,
    ) -> AdjudicatorAccessReceipt:
        checked_assignment = HumanRoleAssignmentReceipt.model_validate(
            adjudicator_assignment.model_dump(mode="json")
        )
        if checked_assignment.role is not HumanReviewRole.ADJUDICATOR:
            raise ValueError("adjudicator access needs the adjudicator assignment")
        checked_barrier = DualLockBarrierReceipt.model_validate(barrier.model_dump(mode="json"))
        if checked_assignment.protocol_hash != checked_barrier.protocol_hash:
            raise ValueError("adjudicator and reviewers are not bound to the same protocol")
        if checked_assignment.handoff_hash != checked_barrier.handoff_hash:
            raise ValueError("adjudicator and reviewers are not bound to the same handoff")
        if checked_assignment.opaque_person_id in checked_barrier.reviewer_person_ids:
            raise ValueError("adjudicator must be distinct from both reviewers")
        normalized_opened_at = _utc(opened_at, label="adjudicator access time")
        if normalized_opened_at < checked_barrier.created_at:
            raise ValueError("adjudicator access cannot open before dual lock")
        payload = {
            "schema_version": "benchmark-adjudicator-access-receipt-v1",
            "protocol_hash": checked_barrier.protocol_hash,
            "handoff_hash": checked_barrier.handoff_hash,
            "adjudicator_person_id": checked_assignment.opaque_person_id,
            "adjudicator_assignment_receipt_hash": checked_assignment.receipt_hash,
            "dual_lock_barrier_hash": checked_barrier.barrier_hash,
            "conflict_index_sha256": conflict_index_sha256,
            "access_before_dual_lock": False,
            "non_conflict_codes_visible": False,
            "agreement_or_coverage_failure_repair_authorized": False,
            "opened_at": normalized_opened_at,
        }
        return cls.model_validate(_addressed_payload(payload, "access_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"access_hash"}))


class BenchmarkHumanReviewHandoff(KernelContract):
    """Complete empty handoff ceremony frozen before human enrollment."""

    schema_version: Literal["benchmark-human-review-handoff-v1"] = (
        "benchmark-human-review-handoff-v1"
    )
    task_id: Literal["263.6.7.2.2"] = "263.6.7.2.2"
    status: Literal["frozen-result-blind-human-handoff"] = (
        "frozen-result-blind-human-handoff"
    )
    parent_erratum: ParentPaginationErratumEvidence
    frozen_at: datetime
    role_requirements: list[HumanRoleRequirement] = Field(min_length=3, max_length=3)
    private_assignment_fields: list[PrivateAssignmentFieldSpec] = Field(
        min_length=7, max_length=7
    )
    public_role_slots: list[PublicHumanRoleSlot] = Field(min_length=3, max_length=3)
    packet_templates: list[BlindedReviewPacketTemplate] = Field(min_length=3, max_length=3)
    stage_transitions: list[HumanHandoffTransition] = Field(min_length=5, max_length=5)
    dual_lock_policy: DualReviewerLockPolicy
    current_stage: Literal[HumanHandoffStage.UNASSIGNED] = HumanHandoffStage.UNASSIGNED
    actual_human_identity_count: Literal[0] = 0
    role_assignment_count: Literal[0] = 0
    review_packet_issued_count: Literal[0] = 0
    review_lock_count: Literal[0] = 0
    adjudicator_access_count: Literal[0] = 0
    formal_search_execution_count: Literal[0] = 0
    screening_record_count: Literal[0] = 0
    critical_coding_record_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    human_roles_assigned: Literal[False] = False
    formal_census_authorized: Literal[False] = False
    automation_can_establish_natural_personhood: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    publication_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    next_action: Literal["project-owner-enrolls-three-real-humans"] = (
        "project-owner-enrolls-three-real-humans"
    )
    handoff_hash: Sha256

    @field_validator("frozen_at")
    @classmethod
    def _frozen_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="human handoff freeze time")

    @field_validator("role_requirements", "public_role_slots", "packet_templates")
    @classmethod
    def _sort_role_contracts(cls, value: list[Any]) -> list[Any]:
        normalized = sorted(value, key=lambda item: item.role.value)
        if {item.role.value for item in normalized} != REQUIRED_ROLE_IDS:
            raise ValueError("human handoff role contracts must cover exactly three roles")
        return normalized

    @field_validator("private_assignment_fields")
    @classmethod
    def _sort_private_fields(
        cls, value: list[PrivateAssignmentFieldSpec]
    ) -> list[PrivateAssignmentFieldSpec]:
        normalized = sorted(value, key=lambda item: item.field_id)
        if {item.field_id for item in normalized} != REQUIRED_PRIVATE_FIELD_IDS:
            raise ValueError("private assignment field inventory changed")
        return normalized

    @field_validator("stage_transitions")
    @classmethod
    def _sort_transitions(
        cls, value: list[HumanHandoffTransition]
    ) -> list[HumanHandoffTransition]:
        normalized = sorted(value, key=lambda item: item.transition_id)
        if {item.transition_id for item in normalized} != REQUIRED_TRANSITION_IDS:
            raise ValueError("human handoff state machine changed")
        return normalized

    @model_validator(mode="after")
    def _validate_handoff(
        self, info: ValidationInfo
    ) -> BenchmarkHumanReviewHandoff:
        if self.parent_erratum.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
            raise ValueError("handoff is not bound to the frozen benchmark protocol")
        if any(item.status is not RoleSlotStatus.UNASSIGNED for item in self.public_role_slots):
            raise ValueError("the frozen handoff cannot contain assigned human roles")
        skip_hash = bool(info.context and info.context.get("skip_hash"))
        if not skip_hash and self.handoff_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("human handoff hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkHumanReviewHandoff:
        payload = {
            "schema_version": "benchmark-human-review-handoff-v1",
            "task_id": "263.6.7.2.2",
            "status": "frozen-result-blind-human-handoff",
            "current_stage": HumanHandoffStage.UNASSIGNED,
            "actual_human_identity_count": 0,
            "role_assignment_count": 0,
            "review_packet_issued_count": 0,
            "review_lock_count": 0,
            "adjudicator_access_count": 0,
            "formal_search_execution_count": 0,
            "screening_record_count": 0,
            "critical_coding_record_count": 0,
            "admission_card_count": 0,
            "human_roles_assigned": False,
            "formal_census_authorized": False,
            "automation_can_establish_natural_personhood": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "publication_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "next_action": "project-owner-enrolls-three-real-humans",
            **values,
        }
        normalized = cls.model_validate(
            {**payload, "handoff_hash": "0" * 64},
            context={"skip_hash": True},
        )
        normalized_payload = normalized.model_dump(mode="json", exclude={"handoff_hash"})
        normalized_payload["handoff_hash"] = canonical_sha256(normalized_payload)
        return cls.model_validate(normalized_payload)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"handoff_hash"}))

    def verify_integrity(self) -> None:
        if self.handoff_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("human handoff hash mismatch")


class HumanReviewHandoffProjection(KernelContract):
    """Minimal result-free contract replayed in two clean interpreters."""

    schema_version: Literal["benchmark-human-review-handoff-projection-v1"] = (
        "benchmark-human-review-handoff-projection-v1"
    )
    task_id: Literal["263.6.7.2.2"] = "263.6.7.2.2"
    status: Literal["frozen-result-blind-human-handoff"] = (
        "frozen-result-blind-human-handoff"
    )
    protocol_hash: Sha256
    parent_erratum_hash: Sha256
    parent_erratum_report_hash: Sha256
    parent_erratum_projection_hash: Sha256
    parent_erratum_manifest_hash: Sha256
    handoff_hash: Sha256
    role_ids: list[StableId]
    role_slot_statuses: dict[StableId, Literal["unassigned"]]
    role_requirement_hashes: dict[StableId, Sha256]
    private_assignment_field_count: Literal[7] = 7
    private_field_spec_hashes: list[Sha256]
    packet_template_hashes: dict[StableId, Sha256]
    stage_transition_count: Literal[5] = 5
    transition_hashes: list[Sha256]
    dual_lock_policy_hash: Sha256
    current_stage: Literal["unassigned"] = "unassigned"
    actual_human_identity_count: Literal[0] = 0
    role_assignment_count: Literal[0] = 0
    review_packet_issued_count: Literal[0] = 0
    review_lock_count: Literal[0] = 0
    adjudicator_access_count: Literal[0] = 0
    formal_search_execution_count: Literal[0] = 0
    screening_record_count: Literal[0] = 0
    critical_coding_record_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    human_roles_assigned: Literal[False] = False
    formal_census_authorized: Literal[False] = False
    automation_can_establish_natural_personhood: Literal[False] = False
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    publication_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    next_action: Literal["project-owner-enrolls-three-real-humans"] = (
        "project-owner-enrolls-three-real-humans"
    )
    projection_sha256: Sha256

    @field_validator("role_ids", "private_field_spec_hashes", "transition_hashes")
    @classmethod
    def _sort_projection_lists(cls, value: list[str]) -> list[str]:
        normalized = sorted(value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("handoff projection lists must be unique")
        return normalized

    @field_validator(
        "role_slot_statuses",
        "role_requirement_hashes",
        "packet_template_hashes",
    )
    @classmethod
    def _sort_projection_mappings(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_projection(
        self, info: ValidationInfo
    ) -> HumanReviewHandoffProjection:
        if set(self.role_ids) != REQUIRED_ROLE_IDS:
            raise ValueError("handoff projection requires exactly three role IDs")
        if self.role_slot_statuses != {role: "unassigned" for role in sorted(REQUIRED_ROLE_IDS)}:
            raise ValueError("handoff projection roles must remain unassigned")
        if set(self.role_requirement_hashes) != REQUIRED_ROLE_IDS:
            raise ValueError("role requirement hashes must cover all roles")
        if set(self.packet_template_hashes) != REQUIRED_ROLE_IDS:
            raise ValueError("packet template hashes must cover all roles")
        _walk_forbidden(self.runner_projection())
        skip_hash = bool(info.context and info.context.get("skip_hash"))
        if not skip_hash and self.projection_sha256 != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("handoff projection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HumanReviewHandoffProjection:
        payload = {
            "schema_version": "benchmark-human-review-handoff-projection-v1",
            "task_id": "263.6.7.2.2",
            "status": "frozen-result-blind-human-handoff",
            "private_assignment_field_count": 7,
            "stage_transition_count": 5,
            "current_stage": "unassigned",
            "actual_human_identity_count": 0,
            "role_assignment_count": 0,
            "review_packet_issued_count": 0,
            "review_lock_count": 0,
            "adjudicator_access_count": 0,
            "formal_search_execution_count": 0,
            "screening_record_count": 0,
            "critical_coding_record_count": 0,
            "admission_card_count": 0,
            "human_roles_assigned": False,
            "formal_census_authorized": False,
            "automation_can_establish_natural_personhood": False,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "publication_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "next_action": "project-owner-enrolls-three-real-humans",
            **values,
        }
        normalized = cls.model_validate(
            {**payload, "projection_sha256": "0" * 64},
            context={"skip_hash": True},
        )
        runner_projection = normalized.model_dump(mode="json", exclude={"projection_sha256"})
        runner_projection["projection_sha256"] = canonical_sha256(runner_projection)
        return cls.model_validate(runner_projection)

    def calculated_hash(self) -> str:
        return canonical_sha256(self.runner_projection())

    def runner_projection(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"projection_sha256"})


class HumanHandoffReplayObservation(KernelContract):
    schema_version: Literal["benchmark-human-handoff-replay-observation-v1"] = (
        "benchmark-human-handoff-replay-observation-v1"
    )
    runtime: InterpreterRuntime
    projection_sha256: Sha256
    output_file_sha256: Sha256
    output_contract_sha256: Sha256
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> HumanHandoffReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("handoff replay observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HumanHandoffReplayObservation:
        payload = {
            "schema_version": "benchmark-human-handoff-replay-observation-v1",
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "observation_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"observation_hash"}))


class HumanHandoffReplayCertificate(KernelContract):
    schema_version: Literal["benchmark-human-handoff-replay-certificate-v1"] = (
        "benchmark-human-handoff-replay-certificate-v1"
    )
    protocol_hash: Sha256
    handoff_hash: Sha256
    projection_sha256: Sha256
    replay_input_sha256: Sha256
    frozen_runner_sha256: Sha256
    observations: list[HumanHandoffReplayObservation] = Field(min_length=2, max_length=2)
    exact_projection_match: Literal[True] = True
    distinct_interpreter_installations: Literal[True] = True
    output_contract_match: Literal[True] = True
    certificate_hash: Sha256

    @field_validator("observations")
    @classmethod
    def _sort_observations(
        cls, value: list[HumanHandoffReplayObservation]
    ) -> list[HumanHandoffReplayObservation]:
        return sorted(value, key=lambda item: item.runtime.role_id)

    @model_validator(mode="after")
    def _validate_certificate(self) -> HumanHandoffReplayCertificate:
        if {item.runtime.role_id for item in self.observations} != {
            "clean-runtime-a",
            "clean-runtime-b",
        }:
            raise ValueError("handoff replay requires two clean runtime roles")
        if any(item.projection_sha256 != self.projection_sha256 for item in self.observations):
            raise ValueError("handoff replay projections differ")
        if len({item.runtime.executable_locator_hash for item in self.observations}) != 2:
            raise ValueError("handoff replay needs distinct interpreter installations")
        if len({item.output_contract_sha256 for item in self.observations}) != 1:
            raise ValueError("handoff replay output contracts differ")
        if self.certificate_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("handoff replay certificate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HumanHandoffReplayCertificate:
        payload = {
            "schema_version": "benchmark-human-handoff-replay-certificate-v1",
            "exact_projection_match": True,
            "distinct_interpreter_installations": True,
            "output_contract_match": True,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "certificate_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"certificate_hash"}))


class BenchmarkHumanReviewHandoffReport(KernelContract):
    schema_version: Literal["benchmark-human-review-handoff-report-v1"] = (
        "benchmark-human-review-handoff-report-v1"
    )
    task_id: Literal["263.6.7.2.2"] = "263.6.7.2.2"
    status: Literal["frozen-result-blind-human-handoff"] = (
        "frozen-result-blind-human-handoff"
    )
    parent_git_commit: StableId
    built_at: datetime
    handoff_source_sha256: Sha256
    frozen_runner_sha256: Sha256
    handoff: BenchmarkHumanReviewHandoff
    projection: HumanReviewHandoffProjection
    replay_certificate: HumanHandoffReplayCertificate
    formal_search_execution_count: Literal[0] = 0
    screening_record_count: Literal[0] = 0
    critical_coding_record_count: Literal[0] = 0
    actual_human_identity_count: Literal[0] = 0
    role_assignment_count: Literal[0] = 0
    review_lock_count: Literal[0] = 0
    adjudicator_access_count: Literal[0] = 0
    admission_card_count: Literal[0] = 0
    benchmark_outcomes_accessed: Literal[False] = False
    candidate_model_calls: Literal[False] = False
    formal_census_authorized: Literal[False] = False
    publication_claim_authorized: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    next_action: Literal["project-owner-enrolls-three-real-humans"] = (
        "project-owner-enrolls-three-real-humans"
    )
    report_hash: Sha256

    @field_validator("built_at")
    @classmethod
    def _built_at_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="handoff report time")

    @model_validator(mode="after")
    def _validate_report(self) -> BenchmarkHumanReviewHandoffReport:
        if self.parent_git_commit != PARENT_ERRATUM_COMMIT:
            raise ValueError("handoff report must parent the completed erratum commit")
        if self.handoff.handoff_hash != self.projection.handoff_hash:
            raise ValueError("handoff projection is not bound to the handoff")
        if self.projection.projection_sha256 != self.replay_certificate.projection_sha256:
            raise ValueError("handoff replay is not bound to the projection")
        if self.handoff.handoff_hash != self.replay_certificate.handoff_hash:
            raise ValueError("handoff replay is not bound to the handoff")
        if self.frozen_runner_sha256 != self.replay_certificate.frozen_runner_sha256:
            raise ValueError("handoff report runner hash differs from replay")
        if self.report_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("handoff report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> BenchmarkHumanReviewHandoffReport:
        payload = {
            "schema_version": "benchmark-human-review-handoff-report-v1",
            "task_id": "263.6.7.2.2",
            "status": "frozen-result-blind-human-handoff",
            "formal_search_execution_count": 0,
            "screening_record_count": 0,
            "critical_coding_record_count": 0,
            "actual_human_identity_count": 0,
            "role_assignment_count": 0,
            "review_lock_count": 0,
            "adjudicator_access_count": 0,
            "admission_card_count": 0,
            "benchmark_outcomes_accessed": False,
            "candidate_model_calls": False,
            "formal_census_authorized": False,
            "publication_claim_authorized": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
            "next_action": "project-owner-enrolls-three-real-humans",
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class HumanReviewHandoffManifest(KernelContract):
    schema_version: Literal["benchmark-human-review-handoff-manifest-v1"] = (
        "benchmark-human-review-handoff-manifest-v1"
    )
    protocol_hash: Sha256
    parent_erratum_hash: Sha256
    handoff_hash: Sha256
    report_hash: Sha256
    projection_sha256: Sha256
    replay_certificate_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    manifest_hash: Sha256

    @field_validator("files")
    @classmethod
    def _sort_files(cls, value: dict[str, str]) -> dict[str, str]:
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def _validate_manifest(self) -> HumanReviewHandoffManifest:
        if self.manifest_hash != self.calculated_hash():
            raise HumanReviewHandoffIntegrityError("handoff manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> HumanReviewHandoffManifest:
        payload = {
            "schema_version": "benchmark-human-review-handoff-manifest-v1",
            **values,
            "files": dict(sorted(values["files"].items())),
        }
        return cls.model_validate(_addressed_payload(payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


HANDOFF_CONTRACT_MODELS = (
    ParentPaginationErratumEvidence,
    HumanRoleRequirement,
    PrivateAssignmentFieldSpec,
    PublicHumanRoleSlot,
    BlindedReviewPacketTemplate,
    HumanHandoffTransition,
    DualReviewerLockPolicy,
    HumanRoleAssignmentReceipt,
    HumanRoleStructuralValidation,
    ReviewerLockReceipt,
    DualLockBarrierReceipt,
    AdjudicatorAccessReceipt,
    BenchmarkHumanReviewHandoff,
    HumanReviewHandoffProjection,
    HumanHandoffReplayObservation,
    HumanHandoffReplayCertificate,
    BenchmarkHumanReviewHandoffReport,
    HumanReviewHandoffManifest,
)


def human_review_handoff_json_schemas() -> dict[str, dict[str, Any]]:
    return {model.__name__: model.model_json_schema() for model in HANDOFF_CONTRACT_MODELS}


def _private_assignment_field_specs() -> list[PrivateAssignmentFieldSpec]:
    definitions = {
        "opaque-person-id": (
            "Owner-generated, non-name identifier used only to enforce pairwise role distinctness.",
            PublicProjectionPolicy.OPAQUE_IDENTIFIER_ONLY,
        ),
        "identity-evidence-artifact": (
            "Private evidence by which the project owner verified a natural person's identity.",
            PublicProjectionPolicy.SHA256_ONLY,
        ),
        "qualification-evidence-artifact": (
            "Private evidence of the role-specific methodological or domain qualifications.",
            PublicProjectionPolicy.SHA256_ONLY,
        ),
        "conflict-disclosure-artifact": (
            "Private signed disclosure covering affiliations, benchmark authorship, and other conflicts.",
            PublicProjectionPolicy.SHA256_ONLY,
        ),
        "role-consent-artifact": (
            "Private evidence that the person accepted the role, blinding, lock, and no-legal-opinion rules.",
            PublicProjectionPolicy.SHA256_ONLY,
        ),
        "owner-verification-attestation": (
            "Private project-owner attestation that enrollment evidence was reviewed outside automation.",
            PublicProjectionPolicy.SHA256_ONLY,
        ),
        "private-assignment-record": (
            "Complete private enrollment record; repository artifacts retain only its content hash.",
            PublicProjectionPolicy.SHA256_ONLY,
        ),
    }
    return [
        PrivateAssignmentFieldSpec.create(
            field_id=field_id,
            definition=definition,
            public_projection_policy=policy,
        )
        for field_id, (definition, policy) in definitions.items()
    ]


def _stage_transitions() -> list[HumanHandoffTransition]:
    return [
        HumanHandoffTransition.create(
            transition_id="unassigned-to-owner-verified",
            from_stage=HumanHandoffStage.UNASSIGNED,
            to_stage=HumanHandoffStage.OWNER_VERIFIED,
            precondition=(
                "The project owner privately verifies three natural persons, qualifications, "
                "conflict disclosures, consent, and pairwise-distinct opaque identifiers."
            ),
            human_action_required=True,
        ),
        HumanHandoffTransition.create(
            transition_id="assign-to-reviewer-packets",
            from_stage=HumanHandoffStage.OWNER_VERIFIED,
            to_stage=HumanHandoffStage.REVIEWER_PACKETS_ISSUED,
            precondition=(
                "A human owner explicitly authorizes the structurally validated assignments; "
                "reviewer packets expose neither peer codes nor benchmark outcomes."
            ),
            human_action_required=True,
        ),
        HumanHandoffTransition.create(
            transition_id="reviewer-packets-to-dual-lock",
            from_stage=HumanHandoffStage.REVIEWER_PACKETS_ISSUED,
            to_stage=HumanHandoffStage.DUAL_LOCKED,
            precondition=(
                "Both reviewers independently lock screening and critical coding digests over "
                "the identical candidate-set commitment without peer-work access."
            ),
            human_action_required=True,
        ),
        HumanHandoffTransition.create(
            transition_id="dual-lock-to-adjudicator",
            from_stage=HumanHandoffStage.DUAL_LOCKED,
            to_stage=HumanHandoffStage.ADJUDICATOR_OPEN,
            precondition=(
                "A valid dual-lock barrier exists; only the distinct adjudicator receives the "
                "locked conflict index and supporting source evidence."
            ),
            human_action_required=True,
        ),
        HumanHandoffTransition.create(
            transition_id="adjudicator-to-synthesis-gate",
            from_stage=HumanHandoffStage.ADJUDICATOR_OPEN,
            to_stage=HumanHandoffStage.SYNTHESIS_GATE,
            precondition=(
                "Human adjudication is complete and the preregistered pre-adjudication "
                "agreement and coverage gates are evaluated without repair by adjudication."
            ),
            human_action_required=True,
        ),
    ]


def build_human_review_handoff(
    *,
    protocol: BenchmarkValidityProtocol,
    parent_erratum: ParentPaginationErratumEvidence,
    frozen_at: datetime,
) -> BenchmarkHumanReviewHandoff:
    protocol.verify_integrity()
    if protocol.protocol_hash != FROZEN_BENCHMARK_VALIDITY_PROTOCOL_HASH:
        raise HumanReviewHandoffIntegrityError("unexpected benchmark-validity protocol")
    if protocol.human_coding_plan.actual_human_identities_assigned:
        raise HumanReviewHandoffIntegrityError("protocol unexpectedly contains human identities")
    checked_parent = ParentPaginationErratumEvidence.model_validate(
        parent_erratum.model_dump(mode="json")
    )
    if checked_parent.protocol_hash != protocol.protocol_hash:
        raise HumanReviewHandoffIntegrityError("handoff parent/protocol mismatch")
    roles = list(HumanReviewRole)
    return BenchmarkHumanReviewHandoff.create(
        parent_erratum=checked_parent,
        frozen_at=frozen_at,
        role_requirements=[HumanRoleRequirement.create(role) for role in roles],
        private_assignment_fields=_private_assignment_field_specs(),
        public_role_slots=[PublicHumanRoleSlot.create(role) for role in roles],
        packet_templates=[BlindedReviewPacketTemplate.create(role=role) for role in roles],
        stage_transitions=_stage_transitions(),
        dual_lock_policy=DualReviewerLockPolicy.from_human_coding_plan(
            protocol.human_coding_plan
        ),
    )


def build_human_review_handoff_projection(
    handoff: BenchmarkHumanReviewHandoff,
) -> HumanReviewHandoffProjection:
    handoff.verify_integrity()
    projection = HumanReviewHandoffProjection.create(
        protocol_hash=handoff.parent_erratum.protocol_hash,
        parent_erratum_hash=handoff.parent_erratum.erratum_hash,
        parent_erratum_report_hash=handoff.parent_erratum.report_hash,
        parent_erratum_projection_hash=handoff.parent_erratum.projection_sha256,
        parent_erratum_manifest_hash=handoff.parent_erratum.manifest_hash,
        handoff_hash=handoff.handoff_hash,
        role_ids=[item.role.value for item in handoff.public_role_slots],
        role_slot_statuses={item.role.value: item.status.value for item in handoff.public_role_slots},
        role_requirement_hashes={
            item.role.value: item.requirement_hash for item in handoff.role_requirements
        },
        private_field_spec_hashes=[
            item.field_spec_hash for item in handoff.private_assignment_fields
        ],
        packet_template_hashes={
            item.role.value: item.packet_hash for item in handoff.packet_templates
        },
        transition_hashes=[item.transition_hash for item in handoff.stage_transitions],
        dual_lock_policy_hash=handoff.dual_lock_policy.policy_hash,
    )
    _walk_forbidden(projection.runner_projection())
    return projection


def build_human_review_handoff_replay_payload(
    projection: HumanReviewHandoffProjection,
) -> dict[str, Any]:
    runner_projection = projection.runner_projection()
    return {
        "expected_projection_sha256": canonical_sha256(runner_projection),
        "projection": runner_projection,
    }


def run_human_review_handoff_replay(
    *,
    projection: HumanReviewHandoffProjection,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    work_dir: Path,
) -> HumanHandoffReplayCertificate:
    if set(interpreters) != {"clean-runtime-a", "clean-runtime-b"}:
        raise ValueError("handoff replay requires clean-runtime-a and clean-runtime-b")
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = build_human_review_handoff_replay_payload(projection)
    input_path = work_dir / "benchmark-human-review-handoff-replay-input.json"
    _write_text_atomic(input_path, _canonical_json_text(payload) + "\n")
    observations: list[HumanHandoffReplayObservation] = []
    for role_id, executable in sorted(interpreters.items()):
        runtime = probe_interpreter_runtime(role_id=role_id, executable=executable)
        output_path = work_dir / f"benchmark-human-review-handoff-{role_id}.json"
        completed = subprocess.run(
            [
                str(executable),
                str(runner_path),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ],
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise HumanReviewHandoffIntegrityError(
                f"handoff replay failed for {role_id}: {stderr[:1000]}"
            )
        output = json.loads(output_path.read_text(encoding="utf-8"))
        if output.get("projection_sha256") != projection.projection_sha256:
            raise HumanReviewHandoffIntegrityError(
                f"handoff replay projection mismatch for {role_id}"
            )
        output_contract_hash = str(output.get("output_sha256", ""))
        if len(output_contract_hash) != 64:
            raise HumanReviewHandoffIntegrityError(
                f"handoff replay output hash missing for {role_id}"
            )
        observations.append(
            HumanHandoffReplayObservation.create(
                runtime=runtime,
                projection_sha256=projection.projection_sha256,
                output_file_sha256=_file_sha256(output_path),
                output_contract_sha256=output_contract_hash,
            )
        )
    return HumanHandoffReplayCertificate.create(
        protocol_hash=projection.protocol_hash,
        handoff_hash=projection.handoff_hash,
        projection_sha256=projection.projection_sha256,
        replay_input_sha256=_file_sha256(input_path),
        frozen_runner_sha256=_file_sha256(runner_path),
        observations=observations,
    )


def render_human_review_handoff_markdown(
    report: BenchmarkHumanReviewHandoffReport,
) -> str:
    return "\n".join(
        [
            "# Benchmark-validity human-review handoff",
            "",
            f"- Task: `{report.task_id}`",
            f"- Status: `{report.status}`",
            f"- Parent erratum: `{report.handoff.parent_erratum.erratum_hash}`",
            f"- Handoff: `{report.handoff.handoff_hash}`",
            f"- Projection: `{report.projection.projection_sha256}`",
            f"- Replay: `{report.replay_certificate.certificate_hash}`",
            "- Human identities assigned: `0`",
            "- Formal census authorized: `false`",
            "- Search/screening/coding/adjudicator access: `0/0/0/0`",
            "- Benchmark outcomes/model calls: `false/false`",
            "",
            "## Frozen ceremony",
            "",
            "Two natural-person reviewers must be privately enrolled by the project owner, "
            "work in separate blinded workspaces, and lock screening plus critical coding "
            "digests over the same candidate-set commitment. Neither reviewer sees the "
            "other stream before both locks. A third, distinct natural-person adjudicator "
            "receives only the locked conflict index after the dual-lock barrier.",
            "",
            "Automation validates schemas, hashes, distinct opaque IDs, packet visibility, "
            "and ordering only. It cannot establish personhood, truthfulness, expertise, "
            "conflicts, or consent, and this package does not authorize Task 263.6.7.3.",
            "",
            "Adjudication cannot repair failed pre-adjudication agreement or evidence-coverage "
            "gates. An unlock, recode after peer reveal, early adjudicator access, or identity "
            "reuse forces the registered diagnostic stop.",
            "",
            "## Next action",
            "",
            "The project owner enrolls two independent real reviewers and one distinct real "
            "adjudicator using private evidence, then explicitly authorizes role activation.",
            "",
        ]
    )


def render_owner_enrollment_checklist(handoff: BenchmarkHumanReviewHandoff) -> str:
    handoff.verify_integrity()
    return "\n".join(
        [
            "# Human reviewer enrollment checklist",
            "",
            "This checklist must be completed by the human project owner. Do not ask an Agent "
            "or model to fill, witness, sign, or infer any private value.",
            "",
            "1. Select two natural-person reviewers and one different natural-person adjudicator.",
            "2. Verify role-specific qualifications outside the automated system.",
            "3. Collect signed conflict disclosures and exclude every material conflict.",
            "4. Collect explicit consent to blinding, private workspaces, immutable locks, and "
            "the no-legal-opinion boundary.",
            "5. Create three random opaque person IDs and confirm they are pairwise distinct.",
            "6. Store identity, qualification, conflict, consent, and owner-verification records "
            "outside Git; publish only their SHA-256 digests.",
            "7. Run structural validation. A passing structure is not proof of personhood and "
            "does not authorize the census.",
            "8. Explicitly authorize the assignments as project owner before reviewer packets "
            "are issued.",
            "9. Keep reviewer workspaces isolated until both lock receipts cover the identical "
            "candidate-set commitment.",
            "10. Open only locked conflicts to the adjudicator after the dual-lock barrier.",
            "",
            f"Frozen handoff: `{handoff.handoff_hash}`",
            "",
        ]
    )


def _artifact_file_map(output_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(output_dir).as_posix()
        if relative == HUMAN_HANDOFF_MANIFEST_FILENAME or path.name.startswith("."):
            continue
        files[relative] = _file_sha256(path)
    return files


def write_human_review_handoff(
    output_dir: Path,
    report: BenchmarkHumanReviewHandoffReport,
) -> HumanReviewHandoffManifest:
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_REPORT_FILENAME,
        _canonical_json_text(report.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_PROJECTION_FILENAME,
        _canonical_json_text(report.projection.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_REPLAY_FILENAME,
        _canonical_json_text(report.replay_certificate.model_dump(mode="json")) + "\n",
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_SCHEMA_FILENAME,
        _pretty_json_text(human_review_handoff_json_schemas()),
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_MARKDOWN_FILENAME,
        render_human_review_handoff_markdown(report),
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_ROLE_SLOTS_FILENAME,
        _pretty_json_text([item.model_dump(mode="json") for item in report.handoff.public_role_slots]),
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_PACKET_TEMPLATES_FILENAME,
        _pretty_json_text([item.model_dump(mode="json") for item in report.handoff.packet_templates]),
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_OWNER_CHECKLIST_FILENAME,
        render_owner_enrollment_checklist(report.handoff),
    )
    files = _artifact_file_map(output_dir)
    required = {
        HUMAN_HANDOFF_REPORT_FILENAME,
        HUMAN_HANDOFF_PROJECTION_FILENAME,
        HUMAN_HANDOFF_REPLAY_FILENAME,
        HUMAN_HANDOFF_SCHEMA_FILENAME,
        HUMAN_HANDOFF_MARKDOWN_FILENAME,
        HUMAN_HANDOFF_ROLE_SLOTS_FILENAME,
        HUMAN_HANDOFF_PACKET_TEMPLATES_FILENAME,
        HUMAN_HANDOFF_OWNER_CHECKLIST_FILENAME,
    }
    if missing := sorted(required - set(files)):
        raise HumanReviewHandoffIntegrityError(
            f"human handoff persistence is missing required files: {missing}"
        )
    manifest = HumanReviewHandoffManifest.create(
        protocol_hash=report.handoff.parent_erratum.protocol_hash,
        parent_erratum_hash=report.handoff.parent_erratum.erratum_hash,
        handoff_hash=report.handoff.handoff_hash,
        report_hash=report.report_hash,
        projection_sha256=report.projection.projection_sha256,
        replay_certificate_hash=report.replay_certificate.certificate_hash,
        files=files,
    )
    _write_text_atomic(
        output_dir / HUMAN_HANDOFF_MANIFEST_FILENAME,
        _canonical_json_text(manifest.model_dump(mode="json")) + "\n",
    )
    return manifest


def load_human_review_handoff(
    output_dir: Path,
) -> tuple[BenchmarkHumanReviewHandoffReport, HumanReviewHandoffManifest]:
    manifest = HumanReviewHandoffManifest.model_validate_json(
        (output_dir / HUMAN_HANDOFF_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    actual = _artifact_file_map(output_dir)
    if set(actual) != set(manifest.files):
        raise HumanReviewHandoffIntegrityError("human handoff artifact inventory changed")
    for relative, expected in manifest.files.items():
        if actual[relative] != expected:
            raise HumanReviewHandoffIntegrityError(
                f"human handoff artifact hash mismatch: {relative}"
            )
    report = BenchmarkHumanReviewHandoffReport.model_validate_json(
        (output_dir / HUMAN_HANDOFF_REPORT_FILENAME).read_text(encoding="utf-8")
    )
    if report.report_hash != manifest.report_hash:
        raise HumanReviewHandoffIntegrityError("handoff manifest/report binding mismatch")
    if report.handoff.handoff_hash != manifest.handoff_hash:
        raise HumanReviewHandoffIntegrityError("handoff manifest/protocol binding mismatch")
    if report.projection.projection_sha256 != manifest.projection_sha256:
        raise HumanReviewHandoffIntegrityError("handoff manifest/projection binding mismatch")
    if report.replay_certificate.certificate_hash != manifest.replay_certificate_hash:
        raise HumanReviewHandoffIntegrityError("handoff manifest/replay binding mismatch")
    projection = HumanReviewHandoffProjection.model_validate_json(
        (output_dir / HUMAN_HANDOFF_PROJECTION_FILENAME).read_text(encoding="utf-8")
    )
    replay = HumanHandoffReplayCertificate.model_validate_json(
        (output_dir / HUMAN_HANDOFF_REPLAY_FILENAME).read_text(encoding="utf-8")
    )
    if projection.projection_sha256 != report.projection.projection_sha256:
        raise HumanReviewHandoffIntegrityError("persisted handoff projection differs")
    if replay.certificate_hash != report.replay_certificate.certificate_hash:
        raise HumanReviewHandoffIntegrityError("persisted handoff replay differs")
    role_slots = json.loads(
        (output_dir / HUMAN_HANDOFF_ROLE_SLOTS_FILENAME).read_text(encoding="utf-8")
    )
    packet_templates = json.loads(
        (output_dir / HUMAN_HANDOFF_PACKET_TEMPLATES_FILENAME).read_text(encoding="utf-8")
    )
    if role_slots != [item.model_dump(mode="json") for item in report.handoff.public_role_slots]:
        raise HumanReviewHandoffIntegrityError("persisted public role slots differ")
    if packet_templates != [
        item.model_dump(mode="json") for item in report.handoff.packet_templates
    ]:
        raise HumanReviewHandoffIntegrityError("persisted packet templates differ")
    return report, manifest


def execute_human_review_handoff_freeze(
    *,
    protocol: BenchmarkValidityProtocol,
    parent_erratum_report: BenchmarkValidityPaginationErratumReport,
    parent_erratum_manifest: PaginationErratumManifest,
    output_dir: Path,
    handoff_source_path: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    replay_work_dir: Path,
    parent_git_commit: str,
    built_at: datetime,
) -> tuple[BenchmarkHumanReviewHandoffReport, HumanReviewHandoffManifest]:
    if parent_git_commit != PARENT_ERRATUM_COMMIT:
        raise HumanReviewHandoffIntegrityError(
            "human handoff must parent the completed pagination erratum commit"
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"human handoff output must be a new empty directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    parent_evidence = ParentPaginationErratumEvidence.from_artifacts(
        report=parent_erratum_report,
        manifest=parent_erratum_manifest,
        focused_parent_commit=parent_git_commit,
    )
    handoff = build_human_review_handoff(
        protocol=protocol,
        parent_erratum=parent_evidence,
        frozen_at=built_at,
    )
    projection = build_human_review_handoff_projection(handoff)
    replay = run_human_review_handoff_replay(
        projection=projection,
        runner_path=runner_path,
        interpreters=interpreters,
        work_dir=replay_work_dir,
    )
    report = BenchmarkHumanReviewHandoffReport.create(
        parent_git_commit=parent_git_commit,
        built_at=built_at,
        handoff_source_sha256=_file_sha256(handoff_source_path),
        frozen_runner_sha256=_file_sha256(runner_path),
        handoff=handoff,
        projection=projection,
        replay_certificate=replay,
    )
    return report, write_human_review_handoff(output_dir, report)


__all__ = [
    "HANDOFF_CONTRACT_MODELS",
    "HUMAN_HANDOFF_MANIFEST_FILENAME",
    "HUMAN_HANDOFF_MARKDOWN_FILENAME",
    "HUMAN_HANDOFF_OWNER_CHECKLIST_FILENAME",
    "HUMAN_HANDOFF_PACKET_TEMPLATES_FILENAME",
    "HUMAN_HANDOFF_PROJECTION_FILENAME",
    "HUMAN_HANDOFF_REPLAY_FILENAME",
    "HUMAN_HANDOFF_REPORT_FILENAME",
    "HUMAN_HANDOFF_ROLE_SLOTS_FILENAME",
    "HUMAN_HANDOFF_RUNNER_SOURCE_PATH",
    "HUMAN_HANDOFF_SCHEMA_FILENAME",
    "PARENT_ERRATUM_COMMIT",
    "PARENT_ERRATUM_HASH",
    "PARENT_ERRATUM_MANIFEST_HASH",
    "PARENT_ERRATUM_PROJECTION_HASH",
    "PARENT_ERRATUM_REPLAY_HASH",
    "PARENT_ERRATUM_REPORT_HASH",
    "AdjudicatorAccessReceipt",
    "BenchmarkHumanReviewHandoff",
    "BenchmarkHumanReviewHandoffReport",
    "BlindedReviewPacketTemplate",
    "DualLockBarrierReceipt",
    "DualReviewerLockPolicy",
    "HumanHandoffReplayCertificate",
    "HumanHandoffReplayObservation",
    "HumanHandoffStage",
    "HumanHandoffTransition",
    "HumanReviewHandoffIntegrityError",
    "HumanReviewHandoffManifest",
    "HumanReviewHandoffProjection",
    "HumanReviewRole",
    "HumanRoleAssignmentReceipt",
    "HumanRoleRequirement",
    "HumanRoleStructuralValidation",
    "ParentPaginationErratumEvidence",
    "PrivateAssignmentFieldSpec",
    "PublicHumanRoleSlot",
    "PublicProjectionPolicy",
    "ReviewerLockReceipt",
    "RoleSlotStatus",
    "build_human_review_handoff",
    "build_human_review_handoff_projection",
    "build_human_review_handoff_replay_payload",
    "execute_human_review_handoff_freeze",
    "human_review_handoff_json_schemas",
    "load_human_review_handoff",
    "render_human_review_handoff_markdown",
    "render_owner_enrollment_checklist",
    "run_human_review_handoff_replay",
    "validate_human_role_assignments",
    "write_human_review_handoff",
]
