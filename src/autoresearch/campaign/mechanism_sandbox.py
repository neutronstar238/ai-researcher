"""Security review and bounded Harness execution for generated mechanisms."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from autoresearch.campaign.mechanism_benchmark import GeneratedClaimDecision
from autoresearch.experiments.executor import execute_experiment_task
from autoresearch.experiments.review import review_generated_code
from autoresearch.kernel import (
    AdapterStep,
    ContextPolicy,
    CostPolicy,
    EntropyInterventionPolicy,
    EpisodeArtifact,
    EpisodePackage,
    EvaluationPolicy,
    ExactFieldGrader,
    FailureAttributionPolicy,
    FailureDomain,
    GraderKind,
    GraderSpec,
    HarnessAdapterError,
    HarnessRunner,
    HarnessRunRequest,
    HarnessSpec,
    JsonFieldType,
    MemoryPolicy,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelPolicy,
    ModelUsage,
    ObservabilityPolicy,
    PermissionPolicy,
    SideEffectLevel,
    StatePolicy,
    StepOutcome,
    StructuredField,
    StructuredOutputContract,
    TaskContract,
    ToolCallRecord,
    ToolDefinition,
    ToolPolicy,
    TrajectoryKind,
    VerificationPolicy,
)
from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)
from autoresearch.kernel.journal import EventJournal
from autoresearch.schemas import ExecutionStatus, ExperimentTask, file_hash

_ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "json",
    "math",
    "pathlib",
    "statistics",
    "typing",
}
_BLOCKED_CALL_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}
_BLOCKED_ATTRIBUTE_NAMES = {
    "chmod",
    "connect",
    "expanduser",
    "fork",
    "glob",
    "hardlink_to",
    "home",
    "popen",
    "remove",
    "rename",
    "replace",
    "request",
    "resolve_uri",
    "rglob",
    "rmdir",
    "spawn",
    "symlink_to",
    "system",
    "unlink",
    "urlopen",
}
_ALLOWED_DUNDER_NAMES = {"__file__", "__main__", "__name__"}
_MAX_SOURCE_BYTES = 16_384
_MAX_AST_NODES = 1_200
_MAX_OUTPUT_BYTES = 262_144


class GeneratedCodeSecurityFinding(KernelContract):
    """One normalized blocking finding over exact generated source bytes."""

    code: StableId
    message: NonEmptyText
    line: int | None = Field(default=None, ge=1)


class GeneratedCodeStaticReviewReport(KernelContract):
    """Content-addressed baseline plus mechanism-specific static review."""

    schema_version: Literal["generated-code-static-review-v1"] = (
        "generated-code-static-review-v1"
    )
    source_sha256: Sha256
    findings: list[GeneratedCodeSecurityFinding]
    approved: bool
    exact_source_reviewed: Literal[True] = True
    report_hash: Sha256

    @field_validator("findings")
    @classmethod
    def _normalize_findings(
        cls,
        value: list[GeneratedCodeSecurityFinding],
    ) -> list[GeneratedCodeSecurityFinding]:
        keys = [(item.code, item.message, item.line) for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("generated-code findings must be unique")
        return sorted(
            value,
            key=lambda item: (item.code, item.line or 0, item.message),
        )

    @model_validator(mode="after")
    def _validate_report(self) -> GeneratedCodeStaticReviewReport:
        if self.approved != (not self.findings):
            raise ValueError("static review verdict contradicts findings")
        if self.report_hash != self.calculated_hash():
            raise ValueError("static review report_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        source_sha256: str,
        findings: list[GeneratedCodeSecurityFinding],
    ) -> GeneratedCodeStaticReviewReport:
        """Attach a digest to normalized deterministic findings."""

        ordered = sorted(
            findings,
            key=lambda item: (item.code, item.line or 0, item.message),
        )
        payload: dict[str, Any] = {
            "schema_version": "generated-code-static-review-v1",
            "source_sha256": source_sha256,
            "findings": [item.model_dump(mode="json") for item in ordered],
            "approved": not ordered,
            "exact_source_reviewed": True,
        }
        payload["report_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the static-review digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


class GeneratedCodeTestReport(KernelContract):
    """Unit or property checks executed against exact generated bytes."""

    schema_version: Literal["generated-code-test-report-v1"] = (
        "generated-code-test-report-v1"
    )
    suite: Literal["unit", "property"]
    source_sha256: Sha256
    checks: dict[StableId, bool]
    observation_hashes: list[Sha256]
    passed: bool
    skipped: bool
    skip_reason: NonEmptyText | None = None
    report_hash: Sha256

    @field_validator("observation_hashes")
    @classmethod
    def _normalize_observations(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("test observation hashes must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_report(self) -> GeneratedCodeTestReport:
        if self.skipped:
            if self.passed or self.skip_reason is None:
                raise ValueError("skipped generated-code suite must explain its skip")
        else:
            if self.skip_reason is not None:
                raise ValueError("executed generated-code suite cannot have skip reason")
            expected_passed = bool(self.checks) and all(self.checks.values())
            if self.passed != expected_passed:
                raise ValueError("generated-code test verdict contradicts checks")
        if self.report_hash != self.calculated_hash():
            raise ValueError("generated-code test report_hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        suite: Literal["unit", "property"],
        source_sha256: str,
        checks: Mapping[str, bool],
        observation_hashes: Sequence[str],
        skipped: bool = False,
        skip_reason: str | None = None,
    ) -> GeneratedCodeTestReport:
        """Compute a suite verdict from deterministic checks."""

        normalized_checks = dict(sorted(checks.items()))
        payload: dict[str, Any] = {
            "schema_version": "generated-code-test-report-v1",
            "suite": suite,
            "source_sha256": source_sha256,
            "checks": normalized_checks,
            "observation_hashes": sorted(set(observation_hashes)),
            "passed": bool(normalized_checks) and all(normalized_checks.values()),
            "skipped": skipped,
            "skip_reason": skip_reason,
        }
        if skipped:
            payload["passed"] = False
        payload["report_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the test-report digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


class SandboxObservation(KernelContract):
    """A compact, non-secret record of one isolated generated-code process."""

    observation_id: StableId
    source_sha256: Sha256
    input_sha256: Sha256
    execution_status: StableId
    exit_code: int | None
    output_sha256: Sha256 | None
    decision_count: int = Field(ge=0)
    network_used: Literal[False] = False
    explicit_environment_keys: list[StableId]
    limit_violations: list[StableId]
    observation_hash: Sha256

    @field_validator("explicit_environment_keys", "limit_violations")
    @classmethod
    def _normalize_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("sandbox observation identifiers must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _validate_hash(self) -> SandboxObservation:
        if self.observation_hash != self.calculated_hash():
            raise ValueError("sandbox observation_hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SandboxObservation:
        """Attach a digest to a sandbox process observation."""

        payload = dict(values)
        payload["network_used"] = False
        payload["explicit_environment_keys"] = sorted(
            payload["explicit_environment_keys"]
        )
        payload["limit_violations"] = sorted(payload["limit_violations"])
        payload["observation_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Recompute the observation digest."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"observation_hash"})
        )


class GeneratedCodeSandboxAdapter:
    """Execute reviewed generated source under a trusted audit-hook wrapper."""

    adapter_id = "generated.code.sandbox"
    adapter_version = "1"

    def __init__(
        self,
        *,
        execution_dir: Path,
        source_text: str,
        claims: list[dict[str, str | float | int]],
        timeout_seconds: int = 15,
        memory_mb: int = 256,
        preflight_approved: bool = True,
        preflight_failure_codes: Sequence[str] = (),
    ) -> None:
        self.execution_dir = execution_dir
        self.source_text = source_text
        self.claims = claims
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.preflight_approved = preflight_approved
        self.preflight_failure_codes = tuple(sorted(set(preflight_failure_codes)))
        self.last_observation: SandboxObservation | None = None
        self.last_decisions: list[GeneratedClaimDecision] = []

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        """Run the exact source or return a truthful security-blocked episode."""

        if not self.preflight_approved:
            raise HarnessAdapterError(
                "Generated source did not pass review and test preflight.",
                domain=FailureDomain.SECURITY,
                code=(
                    self.preflight_failure_codes[0]
                    if self.preflight_failure_codes
                    else "generated_code_preflight"
                ),
                component_id=self.adapter_id,
                retryable=False,
                blocked=True,
            )
        expected_hash = request.task_input.get("generated_source_sha256")
        source_sha256 = hashlib.sha256(
            self.source_text.encode("utf-8")
        ).hexdigest()
        if expected_hash != source_sha256:
            raise HarnessAdapterError(
                "Harness request source hash differs from generated bytes.",
                domain=FailureDomain.SECURITY,
                code="generated_source_hash_mismatch",
                component_id=self.adapter_id,
                retryable=False,
                blocked=True,
            )
        started = time.perf_counter()
        observation, decisions = execute_generated_source(
            execution_dir=self.execution_dir,
            source_text=self.source_text,
            claims=self.claims,
            observation_id=f"{request.episode_id}-process",
            timeout_seconds=self.timeout_seconds,
            memory_mb=self.memory_mb,
        )
        self.last_observation = observation
        self.last_decisions = decisions
        elapsed = max(time.perf_counter() - started, 0.0)
        if observation.execution_status != ExecutionStatus.SUCCESS.value:
            raise HarnessAdapterError(
                "Generated source failed inside the bounded sandbox.",
                domain=FailureDomain.TOOL,
                code="generated_code_execution_failed",
                component_id=self.adapter_id,
                retryable=False,
                blocked=False,
            )
        metrics_path = self.execution_dir / "metrics.json"
        output_sha256 = file_hash(metrics_path)
        artifact_id = f"artifact-{request.episode_id}-metrics"
        return ModelInvocationResult(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            provider_ref="local.python.sandbox",
            model_ref="generated.python.source",
            capabilities=["structured_output", "sandboxed_code_execution"],
            attempts=1,
            structured_output={
                "decision_count": len(decisions),
                "network_used": False,
                "output_sha256": output_sha256,
                "source_sha256": source_sha256,
                "status": "ok",
            },
            usage=ModelUsage(
                total_tokens=0,
                estimated_cost_usd=0.0,
                cost_known=True,
                wall_time_seconds=elapsed,
            ),
            uncertainty=0.0,
            steps=[
                AdapterStep(
                    step_id="generated-code-sandbox-1",
                    kind=TrajectoryKind.TOOL,
                    outcome=StepOutcome.SUCCEEDED,
                    summary=(
                        "Reviewed generated bytes ran under the isolated Python "
                        "audit-hook wrapper with an explicit non-secret environment."
                    ),
                    output_artifact_ids=[artifact_id],
                )
            ],
            tool_calls=[
                ToolCallRecord(
                    call_id="generated-code-tool-1",
                    tool_id="python.generated.execute",
                    outcome=StepOutcome.SUCCEEDED,
                    arguments_hash=canonical_sha256(
                        {
                            "source_sha256": source_sha256,
                            "input_sha256": observation.input_sha256,
                        }
                    ),
                    output_artifact_ids=[artifact_id],
                    summary="Execute exact generated mechanism source locally.",
                )
            ],
            artifacts=[
                EpisodeArtifact(
                    artifact_id=artifact_id,
                    artifact_type="application.json",
                    sha256=output_sha256,
                    media_type="application/json",
                )
            ],
        )


def review_mechanism_source(
    experiment_dir: Path | str,
    *,
    expected_source_sha256: str,
) -> GeneratedCodeStaticReviewReport:
    """Apply baseline and stricter AST review to the exact ``run.py`` bytes."""

    root = Path(experiment_dir)
    source_path = root / "run.py"
    source_bytes = source_path.read_bytes()
    source = source_bytes.decode("utf-8")
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    if actual_hash != expected_source_sha256:
        raise ValueError("static review source hash differs from proposal")
    findings: list[GeneratedCodeSecurityFinding] = []
    baseline = review_generated_code(root, entrypoint="run.py")
    findings.extend(
        GeneratedCodeSecurityFinding(
            code=finding.category,
            message=finding.message,
            line=finding.line,
        )
        for finding in baseline.findings
    )
    findings.extend(_strict_ast_findings(source))
    return GeneratedCodeStaticReviewReport.create(
        source_sha256=actual_hash,
        findings=_dedupe_findings(findings),
    )


def inspect_mechanism_source_text(
    source: str,
) -> tuple[GeneratedCodeSecurityFinding, ...]:
    """Run the pure AST contract before a model proposal is accepted."""

    return tuple(_strict_ast_findings(source))


def build_generated_code_harness_spec(
    *,
    source_sha256: str,
    max_wall_time_seconds: float = 30.0,
) -> HarnessSpec:
    """Build the no-network, one-process Harness contract."""

    output_contract = StructuredOutputContract(
        fields=[
            StructuredField(
                name="decision_count",
                value_type=JsonFieldType.INTEGER,
            ),
            StructuredField(
                name="network_used",
                value_type=JsonFieldType.BOOLEAN,
                enum_values=[False],
            ),
            StructuredField(
                name="output_sha256",
                value_type=JsonFieldType.STRING,
            ),
            StructuredField(
                name="source_sha256",
                value_type=JsonFieldType.STRING,
                enum_values=[source_sha256],
            ),
            StructuredField(
                name="status",
                value_type=JsonFieldType.STRING,
                enum_values=["ok"],
            ),
        ]
    )
    return HarnessSpec.create(
        spec_id=f"mechanism-sandbox-{source_sha256[:16]}",
        version="1",
        task_contract=TaskContract(
            policy_id="task.generated_mechanism_execution",
            version="1",
            task_id="generated_mechanism_execution",
            instructions=(
                "Execute exactly the reviewed generated source against the supplied "
                "claim payload. Return only hashes and decision count; labels and "
                "confirmatory payloads are unavailable."
            ),
            output_contract=output_contract,
            success_criteria=[
                "The process exits successfully under the audit-hook wrapper.",
                "The output covers every supplied claim exactly once.",
                "The executed source SHA-256 equals the reviewed proposal SHA-256.",
                "No network access or secret-bearing environment is available.",
            ],
            forbidden_actions=[
                "Do not access a network, environment secret, or path outside the sandbox.",
                "Do not reveal or execute confirmatory task payloads.",
                "Do not change generated source bytes after review.",
            ],
            stop_conditions=[
                "Stop after one bounded process.",
                "Block before execution if review or tests failed.",
            ],
            required_permission_ids=["code.execute.sandbox"],
            required_tool_ids=["python.generated.execute"],
        ),
        context_policy=ContextPolicy(
            policy_id="context.generated_mechanism_execution",
            version="1",
            allowed_source_ids=["local.development.claims"],
            max_context_tokens=0,
            max_context_bytes=64_000,
            compression_allowed=False,
            reset_between_trials=True,
            contamination_domains=["task2612.confirmatory"],
        ),
        model_policy=ModelPolicy(
            policy_id="model.generated_mechanism_execution",
            version="1",
            adapter_id=GeneratedCodeSandboxAdapter.adapter_id,
            model_ref="generated.python.source",
            required_capabilities=[
                "sandboxed_code_execution",
                "structured_output",
            ],
            max_attempts=1,
            max_output_tokens=64,
            temperature=0.0,
            structured_output_required=True,
            deliberation="disabled",
        ),
        tool_policy=ToolPolicy(
            policy_id="tools.generated_mechanism_execution",
            version="1",
            tools=[
                ToolDefinition(
                    tool_id="python.generated.execute",
                    version="1",
                    input_schema={
                        "type": "object",
                        "additionalProperties": False,
                    },
                    side_effect_level=SideEffectLevel.LOCAL_REVERSIBLE,
                    required_permission_id="code.execute.sandbox",
                    requires_sandbox=True,
                    allowed_network_domains=[],
                )
            ],
            default_deny=True,
            sandbox_required=True,
            network_default_deny=True,
            max_tool_calls=1,
        ),
        memory_policy=MemoryPolicy(
            policy_id="memory.generated_mechanism_execution",
            version="1",
            vault_read=False,
            vault_write=False,
            allowed_vault_prefixes=[],
            short_term_state=True,
            run_cache=False,
            long_term_experience_write=False,
        ),
        state_policy=StatePolicy(
            policy_id="state.generated_mechanism_execution",
            version="1",
            append_only_events=True,
            checkpoint_every_events=1,
            resume_allowed=False,
            max_mutable_state_bytes=512_000,
            terminal_is_immutable=True,
        ),
        permission_policy=PermissionPolicy(
            policy_id="permissions.generated_mechanism_execution",
            version="1",
            granted_permission_ids=["code.execute.sandbox"],
            approval_required_permission_ids=[],
            forbidden_permission_ids=[
                "code.execute.unrestricted",
                "network.access",
                "secret.read",
            ],
            deny_unknown=True,
            permission_expansion_allowed=False,
        ),
        verification_policy=VerificationPolicy(
            policy_id="verification.generated_mechanism_execution",
            version="1",
            required_grader_ids=[
                "grader.generated_source",
                "grader.status_ok",
            ],
            require_output_artifact_hashes=True,
            fail_closed_on_grader_error=True,
            require_journal_seal=True,
        ),
        observability_policy=ObservabilityPolicy(
            policy_id="observability.generated_mechanism_execution",
            version="1",
            record_events=True,
            record_full_trajectory=True,
            record_costs=True,
            record_failures=True,
            record_interventions=True,
            store_raw_model_text=False,
            local_only=True,
            max_step_summary_chars=512,
        ),
        failure_attribution_policy=FailureAttributionPolicy(
            policy_id="failure.generated_mechanism_execution",
            version="1",
        ),
        cost_policy=CostPolicy(
            policy_id="cost.generated_mechanism_execution",
            version="1",
            max_total_tokens=64,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=max_wall_time_seconds,
            max_tool_calls=1,
            require_known_cost=True,
        ),
        entropy_intervention_policy=EntropyInterventionPolicy(
            policy_id="entropy.generated_mechanism_execution",
            version="1",
            max_uncertainty=0.0,
            stop_when_uncertainty_exceeded=True,
            max_retries=0,
            max_human_interventions=0,
            allowed_interventions=[],
        ),
        evaluation_policy=EvaluationPolicy(
            policy_id="evaluation.generated_mechanism_execution",
            version="1",
            trial_count=1,
            graders=[
                GraderSpec(
                    grader_id="grader.generated_source",
                    version="1",
                    kind=GraderKind.DETERMINISTIC,
                    threshold=1.0,
                ),
                GraderSpec(
                    grader_id="grader.status_ok",
                    version="1",
                    kind=GraderKind.DETERMINISTIC,
                    threshold=1.0,
                ),
            ],
            require_environment_outcome=True,
            require_all_graders=True,
            promotion_threshold=1.0,
        ),
        change_prediction=(
            "The model-generated selective gate will execute as the exact reviewed "
            "bytes without network or secret access."
        ),
        evaluation_scope=(
            "One local generated-code process. A successful episode proves only "
            "execution integrity, not a scientific result."
        ),
    )


def run_generated_code_harness(
    *,
    run_id: str,
    episode_id: str,
    output_dir: Path | str,
    source_text: str,
    claims: list[dict[str, str | float | int]],
    preflight_approved: bool,
    preflight_failure_codes: Sequence[str] = (),
    clock: datetime | None = None,
) -> tuple[
    HarnessSpec,
    EpisodePackage,
    SandboxObservation | None,
    list[GeneratedClaimDecision],
]:
    """Run or block one immutable Harness episode and persist its evidence."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    spec = build_generated_code_harness_spec(source_sha256=source_sha256)
    adapter = GeneratedCodeSandboxAdapter(
        execution_dir=root / "process",
        source_text=source_text,
        claims=claims,
        preflight_approved=preflight_approved,
        preflight_failure_codes=preflight_failure_codes,
    )
    journal = EventJournal.create(
        root / "journal",
        run_id=run_id,
        created_at=clock or datetime.now(timezone.utc),
    )
    runner = HarnessRunner(
        spec=spec,
        journal=journal,
        model_adapter=adapter,
        graders={
            "grader.generated_source": ExactFieldGrader(
                grader_id="grader.generated_source",
                grader_version="1",
                field_name="source_sha256",
                expected_value=source_sha256,
            ),
            "grader.status_ok": ExactFieldGrader(
                grader_id="grader.status_ok",
                grader_version="1",
                field_name="status",
                expected_value="ok",
            ),
        },
        clock=(lambda: clock) if clock is not None else None,
    )
    episode = runner.run(
        HarnessRunRequest(
            run_id=run_id,
            episode_id=episode_id,
            task_input={
                "claim_count": len(claims),
                "generated_source_sha256": source_sha256,
            },
            context_artifact_ids=[],
            available_tool_ids=["python.generated.execute"],
        )
    )
    _write_json(root / "harness-spec.json", spec.model_dump(mode="json"))
    _write_json(root / "episode.json", episode.model_dump(mode="json"))
    return spec, episode, adapter.last_observation, adapter.last_decisions


