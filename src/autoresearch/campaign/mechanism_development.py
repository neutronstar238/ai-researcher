"""Model generation, code review, and development screening for task 261.2.2."""

from __future__ import annotations

import ast
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import (
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from autoresearch.campaign.mechanism_benchmark import (
    DevelopmentScreenDecision,
    MechanismDevelopmentScreen,
    MechanismDevelopmentTaskResult,
    build_task2612_panel,
    task2612_confirmatory_tasks,
    task2612_development_tasks,
)
from autoresearch.campaign.mechanism_round import (
    GeneratedCodeEvidence,
    MechanismChangeKind,
    MechanismCodeProposal,
    MechanismDiagnosis,
    MechanismFoundationManifest,
    MechanismPanelSpec,
    MechanismResearchBrief,
    MechanismRoundFreeze,
    ParentSprintEvidence,
    load_mechanism_foundation,
)
from autoresearch.campaign.mechanism_sandbox import (
    GeneratedCodeStaticReviewReport,
    GeneratedCodeTestReport,
    inspect_mechanism_source_text,
    review_mechanism_source,
    run_generated_code_harness,
    run_generated_code_test_suites,
)
from autoresearch.competition.manifest import write_json_model
from autoresearch.kernel import EpisodeOutcomeStatus
from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)
from autoresearch.llm.client import (
    LLMClientError,
    LLMJsonCompletionResult,
    run_llm_json_completion,
)
from autoresearch.schemas import file_hash

JsonCompletion = Callable[..., LLMJsonCompletionResult]
OutputT = TypeVar("OutputT", bound=KernelContract)
_MECHANISM_COMPILER_VERSION = "safe-expression-compiler-v1"
_MECHANISM_SIGNAL_NAMES = frozenset(
    {
        "support_score",
        "contradiction_score",
        "uncertainty",
        "independent_source_count",
        "source_quality",
    }
)
_EXPRESSION_CALL_NAMES = frozenset({"abs", "max", "min"})
_ALLOWED_EXPRESSION_NODE_TYPES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.IfExp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.UAdd,
    ast.USub,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


class MechanismDevelopmentIntegrityError(ValueError):
    """Raised when a persisted development run is incomplete or altered."""


class MechanismGenerationStage(str, Enum):
    """Model-authored stages kept separate in provenance."""

    DIAGNOSIS = "diagnosis"
    PROPOSAL = "proposal"


class MechanismDevelopmentStatus(str, Enum):
    """Terminal task 261.2.2 states."""

    BLOCKED = "blocked"
    NEGATIVE_DEVELOPMENT = "negative_development"
    READY_FOR_PREREGISTRATION = "ready_for_preregistration"


class MechanismModelInteraction(KernelContract):
    """Hash-bound provider-neutral record of one accepted model response."""

    schema_version: Literal["mechanism-model-interaction-v1"] = (
        "mechanism-model-interaction-v1"
    )
    interaction_id: StableId
    stage: MechanismGenerationStage
    input_hashes: dict[StableId, Sha256]
    messages_hash: Sha256
    attempt_trace_hash: Sha256
    provider: NonEmptyText
    base_url: NonEmptyText
    model_name: NonEmptyText
    response_text: str = Field(min_length=2)
    response_sha256: Sha256
    parsed_json_sha256: Sha256
    usage: dict[str, Any]
    attempt_count: int = Field(ge=1, le=2)
    used_fallback: Literal[False] = False
    created_at: datetime
    external_submission_authorized: Literal[False] = False
    interaction_hash: Sha256

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("model interaction time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_interaction(self) -> MechanismModelInteraction:
        if hashlib.sha256(
            self.response_text.encode("utf-8")
        ).hexdigest() != self.response_sha256:
            raise ValueError("model response SHA-256 mismatch")
        if self.interaction_hash != self.calculated_hash():
            raise ValueError("model interaction_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        interaction_id: str,
        stage: MechanismGenerationStage,
        input_hashes: Mapping[str, str],
        messages: Sequence[Mapping[str, str]],
        attempt_trace: Sequence[Mapping[str, Any]],
        response: LLMJsonCompletionResult,
        attempt_count: int,
        created_at: datetime,
    ) -> MechanismModelInteraction:
        """Create an interaction without persisting an API-key value."""

        payload: dict[str, Any] = {
            "schema_version": "mechanism-model-interaction-v1",
            "interaction_id": interaction_id,
            "stage": stage,
            "input_hashes": dict(sorted(input_hashes.items())),
            "messages_hash": canonical_sha256(list(messages)),
            "attempt_trace_hash": canonical_sha256(list(attempt_trace)),
            "provider": response.provider,
            "base_url": response.base_url,
            "model_name": response.model_name,
            "response_text": response.response_text,
            "response_sha256": hashlib.sha256(
                response.response_text.encode("utf-8")
            ).hexdigest(),
            "parsed_json_sha256": canonical_sha256(response.parsed_json),
            "usage": response.usage,
            "attempt_count": attempt_count,
            "used_fallback": False,
            "created_at": created_at,
            "external_submission_authorized": False,
        }
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"interaction_hash"},
        )
        normalized["interaction_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        """Recompute the model-interaction digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"interaction_hash"})
        )


class MechanismDevelopmentFailure(KernelContract):
    """One retained blocked-stage explanation without a fallback result."""

    schema_version: Literal["mechanism-development-failure-v1"] = (
        "mechanism-development-failure-v1"
    )
    stage: StableId
    failure_codes: list[StableId] = Field(min_length=1)
    summary: NonEmptyText
    created_at: datetime
    fallback_scientific_result_created: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    failure_hash: Sha256

    @field_validator("failure_codes")
    @classmethod
    def _normalize_codes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("development failure codes must be unique")
        return sorted(value)

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("development failure time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_hash(self) -> MechanismDevelopmentFailure:
        if self.failure_hash != self.calculated_hash():
            raise ValueError("development failure_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismDevelopmentFailure:
        """Attach a digest while forcing the safe fallback boundary."""

        payload = dict(values)
        payload["schema_version"] = "mechanism-development-failure-v1"
        payload["failure_codes"] = sorted(payload["failure_codes"])
        payload["fallback_scientific_result_created"] = False
        payload["external_submission_authorized"] = False
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"failure_hash"},
        )
        normalized["failure_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        """Recompute the failure digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"failure_hash"})
        )


