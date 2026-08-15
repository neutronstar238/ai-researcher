"""Topic-neutral semantic coverage for a planning literature shortlist.

The contract separates semantic eligibility from bibliometric quality.  A
candidate can satisfy a planning role only by matching every required group in
that role's AND-of-OR query.  Authority quality, complete-match specificity,
and capped citation bands only order candidates that already belong to the
same semantic layer.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.models import StrictFrozenModel

_SHA256 = r"^[0-9a-f]{64}$"
_QUERY_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class PlanningLiteratureCoverageError(ValueError):
    """Raised when a query or required planning coverage is not trustworthy."""


class PlanningLiteratureRole(str, Enum):
    """Semantic roles used by the planning evidence contract."""

    DIRECT_CORE = "direct_core"
    METHOD_FOUNDATION = "method_foundation"
    MECHANISM_OR_NULL = "mechanism_or_null"
    COUNTEREVIDENCE = "counterevidence"
    METHOD_TRANSFER = "method_transfer"
    OFF_TOPIC = "off_topic"


_REQUIRED_ROLES = (
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
_STRONG_SUPPLEMENT_MINIMUM_QUALITY = 0.70
_ADJACENT_SUPPLEMENT_MINIMUM_QUALITY = 0.50
_MAX_ADJACENT_SUPPLEMENTS = 2


class PlanningLiteratureRoleQuery(StrictFrozenModel):
    """One role query represented as AND over OR-alternative groups."""

    role: PlanningLiteratureRole
    query_id: str = Field(pattern=_QUERY_ID)
    raw_query: str = Field(min_length=1)
    must_groups: tuple[tuple[str, ...], ...] = Field(min_length=1)
    prefix_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_query(self) -> PlanningLiteratureRoleQuery:
        if self.role not in _REQUIRED_ROLES:
            raise ValueError("role queries are allowed only for required evidence roles")
        expected_groups, expected_prefixes = _parse_boolean_query(self.raw_query)
        if self.must_groups != expected_groups or self.prefix_terms != expected_prefixes:
            raise ValueError("role query groups do not match the parsed raw query")
        return self


class PlanningLiteratureCandidate(StrictFrozenModel):
    """Minimal topic-neutral projection of one real retrieval record."""

    record_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    abstract: str | None = None
    anchor_id: str | None = Field(default=None, min_length=1)
    retrieval_queries: tuple[str, ...] = ()
    source_stages: tuple[str, ...] = ()
    citation_count: int | None = Field(default=None, ge=0)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    context_characters: int | None = Field(default=None, ge=1)

    @field_validator("record_id", "title")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("candidate required text must not be blank")
        return stripped

    @field_validator("abstract")
    @classmethod
    def _normalize_abstract(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("anchor_id")
    @classmethod
    def _normalize_anchor_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("candidate anchor ID must not be blank")
        return stripped

    @field_validator("retrieval_queries", "source_stages", mode="before")
    @classmethod
    def _normalize_lineage(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        raw_items: tuple[str, ...]
        if isinstance(value, str):
            raw_items = (value,)
        elif isinstance(value, Sequence):
            raw_items = tuple(str(item) for item in value)
        else:
            raise ValueError("candidate lineage must be a sequence of strings")
        normalized = tuple(str(item).strip() for item in raw_items)
        if any(not item for item in normalized):
            raise ValueError("candidate lineage must not contain blank values")
        return tuple(sorted(set(normalized), key=_lineage_sort_key))

    @property
    def effective_context_characters(self) -> int:
        """Return the caller projection size or a deterministic local estimate."""

        if self.context_characters is not None:
            return self.context_characters
        return len(self.title) + len(self.abstract or "")

    @property
    def effective_anchor_id(self) -> str:
        """Return the caller-supplied work-family anchor or the record identity."""

        return self.anchor_id or self.record_id


class PlanningLiteratureMatchedGroup(StrictFrozenModel):
    """Trace of which alternatives satisfied one must group."""

    group_index: int = Field(ge=1)
    matched_terms: tuple[str, ...] = Field(min_length=1)
    matched_fields: tuple[Literal["title", "abstract"], ...] = Field(min_length=1)


class PlanningLiteratureRoleMatch(StrictFrozenModel):
    """A complete role match, or the partial method trace for transfer work."""

    role: PlanningLiteratureRole
    query_id: str = Field(pattern=_QUERY_ID)
    complete: bool
    matched_groups: tuple[PlanningLiteratureMatchedGroup, ...] = Field(min_length=1)
    matched_retrieval_queries: tuple[str, ...] = ()
    source_stages: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_complete_lineage(self) -> PlanningLiteratureRoleMatch:
        if self.complete and (
            not self.matched_retrieval_queries or "targeted_direction" not in self.source_stages
        ):
            raise ValueError("complete planning role matches require exact targeted-query lineage")
        return self


class PlanningLiteratureAnchorAssignment(StrictFrozenModel):
    """One distinct work-family anchor assigned to one required quota slot."""

    role: PlanningLiteratureRole
    query_id: str = Field(pattern=_QUERY_ID)
    record_id: str = Field(min_length=1)
    candidate_index: int = Field(ge=0)
    anchor_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_required_role(self) -> PlanningLiteratureAnchorAssignment:
        if self.role not in _REQUIRED_ROLES:
            raise ValueError("anchor assignments are allowed only for required roles")
        return self


class PlanningLiteratureClassification(StrictFrozenModel):
    """Semantic classification of one candidate before quality ordering."""

    candidate: PlanningLiteratureCandidate
    candidate_hash: str = Field(pattern=_SHA256)
    semantic_layer: PlanningLiteratureRole
    matched_roles: tuple[PlanningLiteratureRole, ...] = ()
    role_matches: tuple[PlanningLiteratureRoleMatch, ...] = ()

    @model_validator(mode="after")
    def _validate_classification(self) -> PlanningLiteratureClassification:
        if self.candidate_hash != canonical_model_hash(self.candidate):
            raise ValueError("planning literature candidate hash mismatch")
        complete_roles = tuple(item.role for item in self.role_matches if item.complete)
        if self.matched_roles != complete_roles:
            raise ValueError("planning literature matched roles do not match role traces")
        if len(self.matched_roles) != len(set(self.matched_roles)):
            raise ValueError("planning literature matched roles must be unique")
        if self.semantic_layer in _REQUIRED_ROLES:
            if self.semantic_layer not in self.matched_roles:
                raise ValueError("semantic layer is not backed by a complete role match")
        elif self.semantic_layer is PlanningLiteratureRole.METHOD_TRANSFER:
            if self.matched_roles or not any(
                item.role is PlanningLiteratureRole.METHOD_FOUNDATION and not item.complete
                for item in self.role_matches
            ):
                raise ValueError("method transfer requires only a partial method-role trace")
        elif self.semantic_layer is PlanningLiteratureRole.OFF_TOPIC:
            if self.matched_roles or self.role_matches:
                raise ValueError("off-topic records must not carry semantic role matches")
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError("unsupported planning literature semantic layer")
        return self


class PlanningLiteratureRoleCounts(StrictFrozenModel):
    """Counts for every semantic role without collapsing transfer/off-topic work."""

    direct_core: int = Field(ge=0)
    method_foundation: int = Field(ge=0)
    mechanism_or_null: int = Field(ge=0)
    counterevidence: int = Field(ge=0)
    method_transfer: int = Field(ge=0)
    off_topic: int = Field(ge=0)


class PlanningLiteratureRequiredRoleEligibleFamilyCounts(StrictFrozenModel):
    """Authority- and bridge-eligible work families for each required role."""

    direct_core: int = Field(ge=0)
    method_foundation: int = Field(ge=0)
    mechanism_or_null: int = Field(ge=0)
    counterevidence: int = Field(ge=0)


class PlanningLiteratureMethodBridgeTermMatch(StrictFrozenModel):
    """Exact field trace for one immutable focus-basis bridge term."""

    term: str = Field(min_length=1)
    matched_fields: tuple[Literal["title", "abstract"], ...] = Field(min_length=1)


class PlanningLiteratureMethodBridgeContract(StrictFrozenModel):
    """Deterministic method-focus bridge derived from immutable basis queries."""

    direct_query_id: str = Field(pattern=_QUERY_ID)
    method_query_id: str = Field(pattern=_QUERY_ID)
    direct_object_terms: tuple[str, ...] = Field(min_length=1)
    direct_focus_terms: tuple[str, ...] = Field(min_length=1)
    method_basis_terms: tuple[str, ...] = Field(min_length=1)
    shared_focus_terms: tuple[str, ...]
    bridge_semantics: Literal[
        "shared_direct_focus_method_basis_or_direct_object_exact_term_match"
    ] = "shared_direct_focus_method_basis_or_direct_object_exact_term_match"


class PlanningLiteratureMethodBridgeAssessment(StrictFrozenModel):
    """Per-candidate focus binding used by v5 method selection."""

    candidate_index: int = Field(ge=0)
    record_id: str = Field(min_length=1)
    bridge_kind: Literal[
        "not_method_candidate",
        "unbridged_method",
        "shared_focus",
        "direct_object",
        "shared_focus_and_direct_object",
    ]
    shared_focus_matches: tuple[PlanningLiteratureMethodBridgeTermMatch, ...] = ()
    direct_object_matches: tuple[PlanningLiteratureMethodBridgeTermMatch, ...] = ()
    bridge_eligible: bool

    @model_validator(mode="after")
    def _validate_bridge_kind(self) -> PlanningLiteratureMethodBridgeAssessment:
        shared = bool(self.shared_focus_matches)
        direct = bool(self.direct_object_matches)
        expected_kind = (
            "shared_focus_and_direct_object"
            if shared and direct
            else "shared_focus"
            if shared
            else "direct_object"
            if direct
            else self.bridge_kind
        )
        if (shared or direct) and self.bridge_kind != expected_kind:
            raise ValueError("method bridge kind does not match its term traces")
        if self.bridge_kind in {"not_method_candidate", "unbridged_method"} and (shared or direct):
            raise ValueError("non-bridged method assessment carries bridge term traces")
        if self.bridge_kind not in {"not_method_candidate", "unbridged_method"} and not (
            shared or direct
        ):
            raise ValueError("bridged method assessment requires term traces")
        expected_eligible = self.bridge_kind in {
            "shared_focus",
            "direct_object",
            "shared_focus_and_direct_object",
        }
        if self.bridge_eligible is not expected_eligible:
            raise ValueError("method bridge eligibility does not match bridge kind")
        return self


class PlanningLiteratureCoverageThresholdsV3(StrictFrozenModel):
    """Frozen quality-limited thresholds emitted by literature protocol v3."""

    direct_core: Literal[2] = 2
    method_foundation: Literal[1] = 1
    mechanism_or_null: Literal[1] = 1
    counterevidence: Literal[1] = 1
    method_transfer_must_not_be_majority: Literal[True] = True
    strong_supplement_minimum_quality: float = Field(default=0.7, ge=0.7, le=0.7)
    adjacent_supplement_minimum_quality: float = Field(default=0.5, ge=0.5, le=0.5)
    maximum_adjacent_supplements: Literal[2] = 2


class PlanningLiteratureCoverageThresholds(PlanningLiteratureCoverageThresholdsV3):
    """Current thresholds, including the repository-only anchor authority gate."""

    repository_only_must_not_fill_required_anchor: Literal[True] = True


class PlanningLiteratureCoverageThresholdsV2(StrictFrozenModel):
    """Frozen thresholds used only to validate historical v2 receipts."""

    direct_core: Literal[2] = 2
    method_foundation: Literal[1] = 1
    mechanism_or_null: Literal[1] = 1
    counterevidence: Literal[1] = 1
    method_transfer_must_not_be_majority: Literal[True] = True


class PlanningLiteratureCoverageReceiptV3(StrictFrozenModel):
    """Read-only validator for the frozen protocol-v3 selection algorithm."""

    schema_version: Literal["contest-planning-literature-coverage-v3"] = (
        "contest-planning-literature-coverage-v3"
    )
    role_queries: tuple[PlanningLiteratureRoleQuery, ...]
    classifications: tuple[PlanningLiteratureClassification, ...]
    thresholds: PlanningLiteratureCoverageThresholdsV3
    candidate_count: int = Field(ge=0)
    maximum_records: int = Field(ge=1)
    maximum_total_context_characters: int | None = Field(default=None, ge=1)
    available_role_counts: PlanningLiteratureRoleCounts
    selected_role_counts: PlanningLiteratureRoleCounts
    selected_record_ids: tuple[str, ...]
    selected_candidate_indices: tuple[int, ...]
    selected_records: tuple[PlanningLiteratureCandidate, ...]
    anchor_assignments: tuple[PlanningLiteratureAnchorAssignment, ...]
    selected_total_context_characters: int = Field(ge=0)
    failure_reasons: tuple[str, ...]
    passed: bool
    selection_semantics: Literal[
        "targeted_lineage_distinct_anchor_dp_then_quality_limited_supplements"
    ] = "targeted_lineage_distinct_anchor_dp_then_quality_limited_supplements"
    receipt_hash: str = Field(pattern=_SHA256)

    @property
    def selected_method_transfer_count(self) -> int:
        return self.selected_role_counts.method_transfer

    def require_pass(self) -> PlanningLiteratureCoverageReceiptV3:
        """Fail closed before a downstream planner consumes the selected subset."""

        if not self.passed:
            detail = ", ".join(self.failure_reasons) or "unknown coverage failure"
            raise PlanningLiteratureCoverageError(f"planning literature coverage failed: {detail}")
        return self

    @model_validator(mode="after")
    def _validate_receipt(self) -> PlanningLiteratureCoverageReceiptV3:
        _validate_coverage_receipt(self, policy_version="v3")
        return self


class PlanningLiteratureCoverageReceiptV4(StrictFrozenModel):
    """Read-only validator for the frozen protocol-v4 authority policy."""

    schema_version: Literal["contest-planning-literature-coverage-v4"] = (
        "contest-planning-literature-coverage-v4"
    )
    role_queries: tuple[PlanningLiteratureRoleQuery, ...]
    classifications: tuple[PlanningLiteratureClassification, ...]
    thresholds: PlanningLiteratureCoverageThresholds
    candidate_count: int = Field(ge=0)
    maximum_records: int = Field(ge=1)
    maximum_total_context_characters: int | None = Field(default=None, ge=1)
    available_role_counts: PlanningLiteratureRoleCounts
    selected_role_counts: PlanningLiteratureRoleCounts
    required_anchor_eligible_record_ids: tuple[str, ...]
    selected_record_ids: tuple[str, ...]
    selected_candidate_indices: tuple[int, ...]
    selected_records: tuple[PlanningLiteratureCandidate, ...]
    anchor_assignments: tuple[PlanningLiteratureAnchorAssignment, ...]
    selected_total_context_characters: int = Field(ge=0)
    failure_reasons: tuple[str, ...]
    passed: bool
    selection_semantics: Literal[
        "targeted_lineage_distinct_anchor_semantic_first_dp_then_quality_limited_supplements"
    ] = "targeted_lineage_distinct_anchor_semantic_first_dp_then_quality_limited_supplements"
    receipt_hash: str = Field(pattern=_SHA256)

    @property
    def selected_method_transfer_count(self) -> int:
        return self.selected_role_counts.method_transfer

    def require_pass(self) -> PlanningLiteratureCoverageReceiptV4:
        if not self.passed:
            detail = ", ".join(self.failure_reasons) or "unknown coverage failure"
            raise PlanningLiteratureCoverageError(f"planning literature coverage failed: {detail}")
        return self

    @model_validator(mode="after")
    def _validate_receipt(self) -> PlanningLiteratureCoverageReceiptV4:
        _validate_coverage_receipt(self, policy_version="v4")
        return self


class PlanningLiteratureCoverageReceipt(StrictFrozenModel):
    """Current method-focus-bound, authority-gated planning selection."""

    schema_version: Literal["contest-planning-literature-coverage-v5"] = (
        "contest-planning-literature-coverage-v5"
    )
    role_queries: tuple[PlanningLiteratureRoleQuery, ...]
    method_focus_basis_queries: tuple[PlanningLiteratureRoleQuery, ...]
    method_bridge_contract: PlanningLiteratureMethodBridgeContract
    classifications: tuple[PlanningLiteratureClassification, ...]
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...]
    thresholds: PlanningLiteratureCoverageThresholds
    candidate_count: int = Field(ge=0)
    maximum_records: int = Field(ge=1)
    maximum_total_context_characters: int | None = Field(default=None, ge=1)
    available_role_counts: PlanningLiteratureRoleCounts
    eligible_role_family_counts: PlanningLiteratureRequiredRoleEligibleFamilyCounts
    selected_role_counts: PlanningLiteratureRoleCounts
    required_anchor_eligible_record_ids: tuple[str, ...]
    selected_record_ids: tuple[str, ...]
    selected_candidate_indices: tuple[int, ...]
    selected_records: tuple[PlanningLiteratureCandidate, ...]
    anchor_assignments: tuple[PlanningLiteratureAnchorAssignment, ...]
    selected_total_context_characters: int = Field(ge=0)
    failure_reasons: tuple[str, ...]
    passed: bool
    selection_semantics: Literal[
        "immutable_focus_bridge_then_authority_distinct_anchor_dp_and_bridged_supplements"
    ] = "immutable_focus_bridge_then_authority_distinct_anchor_dp_and_bridged_supplements"
    receipt_hash: str = Field(pattern=_SHA256)

    @property
    def selected_method_transfer_count(self) -> int:
        return self.selected_role_counts.method_transfer

    def require_pass(self) -> PlanningLiteratureCoverageReceipt:
        if not self.passed:
            detail = ", ".join(self.failure_reasons) or "unknown coverage failure"
            raise PlanningLiteratureCoverageError(f"planning literature coverage failed: {detail}")
        return self

    @model_validator(mode="after")
    def _validate_receipt(self) -> PlanningLiteratureCoverageReceipt:
        _validate_coverage_receipt(self, policy_version="v5")
        return self


class PlanningLiteratureCoverageReceiptV2(StrictFrozenModel):
    """Read-only validator for the frozen pre-quality-gate coverage contract."""

    schema_version: Literal["contest-planning-literature-coverage-v2"] = (
        "contest-planning-literature-coverage-v2"
    )
    role_queries: tuple[PlanningLiteratureRoleQuery, ...]
    classifications: tuple[PlanningLiteratureClassification, ...]
    thresholds: PlanningLiteratureCoverageThresholdsV2
    candidate_count: int = Field(ge=0)
    maximum_records: int = Field(ge=1)
    maximum_total_context_characters: int | None = Field(default=None, ge=1)
    available_role_counts: PlanningLiteratureRoleCounts
    selected_role_counts: PlanningLiteratureRoleCounts
    selected_record_ids: tuple[str, ...]
    selected_candidate_indices: tuple[int, ...]
    selected_records: tuple[PlanningLiteratureCandidate, ...]
    anchor_assignments: tuple[PlanningLiteratureAnchorAssignment, ...]
    selected_total_context_characters: int = Field(ge=0)
    failure_reasons: tuple[str, ...]
    passed: bool
    selection_semantics: Literal[
        "targeted_lineage_distinct_anchor_dp_then_within_layer_quality"
    ] = "targeted_lineage_distinct_anchor_dp_then_within_layer_quality"
    receipt_hash: str = Field(pattern=_SHA256)

    @property
    def selected_method_transfer_count(self) -> int:
        return self.selected_role_counts.method_transfer

    def require_pass(self) -> PlanningLiteratureCoverageReceiptV2:
        if not self.passed:
            detail = ", ".join(self.failure_reasons) or "unknown coverage failure"
            raise PlanningLiteratureCoverageError(f"planning literature coverage failed: {detail}")
        return self

    @model_validator(mode="after")
    def _validate_receipt(self) -> PlanningLiteratureCoverageReceiptV2:
        _validate_coverage_receipt(self, policy_version="v2")
        return self


PlanningLiteratureCoverageReceiptAny = (
    PlanningLiteratureCoverageReceipt
    | PlanningLiteratureCoverageReceiptV4
    | PlanningLiteratureCoverageReceiptV3
    | PlanningLiteratureCoverageReceiptV2
)


def load_planning_literature_coverage_receipt(
    path: Path | str,
) -> PlanningLiteratureCoverageReceiptAny:
    """Load frozen v2-v4 algorithms or validate the current v5 policy."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise PlanningLiteratureCoverageError("planning literature coverage must be an object")
    return parse_planning_literature_coverage_receipt(payload)


