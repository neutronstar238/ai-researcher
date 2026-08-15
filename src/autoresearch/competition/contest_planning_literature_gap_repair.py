"""Pure, content-addressed repair contract for failed planning coverage.

The module diagnoses a failed v4/v5 coverage receipt and projects a complete
second-round query plan.  It does not call a model, a scholarly source, or the
main research loop.  Repair terms must be literal phrases in caller-bound
focus or broad evidence, and only the second must-group of a diagnosed role
may change.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.competition import contest_direction_literature as direction_literature
from autoresearch.competition.contest_planning_literature_coverage import (
    PlanningLiteratureCoverageReceiptAny,
    PlanningLiteratureRole,
    PlanningLiteratureRoleQuery,
    role_query_from_boolean,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel

_SHA256 = r"^[0-9a-f]{64}$"
_ROLE_ORDER = (
    PlanningLiteratureRole.DIRECT_CORE,
    PlanningLiteratureRole.METHOD_FOUNDATION,
    PlanningLiteratureRole.MECHANISM_OR_NULL,
    PlanningLiteratureRole.COUNTEREVIDENCE,
)
_ROLE_MINIMUMS = {
    PlanningLiteratureRole.DIRECT_CORE: 2,
    PlanningLiteratureRole.METHOD_FOUNDATION: 1,
    PlanningLiteratureRole.MECHANISM_OR_NULL: 1,
    PlanningLiteratureRole.COUNTEREVIDENCE: 1,
}
_QUERY_REPAIRABLE_FAILURES = frozenset(
    {
        *(f"insufficient_{role.value}" for role in _ROLE_ORDER),
        "insufficient_distinct_required_role_anchors",
        "insufficient_method_focus_bridge_anchors",
    }
)


class PlanningLiteratureGapRepairError(ValueError):
    """Raised when a failed coverage receipt cannot yield a trusted R2 plan."""


class PlanningLiteratureRoleGapDiagnosis(StrictFrozenModel):
    """Authority-aware deficit trace for one fixed planning evidence role."""

    role: PlanningLiteratureRole
    required_anchor_count: int = Field(ge=1, le=2)
    semantic_anchor_ids: tuple[str, ...]
    semantic_anchor_count: int = Field(ge=0)
    authority_eligible_anchor_ids: tuple[str, ...]
    authority_eligible_anchor_count: int = Field(ge=0)
    authority_ineligible_anchor_ids: tuple[str, ...]
    selection_eligible_anchor_ids: tuple[str, ...]
    selection_eligible_anchor_count: int = Field(ge=0)
    missing_anchor_count: int = Field(ge=0, le=2)
    gap_kind: Literal[
        "none",
        "semantic_shortfall",
        "authority_shortfall",
        "distinct_anchor_conflict",
        "method_focus_bridge_shortfall",
    ]
    supplemental_retrieval_allowed: bool

    @model_validator(mode="after")
    def _validate_counts(self) -> PlanningLiteratureRoleGapDiagnosis:
        if self.role not in _ROLE_ORDER:
            raise ValueError("gap diagnosis is restricted to required planning roles")
        if self.required_anchor_count != _ROLE_MINIMUMS[self.role]:
            raise ValueError("gap diagnosis required-anchor count mismatch")
        for values, label in (
            (self.semantic_anchor_ids, "semantic"),
            (self.authority_eligible_anchor_ids, "authority-eligible"),
            (self.authority_ineligible_anchor_ids, "authority-ineligible"),
            (self.selection_eligible_anchor_ids, "selection-eligible"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{label} anchor IDs must be unique and sorted")
        if self.semantic_anchor_count != len(self.semantic_anchor_ids):
            raise ValueError("semantic anchor count mismatch")
        if self.authority_eligible_anchor_count != len(self.authority_eligible_anchor_ids):
            raise ValueError("authority-eligible anchor count mismatch")
        if self.selection_eligible_anchor_count != len(self.selection_eligible_anchor_ids):
            raise ValueError("selection-eligible anchor count mismatch")
        if not set(self.authority_eligible_anchor_ids).issubset(self.semantic_anchor_ids):
            raise ValueError("authority-eligible anchors must be semantically matched")
        if not set(self.selection_eligible_anchor_ids).issubset(self.authority_eligible_anchor_ids):
            raise ValueError("selection-eligible anchors must pass the authority gate")
        expected_ineligible = tuple(
            sorted(set(self.semantic_anchor_ids).difference(self.authority_eligible_anchor_ids))
        )
        if self.authority_ineligible_anchor_ids != expected_ineligible:
            raise ValueError("authority-ineligible anchor IDs mismatch")
        if self.supplemental_retrieval_allowed != (self.gap_kind != "none"):
            raise ValueError("role repairability does not match its diagnosed gap")
        if self.gap_kind == "none" and self.missing_anchor_count:
            raise ValueError("complete role cannot report a missing anchor")
        if self.gap_kind != "none" and not self.missing_anchor_count:
            raise ValueError("diagnosed role gap must report a missing anchor")
        return self


class PlanningLiteratureGapDiagnosisReceipt(StrictFrozenModel):
    """Replayable diagnosis derived only from one failed v4 coverage receipt."""

    schema_version: Literal["contest-planning-literature-gap-diagnosis-v1"] = (
        "contest-planning-literature-gap-diagnosis-v1"
    )
    coverage_receipt: PlanningLiteratureCoverageReceiptAny
    coverage_receipt_hash: str = Field(pattern=_SHA256)
    role_diagnostics: tuple[PlanningLiteratureRoleGapDiagnosis, ...] = Field(
        min_length=4,
        max_length=4,
    )
    repairable_roles: tuple[PlanningLiteratureRole, ...]
    non_retrieval_blockers: tuple[str, ...]
    supplemental_retrieval_allowed: bool
    diagnosis_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _replay_diagnosis(self) -> PlanningLiteratureGapDiagnosisReceipt:
        _require_failed_supported_coverage(self.coverage_receipt)
        if self.coverage_receipt_hash != self.coverage_receipt.receipt_hash:
            raise ValueError("gap diagnosis coverage receipt hash mismatch")
        expected = _diagnosis_components(self.coverage_receipt)
        if self.role_diagnostics != expected[0]:
            raise ValueError("gap role diagnosis does not replay")
        if self.repairable_roles != expected[1]:
            raise ValueError("gap repairable roles do not replay")
        if self.non_retrieval_blockers != expected[2]:
            raise ValueError("gap non-retrieval blockers do not replay")
        if self.supplemental_retrieval_allowed != expected[3]:
            raise ValueError("gap supplemental-retrieval decision does not replay")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"diagnosis_hash"})
        )
        if self.diagnosis_hash != expected_hash:
            raise ValueError("gap diagnosis hash mismatch")
        return self


class PlanningLiteratureGapRepairEvidenceInput(StrictFrozenModel):
    """Exact focus/broad text from which an R2 replacement term may be copied."""

    source_scope: Literal["focus", "broad"]
    source_artifact_hash: str = Field(pattern=_SHA256)
    record_id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1)
    abstract: str | None = None
    evidence_hash: str = Field(pattern=_SHA256)

    @field_validator("record_id", "title")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("gap-repair evidence text must not be blank")
        return stripped

    @field_validator("abstract")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _validate_hash(self) -> PlanningLiteratureGapRepairEvidenceInput:
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"evidence_hash"}))
        if self.evidence_hash != expected:
            raise ValueError("gap-repair evidence hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PlanningLiteratureGapRepairEvidenceInput:
        """Create one content-addressed evidence projection."""

        allowed = {"source_scope", "source_artifact_hash", "record_id", "title", "abstract"}
        if set(values) != allowed and set(values) != allowed.difference({"abstract"}):
            raise PlanningLiteratureGapRepairError(
                "evidence creation requires only source scope, artifact hash, record ID, title, "
                "and optional abstract"
            )
        abstract_value = values.get("abstract")
        payload = {
            "source_scope": values["source_scope"],
            "source_artifact_hash": values["source_artifact_hash"],
            "record_id": str(values["record_id"]).strip(),
            "title": str(values["title"]).strip(),
            "abstract": (str(abstract_value).strip() if abstract_value is not None else None),
        }
        if payload["abstract"] == "":
            payload["abstract"] = None
        return cls.model_validate({**payload, "evidence_hash": canonical_model_hash(payload)})


class PlanningLiteratureRepairTermProvenance(StrictFrozenModel):
    """One literal replacement term and the exact evidence field containing it."""

    term: str = Field(min_length=1, max_length=72)
    evidence_hash: str = Field(pattern=_SHA256)
    matched_field: Literal["title", "abstract"]

    @field_validator("term")
    @classmethod
    def _normalize_term(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("repair term must not be blank")
        if any(character in normalized for character in ('"', "\\", "(", ")", "*", "?")):
            raise ValueError("repair term contains unsupported query syntax")
        return normalized


class PlanningLiteratureRoleQueryRepair(StrictFrozenModel):
    """The evidence-bound replacement for one diagnosed role's second group."""

    role: PlanningLiteratureRole
    replacement_terms: tuple[PlanningLiteratureRepairTermProvenance, ...] = Field(
        min_length=2,
        max_length=4,
    )

    @model_validator(mode="after")
    def _validate_repair(self) -> PlanningLiteratureRoleQueryRepair:
        if self.role not in _ROLE_ORDER:
            raise ValueError("query repair is restricted to required planning roles")
        normalized_terms = tuple(
            _normalize_for_evidence(item.term) for item in self.replacement_terms
        )
        if len(normalized_terms) != len(set(normalized_terms)):
            raise ValueError("replacement terms must be semantically unique")
        return self


