"""Parent-bound contracts for a model-generated scientific mechanism round.

Task 261.2 must not turn a prompt rewrite or a rerun of the revealed Sprint
panel into a new scientific result.  This module freezes the evidence boundary
before generation or execution:

* the completed clean-v2 Sprint is revalidated as an immutable negative parent;
* a verified, multi-perspective literature brief is content addressed;
* diagnosis, generated code, security/test evidence, and panel partitions have
  explicit causal hashes;
* development and confirmatory tasks cannot overlap each other or the revealed
  parent panel; and
* manuscript claims must resolve to typed literature or execution evidence.

The module intentionally does not call a model or execute generated code.
Those actions belong to task 261.2.2 after these contracts are frozen.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from autoresearch.campaign.sprint import (
    AutonomyLevel,
    SprintAutonomyAudit,
    SprintManifest,
    SprintOutcome,
    SprintStage,
    SprintTopicSelection,
    TaskLevelEndpointResult,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)
from autoresearch.schemas import file_hash

EXPECTED_PARENT_SPRINT_ID = "task261-bounded-autonomous-clean-v2"
EXPECTED_PARENT_MANIFEST_HASH = (
    "eb3ac1c5411b4444e6512a5119ecff1afbbedb736ace12e2f7329d3e90c1e33e"
)
EXPECTED_PARENT_ENDPOINT_HASH = (
    "e4535efd50c34c2d104b367dfa1fc3a7ba1dde51081d8b07738d8c68e9c03c52"
)
EXPECTED_PARENT_AUDIT_HASH = (
    "23e8333334f9e8cb01f8a60303a672a992b628fa94bcabb90851f433561cc360"
)
REQUIRED_PARENT_FAILURES = ("bootstrap_ci_lower_above_zero",)
FORBIDDEN_NON_MECHANISM_CHANGES = (
    "manuscript_only_change",
    "prompt_only_change",
    "revealed_panel_rerun",
    "threshold_only_change",
)

ContractT = TypeVar("ContractT", bound=BaseModel)


class MechanismRoundIntegrityError(ValueError):
    """Raised when a mechanism-round causal or content hash is invalid."""


class LiteratureArea(str, Enum):
    """Independent evidence areas required by the frozen research brief."""

    SELECTIVE_FACTUALITY = "selective_factuality"
    SCIENTIFIC_AGENT_EVALUATION = "scientific_agent_evaluation"
    GENERATED_CODE_SECURITY = "generated_code_security"
    CLAIM_EVIDENCE_ALIGNMENT = "claim_evidence_alignment"


class LiteratureSourceKind(str, Enum):
    """Evidence maturity for one verified source."""

    PEER_REVIEWED = "peer_reviewed"
    PREPRINT = "preprint"
    OFFICIAL_STANDARD = "official_standard"


class MechanismChangeKind(str, Enum):
    """Mechanism-level changes that may be proposed after diagnosis."""

    RISK_SELECTIVE_GATE = "risk_selective_gate"
    VERIFIER_ENSEMBLE = "verifier_ensemble"
    EXTERNAL_FEEDBACK_CONTROL = "external_feedback_control"
    OTHER_EXECUTABLE_MECHANISM = "other_executable_mechanism"


class ClaimKind(str, Enum):
    """Material manuscript claim classes that require explicit evidence."""

    NAMED_PRIOR_WORK = "named_prior_work"
    METHOD = "method"
    EXPERIMENT = "experiment"
    RESULT = "result"
    LIMITATION = "limitation"
    FIGURE_DESCRIPTION = "figure_description"


class ClaimEvidenceKind(str, Enum):
    """Evidence surfaces admitted by the manuscript claim audit."""

    VERIFIED_LITERATURE = "verified_literature"
    GENERATED_CODE = "generated_code"
    PREREGISTERED_PROTOCOL = "preregistered_protocol"
    EXECUTION_ARTIFACT = "execution_artifact"
    METRIC = "metric"
    ADJUDICATION = "adjudication"
    FAILURE_OR_UNCERTAINTY = "failure_or_uncertainty"
    FIGURE_ARTIFACT = "figure_artifact"


class MechanismLiteratureSource(KernelContract):
    """One existence- and abstract-verified source in the research brief."""

    source_id: StableId
    title: NonEmptyText
    authors: list[NonEmptyText] = Field(min_length=1)
    year: int = Field(ge=2000, le=2100)
    venue: NonEmptyText
    locator: NonEmptyText
    source_url: NonEmptyText
    source_kind: LiteratureSourceKind
    areas: list[LiteratureArea] = Field(min_length=1)
    finding: NonEmptyText
    limitation: NonEmptyText
    verification_grade: Literal["verified"] = "verified"

    @field_validator("areas")
    @classmethod
    def _normalize_areas(cls, value: list[LiteratureArea]) -> list[LiteratureArea]:
        if len(value) != len(set(value)):
            raise ValueError("literature source areas must be unique")
        return sorted(value, key=lambda item: item.value)


class ParentSprintEvidence(KernelContract):
    """Portable, path-free identity for the immutable clean-v2 negative parent."""

    schema_version: Literal["mechanism-parent-sprint-v1"] = (
        "mechanism-parent-sprint-v1"
    )
    parent_sprint_id: StableId
    manifest_file_sha256: Sha256
    manifest_hash: Sha256
    endpoint_file_sha256: Sha256
    endpoint_hash: Sha256
    autonomy_audit_file_sha256: Sha256
    autonomy_audit_hash: Sha256
    topic_selection_file_sha256: Sha256
    topic_selection_hash: Sha256
    selected_candidate_id: StableId
    selected_program_id: StableId
    scientific_endpoint: Literal["negative_result"] = "negative_result"
    parent_failure_codes: list[StableId] = Field(min_length=1)
    revealed_task_ids: list[StableId] = Field(min_length=1)
    autonomy_level: Literal["bounded_autonomous"] = "bounded_autonomous"
    external_submission_authorized: Literal[False] = False
    evidence_hash: Sha256

    @field_validator("parent_failure_codes", "revealed_task_ids")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("parent evidence identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> ParentSprintEvidence:
        if self.evidence_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("parent evidence_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> ParentSprintEvidence:
        """Attach a canonical digest to validated parent evidence."""

        payload = dict(values)
        payload["schema_version"] = "mechanism-parent-sprint-v1"
        payload["scientific_endpoint"] = "negative_result"
        payload["autonomy_level"] = "bounded_autonomous"
        payload["external_submission_authorized"] = False
        payload["parent_failure_codes"] = sorted(payload["parent_failure_codes"])
        payload["revealed_task_ids"] = sorted(payload["revealed_task_ids"])
        payload["evidence_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the parent evidence digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_hash"})
        )


class MechanismResearchBrief(KernelContract):
    """Frozen questions, search perspectives, corpus, and evidence-earned angle."""

    schema_version: Literal["mechanism-research-brief-v1"] = (
        "mechanism-research-brief-v1"
    )
    brief_id: StableId
    parent_endpoint_hash: Sha256
    topic: NonEmptyText
    research_questions: list[NonEmptyText] = Field(min_length=3, max_length=3)
    search_perspectives: list[NonEmptyText] = Field(min_length=4)
    intended_reader: NonEmptyText
    inclusion_rule: NonEmptyText
    exclusion_rule: NonEmptyText
    angle: NonEmptyText
    sources: list[MechanismLiteratureSource] = Field(min_length=12)
    brief_hash: Sha256

    @model_validator(mode="after")
    def _validate_brief(self) -> MechanismResearchBrief:
        if len(self.research_questions) != len(set(self.research_questions)):
            raise ValueError("research questions must be unique")
        if len(self.search_perspectives) != len(set(self.search_perspectives)):
            raise ValueError("search perspectives must be unique")
        source_ids = [source.source_id for source in self.sources]
        if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
            raise ValueError("literature sources must be unique and source-id sorted")
        for area in LiteratureArea:
            coverage = sum(area in source.areas for source in self.sources)
            if coverage < 3:
                raise ValueError(
                    f"research brief needs at least three sources for {area.value}"
                )
        if self.brief_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("research brief_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismResearchBrief:
        """Normalize the corpus and attach the research-brief digest."""

        payload = dict(values)
        payload["schema_version"] = "mechanism-research-brief-v1"
        sources = [
            source
            if isinstance(source, MechanismLiteratureSource)
            else MechanismLiteratureSource.model_validate(source)
            for source in payload["sources"]
        ]
        payload["sources"] = [
            source.model_dump(mode="json")
            for source in sorted(sources, key=lambda item: item.source_id)
        ]
        payload["brief_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the research-brief digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"brief_hash"})
        )


class MechanismDiagnosis(KernelContract):
    """Model-authored, parent-bound explanation of what must change."""

    schema_version: Literal["mechanism-diagnosis-v1"] = "mechanism-diagnosis-v1"
    diagnosis_id: StableId
    parent_evidence_hash: Sha256
    parent_endpoint_hash: Sha256
    research_brief_hash: Sha256
    observed_failure_codes: list[StableId] = Field(min_length=1)
    causal_hypotheses: list[NonEmptyText] = Field(min_length=2)
    required_mechanism_properties: list[NonEmptyText] = Field(min_length=2)
    forbidden_change_codes: list[StableId]
    literature_source_ids: list[StableId] = Field(min_length=3)
    model_interaction_hash: Sha256
    external_submission_authorized: Literal[False] = False
    diagnosis_hash: Sha256

    @field_validator(
        "observed_failure_codes",
        "forbidden_change_codes",
        "literature_source_ids",
    )
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("diagnosis identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_diagnosis(self) -> MechanismDiagnosis:
        if self.forbidden_change_codes != sorted(FORBIDDEN_NON_MECHANISM_CHANGES):
            raise ValueError("diagnosis must retain every forbidden non-mechanism change")
        if self.diagnosis_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("diagnosis_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        parent: ParentSprintEvidence,
        brief: MechanismResearchBrief,
        diagnosis_id: str,
        causal_hypotheses: list[str],
        required_mechanism_properties: list[str],
        literature_source_ids: list[str],
        model_interaction_hash: str,
    ) -> MechanismDiagnosis:
        """Create a diagnosis only from the frozen parent and verified corpus."""

        known_sources = {source.source_id for source in brief.sources}
        if not set(literature_source_ids).issubset(known_sources):
            raise ValueError("diagnosis references an unknown literature source")
        payload: dict[str, Any] = {
            "schema_version": "mechanism-diagnosis-v1",
            "diagnosis_id": diagnosis_id,
            "parent_evidence_hash": parent.evidence_hash,
            "parent_endpoint_hash": parent.endpoint_hash,
            "research_brief_hash": brief.brief_hash,
            "observed_failure_codes": parent.parent_failure_codes,
            "causal_hypotheses": causal_hypotheses,
            "required_mechanism_properties": required_mechanism_properties,
            "forbidden_change_codes": list(FORBIDDEN_NON_MECHANISM_CHANGES),
            "literature_source_ids": literature_source_ids,
            "model_interaction_hash": model_interaction_hash,
            "external_submission_authorized": False,
        }
        payload["diagnosis_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the diagnosis digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"diagnosis_hash"})
        )


class MechanismCodeProposal(KernelContract):
    """A model-authored executable mechanism, not an approval to run it."""

    schema_version: Literal["mechanism-code-proposal-v1"] = (
        "mechanism-code-proposal-v1"
    )
    proposal_id: StableId
    diagnosis_hash: Sha256
    research_brief_hash: Sha256
    mechanism_kind: MechanismChangeKind
    mechanism_title: NonEmptyText
    mechanism_delta: NonEmptyText
    falsification_conditions: list[NonEmptyText] = Field(min_length=2)
    literature_source_ids: list[StableId] = Field(min_length=3)
    expected_entrypoint: Literal["run.py"] = "run.py"
    generated_function: Literal["evaluate_claims"] = "evaluate_claims"
    source_text: str = Field(min_length=40)
    source_sha256: Sha256
    model_interaction_hash: Sha256
    prompt_only_change: Literal[False] = False
    manuscript_only_change: Literal[False] = False
    threshold_only_change: Literal[False] = False
    revealed_panel_rerun: Literal[False] = False
    network_required: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    proposal_hash: Sha256

    @field_validator("literature_source_ids")
    @classmethod
    def _normalize_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("proposal literature references must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_proposal(self) -> MechanismCodeProposal:
        source_digest = hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()
        if self.source_sha256 != source_digest:
            raise MechanismRoundIntegrityError("generated source SHA-256 mismatch")
        if self.proposal_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("proposal_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        diagnosis: MechanismDiagnosis,
        brief: MechanismResearchBrief,
        proposal_id: str,
        mechanism_kind: MechanismChangeKind,
        mechanism_title: str,
        mechanism_delta: str,
        falsification_conditions: list[str],
        literature_source_ids: list[str],
        source_text: str,
        model_interaction_hash: str,
    ) -> MechanismCodeProposal:
        """Bind the proposal text and exact generated bytes to prior evidence."""

        known_sources = {source.source_id for source in brief.sources}
        if not set(literature_source_ids).issubset(known_sources):
            raise ValueError("proposal references an unknown literature source")
        payload: dict[str, Any] = {
            "schema_version": "mechanism-code-proposal-v1",
            "proposal_id": proposal_id,
            "diagnosis_hash": diagnosis.diagnosis_hash,
            "research_brief_hash": brief.brief_hash,
            "mechanism_kind": mechanism_kind.value,
            "mechanism_title": mechanism_title,
            "mechanism_delta": mechanism_delta,
            "falsification_conditions": falsification_conditions,
            "literature_source_ids": sorted(literature_source_ids),
            "expected_entrypoint": "run.py",
            "generated_function": "evaluate_claims",
            "source_text": source_text,
            "source_sha256": hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            "model_interaction_hash": model_interaction_hash,
            "prompt_only_change": False,
            "manuscript_only_change": False,
            "threshold_only_change": False,
            "revealed_panel_rerun": False,
            "network_required": False,
            "external_submission_authorized": False,
        }
        payload["proposal_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the code-proposal digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"proposal_hash"})
        )


class GeneratedCodeEvidence(KernelContract):
    """Static, test, sandbox, and Harness evidence for exact generated bytes."""

    schema_version: Literal["generated-mechanism-code-evidence-v1"] = (
        "generated-mechanism-code-evidence-v1"
    )
    proposal_hash: Sha256
    source_sha256: Sha256
    static_review_report_hash: Sha256
    static_review_approved: bool
    blocking_finding_codes: list[StableId]
    unit_test_report_hash: Sha256
    unit_tests_passed: bool
    property_test_report_hash: Sha256
    property_tests_passed: bool
    harness_spec_hash: Sha256
    sandbox_episode_hash: Sha256
    sandbox_smoke_passed: bool
    network_used: bool
    approved_for_development: bool
    external_submission_authorized: Literal[False] = False
    evidence_hash: Sha256

    @field_validator("blocking_finding_codes")
    @classmethod
    def _normalize_findings(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("blocking generated-code findings must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_evidence(self) -> GeneratedCodeEvidence:
        expected = (
            self.static_review_approved
            and not self.blocking_finding_codes
            and self.unit_tests_passed
            and self.property_tests_passed
            and self.sandbox_smoke_passed
            and not self.network_used
        )
        if self.approved_for_development != expected:
            raise ValueError("generated-code approval contradicts review evidence")
        if self.evidence_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("generated code evidence_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> GeneratedCodeEvidence:
        """Compute the development approval without trusting a caller verdict."""

        payload = dict(values)
        payload["schema_version"] = "generated-mechanism-code-evidence-v1"
        payload["blocking_finding_codes"] = sorted(
            payload.get("blocking_finding_codes", [])
        )
        payload["external_submission_authorized"] = False
        payload["approved_for_development"] = (
            bool(payload["static_review_approved"])
            and not payload["blocking_finding_codes"]
            and bool(payload["unit_tests_passed"])
            and bool(payload["property_tests_passed"])
            and bool(payload["sandbox_smoke_passed"])
            and not bool(payload["network_used"])
        )
        payload["evidence_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the generated-code evidence digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_hash"})
        )


class MechanismTaskReference(KernelContract):
    """One immutable independent task admitted to a panel partition."""

    task_id: StableId
    task_family: StableId
    source_fingerprint: Sha256
    task_contract_hash: Sha256


class MechanismPanelSpec(KernelContract):
    """Result-blind development and confirmatory partitions."""

    schema_version: Literal["mechanism-independent-panel-v1"] = (
        "mechanism-independent-panel-v1"
    )
    panel_id: StableId
    parent_evidence_hash: Sha256
    parent_revealed_task_ids: list[StableId] = Field(min_length=1)
    development_tasks: list[MechanismTaskReference] = Field(min_length=3)
    confirmatory_tasks: list[MechanismTaskReference] = Field(min_length=6)
    confirmatory_visibility: Literal["sealed-until-code-freeze"] = (
        "sealed-until-code-freeze"
    )
    primary_metric: Literal["unsupported_claim_rate_at_minimum_coverage"] = (
        "unsupported_claim_rate_at_minimum_coverage"
    )
    minimum_coverage: float = Field(gt=0.0, le=1.0)
    maximum_unsupported_claim_rate: float = Field(ge=0.0, lt=1.0)
    bootstrap_resamples: int = Field(ge=1_000)
    bootstrap_seed: int = Field(ge=0)
    post_freeze_threshold_change_allowed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    panel_hash: Sha256

    @field_validator("parent_revealed_task_ids")
    @classmethod
    def _normalize_parent_tasks(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("parent revealed task IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_panel(self) -> MechanismPanelSpec:
        development_ids = [task.task_id for task in self.development_tasks]
        confirmatory_ids = [task.task_id for task in self.confirmatory_tasks]
        if len(development_ids) != len(set(development_ids)):
            raise ValueError("development task IDs must be unique")
        if len(confirmatory_ids) != len(set(confirmatory_ids)):
            raise ValueError("confirmatory task IDs must be unique")
        if set(development_ids) & set(confirmatory_ids):
            raise ValueError("development and confirmatory panels must be disjoint")
        parent_ids = set(self.parent_revealed_task_ids)
        if parent_ids & (set(development_ids) | set(confirmatory_ids)):
            raise ValueError("new mechanism panel reuses a revealed parent task")
        if self.development_tasks != sorted(
            self.development_tasks, key=lambda task: task.task_id
        ):
            raise ValueError("development tasks must be task-id sorted")
        if self.confirmatory_tasks != sorted(
            self.confirmatory_tasks, key=lambda task: task.task_id
        ):
            raise ValueError("confirmatory tasks must be task-id sorted")
        if self.panel_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("panel_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        parent: ParentSprintEvidence,
        panel_id: str,
        development_tasks: list[MechanismTaskReference],
        confirmatory_tasks: list[MechanismTaskReference],
        minimum_coverage: float,
        maximum_unsupported_claim_rate: float,
        bootstrap_resamples: int,
        bootstrap_seed: int,
    ) -> MechanismPanelSpec:
        """Freeze disjoint task partitions without exposing confirmatory results."""

        payload: dict[str, Any] = {
            "schema_version": "mechanism-independent-panel-v1",
            "panel_id": panel_id,
            "parent_evidence_hash": parent.evidence_hash,
            "parent_revealed_task_ids": parent.revealed_task_ids,
            "development_tasks": [
                task.model_dump(mode="json")
                for task in sorted(development_tasks, key=lambda item: item.task_id)
            ],
            "confirmatory_tasks": [
                task.model_dump(mode="json")
                for task in sorted(confirmatory_tasks, key=lambda item: item.task_id)
            ],
            "confirmatory_visibility": "sealed-until-code-freeze",
            "primary_metric": "unsupported_claim_rate_at_minimum_coverage",
            "minimum_coverage": minimum_coverage,
            "maximum_unsupported_claim_rate": maximum_unsupported_claim_rate,
            "bootstrap_resamples": bootstrap_resamples,
            "bootstrap_seed": bootstrap_seed,
            "post_freeze_threshold_change_allowed": False,
            "external_submission_authorized": False,
        }
        payload["panel_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the panel digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"panel_hash"})
        )


class MechanismRoundFreeze(KernelContract):
    """Causal freeze before any confirmatory-task result is revealed."""

    schema_version: Literal["mechanism-round-freeze-v1"] = (
        "mechanism-round-freeze-v1"
    )
    round_id: StableId
    parent_evidence_hash: Sha256
    research_brief_hash: Sha256
    diagnosis_hash: Sha256
    proposal_hash: Sha256
    generated_source_sha256: Sha256
    generated_code_evidence_hash: Sha256
    panel_hash: Sha256
    model_generated_mechanism_code_verified: Literal[True] = True
    open_ended_experiment_code_generation: Literal[True] = True
    confirmatory_results_revealed: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    freeze_hash: Sha256

    @model_validator(mode="after")
    def _validate_freeze(self) -> MechanismRoundFreeze:
        if self.freeze_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("mechanism round freeze_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        round_id: str,
        parent: ParentSprintEvidence,
        brief: MechanismResearchBrief,
        diagnosis: MechanismDiagnosis,
        proposal: MechanismCodeProposal,
        code_evidence: GeneratedCodeEvidence,
        panel: MechanismPanelSpec,
    ) -> MechanismRoundFreeze:
        """Close the proposal-to-executed-code chain or fail before confirmation."""

        if diagnosis.parent_evidence_hash != parent.evidence_hash:
            raise MechanismRoundIntegrityError("diagnosis is not bound to the parent")
        if diagnosis.research_brief_hash != brief.brief_hash:
            raise MechanismRoundIntegrityError("diagnosis is not bound to the brief")
        if proposal.diagnosis_hash != diagnosis.diagnosis_hash:
            raise MechanismRoundIntegrityError("proposal is not bound to the diagnosis")
        if proposal.research_brief_hash != brief.brief_hash:
            raise MechanismRoundIntegrityError("proposal is not bound to the brief")
        if code_evidence.proposal_hash != proposal.proposal_hash:
            raise MechanismRoundIntegrityError(
                "generated-code evidence is not bound to the proposal"
            )
        if code_evidence.source_sha256 != proposal.source_sha256:
            raise MechanismRoundIntegrityError(
                "reviewed code differs from the proposed generated source"
            )
        if not code_evidence.approved_for_development:
            raise MechanismRoundIntegrityError(
                "generated code has not passed review, tests, and sandbox smoke"
            )
        if panel.parent_evidence_hash != parent.evidence_hash:
            raise MechanismRoundIntegrityError("panel is not bound to the parent")
        payload: dict[str, Any] = {
            "schema_version": "mechanism-round-freeze-v1",
            "round_id": round_id,
            "parent_evidence_hash": parent.evidence_hash,
            "research_brief_hash": brief.brief_hash,
            "diagnosis_hash": diagnosis.diagnosis_hash,
            "proposal_hash": proposal.proposal_hash,
            "generated_source_sha256": proposal.source_sha256,
            "generated_code_evidence_hash": code_evidence.evidence_hash,
            "panel_hash": panel.panel_hash,
            "model_generated_mechanism_code_verified": True,
            "open_ended_experiment_code_generation": True,
            "confirmatory_results_revealed": False,
            "external_submission_authorized": False,
        }
        payload["freeze_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the mechanism-round freeze digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"freeze_hash"})
        )


class ClaimEvidenceRequirement(KernelContract):
    """Typed evidence requirement for one material manuscript claim."""

    claim_id: StableId
    claim_kind: ClaimKind
    claim_text: NonEmptyText
    required_evidence_kinds: list[ClaimEvidenceKind] = Field(min_length=1)

    @field_validator("required_evidence_kinds")
    @classmethod
    def _normalize_evidence(
        cls,
        value: list[ClaimEvidenceKind],
    ) -> list[ClaimEvidenceKind]:
        if len(value) != len(set(value)):
            raise ValueError("required claim evidence kinds must be unique")
        return sorted(value, key=lambda item: item.value)

    @model_validator(mode="after")
    def _validate_semantic_requirement(self) -> ClaimEvidenceRequirement:
        required_by_kind = {
            ClaimKind.NAMED_PRIOR_WORK: {ClaimEvidenceKind.VERIFIED_LITERATURE},
            ClaimKind.METHOD: {
                ClaimEvidenceKind.GENERATED_CODE,
                ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
            },
            ClaimKind.EXPERIMENT: {
                ClaimEvidenceKind.PREREGISTERED_PROTOCOL,
                ClaimEvidenceKind.EXECUTION_ARTIFACT,
            },
            ClaimKind.RESULT: {
                ClaimEvidenceKind.METRIC,
                ClaimEvidenceKind.ADJUDICATION,
            },
            ClaimKind.LIMITATION: {ClaimEvidenceKind.FAILURE_OR_UNCERTAINTY},
            ClaimKind.FIGURE_DESCRIPTION: {
                ClaimEvidenceKind.FIGURE_ARTIFACT,
                ClaimEvidenceKind.METRIC,
            },
        }
        required = required_by_kind[self.claim_kind]
        if not required.issubset(set(self.required_evidence_kinds)):
            missing = sorted(item.value for item in required - set(self.required_evidence_kinds))
            raise ValueError(
                f"{self.claim_kind.value} claim is missing required evidence: {missing}"
            )
        return self


class ClaimEvidenceLink(KernelContract):
    """One hash-bound support relation for a manuscript claim."""

    claim_id: StableId
    evidence_kind: ClaimEvidenceKind
    evidence_id: StableId
    evidence_hash: Sha256
    supports_claim: bool


class ManuscriptClaimEvidenceAudit(KernelContract):
    """Fail-closed coverage audit without granting submission authority."""

    schema_version: Literal["mechanism-claim-evidence-audit-v1"] = (
        "mechanism-claim-evidence-audit-v1"
    )
    round_freeze_hash: Sha256
    manuscript_sha256: Sha256
    requirements: list[ClaimEvidenceRequirement] = Field(min_length=1)
    links: list[ClaimEvidenceLink] = Field(min_length=1)
    unsupported_claim_ids: list[StableId]
    coverage_complete: bool
    submission_readiness_granted: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    audit_hash: Sha256

    @field_validator("unsupported_claim_ids")
    @classmethod
    def _normalize_unsupported(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("unsupported claim IDs must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_audit(self) -> ManuscriptClaimEvidenceAudit:
        expected_unsupported = _unsupported_claim_ids(self.requirements, self.links)
        if self.unsupported_claim_ids != expected_unsupported:
            raise ValueError("unsupported claim IDs contradict claim-evidence links")
        if self.coverage_complete != (not expected_unsupported):
            raise ValueError("claim-evidence coverage verdict is inconsistent")
        if self.audit_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("claim-evidence audit_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        round_freeze_hash: str,
        manuscript_sha256: str,
        requirements: list[ClaimEvidenceRequirement],
        links: list[ClaimEvidenceLink],
    ) -> ManuscriptClaimEvidenceAudit:
        """Recompute material-claim coverage from typed support links."""

        unsupported = _unsupported_claim_ids(requirements, links)
        payload: dict[str, Any] = {
            "schema_version": "mechanism-claim-evidence-audit-v1",
            "round_freeze_hash": round_freeze_hash,
            "manuscript_sha256": manuscript_sha256,
            "requirements": [
                requirement.model_dump(mode="json")
                for requirement in sorted(
                    requirements,
                    key=lambda item: item.claim_id,
                )
            ],
            "links": [
                link.model_dump(mode="json")
                for link in sorted(
                    links,
                    key=lambda item: (
                        item.claim_id,
                        item.evidence_kind.value,
                        item.evidence_id,
                    ),
                )
            ],
            "unsupported_claim_ids": unsupported,
            "coverage_complete": not unsupported,
            "submission_readiness_granted": False,
            "external_submission_authorized": False,
        }
        payload["audit_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the claim-evidence audit digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )


class MechanismFoundationManifest(KernelContract):
    """File-level index for the frozen task 261.2.1 foundation."""

    schema_version: Literal["mechanism-foundation-manifest-v1"] = (
        "mechanism-foundation-manifest-v1"
    )
    foundation_id: StableId
    frozen_at: datetime
    parent_evidence_hash: Sha256
    parent_evidence_file_sha256: Sha256
    research_brief_hash: Sha256
    research_brief_file_sha256: Sha256
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @model_validator(mode="after")
    def _validate_manifest(self) -> MechanismFoundationManifest:
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise ValueError("mechanism foundation time must be timezone-aware")
        if self.manifest_hash != self.calculated_hash():
            raise MechanismRoundIntegrityError("foundation manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismFoundationManifest:
        """Attach a canonical digest to the foundation file index."""

        payload = dict(values)
        payload["schema_version"] = "mechanism-foundation-manifest-v1"
        payload["external_submission_authorized"] = False
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"manifest_hash"},
        )
        normalized["manifest_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        """Recompute the foundation manifest digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


