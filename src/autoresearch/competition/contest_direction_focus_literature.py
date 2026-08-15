"""Evidence-grounded focus selection followed by direction-targeted retrieval.

This sibling component fills the narrow gap between a broad, strictly loaded
literature artifact and the existing Skill router.  Strict loading verifies
provenance/hash bindings but does not imply publication-status rechecking.  The
component deliberately has no Skill
input: a model first proposes a few provisional research foci from bibliographic
evidence, an independent model call selects one, and only then is the existing
real-search boundary invoked again for that selected focus.

The component is intentionally not wired into the main direction loop here.  It
provides a stable, resumable API and immutable artifacts so that the loop can
adopt it in a separate integration change.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, JsonValue, model_validator

from autoresearch.competition.contest_adapter_semantics import (
    assess_adapter_semantic_compatibility,
)
from autoresearch.competition.contest_direction_literature import (
    ContestDirectionLiteratureArtifact,
    ContestDirectionLiteratureRecord,
    DirectionSearchCallable,
    retrieve_contest_direction_literature,
)
from autoresearch.competition.contest_direction_plan_cli import (
    _eligible_literature,
    _select_planning_literature,
)
from autoresearch.competition.contest_direction_stage_checkpoint import (
    record_completed_stage,
    replayable_literature_searchers,
    replayable_stage_completion,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.literature.models import AcademicPaper, PublicationStatus
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_FOCUS_ARTIFACT_NAME = "direction-focus.json"
_BRAINSTORM_RECEIPT_NAME = "direction-focus-brainstorm-response.json"
_SELECTION_RECEIPT_NAME = "direction-focus-selection-response.json"
_STATUS_RECEIPT_NAME = "direction-focus-status-verification.json"
_TARGETED_LITERATURE_NAME = "targeted-literature.json"
_TARGETED_QUERY_RECEIPT_NAME = "targeted-query-response.json"
_TARGETED_BINDING_NAME = "direction-targeted-retrieval.json"
_MAX_FOCUS_EVIDENCE_RECORDS = 16
_FOCUS_STATUS_REFILL_RESERVE = 8

CompletionCallable = Callable[..., LLMJsonCompletionResult]


class ContestDirectionFocusError(RuntimeError):
    """Raised when focus selection or its artifact bindings are not trustworthy."""


class ContestFocusFileBinding(StrictFrozenModel):
    """A root-relative immutable file binding."""

    relative_path: str = Field(min_length=1)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_path(self) -> ContestFocusFileBinding:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ContestDirectionFocusError("file binding must stay inside its artifact root")
        return self


class ContestDirectionFocusStatusCheck(StrictFrozenModel):
    """One bounded shortlist status check, including non-calls and failures."""

    candidate_rank: int = Field(ge=1)
    record_id: str = Field(pattern=r"^direction-paper-[0-9a-f]{16}$")
    record_hash: str = Field(pattern=_SHA256_PATTERN)
    source_url: str = Field(min_length=1)
    original_status: PublicationStatus
    original_status_source: str | None = None
    original_status_as_of: date | None = None
    is_arxiv: bool
    verification_attempted: bool
    verified_status: PublicationStatus
    verified_status_source: str | None = None
    verified_status_as_of: date | None = None
    outcome: Literal[
        "not_arxiv_no_verification_needed",
        "verified_eligible",
        "verified_withdrawn_excluded",
        "verified_retracted_excluded",
        "verification_failed_preserved_upstream_degraded",
        "verification_returned_unchanged_upstream_degraded",
        "arxiv_missing_verifiable_url_preserved_upstream_degraded",
    ]
    retained_for_focus: bool
    error: str | None = Field(default=None, max_length=2_000)
    check_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_check(self) -> ContestDirectionFocusStatusCheck:
        excluded = self.outcome in {
            "verified_withdrawn_excluded",
            "verified_retracted_excluded",
        }
        if excluded == self.retained_for_focus:
            raise ContestDirectionFocusError("focus status exclusion/retention mismatch")
        if excluded and self.verified_status not in {"withdrawn", "retracted"}:
            raise ContestDirectionFocusError("excluded status check lacks withdrawn status")
        failed = self.outcome == "verification_failed_preserved_upstream_degraded"
        if failed != (self.error is not None):
            raise ContestDirectionFocusError("focus status verification error mismatch")
        if not self.is_arxiv and (
            self.verification_attempted or self.outcome != "not_arxiv_no_verification_needed"
        ):
            raise ContestDirectionFocusError("non-arXiv status check must not call verifier")
        if self.verification_attempted and not self.is_arxiv:
            raise ContestDirectionFocusError("only arXiv records may be status verified")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"check_hash"}))
        if self.check_hash != expected:
            raise ContestDirectionFocusError("focus status check hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionFocusStatusCheck:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, check_hash="0" * 64)
        payload["check_hash"] = canonical_model_hash(
            unhashed.model_dump(mode="json", exclude={"check_hash"})
        )
        return cls.model_validate(payload)


class ContestDirectionFocusStatusReceipt(StrictFrozenModel):
    """Write-once receipt used to rebuild verified focus evidence without network."""

    schema_version: Literal["contest-direction-focus-status-verification-v1"] = (
        "contest-direction-focus-status-verification-v1"
    )
    broad_literature_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    broad_literature_catalog_hash: str = Field(pattern=_SHA256_PATTERN)
    candidate_pool: tuple[dict[str, JsonValue], ...] = Field(min_length=1)
    candidate_pool_hash: str = Field(pattern=_SHA256_PATTERN)
    target_evidence_count: int = Field(ge=1, le=_MAX_FOCUS_EVIDENCE_RECORDS)
    checks: tuple[ContestDirectionFocusStatusCheck, ...] = Field(min_length=1)
    retained_record_ids: tuple[str, ...] = ()
    retained_count: int = Field(ge=0, le=_MAX_FOCUS_EVIDENCE_RECORDS)
    excluded_count: int = Field(ge=0)
    degraded_count: int = Field(ge=0)
    verification_state: Literal["complete", "degraded"]
    network_boundary: Literal["caller_injected_shortlist_verifier_serial"] = (
        "caller_injected_shortlist_verifier_serial"
    )
    receipt_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_receipt(self) -> ContestDirectionFocusStatusReceipt:
        if self.candidate_pool_hash != canonical_model_hash(
            {"candidate_pool": list(self.candidate_pool)}
        ):
            raise ContestDirectionFocusError("focus status candidate-pool hash mismatch")
        if tuple(item.candidate_rank for item in self.checks) != tuple(
            range(1, len(self.checks) + 1)
        ):
            raise ContestDirectionFocusError("focus status checks must follow rank order")
        retained = tuple(item.record_id for item in self.checks if item.retained_for_focus)
        if retained != self.retained_record_ids or self.retained_count != len(retained):
            raise ContestDirectionFocusError("focus status retained-record count mismatch")
        excluded = sum(not item.retained_for_focus for item in self.checks)
        if self.excluded_count != excluded:
            raise ContestDirectionFocusError("focus status excluded-record count mismatch")
        degraded = sum(_status_check_is_degraded(item) for item in self.checks)
        if self.degraded_count != degraded:
            raise ContestDirectionFocusError("focus status degraded-record count mismatch")
        expected_state = "degraded" if degraded else "complete"
        if self.verification_state != expected_state:
            raise ContestDirectionFocusError("focus status overall state mismatch")
        if self.retained_count > self.target_evidence_count:
            raise ContestDirectionFocusError("focus status receipt retained too many records")
        if self.retained_count == self.target_evidence_count:
            if len(self.checks) < self.target_evidence_count:
                raise ContestDirectionFocusError("focus status receipt stopped before target")
        elif len(self.checks) != len(self.candidate_pool):
            raise ContestDirectionFocusError(
                "focus status receipt stopped without reaching target or exhausting pool"
            )
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ContestDirectionFocusError("focus status receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionFocusStatusReceipt:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, receipt_hash="0" * 64)
        payload["receipt_hash"] = canonical_model_hash(
            unhashed.model_dump(mode="json", exclude={"receipt_hash"})
        )
        return cls.model_validate(payload)


class ContestDirectionFocusResponseReceipt(StrictFrozenModel):
    """Exact provider completion retained before any scientific projection."""

    schema_version: Literal["contest-direction-focus-response-v1"] = (
        "contest-direction-focus-response-v1"
    )
    stage_name: Literal[
        "direction-focus-brainstorm",
        "direction-focus-selection",
        "direction-targeted-query",
    ]
    stage_input_hash: str = Field(pattern=_SHA256_PATTERN)
    messages: tuple[dict[str, str], ...] = Field(min_length=2)
    messages_hash: str = Field(pattern=_SHA256_PATTERN)
    completion: dict[str, JsonValue]
    completion_hash: str = Field(pattern=_SHA256_PATTERN)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    response_text_sha256: str = Field(pattern=_SHA256_PATTERN)
    receipt_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_receipt(self) -> ContestDirectionFocusResponseReceipt:
        if self.messages_hash != canonical_model_hash({"messages": list(self.messages)}):
            raise ContestDirectionFocusError("focus response messages hash mismatch")
        if self.completion_hash != canonical_model_hash(self.completion):
            raise ContestDirectionFocusError("focus response completion hash mismatch")
        completion = LLMJsonCompletionResult.model_validate(self.completion)
        if completion.provider != self.provider or completion.model_name != self.model_name:
            raise ContestDirectionFocusError("focus response provider identity mismatch")
        response_hash = hashlib.sha256(completion.response_text.encode("utf-8")).hexdigest()
        if self.response_text_sha256 != response_hash:
            raise ContestDirectionFocusError("focus raw response text hash mismatch")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"receipt_hash"}))
        if self.receipt_hash != expected:
            raise ContestDirectionFocusError("focus response receipt hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        stage_name: Literal[
            "direction-focus-brainstorm",
            "direction-focus-selection",
            "direction-targeted-query",
        ],
        stage_input_hash: str,
        messages: Sequence[Mapping[str, str]],
        completion: LLMJsonCompletionResult,
    ) -> ContestDirectionFocusResponseReceipt:
        message_payload = tuple(dict(item) for item in messages)
        completion_payload = completion.model_dump(mode="json")
        payload: dict[str, Any] = {
            "schema_version": "contest-direction-focus-response-v1",
            "stage_name": stage_name,
            "stage_input_hash": stage_input_hash,
            "messages": message_payload,
            "messages_hash": canonical_model_hash({"messages": list(message_payload)}),
            "completion": completion_payload,
            "completion_hash": canonical_model_hash(completion_payload),
            "provider": completion.provider,
            "model_name": completion.model_name,
            "response_text_sha256": hashlib.sha256(
                completion.response_text.encode("utf-8")
            ).hexdigest(),
        }
        payload["receipt_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)

    def completion_result(self) -> LLMJsonCompletionResult:
        """Reconstruct the exact saved completion without a provider request."""

        return LLMJsonCompletionResult.model_validate(self.completion)


class ContestDirectionFocusEvidence(StrictFrozenModel):
    """One broad-search record admitted with explicit status-check provenance."""

    evidence_index: int = Field(ge=1, le=_MAX_FOCUS_EVIDENCE_RECORDS)
    record_id: str = Field(pattern=r"^direction-paper-[0-9a-f]{16}$")
    record_hash: str = Field(pattern=_SHA256_PATTERN)
    title: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    abstract: str = Field(min_length=1)
    publication_date: str | None = None
    venue: str | None = None
    doi: str | None = None
    repository_doi: str | None = None
    source_url: str = Field(min_length=1)
    citation_count: int | None = Field(default=None, ge=0)
    publication_status: str = Field(min_length=1)
    publication_status_verification: Literal[
        "upstream_provenance_retained_status_not_rechecked",
        "verified_by_caller_injected_shortlist_verifier",
        "verification_failed_preserved_upstream_status_degraded",
        "verification_returned_unchanged_upstream_status_degraded",
        "non_arxiv_no_verification_needed",
        "arxiv_missing_verifiable_url_preserved_upstream_status_degraded",
    ] = "upstream_provenance_retained_status_not_rechecked"
    retrieved_from: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)

    def prompt_projection(self) -> dict[str, JsonValue]:
        """Return scientific metadata only; internal IDs and hashes stay private."""

        return {
            "evidence_index": self.evidence_index,
            "title": self.title,
            "authors": list(self.authors),
            "abstract": self.abstract,
            "publication_date": self.publication_date,
            "venue": self.venue,
            "doi": self.doi,
            "repository_doi": self.repository_doi,
            "source_url": self.source_url,
            "citation_count": self.citation_count,
            "publication_status": self.publication_status,
            "publication_status_verification": self.publication_status_verification,
            "retrieved_from": self.retrieved_from,
            "retrieved_at": self.retrieved_at,
        }


class ContestDirectionFocusAdapterCapability(StrictFrozenModel):
    """Safe pilot-capability projection visible during focus feasibility checks.

    The model never receives runner paths, imports, callable identities, Skill
    content, or implementation-specific configuration through this contract.
    """

    adapter_id: str = Field(min_length=1, max_length=256)
    scientific_object: str = Field(min_length=1)
    observable: str = Field(min_length=1)
    supported_metrics: tuple[str, ...] = Field(min_length=1)
    supported_nulls: tuple[str, ...] = Field(min_length=1)
    execution_boundary_zh: str = Field(min_length=1)
    description: str | None = None

    @model_validator(mode="after")
    def _validate_capability(self) -> ContestDirectionFocusAdapterCapability:
        if self.adapter_id == "no_adapter":
            raise ContestDirectionFocusError("no_adapter is reserved for unmatched directions")
        if len(set(self.supported_metrics)) != len(self.supported_metrics):
            raise ContestDirectionFocusError("adapter metrics must be unique")
        if len(set(self.supported_nulls)) != len(self.supported_nulls):
            raise ContestDirectionFocusError("adapter null models must be unique")
        return self


class ContestDirectionFocusCandidate(StrictFrozenModel):
    """One model-authored provisional focus with a program-computed identity."""

    candidate_number: int = Field(ge=1, le=4)
    candidate_id: str = Field(pattern=r"^direction-focus-candidate-[0-9a-f]{16}$")
    title_cn: str = Field(min_length=1)
    focused_direction_cn: str = Field(min_length=1)
    problem_gap_cn: str = Field(min_length=1)
    falsifiable_objective_cn: str = Field(min_length=1)
    evidence_rationale_cn: str = Field(min_length=1)
    nearest_work_queries: tuple[str, ...] = Field(min_length=1, max_length=4)
    methods_baselines_queries: tuple[str, ...] = Field(min_length=1, max_length=4)
    counterevidence_queries: tuple[str, ...] = Field(min_length=1, max_length=4)
    evidence_indices: tuple[int, ...] = Field(min_length=1)
    pilot_adapter_id: str = Field(default="no_adapter", min_length=1)
    pilot_feasibility_cn: str = Field(
        default="当前候选未绑定已声明的可执行预实验适配器。",
        min_length=1,
    )
    candidate_payload_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_candidate(self) -> ContestDirectionFocusCandidate:
        unhashed = self.model_dump(mode="json", exclude={"candidate_id", "candidate_payload_hash"})
        expected_hash = canonical_model_hash(unhashed)
        if self.candidate_payload_hash != expected_hash:
            raise ContestDirectionFocusError("focus candidate payload hash mismatch")
        if self.candidate_id != f"direction-focus-candidate-{expected_hash[:16]}":
            raise ContestDirectionFocusError("focus candidate ID mismatch")
        for queries in (
            self.nearest_work_queries,
            self.methods_baselines_queries,
            self.counterevidence_queries,
        ):
            if len(set(queries)) != len(queries):
                raise ContestDirectionFocusError("focus candidate queries must be unique")
        if len(set(self.evidence_indices)) != len(self.evidence_indices):
            raise ContestDirectionFocusError("focus evidence indices must be unique")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionFocusCandidate:
        payload = dict(values)
        unhashed = cls.model_construct(
            **payload,
            candidate_id="direction-focus-candidate-" + ("0" * 16),
            candidate_payload_hash="0" * 64,
        )
        candidate_hash = canonical_model_hash(
            unhashed.model_dump(mode="json", exclude={"candidate_id", "candidate_payload_hash"})
        )
        payload["candidate_payload_hash"] = candidate_hash
        payload["candidate_id"] = f"direction-focus-candidate-{candidate_hash[:16]}"
        return cls.model_validate(payload)


class ContestDirectionFocusArtifact(StrictFrozenModel):
    """Two-call provisional direction decision grounded only in broad evidence."""

    schema_version: Literal["contest-direction-focus-v1"] = "contest-direction-focus-v1"
    direction: str = Field(min_length=1)
    parent_direction_sha256: str = Field(pattern=_SHA256_PATTERN)
    requirements: tuple[str, ...] = ()
    broad_literature_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    broad_literature_catalog_hash: str = Field(pattern=_SHA256_PATTERN)
    focus_evidence: tuple[ContestDirectionFocusEvidence, ...] = Field(min_length=1)
    focus_evidence_hash: str = Field(pattern=_SHA256_PATTERN)
    focus_evidence_role: Literal["broad_discovery_only_not_final_bibliography"] = (
        "broad_discovery_only_not_final_bibliography"
    )
    broad_publication_status_verification: Literal[
        "upstream_provenance_retained_status_not_rechecked",
        "shortlisted_arxiv_status_rechecked_complete",
        "shortlisted_arxiv_status_rechecked_degraded",
    ] = "upstream_provenance_retained_status_not_rechecked"
    publication_status_receipt: ContestFocusFileBinding | None = None
    publication_status_receipt_hash: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    executable_adapter_capabilities: tuple[ContestDirectionFocusAdapterCapability, ...] = ()
    executable_adapter_capabilities_hash: str = Field(pattern=_SHA256_PATTERN)
    adapter_capability_boundary: Literal[
        "feasibility_only_not_evidence_method_answer_or_forced_choice"
    ] = "feasibility_only_not_evidence_method_answer_or_forced_choice"
    candidates: tuple[ContestDirectionFocusCandidate, ...] = Field(min_length=2, max_length=4)
    selected_candidate_number: int = Field(ge=1, le=4)
    selected_focus_id: str = Field(pattern=r"^direction-focus-[0-9a-f]{16}$")
    selection_rationale_cn: str = Field(min_length=1)
    brainstorm_receipt: ContestFocusFileBinding
    brainstorm_receipt_hash: str = Field(pattern=_SHA256_PATTERN)
    selection_receipt: ContestFocusFileBinding
    selection_receipt_hash: str = Field(pattern=_SHA256_PATTERN)
    model_call_count_at_creation: Literal[2] = 2
    skills_available_to_focus_models: Literal[False] = False
    novelty_status: Literal["unverified_until_targeted_nearest_work_search"] = (
        "unverified_until_targeted_nearest_work_search"
    )
    artifact_relative_path: Literal["direction-focus.json"] = "direction-focus.json"
    artifact_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_artifact(self) -> ContestDirectionFocusArtifact:
        if self.parent_direction_sha256 != canonical_model_hash(
            {"parent_direction": self.direction}
        ):
            raise ContestDirectionFocusError("parent direction hash mismatch")
        expected_indices = tuple(range(1, len(self.focus_evidence) + 1))
        if tuple(item.evidence_index for item in self.focus_evidence) != expected_indices:
            raise ContestDirectionFocusError("focus evidence numbering mismatch")
        if self.focus_evidence_hash != canonical_model_hash(
            {"focus_evidence": [item.model_dump(mode="json") for item in self.focus_evidence]}
        ):
            raise ContestDirectionFocusError("focus evidence hash mismatch")
        if self.executable_adapter_capabilities_hash != canonical_model_hash(
            {
                "executable_adapter_capabilities": [
                    item.model_dump(mode="json") for item in self.executable_adapter_capabilities
                ]
            }
        ):
            raise ContestDirectionFocusError("focus adapter-capability hash mismatch")
        status_rechecked = self.broad_publication_status_verification != (
            "upstream_provenance_retained_status_not_rechecked"
        )
        if status_rechecked != (self.publication_status_receipt is not None):
            raise ContestDirectionFocusError("focus status receipt presence mismatch")
        if status_rechecked != (self.publication_status_receipt_hash is not None):
            raise ContestDirectionFocusError("focus status receipt hash presence mismatch")
        adapter_ids = tuple(item.adapter_id for item in self.executable_adapter_capabilities)
        if len(set(adapter_ids)) != len(adapter_ids):
            raise ContestDirectionFocusError("focus adapter capability IDs must be unique")
        candidate_numbers = tuple(item.candidate_number for item in self.candidates)
        if candidate_numbers != tuple(range(1, len(self.candidates) + 1)):
            raise ContestDirectionFocusError("focus candidate numbering mismatch")
        if self.selected_candidate_number not in candidate_numbers:
            raise ContestDirectionFocusError("selected focus candidate is unavailable")
        allowed_evidence = set(expected_indices)
        if any(
            index not in allowed_evidence
            for candidate in self.candidates
            for index in candidate.evidence_indices
        ):
            raise ContestDirectionFocusError("focus candidate cites unknown broad evidence")
        allowed_adapters = set(adapter_ids) | {"no_adapter"}
        if any(candidate.pilot_adapter_id not in allowed_adapters for candidate in self.candidates):
            raise ContestDirectionFocusError(
                "focus candidate cites an unavailable pilot adapter capability"
            )
        capabilities = {item.adapter_id: item for item in self.executable_adapter_capabilities}
        for candidate in self.candidates:
            if candidate.pilot_adapter_id == "no_adapter":
                continue
            compatibility = assess_adapter_semantic_compatibility(
                capabilities[candidate.pilot_adapter_id],
                scope_texts=(
                    candidate.title_cn,
                    candidate.focused_direction_cn,
                    candidate.falsifiable_objective_cn,
                ),
            )
            if not compatibility.compatible:
                raise ContestDirectionFocusError(
                    "focus candidate adapter binding violates runner semantics"
                )
        selected = self.selected_candidate
        expected_focus_id = _selected_focus_id(
            candidate=selected,
            selection_receipt_hash=self.selection_receipt_hash,
        )
        if self.selected_focus_id != expected_focus_id:
            raise ContestDirectionFocusError("selected focus ID mismatch")
        expected_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ContestDirectionFocusError("direction focus artifact hash mismatch")
        return self

    @property
    def selected_candidate(self) -> ContestDirectionFocusCandidate:
        return self.candidates[self.selected_candidate_number - 1]

    @property
    def focused_direction_cn(self) -> str:
        """Return the direction later scientific stages must consume."""

        return self.selected_candidate.focused_direction_cn

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionFocusArtifact:
        payload = dict(values)
        selected = tuple(payload["candidates"])[int(payload["selected_candidate_number"]) - 1]
        payload["selected_focus_id"] = _selected_focus_id(
            candidate=selected,
            selection_receipt_hash=str(payload["selection_receipt_hash"]),
        )
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_model_hash(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)


class ContestDirectionTargetedRetrievalBinding(StrictFrozenModel):
    """Exact bridge from one selected focus to the second real search artifact."""

    schema_version: Literal["contest-direction-targeted-retrieval-v1"] = (
        "contest-direction-targeted-retrieval-v1"
    )
    focus_artifact: ContestFocusFileBinding
    focus_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    selected_focus_id: str = Field(pattern=r"^direction-focus-[0-9a-f]{16}$")
    broad_literature_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    targeted_search_context: str = Field(min_length=1)
    targeted_search_context_hash: str = Field(pattern=_SHA256_PATTERN)
    targeted_literature: ContestFocusFileBinding
    targeted_literature_artifact_hash: str = Field(pattern=_SHA256_PATTERN)
    targeted_literature_catalog_hash: str = Field(pattern=_SHA256_PATTERN)
    targeted_query_receipt: ContestFocusFileBinding
    targeted_query_receipt_hash: str = Field(pattern=_SHA256_PATTERN)
    selected_method_skills: tuple[()] = ()
    skills_available_to_targeted_query_model: Literal[False] = False
    retrieval_execution: Literal["serial_existing_retriever_rate_limits"] = (
        "serial_existing_retriever_rate_limits"
    )
    searcher_lifecycle: Literal["caller_injected_reuse_required_for_cross_stage_rate_limits"] = (
        "caller_injected_reuse_required_for_cross_stage_rate_limits"
    )
    novelty_status: Literal["unverified_requires_nearest_work_comparison"] = (
        "unverified_requires_nearest_work_comparison"
    )
    artifact_relative_path: Literal["direction-targeted-retrieval.json"] = (
        "direction-targeted-retrieval.json"
    )
    artifact_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_binding(self) -> ContestDirectionTargetedRetrievalBinding:
        if self.targeted_search_context_hash != canonical_model_hash(
            {"targeted_search_context": self.targeted_search_context}
        ):
            raise ContestDirectionFocusError("targeted search context hash mismatch")
        expected = canonical_model_hash(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ContestDirectionFocusError("targeted retrieval binding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ContestDirectionTargetedRetrievalBinding:
        payload = dict(values)
        unhashed = cls.model_construct(**payload, artifact_hash="0" * 64)
        payload["artifact_hash"] = canonical_model_hash(
            unhashed.model_dump(mode="json", exclude={"artifact_hash"})
        )
        return cls.model_validate(payload)


def build_contest_direction_focus_brainstorm_messages(
    *,
    direction: str,
    requirements: Sequence[str],
    evidence: Sequence[ContestDirectionFocusEvidence],
    executable_adapter_capabilities: Sequence[ContestDirectionFocusAdapterCapability] = (),
) -> list[dict[str, str]]:
    """Build a Skill-free evidence-grounded provisional-focus request."""

    normalized_direction = _required_text(direction, label="direction")
    normalized_requirements = _normalize_texts(requirements)
    return [
        {
            "role": "system",
            "content": (
                "你是科研方向构思智能体。只根据用户问题和真实检索证据提出2至4个暂定研究焦点。"
                "每个焦点必须有可证伪目标，并分别给出：最近相邻工作的检索词、可学习的方法/"
                "基线/评价检索词、反证/失败条件/替代解释检索词，以及支持判断的证据序号。"
                "证据只能支持暂定方向，不能据此宣称创新性已经证实；被引次数、发表载体和DOI"
                "只是软信息，不能替代相关性、方法适配性和反例核对。不得生成或猜测论文、DOI、"
                "URL、实验结果，也不得使用任何Skill内容。每条证据明确标注发表状态的核对"
                "方式；不得把未复核或核对失败的状态写成已复验事实。列出的预实验能力只用于判断"
                "当前系统能否真实执行一个低成本pilot；它不是事实证据、不是方法答案，也不"
                "强制你选择适配器覆盖的方向。可以提出pilot_adapter_id=no_adapter的方向，但"
                "必须在pilot_feasibility_cn中诚实说明当前无法直接执行。adapter_id相同不代表"
                "科学语义相容：候选若增加能力边界外的表示变换、诱导距离/间隙或未列出的主"
                "指标，必须写no_adapter；不得用列出的对象/观测量关键词掩盖语义变化。只输出"
                "一个JSON对象。"
            ),
        },
        {
            "role": "user",
            "content": _json_text(
                {
                    "question": normalized_direction,
                    "requirements": list(normalized_requirements),
                    "broad_retrieval_evidence": [item.prompt_projection() for item in evidence],
                    "executable_pilot_capabilities": [
                        item.model_dump(mode="json") for item in executable_adapter_capabilities
                    ],
                    "pilot_capability_boundary_zh": (
                        "这些能力只用于可行性判断，不是事实证据、方法答案或强制选题。"
                        "能力为空、候选超出execution_boundary_zh，或需要额外变换/度量时，"
                        "使用no_adapter并诚实说明。"
                    ),
                    "output_contract": {
                        "candidates": [
                            {
                                "title_cn": "暂定方向",
                                "focused_direction_cn": (
                                    "包含研究对象、限定范围与可证伪目标的聚焦方向"
                                ),
                                "problem_gap_cn": "由证据支持但尚待定向检索核对的缺口",
                                "falsifiable_objective_cn": "可被数据或预实验否定的目标",
                                "evidence_rationale_cn": "证据链与局限",
                                "nearest_work_queries": ["最近且最相邻工作的检索词"],
                                "methods_baselines_queries": ["方法、基线与评价检索词"],
                                "counterevidence_queries": ["反证、失败与替代解释检索词"],
                                "evidence_indices": [1],
                                "pilot_adapter_id": "已列出的adapter_id或no_adapter",
                                "pilot_feasibility_cn": "当前系统能否真实执行及其边界",
                            }
                        ]
                    },
                }
            ),
        },
    ]


def build_contest_direction_focus_selection_messages(
    *,
    direction: str,
    requirements: Sequence[str],
    evidence: Sequence[ContestDirectionFocusEvidence],
    candidates: Sequence[ContestDirectionFocusCandidate],
    executable_adapter_capabilities: Sequence[ContestDirectionFocusAdapterCapability] = (),
) -> list[dict[str, str]]:
    """Build the independent selector request; it can select but not rewrite."""

    candidate_payload = [
        {
            "candidate_number": item.candidate_number,
            "candidate_id": item.candidate_id,
            "title_cn": item.title_cn,
            "focused_direction_cn": item.focused_direction_cn,
            "problem_gap_cn": item.problem_gap_cn,
            "falsifiable_objective_cn": item.falsifiable_objective_cn,
            "evidence_rationale_cn": item.evidence_rationale_cn,
            "nearest_work_queries": list(item.nearest_work_queries),
            "methods_baselines_queries": list(item.methods_baselines_queries),
            "counterevidence_queries": list(item.counterevidence_queries),
            "evidence_indices": list(item.evidence_indices),
            "pilot_adapter_id": item.pilot_adapter_id,
            "pilot_feasibility_cn": item.pilot_feasibility_cn,
        }
        for item in candidates
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是独立的暂定方向选择智能体。你没有参与候选构思。请根据问题清晰度、证据"
                "相关性与时效性、可证伪性、低成本预实验可行性、最近工作区分能力、方法/基线"
                "可学习性以及反例覆盖，选择一个现有候选。不得改写候选，不得声称创新性已被"
                "证实，不得把被引次数或期刊影响力作为硬门，也不得使用任何Skill内容。预实验"
                "能力只用于可行性判断，不是证据、方法答案或强制选题。允许选择no_adapter候选，"
                "但selection_rationale_cn必须诚实说明当前系统不能立即执行该方向的真实pilot。"
                "候选中的adapter可行性已经过程序语义门；不得仅因题面含有相似关键词而推翻"
                "no_adapter。"
                "只输出JSON对象，包含selected_candidate_number和selection_rationale_cn。"
            ),
        },
        {
            "role": "user",
            "content": _json_text(
                {
                    "question": _required_text(direction, label="direction"),
                    "requirements": list(_normalize_texts(requirements)),
                    "broad_evidence": [item.prompt_projection() for item in evidence],
                    "executable_pilot_capabilities": [
                        item.model_dump(mode="json") for item in executable_adapter_capabilities
                    ],
                    "pilot_capability_boundary_zh": (
                        "只用于可行性判断；不是事实证据、方法答案或强制选择。"
                    ),
                    "provisional_candidates": candidate_payload,
                }
            ),
        },
    ]


def run_contest_direction_focus_selection(
    *,
    direction: str,
    broad_literature: ContestDirectionLiteratureArtifact,
    output_dir: Path | str,
    requirements: Sequence[str] = (),
    executable_adapter_capabilities: Sequence[Mapping[str, Any]] = (),
    publication_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    brainstorm_max_tokens: int = 3_200,
    selection_max_tokens: int = 1_200,
    completion: CompletionCallable = run_llm_json_completion,
) -> ContestDirectionFocusArtifact:
    """Run exactly one provisional-focus call and one independent selection call.

    Existing raw-response receipts are replayed locally.  There is no repair or
    formatting loop: tolerant projection accepts common field aliases, while a
    scientifically incomplete response fails explicitly.
    """

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    normalized_capabilities = _normalize_adapter_capabilities(executable_adapter_capabilities)
    destination = root / _FOCUS_ARTIFACT_NAME
    if destination.is_file():
        return load_contest_direction_focus_selection(
            destination,
            broad_literature=broad_literature,
            executable_adapter_capabilities=executable_adapter_capabilities,
            require_publication_status_verification=(publication_status_verifier is not None),
        )

    normalized_direction = _required_text(direction, label="direction")
    if normalized_direction != broad_literature.direction:
        raise ContestDirectionFocusError(
            "focus parent direction differs from the broad retrieval direction"
        )
    normalized_requirements = _normalize_texts(requirements)
    evidence, status_receipt, status_receipt_binding = _prepare_focus_evidence(
        broad_literature=broad_literature,
        root=root,
        publication_status_verifier=publication_status_verifier,
    )
    status_verification = _status_verification_label(status_receipt)
    base_input_hash = canonical_model_hash(
        {
            "direction": normalized_direction,
            "requirements": list(normalized_requirements),
            "broad_literature_artifact_hash": broad_literature.artifact_hash,
            "broad_literature_catalog_hash": broad_literature.literature_catalog_hash,
            "focus_evidence": [item.model_dump(mode="json") for item in evidence],
            "executable_adapter_capabilities": [
                item.model_dump(mode="json") for item in normalized_capabilities
            ],
            "executable_adapter_capabilities_hash": canonical_model_hash(
                {
                    "executable_adapter_capabilities": [
                        item.model_dump(mode="json") for item in normalized_capabilities
                    ]
                }
            ),
            "publication_status_verification": status_verification,
            "publication_status_receipt_hash": (
                status_receipt.receipt_hash if status_receipt is not None else None
            ),
        }
    )
    brainstorm_messages = build_contest_direction_focus_brainstorm_messages(
        direction=normalized_direction,
        requirements=normalized_requirements,
        evidence=evidence,
        executable_adapter_capabilities=normalized_capabilities,
    )
    brainstorm_receipt_path = root / _BRAINSTORM_RECEIPT_NAME
    brainstorm_receipt = _call_or_load_response(
        root=root,
        receipt_path=brainstorm_receipt_path,
        stage_name="direction-focus-brainstorm",
        stage_input_hash=base_input_hash,
        messages=brainstorm_messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=brainstorm_max_tokens,
        completion=completion,
    )
    candidates = _project_focus_candidates(
        brainstorm_receipt.completion_result().parsed_json,
        evidence_count=len(evidence),
        adapter_capabilities=normalized_capabilities,
    )

    selection_messages = build_contest_direction_focus_selection_messages(
        direction=normalized_direction,
        requirements=normalized_requirements,
        evidence=evidence,
        candidates=candidates,
        executable_adapter_capabilities=normalized_capabilities,
    )
    selection_input_hash = canonical_model_hash(
        {
            "base_input_hash": base_input_hash,
            "brainstorm_receipt_hash": brainstorm_receipt.receipt_hash,
            "candidates": [item.model_dump(mode="json") for item in candidates],
        }
    )
    selection_receipt_path = root / _SELECTION_RECEIPT_NAME
    selection_receipt = _call_or_load_response(
        root=root,
        receipt_path=selection_receipt_path,
        stage_name="direction-focus-selection",
        stage_input_hash=selection_input_hash,
        messages=selection_messages,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=selection_max_tokens,
        completion=completion,
    )
    selected_number, rationale = _project_focus_selection(
        selection_receipt.completion_result().parsed_json,
        candidates=candidates,
    )
    brainstorm_binding = _file_binding(root, brainstorm_receipt_path)
    selection_binding = _file_binding(root, selection_receipt_path)
    artifact = ContestDirectionFocusArtifact.create(
        direction=normalized_direction,
        parent_direction_sha256=canonical_model_hash({"parent_direction": normalized_direction}),
        requirements=normalized_requirements,
        broad_literature_artifact_hash=broad_literature.artifact_hash,
        broad_literature_catalog_hash=broad_literature.literature_catalog_hash,
        focus_evidence=evidence,
        focus_evidence_hash=canonical_model_hash(
            {"focus_evidence": [item.model_dump(mode="json") for item in evidence]}
        ),
        focus_evidence_role="broad_discovery_only_not_final_bibliography",
        broad_publication_status_verification=(status_verification),
        publication_status_receipt=status_receipt_binding,
        publication_status_receipt_hash=(
            status_receipt.receipt_hash if status_receipt is not None else None
        ),
        executable_adapter_capabilities=normalized_capabilities,
        executable_adapter_capabilities_hash=canonical_model_hash(
            {
                "executable_adapter_capabilities": [
                    item.model_dump(mode="json") for item in normalized_capabilities
                ]
            }
        ),
        adapter_capability_boundary=(
            "feasibility_only_not_evidence_method_answer_or_forced_choice"
        ),
        candidates=candidates,
        selected_candidate_number=selected_number,
        selection_rationale_cn=rationale,
        brainstorm_receipt=brainstorm_binding,
        brainstorm_receipt_hash=brainstorm_receipt.receipt_hash,
        selection_receipt=selection_binding,
        selection_receipt_hash=selection_receipt.receipt_hash,
        model_call_count_at_creation=2,
        skills_available_to_focus_models=False,
        novelty_status="unverified_until_targeted_nearest_work_search",
        artifact_relative_path=_FOCUS_ARTIFACT_NAME,
    )
    _write_once_model(destination, artifact)
    stage_artifacts = [
        brainstorm_receipt_path,
        selection_receipt_path,
        destination,
    ]
    if status_receipt_binding is not None:
        stage_artifacts.insert(0, root / status_receipt_binding.relative_path)
    record_completed_stage(
        root=root,
        ordinal=1,
        stage_name="direction-focus-selection",
        stage_input_hash=base_input_hash,
        artifacts=tuple(stage_artifacts),
    )
    return artifact


def load_contest_direction_focus_selection(
    path: Path | str,
    *,
    broad_literature: ContestDirectionLiteratureArtifact,
    executable_adapter_capabilities: Sequence[Mapping[str, Any]] = (),
    require_publication_status_verification: bool = False,
) -> ContestDirectionFocusArtifact:
    """Load a focus decision and revalidate broad evidence and raw receipts."""

    artifact_path = Path(path).expanduser().resolve()
    root = artifact_path.parent
    artifact = ContestDirectionFocusArtifact.model_validate_json(
        artifact_path.read_text(encoding="utf-8")
    )
    normalized_capabilities = _normalize_adapter_capabilities(executable_adapter_capabilities)
    if artifact_path.name != artifact.artifact_relative_path:
        raise ContestDirectionFocusError("focus artifact filename mismatch")
    if (
        artifact.broad_literature_artifact_hash != broad_literature.artifact_hash
        or artifact.broad_literature_catalog_hash != broad_literature.literature_catalog_hash
        or artifact.direction != broad_literature.direction
    ):
        raise ContestDirectionFocusError("focus artifact does not bind the broad search")
    receipt_path = root / _STATUS_RECEIPT_NAME
    if artifact.publication_status_receipt is not None:
        _verify_file_binding(root, artifact.publication_status_receipt)
        if receipt_path != _resolve_binding(root, artifact.publication_status_receipt):
            raise ContestDirectionFocusError("focus status receipt path mismatch")
        status_receipt = ContestDirectionFocusStatusReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if status_receipt.receipt_hash != artifact.publication_status_receipt_hash:
            raise ContestDirectionFocusError("focus status receipt artifact binding mismatch")
        candidates = _focus_evidence_candidates(
            broad_literature,
            maximum_records=_MAX_FOCUS_EVIDENCE_RECORDS + _FOCUS_STATUS_REFILL_RESERVE,
        )
        expected_evidence = _rebuild_focus_evidence_from_status_receipt(
            broad_literature=broad_literature,
            candidates=candidates,
            receipt=status_receipt,
        )
    else:
        status_receipt = None
        expected_evidence = _select_focus_evidence(broad_literature)
        if receipt_path.exists():
            raise ContestDirectionFocusError("unbound focus status receipt exists")
    if require_publication_status_verification and status_receipt is None:
        raise ContestDirectionFocusError(
            "completed focus artifact lacks required shortlist status verification"
        )
    if artifact.broad_publication_status_verification != _status_verification_label(status_receipt):
        raise ContestDirectionFocusError("focus status verification label mismatch")
    if artifact.focus_evidence != expected_evidence:
        raise ContestDirectionFocusError("focus evidence projection changed")
    if artifact.executable_adapter_capabilities != normalized_capabilities:
        raise ContestDirectionFocusError("focus adapter-capability input changed")
    brainstorm = _load_bound_receipt(root, artifact.brainstorm_receipt)
    selection = _load_bound_receipt(root, artifact.selection_receipt)
    if (
        brainstorm.receipt_hash != artifact.brainstorm_receipt_hash
        or brainstorm.stage_name != "direction-focus-brainstorm"
        or selection.receipt_hash != artifact.selection_receipt_hash
        or selection.stage_name != "direction-focus-selection"
    ):
        raise ContestDirectionFocusError("focus response receipt binding mismatch")
    expected_base_input_hash = canonical_model_hash(
        {
            "direction": artifact.direction,
            "requirements": list(artifact.requirements),
            "broad_literature_artifact_hash": broad_literature.artifact_hash,
            "broad_literature_catalog_hash": broad_literature.literature_catalog_hash,
            "focus_evidence": [item.model_dump(mode="json") for item in artifact.focus_evidence],
            "executable_adapter_capabilities": [
                item.model_dump(mode="json") for item in artifact.executable_adapter_capabilities
            ],
            "executable_adapter_capabilities_hash": (artifact.executable_adapter_capabilities_hash),
            "publication_status_verification": (artifact.broad_publication_status_verification),
            "publication_status_receipt_hash": (artifact.publication_status_receipt_hash),
        }
    )
    expected_brainstorm_messages = tuple(
        build_contest_direction_focus_brainstorm_messages(
            direction=artifact.direction,
            requirements=artifact.requirements,
            evidence=artifact.focus_evidence,
            executable_adapter_capabilities=artifact.executable_adapter_capabilities,
        )
    )
    if (
        brainstorm.stage_input_hash != expected_base_input_hash
        or brainstorm.messages != expected_brainstorm_messages
    ):
        raise ContestDirectionFocusError("focus brainstorm receipt inputs changed")
    projected_candidates = _project_focus_candidates(
        brainstorm.completion_result().parsed_json,
        evidence_count=len(artifact.focus_evidence),
        adapter_capabilities=artifact.executable_adapter_capabilities,
    )
    if projected_candidates != artifact.candidates:
        raise ContestDirectionFocusError("focus candidates differ from the raw response")
    expected_selection_input_hash = canonical_model_hash(
        {
            "base_input_hash": expected_base_input_hash,
            "brainstorm_receipt_hash": brainstorm.receipt_hash,
            "candidates": [item.model_dump(mode="json") for item in artifact.candidates],
        }
    )
    expected_selection_messages = tuple(
        build_contest_direction_focus_selection_messages(
            direction=artifact.direction,
            requirements=artifact.requirements,
            evidence=artifact.focus_evidence,
            candidates=artifact.candidates,
            executable_adapter_capabilities=artifact.executable_adapter_capabilities,
        )
    )
    if (
        selection.stage_input_hash != expected_selection_input_hash
        or selection.messages != expected_selection_messages
    ):
        raise ContestDirectionFocusError("focus selection receipt inputs changed")
    selected_number, rationale = _project_focus_selection(
        selection.completion_result().parsed_json,
        candidates=artifact.candidates,
    )
    if (
        selected_number != artifact.selected_candidate_number
        or rationale != artifact.selection_rationale_cn
    ):
        raise ContestDirectionFocusError("selected focus differs from the raw response")
    return artifact


def run_contest_direction_targeted_retrieval(
    *,
    focus: ContestDirectionFocusArtifact,
    output_dir: Path | str,
    searchers: Mapping[str, DirectionSearchCallable],
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    timeout_seconds: int | None = None,
    max_tokens: int = 1_200,
    max_results_per_search: int = 20,
    completion: CompletionCallable = run_llm_json_completion,
) -> ContestDirectionTargetedRetrievalBinding:
    """Run the existing real retriever once for the selected provisional focus.

    Skill content is unavailable by construction.  Source calls remain serial and
    are wrapped with the existing replay checkpoint; each client keeps its own
    configured rate limiter.
    """

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    focus_path = root / _FOCUS_ARTIFACT_NAME
    _require_matching_model_file(focus_path, focus)
    destination = root / _TARGETED_BINDING_NAME
    if destination.is_file():
        return load_contest_direction_targeted_retrieval(destination, focus=focus)

    selected = focus.selected_candidate
    targeted_context = _targeted_search_context(focus)
    targeted_input_hash = _targeted_input_hash(focus, targeted_context)
    raw_searchers = dict(searchers)
    if not raw_searchers:
        raise ContestDirectionFocusError(
            "targeted retrieval requires caller-injected shared searcher instances"
        )
    replayable_searchers = replayable_literature_searchers(
        root=root,
        searchers=raw_searchers,
    )
    targeted_query_receipt_path = root / _TARGETED_QUERY_RECEIPT_NAME

    def query_completion(**kwargs: Any) -> LLMJsonCompletionResult:
        messages = kwargs.get("messages")
        if not isinstance(messages, list):
            raise ContestDirectionFocusError("targeted query completion omitted messages")
        receipt = _call_or_load_response(
            root=root,
            receipt_path=targeted_query_receipt_path,
            stage_name="direction-targeted-query",
            stage_input_hash=targeted_input_hash,
            messages=messages,
            config_path=kwargs.get("config_path", config_path),
            env_path=kwargs.get("env_path", env_path),
            timeout_seconds=kwargs.get("timeout_seconds", timeout_seconds),
            max_tokens=int(kwargs.get("max_tokens") or max_tokens),
            response_schema=kwargs.get("response_schema"),
            response_schema_name=kwargs.get("response_schema_name"),
            completion=completion,
        )
        return receipt.completion_result()

    literature_path = root / _TARGETED_LITERATURE_NAME
    if literature_path.is_file():
        targeted = ContestDirectionLiteratureArtifact.model_validate_json(
            literature_path.read_text(encoding="utf-8")
        )
    else:
        targeted = retrieve_contest_direction_literature(
            direction=targeted_context,
            requirements=(
                f"最近工作检索：{' ; '.join(selected.nearest_work_queries)}",
                f"方法、指标、基线与评价检索：{' ; '.join(selected.methods_baselines_queries)}",
                f"反证与失败检索：{' ; '.join(selected.counterevidence_queries)}",
            ),
            selected_method_skills={},
            searchers=replayable_searchers,
            config_path=config_path,
            env_path=env_path,
            output_path=literature_path,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            max_results_per_search=max_results_per_search,
            llm_call=query_completion,
        )
    if targeted.method_skills:
        raise ContestDirectionFocusError("targeted retrieval unexpectedly received Skill content")
    query_receipt = ContestDirectionFocusResponseReceipt.model_validate_json(
        targeted_query_receipt_path.read_text(encoding="utf-8")
    )
    binding = ContestDirectionTargetedRetrievalBinding.create(
        focus_artifact=_file_binding(root, focus_path),
        focus_artifact_hash=focus.artifact_hash,
        selected_focus_id=focus.selected_focus_id,
        broad_literature_artifact_hash=focus.broad_literature_artifact_hash,
        targeted_search_context=targeted_context,
        targeted_search_context_hash=canonical_model_hash(
            {"targeted_search_context": targeted_context}
        ),
        targeted_literature=_file_binding(root, literature_path),
        targeted_literature_artifact_hash=targeted.artifact_hash,
        targeted_literature_catalog_hash=targeted.literature_catalog_hash,
        targeted_query_receipt=_file_binding(root, targeted_query_receipt_path),
        targeted_query_receipt_hash=query_receipt.receipt_hash,
        selected_method_skills=(),
        skills_available_to_targeted_query_model=False,
        retrieval_execution="serial_existing_retriever_rate_limits",
        searcher_lifecycle="caller_injected_reuse_required_for_cross_stage_rate_limits",
        novelty_status="unverified_requires_nearest_work_comparison",
        artifact_relative_path=_TARGETED_BINDING_NAME,
    )
    _write_once_model(destination, binding)
    record_completed_stage(
        root=root,
        ordinal=2,
        stage_name="direction-targeted-retrieval",
        stage_input_hash=targeted_input_hash,
        artifacts=(targeted_query_receipt_path, literature_path, destination),
    )
    return binding


def load_contest_direction_targeted_retrieval(
    path: Path | str,
    *,
    focus: ContestDirectionFocusArtifact,
) -> ContestDirectionTargetedRetrievalBinding:
    """Load and re-hash the complete focus-to-targeted-search bridge."""

    binding_path = Path(path).expanduser().resolve()
    root = binding_path.parent
    binding = ContestDirectionTargetedRetrievalBinding.model_validate_json(
        binding_path.read_text(encoding="utf-8")
    )
    if binding_path.name != binding.artifact_relative_path:
        raise ContestDirectionFocusError("targeted retrieval binding filename mismatch")
    if (
        binding.focus_artifact_hash != focus.artifact_hash
        or binding.selected_focus_id != focus.selected_focus_id
        or binding.broad_literature_artifact_hash != focus.broad_literature_artifact_hash
    ):
        raise ContestDirectionFocusError("targeted retrieval does not bind the selected focus")
    _verify_file_binding(root, binding.focus_artifact)
    _verify_file_binding(root, binding.targeted_literature)
    _verify_file_binding(root, binding.targeted_query_receipt)
    focus_path = _resolve_binding(root, binding.focus_artifact)
    _require_matching_model_file(focus_path, focus)
    targeted = ContestDirectionLiteratureArtifact.model_validate_json(
        _resolve_binding(root, binding.targeted_literature).read_text(encoding="utf-8")
    )
    if (
        targeted.artifact_hash != binding.targeted_literature_artifact_hash
        or targeted.literature_catalog_hash != binding.targeted_literature_catalog_hash
        or targeted.method_skills
        or targeted.direction != binding.targeted_search_context
    ):
        raise ContestDirectionFocusError("targeted literature artifact binding mismatch")
    receipt = ContestDirectionFocusResponseReceipt.model_validate_json(
        _resolve_binding(root, binding.targeted_query_receipt).read_text(encoding="utf-8")
    )
    if (
        receipt.stage_name != "direction-targeted-query"
        or receipt.receipt_hash != binding.targeted_query_receipt_hash
        or receipt.stage_input_hash != _targeted_input_hash(focus, binding.targeted_search_context)
        or receipt.messages != targeted.messages
        or canonical_model_hash({"response_text": receipt.completion_result().response_text})
        != targeted.query_model_response_hash
    ):
        raise ContestDirectionFocusError("targeted query response receipt mismatch")
    return binding


def _select_focus_evidence(
    broad_literature: ContestDirectionLiteratureArtifact,
) -> tuple[ContestDirectionFocusEvidence, ...]:
    candidates = _focus_evidence_candidates(
        broad_literature,
        maximum_records=_MAX_FOCUS_EVIDENCE_RECORDS,
    )
    return tuple(
        _focus_evidence_from_candidate(
            record=record,
            projected=item,
            evidence_index=index,
            publication_status=record.publication_status,
            publication_status_verification=("upstream_provenance_retained_status_not_rechecked"),
        )
        for index, (record, item) in enumerate(candidates, start=1)
    )


def _focus_evidence_candidates(
    broad_literature: ContestDirectionLiteratureArtifact,
    *,
    maximum_records: int,
) -> tuple[tuple[ContestDirectionLiteratureRecord, dict[str, Any]], ...]:
    if broad_literature.method_skills:
        raise ContestDirectionFocusError(
            "broad discovery literature must be generated before Skill selection"
        )
    eligible, context, _excluded = _eligible_literature(broad_literature)
    selected, _selected_context = _select_planning_literature(
        eligible,
        context,
        queries=broad_literature.queries,
        minimum_records=1,
        maximum_records=maximum_records,
    )
    records_by_id = {item.record_id: item for item in broad_literature.retrieved_records}
    candidates: list[tuple[ContestDirectionLiteratureRecord, dict[str, Any]]] = []
    for item in selected:
        record_id = str(item.get("record_id") or "")
        try:
            record = records_by_id[record_id]
        except KeyError as exc:
            raise ContestDirectionFocusError("planning evidence escaped broad catalog") from exc
        abstract = str(item.get("abstract") or "").strip()
        source_url = str(item.get("source_url") or item.get("url") or "").strip()
        if not abstract or not source_url:
            raise ContestDirectionFocusError("focus evidence lacks abstract or source URL")
        candidates.append((record, dict(item)))
    return tuple(candidates)


def _prepare_focus_evidence(
    *,
    broad_literature: ContestDirectionLiteratureArtifact,
    root: Path,
    publication_status_verifier: Callable[[AcademicPaper], AcademicPaper] | None,
) -> tuple[
    tuple[ContestDirectionFocusEvidence, ...],
    ContestDirectionFocusStatusReceipt | None,
    ContestFocusFileBinding | None,
]:
    receipt_path = root / _STATUS_RECEIPT_NAME
    if receipt_path.is_file():
        receipt = ContestDirectionFocusStatusReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        candidates = _focus_evidence_candidates(
            broad_literature,
            maximum_records=_MAX_FOCUS_EVIDENCE_RECORDS + _FOCUS_STATUS_REFILL_RESERVE,
        )
        evidence = _rebuild_focus_evidence_from_status_receipt(
            broad_literature=broad_literature,
            candidates=candidates,
            receipt=receipt,
        )
        return evidence, receipt, _file_binding(root, receipt_path)

    if publication_status_verifier is None:
        return _select_focus_evidence(broad_literature), None, None

    base_candidates = _focus_evidence_candidates(
        broad_literature,
        maximum_records=_MAX_FOCUS_EVIDENCE_RECORDS,
    )
    candidates = _focus_evidence_candidates(
        broad_literature,
        maximum_records=_MAX_FOCUS_EVIDENCE_RECORDS + _FOCUS_STATUS_REFILL_RESERVE,
    )
    target_count = len(base_candidates)
    checks: list[ContestDirectionFocusStatusCheck] = []
    retained: list[str] = []
    for rank, (record, projected) in enumerate(candidates, start=1):
        if len(retained) == target_count:
            break
        check = _verify_focus_status_candidate(
            rank=rank,
            record=record,
            projected=projected,
            verifier=publication_status_verifier,
        )
        checks.append(check)
        if check.retained_for_focus:
            retained.append(check.record_id)
    pool_projection = _status_candidate_pool_projection(candidates)
    degraded_count = sum(_status_check_is_degraded(item) for item in checks)
    receipt = ContestDirectionFocusStatusReceipt.create(
        broad_literature_artifact_hash=broad_literature.artifact_hash,
        broad_literature_catalog_hash=broad_literature.literature_catalog_hash,
        candidate_pool=pool_projection,
        candidate_pool_hash=canonical_model_hash({"candidate_pool": list(pool_projection)}),
        target_evidence_count=target_count,
        checks=tuple(checks),
        retained_record_ids=tuple(retained),
        retained_count=len(retained),
        excluded_count=sum(not item.retained_for_focus for item in checks),
        degraded_count=degraded_count,
        verification_state="degraded" if degraded_count else "complete",
        network_boundary="caller_injected_shortlist_verifier_serial",
    )
    _write_once_model(receipt_path, receipt)
    evidence = _rebuild_focus_evidence_from_status_receipt(
        broad_literature=broad_literature,
        candidates=candidates,
        receipt=receipt,
    )
    return evidence, receipt, _file_binding(root, receipt_path)


def _rebuild_focus_evidence_from_status_receipt(
    *,
    broad_literature: ContestDirectionLiteratureArtifact,
    candidates: Sequence[tuple[ContestDirectionLiteratureRecord, Mapping[str, Any]]],
    receipt: ContestDirectionFocusStatusReceipt,
) -> tuple[ContestDirectionFocusEvidence, ...]:
    if (
        receipt.broad_literature_artifact_hash != broad_literature.artifact_hash
        or receipt.broad_literature_catalog_hash != broad_literature.literature_catalog_hash
    ):
        raise ContestDirectionFocusError("focus status receipt broad-literature mismatch")
    expected_pool = _status_candidate_pool_projection(candidates)
    if receipt.candidate_pool != expected_pool:
        raise ContestDirectionFocusError("focus status receipt candidate pool changed")
    if receipt.target_evidence_count != min(
        _MAX_FOCUS_EVIDENCE_RECORDS,
        len(candidates),
    ):
        raise ContestDirectionFocusError("focus status receipt target count mismatch")
    evidence: list[ContestDirectionFocusEvidence] = []
    for expected_rank, check in enumerate(receipt.checks, start=1):
        record, projected = candidates[expected_rank - 1]
        source_url = str(projected.get("source_url") or projected.get("url") or "").strip()
        if (
            check.candidate_rank != expected_rank
            or check.record_id != record.record_id
            or check.record_hash != record.record_hash
            or check.source_url != source_url
        ):
            raise ContestDirectionFocusError("focus status check record binding mismatch")
        if not check.retained_for_focus:
            continue
        evidence.append(
            _focus_evidence_from_candidate(
                record=record,
                projected=projected,
                evidence_index=len(evidence) + 1,
                publication_status=check.verified_status,
                publication_status_verification=_status_evidence_label(check),
            )
        )
    if not evidence:
        raise ContestDirectionFocusError(
            "no focus evidence remains after shortlisted publication-status verification"
        )
    if tuple(item.record_id for item in evidence) != receipt.retained_record_ids:
        raise ContestDirectionFocusError("focus status receipt evidence order mismatch")
    return tuple(evidence)


def _focus_evidence_from_candidate(
    *,
    record: ContestDirectionLiteratureRecord,
    projected: Mapping[str, Any],
    evidence_index: int,
    publication_status: PublicationStatus,
    publication_status_verification: Literal[
        "upstream_provenance_retained_status_not_rechecked",
        "verified_by_caller_injected_shortlist_verifier",
        "verification_failed_preserved_upstream_status_degraded",
        "verification_returned_unchanged_upstream_status_degraded",
        "non_arxiv_no_verification_needed",
        "arxiv_missing_verifiable_url_preserved_upstream_status_degraded",
    ],
) -> ContestDirectionFocusEvidence:
    return ContestDirectionFocusEvidence(
        evidence_index=evidence_index,
        record_id=record.record_id,
        record_hash=record.record_hash,
        title=record.title,
        authors=record.authors,
        abstract=str(projected.get("abstract") or "").strip(),
        publication_date=(
            record.publication_date.isoformat() if record.publication_date is not None else None
        ),
        venue=record.venue,
        doi=record.doi,
        repository_doi=record.repository_doi,
        source_url=str(projected.get("source_url") or projected.get("url") or "").strip(),
        citation_count=record.citation_count,
        publication_status=publication_status,
        publication_status_verification=publication_status_verification,
        retrieved_from=str(projected.get("retrieved_from") or "unknown"),
        retrieved_at=str(projected.get("retrieved_at") or "unknown"),
    )


def _status_candidate_pool_projection(
    candidates: Sequence[tuple[ContestDirectionLiteratureRecord, Mapping[str, Any]]],
) -> tuple[dict[str, JsonValue], ...]:
    return tuple(
        {
            "candidate_rank": rank,
            "record_id": record.record_id,
            "record_hash": record.record_hash,
            "source_url": str(projected.get("source_url") or projected.get("url") or "").strip(),
            "is_arxiv": _is_arxiv_record(record),
        }
        for rank, (record, projected) in enumerate(candidates, start=1)
    )


def _verify_focus_status_candidate(
    *,
    rank: int,
    record: ContestDirectionLiteratureRecord,
    projected: Mapping[str, Any],
    verifier: Callable[[AcademicPaper], AcademicPaper],
) -> ContestDirectionFocusStatusCheck:
    source_url = str(projected.get("source_url") or projected.get("url") or "").strip()
    common: dict[str, Any] = {
        "candidate_rank": rank,
        "record_id": record.record_id,
        "record_hash": record.record_hash,
        "source_url": source_url,
        "original_status": record.publication_status,
        "original_status_source": record.status_source,
        "original_status_as_of": record.status_as_of,
        "verified_status": record.publication_status,
        "verified_status_source": record.status_source,
        "verified_status_as_of": record.status_as_of,
        "retained_for_focus": True,
        "error": None,
    }
    if not _is_arxiv_record(record):
        return ContestDirectionFocusStatusCheck.create(
            **common,
            is_arxiv=False,
            verification_attempted=False,
            outcome="not_arxiv_no_verification_needed",
        )
    arxiv_url = _arxiv_status_url(record)
    if arxiv_url is None:
        return ContestDirectionFocusStatusCheck.create(
            **common,
            is_arxiv=True,
            verification_attempted=False,
            outcome="arxiv_missing_verifiable_url_preserved_upstream_degraded",
        )
    paper = _record_as_arxiv_paper(record, url=arxiv_url)
    try:
        verified = verifier(paper)
        if not isinstance(verified, AcademicPaper):
            raise TypeError("publication status verifier returned a non-AcademicPaper")
        if not _same_verification_paper(paper, verified):
            raise ValueError("publication status verifier changed paper identity")
    except Exception as exc:  # noqa: BLE001 - failure is retained as degraded evidence.
        return ContestDirectionFocusStatusCheck.create(
            **{**common, "error": f"{type(exc).__name__}: {exc}"[:2_000]},
            is_arxiv=True,
            verification_attempted=True,
            outcome="verification_failed_preserved_upstream_degraded",
        )
    verified_values = {
        **common,
        "is_arxiv": True,
        "verification_attempted": True,
        "verified_status": verified.publication_status,
        "verified_status_source": verified.status_source,
        "verified_status_as_of": verified.status_as_of,
    }
    if verified.publication_status == "withdrawn":
        return ContestDirectionFocusStatusCheck.create(
            **{**verified_values, "retained_for_focus": False},
            outcome="verified_withdrawn_excluded",
        )
    if verified.publication_status == "retracted":
        return ContestDirectionFocusStatusCheck.create(
            **{**verified_values, "retained_for_focus": False},
            outcome="verified_retracted_excluded",
        )
    if (
        verified.publication_status == paper.publication_status
        and verified.status_source == paper.status_source
        and verified.status_as_of == paper.status_as_of
    ):
        return ContestDirectionFocusStatusCheck.create(
            **verified_values,
            outcome="verification_returned_unchanged_upstream_degraded",
        )
    return ContestDirectionFocusStatusCheck.create(
        **verified_values,
        outcome="verified_eligible",
    )


def _is_arxiv_record(record: ContestDirectionLiteratureRecord) -> bool:
    return (
        record.paper_source.casefold() == "arxiv"
        or any(item.source.casefold() == "arxiv" for item in record.retrievals)
        or _arxiv_status_url(record) is not None
    )


def _arxiv_status_url(record: ContestDirectionLiteratureRecord) -> str | None:
    value = str(record.url or "").strip()
    if re.match(
        r"^https?://(?:(?:www|export)\.)?arxiv\.org/(?:abs|pdf)/",
        value,
        flags=re.IGNORECASE,
    ):
        return value
    repository_doi = str(record.repository_doi or "").strip()
    match = re.fullmatch(
        r"10\.48550/arxiv\.([A-Za-z0-9._/-]+)",
        repository_doi,
        flags=re.IGNORECASE,
    )
    if match:
        return f"https://arxiv.org/abs/{match.group(1)}"
    return None


def _record_as_arxiv_paper(
    record: ContestDirectionLiteratureRecord,
    *,
    url: str,
) -> AcademicPaper:
    return AcademicPaper(
        title=record.title,
        authors=list(record.authors),
        abstract=record.abstract,
        publication_date=record.publication_date,
        venue=record.venue,
        doi=record.doi,
        repository_doi=record.repository_doi,
        url=url,
        citation_count=record.citation_count,
        citation_count_source=record.citation_count_source,
        citation_count_as_of=record.citation_count_as_of,
        publication_status=record.publication_status,
        status_source=record.status_source,
        status_as_of=record.status_as_of,
        source="arxiv",
    )


def _same_verification_paper(left: AcademicPaper, right: AcademicPaper) -> bool:
    excluded = {"publication_status", "status_source", "status_as_of"}
    return left.model_dump(mode="json", exclude=excluded) == right.model_dump(
        mode="json", exclude=excluded
    )


def _status_check_is_degraded(check: ContestDirectionFocusStatusCheck) -> bool:
    return check.outcome in {
        "verification_failed_preserved_upstream_degraded",
        "verification_returned_unchanged_upstream_degraded",
        "arxiv_missing_verifiable_url_preserved_upstream_degraded",
    }


def _status_verification_label(
    receipt: ContestDirectionFocusStatusReceipt | None,
) -> Literal[
    "upstream_provenance_retained_status_not_rechecked",
    "shortlisted_arxiv_status_rechecked_complete",
    "shortlisted_arxiv_status_rechecked_degraded",
]:
    if receipt is None:
        return "upstream_provenance_retained_status_not_rechecked"
    if receipt.verification_state == "degraded":
        return "shortlisted_arxiv_status_rechecked_degraded"
    return "shortlisted_arxiv_status_rechecked_complete"


def _status_evidence_label(
    check: ContestDirectionFocusStatusCheck,
) -> Literal[
    "verified_by_caller_injected_shortlist_verifier",
    "verification_failed_preserved_upstream_status_degraded",
    "verification_returned_unchanged_upstream_status_degraded",
    "non_arxiv_no_verification_needed",
    "arxiv_missing_verifiable_url_preserved_upstream_status_degraded",
]:
    if check.outcome == "not_arxiv_no_verification_needed":
        return "non_arxiv_no_verification_needed"
    if check.outcome == "verification_failed_preserved_upstream_degraded":
        return "verification_failed_preserved_upstream_status_degraded"
    if check.outcome == "verification_returned_unchanged_upstream_degraded":
        return "verification_returned_unchanged_upstream_status_degraded"
    if check.outcome == "arxiv_missing_verifiable_url_preserved_upstream_degraded":
        return "arxiv_missing_verifiable_url_preserved_upstream_status_degraded"
    if check.outcome != "verified_eligible":
        raise ContestDirectionFocusError("excluded focus status check reached evidence projection")
    return "verified_by_caller_injected_shortlist_verifier"


def _project_focus_candidates(
    payload: Mapping[str, Any],
    *,
    evidence_count: int,
    adapter_capabilities: Sequence[ContestDirectionFocusAdapterCapability],
) -> tuple[ContestDirectionFocusCandidate, ...]:
    raw = _first_present(payload, "candidates", "focus_candidates", "directions", "ideas")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray):
        raise ContestDirectionFocusError("focus brainstorm must contain a candidate list")
    capability_by_id = {item.adapter_id: item for item in adapter_capabilities}
    candidates: list[ContestDirectionFocusCandidate] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        title = _mapping_text(item, "title_cn", "title", "focus", "direction")
        gap = _mapping_text(item, "problem_gap_cn", "problem_gap", "gap", "rationale")
        objective = _mapping_text(
            item,
            "falsifiable_objective_cn",
            "falsifiable_objective",
            "research_objective_cn",
            "objective",
        )
        focused_direction = _mapping_text(
            item,
            "focused_direction_cn",
            "focused_direction",
            "research_focus_cn",
        )
        if not focused_direction and title and objective:
            focused_direction = f"{title}：{objective}"
        evidence_rationale = _mapping_text(
            item,
            "evidence_rationale_cn",
            "evidence_rationale",
            "evidence_chain",
            "support",
        )
        nearest, methods, counter = _project_query_groups(item)
        references = _project_indices(
            _first_present(item, "evidence_indices", "reference_indices", "references", "evidence"),
            upper=evidence_count,
        )
        if not references:
            # Qwen sometimes cites the locked evidence explicitly in its prose
            # (for example ``证据[7]``) but omits the redundant integer array.
            # Recover only those literal indices; never infer or invent one.
            references = _inline_evidence_indices(
                evidence_rationale,
                upper=evidence_count,
            )
        pilot_adapter_id = _normalize_pilot_adapter_id(
            _mapping_text(
                item,
                "pilot_adapter_id",
                "adapter_id",
                "executable_adapter_id",
            )
        )
        if pilot_adapter_id not in set(capability_by_id) | {"no_adapter"}:
            raise ContestDirectionFocusError(
                "focus candidate selected an unavailable pilot adapter capability"
            )
        pilot_feasibility = _mapping_text(
            item,
            "pilot_feasibility_cn",
            "pilot_feasibility",
            "adapter_fit_cn",
            "execution_feasibility_cn",
        )
        if pilot_adapter_id != "no_adapter":
            compatibility = assess_adapter_semantic_compatibility(
                capability_by_id[pilot_adapter_id],
                scope_texts=(title, focused_direction, objective),
            )
            if not compatibility.compatible:
                rejected_adapter = pilot_adapter_id
                pilot_adapter_id = "no_adapter"
                pilot_feasibility = (
                    f"程序语义兼容性门拒绝{rejected_adapter}：候选需要该runner执行边界外的"
                    f"科学对象变换或度量（{','.join(compatibility.reason_codes)}）；"
                    "当前不能直接执行真实pilot。"
                )
        if not pilot_feasibility:
            pilot_feasibility = (
                "当前候选未绑定已声明的可执行预实验适配器。"
                if pilot_adapter_id == "no_adapter"
                else (
                    f"候选声明与已提供的{pilot_adapter_id}能力对齐；"
                    "仍须在预实验阶段验证输入和执行边界。"
                )
            )
        if not all(
            (
                title,
                focused_direction,
                gap,
                objective,
                evidence_rationale,
                nearest,
                methods,
                counter,
                references,
            )
        ):
            continue
        identity = canonical_model_hash(
            {
                "title": title,
                "focused_direction": focused_direction,
                "gap": gap,
                "objective": objective,
                "nearest": list(nearest),
                "methods": list(methods),
                "counter": list(counter),
                "references": list(references),
                "pilot_adapter_id": pilot_adapter_id,
                "pilot_feasibility": pilot_feasibility,
            }
        )
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(
            ContestDirectionFocusCandidate.create(
                candidate_number=len(candidates) + 1,
                title_cn=title,
                focused_direction_cn=focused_direction,
                problem_gap_cn=gap,
                falsifiable_objective_cn=objective,
                evidence_rationale_cn=evidence_rationale,
                nearest_work_queries=nearest,
                methods_baselines_queries=methods,
                counterevidence_queries=counter,
                evidence_indices=references,
                pilot_adapter_id=pilot_adapter_id,
                pilot_feasibility_cn=pilot_feasibility,
            )
        )
        if len(candidates) == 4:
            break
    if len(candidates) < 2:
        raise ContestDirectionFocusError(
            "focus brainstorm produced fewer than two complete, distinct candidates"
        )
    return tuple(candidates)


def _project_query_groups(
    item: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    nested = item.get("search_queries")
    nested_mapping = nested if isinstance(nested, Mapping) else {}
    nearest = _normalize_query_values(
        _first_present(item, "nearest_work_queries", "nearest_queries", "prior_work_queries")
        or _first_present(nested_mapping, "nearest_work", "nearest", "prior_work")
    )
    methods = _normalize_query_values(
        _first_present(
            item,
            "methods_baselines_queries",
            "method_baseline_queries",
            "methods_queries",
        )
        or _first_present(nested_mapping, "methods_baselines", "methods", "baselines")
    )
    counter = _normalize_query_values(
        _first_present(
            item,
            "counterevidence_queries",
            "counter_evidence_queries",
            "failure_queries",
        )
        or _first_present(nested_mapping, "counterevidence", "failures", "alternatives")
    )
    return nearest, methods, counter


def _inline_evidence_indices(text: str, *, upper: int) -> tuple[int, ...]:
    values: list[int] = []
    for raw in re.findall(r"(?:证据|文献|参考)?\s*[\[【]\s*(\d+)\s*[\]】]", text):
        value = int(raw)
        if 1 <= value <= upper and value not in values:
            values.append(value)
    return tuple(values)


def _project_focus_selection(
    payload: Mapping[str, Any],
    *,
    candidates: Sequence[ContestDirectionFocusCandidate],
) -> tuple[int, str]:
    raw_choice = _first_present(
        payload,
        "selected_candidate_number",
        "candidate_number",
        "selected_index",
        "choice",
        "selected_candidate_id",
    )
    selected_number: int | None = None
    if isinstance(raw_choice, int) and not isinstance(raw_choice, bool):
        selected_number = raw_choice
    elif isinstance(raw_choice, str):
        stripped = raw_choice.strip()
        for candidate in candidates:
            if stripped == candidate.candidate_id:
                selected_number = candidate.candidate_number
                break
        if selected_number is None:
            match = re.search(r"\d+", stripped)
            if match:
                selected_number = int(match.group())
    allowed = {item.candidate_number for item in candidates}
    if selected_number not in allowed:
        raise ContestDirectionFocusError("focus selector chose an unavailable candidate")
    rationale = _mapping_text(
        payload,
        "selection_rationale_cn",
        "selection_rationale",
        "rationale",
        "reason",
    )
    if not rationale:
        raise ContestDirectionFocusError("focus selector omitted its scientific rationale")
    return selected_number, rationale


def _targeted_search_context(focus: ContestDirectionFocusArtifact) -> str:
    selected = focus.selected_candidate
    return "\n".join(
        (
            f"原始科学问题：{focus.direction}",
            f"暂定研究焦点：{selected.title_cn}",
            f"后续科研阶段使用的聚焦方向：{selected.focused_direction_cn}",
            f"待核对的证据缺口：{selected.problem_gap_cn}",
            f"可证伪研究目标：{selected.falsifiable_objective_cn}",
            f"最近相邻工作线索：{'；'.join(selected.nearest_work_queries)}",
            f"方法、基线与评价线索：{'；'.join(selected.methods_baselines_queries)}",
            f"反证、失败与替代解释线索：{'；'.join(selected.counterevidence_queries)}",
            "边界：这是待第二轮真实检索核对的暂定方向，尚未证明新颖性。",
        )
    )


def _targeted_input_hash(
    focus: ContestDirectionFocusArtifact,
    targeted_search_context: str,
) -> str:
    return canonical_model_hash(
        {
            "focus_artifact_hash": focus.artifact_hash,
            "selected_focus_id": focus.selected_focus_id,
            "targeted_search_context": targeted_search_context,
            "selected_method_skills": [],
        }
    )


def _call_or_load_response(
    *,
    root: Path,
    receipt_path: Path,
    stage_name: Literal[
        "direction-focus-brainstorm",
        "direction-focus-selection",
        "direction-targeted-query",
    ],
    stage_input_hash: str,
    messages: Sequence[Mapping[str, str]],
    config_path: Path | str,
    env_path: Path | str,
    timeout_seconds: int | None,
    max_tokens: int,
    response_schema: Mapping[str, Any] | None = None,
    response_schema_name: str | None = None,
    completion: CompletionCallable,
) -> ContestDirectionFocusResponseReceipt:
    if receipt_path.is_file():
        receipt = ContestDirectionFocusResponseReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        if (
            receipt.stage_name != stage_name
            or receipt.stage_input_hash != stage_input_hash
            or receipt.messages != tuple(dict(item) for item in messages)
        ):
            raise ContestDirectionFocusError("saved response receipt has different inputs")
        return receipt
    replayable = replayable_stage_completion(
        root=root,
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        completion=completion,
    )
    completion_kwargs: dict[str, Any] = {
        "messages": [dict(item) for item in messages],
        "config_path": config_path,
        "env_path": env_path,
        "timeout_seconds": timeout_seconds,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "thinking_mode": "disabled",
        "thinking_budget": None,
    }
    if response_schema is not None:
        completion_kwargs["response_schema"] = dict(response_schema)
        completion_kwargs["response_schema_name"] = response_schema_name
    result = replayable(
        **completion_kwargs,
    )
    receipt = ContestDirectionFocusResponseReceipt.create(
        stage_name=stage_name,
        stage_input_hash=stage_input_hash,
        messages=messages,
        completion=result,
    )
    _write_once_model(receipt_path, receipt)
    return receipt


def _load_bound_receipt(
    root: Path,
    binding: ContestFocusFileBinding,
) -> ContestDirectionFocusResponseReceipt:
    _verify_file_binding(root, binding)
    return ContestDirectionFocusResponseReceipt.model_validate_json(
        _resolve_binding(root, binding).read_text(encoding="utf-8")
    )


def _mapping_text(payload: Mapping[str, Any], *keys: str) -> str:
    value = _first_present(payload, *keys)
    return value.strip() if isinstance(value, str) else ""


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _normalize_query_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw: Sequence[Any] = re.split(r"[\r\n]+|\s*;\s*|\s*；\s*", value)
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        raw = value
    else:
        return ()
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        normalized = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", item).strip()
        if normalized and normalized not in values:
            values.append(normalized)
        if len(values) == 4:
            break
    return tuple(values)


def _project_indices(value: Any, *, upper: int) -> tuple[int, ...]:
    if isinstance(value, int) and not isinstance(value, bool):
        raw: Sequence[Any] = (value,)
    elif isinstance(value, str):
        raw = tuple(int(item) for item in re.findall(r"\d+", value))
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        raw = value
    else:
        return ()
    indices: list[int] = []
    for item in raw:
        if isinstance(item, int) and not isinstance(item, bool):
            index = item
        elif isinstance(item, str) and re.fullmatch(r"\s*\[?\d+\]?\s*", item):
            index = int(re.search(r"\d+", item).group())  # type: ignore[union-attr]
        else:
            continue
        if 1 <= index <= upper and index not in indices:
            indices.append(index)
    return tuple(indices)


def _normalize_adapter_capabilities(
    records: Sequence[Mapping[str, Any]],
) -> tuple[ContestDirectionFocusAdapterCapability, ...]:
    """Keep only safe scientific capability fields and canonicalize their order."""

    capabilities: list[ContestDirectionFocusAdapterCapability] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ContestDirectionFocusError("adapter capability must be a mapping")
        adapter_id = str(record.get("adapter_id") or "").strip()
        scientific_object = str(record.get("scientific_object") or "").strip()
        observable = str(record.get("observable") or "").strip()
        execution_boundary = str(record.get("execution_boundary_zh") or "").strip()
        metrics = _normalize_capability_values(record.get("supported_metrics"))
        nulls = _normalize_capability_values(record.get("supported_nulls"))
        if (
            not adapter_id
            or not scientific_object
            or not observable
            or not execution_boundary
            or not metrics
            or not nulls
        ):
            raise ContestDirectionFocusError("adapter capability metadata is incomplete")
        if adapter_id in seen:
            raise ContestDirectionFocusError("adapter capability ID is repeated")
        seen.add(adapter_id)
        description = str(record.get("description") or "").strip() or None
        capabilities.append(
            ContestDirectionFocusAdapterCapability(
                adapter_id=adapter_id,
                scientific_object=scientific_object,
                observable=observable,
                supported_metrics=metrics,
                supported_nulls=nulls,
                execution_boundary_zh=execution_boundary,
                description=description,
            )
        )
    return tuple(sorted(capabilities, key=lambda item: item.adapter_id))


def _normalize_capability_values(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _normalize_pilot_adapter_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized.casefold() in {
        "none",
        "no-adapter",
        "no_adapter",
        "unavailable",
        "无",
        "无适配器",
    }:
        return "no_adapter"
    return normalized


def _normalize_texts(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))


def _required_text(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ContestDirectionFocusError(f"{label} must not be blank")
    return normalized


def _selected_focus_id(
    *,
    candidate: ContestDirectionFocusCandidate,
    selection_receipt_hash: str,
) -> str:
    digest = canonical_model_hash(
        {
            "candidate_id": candidate.candidate_id,
            "candidate_payload_hash": candidate.candidate_payload_hash,
            "selection_receipt_hash": selection_receipt_hash,
        }
    )
    return f"direction-focus-{digest[:16]}"


def _file_binding(root: Path, path: Path) -> ContestFocusFileBinding:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ContestDirectionFocusError("artifact file escapes output root") from exc
    if not resolved_path.is_file():
        raise ContestDirectionFocusError(f"artifact file is missing: {relative}")
    raw = resolved_path.read_bytes()
    return ContestFocusFileBinding(
        relative_path=relative,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _resolve_binding(root: Path, binding: ContestFocusFileBinding) -> Path:
    path = (root / binding.relative_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ContestDirectionFocusError("artifact binding escapes output root") from exc
    return path


def _verify_file_binding(root: Path, binding: ContestFocusFileBinding) -> None:
    path = _resolve_binding(root, binding)
    if not path.is_file():
        raise ContestDirectionFocusError(f"bound artifact is missing: {binding.relative_path}")
    raw = path.read_bytes()
    if len(raw) != binding.size_bytes or hashlib.sha256(raw).hexdigest() != binding.sha256:
        raise ContestDirectionFocusError(f"bound artifact changed: {binding.relative_path}")


def _require_matching_model_file(path: Path, model: StrictFrozenModel) -> None:
    if not path.is_file():
        raise ContestDirectionFocusError(f"required artifact is missing: {path.name}")
    try:
        current = type(model).model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContestDirectionFocusError(f"required artifact is invalid: {path.name}") from exc
    if current != model:
        raise ContestDirectionFocusError(
            f"required artifact differs from supplied model: {path.name}"
        )


def _write_once_model(path: Path, model: StrictFrozenModel) -> None:
    payload = model.model_dump(mode="json")
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        if path.read_bytes() != raw:
            raise ContestDirectionFocusError(
                f"refusing to overwrite different artifact bytes: {path.name}"
            ) from exc
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ContestDirectionFocusAdapterCapability",
    "ContestDirectionFocusArtifact",
    "ContestDirectionFocusCandidate",
    "ContestDirectionFocusError",
    "ContestDirectionFocusEvidence",
    "ContestDirectionFocusResponseReceipt",
    "ContestDirectionFocusStatusCheck",
    "ContestDirectionFocusStatusReceipt",
    "ContestDirectionTargetedRetrievalBinding",
    "build_contest_direction_focus_brainstorm_messages",
    "build_contest_direction_focus_selection_messages",
    "load_contest_direction_focus_selection",
    "load_contest_direction_targeted_retrieval",
    "run_contest_direction_focus_selection",
    "run_contest_direction_targeted_retrieval",
]