class MechanismProgram(KernelContract):
    """Model-authored scientific logic compiled into a trusted fixed wrapper."""

    schema_version: Literal["mechanism-expression-program-v1"] = (
        "mechanism-expression-program-v1"
    )
    program_id: StableId
    implementation_mode: Literal["structured_expression_v1"] = (
        "structured_expression_v1"
    )
    risk_expression: str = Field(min_length=40, max_length=1_200)
    accept_expression: str = Field(min_length=40, max_length=1_200)
    accept_reason_code: StableId
    abstain_reason_code: StableId
    required_signal_names: list[StableId]
    compiler_version: Literal["safe-expression-compiler-v1"] = (
        "safe-expression-compiler-v1"
    )
    model_interaction_hash: Sha256
    external_submission_authorized: Literal[False] = False
    program_hash: Sha256

    @model_validator(mode="after")
    def _validate_program(self) -> MechanismProgram:
        if self.required_signal_names != sorted(_MECHANISM_SIGNAL_NAMES):
            raise ValueError("mechanism program signal contract mismatch")
        _validate_mechanism_expression(
            self.risk_expression,
            expression_kind="risk",
        )
        _validate_mechanism_expression(
            self.accept_expression,
            expression_kind="accept",
        )
        if self.program_hash != self.calculated_hash():
            raise ValueError("mechanism program_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        program_id: str,
        risk_expression: str,
        accept_expression: str,
        accept_reason_code: str,
        abstain_reason_code: str,
        model_interaction_hash: str,
    ) -> MechanismProgram:
        """Bind exact model-authored logic to its accepted interaction."""

        payload: dict[str, Any] = {
            "schema_version": "mechanism-expression-program-v1",
            "program_id": program_id,
            "implementation_mode": "structured_expression_v1",
            "risk_expression": risk_expression,
            "accept_expression": accept_expression,
            "accept_reason_code": accept_reason_code,
            "abstain_reason_code": abstain_reason_code,
            "required_signal_names": sorted(_MECHANISM_SIGNAL_NAMES),
            "compiler_version": _MECHANISM_COMPILER_VERSION,
            "model_interaction_hash": model_interaction_hash,
            "external_submission_authorized": False,
        }
        payload["program_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the scientific-program digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"program_hash"})
        )