def parse_planning_literature_coverage_receipt(
    payload: Mapping[str, Any],
) -> PlanningLiteratureCoverageReceiptAny:
    """Dispatch without upgrading or reinterpreting a historical receipt."""

    version = payload.get("schema_version")
    if version == "contest-planning-literature-coverage-v2":
        return PlanningLiteratureCoverageReceiptV2.model_validate(payload)
    if version == "contest-planning-literature-coverage-v3":
        return PlanningLiteratureCoverageReceiptV3.model_validate(payload)
    if version == "contest-planning-literature-coverage-v4":
        return PlanningLiteratureCoverageReceiptV4.model_validate(payload)
    if version == "contest-planning-literature-coverage-v5":
        return PlanningLiteratureCoverageReceipt.model_validate(payload)
    raise PlanningLiteratureCoverageError(
        f"unsupported planning literature coverage schema: {version!r}"
    )


def _validate_coverage_receipt(
    receipt: PlanningLiteratureCoverageReceiptAny,
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> None:
    _validate_role_queries(receipt.role_queries)
    if receipt.candidate_count != len(receipt.classifications):
        raise ValueError("planning literature candidate count mismatch")
    candidate_ids = tuple(item.candidate.record_id for item in receipt.classifications)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("planning literature candidate IDs must be unique")
    if isinstance(
        receipt,
        PlanningLiteratureCoverageReceipt | PlanningLiteratureCoverageReceiptV4,
    ):
        eligible_ids = receipt.required_anchor_eligible_record_ids
        if len(eligible_ids) != len(set(eligible_ids)):
            raise ValueError("required-anchor eligible record IDs must be unique")
        if not set(eligible_ids).issubset(candidate_ids):
            raise ValueError("required-anchor eligibility references an unknown record")
    else:
        eligible_ids = candidate_ids
    if receipt.available_role_counts != _role_counts(receipt.classifications):
        raise ValueError("available planning literature role counts mismatch")
    expected_classifications = _classify_planning_candidates_for_policy(
        tuple(item.candidate for item in receipt.classifications),
        receipt.role_queries,
        policy_version=policy_version,
    )
    if receipt.classifications != expected_classifications:
        raise ValueError("planning literature classifications do not replay")
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...] = ()
    if isinstance(receipt, PlanningLiteratureCoverageReceipt):
        basis_queries = _validate_method_focus_basis_queries(receipt.method_focus_basis_queries)
        expected_contract = _method_bridge_contract(basis_queries)
        if receipt.method_bridge_contract != expected_contract:
            raise ValueError("method bridge contract does not replay")
        method_bridge_assessments = _method_bridge_assessments(
            receipt.classifications,
            basis_queries=basis_queries,
            contract=expected_contract,
        )
        if receipt.method_bridge_assessments != method_bridge_assessments:
            raise ValueError("method bridge assessments do not replay")
        expected_eligible_counts = _eligible_required_role_family_counts(
            receipt.classifications,
            required_anchor_eligible_record_ids=eligible_ids,
            method_bridge_assessments=method_bridge_assessments,
        )
        if receipt.eligible_role_family_counts != expected_eligible_counts:
            raise ValueError("eligible planning literature role-family counts mismatch")
    expected_indices, expected_assignments, expected_failures = (
        _select_classified_planning_literature(
            receipt.classifications,
            maximum_records=receipt.maximum_records,
            maximum_total_context_characters=receipt.maximum_total_context_characters,
            policy_version=policy_version,
            required_anchor_eligible_record_ids=eligible_ids,
            method_bridge_assessments=method_bridge_assessments,
        )
    )
    if (
        receipt.selected_candidate_indices != expected_indices
        or receipt.anchor_assignments != expected_assignments
        or receipt.failure_reasons != expected_failures
    ):
        raise ValueError("planning literature anchor selection does not replay")
    if len(receipt.selected_candidate_indices) != len(set(receipt.selected_candidate_indices)):
        raise ValueError("selected candidate indices must be unique")
    if any(
        index < 0 or index >= len(receipt.classifications)
        for index in receipt.selected_candidate_indices
    ):
        raise ValueError("selected candidate index is outside the catalog")
    expected_records = tuple(
        receipt.classifications[index].candidate for index in receipt.selected_candidate_indices
    )
    if receipt.selected_records != expected_records:
        raise ValueError("selected records do not match selected candidate indices")
    if receipt.selected_record_ids != tuple(item.record_id for item in expected_records):
        raise ValueError("selected record IDs do not match selected records")
    if len(receipt.selected_records) > receipt.maximum_records:
        raise ValueError("selected records exceed the maximum")
    selected_classifications = tuple(
        receipt.classifications[index] for index in receipt.selected_candidate_indices
    )
    if receipt.selected_role_counts != _role_counts(selected_classifications):
        raise ValueError("selected planning literature role counts mismatch")
    expected_characters = sum(
        item.effective_context_characters for item in receipt.selected_records
    )
    if receipt.selected_total_context_characters != expected_characters:
        raise ValueError("selected planning literature context size mismatch")
    if (
        receipt.maximum_total_context_characters is not None
        and expected_characters > receipt.maximum_total_context_characters
    ):
        raise ValueError("selected planning literature exceeds the context budget")
    if receipt.passed != (not receipt.failure_reasons):
        raise ValueError("planning literature pass status and failures disagree")
    if not receipt.passed and (
        receipt.selected_records
        or receipt.selected_record_ids
        or receipt.selected_candidate_indices
        or receipt.anchor_assignments
        or receipt.selected_total_context_characters
    ):
        raise ValueError("failed planning coverage must not expose a selected subset")
    if receipt.passed:
        _validate_selected_coverage(
            receipt.classifications,
            receipt.selected_candidate_indices,
            receipt.anchor_assignments,
            required_anchor_eligible_record_ids=eligible_ids,
            method_bridge_assessments=method_bridge_assessments,
        )
    expected_hash = canonical_model_hash(receipt.model_dump(mode="json", exclude={"receipt_hash"}))
    if receipt.receipt_hash != expected_hash:
        raise ValueError("planning literature coverage receipt hash mismatch")