def load_parent_sprint_evidence(
    sprint_dir: Path | str,
    *,
    require_formal_clean_v2_identity: bool = True,
) -> ParentSprintEvidence:
    """Revalidate a completed negative Sprint before admitting a child round."""

    root = Path(sprint_dir).resolve()
    manifest_path = root / "sprint-manifest.json"
    if not manifest_path.is_file():
        raise MechanismRoundIntegrityError("parent sprint manifest is missing")
    manifest = _load_stamped_model(
        manifest_path,
        SprintManifest,
        "manifest_hash",
        hash_mode="null",
    )
    _verify_manifest_artifacts(root, manifest)
    if manifest.stage is not SprintStage.COMPLETE:
        raise MechanismRoundIntegrityError("parent sprint is not complete")
    if manifest.outcome is not SprintOutcome.COMPLETED:
        raise MechanismRoundIntegrityError("parent sprint did not complete")
    if manifest.external_submission_authorized:
        raise MechanismRoundIntegrityError("parent sprint unexpectedly authorizes submission")

    endpoint_path = _required_artifact_path(root, manifest, "task_level_endpoint")
    audit_path = _required_artifact_path(root, manifest, "autonomy_audit")
    topic_path = _required_artifact_path(root, manifest, "topic_selection")
    endpoint = _load_stamped_model(
        endpoint_path,
        TaskLevelEndpointResult,
        "endpoint_hash",
        hash_mode="null",
    )
    audit = _load_stamped_model(
        audit_path,
        SprintAutonomyAudit,
        "audit_hash",
        hash_mode="null",
    )
    selection = _load_stamped_model(
        topic_path,
        SprintTopicSelection,
        "selection_hash",
        hash_mode="null",
    )
    if endpoint.sprint_id != manifest.sprint_id:
        raise MechanismRoundIntegrityError("parent endpoint belongs to another sprint")
    if audit.sprint_id != manifest.sprint_id:
        raise MechanismRoundIntegrityError("parent autonomy audit belongs to another sprint")
    if selection.sprint_id != manifest.sprint_id:
        raise MechanismRoundIntegrityError("parent topic selection belongs to another sprint")
    if endpoint.passed or not endpoint.failures:
        raise MechanismRoundIntegrityError("child mechanism requires a retained negative parent")
    if not set(REQUIRED_PARENT_FAILURES).issubset(set(endpoint.failures)):
        raise MechanismRoundIntegrityError(
            "parent did not fail the frozen task-level uncertainty gate"
        )
    if endpoint.external_submission_authorized or audit.external_submission_authorized:
        raise MechanismRoundIntegrityError("parent artifacts authorize external submission")
    if audit.autonomy_level is not AutonomyLevel.BOUNDED_AUTONOMOUS:
        raise MechanismRoundIntegrityError("parent autonomy level is not bounded_autonomous")
    if audit.checks.get("open_ended_experiment_code_generation") is not False:
        raise MechanismRoundIntegrityError(
            "parent already claims generated experiment-code autonomy"
        )
    if selection.used_fallback:
        raise MechanismRoundIntegrityError("parent topic selection used a fallback")
    if endpoint.topic_selection_hash != selection.selection_hash:
        raise MechanismRoundIntegrityError("parent endpoint/topic hash mismatch")
    if manifest.selected_candidate_id != endpoint.candidate_id:
        raise MechanismRoundIntegrityError("parent candidate identity mismatch")
    if manifest.selected_program_id != endpoint.program_id:
        raise MechanismRoundIntegrityError("parent program identity mismatch")

    if require_formal_clean_v2_identity:
        expected = {
            "sprint_id": EXPECTED_PARENT_SPRINT_ID,
            "manifest_hash": EXPECTED_PARENT_MANIFEST_HASH,
            "endpoint_hash": EXPECTED_PARENT_ENDPOINT_HASH,
            "audit_hash": EXPECTED_PARENT_AUDIT_HASH,
        }
        observed = {
            "sprint_id": manifest.sprint_id,
            "manifest_hash": manifest.manifest_hash,
            "endpoint_hash": endpoint.endpoint_hash,
            "audit_hash": audit.audit_hash,
        }
        if observed != expected:
            raise MechanismRoundIntegrityError(
                "parent does not match the formal clean-v2 identity"
            )

    return ParentSprintEvidence.create(
        parent_sprint_id=manifest.sprint_id,
        manifest_file_sha256=file_hash(manifest_path),
        manifest_hash=_required_hash(manifest.manifest_hash, "manifest"),
        endpoint_file_sha256=file_hash(endpoint_path),
        endpoint_hash=_required_hash(endpoint.endpoint_hash, "endpoint"),
        autonomy_audit_file_sha256=file_hash(audit_path),
        autonomy_audit_hash=_required_hash(audit.audit_hash, "autonomy audit"),
        topic_selection_file_sha256=file_hash(topic_path),
        topic_selection_hash=_required_hash(selection.selection_hash, "topic selection"),
        selected_candidate_id=endpoint.candidate_id,
        selected_program_id=endpoint.program_id,
        parent_failure_codes=list(endpoint.failures),
        revealed_task_ids=list(endpoint.paired_task_differences),
    )