class PlanningLiteratureGapRepairProjection(StrictFrozenModel):
    """Complete replayable R2 query plan projected from a diagnosis and evidence."""

    schema_version: Literal["contest-planning-literature-gap-repair-v1"] = (
        "contest-planning-literature-gap-repair-v1"
    )
    query_compiler_version: Literal["source-query-compiler-v4"] = "source-query-compiler-v4"
    diagnosis: PlanningLiteratureGapDiagnosisReceipt
    diagnosis_hash: str = Field(pattern=_SHA256)
    coverage_receipt_hash: str = Field(pattern=_SHA256)
    evidence_inputs: tuple[PlanningLiteratureGapRepairEvidenceInput, ...] = Field(min_length=1)
    evidence_catalog_hash: str = Field(pattern=_SHA256)
    repairs: tuple[PlanningLiteratureRoleQueryRepair, ...] = Field(min_length=1, max_length=4)
    r2_role_queries: tuple[PlanningLiteratureRoleQuery, ...] = Field(min_length=4, max_length=4)
    r2_query_plan_hash: str = Field(pattern=_SHA256)
    projection_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _replay_projection(self) -> PlanningLiteratureGapRepairProjection:
        if self.diagnosis_hash != self.diagnosis.diagnosis_hash:
            raise ValueError("gap-repair diagnosis hash mismatch")
        if self.coverage_receipt_hash != self.diagnosis.coverage_receipt_hash:
            raise ValueError("gap-repair coverage receipt hash mismatch")
        evidence = _normalize_evidence_inputs(self.evidence_inputs)
        if self.evidence_inputs != evidence:
            raise ValueError("gap-repair evidence inputs are not in canonical order")
        expected_evidence_hash = _evidence_catalog_hash(evidence)
        if self.evidence_catalog_hash != expected_evidence_hash:
            raise ValueError("gap-repair evidence catalog hash mismatch")
        expected_repairs, expected_queries = _project_r2_queries(
            self.diagnosis,
            evidence_inputs=evidence,
            repairs=self.repairs,
        )
        if self.repairs != expected_repairs:
            raise ValueError("gap-repair role replacements do not replay")
        if self.r2_role_queries != expected_queries:
            raise ValueError("gap-repair R2 query projection does not replay")
        expected_query_hash = _r2_query_plan_hash(
            self.coverage_receipt_hash,
            expected_queries,
        )
        if self.r2_query_plan_hash != expected_query_hash:
            raise ValueError("gap-repair R2 query-plan hash mismatch")
        expected_projection_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"projection_hash"})
        )
        if self.projection_hash != expected_projection_hash:
            raise ValueError("gap-repair projection hash mismatch")
        return self