def role_query_from_boolean(
    role: PlanningLiteratureRole | str,
    query_id: str,
    query: str,
) -> PlanningLiteratureRoleQuery:
    """Parse a conservative Boolean query into an AND-of-OR role contract.

    Top-level ``AND`` creates must groups and ``OR`` creates alternatives
    inside a group.  Ambiguous precedence, negation, nested mixed operators,
    unmatched delimiters, and internal wildcards are rejected instead of being
    degraded to a bag of words.
    """

    parsed_role = PlanningLiteratureRole(role)
    groups, prefixes = _parse_boolean_query(query)
    return PlanningLiteratureRoleQuery(
        role=parsed_role,
        query_id=query_id,
        raw_query=query.strip(),
        must_groups=groups,
        prefix_terms=prefixes,
    )


def classify_planning_candidates(
    candidates: Sequence[PlanningLiteratureCandidate],
    role_queries: Sequence[PlanningLiteratureRoleQuery],
) -> tuple[PlanningLiteratureClassification, ...]:
    """Classify candidates by semantic role before looking at quality metadata."""

    return _classify_planning_candidates_for_policy(
        candidates,
        role_queries,
        policy_version="v5",
    )


def _classify_planning_candidates_for_policy(
    candidates: Sequence[PlanningLiteratureCandidate],
    role_queries: Sequence[PlanningLiteratureRoleQuery],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> tuple[PlanningLiteratureClassification, ...]:
    """Classify with the matching rules frozen for one receipt generation."""

    normalized_queries = _validate_role_queries(tuple(role_queries))
    normalized_candidates = tuple(candidates)
    ids = tuple(item.record_id for item in normalized_candidates)
    if len(ids) != len(set(ids)):
        raise PlanningLiteratureCoverageError(
            "planning literature candidate record IDs must be unique"
        )
    return tuple(
        _classify_candidate(
            candidate,
            normalized_queries,
            reject_negated_counterevidence=policy_version in {"v4", "v5"},
        )
        for candidate in normalized_candidates
    )


def select_planning_literature(
    candidates: Sequence[PlanningLiteratureCandidate],
    role_queries: Sequence[PlanningLiteratureRoleQuery],
    *,
    maximum_records: int = 10,
    maximum_total_context_characters: int | None = None,
    required_anchor_eligible_record_ids: Sequence[str] | None = None,
    method_focus_basis_queries: Sequence[PlanningLiteratureRoleQuery] | None = None,
) -> PlanningLiteratureCoverageReceipt:
    """Select a role-complete shortlist, then fill it to the caller's limit.

    Missing semantic roles fail closed with an empty selected subset.  Once the
    fixed coverage gate passes, remaining full-role records are considered by
    fixed semantic layer and quality within that layer. Strong supplements may
    use the remaining caller budget; unverified adjacent work is capped at two,
    and weak records are not used as padding. Partial method-transfer work is
    admitted last and can never outnumber the non-transfer records. Off-topic
    work is never selected.
    """

    if maximum_records < 1:
        raise PlanningLiteratureCoverageError("maximum_records must be positive")
    if maximum_total_context_characters is not None and maximum_total_context_characters < 1:
        raise PlanningLiteratureCoverageError("maximum_total_context_characters must be positive")
    normalized_queries = _validate_role_queries(tuple(role_queries))
    classifications = classify_planning_candidates(candidates, normalized_queries)
    normalized_basis_queries = _validate_method_focus_basis_queries(
        tuple(method_focus_basis_queries or normalized_queries)
    )
    bridge_contract = _method_bridge_contract(normalized_basis_queries)
    bridge_assessments = _method_bridge_assessments(
        classifications,
        basis_queries=normalized_basis_queries,
        contract=bridge_contract,
    )
    candidate_ids = tuple(item.candidate.record_id for item in classifications)
    eligible_ids = (
        candidate_ids
        if required_anchor_eligible_record_ids is None
        else tuple(dict.fromkeys(str(item).strip() for item in required_anchor_eligible_record_ids))
    )
    if any(not item for item in eligible_ids):
        raise PlanningLiteratureCoverageError(
            "required-anchor eligible record IDs must not contain blanks"
        )
    unknown_eligible_ids = set(eligible_ids).difference(candidate_ids)
    if unknown_eligible_ids:
        raise PlanningLiteratureCoverageError(
            "required-anchor eligibility references a record outside the candidate catalog"
        )
    selected, anchor_assignments, failures = _select_classified_planning_literature(
        classifications,
        maximum_records=maximum_records,
        maximum_total_context_characters=maximum_total_context_characters,
        policy_version="v5",
        required_anchor_eligible_record_ids=eligible_ids,
        method_bridge_assessments=bridge_assessments,
    )

    return _build_v5_receipt(
        role_queries=normalized_queries,
        method_focus_basis_queries=normalized_basis_queries,
        method_bridge_contract=bridge_contract,
        classifications=classifications,
        method_bridge_assessments=bridge_assessments,
        maximum_records=maximum_records,
        maximum_total_context_characters=maximum_total_context_characters,
        selected_indices=selected,
        anchor_assignments=anchor_assignments,
        failure_reasons=failures,
        required_anchor_eligible_record_ids=eligible_ids,
    )


@dataclass(frozen=True)
class _AnchorChoice:
    candidate_index: int
    role: PlanningLiteratureRole
    query_id: str
    anchor_id: str
    role_rank: int


@dataclass(frozen=True)
class _AnchorPlan:
    context_characters: int
    total_role_rank: int
    choices: tuple[_AnchorChoice, ...]


def _select_classified_planning_literature(
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    maximum_records: int,
    maximum_total_context_characters: int | None,
    policy_version: Literal["v2", "v3", "v4", "v5"],
    required_anchor_eligible_record_ids: tuple[str, ...],
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...] = (),
) -> tuple[
    tuple[int, ...],
    tuple[PlanningLiteratureAnchorAssignment, ...],
    tuple[str, ...],
]:
    available_failures = _available_coverage_failures(_role_counts(classifications))
    if available_failures:
        return (), (), available_failures
    if policy_version == "v5" and not _method_bridge_complete_family_count(
        classifications,
        method_bridge_assessments,
    ):
        return (), (), ("insufficient_method_focus_bridge_anchors",)
    required_anchor_count = sum(_ROLE_MINIMUMS.values())
    if maximum_records < required_anchor_count:
        return (), (), ("maximum_records_prevents_required_coverage",)

    plan = _required_anchor_plan(
        classifications,
        maximum_total_context_characters=maximum_total_context_characters,
        policy_version=policy_version,
        required_anchor_eligible_record_ids=required_anchor_eligible_record_ids,
        method_bridge_assessments=method_bridge_assessments,
    )
    if plan is None:
        if (
            maximum_total_context_characters is not None
            and _required_anchor_plan(
                classifications,
                maximum_total_context_characters=None,
                policy_version=policy_version,
                required_anchor_eligible_record_ids=required_anchor_eligible_record_ids,
                method_bridge_assessments=method_bridge_assessments,
            )
            is not None
        ):
            return (), (), ("context_budget_prevents_required_coverage",)
        return (), (), ("insufficient_distinct_required_role_anchors",)

    assignments = _anchor_assignments(
        plan,
        classifications,
        policy_version=policy_version,
    )
    selected = [item.candidate_index for item in assignments]
    used_anchors = {item.anchor_id for item in assignments}
    adjacent_supplement_count = 0

    def selected_characters() -> int:
        return sum(
            classifications[index].candidate.effective_context_characters for index in selected
        )

    def can_add(index: int) -> bool:
        candidate = classifications[index].candidate
        if (
            index in selected
            or candidate.effective_anchor_id in used_anchors
            or len(selected) >= maximum_records
        ):
            return False
        if maximum_total_context_characters is None:
            return True
        return (
            selected_characters() + candidate.effective_context_characters
            <= maximum_total_context_characters
        )

    def add(index: int) -> None:
        selected.append(index)
        used_anchors.add(classifications[index].candidate.effective_anchor_id)

    def can_add_supplement(index: int) -> bool:
        if not can_add(index):
            return False
        if (
            policy_version == "v5"
            and classifications[index].semantic_layer
            in {
                PlanningLiteratureRole.METHOD_FOUNDATION,
                PlanningLiteratureRole.METHOD_TRANSFER,
            }
            and not method_bridge_assessments[index].bridge_eligible
        ):
            return False
        if policy_version == "v2":
            return True
        quality = classifications[index].candidate.quality_score
        if quality >= _STRONG_SUPPLEMENT_MINIMUM_QUALITY:
            return True
        return (
            quality >= _ADJACENT_SUPPLEMENT_MINIMUM_QUALITY
            and adjacent_supplement_count < _MAX_ADJACENT_SUPPLEMENTS
        )

    def add_supplement(index: int) -> None:
        nonlocal adjacent_supplement_count
        if (
            policy_version != "v2"
            and classifications[index].candidate.quality_score < _STRONG_SUPPLEMENT_MINIMUM_QUALITY
        ):
            adjacent_supplement_count += 1
        add(index)

    for layer in _REQUIRED_ROLES:
        options = sorted(
            (index for index, item in enumerate(classifications) if item.semantic_layer is layer),
            key=lambda index: _quality_key(
                classifications[index],
                role=layer,
                policy_version=policy_version,
                required_anchor=False,
            ),
        )
        for index in options:
            if can_add_supplement(index):
                add_supplement(index)
            if len(selected) == maximum_records:
                break
        if len(selected) == maximum_records:
            break

    if len(selected) < maximum_records:
        transfer_options = sorted(
            (
                index
                for index, item in enumerate(classifications)
                if item.semantic_layer is PlanningLiteratureRole.METHOD_TRANSFER
            ),
            key=lambda index: _quality_key(
                classifications[index],
                role=PlanningLiteratureRole.METHOD_TRANSFER,
                policy_version=policy_version,
                required_anchor=False,
            ),
        )
        for index in transfer_options:
            transfer_count = sum(
                classifications[selected_index].semantic_layer
                is PlanningLiteratureRole.METHOD_TRANSFER
                for selected_index in selected
            )
            if (transfer_count + 1) * 2 > len(selected) + 1:
                break
            if can_add_supplement(index):
                add_supplement(index)
            if len(selected) == maximum_records:
                break

    return tuple(selected), assignments, ()