class MechanismDevelopmentManifest(KernelContract):
    """Immutable terminal index for one task 261.2.2 attempt."""

    schema_version: Literal["mechanism-development-manifest-v1"] = (
        "mechanism-development-manifest-v1"
    )
    run_id: StableId
    status: MechanismDevelopmentStatus
    started_at: datetime
    completed_at: datetime
    foundation_manifest_hash: Sha256
    parent_evidence_hash: Sha256
    research_brief_hash: Sha256
    panel_hash: Sha256
    diagnosis_hash: Sha256 | None = None
    proposal_hash: Sha256 | None = None
    generated_source_sha256: Sha256 | None = None
    generated_code_evidence_hash: Sha256 | None = None
    round_freeze_hash: Sha256 | None = None
    development_screen_hash: Sha256 | None = None
    model_interaction_hashes: list[Sha256]
    artifact_file_sha256s: dict[str, Sha256]
    failure_codes: list[StableId]
    confirmatory_visibility: Literal["sealed-until-task-261.2.3"] = (
        "sealed-until-task-261.2.3"
    )
    confirmatory_payload_executed: Literal[False] = False
    confirmatory_result_artifact_count: Literal[0] = 0
    scientific_result_created: Literal[False] = False
    fallback_scientific_result_created: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    manifest_hash: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("development manifest time must be timezone-aware")
        return value

    @field_validator("model_interaction_hashes", "failure_codes")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("development manifest identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_manifest(self) -> MechanismDevelopmentManifest:
        if self.completed_at < self.started_at:
            raise ValueError("development manifest completion precedes start")
        if self.status is MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION:
            required = (
                self.diagnosis_hash,
                self.proposal_hash,
                self.generated_source_sha256,
                self.generated_code_evidence_hash,
                self.round_freeze_hash,
                self.development_screen_hash,
            )
            if any(value is None for value in required) or self.failure_codes:
                raise ValueError("ready development manifest lacks causal artifacts")
        if (
            self.status is MechanismDevelopmentStatus.NEGATIVE_DEVELOPMENT
            and (self.development_screen_hash is None or not self.failure_codes)
        ):
            raise ValueError("negative development manifest lacks screen evidence")
        if self.status is MechanismDevelopmentStatus.BLOCKED and not self.failure_codes:
            raise ValueError("blocked development manifest needs a failure code")
        if self.manifest_hash != self.calculated_hash():
            raise ValueError("development manifest_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> MechanismDevelopmentManifest:
        """Normalize a terminal run index and attach its digest."""

        payload = dict(values)
        payload["schema_version"] = "mechanism-development-manifest-v1"
        payload["model_interaction_hashes"] = sorted(
            payload.get("model_interaction_hashes", [])
        )
        payload["artifact_file_sha256s"] = dict(
            sorted(payload["artifact_file_sha256s"].items())
        )
        payload["failure_codes"] = sorted(payload.get("failure_codes", []))
        payload["confirmatory_visibility"] = "sealed-until-task-261.2.3"
        payload["confirmatory_payload_executed"] = False
        payload["confirmatory_result_artifact_count"] = 0
        payload["scientific_result_created"] = False
        payload["fallback_scientific_result_created"] = False
        payload["external_submission_authorized"] = False
        normalized = cls.model_construct(**payload).model_dump(
            mode="json",
            exclude={"manifest_hash"},
        )
        normalized["manifest_hash"] = canonical_sha256(normalized)
        return cls.model_validate(normalized)

    def calculated_hash(self) -> str:
        """Recompute the terminal manifest digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )


class _DiagnosisOutput(KernelContract):
    causal_hypotheses: list[str] = Field(min_length=2, max_length=5)
    required_mechanism_properties: list[str] = Field(min_length=3, max_length=8)
    literature_source_ids: list[str] = Field(min_length=3, max_length=8)


class _ProposalOutput(KernelContract):
    mechanism_kind: MechanismChangeKind
    mechanism_title: str = Field(min_length=12, max_length=160)
    mechanism_delta: str = Field(min_length=80, max_length=1200)
    falsification_conditions: list[str] = Field(min_length=2, max_length=6)
    literature_source_ids: list[str] = Field(min_length=3, max_length=8)
    implementation_mode: Literal["structured_expression_v1"]
    risk_expression: str = Field(min_length=40, max_length=1_200)
    accept_expression: str = Field(min_length=40, max_length=1_200)
    accept_reason_code: StableId
    abstain_reason_code: StableId

    @model_validator(mode="after")
    def _validate_implementation(self) -> _ProposalOutput:
        _validate_mechanism_expression(
            self.risk_expression,
            expression_kind="risk",
        )
        _validate_mechanism_expression(
            self.accept_expression,
            expression_kind="accept",
        )
        if self.accept_reason_code == self.abstain_reason_code:
            raise ValueError("accept and abstain reason codes must differ")
        return self


def run_task2612_mechanism_development(
    *,
    output_dir: Path | str,
    foundation_dir: Path | str,
    llm_config_path: Path | str,
    completion: JsonCompletion = run_llm_json_completion,
    env_path: Path | str = Path("__no_mechanism_env_file__"),
    run_id: str = "task2612-mechanism-development-v1",
    clock: Callable[[], datetime] | None = None,
) -> MechanismDevelopmentManifest:
    """Generate, review, and development-screen exactly one model mechanism."""

    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now()
    foundation, parent, brief = load_mechanism_foundation(foundation_dir)
    root = Path(output_dir).resolve()
    manifest_path = root / "development-manifest.json"
    if manifest_path.is_file():
        return load_mechanism_development(root)
    if root.exists() and any(root.iterdir()):
        raise MechanismDevelopmentIntegrityError(
            "mechanism development output must be empty or terminal"
        )
    root.mkdir(parents=True, exist_ok=True)
    panel = build_task2612_panel(parent)
    _write_panel_evidence(root, panel)
    interactions: list[MechanismModelInteraction] = []
    diagnosis: MechanismDiagnosis | None = None
    proposal: MechanismCodeProposal | None = None
    code_evidence: GeneratedCodeEvidence | None = None
    round_freeze: MechanismRoundFreeze | None = None
    screen: MechanismDevelopmentScreen | None = None
    stage = "diagnosis_generation"

    try:
        diagnosis_messages = _diagnosis_messages(parent, brief, panel)
        diagnosis_schema = _transport_response_schema(
            _DiagnosisOutput.model_json_schema()
        )
        write_json_model(
            root / "model" / "diagnosis-response-schema.json",
            diagnosis_schema,
        )
        diagnosis_response, diagnosis_output, diagnosis_attempt, diagnosis_trace = (
            _generate_validated(
                completion=completion,
                messages=diagnosis_messages,
                output_type=_DiagnosisOutput,
                response_schema=diagnosis_schema,
                attempt_artifact_dir=root / "model" / "attempts" / "diagnosis",
                llm_config_path=llm_config_path,
                env_path=env_path,
                response_schema_name="task2612_mechanism_diagnosis",
                max_tokens=1_500,
            )
        )
        diagnosis_interaction = MechanismModelInteraction.create(
            interaction_id=f"{run_id}-diagnosis",
            stage=MechanismGenerationStage.DIAGNOSIS,
            input_hashes={
                "parent_evidence": parent.evidence_hash,
                "research_brief": brief.brief_hash,
                "panel": panel.panel_hash,
                "response_schema": canonical_sha256(diagnosis_schema),
            },
            messages=diagnosis_messages,
            attempt_trace=diagnosis_trace,
            response=diagnosis_response,
            attempt_count=diagnosis_attempt,
            created_at=now(),
        )
        interactions.append(diagnosis_interaction)
        diagnosis = MechanismDiagnosis.create(
            parent=parent,
            brief=brief,
            diagnosis_id=f"{run_id}-diagnosis",
            causal_hypotheses=diagnosis_output.causal_hypotheses,
            required_mechanism_properties=(
                diagnosis_output.required_mechanism_properties
            ),
            literature_source_ids=diagnosis_output.literature_source_ids,
            model_interaction_hash=diagnosis_interaction.interaction_hash,
        )
        write_json_model(
            root / "model" / "diagnosis-interaction.json",
            diagnosis_interaction,
        )
        write_json_model(root / "model" / "diagnosis.json", diagnosis)

        stage = "proposal_generation"
        proposal_messages = _proposal_messages(parent, brief, diagnosis, panel)
        proposal_schema = _transport_response_schema(
            _ProposalOutput.model_json_schema()
        )
        write_json_model(
            root / "model" / "proposal-response-schema.json",
            proposal_schema,
        )
        proposal_response, proposal_output, proposal_attempt, proposal_trace = (
            _generate_validated(
                completion=completion,
                messages=proposal_messages,
                output_type=_ProposalOutput,
                response_schema=proposal_schema,
                attempt_artifact_dir=root / "model" / "attempts" / "proposal",
                llm_config_path=llm_config_path,
                env_path=env_path,
                response_schema_name="task2612_mechanism_proposal",
                max_tokens=4_000,
            )
        )
        proposal_interaction = MechanismModelInteraction.create(
            interaction_id=f"{run_id}-proposal",
            stage=MechanismGenerationStage.PROPOSAL,
            input_hashes={
                "diagnosis": diagnosis.diagnosis_hash,
                "research_brief": brief.brief_hash,
                "panel": panel.panel_hash,
                "response_schema": canonical_sha256(proposal_schema),
            },
            messages=proposal_messages,
            attempt_trace=proposal_trace,
            response=proposal_response,
            attempt_count=proposal_attempt,
            created_at=now(),
        )
        interactions.append(proposal_interaction)
        program = MechanismProgram.create(
            program_id=f"{run_id}-program",
            risk_expression=proposal_output.risk_expression,
            accept_expression=proposal_output.accept_expression,
            accept_reason_code=proposal_output.accept_reason_code,
            abstain_reason_code=proposal_output.abstain_reason_code,
            model_interaction_hash=proposal_interaction.interaction_hash,
        )
        source_text, compiler_contract_hash = _compile_mechanism_program(program)
        proposal = MechanismCodeProposal.create(
            diagnosis=diagnosis,
            brief=brief,
            proposal_id=f"{run_id}-proposal",
            mechanism_kind=proposal_output.mechanism_kind,
            mechanism_title=proposal_output.mechanism_title,
            mechanism_delta=proposal_output.mechanism_delta,
            falsification_conditions=proposal_output.falsification_conditions,
            literature_source_ids=proposal_output.literature_source_ids,
            source_text=source_text,
            model_interaction_hash=proposal_interaction.interaction_hash,
        )
        write_json_model(
            root / "model" / "proposal-interaction.json",
            proposal_interaction,
        )
        write_json_model(root / "model" / "mechanism-program.json", program)
        write_json_model(root / "model" / "proposal.json", proposal)
        write_json_model(
            root / "model" / "source-serialization.json",
            {
                "schema_version": "model-expression-compiler-record-v1",
                "method": "render-validated-model-expressions-in-fixed-wrapper",
                "mechanism_program_hash": program.program_hash,
                "compiler_version": _MECHANISM_COMPILER_VERSION,
                "compiler_contract_hash": compiler_contract_hash,
                "source_line_count": len(source_text.splitlines()),
                "terminal_lf_present": source_text.endswith("\n"),
                "source_sha256": proposal.source_sha256,
                "proposal_interaction_hash": (
                    proposal_interaction.interaction_hash
                ),
                "code_side_repair_applied": False,
                "trusted_non_scientific_wrapper_used": True,
                "fallback_source_used": False,
            },
        )
        source_path = root / "generated" / "run.py"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(proposal.source_text.encode("utf-8"))
        if file_hash(source_path) != proposal.source_sha256:
            raise MechanismDevelopmentIntegrityError(
                "persisted generated bytes differ from proposal"
            )

        stage = "generated_code_review"
        static_report = review_mechanism_source(
            source_path.parent,
            expected_source_sha256=proposal.source_sha256,
        )
        write_json_model(root / "review" / "static-review.json", static_report)
        unit_report, property_report = run_generated_code_test_suites(
            output_dir=root / "review" / "tests",
            source_text=proposal.source_text,
            static_review_approved=static_report.approved,
        )
        preflight_approved = (
            static_report.approved
            and unit_report.passed
            and property_report.passed
        )
        preflight_codes = _preflight_failure_codes(
            static_report,
            unit_report,
            property_report,
        )
        smoke_spec, smoke_episode, smoke_observation, _ = (
            run_generated_code_harness(
                run_id=run_id,
                episode_id=f"{run_id}-sandbox-smoke",
                output_dir=root / "review" / "sandbox-smoke",
                source_text=proposal.source_text,
                claims=_sandbox_smoke_claims(),
                preflight_approved=preflight_approved,
                preflight_failure_codes=preflight_codes,
                clock=now(),
            )
        )
        sandbox_passed = (
            smoke_episode.final_outcome.status
            is EpisodeOutcomeStatus.SUCCEEDED
        )
        code_evidence = GeneratedCodeEvidence.create(
            proposal_hash=proposal.proposal_hash,
            source_sha256=proposal.source_sha256,
            static_review_report_hash=static_report.report_hash,
            static_review_approved=static_report.approved,
            blocking_finding_codes=sorted(
                {finding.code for finding in static_report.findings}
            ),
            unit_test_report_hash=unit_report.report_hash,
            unit_tests_passed=unit_report.passed,
            property_test_report_hash=property_report.report_hash,
            property_tests_passed=property_report.passed,
            harness_spec_hash=smoke_spec.spec_hash,
            sandbox_episode_hash=smoke_episode.episode_hash,
            sandbox_smoke_passed=sandbox_passed,
            network_used=(
                smoke_observation.network_used
                if smoke_observation is not None
                else False
            ),
        )
        write_json_model(
            root / "review" / "generated-code-evidence.json",
            code_evidence,
        )
        if not code_evidence.approved_for_development:
            codes = preflight_codes or [
                failure.code for failure in smoke_episode.failures
            ]
            return _finalize_blocked(
                root=root,
                run_id=run_id,
                started_at=started_at,
                completed_at=now(),
                foundation=foundation,
                parent=parent,
                brief=brief,
                panel=panel,
                stage=stage,
                failure_codes=codes or ["generated_code_not_approved"],
                summary=(
                    "The exact model-generated source did not pass every static, "
                    "unit, property, and sandbox gate. No development or "
                    "confirmatory payload was executed."
                ),
                interactions=interactions,
                diagnosis=diagnosis,
                proposal=proposal,
                code_evidence=code_evidence,
            )

        round_freeze = MechanismRoundFreeze.create(
            round_id=f"{run_id}-round",
            parent=parent,
            brief=brief,
            diagnosis=diagnosis,
            proposal=proposal,
            code_evidence=code_evidence,
            panel=panel,
        )
        write_json_model(root / "freeze" / "round-freeze.json", round_freeze)

        stage = "development_screen"
        development_results = _run_development_panel(
            root=root,
            run_id=run_id,
            proposal=proposal,
            panel=panel,
            clock=now,
        )
        screen = MechanismDevelopmentScreen.create(
            round_freeze_hash=round_freeze.freeze_hash,
            panel=panel,
            generated_source_sha256=proposal.source_sha256,
            results=development_results,
        )
        write_json_model(root / "development" / "screen.json", screen)
        status = (
            MechanismDevelopmentStatus.READY_FOR_PREREGISTRATION
            if screen.decision
            is DevelopmentScreenDecision.ADVANCE_TO_PREREGISTRATION
            else MechanismDevelopmentStatus.NEGATIVE_DEVELOPMENT
        )
        return _finalize_manifest(
            root=root,
            run_id=run_id,
            status=status,
            started_at=started_at,
            completed_at=now(),
            foundation=foundation,
            parent=parent,
            brief=brief,
            panel=panel,
            interactions=interactions,
            diagnosis=diagnosis,
            proposal=proposal,
            code_evidence=code_evidence,
            round_freeze=round_freeze,
            screen=screen,
            failure_codes=screen.failure_codes,
        )
    except (
        LLMClientError,
        MechanismDevelopmentIntegrityError,
        ValidationError,
        ValueError,
    ) as exc:
        return _finalize_blocked(
            root=root,
            run_id=run_id,
            started_at=started_at,
            completed_at=now(),
            foundation=foundation,
            parent=parent,
            brief=brief,
            panel=panel,
            stage=stage,
            failure_codes=[_failure_code(stage, exc)],
            summary=_safe_failure_summary(exc),
            interactions=interactions,
            diagnosis=diagnosis,
            proposal=proposal,
            code_evidence=code_evidence,
            round_freeze=round_freeze,
            screen=screen,
        )


def load_mechanism_development(
    output_dir: Path | str,
) -> MechanismDevelopmentManifest:
    """Verify a terminal task 261.2.2 manifest and every indexed file."""

    root = Path(output_dir).resolve()
    manifest_path = root / "development-manifest.json"
    manifest = MechanismDevelopmentManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    actual = _artifact_file_hashes(root)
    if actual != manifest.artifact_file_sha256s:
        missing = sorted(set(manifest.artifact_file_sha256s) - set(actual))
        extra = sorted(set(actual) - set(manifest.artifact_file_sha256s))
        drift = sorted(
            path
            for path in set(actual) & set(manifest.artifact_file_sha256s)
            if actual[path] != manifest.artifact_file_sha256s[path]
        )
        raise MechanismDevelopmentIntegrityError(
            "development artifact index mismatch: "
            f"missing={missing}, extra={extra}, drift={drift}"
        )
    return manifest


def _generate_validated(
    *,
    completion: JsonCompletion,
    messages: list[dict[str, str]],
    output_type: type[OutputT],
    response_schema: dict[str, Any],
    attempt_artifact_dir: Path,
    llm_config_path: Path | str,
    env_path: Path | str,
    response_schema_name: str,
    max_tokens: int,
) -> tuple[LLMJsonCompletionResult, OutputT, int, list[dict[str, Any]]]:
    working_messages = list(messages)
    trace: list[dict[str, Any]] = []
    response: LLMJsonCompletionResult | None = None
    for attempt in (1, 2):
        try:
            response = completion(
                messages=working_messages,
                config_path=llm_config_path,
                env_path=env_path,
                timeout_seconds=300,
                max_tokens=max_tokens,
                temperature=0.0 if attempt == 1 else 0.05,
                reasoning_effort="none",
                response_schema=response_schema,
                response_schema_name=response_schema_name,
            )
            parsed = output_type.model_validate(response.parsed_json)
            attempt_artifact_sha256 = _write_model_attempt(
                output_dir=attempt_artifact_dir,
                attempt=attempt,
                response=response,
                valid=True,
                validation_summary=None,
            )
            trace.append(
                {
                    "attempt": attempt,
                    "response_sha256": hashlib.sha256(
                        response.response_text.encode("utf-8")
                    ).hexdigest(),
                    "attempt_artifact_sha256": attempt_artifact_sha256,
                    "valid": True,
                }
            )
            return response, parsed, attempt, trace
        except (LLMClientError, ValidationError, ValueError) as exc:
            validation_summary = _safe_failure_summary(exc)
            attempt_artifact_sha256 = _write_model_attempt(
                output_dir=attempt_artifact_dir,
                attempt=attempt,
                response=response,
                valid=False,
                validation_summary=validation_summary,
            )
            trace.append(
                {
                    "attempt": attempt,
                    "error_type": type(exc).__name__,
                    "error_sha256": hashlib.sha256(
                        _safe_failure_summary(exc).encode("utf-8")
                    ).hexdigest(),
                    "response_sha256": (
                        hashlib.sha256(
                            response.response_text.encode("utf-8")
                        ).hexdigest()
                        if response is not None
                        else None
                    ),
                    "attempt_artifact_sha256": attempt_artifact_sha256,
                    "valid": False,
                }
            )
            if attempt == 2:
                raise
            if response is not None:
                working_messages.append(
                    {
                        "role": "assistant",
                        "content": response.response_text,
                    }
                )
            working_messages.append(
                {
                    "role": "user",
                    "content": (
                        "The prior object failed deterministic schema or causal "
                        "validation. Return the complete corrected JSON object only. "
                        "Do not add markdown fences or prose. Preserve the requested "
                        "scientific boundary and do not invent source IDs. Validator "
                        f"category: {type(exc).__name__}. Safe validator summary: "
                        f"{validation_summary[:600]}"
                    ),
                }
            )
            response = None
    raise AssertionError("two-attempt generation loop did not terminate")


def _write_model_attempt(
    *,
    output_dir: Path,
    attempt: int,
    response: LLMJsonCompletionResult | None,
    valid: bool,
    validation_summary: str | None,
) -> str:
    payload: dict[str, Any] = {
        "schema_version": "mechanism-model-attempt-v1",
        "attempt": attempt,
        "valid": valid,
        "validation_summary": validation_summary,
        "fallback_used": False,
        "external_submission_authorized": False,
    }
    if response is not None:
        payload.update(
            {
                "provider": response.provider,
                "base_url": response.base_url,
                "model_name": response.model_name,
                "response_text": response.response_text,
                "response_sha256": hashlib.sha256(
                    response.response_text.encode("utf-8")
                ).hexdigest(),
                "parsed_json": response.parsed_json,
                "parsed_json_sha256": canonical_sha256(response.parsed_json),
                "usage": response.usage,
            }
        )
    path = write_json_model(output_dir / f"attempt-{attempt}.json", payload)
    return file_hash(path)


def _validate_mechanism_expression(
    value: str,
    *,
    expression_kind: Literal["risk", "accept"],
) -> ast.Expression:
    if value != value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{expression_kind}_expression must be one stripped line")
    if "#" in value or "\\" in value:
        raise ValueError(
            f"{expression_kind}_expression cannot contain comments or escapes"
        )
    try:
        tree = ast.parse(value, mode="eval")
    except SyntaxError as exc:
        raise ValueError(
            f"{expression_kind}_expression is not a valid Python expression"
        ) from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 160:
        raise ValueError(f"{expression_kind}_expression is too complex")
    allowed_names = set(_MECHANISM_SIGNAL_NAMES) | set(
        _EXPRESSION_CALL_NAMES
    )
    if expression_kind == "accept":
        allowed_names.add("risk_score")
    for node in nodes:
        if not isinstance(node, _ALLOWED_EXPRESSION_NODE_TYPES):
            raise ValueError(
                f"{expression_kind}_expression uses forbidden AST node "
                f"{type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(
                f"{expression_kind}_expression uses unknown name {node.id}"
            )
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name)
            or node.func.id not in _EXPRESSION_CALL_NAMES
            or node.keywords
        ):
            raise ValueError(
                f"{expression_kind}_expression uses a forbidden call"
            )
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, bool | int | float):
                raise ValueError(
                    f"{expression_kind}_expression constants must be numeric "
                    "or boolean"
                )
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ValueError(
                    f"{expression_kind}_expression constants must be finite"
                )
    referenced_names = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name)
        and node.id not in _EXPRESSION_CALL_NAMES
    }
    if expression_kind == "risk":
        missing = sorted(_MECHANISM_SIGNAL_NAMES - referenced_names)
        if missing:
            raise ValueError(
                "risk_expression must reference every evidence signal: "
                + ",".join(missing)
            )
        if not any(isinstance(node, ast.BinOp) for node in nodes):
            raise ValueError("risk_expression must combine multiple signals")
    else:
        required_accept_names = {
            "risk_score",
            "independent_source_count",
        }
        missing = sorted(required_accept_names - referenced_names)
        if missing:
            raise ValueError(
                "accept_expression lacks required decision names: "
                + ",".join(missing)
            )
        if not any(isinstance(node, ast.Compare) for node in nodes):
            raise ValueError("accept_expression must contain a comparison")
    return tree


def _compile_mechanism_program(
    program: MechanismProgram,
) -> tuple[str, str]:
    compiler_contract = {
        "compiler_version": _MECHANISM_COMPILER_VERSION,
        "allowed_ast_nodes": sorted(
            node_type.__name__
            for node_type in _ALLOWED_EXPRESSION_NODE_TYPES
        ),
        "allowed_calls": sorted(_EXPRESSION_CALL_NAMES),
        "risk_required_names": sorted(_MECHANISM_SIGNAL_NAMES),
        "accept_required_names": [
            "independent_source_count",
            "risk_score",
        ],
        "wrapper_contract": [
            "read input.json beside __file__ as UTF-8",
            "evaluate each claim in input order",
            "clamp model-authored risk to [0,1]",
            "write metrics.json beside __file__ as UTF-8",
            "no network, environment, dynamic execution, or external paths",
        ],
    }
    compiler_contract_hash = canonical_sha256(compiler_contract)
    accept_reason = json.dumps(program.accept_reason_code)
    abstain_reason = json.dumps(program.abstain_reason_code)
    source = (
        "from __future__ import annotations\n"
        "\n"
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        f'MECHANISM_PROGRAM_SHA256 = "{program.program_hash}"\n'
        f'MECHANISM_COMPILER_VERSION = "{_MECHANISM_COMPILER_VERSION}"\n'
        f'COMPILER_CONTRACT_SHA256 = "{compiler_contract_hash}"\n'
        "\n"
        "\n"
        "def evaluate_claims(claims):\n"
        "    decisions = []\n"
        "    for claim in claims:\n"
        '        claim_id = str(claim["claim_id"])\n'
        '        support_score = float(claim["support_score"])\n'
        '        contradiction_score = float(claim["contradiction_score"])\n'
        '        uncertainty = float(claim["uncertainty"])\n'
        "        independent_source_count = "
        'int(claim["independent_source_count"])\n'
        '        source_quality = float(claim["source_quality"])\n'
        f"        risk_score = float({program.risk_expression})\n"
        "        risk_score = max(0.0, min(1.0, risk_score))\n"
        f"        accepted = bool({program.accept_expression})\n"
        "        decisions.append(\n"
        "            {\n"
        '                "claim_id": claim_id,\n'
        '                "decision": "accept" if accepted else "abstain",\n'
        '                "risk_score": risk_score,\n'
        f'                "reason_code": {accept_reason} if accepted else '
        f"{abstain_reason},\n"
        "            }\n"
        "        )\n"
        "    return decisions\n"
        "\n"
        "\n"
        "def main():\n"
        "    root = Path(__file__).resolve().parent\n"
        "    payload = json.loads(\n"
        '        (root / "input.json").read_text(encoding="utf-8")\n'
        "    )\n"
        '    decisions = evaluate_claims(payload["claims"])\n'
        '    (root / "metrics.json").write_text(\n'
        "        json.dumps(\n"
        '            {"status": "success", "decisions": decisions},\n'
        "            sort_keys=True,\n"
        "        ),\n"
        '        encoding="utf-8",\n'
        "    )\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
    findings = inspect_mechanism_source_text(source)
    if findings:
        codes = ",".join(sorted({finding.code for finding in findings}))
        raise ValueError(
            "trusted expression compiler emitted invalid source: " + codes
        )
    return source, compiler_contract_hash


def _transport_response_schema(value: Any) -> Any:
    """Drop grammar-expanding string caps while retaining local validation."""

    if isinstance(value, dict):
        return {
            key: _transport_response_schema(item)
            for key, item in value.items()
            if key != "maxLength"
        }
    if isinstance(value, list):
        return [_transport_response_schema(item) for item in value]
    return value


def _diagnosis_messages(
    parent: ParentSprintEvidence,
    brief: MechanismResearchBrief,
    panel: MechanismPanelSpec,
) -> list[dict[str, str]]:
    payload = {
        "parent": {
            "evidence_hash": parent.evidence_hash,
            "endpoint_hash": parent.endpoint_hash,
            "failure_codes": parent.parent_failure_codes,
            "selected_program_id": parent.selected_program_id,
            "revealed_task_count": len(parent.revealed_task_ids),
            "scientific_endpoint": parent.scientific_endpoint,
        },
        "research_brief": _brief_prompt_payload(brief),
        "panel": {
            "panel_hash": panel.panel_hash,
            "development_task_count": len(panel.development_tasks),
            "confirmatory_task_count": len(panel.confirmatory_tasks),
            "minimum_coverage": panel.minimum_coverage,
            "maximum_unsupported_claim_rate": (
                panel.maximum_unsupported_claim_rate
            ),
            "task_payloads_visible": False,
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are the mechanism-diagnosis model in a bounded evidence-first "
                "research run. Diagnose the frozen negative endpoint; do not claim a "
                "new result. Use only supplied source IDs. A prompt rewrite, paper "
                "rewrite, threshold-only change, or revealed-panel rerun is forbidden. "
                "Return exactly one JSON object matching the schema."
            ),
        },
        {
            "role": "user",
            "content": (
                "Produce at least two causal hypotheses, at least three executable "
                "mechanism properties, and at least three verified literature source "
                "IDs. Properties must require explicit accept/abstain output, residual "
                "risk, minimum coverage, external evidence signals, deterministic "
                "behavior, and conservative degradation behavior. Parent-bound input:\n"
                + json.dumps(payload, sort_keys=True, separators=(",", ":"))
            ),
        },
    ]


def _proposal_messages(
    parent: ParentSprintEvidence,
    brief: MechanismResearchBrief,
    diagnosis: MechanismDiagnosis,
    panel: MechanismPanelSpec,
) -> list[dict[str, str]]:
    payload = {
        "parent_evidence_hash": parent.evidence_hash,
        "research_brief_hash": brief.brief_hash,
        "diagnosis": diagnosis.model_dump(mode="json"),
        "panel_contract": {
            "panel_hash": panel.panel_hash,
            "minimum_coverage": panel.minimum_coverage,
            "maximum_unsupported_claim_rate": (
                panel.maximum_unsupported_claim_rate
            ),
            "development_payload_visible": False,
            "confirmatory_payload_visible": False,
        },
        "verified_sources": [
            {
                "source_id": source.source_id,
                "areas": [area.value for area in source.areas],
                "finding": source.finding,
                "limitation": source.limitation,
            }
            for source in brief.sources
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "You generate one executable scientific mechanism for a bounded "
                "development screen. Return exactly one JSON object matching the "
                "schema. The structured_expression_v1 fields are the model-authored "
                "scientific logic; a versioned compiler supplies only fixed parsing, "
                "iteration, output, and sandbox boilerplate. No code-authored "
                "scientific fallback will replace the expressions. Do not claim "
                "success and do not use unseen task payloads."
            ),
        },
        {
            "role": "user",
            "content": (
                "Propose a mechanism-level delta supported by at least three supplied "
                "source IDs and at least two falsification conditions. It must combine "
                "multiple evidence signals rather than merely changing one threshold.\n\n"
                "structured_expression_v1 requirements:\n"
                "- Set implementation_mode exactly to structured_expression_v1.\n"
                "- risk_expression is one Python expression, not an assignment or code "
                "block. It must reference all five exact numeric names: support_score, "
                "contradiction_score, uncertainty, independent_source_count, and "
                "source_quality. It may use numeric/boolean literals, + - * / %, "
                "comparisons, and/or/not, a conditional expression, and min/max/abs "
                "calls only. The trusted wrapper converts it to float and clamps it "
                "to [0,1].\n"
                "- accept_expression is one boolean Python expression evaluated after "
                "risk_score is clamped. It must reference risk_score and "
                "independent_source_count; it may also reference the other exact "
                "signal names and use the same restricted operators/functions.\n"
                "- Both expressions must be single-line, stripped, deterministic, and "
                "contain no strings, attributes, indexing, imports, assignments, "
                "comprehensions, lambdas, or unlisted names/calls.\n"
                "- The risk expression must be defined for every closed-domain input "
                "where scores are in [0,1] and independent_source_count is a "
                "nonnegative integer. Every possible divisor must be bounded away "
                "from zero with max(..., 1e-6) or an equivalent guarded conditional.\n"
                "- accept_reason_code and abstain_reason_code must differ and be "
                "lowercase path-safe identifiers containing only letters, digits, "
                "dot, underscore, or hyphen.\n"
                "- Be deterministic and permutation-equivariant. A claim degraded to "
                "support_score=0.35, contradiction_score=0.75, uncertainty=0.82, "
                "independent_source_count=0, source_quality=0.42 must abstain.\n"
                "- Do not emit source code, markdown, extra fields, success claims, "
                "network requests, or a fallback implementation.\n\n"
                "Frozen causal input:\n"
                + json.dumps(payload, sort_keys=True, separators=(",", ":"))
            ),
        },
    ]


def _brief_prompt_payload(brief: MechanismResearchBrief) -> dict[str, Any]:
    return {
        "brief_hash": brief.brief_hash,
        "angle": brief.angle,
        "research_questions": brief.research_questions,
        "sources": [
            {
                "source_id": source.source_id,
                "areas": [area.value for area in source.areas],
                "finding": source.finding,
                "limitation": source.limitation,
            }
            for source in brief.sources
        ],
    }


def _write_panel_evidence(root: Path, panel: MechanismPanelSpec) -> None:
    development = task2612_development_tasks()
    confirmatory = task2612_confirmatory_tasks()
    write_json_model(root / "panel" / "panel-spec.json", panel)
    write_json_model(
        root / "panel" / "development-tasks.json",
        {
            "schema_version": "mechanism-development-task-bundle-v1",
            "visibility": "reveal-only-after-code-approval",
            "tasks": [task.model_dump(mode="json") for task in development],
            "bundle_hash": canonical_sha256(
                [task.model_dump(mode="json") for task in development]
            ),
        },
    )
    confirmatory_payload = {
        "schema_version": "mechanism-confirmatory-task-bundle-v1",
        "visibility": "sealed-until-task-261.2.3",
        "executed": False,
        "result_artifact_count": 0,
        "tasks": [task.model_dump(mode="json") for task in confirmatory],
    }
    confirmatory_payload["bundle_hash"] = canonical_sha256(confirmatory_payload)
    write_json_model(
        root / "panel" / "sealed-confirmatory-tasks.json",
        confirmatory_payload,
    )


def _run_development_panel(
    *,
    root: Path,
    run_id: str,
    proposal: MechanismCodeProposal,
    panel: MechanismPanelSpec,
    clock: Callable[[], datetime],
) -> list[MechanismDevelopmentTaskResult]:
    tasks = task2612_development_tasks()
    task_by_id = {task.task_id: task for task in tasks}
    results: list[MechanismDevelopmentTaskResult] = []
    for reference in panel.development_tasks:
        task = task_by_id[reference.task_id]
        spec, episode, observation, decisions = run_generated_code_harness(
            run_id=f"{run_id}-{task.task_id}",
            episode_id=f"{run_id}-{task.task_id}-episode",
            output_dir=root / "development" / task.task_id,
            source_text=proposal.source_text,
            claims=[claim.public_payload() for claim in task.claims],
            preflight_approved=True,
            clock=clock(),
        )
        if (
            episode.final_outcome.status is not EpisodeOutcomeStatus.SUCCEEDED
            or observation is None
            or observation.output_sha256 is None
        ):
            failure_codes = [
                failure.code for failure in episode.failures
            ] or ["development_harness_execution"]
            raise MechanismDevelopmentIntegrityError(
                "development Harness failed: " + ",".join(failure_codes)
            )
        result = MechanismDevelopmentTaskResult.create(
            task=task,
            generated_source_sha256=proposal.source_sha256,
            harness_spec_hash=spec.spec_hash,
            harness_episode_hash=episode.episode_hash,
            output_artifact_sha256=observation.output_sha256,
            decisions=decisions,
            execution_succeeded=True,
        )
        write_json_model(
            root / "development" / task.task_id / "task-result.json",
            result,
        )
        results.append(result)
    return results


def _preflight_failure_codes(
    static_report: GeneratedCodeStaticReviewReport,
    unit_report: GeneratedCodeTestReport,
    property_report: GeneratedCodeTestReport,
) -> list[str]:
    codes = [finding.code for finding in static_report.findings]
    if not unit_report.passed:
        codes.append("generated_code_unit_tests")
    if not property_report.passed:
        codes.append("generated_code_property_tests")
    return sorted(set(codes))


def _sandbox_smoke_claims() -> list[dict[str, str | float | int]]:
    return [
        {
            "claim_id": "smoke-supported",
            "support_score": 0.90,
            "contradiction_score": 0.04,
            "uncertainty": 0.10,
            "independent_source_count": 4,
            "source_quality": 0.92,
        },
        {
            "claim_id": "smoke-unsupported",
            "support_score": 0.35,
            "contradiction_score": 0.75,
            "uncertainty": 0.82,
            "independent_source_count": 0,
            "source_quality": 0.42,
        },
    ]


def _finalize_blocked(
    *,
    root: Path,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    foundation: MechanismFoundationManifest,
    parent: ParentSprintEvidence,
    brief: MechanismResearchBrief,
    panel: MechanismPanelSpec,
    stage: str,
    failure_codes: Sequence[str],
    summary: str,
    interactions: list[MechanismModelInteraction],
    diagnosis: MechanismDiagnosis | None = None,
    proposal: MechanismCodeProposal | None = None,
    code_evidence: GeneratedCodeEvidence | None = None,
    round_freeze: MechanismRoundFreeze | None = None,
    screen: MechanismDevelopmentScreen | None = None,
) -> MechanismDevelopmentManifest:
    normalized_codes = sorted(set(failure_codes)) or ["unknown_blocker"]
    failure = MechanismDevelopmentFailure.create(
        stage=stage,
        failure_codes=normalized_codes,
        summary=summary,
        created_at=completed_at,
    )
    write_json_model(root / "failure.json", failure)
    return _finalize_manifest(
        root=root,
        run_id=run_id,
        status=MechanismDevelopmentStatus.BLOCKED,
        started_at=started_at,
        completed_at=completed_at,
        foundation=foundation,
        parent=parent,
        brief=brief,
        panel=panel,
        interactions=interactions,
        diagnosis=diagnosis,
        proposal=proposal,
        code_evidence=code_evidence,
        round_freeze=round_freeze,
        screen=screen,
        failure_codes=normalized_codes,
    )


def _finalize_manifest(
    *,
    root: Path,
    run_id: str,
    status: MechanismDevelopmentStatus,
    started_at: datetime,
    completed_at: datetime,
    foundation: MechanismFoundationManifest,
    parent: ParentSprintEvidence,
    brief: MechanismResearchBrief,
    panel: MechanismPanelSpec,
    interactions: list[MechanismModelInteraction],
    diagnosis: MechanismDiagnosis | None,
    proposal: MechanismCodeProposal | None,
    code_evidence: GeneratedCodeEvidence | None,
    round_freeze: MechanismRoundFreeze | None,
    screen: MechanismDevelopmentScreen | None,
    failure_codes: Sequence[str],
) -> MechanismDevelopmentManifest:
    manifest = MechanismDevelopmentManifest.create(
        run_id=run_id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        foundation_manifest_hash=foundation.manifest_hash,
        parent_evidence_hash=parent.evidence_hash,
        research_brief_hash=brief.brief_hash,
        panel_hash=panel.panel_hash,
        diagnosis_hash=diagnosis.diagnosis_hash if diagnosis else None,
        proposal_hash=proposal.proposal_hash if proposal else None,
        generated_source_sha256=proposal.source_sha256 if proposal else None,
        generated_code_evidence_hash=(
            code_evidence.evidence_hash if code_evidence else None
        ),
        round_freeze_hash=round_freeze.freeze_hash if round_freeze else None,
        development_screen_hash=screen.screen_hash if screen else None,
        model_interaction_hashes=[
            interaction.interaction_hash for interaction in interactions
        ],
        artifact_file_sha256s=_artifact_file_hashes(root),
        failure_codes=list(failure_codes),
    )
    write_json_model(root / "development-manifest.json", manifest)
    return load_mechanism_development(root)


def _artifact_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.name != "development-manifest.json"
        and not path.name.endswith(".tmp")
    }


def _failure_code(stage: str, error: BaseException) -> str:
    if isinstance(error, LLMClientError):
        return f"{stage}_model_unavailable_or_invalid"
    if isinstance(error, ValidationError):
        return f"{stage}_schema_invalid"
    if "hash" in str(error).casefold():
        return f"{stage}_hash_mismatch"
    return f"{stage}_failed"


def _safe_failure_summary(error: BaseException) -> str:
    text = " ".join(str(error).split())
    for marker in ("api_key=", "authorization:", "bearer "):
        if marker in text.casefold():
            return (
                f"{type(error).__name__}: failure details were redacted because "
                "they may contain a credential."
            )
    return f"{type(error).__name__}: {text[:800]}"