def diagnose_planning_literature_gap(
    coverage_receipt: PlanningLiteratureCoverageReceiptAny,
) -> PlanningLiteratureGapDiagnosisReceipt:
    """Derive an authority-aware role diagnosis from one failed v4/v5 receipt."""

    _require_failed_supported_coverage(coverage_receipt)
    role_diagnostics, repairable_roles, blockers, allowed = _diagnosis_components(coverage_receipt)
    payload = {
        "schema_version": "contest-planning-literature-gap-diagnosis-v1",
        "coverage_receipt": coverage_receipt.model_dump(mode="json"),
        "coverage_receipt_hash": coverage_receipt.receipt_hash,
        "role_diagnostics": [item.model_dump(mode="json") for item in role_diagnostics],
        "repairable_roles": [item.value for item in repairable_roles],
        "non_retrieval_blockers": list(blockers),
        "supplemental_retrieval_allowed": allowed,
    }
    return PlanningLiteratureGapDiagnosisReceipt.model_validate(
        {**payload, "diagnosis_hash": canonical_model_hash(payload)}
    )


def project_planning_literature_query_repair(
    diagnosis: PlanningLiteratureGapDiagnosisReceipt,
    *,
    evidence_inputs: Sequence[PlanningLiteratureGapRepairEvidenceInput],
    repairs: Sequence[PlanningLiteratureRoleQueryRepair],
) -> PlanningLiteratureGapRepairProjection:
    """Project a complete four-query R2 plan without calling a model or source."""

    evidence = _normalize_evidence_inputs(tuple(evidence_inputs))
    normalized_repairs, r2_queries = _project_r2_queries(
        diagnosis,
        evidence_inputs=evidence,
        repairs=tuple(repairs),
    )
    evidence_hash = _evidence_catalog_hash(evidence)
    query_hash = _r2_query_plan_hash(diagnosis.coverage_receipt_hash, r2_queries)
    payload = {
        "schema_version": "contest-planning-literature-gap-repair-v1",
        "query_compiler_version": "source-query-compiler-v4",
        "diagnosis": diagnosis.model_dump(mode="json"),
        "diagnosis_hash": diagnosis.diagnosis_hash,
        "coverage_receipt_hash": diagnosis.coverage_receipt_hash,
        "evidence_inputs": [item.model_dump(mode="json") for item in evidence],
        "evidence_catalog_hash": evidence_hash,
        "repairs": [item.model_dump(mode="json") for item in normalized_repairs],
        "r2_role_queries": [item.model_dump(mode="json") for item in r2_queries],
        "r2_query_plan_hash": query_hash,
    }
    return PlanningLiteratureGapRepairProjection.model_validate(
        {**payload, "projection_hash": canonical_model_hash(payload)}
    )