def _required_anchor_plan(
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    maximum_total_context_characters: int | None,
    policy_version: Literal["v2", "v3", "v4", "v5"],
    required_anchor_eligible_record_ids: tuple[str, ...],
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...] = (),
) -> _AnchorPlan | None:
    target_state = tuple(_ROLE_MINIMUMS[role] for role in _REQUIRED_ROLES)
    zero_state = (0, 0, 0, 0)
    role_ranks: dict[tuple[int, PlanningLiteratureRole], int] = {}
    eligible_ids = set(required_anchor_eligible_record_ids)
    for role in _REQUIRED_ROLES:
        ranked = sorted(
            (
                index
                for index, item in enumerate(classifications)
                if role in item.matched_roles
                and (policy_version not in {"v4", "v5"} or item.candidate.record_id in eligible_ids)
                and (
                    policy_version != "v5"
                    or role is not PlanningLiteratureRole.METHOD_FOUNDATION
                    or method_bridge_assessments[index].bridge_eligible
                )
            ),
            key=lambda index: _quality_key(
                classifications[index],
                role=role,
                policy_version=policy_version,
                required_anchor=True,
            ),
        )
        role_ranks.update({(index, role): rank for rank, index in enumerate(ranked)})

    family_indices: dict[str, list[int]] = {}
    for index, classification in enumerate(classifications):
        family_indices.setdefault(classification.candidate.effective_anchor_id, []).append(index)

    frontiers: dict[tuple[int, ...], list[_AnchorPlan]] = {
        zero_state: [_AnchorPlan(context_characters=0, total_role_rank=0, choices=())]
    }
    for anchor_id in sorted(family_indices):
        options: list[_AnchorChoice] = []
        for index in family_indices[anchor_id]:
            classification = classifications[index]
            if (
                policy_version in {"v4", "v5"}
                and classification.candidate.record_id not in eligible_ids
            ):
                continue
            for role in classification.matched_roles:
                if (
                    policy_version == "v5"
                    and role is PlanningLiteratureRole.METHOD_FOUNDATION
                    and not method_bridge_assessments[index].bridge_eligible
                ):
                    continue
                match = next(
                    item
                    for item in classification.role_matches
                    if item.complete and item.role is role
                )
                options.append(
                    _AnchorChoice(
                        candidate_index=index,
                        role=role,
                        query_id=match.query_id,
                        anchor_id=anchor_id,
                        role_rank=role_ranks[(index, role)],
                    )
                )
        options.sort(
            key=lambda item: _anchor_choice_sort_key(
                item,
                classifications,
                policy_version=policy_version,
            )
        )
        next_frontiers = {state: list(plans) for state, plans in frontiers.items()}
        for state, plans in frontiers.items():
            for plan in plans:
                for option in options:
                    role_index = _REQUIRED_ROLES.index(option.role)
                    if state[role_index] >= target_state[role_index]:
                        continue
                    candidate = classifications[option.candidate_index].candidate
                    context_characters = (
                        plan.context_characters + candidate.effective_context_characters
                    )
                    if (
                        maximum_total_context_characters is not None
                        and context_characters > maximum_total_context_characters
                    ):
                        continue
                    next_state = list(state)
                    next_state[role_index] += 1
                    next_plan = _AnchorPlan(
                        context_characters=context_characters,
                        total_role_rank=plan.total_role_rank + option.role_rank,
                        choices=(*plan.choices, option),
                    )
                    _insert_anchor_plan(
                        next_frontiers.setdefault(tuple(next_state), []),
                        next_plan,
                        classifications,
                        policy_version=policy_version,
                    )
        frontiers = next_frontiers
    terminal = frontiers.get(target_state, ())
    if not terminal:
        return None
    return min(
        terminal,
        key=lambda item: _anchor_plan_sort_key(
            item,
            classifications,
            policy_version=policy_version,
        ),
    )