def task2612_verified_sources() -> list[MechanismLiteratureSource]:
    """Return the manually verified, primary/official task 261.2 source corpus."""

    return [
        MechanismLiteratureSource(
            source_id="source-001",
            title="Evaluating large language models for accuracy incentivizes hallucinations",
            authors=[
                "Adam Tauman Kalai",
                "Ofir Nachum",
                "Santosh S. Vempala",
                "Edwin Zhang",
            ],
            year=2026,
            venue="Nature 653",
            locator="doi:10.1038/s41586-026-10549-w",
            source_url="https://www.nature.com/articles/s41586-026-10549-w",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.SELECTIVE_FACTUALITY],
            finding=(
                "Accuracy-only evaluation rewards guessing; an open rubric with explicit "
                "error costs is needed to make abstention an auditable choice."
            ),
            limitation=(
                "The paper establishes incentive effects, not a ready-made scientific-agent "
                "claim gate or a guarantee for this repository's task distribution."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-002",
            title="Detecting hallucinations in large language models using semantic entropy",
            authors=[
                "Sebastian Farquhar",
                "Jannik Kossen",
                "Lorenz Kuhn",
                "Yarin Gal",
            ],
            year=2024,
            venue="Nature 630",
            locator="doi:10.1038/s41586-024-07421-0",
            source_url="https://www.nature.com/articles/s41586-024-07421-0",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.SELECTIVE_FACTUALITY],
            finding=(
                "Meaning-level disagreement can identify confabulations and improve the "
                "accuracy-coverage trade-off when uncertain outputs are rejected."
            ),
            limitation=(
                "Semantic entropy targets confabulation under sampled generations; it does "
                "not verify external evidence or scientific causal claims by itself."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-003",
            title=(
                "When Can Conformal Risk Control Certify LLM Outputs? Bounds, "
                "Impossibility, and Adaptation for Structured Generation"
            ),
            authors=["Varun Kotte"],
            year=2026,
            venue="arXiv preprint",
            locator="arXiv:2606.29054",
            source_url="https://arxiv.org/abs/2606.29054",
            source_kind=LiteratureSourceKind.PREPRINT,
            areas=[LiteratureArea.SELECTIVE_FACTUALITY],
            finding=(
                "Risk certification needs an explicit feasibility check and can become "
                "impossible at strict targets; distribution shift leaves residual failures."
            ),
            limitation=(
                "This is a recent preprint and its guarantees require exchangeability and "
                "task-specific risk definitions that must not be assumed here."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-004",
            title="Long-form factuality in large language models",
            authors=[
                "Jerry Wei",
                "Chengrun Yang",
                "Xinying Song",
                "Yifeng Lu",
                "Nathan Hu",
                "Jie Huang",
                "Dustin Tran",
                "Daiyi Peng",
                "Ruibo Liu",
                "Da Huang",
                "Cosmo Du",
                "Quoc V. Le",
            ],
            year=2024,
            venue="NeurIPS 2024",
            locator="doi:10.52202/079017-2567",
            source_url=(
                "https://papers.nips.cc/paper/2024/hash/"
                "937ae0e83eb08d2cb8627fe1def8c751-Abstract-Conference.html"
            ),
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[
                LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT,
                LiteratureArea.SELECTIVE_FACTUALITY,
            ],
            finding=(
                "Long-form outputs can be decomposed into atomic facts and checked against "
                "retrieved evidence, with precision balanced against response coverage."
            ),
            limitation=(
                "SAFE still uses an LLM evaluator and open-web search; agreement with human "
                "raters is not proof that every scientific claim is correct."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-005",
            title=(
                "ScienceAgentBench: Toward Rigorous Assessment of Language Agents for "
                "Data-Driven Scientific Discovery"
            ),
            authors=[
                "Ziru Chen",
                "Shijie Chen",
                "Yuting Ning",
                "Qianheng Zhang",
                "Boshi Wang",
                "Botao Yu",
                "Yifei Li",
                "Zeyi Liao",
                "Chen Wei",
                "Zitong Lu",
                "Vishal Dey",
                "Mingyi Xue",
                "Frazier N. Baker",
                "Benjamin Burns",
                "Daniel Adu-Ampratwum",
                "Xuhui Huang",
                "Xia Ning",
                "Song Gao",
                "Yu Su",
                "Huan Sun",
            ],
            year=2025,
            venue="ICLR 2025",
            locator="OpenReview:6z4YKr0GK6",
            source_url="https://openreview.net/forum?id=6z4YKr0GK6",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.SCIENTIFIC_AGENT_EVALUATION],
            finding=(
                "Scientific agents should be evaluated on expert-validated executable "
                "workflow tasks using generated programs, execution results, and cost."
            ),
            limitation=(
                "The benchmark measures bounded task completion and explicitly does not "
                "establish reliable end-to-end autonomous discovery."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-006",
            title=(
                "CORE-Bench: Fostering the Credibility of Published Research Through a "
                "Computational Reproducibility Agent Benchmark"
            ),
            authors=[
                "Zachary S. Siegel",
                "Sayash Kapoor",
                "Nitya Nadgir",
                "Benedikt Stroebl",
                "Arvind Narayanan",
            ],
            year=2025,
            venue="Transactions on Machine Learning Research",
            locator="OpenReview:BsMMc4MEGS",
            source_url="https://openreview.net/forum?id=BsMMc4MEGS",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.SCIENTIFIC_AGENT_EVALUATION],
            finding=(
                "Computational reproducibility is a necessary, difficult precursor to "
                "credible automated research and benefits from execution-based tasks."
            ),
            limitation=(
                "Reproducing published work is narrower than originating and validating a "
                "new mechanism."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-007",
            title=(
                "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via "
                "Agentic Tree Search"
            ),
            authors=[
                "Yutaro Yamada",
                "Robert Tjarko Lange",
                "Cong Lu",
                "Shengran Hu",
                "Chris Lu",
                "Jakob Foerster",
                "Jeff Clune",
                "David Ha",
            ],
            year=2025,
            venue="arXiv preprint",
            locator="arXiv:2504.08066",
            source_url="https://arxiv.org/abs/2504.08066",
            source_kind=LiteratureSourceKind.PREPRINT,
            areas=[LiteratureArea.SCIENTIFIC_AGENT_EVALUATION],
            finding=(
                "Template-free experiment generation and iterative experiment management "
                "are feasible in a bounded ML setting."
            ),
            limitation=(
                "Workshop acceptance and a small number of submissions do not establish "
                "general scientific reliability, security, or uncontaminated evaluation."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-008",
            title=(
                "SecureVibeBench: Benchmarking Secure Vibe Coding of AI Agents via "
                "Reconstructing Vulnerability-Introducing Scenarios"
            ),
            authors=[
                "Junkai Chen",
                "Huihui Huang",
                "Yunbo Lyu",
                "Junwen An",
                "Jieke Shi",
                "Chengran Yang",
                "Ting Zhang",
                "Haoye Tian",
                "Yikun Li",
                "Zhenhao Li",
                "Xin Zhou",
                "Xing Hu",
                "David Lo",
            ],
            year=2026,
            venue="ACL 2026",
            locator="doi:10.18653/v1/2026.acl-long.1107",
            source_url="https://aclanthology.org/2026.acl-long.1107/",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.GENERATED_CODE_SECURITY],
            finding=(
                "Security evaluation must combine functionality with static and dynamic "
                "security oracles because either dimension alone misses the joint objective."
            ),
            limitation=(
                "The benchmark studies repository software tasks rather than scientific "
                "experiment plugins, so its measured rates do not transfer directly."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-009",
            title="Rethinking the Evaluation of Secure Code Generation",
            authors=["Shih-Chieh Dai", "Jun Xu", "Guanhong Tao"],
            year=2026,
            venue="ICSE 2026 Research Track",
            locator="ICSE 2026; arXiv:2503.15554",
            source_url=(
                "https://conf.researchr.org/details/icse-2026/"
                "icse-2026-research-track/175/"
                "Rethinking-the-Evaluation-of-Secure-Code-Generation"
            ),
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.GENERATED_CODE_SECURITY],
            finding=(
                "Security and functionality need joint evaluation with more than one signal; "
                "a single analyzer can miss vulnerabilities or reward non-functional code."
            ),
            limitation=(
                "The evaluated techniques and analyzers do not provide a formal sandbox or "
                "scientific-validity guarantee."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-010",
            title="Secure Software Development Framework (SSDF) Version 1.1",
            authors=[
                "Murugiah Souppaya",
                "Karen Scarfone",
                "Donna Dodson",
            ],
            year=2022,
            venue="NIST Special Publication 800-218",
            locator="doi:10.6028/NIST.SP.800-218",
            source_url="https://csrc.nist.gov/pubs/sp/800/218/final",
            source_kind=LiteratureSourceKind.OFFICIAL_STANDARD,
            areas=[LiteratureArea.GENERATED_CODE_SECURITY],
            finding=(
                "Secure development requires review or analysis of human-readable code, "
                "testing of executable code, and provenance for software components."
            ),
            limitation=(
                "SSDF is an outcome-oriented framework; this project must define its own "
                "concrete generated-code controls and scientific evidence gates."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-011",
            title="SCICOQA: Quality Assurance for Scientific Paper-Code Alignment",
            authors=["Tim Baumgärtner", "Iryna Gurevych"],
            year=2026,
            venue="ACL 2026",
            locator="doi:10.18653/v1/2026.acl-long.1795",
            source_url="https://aclanthology.org/2026.acl-long.1795/",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT],
            finding=(
                "Paper-code discrepancy detection remains difficult, especially for omitted "
                "details, long context, and papers outside model pretraining."
            ),
            limitation=(
                "The benchmark diagnoses paper-code mismatches after the fact and does not "
                "guarantee that a generated manuscript is causally bound to executed code."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-012",
            title=(
                "CiteGuard: Faithful Citation Attribution for LLMs via "
                "Retrieval-Augmented Validation"
            ),
            authors=[
                "Yee Man Choi",
                "Xuehang Guo",
                "Yi R. Fung",
                "Qingyun Wang",
            ],
            year=2026,
            venue="ACL 2026",
            locator="doi:10.18653/v1/2026.acl-long.282",
            source_url="https://aclanthology.org/2026.acl-long.282/",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT],
            finding=(
                "Citation validation benefits from retrieval-aware attribution alignment "
                "rather than relying on an ungrounded LLM judge alone."
            ),
            limitation=(
                "Citation attribution accuracy is not equivalent to evidential support for "
                "all method, result, limitation, and figure claims."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-013",
            title=(
                "RIGOURATE: Quantifying Scientific Exaggeration with "
                "Evidence-Aligned Claim Evaluation"
            ),
            authors=[
                "Joseph James",
                "Chenghao Xiao",
                "Yucheng Li",
                "Nafise Sadat Moosavi",
                "Chenghua Lin",
            ],
            year=2026,
            venue="Findings of ACL 2026",
            locator="doi:10.18653/v1/2026.findings-acl.1699",
            source_url="https://aclanthology.org/2026.findings-acl.1699/",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT],
            finding=(
                "Scientific overstatement can be operationalized by retrieving supporting "
                "paper evidence and judging whether claim strength exceeds that evidence."
            ),
            limitation=(
                "The framework evaluates paper-internal evidence and does not by itself "
                "validate external sources or experiment provenance."
            ),
        ),
        MechanismLiteratureSource(
            source_id="source-014",
            title="Enabling Large Language Models to Generate Text with Citations",
            authors=["Tianyu Gao", "Howard Yen", "Jiatong Yu", "Danqi Chen"],
            year=2023,
            venue="EMNLP 2023",
            locator="doi:10.18653/v1/2023.emnlp-main.398",
            source_url="https://aclanthology.org/2023.emnlp-main.398/",
            source_kind=LiteratureSourceKind.PEER_REVIEWED,
            areas=[LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT],
            finding=(
                "Attributed generation needs separate evaluation of correctness, citation "
                "recall, and citation precision rather than citation syntax alone."
            ),
            limitation=(
                "ALCE targets answer generation and does not cover execution hashes, "
                "scientific negative results, or paper-code consistency."
            ),
        ),
    ]


def build_task2612_research_brief(
    parent: ParentSprintEvidence,
) -> MechanismResearchBrief:
    """Freeze the evidence-first brief used by the next model interaction."""

    return MechanismResearchBrief.create(
        brief_id="task-261.2-mechanism-research-brief",
        parent_endpoint_hash=parent.endpoint_hash,
        topic=(
            "A parent-bound, risk-selective evidence mechanism with secure generated "
            "code and claim-level scientific provenance"
        ),
        research_questions=[
            (
                "Which mechanism can improve unsupported-claim control beyond a binary "
                "evidence gate while making abstention, coverage, and residual risk explicit?"
            ),
            (
                "Which controls are required to prove that a model proposal, reviewed "
                "generated code, sandbox execution, and scientific result are one causal chain?"
            ),
            (
                "Which result-blind panel and claim-evidence rules prevent revealed-task "
                "tuning and unsupported manuscript claims from masquerading as a new result?"
            ),
        ],
        search_perspectives=[
            "mainstream selective factuality and retrieval-grounded verification",
            "critical evidence on guessing incentives and self-correction limits",
            "scientific-agent execution benchmarks and hidden-task evaluation",
            "secure generated-code review, testing, sandboxing, and provenance",
            "scientific claim-citation, paper-code, and overstatement alignment",
        ],
        intended_reader=(
            "AutoResearch implementers and reviewers deciding whether task 261.2 may "
            "advance from a retained negative result to generated mechanism execution"
        ),
        inclusion_rule=(
            "Include only sources whose existence, authorship, and quoted abstract-level "
            "finding were verified on an official publisher, standards, or arXiv page."
        ),
        exclusion_rule=(
            "Exclude unverifiable citations, vendor marketing, prompt-only improvements "
            "without independent execution evidence, and claims stronger than the source."
        ),
        angle=(
            "The evidence does not justify another binary gate or an intrinsic self-critique "
            "loop. The testable child mechanism must expose an accuracy-coverage-abstention "
            "trade-off, use external executable evidence, bind exact generated bytes through "
            "security and functional checks, and face a disjoint sealed task panel."
        ),
        sources=task2612_verified_sources(),
    )


def freeze_task2612_foundation(
    *,
    parent_sprint_dir: Path | str,
    output_dir: Path | str,
    frozen_at: datetime,
    require_formal_clean_v2_identity: bool = True,
) -> MechanismFoundationManifest:
    """Write the verified parent identity and literature brief to an empty directory."""

    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise MechanismRoundIntegrityError(
            "mechanism foundation output directory must be empty"
        )
    root.mkdir(parents=True, exist_ok=True)
    parent = load_parent_sprint_evidence(
        parent_sprint_dir,
        require_formal_clean_v2_identity=require_formal_clean_v2_identity,
    )
    brief = build_task2612_research_brief(parent)
    parent_path = write_json_model(root / "parent-evidence.json", parent)
    brief_path = write_json_model(root / "research-brief.json", brief)
    manifest = MechanismFoundationManifest.create(
        foundation_id="task-261.2.1-foundation",
        frozen_at=frozen_at,
        parent_evidence_hash=parent.evidence_hash,
        parent_evidence_file_sha256=file_hash(parent_path),
        research_brief_hash=brief.brief_hash,
        research_brief_file_sha256=file_hash(brief_path),
    )
    write_json_model(root / "foundation-manifest.json", manifest)
    return manifest


def load_mechanism_foundation(
    output_dir: Path | str,
) -> tuple[MechanismFoundationManifest, ParentSprintEvidence, MechanismResearchBrief]:
    """Reload and verify every foundation contract and file digest."""

    root = Path(output_dir).resolve()
    manifest = _load_stamped_model(
        root / "foundation-manifest.json",
        MechanismFoundationManifest,
        "manifest_hash",
    )
    parent_path = root / "parent-evidence.json"
    brief_path = root / "research-brief.json"
    if file_hash(parent_path) != manifest.parent_evidence_file_sha256:
        raise MechanismRoundIntegrityError("parent evidence file hash mismatch")
    if file_hash(brief_path) != manifest.research_brief_file_sha256:
        raise MechanismRoundIntegrityError("research brief file hash mismatch")
    parent = _load_stamped_model(parent_path, ParentSprintEvidence, "evidence_hash")
    brief = _load_stamped_model(brief_path, MechanismResearchBrief, "brief_hash")
    if parent.evidence_hash != manifest.parent_evidence_hash:
        raise MechanismRoundIntegrityError("foundation parent contract hash mismatch")
    if brief.brief_hash != manifest.research_brief_hash:
        raise MechanismRoundIntegrityError("foundation brief contract hash mismatch")
    if brief.parent_endpoint_hash != parent.endpoint_hash:
        raise MechanismRoundIntegrityError("research brief is not bound to parent endpoint")
    return manifest, parent, brief


def _unsupported_claim_ids(
    requirements: list[ClaimEvidenceRequirement],
    links: list[ClaimEvidenceLink],
) -> list[str]:
    requirement_ids = [requirement.claim_id for requirement in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ValueError("claim requirements must have unique IDs")
    known_ids = set(requirement_ids)
    if any(link.claim_id not in known_ids for link in links):
        raise ValueError("claim-evidence link references an unknown claim")
    supported = {
        (link.claim_id, link.evidence_kind)
        for link in links
        if link.supports_claim
    }
    return sorted(
        requirement.claim_id
        for requirement in requirements
        if any(
            (requirement.claim_id, evidence_kind) not in supported
            for evidence_kind in requirement.required_evidence_kinds
        )
    )


def _verify_manifest_artifacts(root: Path, manifest: SprintManifest) -> None:
    if set(manifest.artifact_paths) != set(manifest.artifact_sha256):
        raise MechanismRoundIntegrityError(
            "parent manifest artifact path/hash keys differ"
        )
    for name in manifest.artifact_paths:
        _required_artifact_path(root, manifest, name)


def _required_artifact_path(
    root: Path,
    manifest: SprintManifest,
    name: str,
) -> Path:
    raw_path = manifest.artifact_paths.get(name)
    expected_hash = manifest.artifact_sha256.get(name)
    if raw_path is None or expected_hash is None:
        raise MechanismRoundIntegrityError(f"parent artifact is missing: {name}")
    path = Path(raw_path).resolve()
    if not path.is_relative_to(root):
        raise MechanismRoundIntegrityError(
            f"parent artifact resolves outside the sprint: {name}"
        )
    if not path.is_file():
        raise MechanismRoundIntegrityError(f"parent artifact file is missing: {name}")
    if file_hash(path) != expected_hash:
        raise MechanismRoundIntegrityError(f"parent artifact changed: {name}")
    return path


def _load_stamped_model(
    path: Path,
    model_type: type[ContractT],
    hash_field: str,
    *,
    hash_mode: Literal["excluded", "null"] = "excluded",
) -> ContractT:
    if not path.is_file():
        raise MechanismRoundIntegrityError(f"required contract is missing: {path.name}")
    model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
    if hash_mode == "null":
        expected = canonical_sha256(
            model.model_copy(update={hash_field: None}).model_dump(mode="json")
        )
    else:
        expected = canonical_sha256(
            model.model_dump(mode="json", exclude={hash_field})
        )
    if getattr(model, hash_field) != expected:
        raise MechanismRoundIntegrityError(
            f"{model_type.__name__} {hash_field} mismatch"
        )
    return model


def _required_hash(value: str | None, label: str) -> str:
    if value is None:
        raise MechanismRoundIntegrityError(f"{label} hash is missing")
    return value