def write_planning_literature_gap_diagnosis(
    path: Path | str,
    diagnosis: PlanningLiteratureGapDiagnosisReceipt,
) -> Path:
    """Persist a diagnosis in deterministic JSON."""

    return write_json_model(path, diagnosis)


def load_planning_literature_gap_diagnosis(
    path: Path | str,
) -> PlanningLiteratureGapDiagnosisReceipt:
    """Load and fully replay a persisted diagnosis."""

    return PlanningLiteratureGapDiagnosisReceipt.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def write_planning_literature_gap_repair_projection(
    path: Path | str,
    projection: PlanningLiteratureGapRepairProjection,
) -> Path:
    """Persist a complete R2 projection in deterministic JSON."""

    return write_json_model(path, projection)


def load_planning_literature_gap_repair_projection(
    path: Path | str,
) -> PlanningLiteratureGapRepairProjection:
    """Load and fully replay a persisted R2 projection."""

    return PlanningLiteratureGapRepairProjection.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _require_failed_supported_coverage(
    receipt: PlanningLiteratureCoverageReceiptAny,
) -> None:
    if (
        receipt.schema_version
        not in {
            "contest-planning-literature-coverage-v4",
            "contest-planning-literature-coverage-v5",
        }
        or receipt.passed
    ):
        raise PlanningLiteratureGapRepairError(
            "gap repair requires one failed v4 or v5 planning-literature coverage receipt"
        )