def _insert_anchor_plan(
    frontier: list[_AnchorPlan],
    candidate: _AnchorPlan,
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> None:
    candidate_quality = _anchor_plan_quality_key(
        candidate,
        classifications,
        policy_version=policy_version,
    )
    candidate_identity = _anchor_plan_identity_key(
        candidate,
        classifications,
        policy_version=policy_version,
    )
    survivors: list[_AnchorPlan] = []
    for existing in frontier:
        existing_quality = _anchor_plan_quality_key(
            existing,
            classifications,
            policy_version=policy_version,
        )
        existing_dominates = (
            existing.context_characters <= candidate.context_characters
            and existing_quality <= candidate_quality
        )
        candidate_dominates = (
            candidate.context_characters <= existing.context_characters
            and candidate_quality <= existing_quality
        )
        if existing_dominates:
            if (
                existing.context_characters == candidate.context_characters
                and existing_quality == candidate_quality
                and candidate_identity
                < _anchor_plan_identity_key(
                    existing,
                    classifications,
                    policy_version=policy_version,
                )
            ):
                continue
            return
        if not candidate_dominates:
            survivors.append(existing)
    survivors.append(candidate)
    survivors.sort(
        key=lambda item: _anchor_plan_sort_key(
            item,
            classifications,
            policy_version=policy_version,
        )
    )
    frontier[:] = survivors


def _anchor_choice_sort_key(
    choice: _AnchorChoice,
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> tuple[object, ...]:
    classification = classifications[choice.candidate_index]
    return (
        _REQUIRED_ROLES.index(choice.role),
        _quality_key(
            classification,
            role=choice.role,
            policy_version=policy_version,
            required_anchor=True,
        ),
        choice.anchor_id,
        classification.candidate.record_id,
    )


def _anchor_plan_sort_key(
    plan: _AnchorPlan,
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> tuple[object, ...]:
    quality_key = _anchor_plan_quality_key(
        plan,
        classifications,
        policy_version=policy_version,
    )
    return (
        quality_key[0],
        quality_key[1],
        plan.context_characters,
        _anchor_plan_identity_key(
            plan,
            classifications,
            policy_version=policy_version,
        ),
    )


def _anchor_plan_quality_key(
    plan: _AnchorPlan,
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> tuple[object, ...]:
    ordered_choices = tuple(
        sorted(
            plan.choices,
            key=lambda item: _anchor_choice_sort_key(
                item,
                classifications,
                policy_version=policy_version,
            ),
        )
    )
    return (
        plan.total_role_rank,
        tuple(
            (
                _REQUIRED_ROLES.index(choice.role),
                _quality_key(
                    classifications[choice.candidate_index],
                    role=choice.role,
                    policy_version=policy_version,
                    required_anchor=True,
                ),
            )
            for choice in ordered_choices
        ),
    )


def _anchor_plan_identity_key(
    plan: _AnchorPlan,
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> tuple[tuple[str, str, str], ...]:
    ordered_choices = tuple(
        sorted(
            plan.choices,
            key=lambda item: _anchor_choice_sort_key(
                item,
                classifications,
                policy_version=policy_version,
            ),
        )
    )
    return tuple(
        (
            choice.role.value,
            choice.anchor_id,
            classifications[choice.candidate_index].candidate.record_id,
        )
        for choice in ordered_choices
    )


def _anchor_assignments(
    plan: _AnchorPlan,
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    policy_version: Literal["v2", "v3", "v4", "v5"],
) -> tuple[PlanningLiteratureAnchorAssignment, ...]:
    choices = sorted(
        plan.choices,
        key=lambda item: _anchor_choice_sort_key(
            item,
            classifications,
            policy_version=policy_version,
        ),
    )
    return tuple(
        PlanningLiteratureAnchorAssignment(
            role=choice.role,
            query_id=choice.query_id,
            record_id=classifications[choice.candidate_index].candidate.record_id,
            candidate_index=choice.candidate_index,
            anchor_id=choice.anchor_id,
        )
        for choice in choices
    )


def _build_v4_receipt(
    *,
    role_queries: tuple[PlanningLiteratureRoleQuery, ...],
    classifications: tuple[PlanningLiteratureClassification, ...],
    maximum_records: int,
    maximum_total_context_characters: int | None,
    selected_indices: tuple[int, ...],
    anchor_assignments: tuple[PlanningLiteratureAnchorAssignment, ...],
    failure_reasons: tuple[str, ...],
    required_anchor_eligible_record_ids: tuple[str, ...],
) -> PlanningLiteratureCoverageReceiptV4:
    selected = tuple(classifications[index] for index in selected_indices)
    selected_records = tuple(item.candidate for item in selected)
    payload = {
        "schema_version": "contest-planning-literature-coverage-v4",
        "role_queries": [item.model_dump(mode="json") for item in role_queries],
        "classifications": [item.model_dump(mode="json") for item in classifications],
        "thresholds": PlanningLiteratureCoverageThresholds().model_dump(mode="json"),
        "candidate_count": len(classifications),
        "maximum_records": maximum_records,
        "maximum_total_context_characters": maximum_total_context_characters,
        "available_role_counts": _role_counts(classifications).model_dump(mode="json"),
        "selected_role_counts": _role_counts(selected).model_dump(mode="json"),
        "required_anchor_eligible_record_ids": list(required_anchor_eligible_record_ids),
        "selected_record_ids": [item.record_id for item in selected_records],
        "selected_candidate_indices": list(selected_indices),
        "selected_records": [item.model_dump(mode="json") for item in selected_records],
        "anchor_assignments": [item.model_dump(mode="json") for item in anchor_assignments],
        "selected_total_context_characters": sum(
            item.effective_context_characters for item in selected_records
        ),
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        "passed": not failure_reasons,
        "selection_semantics": (
            "targeted_lineage_distinct_anchor_semantic_first_dp_then_" "quality_limited_supplements"
        ),
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    return PlanningLiteratureCoverageReceiptV4.model_validate(payload)


def _build_v5_receipt(
    *,
    role_queries: tuple[PlanningLiteratureRoleQuery, ...],
    method_focus_basis_queries: tuple[PlanningLiteratureRoleQuery, ...],
    method_bridge_contract: PlanningLiteratureMethodBridgeContract,
    classifications: tuple[PlanningLiteratureClassification, ...],
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...],
    maximum_records: int,
    maximum_total_context_characters: int | None,
    selected_indices: tuple[int, ...],
    anchor_assignments: tuple[PlanningLiteratureAnchorAssignment, ...],
    failure_reasons: tuple[str, ...],
    required_anchor_eligible_record_ids: tuple[str, ...],
) -> PlanningLiteratureCoverageReceipt:
    selected = tuple(classifications[index] for index in selected_indices)
    selected_records = tuple(item.candidate for item in selected)
    payload = {
        "schema_version": "contest-planning-literature-coverage-v5",
        "role_queries": [item.model_dump(mode="json") for item in role_queries],
        "method_focus_basis_queries": [
            item.model_dump(mode="json") for item in method_focus_basis_queries
        ],
        "method_bridge_contract": method_bridge_contract.model_dump(mode="json"),
        "classifications": [item.model_dump(mode="json") for item in classifications],
        "method_bridge_assessments": [
            item.model_dump(mode="json") for item in method_bridge_assessments
        ],
        "thresholds": PlanningLiteratureCoverageThresholds().model_dump(mode="json"),
        "candidate_count": len(classifications),
        "maximum_records": maximum_records,
        "maximum_total_context_characters": maximum_total_context_characters,
        "available_role_counts": _role_counts(classifications).model_dump(mode="json"),
        "eligible_role_family_counts": _eligible_required_role_family_counts(
            classifications,
            required_anchor_eligible_record_ids=required_anchor_eligible_record_ids,
            method_bridge_assessments=method_bridge_assessments,
        ).model_dump(mode="json"),
        "selected_role_counts": _role_counts(selected).model_dump(mode="json"),
        "required_anchor_eligible_record_ids": list(required_anchor_eligible_record_ids),
        "selected_record_ids": [item.record_id for item in selected_records],
        "selected_candidate_indices": list(selected_indices),
        "selected_records": [item.model_dump(mode="json") for item in selected_records],
        "anchor_assignments": [item.model_dump(mode="json") for item in anchor_assignments],
        "selected_total_context_characters": sum(
            item.effective_context_characters for item in selected_records
        ),
        "failure_reasons": list(dict.fromkeys(failure_reasons)),
        "passed": not failure_reasons,
        "selection_semantics": (
            "immutable_focus_bridge_then_authority_distinct_anchor_dp_and_" "bridged_supplements"
        ),
    }
    payload["receipt_hash"] = canonical_model_hash(payload)
    return PlanningLiteratureCoverageReceipt.model_validate(payload)


def _classify_candidate(
    candidate: PlanningLiteratureCandidate,
    role_queries: tuple[PlanningLiteratureRoleQuery, ...],
    *,
    reject_negated_counterevidence: bool,
) -> PlanningLiteratureClassification:
    normalized_fields: dict[str, str] = {
        "title": _normalize_for_match(candidate.title),
        "abstract": _normalize_for_match(candidate.abstract or ""),
    }
    complete_matches: list[PlanningLiteratureRoleMatch] = []
    partial_method_match: PlanningLiteratureRoleMatch | None = None
    for query in role_queries:
        matched_groups = _matched_groups(
            query,
            normalized_fields,
            reject_negated_counterevidence=reject_negated_counterevidence,
        )
        lineage = tuple(item for item in candidate.retrieval_queries if item == query.raw_query)
        if (
            len(matched_groups) == len(query.must_groups)
            and lineage
            and "targeted_direction" in candidate.source_stages
        ):
            complete_matches.append(
                PlanningLiteratureRoleMatch(
                    role=query.role,
                    query_id=query.query_id,
                    complete=True,
                    matched_groups=matched_groups,
                    matched_retrieval_queries=lineage,
                    source_stages=candidate.source_stages,
                )
            )
        elif query.role is PlanningLiteratureRole.METHOD_FOUNDATION and matched_groups:
            partial_method_match = PlanningLiteratureRoleMatch(
                role=query.role,
                query_id=query.query_id,
                complete=False,
                matched_groups=matched_groups,
                matched_retrieval_queries=lineage,
                source_stages=candidate.source_stages,
            )

    complete_matches.sort(key=lambda item: _REQUIRED_ROLES.index(item.role))
    matched_roles = tuple(item.role for item in complete_matches)
    if PlanningLiteratureRole.DIRECT_CORE in matched_roles:
        semantic_layer = PlanningLiteratureRole.DIRECT_CORE
    elif PlanningLiteratureRole.METHOD_FOUNDATION in matched_roles:
        semantic_layer = PlanningLiteratureRole.METHOD_FOUNDATION
    elif PlanningLiteratureRole.MECHANISM_OR_NULL in matched_roles:
        semantic_layer = PlanningLiteratureRole.MECHANISM_OR_NULL
    elif PlanningLiteratureRole.COUNTEREVIDENCE in matched_roles:
        semantic_layer = PlanningLiteratureRole.COUNTEREVIDENCE
    elif partial_method_match is not None:
        semantic_layer = PlanningLiteratureRole.METHOD_TRANSFER
    else:
        semantic_layer = PlanningLiteratureRole.OFF_TOPIC

    role_matches: tuple[PlanningLiteratureRoleMatch, ...]
    if complete_matches:
        role_matches = tuple(complete_matches)
    elif partial_method_match is not None:
        role_matches = (partial_method_match,)
    else:
        role_matches = ()
    return PlanningLiteratureClassification(
        candidate=candidate,
        candidate_hash=canonical_model_hash(candidate),
        semantic_layer=semantic_layer,
        matched_roles=matched_roles,
        role_matches=role_matches,
    )


def _matched_groups(
    query: PlanningLiteratureRoleQuery,
    normalized_fields: dict[str, str],
    *,
    reject_negated_counterevidence: bool,
) -> tuple[PlanningLiteratureMatchedGroup, ...]:
    matches: list[PlanningLiteratureMatchedGroup] = []
    prefix_terms = set(query.prefix_terms)
    for index, alternatives in enumerate(query.must_groups, start=1):
        terms: list[str] = []
        fields: list[Literal["title", "abstract"]] = []
        for term in alternatives:
            term_fields = tuple(
                field
                for field, text in normalized_fields.items()
                if _contains_term(
                    text,
                    term,
                    prefix=term in prefix_terms,
                    reject_negated=(
                        reject_negated_counterevidence
                        and query.role is PlanningLiteratureRole.COUNTEREVIDENCE
                    ),
                )
            )
            if not term_fields:
                continue
            terms.append(term)
            for field in term_fields:
                if field not in fields:
                    fields.append(field)  # type: ignore[arg-type]
        if terms:
            matches.append(
                PlanningLiteratureMatchedGroup(
                    group_index=index,
                    matched_terms=tuple(terms),
                    matched_fields=tuple(fields),
                )
            )
    return tuple(matches)


def _validate_role_queries(
    role_queries: tuple[PlanningLiteratureRoleQuery, ...],
) -> tuple[PlanningLiteratureRoleQuery, ...]:
    roles = tuple(item.role for item in role_queries)
    if len(role_queries) != len(_REQUIRED_ROLES) or set(roles) != set(_REQUIRED_ROLES):
        raise PlanningLiteratureCoverageError(
            "exactly one query is required for each planning literature evidence role"
        )
    query_ids = tuple(item.query_id for item in role_queries)
    if len(query_ids) != len(set(query_ids)):
        raise PlanningLiteratureCoverageError("planning literature query IDs must be unique")
    by_role = {item.role: item for item in role_queries}
    return tuple(by_role[role] for role in _REQUIRED_ROLES)


def _validate_method_focus_basis_queries(
    role_queries: tuple[PlanningLiteratureRoleQuery, ...],
) -> tuple[PlanningLiteratureRoleQuery, ...]:
    normalized = _validate_role_queries(role_queries)
    direct_query = normalized[_REQUIRED_ROLES.index(PlanningLiteratureRole.DIRECT_CORE)]
    if len(direct_query.must_groups) < 2:
        raise PlanningLiteratureCoverageError(
            "method focus basis requires a direct object group and a focus group"
        )
    return normalized


def _method_bridge_contract(
    basis_queries: tuple[PlanningLiteratureRoleQuery, ...],
) -> PlanningLiteratureMethodBridgeContract:
    by_role = {item.role: item for item in basis_queries}
    direct_query = by_role[PlanningLiteratureRole.DIRECT_CORE]
    method_query = by_role[PlanningLiteratureRole.METHOD_FOUNDATION]
    direct_object_terms = direct_query.must_groups[0]
    direct_focus_terms = tuple(
        sorted(
            {term for group in direct_query.must_groups[1:] for term in group},
            key=_semantic_sort_key,
        )
    )
    method_basis_terms = method_query.must_groups[0]
    shared_focus_terms = tuple(
        sorted(
            set(direct_focus_terms).intersection(method_basis_terms),
            key=_semantic_sort_key,
        )
    )
    return PlanningLiteratureMethodBridgeContract(
        direct_query_id=direct_query.query_id,
        method_query_id=method_query.query_id,
        direct_object_terms=direct_object_terms,
        direct_focus_terms=direct_focus_terms,
        method_basis_terms=method_basis_terms,
        shared_focus_terms=shared_focus_terms,
    )


def _method_bridge_assessments(
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    basis_queries: tuple[PlanningLiteratureRoleQuery, ...],
    contract: PlanningLiteratureMethodBridgeContract,
) -> tuple[PlanningLiteratureMethodBridgeAssessment, ...]:
    by_role = {item.role: item for item in basis_queries}
    direct_query = by_role[PlanningLiteratureRole.DIRECT_CORE]
    method_query = by_role[PlanningLiteratureRole.METHOD_FOUNDATION]
    shared_prefix_terms = set(direct_query.prefix_terms).union(method_query.prefix_terms)
    direct_prefix_terms = set(direct_query.prefix_terms)
    assessments: list[PlanningLiteratureMethodBridgeAssessment] = []
    for index, classification in enumerate(classifications):
        method_candidate = any(
            match.role is PlanningLiteratureRole.METHOD_FOUNDATION
            for match in classification.role_matches
        )
        if not method_candidate:
            assessments.append(
                PlanningLiteratureMethodBridgeAssessment(
                    candidate_index=index,
                    record_id=classification.candidate.record_id,
                    bridge_kind="not_method_candidate",
                    bridge_eligible=False,
                )
            )
            continue
        shared_matches = _method_bridge_term_matches(
            classification.candidate,
            contract.shared_focus_terms,
            prefix_terms=shared_prefix_terms,
        )
        direct_matches = _method_bridge_term_matches(
            classification.candidate,
            contract.direct_object_terms,
            prefix_terms=direct_prefix_terms,
        )
        kind: Literal[
            "unbridged_method",
            "shared_focus",
            "direct_object",
            "shared_focus_and_direct_object",
        ]
        if shared_matches and direct_matches:
            kind = "shared_focus_and_direct_object"
        elif shared_matches:
            kind = "shared_focus"
        elif direct_matches:
            kind = "direct_object"
        else:
            kind = "unbridged_method"
        assessments.append(
            PlanningLiteratureMethodBridgeAssessment(
                candidate_index=index,
                record_id=classification.candidate.record_id,
                bridge_kind=kind,
                shared_focus_matches=shared_matches,
                direct_object_matches=direct_matches,
                bridge_eligible=bool(shared_matches or direct_matches),
            )
        )
    return tuple(assessments)


def _method_bridge_term_matches(
    candidate: PlanningLiteratureCandidate,
    terms: Sequence[str],
    *,
    prefix_terms: set[str],
) -> tuple[PlanningLiteratureMethodBridgeTermMatch, ...]:
    normalized_fields: dict[Literal["title", "abstract"], str] = {
        "title": _normalize_for_match(candidate.title),
        "abstract": _normalize_for_match(candidate.abstract or ""),
    }
    matches: list[PlanningLiteratureMethodBridgeTermMatch] = []
    for term in terms:
        fields = tuple(
            field
            for field, value in normalized_fields.items()
            if _contains_term(
                value,
                term,
                prefix=term in prefix_terms,
                reject_negated=False,
            )
        )
        if fields:
            matches.append(
                PlanningLiteratureMethodBridgeTermMatch(
                    term=term,
                    matched_fields=fields,
                )
            )
    return tuple(matches)


def _method_bridge_complete_family_count(
    classifications: tuple[PlanningLiteratureClassification, ...],
    assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...],
) -> int:
    if len(classifications) != len(assessments):
        raise PlanningLiteratureCoverageError(
            "planning literature classifications and method bridge assessments differ in size"
        )
    return len(
        {
            classification.candidate.effective_anchor_id
            for classification, assessment in zip(classifications, assessments, strict=True)
            if PlanningLiteratureRole.METHOD_FOUNDATION in classification.matched_roles
            and assessment.bridge_eligible
        }
    )


def _eligible_required_role_family_counts(
    classifications: tuple[PlanningLiteratureClassification, ...],
    *,
    required_anchor_eligible_record_ids: tuple[str, ...],
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...],
) -> PlanningLiteratureRequiredRoleEligibleFamilyCounts:
    if len(classifications) != len(method_bridge_assessments):
        raise PlanningLiteratureCoverageError(
            "planning literature classifications and method bridge assessments differ in size"
        )
    eligible_ids = set(required_anchor_eligible_record_ids)

    def count(role: PlanningLiteratureRole) -> int:
        return len(
            {
                classification.candidate.effective_anchor_id
                for classification, assessment in zip(
                    classifications,
                    method_bridge_assessments,
                    strict=True,
                )
                if classification.candidate.record_id in eligible_ids
                and role in classification.matched_roles
                and (
                    role is not PlanningLiteratureRole.METHOD_FOUNDATION
                    or assessment.bridge_eligible
                )
            }
        )

    return PlanningLiteratureRequiredRoleEligibleFamilyCounts(
        direct_core=count(PlanningLiteratureRole.DIRECT_CORE),
        method_foundation=count(PlanningLiteratureRole.METHOD_FOUNDATION),
        mechanism_or_null=count(PlanningLiteratureRole.MECHANISM_OR_NULL),
        counterevidence=count(PlanningLiteratureRole.COUNTEREVIDENCE),
    )


def _available_coverage_failures(
    counts: PlanningLiteratureRoleCounts,
) -> tuple[str, ...]:
    failures: list[str] = []
    for role, minimum in _ROLE_MINIMUMS.items():
        if getattr(counts, role.value) < minimum:
            failures.append(f"insufficient_{role.value}")
    return tuple(failures)


def _validate_selected_coverage(
    classifications: tuple[PlanningLiteratureClassification, ...],
    selected_indices: tuple[int, ...],
    assignments: tuple[PlanningLiteratureAnchorAssignment, ...],
    *,
    required_anchor_eligible_record_ids: tuple[str, ...],
    method_bridge_assessments: tuple[PlanningLiteratureMethodBridgeAssessment, ...] = (),
) -> None:
    selected = tuple(classifications[index] for index in selected_indices)
    selected_anchors = tuple(item.candidate.effective_anchor_id for item in selected)
    if len(selected_anchors) != len(set(selected_anchors)):
        raise ValueError("selected planning literature work-family anchors must be unique")
    expected_assignment_count = sum(_ROLE_MINIMUMS.values())
    if len(assignments) != expected_assignment_count:
        raise ValueError("planning literature requires exactly five anchor assignments")
    if len({item.candidate_index for item in assignments}) != len(assignments):
        raise ValueError("one planning candidate cannot fill multiple required role slots")
    if len({item.record_id for item in assignments}) != len(assignments):
        raise ValueError("one planning record cannot fill multiple required role slots")
    if len({item.anchor_id for item in assignments}) != len(assignments):
        raise ValueError("one work-family anchor cannot fill multiple required role slots")
    selected_index_set = set(selected_indices)
    eligible_ids = set(required_anchor_eligible_record_ids)
    if method_bridge_assessments:
        if len(method_bridge_assessments) != len(classifications):
            raise ValueError("method bridge assessments differ from the candidate catalog")
        if any(
            classifications[index].semantic_layer
            in {
                PlanningLiteratureRole.METHOD_FOUNDATION,
                PlanningLiteratureRole.METHOD_TRANSFER,
            }
            and not method_bridge_assessments[index].bridge_eligible
            for index in selected_indices
        ):
            raise ValueError("selected method literature lacks an immutable focus bridge")
    for role, minimum in _ROLE_MINIMUMS.items():
        if sum(item.role is role for item in assignments) != minimum:
            raise ValueError("planning literature anchor role quotas are incomplete")
    for assignment in assignments:
        if assignment.candidate_index not in selected_index_set:
            raise ValueError("planning literature anchor is not in the selected subset")
        if assignment.record_id not in eligible_ids:
            raise ValueError("planning literature anchor lacks required authority eligibility")
        if (
            assignment.role is PlanningLiteratureRole.METHOD_FOUNDATION
            and method_bridge_assessments
            and not method_bridge_assessments[assignment.candidate_index].bridge_eligible
        ):
            raise ValueError("method foundation anchor lacks an immutable focus bridge")
        classification = classifications[assignment.candidate_index]
        if (
            assignment.record_id != classification.candidate.record_id
            or assignment.anchor_id != classification.candidate.effective_anchor_id
        ):
            raise ValueError("planning literature anchor identity mismatch")
        if not any(
            match.complete
            and match.role is assignment.role
            and match.query_id == assignment.query_id
            for match in classification.role_matches
        ):
            raise ValueError("planning literature anchor lacks its complete role-query trace")
    counts = _role_counts(selected)
    if counts.method_transfer * 2 > len(selected):
        raise ValueError("method-transfer literature must not be a selected majority")
    if counts.off_topic:
        raise ValueError("off-topic literature must not enter the selected shortlist")


def _role_counts(
    classifications: Sequence[PlanningLiteratureClassification],
) -> PlanningLiteratureRoleCounts:
    return PlanningLiteratureRoleCounts(
        direct_core=len(
            {
                item.candidate.effective_anchor_id
                for item in classifications
                if PlanningLiteratureRole.DIRECT_CORE in item.matched_roles
            }
        ),
        method_foundation=len(
            {
                item.candidate.effective_anchor_id
                for item in classifications
                if PlanningLiteratureRole.METHOD_FOUNDATION in item.matched_roles
            }
        ),
        mechanism_or_null=len(
            {
                item.candidate.effective_anchor_id
                for item in classifications
                if PlanningLiteratureRole.MECHANISM_OR_NULL in item.matched_roles
            }
        ),
        counterevidence=len(
            {
                item.candidate.effective_anchor_id
                for item in classifications
                if PlanningLiteratureRole.COUNTEREVIDENCE in item.matched_roles
            }
        ),
        method_transfer=len(
            {
                item.candidate.effective_anchor_id
                for item in classifications
                if item.semantic_layer is PlanningLiteratureRole.METHOD_TRANSFER
            }
        ),
        off_topic=len(
            {
                item.candidate.effective_anchor_id
                for item in classifications
                if item.semantic_layer is PlanningLiteratureRole.OFF_TOPIC
            }
        ),
    )


def _quality_key(
    classification: PlanningLiteratureClassification,
    *,
    role: PlanningLiteratureRole | None = None,
    policy_version: Literal["v2", "v3", "v4", "v5"],
    required_anchor: bool,
) -> tuple[object, ...]:
    candidate = classification.candidate
    if policy_version == "v2":
        bibliometric_rank = candidate.citation_count if candidate.citation_count is not None else -1
        return (
            -candidate.quality_score,
            -bibliometric_rank,
            _normalize_for_match(candidate.title),
            candidate.record_id,
        )
    matched_term_count, title_group_count = _semantic_match_specificity(
        classification,
        role=role,
    )
    if policy_version == "v4" and required_anchor:
        return (
            -matched_term_count,
            -title_group_count,
            -candidate.quality_score,
            -_bounded_bibliometric_rank(candidate.citation_count),
            _normalize_for_match(candidate.title),
            candidate.record_id,
        )
    if policy_version == "v5" and required_anchor:
        return (
            -title_group_count,
            -candidate.quality_score,
            -_bounded_bibliometric_rank(candidate.citation_count),
            _normalize_for_match(candidate.title),
            candidate.record_id,
        )
    if policy_version == "v5":
        return (
            -candidate.quality_score,
            -title_group_count,
            -_bounded_bibliometric_rank(candidate.citation_count),
            _normalize_for_match(candidate.title),
            candidate.record_id,
        )
    return (
        -candidate.quality_score,
        -matched_term_count,
        -title_group_count,
        -_bounded_bibliometric_rank(candidate.citation_count),
        _normalize_for_match(candidate.title),
        candidate.record_id,
    )


def _semantic_match_specificity(
    classification: PlanningLiteratureClassification,
    *,
    role: PlanningLiteratureRole | None,
) -> tuple[int, int]:
    """Rank only complete evidence for the role currently being assigned.

    The first component counts distinct alternatives actually found across the
    role's must-groups.  The second records how many of those groups also have
    a title hit.  This is a deterministic specificity tie-break, not a new
    semantic eligibility rule: every candidate has already passed all required
    groups and exact targeted-query lineage before reaching this function.
    """

    effective_role = role
    if effective_role is None and classification.semantic_layer in _REQUIRED_ROLES:
        effective_role = classification.semantic_layer
    complete_matches = tuple(
        match
        for match in classification.role_matches
        if match.complete and (effective_role is None or match.role is effective_role)
    )
    distinct_terms = {
        term.casefold()
        for match in complete_matches
        for group in match.matched_groups
        for term in group.matched_terms
    }
    title_groups = {
        (match.query_id, group.group_index)
        for match in complete_matches
        for group in match.matched_groups
        if "title" in group.matched_fields
    }
    return len(distinct_terms), len(title_groups)


def _bounded_bibliometric_rank(citation_count: int | None) -> int:
    """Return a capped secondary signal so citation magnitude cannot dominate quality."""

    if citation_count is None or citation_count <= 0:
        return 0
    if citation_count < 10:
        return 1
    if citation_count < 100:
        return 2
    if citation_count < 1_000:
        return 3
    return 4


def _parse_boolean_query(query: str) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    expression = query.strip()
    if not expression:
        raise PlanningLiteratureCoverageError("role query must not be blank")
    if "\\" in expression:
        raise PlanningLiteratureCoverageError("escaped query syntax is not supported")
    expression = _strip_outer_parentheses(expression)
    operators = _top_level_operators(expression)
    operator_names = {item[2] for item in operators}
    if "NOT" in operator_names or ("AND" in operator_names and "OR" in operator_names):
        raise PlanningLiteratureCoverageError(
            "role query uses negation or ambiguous top-level Boolean precedence"
        )

    if operator_names == {"AND"}:
        clauses = _split_on_operator(expression, operators, "AND")
    elif operator_names == {"OR"} or not operators:
        clauses = (expression,)
    else:
        raise PlanningLiteratureCoverageError("unsupported role query Boolean structure")

    groups: list[tuple[str, ...]] = []
    prefix_terms: list[str] = []
    for clause in clauses:
        alternatives = _parse_or_clause(clause)
        cleaned: list[str] = []
        for atom in alternatives:
            term, prefix = _clean_boolean_atom(atom)
            cleaned.append(term)
            if prefix:
                prefix_terms.append(term)
        unique = tuple(sorted(set(cleaned), key=_semantic_sort_key))
        if not unique:
            raise PlanningLiteratureCoverageError("role query contains an empty must group")
        groups.append(unique)
    if len(groups) != len(set(groups)):
        raise PlanningLiteratureCoverageError("role query contains duplicate must groups")
    return tuple(groups), tuple(sorted(set(prefix_terms), key=_semantic_sort_key))


def _parse_or_clause(clause: str) -> tuple[str, ...]:
    expression = _strip_outer_parentheses(clause.strip())
    operators = _top_level_operators(expression)
    names = {item[2] for item in operators}
    if "NOT" in names or "AND" in names:
        raise PlanningLiteratureCoverageError(
            "must groups may contain OR alternatives but not nested AND/NOT"
        )
    if not operators:
        return (expression,)
    if names != {"OR"}:
        raise PlanningLiteratureCoverageError("unsupported operator inside a must group")
    atoms = _split_on_operator(expression, operators, "OR")
    flattened: list[str] = []
    for atom in atoms:
        nested = _strip_outer_parentheses(atom.strip())
        nested_operators = _top_level_operators(nested)
        if nested_operators:
            if {item[2] for item in nested_operators} != {"OR"}:
                raise PlanningLiteratureCoverageError(
                    "nested must-group structure is not a pure OR expression"
                )
            flattened.extend(_parse_or_clause(nested))
        else:
            flattened.append(nested)
    return tuple(flattened)


def _clean_boolean_atom(atom: str) -> tuple[str, bool]:
    value = atom.strip()
    if not value:
        raise PlanningLiteratureCoverageError("role query contains an empty term")
    was_quoted = False
    if value[0:1] in {'"', "'"}:
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise PlanningLiteratureCoverageError("role query contains unmatched quotes")
        value = value[1:-1].strip()
        was_quoted = True
    if any(character in value for character in "\"'()"):
        raise PlanningLiteratureCoverageError(
            "role query term contains unsupported quotes or parentheses"
        )
    if not was_quoted and ":" in value:
        raise PlanningLiteratureCoverageError("field-qualified role query terms are not supported")
    if not was_quoted and re.search(r"(?i)(?<![\w])(?:AND|OR|NOT)(?![\w])", value):
        raise PlanningLiteratureCoverageError("role query term contains a Boolean operator")
    wildcard_positions = tuple(index for index, character in enumerate(value) if character in "*?")
    prefix = False
    if wildcard_positions:
        first = wildcard_positions[0]
        suffix = value[first:]
        if first == 0 or not value[first - 1].isalnum() or set(suffix) - {"*", "?"}:
            raise PlanningLiteratureCoverageError("only a trailing term wildcard is supported")
        value = value[:first].rstrip()
        prefix = True
    value = " ".join(unicodedata.normalize("NFC", value).casefold().split())
    if not _normalize_for_match(value):
        raise PlanningLiteratureCoverageError("role query term has no searchable content")
    return value, prefix


def _top_level_operators(expression: str) -> tuple[tuple[int, int, str], ...]:
    operators: list[tuple[int, int, str]] = []
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(expression):
        character = expression[index]
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
            if depth < 0:
                raise PlanningLiteratureCoverageError("role query parentheses are unbalanced")
            index += 1
            continue
        if depth == 0:
            match = re.match(r"(?i)(AND|OR|NOT)(?![\w])", expression[index:])
            previous = expression[index - 1] if index else " "
            if match is not None and not (previous.isalnum() or previous == "_"):
                name = match.group(1).upper()
                operators.append((index, index + len(match.group(1)), name))
                index += len(match.group(1))
                continue
        index += 1
    if quote is not None:
        raise PlanningLiteratureCoverageError("role query quotes are unbalanced")
    if depth:
        raise PlanningLiteratureCoverageError("role query parentheses are unbalanced")
    return tuple(operators)


def _split_on_operator(
    expression: str,
    operators: tuple[tuple[int, int, str], ...],
    operator: str,
) -> tuple[str, ...]:
    selected = tuple(item for item in operators if item[2] == operator)
    parts: list[str] = []
    cursor = 0
    for start, end, _ in selected:
        part = expression[cursor:start].strip()
        if not part:
            raise PlanningLiteratureCoverageError("role query has a missing Boolean operand")
        parts.append(part)
        cursor = end
    final = expression[cursor:].strip()
    if not final:
        raise PlanningLiteratureCoverageError("role query has a missing Boolean operand")
    parts.append(final)
    return tuple(parts)


def _strip_outer_parentheses(expression: str) -> str:
    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quote: str | None = None
        closes_at_end = False
        for index, character in enumerate(value):
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
                if depth < 0:
                    raise PlanningLiteratureCoverageError("role query parentheses are unbalanced")
                if depth == 0:
                    closes_at_end = index == len(value) - 1
                    break
        if quote is not None:
            raise PlanningLiteratureCoverageError("role query quotes are unbalanced")
        if depth != 0 or not closes_at_end:
            break
        value = value[1:-1].strip()
    if not value:
        raise PlanningLiteratureCoverageError("role query has an empty expression")
    _top_level_operators(value)
    return value


def _contains_term(
    normalized_text: str,
    term: str,
    *,
    prefix: bool,
    reject_negated: bool = False,
) -> bool:
    normalized_term = _normalize_for_match(term)
    if not normalized_term or not normalized_text:
        return False
    if _contains_cjk(normalized_term):
        compact_term = normalized_term.replace(" ", "")
        compact_text = normalized_text.replace(" ", "")
        if compact_term not in compact_text:
            return False
        if not reject_negated:
            return True
        return not any(
            marker + compact_term in compact_text
            for marker in ("无", "没有", "未见", "不存在", "零")
        )
    text_tokens = normalized_text.split()
    term_tokens = normalized_term.split()
    if len(term_tokens) > len(text_tokens):
        return False
    width = len(term_tokens)
    for start in range(len(text_tokens) - width + 1):
        window = text_tokens[start : start + width]
        if _phrase_tokens_match(window, term_tokens, prefix=prefix) and (
            not reject_negated or not _match_is_negated(text_tokens, start)
        ):
            return True
    if width < 2 or len(text_tokens) <= width:
        return False
    expanded_width = width + 1
    for start in range(len(text_tokens) - expanded_width + 1):
        window = text_tokens[start : start + expanded_width]
        for inserted_index in range(1, expanded_width - 1):
            without_insertion = [
                token for index, token in enumerate(window) if index != inserted_index
            ]
            if _phrase_tokens_match(without_insertion, term_tokens, prefix=prefix) and (
                not reject_negated or not _match_is_negated(text_tokens, start)
            ):
                return True
    return False


def _match_is_negated(tokens: Sequence[str], start: int) -> bool:
    """Conservatively reject counterevidence terms under a short negation scope."""

    scope = tokens[max(0, start - 3) : start]
    return any(
        token
        in {
            "no",
            "not",
            "without",
            "zero",
            "absence",
            "absent",
            "lack",
            "lacks",
            "lacking",
            "never",
            "neither",
        }
        for token in scope
    )


def _phrase_tokens_match(
    text_tokens: Sequence[str],
    term_tokens: Sequence[str],
    *,
    prefix: bool,
) -> bool:
    if len(text_tokens) != len(term_tokens):
        return False
    last_index = len(term_tokens) - 1
    return all(
        _english_token_matches(
            text_token,
            term_token,
            prefix=prefix and index == last_index,
        )
        for index, (text_token, term_token) in enumerate(zip(text_tokens, term_tokens, strict=True))
    )


def _english_token_matches(text_token: str, term_token: str, *, prefix: bool) -> bool:
    if prefix:
        return text_token.startswith(term_token)
    if text_token == term_token:
        return True
    return (
        _regular_english_plural(text_token) == term_token
        or _regular_english_plural(term_token) == text_token
    )


def _regular_english_plural(token: str) -> str | None:
    if len(token) < 2 or not token.isascii() or not token.isalpha():
        return None
    if token.endswith("is") and len(token) >= 4:
        return f"{token[:-2]}es"
    if token.endswith("y") and token[-2] not in "aeiou":
        return f"{token[:-1]}ies"
    if token.endswith(("ch", "sh", "s", "x", "z")):
        return f"{token}es"
    return f"{token}s"


def _normalize_for_match(value: str) -> str:
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


def _semantic_sort_key(value: str) -> tuple[str, str]:
    return _normalize_for_match(value), value


def _lineage_sort_key(value: str) -> str:
    return " ".join(value.casefold().split())
