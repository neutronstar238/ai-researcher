"""Tests for versioned harness policies, bounded execution, and episodes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from autoresearch.kernel import (
    AdapterStep,
    ApprovalDecision,
    ApprovalGrant,
    ContextPolicy,
    CostPolicy,
    DeterministicFixtureAdapter,
    EntropyInterventionPolicy,
    EpisodeArtifact,
    EpisodeOutcomeStatus,
    EvaluationPolicy,
    ExactFieldGrader,
    FailureAttributionPolicy,
    FailureDomain,
    GraderKind,
    GraderSpec,
    HarnessAdapterError,
    HarnessRunner,
    HarnessRunRequest,
    HarnessRuntimeError,
    HarnessSpec,
    InterventionKind,
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
    StructuredOutputValidationError,
    TaskContract,
    ToolCallRecord,
    ToolDefinition,
    ToolPolicy,
    TrajectoryKind,
    VerificationPolicy,
)
from autoresearch.kernel.journal import EventJournal

BASE_TIME = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)


def _output_contract(*, allow_additional_fields: bool = False) -> StructuredOutputContract:
    return StructuredOutputContract(
        fields=[
            StructuredField(
                name="status",
                value_type=JsonFieldType.STRING,
                enum_values=["ok"],
            ),
            StructuredField(
                name="value",
                value_type=JsonFieldType.INTEGER,
            ),
        ],
        allow_additional_fields=allow_additional_fields,
    )


def _spec(
    *,
    max_total_tokens: int = 100,
    granted_permissions: list[str] | None = None,
    approval_permissions: list[str] | None = None,
    forbidden_permissions: list[str] | None = None,
    required_permissions: list[str] | None = None,
    required_tools: list[str] | None = None,
    tools: list[ToolDefinition] | None = None,
    max_tool_calls: int = 0,
    max_attempts: int = 1,
    max_retries: int = 0,
    max_uncertainty: float = 1.0,
    require_artifacts: bool = True,
    allow_human_approval: bool = False,
    allow_retry_intervention: bool = True,
    max_human_interventions: int = 0,
    output_contract: StructuredOutputContract | None = None,
) -> HarnessSpec:
    required_permission_ids = required_permissions or ["execute.model"]
    tool_definitions = tools or []
    return HarnessSpec.create(
        spec_id="harness_fixture_v1",
        version="1",
        task_contract=TaskContract(
            policy_id="task.fixture",
            version="1",
            task_id="fixture_task",
            instructions="Return the frozen deterministic fixture result.",
            output_contract=output_contract or _output_contract(),
            success_criteria=["The exact-field grader passes."],
            forbidden_actions=["Do not invent an external scientific result."],
            stop_conditions=["Stop after one bounded trial."],
            required_permission_ids=required_permission_ids,
            required_tool_ids=required_tools or [],
        ),
        context_policy=ContextPolicy(
            policy_id="context.fixture",
            version="1",
            allowed_source_ids=["local.fixture"],
            max_context_tokens=512,
            max_context_bytes=4096,
            compression_allowed=False,
            reset_between_trials=True,
            contamination_domains=["confirmatory.holdout"],
        ),
        model_policy=ModelPolicy(
            policy_id="model.fixture",
            version="1",
            adapter_id="deterministic.fixture",
            model_ref="fixture.model",
            required_capabilities=["structured_output"],
            max_attempts=max_attempts,
            max_output_tokens=128,
            temperature=0.0,
            structured_output_required=True,
            deliberation="disabled",
        ),
        tool_policy=ToolPolicy(
            policy_id="tools.fixture",
            version="1",
            tools=tool_definitions,
            default_deny=True,
            sandbox_required=True,
            network_default_deny=True,
            max_tool_calls=max_tool_calls,
        ),
        memory_policy=MemoryPolicy(
            policy_id="memory.fixture",
            version="1",
            vault_read=True,
            vault_write=False,
            allowed_vault_prefixes=["projects/fixture"],
            short_term_state=True,
            run_cache=True,
            long_term_experience_write=False,
        ),
        state_policy=StatePolicy(
            policy_id="state.fixture",
            version="1",
            append_only_events=True,
            checkpoint_every_events=1,
            resume_allowed=True,
            max_mutable_state_bytes=4096,
            terminal_is_immutable=True,
        ),
        permission_policy=PermissionPolicy(
            policy_id="permissions.fixture",
            version="1",
            granted_permission_ids=(
                ["execute.model"]
                if granted_permissions is None
                else granted_permissions
            ),
            approval_required_permission_ids=approval_permissions or [],
            forbidden_permission_ids=forbidden_permissions or [],
            deny_unknown=True,
            permission_expansion_allowed=False,
        ),
        verification_policy=VerificationPolicy(
            policy_id="verification.fixture",
            version="1",
            required_grader_ids=["grader.exact"],
            require_output_artifact_hashes=require_artifacts,
            fail_closed_on_grader_error=True,
            require_journal_seal=True,
        ),
        observability_policy=ObservabilityPolicy(
            policy_id="observability.fixture",
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
            policy_id="failure.fixture",
            version="1",
        ),
        cost_policy=CostPolicy(
            policy_id="cost.fixture",
            version="1",
            max_total_tokens=max_total_tokens,
            max_estimated_cost_usd=1.0,
            max_wall_time_seconds=30.0,
            max_tool_calls=max_tool_calls,
            require_known_cost=True,
        ),
        entropy_intervention_policy=EntropyInterventionPolicy(
            policy_id="entropy.fixture",
            version="1",
            max_uncertainty=max_uncertainty,
            stop_when_uncertainty_exceeded=True,
            max_retries=max_retries,
            max_human_interventions=max_human_interventions,
            allowed_interventions=(
                [InterventionKind.HUMAN_APPROVAL]
                if allow_human_approval
                else (
                    [InterventionKind.RETRY]
                    if max_retries and allow_retry_intervention
                    else []
                )
            ),
        ),
        evaluation_policy=EvaluationPolicy(
            policy_id="evaluation.fixture",
            version="1",
            trial_count=1,
            graders=[
                GraderSpec(
                    grader_id="grader.exact",
                    version="1",
                    kind=GraderKind.DETERMINISTIC,
                    threshold=1.0,
                )
            ],
            require_environment_outcome=True,
            require_all_graders=True,
            promotion_threshold=1.0,
        ),
        change_prediction="The versioned harness will make failures attributable.",
        evaluation_scope="One deterministic local characterization fixture.",
    )


def _artifact() -> EpisodeArtifact:
    return EpisodeArtifact(
        artifact_id="artifact_fixture_output",
        artifact_type="application.json",
        sha256="a" * 64,
        media_type="application/json",
    )


def _result(
    *,
    output: dict[str, object] | None = None,
    attempts: int = 1,
    uncertainty: float = 0.0,
    total_tokens: int = 7,
    cost_known: bool = True,
    tool_calls: list[ToolCallRecord] | None = None,
    artifacts: list[EpisodeArtifact] | None = None,
) -> ModelInvocationResult:
    return ModelInvocationResult(
        adapter_id="deterministic.fixture",
        adapter_version="1",
        provider_ref="local.fixture",
        model_ref="fixture.model",
        capabilities=["structured_output"],
        attempts=attempts,
        structured_output=output or {"status": "ok", "value": 4},
        usage=ModelUsage(
            prompt_tokens=4,
            completion_tokens=3,
            total_tokens=total_tokens,
            estimated_cost_usd=0.0,
            cost_known=cost_known,
            wall_time_seconds=0.01,
        ),
        uncertainty=uncertainty,
        steps=[
            AdapterStep(
                step_id="adapter_model_1",
                kind=TrajectoryKind.MODEL,
                outcome=StepOutcome.SUCCEEDED,
                summary="Deterministic fixture returned its frozen object.",
            )
        ],
        tool_calls=tool_calls or [],
        artifacts=[_artifact()] if artifacts is None else artifacts,
    )


def _grader(*, expected: object = 4) -> ExactFieldGrader:
    return ExactFieldGrader(
        grader_id="grader.exact",
        grader_version="1",
        field_name="value",
        expected_value=expected,
    )


def _request(
    *,
    approvals: list[ApprovalGrant] | None = None,
    available_tools: list[str] | None = None,
    task_input: dict[str, object] | None = None,
) -> HarnessRunRequest:
    return HarnessRunRequest(
        run_id="run_harness_fixture",
        episode_id="episode_fixture",
        task_input=task_input or {"operand": 2},
        context_artifact_ids=["context_fixture"],
        available_tool_ids=available_tools or [],
        approvals=approvals or [],
    )


def _runner(
    tmp_path: Path,
    *,
    spec: HarnessSpec | None = None,
    adapter: object | None = None,
    graders: dict[str, object] | None = None,
) -> tuple[HarnessRunner, EventJournal, object]:
    resolved_spec = spec or _spec()
    resolved_adapter = adapter or DeterministicFixtureAdapter(_result())
    journal = EventJournal.create(
        tmp_path / "journal",
        run_id="run_harness_fixture",
        created_at=BASE_TIME,
    )
    runner = HarnessRunner(
        spec=resolved_spec,
        journal=journal,
        model_adapter=resolved_adapter,
        graders=(
            graders if graders is not None else {"grader.exact": _grader()}
        ),
        clock=lambda: BASE_TIME,
    )
    return runner, journal, resolved_adapter


def test_harness_spec_is_content_addressed_and_exports_strict_response_schema() -> None:
    spec = _spec()
    restored = HarnessSpec.model_validate_json(spec.canonical_json())

    assert restored == spec
    assert restored.spec_hash == restored.calculated_hash()
    assert spec.task_contract.output_contract.json_schema() == {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ok"]},
            "value": {"type": "integer"},
        },
        "required": ["status", "value"],
        "additionalProperties": False,
    }


def test_harness_spec_detects_nested_tampering() -> None:
    spec = _spec()
    spec.cost_policy.max_total_tokens = 999

    with pytest.raises(HarnessRuntimeError, match="integrity"):
        spec.verify_integrity()


def test_cross_policy_validation_rejects_missing_tools_and_retry_budget() -> None:
    with pytest.raises(ValidationError, match="absent from tool policy"):
        _spec(required_tools=["missing.tool"])

    with pytest.raises(ValidationError, match="retry count exceeds"):
        _spec(max_attempts=2, max_retries=0)


def test_permission_sets_are_disjoint() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        PermissionPolicy(
            policy_id="permissions.invalid",
            version="1",
            granted_permission_ids=["execute.model"],
            approval_required_permission_ids=["execute.model"],
        )


@given(value=st.integers(min_value=-1_000_000, max_value=1_000_000))
def test_structured_output_property_accepts_integers_and_rejects_boolean(value: int) -> None:
    contract = _output_contract()

    assert contract.validate_output({"status": "ok", "value": value})["value"] == value
    with pytest.raises(StructuredOutputValidationError, match="must be integer"):
        contract.validate_output({"status": "ok", "value": True})


def test_structured_output_rejects_missing_extra_enum_and_wrong_top_level() -> None:
    contract = _output_contract()

    with pytest.raises(StructuredOutputValidationError, match="missing required"):
        contract.validate_output({"status": "ok"})
    with pytest.raises(StructuredOutputValidationError, match="additional fields"):
        contract.validate_output({"status": "ok", "value": 4, "extra": "no"})
    with pytest.raises(StructuredOutputValidationError, match="outside its enum"):
        contract.validate_output({"status": "bad", "value": 4})
    with pytest.raises(StructuredOutputValidationError, match="must be an object"):
        contract.validate_output(["not", "an", "object"])


def test_deterministic_fixture_emits_complete_sealed_episode(tmp_path: Path) -> None:
    runner, journal, adapter = _runner(tmp_path)

    episode = runner.run(_request())
    snapshot = journal.snapshot()

    assert episode.final_outcome.status == EpisodeOutcomeStatus.SUCCEEDED
    assert episode.final_outcome.structured_output == {"status": "ok", "value": 4}
    assert len(episode.trials) == 1
    assert [step.kind for step in episode.trajectory] == [
        TrajectoryKind.PREFLIGHT,
        TrajectoryKind.MODEL,
        TrajectoryKind.VERIFICATION,
        TrajectoryKind.OUTCOME,
    ]
    assert episode.graders[0].passed is True
    assert episode.costs[0].total_tokens == 7
    assert episode.artifacts == [_artifact()]
    assert episode.failures == []
    assert episode.approvals == []
    assert episode.interventions == []
    assert len(snapshot.events) == 2
    assert snapshot.seal is not None
    assert episode.journal_seal_hash == snapshot.seal.seal_hash
    assert episode.episode_hash == episode.calculated_hash()
    assert isinstance(adapter, DeterministicFixtureAdapter)
    assert adapter.invocations == 1


def test_negative_grader_is_an_outcome_not_an_execution_failure(tmp_path: Path) -> None:
    runner, journal, _ = _runner(
        tmp_path,
        graders={"grader.exact": _grader(expected=99)},
    )

    episode = runner.run(_request())

    assert episode.final_outcome.status == EpisodeOutcomeStatus.NEGATIVE_RESULT
    assert episode.final_outcome.structured_output == {"status": "ok", "value": 4}
    assert episode.graders[0].passed is False
    assert episode.failures == []
    assert journal.snapshot().events[-1].status.value == "negative_result"


class _ErrorAdapter:
    adapter_id = "deterministic.fixture"
    adapter_version = "1"

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.invocations = 0

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        del request
        self.invocations += 1
        raise self.error


def test_missing_model_becomes_blocked_without_synthetic_output(tmp_path: Path) -> None:
    adapter = _ErrorAdapter(
        HarnessAdapterError(
            "Configured model is unavailable.",
            domain=FailureDomain.MODEL,
            code="model_unavailable",
            component_id="deterministic.fixture",
            retryable=True,
            blocked=True,
        )
    )
    runner, journal, _ = _runner(tmp_path, adapter=adapter)

    episode = runner.run(_request())

    assert episode.final_outcome.status == EpisodeOutcomeStatus.BLOCKED
    assert episode.final_outcome.structured_output is None
    assert episode.graders == []
    assert episode.artifacts == []
    assert episode.failures[0].code == "model_unavailable"
    assert adapter.invocations == 1
    assert journal.snapshot().seal is not None


def test_unexpected_adapter_exception_becomes_attributed_failure(tmp_path: Path) -> None:
    runner, _, _ = _runner(tmp_path, adapter=_ErrorAdapter(RuntimeError("boom")))

    episode = runner.run(_request())

    assert episode.final_outcome.status == EpisodeOutcomeStatus.FAILED
    assert episode.failures[0].domain == FailureDomain.SYSTEM
    assert episode.failures[0].code == "unexpected_adapter_error"


def test_invalid_structured_output_becomes_failed_without_output(tmp_path: Path) -> None:
    adapter = DeterministicFixtureAdapter(_result(output={"status": "ok"}))
    runner, journal, _ = _runner(tmp_path, adapter=adapter)

    episode = runner.run(_request())

    assert episode.final_outcome.status == EpisodeOutcomeStatus.FAILED
    assert episode.final_outcome.structured_output is None
    assert episode.failures[0].domain == FailureDomain.OUTPUT_VALIDATION
    assert episode.failures[0].code == "invalid_structured_output"
    assert journal.snapshot().events[-1].status.value == "failed"


def test_sensitive_model_output_is_failed_and_not_copied_to_episode(tmp_path: Path) -> None:
    adapter = DeterministicFixtureAdapter(
        _result(output={"status": "ok", "value": 4, "note": "person@example.org"})
    )
    runner, _, _ = _runner(tmp_path, adapter=adapter)

    episode = runner.run(_request())
    serialized = episode.canonical_json()

    assert episode.final_outcome.status == EpisodeOutcomeStatus.FAILED
    assert episode.failures[0].code == "sensitive_model_output"
    assert "person@example.org" not in serialized


def test_exhausted_budget_and_denied_permission_block_before_model(tmp_path: Path) -> None:
    budget_adapter = DeterministicFixtureAdapter(_result())
    budget_runner, _, _ = _runner(
        tmp_path / "budget",
        spec=_spec(max_total_tokens=0),
        adapter=budget_adapter,
    )
    budget_episode = budget_runner.run(_request())

    denied_adapter = DeterministicFixtureAdapter(_result())
    denied_runner, _, _ = _runner(
        tmp_path / "permission",
        spec=_spec(granted_permissions=[], forbidden_permissions=["execute.model"]),
        adapter=denied_adapter,
    )
    denied_episode = denied_runner.run(_request())

    assert budget_episode.final_outcome.status == EpisodeOutcomeStatus.BLOCKED
    assert budget_episode.failures[0].code == "token_budget_exhausted"
    assert budget_adapter.invocations == 0
    assert denied_episode.final_outcome.status == EpisodeOutcomeStatus.BLOCKED
    assert denied_episode.failures[0].code == "forbidden_permission"
    assert denied_adapter.invocations == 0


def test_sensitive_runtime_input_blocks_before_model_and_is_not_persisted(
    tmp_path: Path,
) -> None:
    adapter = DeterministicFixtureAdapter(_result())
    runner, journal, _ = _runner(tmp_path, adapter=adapter)

    episode = runner.run(_request(task_input={"email": "person@example.org"}))

    assert episode.final_outcome.status == EpisodeOutcomeStatus.BLOCKED
    assert episode.failures[0].code == "sensitive_runtime_input"
    assert "person@example.org" not in episode.canonical_json()
    assert "person@example.org" not in journal.snapshot().events[0].canonical_json()
    assert adapter.invocations == 0


def test_explicit_approval_is_distinct_from_intervention_and_permission(
    tmp_path: Path,
) -> None:
    spec = _spec(
        granted_permissions=[],
        approval_permissions=["execute.model"],
        allow_human_approval=True,
        max_human_interventions=1,
    )
    approval = ApprovalGrant(
        permission_id="execute.model",
        decision_id="decision_approve_model",
        decision=ApprovalDecision.APPROVED,
        actor_id="operator.fixture",
        decided_at=BASE_TIME,
        reason="Approve one bounded local fixture model call.",
    )
    runner, _, _ = _runner(tmp_path, spec=spec)

    episode = runner.run(_request(approvals=[approval]))

    assert episode.final_outcome.status == EpisodeOutcomeStatus.SUCCEEDED
    assert episode.approvals == [approval]
    assert episode.interventions[0].kind == InterventionKind.HUMAN_APPROVAL


def test_missing_approval_blocks_before_model(tmp_path: Path) -> None:
    adapter = DeterministicFixtureAdapter(_result())
    runner, _, _ = _runner(
        tmp_path,
        spec=_spec(
            granted_permissions=[],
            approval_permissions=["execute.model"],
            allow_human_approval=True,
            max_human_interventions=1,
        ),
        adapter=adapter,
    )

    episode = runner.run(_request())

    assert episode.final_outcome.status == EpisodeOutcomeStatus.BLOCKED
    assert episode.failures[0].code == "approval_missing_or_denied"
    assert adapter.invocations == 0


def test_tool_failure_is_attributed_and_cannot_become_success(tmp_path: Path) -> None:
    tool = ToolDefinition(
        tool_id="tool.calculator",
        version="1",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.NONE,
        required_permission_id="tool.execute",
        requires_sandbox=True,
    )
    spec = _spec(
        granted_permissions=["execute.model", "tool.execute"],
        required_permissions=["execute.model"],
        required_tools=[tool.tool_id],
        tools=[tool],
        max_tool_calls=1,
    )
    failed_call = ToolCallRecord(
        call_id="call_calculator_1",
        tool_id=tool.tool_id,
        outcome=StepOutcome.FAILED,
        arguments_hash="b" * 64,
        failure_code="tool_process_failed",
        summary="Calculator fixture returned a non-zero exit.",
    )
    adapter = DeterministicFixtureAdapter(_result(tool_calls=[failed_call]))
    runner, journal, _ = _runner(tmp_path, spec=spec, adapter=adapter)

    episode = runner.run(_request(available_tools=[tool.tool_id]))

    assert episode.final_outcome.status == EpisodeOutcomeStatus.FAILED
    assert episode.failures[0].domain == FailureDomain.TOOL
    assert episode.failures[0].code == "tool_process_failed"
    assert episode.tool_calls == [failed_call]
    assert journal.snapshot().events[-1].status.value == "failed"


def test_required_tool_unavailable_blocks_before_model(tmp_path: Path) -> None:
    tool = ToolDefinition(
        tool_id="tool.calculator",
        version="1",
        input_schema={},
        side_effect_level=SideEffectLevel.NONE,
    )
    adapter = DeterministicFixtureAdapter(_result())
    runner, _, _ = _runner(
        tmp_path,
        spec=_spec(
            required_tools=[tool.tool_id],
            tools=[tool],
            max_tool_calls=1,
        ),
        adapter=adapter,
    )

    episode = runner.run(_request())

    assert episode.final_outcome.status == EpisodeOutcomeStatus.BLOCKED
    assert episode.failures[0].code == "required_tool_unavailable"
    assert adapter.invocations == 0


@pytest.mark.parametrize(
    ("spec", "result", "failure_code"),
    [
        (_spec(max_total_tokens=6), _result(total_tokens=7), "token_budget_exceeded"),
        (
            _spec(require_artifacts=False),
            _result(cost_known=False),
            "unknown_model_cost",
        ),
        (
            _spec(
                max_attempts=2,
                max_retries=1,
                allow_retry_intervention=False,
            ),
            _result(attempts=2),
            "retry_intervention_forbidden",
        ),
        (
            _spec(max_uncertainty=0.2),
            _result(uncertainty=0.9),
            "uncertainty_threshold_exceeded",
        ),
        (
            _spec(require_artifacts=True),
            _result(artifacts=[]),
            "output_artifact_hash_missing",
        ),
    ],
)
def test_post_model_policy_failures_remain_blocked_or_failed(
    tmp_path: Path,
    spec: HarnessSpec,
    result: ModelInvocationResult,
    failure_code: str,
) -> None:
    runner, _, _ = _runner(
        tmp_path / failure_code,
        spec=spec,
        adapter=DeterministicFixtureAdapter(result),
    )

    episode = runner.run(_request())

    assert episode.final_outcome.structured_output is None
    assert episode.failures[0].code == failure_code


def test_missing_or_mismatched_grader_is_a_verification_failure(
    tmp_path: Path,
) -> None:
    missing_runner, _, _ = _runner(tmp_path / "missing", graders={})
    missing_episode = missing_runner.run(_request())

    wrong = ExactFieldGrader(
        grader_id="grader.exact",
        grader_version="2",
        field_name="value",
        expected_value=4,
    )
    wrong_runner, _, _ = _runner(
        tmp_path / "wrong",
        graders={"grader.exact": wrong},
    )
    wrong_episode = wrong_runner.run(_request())

    assert missing_episode.final_outcome.status == EpisodeOutcomeStatus.FAILED
    assert missing_episode.failures[0].code == "grader_unavailable"
    assert wrong_episode.final_outcome.status == EpisodeOutcomeStatus.FAILED
    assert wrong_episode.failures[0].code == "grader_identity_mismatch"


def test_episode_round_trip_and_nested_tamper_detection(tmp_path: Path) -> None:
    runner, _, _ = _runner(tmp_path)
    episode = runner.run(_request())
    restored = type(episode).model_validate_json(episode.canonical_json())

    assert restored == episode
    episode.final_outcome.structured_output["value"] = 99
    with pytest.raises(HarnessRuntimeError, match="integrity"):
        episode.verify_integrity()


def test_runner_rejects_wrong_or_nonempty_journal(tmp_path: Path) -> None:
    runner, journal, _ = _runner(tmp_path / "wrong")
    with pytest.raises(HarnessRuntimeError, match="does not match journal"):
        runner.run(
            HarnessRunRequest(
                run_id="run_other",
                episode_id="episode_wrong",
            )
        )

    nonempty_runner, nonempty_journal, _ = _runner(tmp_path / "nonempty")
    event_result = _result()
    first_runner = HarnessRunner(
        spec=_spec(),
        journal=nonempty_journal,
        model_adapter=DeterministicFixtureAdapter(event_result),
        graders={"grader.exact": _grader()},
        clock=lambda: BASE_TIME,
    )
    first_runner.run(_request())

    with pytest.raises(HarnessRuntimeError, match="empty episode journal"):
        nonempty_runner.run(_request())
    assert journal.snapshot().events == []