def _diagnosis_components(
    receipt: PlanningLiteratureCoverageReceiptAny,
) -> tuple[
    tuple[PlanningLiteratureRoleGapDiagnosis, ...],
    tuple[PlanningLiteratureRole, ...],
    tuple[str, ...],
    bool,
]:
    semantic = _anchor_sets_by_role(receipt, authority_only=False)
    authority = _anchor_sets_by_role(receipt, authority_only=True)
    selection_eligible = _selection_eligible_anchor_sets_by_role(receipt, authority)
    conflict_roles = _hall_conflict_roles(selection_eligible)
    diagnostics: list[PlanningLiteratureRoleGapDiagnosis] = []
    for role in _ROLE_ORDER:
        required = _ROLE_MINIMUMS[role]
        semantic_ids = tuple(sorted(semantic[role]))
        authority_ids = tuple(sorted(authority[role]))
        selection_ids = tuple(sorted(selection_eligible[role]))
        gap_kind: Literal[
            "none",
            "semantic_shortfall",
            "authority_shortfall",
            "distinct_anchor_conflict",
            "method_focus_bridge_shortfall",
        ]
        if len(semantic_ids) < required:
            gap_kind = "semantic_shortfall"
            missing = required - len(semantic_ids)
        elif len(authority_ids) < required:
            gap_kind = "authority_shortfall"
            missing = required - len(authority_ids)
        elif (
            len(selection_ids) < required
            and role is PlanningLiteratureRole.METHOD_FOUNDATION
            and receipt.schema_version == "contest-planning-literature-coverage-v5"
        ):
            gap_kind = "method_focus_bridge_shortfall"
            missing = required - len(selection_ids)
        elif (
            "insufficient_distinct_required_role_anchors" in receipt.failure_reasons
            and role in conflict_roles
        ):
            gap_kind = "distinct_anchor_conflict"
            missing = 1
        elif (
            role is PlanningLiteratureRole.METHOD_FOUNDATION
            and "insufficient_method_focus_bridge_anchors" in receipt.failure_reasons
        ):
            gap_kind = "method_focus_bridge_shortfall"
            missing = 1
        else:
            gap_kind = "none"
            missing = 0
        diagnostics.append(
            PlanningLiteratureRoleGapDiagnosis(
                role=role,
                required_anchor_count=required,
                semantic_anchor_ids=semantic_ids,
                semantic_anchor_count=len(semantic_ids),
                authority_eligible_anchor_ids=authority_ids,
                authority_eligible_anchor_count=len(authority_ids),
                authority_ineligible_anchor_ids=tuple(
                    sorted(set(semantic_ids).difference(authority_ids))
                ),
                selection_eligible_anchor_ids=selection_ids,
                selection_eligible_anchor_count=len(selection_ids),
                missing_anchor_count=missing,
                gap_kind=gap_kind,
                supplemental_retrieval_allowed=gap_kind != "none",
            )
        )
    blockers = tuple(
        failure for failure in receipt.failure_reasons if failure not in _QUERY_REPAIRABLE_FAILURES
    )
    repairable_roles = tuple(
        item.role for item in diagnostics if item.supplemental_retrieval_allowed
    )
    allowed = bool(repairable_roles) and not blockers
    if not allowed:
        repairable_roles = ()
        diagnostics = [
            item.model_copy(
                update={
                    "gap_kind": "none",
                    "missing_anchor_count": 0,
                    "supplemental_retrieval_allowed": False,
                }
            )
            for item in diagnostics
        ]
    return tuple(diagnostics), repairable_roles, blockers, allowed


def _anchor_sets_by_role(
    receipt: PlanningLiteratureCoverageReceiptAny,
    *,
    authority_only: bool,
) -> dict[PlanningLiteratureRole, set[str]]:
    eligible = set(_required_anchor_eligible_record_ids(receipt))
    result: dict[PlanningLiteratureRole, set[str]] = {role: set() for role in _ROLE_ORDER}
    for classification in receipt.classifications:
        candidate = classification.candidate
        if authority_only and candidate.record_id not in eligible:
            continue
        for match in classification.role_matches:
            if match.complete and match.role in result:
                result[match.role].add(candidate.effective_anchor_id)
    return result