def execute_generated_source(
    *,
    execution_dir: Path | str,
    source_text: str,
    claims: list[dict[str, str | float | int]],
    observation_id: str,
    timeout_seconds: int = 15,
    memory_mb: int = 256,
) -> tuple[SandboxObservation, list[GeneratedClaimDecision]]:
    """Execute exact source with an isolated interpreter and trusted audit hook."""

    root = Path(execution_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "run.py"
    source_path.write_bytes(source_text.encode("utf-8"))
    input_payload = {"claims": claims}
    _write_json(root / "input.json", input_payload)
    (root / "sandbox_runner.py").write_text(
        _sandbox_runner_source(),
        encoding="utf-8",
    )
    task = ExperimentTask(
        id=f"task-{observation_id}",
        project_id="autoresearch-ccfb",
        hypothesis_id="task2612-generated-mechanism",
        name="Generated mechanism sandbox execution",
        description=(
            "Execute exact reviewed generated mechanism code with no network or "
            "secret-bearing environment."
        ),
        entrypoint=(root / "sandbox_runner.py").as_posix(),
        config_path=(root / "input.json").as_posix(),
        metrics=["decision_count"],
        resource_budget={
            "cpu_time_seconds": max(timeout_seconds - 1, 1),
            "memory_mb": memory_mb,
        },
        timeout_seconds=timeout_seconds,
        expected_outputs=["metrics.json"],
    )
    environment = _sandbox_environment(root)
    run = execute_experiment_task(
        root,
        task,
        entrypoint="sandbox_runner.py",
        review_entrypoint="run.py",
        python_arguments=["-I"],
        environment=environment,
        project_root=Path(__file__).resolve().parents[3],
    )
    _write_json(root / "execution-run.json", run.model_dump(mode="json"))
    metrics_path = root / "metrics.json"
    decisions: list[GeneratedClaimDecision] = []
    output_sha256: str | None = None
    if run.status is ExecutionStatus.SUCCESS and metrics_path.is_file():
        if metrics_path.stat().st_size > _MAX_OUTPUT_BYTES:
            raise ValueError("generated mechanism output exceeds size limit")
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        decisions = _parse_decisions(payload, expected_claims=claims)
        output_sha256 = file_hash(metrics_path)
    observation = SandboxObservation.create(
        observation_id=observation_id,
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        input_sha256=canonical_sha256(input_payload),
        execution_status=run.status.value,
        exit_code=run.exit_code,
        output_sha256=output_sha256,
        decision_count=len(decisions),
        explicit_environment_keys=sorted(environment),
        limit_violations=run.limit_violations,
    )
    _write_json(root / "sandbox-observation.json", observation.model_dump(mode="json"))
    return observation, decisions


def run_generated_code_test_suites(
    *,
    output_dir: Path | str,
    source_text: str,
    static_review_approved: bool,
) -> tuple[GeneratedCodeTestReport, GeneratedCodeTestReport]:
    """Run deterministic unit and property probes without scientific labels."""

    root = Path(output_dir)
    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if not static_review_approved:
        unit = GeneratedCodeTestReport.create(
            suite="unit",
            source_sha256=source_sha256,
            checks={},
            observation_hashes=[],
            skipped=True,
            skip_reason="Static review failed; generated code was not executed.",
        )
        properties = GeneratedCodeTestReport.create(
            suite="property",
            source_sha256=source_sha256,
            checks={},
            observation_hashes=[],
            skipped=True,
            skip_reason="Static review failed; generated code was not executed.",
        )
        _write_json(root / "unit-report.json", unit.model_dump(mode="json"))
        _write_json(root / "property-report.json", properties.model_dump(mode="json"))
        return unit, properties

    unit_observations: list[SandboxObservation] = []
    unit_checks: dict[str, bool] = {}
    unit_payloads = [
        _probe_claims("unit-supported", supported=True),
        _probe_claims("unit-unsupported", supported=False),
        [
            *_probe_claims("unit-mixed-a", supported=True),
            *_probe_claims("unit-mixed-b", supported=False),
        ],
    ]
    for index, claims in enumerate(unit_payloads, start=1):
        observation, decisions = execute_generated_source(
            execution_dir=root / "unit" / f"probe-{index}",
            source_text=source_text,
            claims=claims,
            observation_id=f"unit-probe-{index}",
        )
        unit_observations.append(observation)
        unit_checks[f"probe_{index}_succeeded"] = (
            observation.execution_status == ExecutionStatus.SUCCESS.value
        )
        unit_checks[f"probe_{index}_complete"] = len(decisions) == len(claims)
    unit = GeneratedCodeTestReport.create(
        suite="unit",
        source_sha256=source_sha256,
        checks=unit_checks,
        observation_hashes=[
            observation.observation_hash for observation in unit_observations
        ],
    )

    base_claims: list[dict[str, str | float | int]] = [
        {
            "claim_id": "property-a",
            "support_score": 0.88,
            "contradiction_score": 0.05,
            "uncertainty": 0.12,
            "independent_source_count": 4,
            "source_quality": 0.91,
        },
        {
            "claim_id": "property-b",
            "support_score": 0.43,
            "contradiction_score": 0.62,
            "uncertainty": 0.68,
            "independent_source_count": 1,
            "source_quality": 0.56,
        },
    ]
    property_observations: list[SandboxObservation] = []
    base_obs, base_decisions = execute_generated_source(
        execution_dir=root / "property" / "base",
        source_text=source_text,
        claims=base_claims,
        observation_id="property-base",
    )
    repeat_obs, repeat_decisions = execute_generated_source(
        execution_dir=root / "property" / "repeat",
        source_text=source_text,
        claims=base_claims,
        observation_id="property-repeat",
    )
    permuted_obs, permuted_decisions = execute_generated_source(
        execution_dir=root / "property" / "permuted",
        source_text=source_text,
        claims=list(reversed(base_claims)),
        observation_id="property-permuted",
    )
    degraded_claims: list[dict[str, str | float | int]] = [
        {
            "claim_id": "property-a",
            "support_score": 0.35,
            "contradiction_score": 0.75,
            "uncertainty": 0.82,
            "independent_source_count": 0,
            "source_quality": 0.42,
        }
    ]
    degraded_obs, degraded_decisions = execute_generated_source(
        execution_dir=root / "property" / "degraded",
        source_text=source_text,
        claims=degraded_claims,
        observation_id="property-degraded",
    )
    boundary_claims: list[dict[str, str | float | int]] = [
        {
            "claim_id": "property-boundary-supported",
            "support_score": 1.0,
            "contradiction_score": 0.0,
            "uncertainty": 0.0,
            "independent_source_count": 3,
            "source_quality": 1.0,
        },
        {
            "claim_id": "property-boundary-unsupported",
            "support_score": 0.0,
            "contradiction_score": 1.0,
            "uncertainty": 1.0,
            "independent_source_count": 1,
            "source_quality": 0.0,
        },
    ]
    boundary_obs, boundary_decisions = execute_generated_source(
        execution_dir=root / "property" / "numeric-boundaries",
        source_text=source_text,
        claims=boundary_claims,
        observation_id="property-numeric-boundaries",
    )
    property_observations.extend(
        [
            base_obs,
            repeat_obs,
            permuted_obs,
            degraded_obs,
            boundary_obs,
        ]
    )
    base_map = {
        decision.claim_id: decision.model_dump(mode="json")
        for decision in base_decisions
    }
    repeat_map = {
        decision.claim_id: decision.model_dump(mode="json")
        for decision in repeat_decisions
    }
    permuted_map = {
        decision.claim_id: decision.model_dump(mode="json")
        for decision in permuted_decisions
    }
    degraded_abstains = bool(degraded_decisions) and all(
        decision.decision.value == "abstain" for decision in degraded_decisions
    )
    property_checks = {
        "all_processes_succeeded": all(
            observation.execution_status == ExecutionStatus.SUCCESS.value
            for observation in property_observations
        ),
        "deterministic": base_map == repeat_map,
        "permutation_equivariant": base_map == permuted_map,
        "degraded_evidence_abstains": degraded_abstains,
        "closed_numeric_boundaries_succeed": (
            boundary_obs.execution_status == ExecutionStatus.SUCCESS.value
            and len(boundary_decisions) == len(boundary_claims)
        ),
        "extreme_unsupported_abstains": (
            base_map.get("property-b", {}).get("decision") == "abstain"
        ),
    }
    properties = GeneratedCodeTestReport.create(
        suite="property",
        source_sha256=source_sha256,
        checks=property_checks,
        observation_hashes=[
            observation.observation_hash for observation in property_observations
        ],
    )
    _write_json(root / "unit-report.json", unit.model_dump(mode="json"))
    _write_json(root / "property-report.json", properties.model_dump(mode="json"))
    return unit, properties


def _strict_ast_findings(source: str) -> list[GeneratedCodeSecurityFinding]:
    findings: list[GeneratedCodeSecurityFinding] = []
    source_bytes = source.encode("utf-8")
    if len(source_bytes) > _MAX_SOURCE_BYTES:
        findings.append(
            _security_finding(
                "source_size",
                f"generated source exceeds {_MAX_SOURCE_BYTES} bytes",
            )
        )
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            _security_finding(
                "syntax_error",
                exc.msg,
                line=exc.lineno,
            )
        ]
    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        findings.append(
            _security_finding(
                "ast_size",
                f"generated source exceeds {_MAX_AST_NODES} AST nodes",
            )
        )
    function_by_name = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    evaluate = function_by_name.get("evaluate_claims")
    if evaluate is None:
        findings.append(
            _security_finding(
                "missing_function",
                "generated source must define evaluate_claims",
            )
        )
    elif (
        len(evaluate.args.args) != 1
        or evaluate.args.vararg is not None
        or evaluate.args.kwarg is not None
    ):
        findings.append(
            _security_finding(
                "invalid_signature",
                "evaluate_claims must accept exactly one positional argument",
                line=evaluate.lineno,
            )
        )
    if "main" not in function_by_name:
        findings.append(
            _security_finding(
                "missing_main",
                "generated source must define main",
            )
        )
    else:
        main_function = function_by_name["main"]
        if (
            main_function.args.args
            or main_function.args.vararg is not None
            or main_function.args.kwarg is not None
        ):
            findings.append(
                _security_finding(
                    "invalid_signature",
                    "main must not accept arguments",
                    line=main_function.lineno,
                )
            )
    for node in nodes:
        if isinstance(
            node,
            ast.AsyncFunctionDef | ast.Await | ast.ClassDef | ast.Lambda,
        ):
            findings.append(
                _security_finding(
                    "dynamic_structure",
                    f"generated source cannot use {type(node).__name__}",
                    line=getattr(node, "lineno", None),
                )
            )
        if isinstance(node, ast.While):
            findings.append(
                _security_finding(
                    "unbounded_loop",
                    "generated source cannot use while loops",
                    line=node.lineno,
                )
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", maxsplit=1)[0]
                if root not in _ALLOWED_IMPORT_ROOTS:
                    findings.append(
                        _security_finding(
                            "import_not_allowlisted",
                            f"import root {root} is not allowlisted",
                            line=node.lineno,
                        )
                    )
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", maxsplit=1)[0]
            if root not in _ALLOWED_IMPORT_ROOTS:
                findings.append(
                    _security_finding(
                        "import_not_allowlisted",
                        f"import root {root or '<relative>'} is not allowlisted",
                        line=node.lineno,
                    )
                )
        if isinstance(node, ast.Call):
            name = _ast_call_name(node.func)
            if name in _BLOCKED_CALL_NAMES:
                findings.append(
                    _security_finding(
                        "dynamic_execution",
                        f"call {name} is forbidden",
                        line=node.lineno,
                    )
                )
            if (
                name == "evaluate_claims"
                and evaluate is not None
                and any(node is nested for nested in ast.walk(evaluate))
            ):
                findings.append(
                    _security_finding(
                        "recursion",
                        "evaluate_claims cannot call itself",
                        line=node.lineno,
                    )
                )
        if isinstance(node, ast.Attribute):
            if node.attr in _BLOCKED_ATTRIBUTE_NAMES:
                findings.append(
                    _security_finding(
                        "blocked_attribute",
                        f"attribute {node.attr} is forbidden",
                        line=node.lineno,
                    )
                )
            if node.attr.startswith("__") and node.attr not in _ALLOWED_DUNDER_NAMES:
                findings.append(
                    _security_finding(
                        "dunder_access",
                        f"dunder attribute {node.attr} is forbidden",
                        line=node.lineno,
                    )
                )
        if (
            isinstance(node, ast.Name)
            and node.id.startswith("__")
            and node.id not in _ALLOWED_DUNDER_NAMES
        ):
            findings.append(
                _security_finding(
                    "dunder_access",
                    f"dunder name {node.id} is forbidden",
                    line=node.lineno,
                )
            )
    for statement in tree.body:
        allowed_top_level = (
            ast.Assign,
            ast.AnnAssign,
            ast.FunctionDef,
            ast.If,
            ast.Import,
            ast.ImportFrom,
        )
        if not isinstance(statement, allowed_top_level):
            findings.append(
                _security_finding(
                    "top_level_effect",
                    f"top-level {type(statement).__name__} is forbidden",
                    line=getattr(statement, "lineno", None),
                )
            )
        if isinstance(statement, ast.If) and not _is_exact_main_guard(statement):
            findings.append(
                _security_finding(
                    "invalid_main_guard",
                    "the only allowed top-level if is exact "
                    'if __name__ == "__main__": main()',
                    line=statement.lineno,
                )
            )
        if isinstance(statement, ast.Assign | ast.AnnAssign) and any(
            isinstance(node, ast.Call) for node in ast.walk(statement)
        ):
            findings.append(
                _security_finding(
                    "top_level_effect",
                    "top-level assignments cannot call functions",
                    line=statement.lineno,
                )
            )
    main_guards = [
        statement
        for statement in tree.body
        if isinstance(statement, ast.If) and _is_exact_main_guard(statement)
    ]
    if len(main_guards) != 1:
        findings.append(
            _security_finding(
                "invalid_main_guard",
                "generated source must contain exactly one "
                'if __name__ == "__main__": main() guard',
            )
        )
    string_literals = {
        node.value
        for node in nodes
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    for required in ("input.json", "metrics.json"):
        if required not in string_literals:
            findings.append(
                _security_finding(
                    "missing_io_contract",
                    f"generated source must reference exact path {required}",
                )
            )
    return _dedupe_findings(findings)


def _is_exact_main_guard(statement: ast.If) -> bool:
    test = statement.test
    if (
        not isinstance(test, ast.Compare)
        or not isinstance(test.left, ast.Name)
        or test.left.id != "__name__"
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
        or len(test.comparators) != 1
        or not isinstance(test.comparators[0], ast.Constant)
        or test.comparators[0].value != "__main__"
        or statement.orelse
        or len(statement.body) != 1
    ):
        return False
    body = statement.body[0]
    return (
        isinstance(body, ast.Expr)
        and isinstance(body.value, ast.Call)
        and isinstance(body.value.func, ast.Name)
        and body.value.func.id == "main"
        and not body.value.args
        and not body.value.keywords
    )


def _parse_decisions(
    payload: object,
    *,
    expected_claims: Sequence[Mapping[str, str | float | int]],
) -> list[GeneratedClaimDecision]:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("generated metrics must be a success object")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("generated metrics decisions must be a list")
    decisions = [
        GeneratedClaimDecision.model_validate(item) for item in raw_decisions
    ]
    expected_ids = {
        str(claim["claim_id"])
        for claim in expected_claims
    }
    observed_ids = [decision.claim_id for decision in decisions]
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("generated decisions contain duplicate claim IDs")
    if set(observed_ids) != expected_ids:
        raise ValueError("generated decisions do not cover exact input claims")
    return sorted(decisions, key=lambda decision: decision.claim_id)


def _probe_claims(
    prefix: str,
    *,
    supported: bool,
) -> list[dict[str, str | float | int]]:
    if supported:
        return [
            {
                "claim_id": f"{prefix}-1",
                "support_score": 0.90,
                "contradiction_score": 0.04,
                "uncertainty": 0.10,
                "independent_source_count": 4,
                "source_quality": 0.92,
            },
            {
                "claim_id": f"{prefix}-2",
                "support_score": 0.78,
                "contradiction_score": 0.12,
                "uncertainty": 0.22,
                "independent_source_count": 2,
                "source_quality": 0.82,
            },
        ]
    return [
        {
            "claim_id": f"{prefix}-1",
            "support_score": 0.35,
            "contradiction_score": 0.72,
            "uncertainty": 0.78,
            "independent_source_count": 0,
            "source_quality": 0.45,
        },
        {
            "claim_id": f"{prefix}-2",
            "support_score": 0.48,
            "contradiction_score": 0.55,
            "uncertainty": 0.63,
            "independent_source_count": 1,
            "source_quality": 0.58,
        },
    ]


def _sandbox_environment(root: Path) -> dict[str, str]:
    environment = {
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "TEMP": root.as_posix(),
        "TMP": root.as_posix(),
    }
    for key in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _sandbox_runner_source() -> str:
    return '''from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON_ROOTS = tuple(
    Path(value).resolve()
    for value in {sys.base_prefix, sys.prefix}
    if value
)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event.startswith("socket.") or event in {
        "os.system",
        "subprocess.Popen",
        "urllib.Request",
    }:
        raise PermissionError(f"sandbox blocked audit event: {event}")
    if event != "open" or not args or isinstance(args[0], int):
        return
    target = Path(str(args[0]))
    if not target.is_absolute():
        target = ROOT / target
    mode = str(args[1]) if len(args) > 1 else "r"
    writes = any(marker in mode for marker in ("a", "w", "x", "+"))
    if _within(target, ROOT):
        return
    if not writes and any(_within(target, allowed) for allowed in PYTHON_ROOTS):
        return
    raise PermissionError(f"sandbox blocked path: {target}")


sys.addaudithook(_audit)
runpy.run_path(str(ROOT / "run.py"), run_name="__main__")
metrics_path = ROOT / "metrics.json"
if not metrics_path.is_file():
    metrics_path.write_text(
        json.dumps({"status": "failed", "error": "missing metrics.json"}),
        encoding="utf-8",
    )
    raise RuntimeError("generated code did not write metrics.json")
'''


def _ast_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _security_finding(
    code: str,
    message: str,
    *,
    line: int | None = None,
) -> GeneratedCodeSecurityFinding:
    return GeneratedCodeSecurityFinding(code=code, message=message, line=line)


def _dedupe_findings(
    findings: Sequence[GeneratedCodeSecurityFinding],
) -> list[GeneratedCodeSecurityFinding]:
    unique = {
        (finding.code, finding.message, finding.line): finding
        for finding in findings
    }
    return sorted(
        unique.values(),
        key=lambda item: (item.code, item.line or 0, item.message),
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