def _required_anchor_eligible_record_ids(
    receipt: PlanningLiteratureCoverageReceiptAny,
) -> tuple[str, ...]:
    values = getattr(receipt, "required_anchor_eligible_record_ids", None)
    if values is None:
        raise PlanningLiteratureGapRepairError(
            "failed coverage receipt lacks authority eligibility required by gap diagnosis"
        )
    return tuple(str(item) for item in values)


def _selection_eligible_anchor_sets_by_role(
    receipt: PlanningLiteratureCoverageReceiptAny,
    authority: dict[PlanningLiteratureRole, set[str]],
) -> dict[PlanningLiteratureRole, set[str]]:
    result = {role: set(values) for role, values in authority.items()}
    if receipt.schema_version != "contest-planning-literature-coverage-v5":
        return result
    assessments = getattr(receipt, "method_bridge_assessments", ())
    eligible_record_ids = set(_required_anchor_eligible_record_ids(receipt))
    bridged_method_anchors: set[str] = set()
    for classification, assessment in zip(
        receipt.classifications,
        assessments,
        strict=True,
    ):
        if (
            classification.candidate.record_id in eligible_record_ids
            and assessment.bridge_eligible
            and PlanningLiteratureRole.METHOD_FOUNDATION in classification.matched_roles
        ):
            bridged_method_anchors.add(classification.candidate.effective_anchor_id)
    result[PlanningLiteratureRole.METHOD_FOUNDATION] = bridged_method_anchors
    return result


def _hall_conflict_roles(
    authority: dict[PlanningLiteratureRole, set[str]],
) -> set[PlanningLiteratureRole]:
    slots = tuple(role for role in _ROLE_ORDER for _unused in range(_ROLE_MINIMUMS[role]))
    minimal_deficient_subsets: list[frozenset[int]] = []
    for size in range(1, len(slots) + 1):
        for slot_indices in combinations(range(len(slots)), size):
            subset = frozenset(slot_indices)
            if any(existing.issubset(subset) for existing in minimal_deficient_subsets):
                continue
            neighbor_anchors = set().union(*(authority[slots[index]] for index in subset))
            if len(neighbor_anchors) < size:
                minimal_deficient_subsets.append(subset)
    return {slots[index] for subset in minimal_deficient_subsets for index in subset}


def _normalize_evidence_inputs(
    evidence_inputs: Sequence[PlanningLiteratureGapRepairEvidenceInput],
) -> tuple[PlanningLiteratureGapRepairEvidenceInput, ...]:
    evidence = tuple(
        sorted(
            evidence_inputs,
            key=lambda item: (
                item.source_scope,
                item.record_id.casefold(),
                item.evidence_hash,
            ),
        )
    )
    if not evidence:
        raise PlanningLiteratureGapRepairError("gap repair requires focus or broad evidence")
    hashes = tuple(item.evidence_hash for item in evidence)
    if len(hashes) != len(set(hashes)):
        raise PlanningLiteratureGapRepairError("gap-repair evidence hashes must be unique")
    identities = tuple((item.source_scope, item.record_id) for item in evidence)
    if len(identities) != len(set(identities)):
        raise PlanningLiteratureGapRepairError("gap-repair evidence identities must be unique")
    return evidence


def _evidence_catalog_hash(
    evidence: tuple[PlanningLiteratureGapRepairEvidenceInput, ...],
) -> str:
    return canonical_model_hash(
        {"evidence_inputs": [item.model_dump(mode="json") for item in evidence]}
    )


def _project_r2_queries(
    diagnosis: PlanningLiteratureGapDiagnosisReceipt,
    *,
    evidence_inputs: tuple[PlanningLiteratureGapRepairEvidenceInput, ...],
    repairs: Sequence[PlanningLiteratureRoleQueryRepair],
) -> tuple[
    tuple[PlanningLiteratureRoleQueryRepair, ...],
    tuple[PlanningLiteratureRoleQuery, ...],
]:
    if not diagnosis.supplemental_retrieval_allowed:
        raise PlanningLiteratureGapRepairError(
            "diagnosed coverage failure is not repairable by supplemental retrieval"
        )
    repair_by_role = {item.role: item for item in repairs}
    if len(repair_by_role) != len(tuple(repairs)):
        raise PlanningLiteratureGapRepairError("each diagnosed role may have only one repair")
    if set(repair_by_role) != set(diagnosis.repairable_roles):
        raise PlanningLiteratureGapRepairError(
            "repairs must cover exactly the diagnosed repairable roles"
        )
    normalized_repairs = tuple(repair_by_role[role] for role in diagnosis.repairable_roles)
    evidence_by_hash = {item.evidence_hash: item for item in evidence_inputs}
    for repair in normalized_repairs:
        for provenance in repair.replacement_terms:
            evidence = evidence_by_hash.get(provenance.evidence_hash)
            if evidence is None:
                raise PlanningLiteratureGapRepairError(
                    f"repair term {provenance.term!r} references unknown evidence"
                )
            source_text = getattr(evidence, provenance.matched_field)
            if not source_text or not _term_occurs_in_evidence(provenance.term, source_text):
                raise PlanningLiteratureGapRepairError(
                    f"repair term {provenance.term!r} does not occur in bound "
                    f"{evidence.source_scope} evidence {provenance.matched_field}"
                )

    original_queries = diagnosis.coverage_receipt.role_queries
    original_by_role = {item.role: item for item in original_queries}
    r2_queries: list[PlanningLiteratureRoleQuery] = []
    for role in _ROLE_ORDER:
        original = original_by_role[role]
        candidate_repair = repair_by_role.get(role)
        if candidate_repair is None:
            projected = original
        else:
            revised_raw = _replace_second_must_group(
                original.raw_query,
                tuple(item.term for item in candidate_repair.replacement_terms),
            )
            projected = role_query_from_boolean(
                role,
                _r2_query_id(original.query_id),
                revised_raw,
            )
            if projected.must_groups[0] != original.must_groups[0]:
                raise PlanningLiteratureGapRepairError(
                    "repair changed bytes outside the diagnosed role's second group"
                )
            if projected.must_groups[1] == original.must_groups[1]:
                raise PlanningLiteratureGapRepairError(
                    "repair must materially change the diagnosed role's second group"
                )
        r2_queries.append(projected)
    projected_tuple = tuple(r2_queries)
    for original, projected in zip(original_queries, projected_tuple, strict=True):
        if original.role not in repair_by_role and original.raw_query != projected.raw_query:
            raise PlanningLiteratureGapRepairError("non-gap query bytes changed during R2 repair")
        if original.must_groups[0] != projected.must_groups[0]:
            raise PlanningLiteratureGapRepairError("R2 repair changed a query object group")
    try:
        direction_literature._validate_v4_query_plan(  # noqa: SLF001
            tuple(item.raw_query for item in projected_tuple)
        )
        for projected in projected_tuple:
            for source in ("arxiv", "openalex"):
                direction_literature._compile_source_query(  # noqa: SLF001
                    source,
                    projected.raw_query,
                    compiler_version="source-query-compiler-v4",
                )
    except direction_literature.ContestDirectionLiteratureError as exc:
        raise PlanningLiteratureGapRepairError(str(exc)) from exc
    return normalized_repairs, projected_tuple


def _replace_second_must_group(raw_query: str, replacement_terms: tuple[str, ...]) -> str:
    expression_start, expression_end = _effective_expression_bounds(raw_query)
    operator_spans = _top_level_and_spans(
        raw_query,
        start=expression_start,
        end=expression_end,
    )
    if len(operator_spans) != 1:
        raise PlanningLiteratureGapRepairError(
            "R1 role query does not expose exactly two replaceable must-groups"
        )
    _operator_start, operator_end = operator_spans[0]
    second_start = operator_end
    while second_start < expression_end and raw_query[second_start].isspace():
        second_start += 1
    second_end = expression_end
    while second_end > second_start and raw_query[second_end - 1].isspace():
        second_end -= 1
    if second_start >= second_end:
        raise PlanningLiteratureGapRepairError("R1 role query has an empty second must-group")
    rendered = "(" + " OR ".join(_render_query_term(term) for term in replacement_terms) + ")"
    return raw_query[:second_start] + rendered + raw_query[second_end:]


def _effective_expression_bounds(value: str) -> tuple[int, int]:
    start = 0
    end = len(value)
    while start < end and value[start].isspace():
        start += 1
    while end > start and value[end - 1].isspace():
        end -= 1
    while start < end and value[start] == "(" and value[end - 1] == ")":
        if _matching_parenthesis(value, start, end) != end - 1:
            break
        start += 1
        end -= 1
        while start < end and value[start].isspace():
            start += 1
        while end > start and value[end - 1].isspace():
            end -= 1
    return start, end


def _matching_parenthesis(value: str, start: int, end: int) -> int | None:
    depth = 0
    quote: str | None = None
    for index in range(start, end):
        character = value[index]
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return None
    return None


def _top_level_and_spans(
    value: str,
    *,
    start: int,
    end: int,
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    depth = 0
    quote: str | None = None
    index = start
    while index < end:
        character = value[index]
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {'"', "'"}:
            quote = character
            index += 1
            continue
        if character == "(":
            depth += 1
            index += 1
            continue
        if character == ")":
            depth -= 1
            index += 1
            continue
        match = re.match(r"(?i)AND(?![\w])", value[index:end]) if depth == 0 else None
        previous = value[index - 1] if index > start else " "
        if match is not None and not (previous.isalnum() or previous == "_"):
            spans.append((index, index + len(match.group(0))))
            index += len(match.group(0))
            continue
        index += 1
    return tuple(spans)


def _render_query_term(term: str) -> str:
    if re.fullmatch(r"[\w-]+", term, flags=re.UNICODE) and term.casefold() not in {
        "and",
        "or",
        "not",
    }:
        return term
    return json.dumps(term, ensure_ascii=False)


def _r2_query_id(parent_query_id: str) -> str:
    if len(parent_query_id) <= 125:
        return f"{parent_query_id}-r2"
    digest = canonical_model_hash({"parent_query_id": parent_query_id})[:16]
    return f"{parent_query_id[:107]}-r2-{digest}"


def _term_occurs_in_evidence(term: str, evidence_text: str) -> bool:
    normalized_term = _normalize_for_evidence(term)
    normalized_text = _normalize_for_evidence(evidence_text)
    if not normalized_term or not normalized_text:
        return False
    if _contains_cjk(normalized_term):
        return normalized_term.replace(" ", "") in normalized_text.replace(" ", "")
    term_tokens = normalized_term.split()
    text_tokens = normalized_text.split()
    width = len(term_tokens)
    return any(
        text_tokens[index : index + width] == term_tokens
        for index in range(len(text_tokens) - width + 1)
    )


def _normalize_for_evidence(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character for character in decomposed if not unicodedata.category(character).startswith("M")
    )
    spaced = "".join(
        character if unicodedata.category(character)[:1] in {"L", "N"} else " "
        for character in without_marks
    )
    return " ".join(spaced.split())


def _contains_cjk(value: str) -> bool:
    return any(
        "CJK" in unicodedata.name(character, "")
        or "HIRAGANA" in unicodedata.name(character, "")
        or "KATAKANA" in unicodedata.name(character, "")
        or "HANGUL" in unicodedata.name(character, "")
        for character in value
    )


def _r2_query_plan_hash(
    coverage_receipt_hash: str,
    queries: tuple[PlanningLiteratureRoleQuery, ...],
) -> str:
    return canonical_model_hash(
        {
            "query_compiler_version": "source-query-compiler-v4",
            "coverage_receipt_hash": coverage_receipt_hash,
            "r2_role_queries": [item.model_dump(mode="json") for item in queries],
        }
    )


__all__ = [
    "PlanningLiteratureGapDiagnosisReceipt",
    "PlanningLiteratureGapRepairError",
    "PlanningLiteratureGapRepairEvidenceInput",
    "PlanningLiteratureGapRepairProjection",
    "PlanningLiteratureRepairTermProvenance",
    "PlanningLiteratureRoleGapDiagnosis",
    "PlanningLiteratureRoleQueryRepair",
    "diagnose_planning_literature_gap",
    "load_planning_literature_gap_diagnosis",
    "load_planning_literature_gap_repair_projection",
    "project_planning_literature_query_repair",
    "write_planning_literature_gap_diagnosis",
    "write_planning_literature_gap_repair_projection",
]
