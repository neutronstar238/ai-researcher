"""OpenAI-compatible adapter for the provider-neutral vNext harness."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from autoresearch.kernel import (
    AdapterStep,
    ContextPolicy,
    CostPolicy,
    EntropyInterventionPolicy,
    EvaluationPolicy,
    ExactFieldGrader,
    FailureAttributionPolicy,
    FailureDomain,
    GraderKind,
    GraderSpec,
    HarnessAdapterError,
    HarnessSpec,
    JsonFieldType,
    MemoryPolicy,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelPolicy,
    ModelUsage,
    ObservabilityPolicy,
    PermissionPolicy,
    StatePolicy,
    StepOutcome,
    StructuredField,
    StructuredOutputContract,
    TaskContract,
    ToolPolicy,
    TrajectoryKind,
    VerificationPolicy,
)

from .client import LLMClientError, run_llm_json_completion


class OpenAICompatibleHarnessAdapter:
    """Map the existing configurable JSON completion client into the harness protocol."""

    adapter_id = "openai.compatible"
    adapter_version = "1"

    def __init__(
        self,
        *,
        config_path: Path | str,
        env_path: Path | str = Path(".env"),
        estimated_cost_usd: float | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.env_path = Path(env_path)
        self.estimated_cost_usd = estimated_cost_usd

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        """Execute one schema-constrained call without returning endpoint or credentials."""

        messages = _harness_messages(request)
        started = time.perf_counter()
        try:
            completion = run_llm_json_completion(
                messages=messages,
                config_path=self.config_path,
                env_path=self.env_path,
                max_tokens=request.max_output_tokens,
                temperature=request.temperature,
                reasoning_effort=(
                    "none" if request.deliberation == "disabled" else None
                ),
                response_schema=request.response_schema,
                response_schema_name="autoresearch_harness_output",
            )
        except LLMClientError as exc:
            raise _adapter_error(exc, component_id=self.adapter_id) from exc
        elapsed = max(time.perf_counter() - started, 0.0)
        usage = _normalize_usage(
            completion.usage,
            wall_time_seconds=elapsed,
            estimated_cost_usd=self.estimated_cost_usd,
        )
        return ModelInvocationResult(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            provider_ref=completion.provider,
            model_ref=completion.model_name,
            capabilities=["structured_output"],
            attempts=1,
            structured_output=completion.parsed_json,
            usage=usage,
            uncertainty=0.0,
            steps=[
                AdapterStep(
                    step_id="adapter_model_1",
                    kind=TrajectoryKind.MODEL,
                    outcome=StepOutcome.SUCCEEDED,
                    summary=(
                        "OpenAI-compatible adapter returned one schema-constrained "
                        "JSON object."
                    ),
                )
            ],
        )


def build_openai_compatible_characterization_spec(
    *,
    model_ref: str,
) -> HarnessSpec:
    """Build the frozen single-turn spec used by mocked and local-Qwen smoke tests."""

    output_contract = StructuredOutputContract(
        fields=[
            StructuredField(
                name="status",
                value_type=JsonFieldType.STRING,
                enum_values=["ok"],
                description="Literal readiness status.",
            ),
            StructuredField(
                name="summary",
                value_type=JsonFieldType.STRING,
                description=(
                    "A concise statement that this is only a harness "
                    "characterization, not a scientific result."
                ),
            ),
        ]
    )
    return HarnessSpec.create(
        spec_id="harness_openai_compatible_characterization",
        version="1",
        task_contract=TaskContract(
            policy_id="task.openai_compatible_characterization",
            version="1",
            task_id="openai_compatible_characterization",
            instructions=(
                "Return status ok and a concise summary. State that this call only "
                "characterizes the harness path and does not establish a scientific "
                "result. Return no URLs, credentials, personal identifiers, or claims "
                "about external evidence."
            ),
            output_contract=output_contract,
            success_criteria=[
                "The response is a strict JSON object with status equal to ok.",
                "The deterministic status grader passes.",
            ],
            forbidden_actions=[
                "Do not claim a scientific discovery or external benchmark result.",
                "Do not expose credentials, endpoints, or personal identifiers.",
            ],
            stop_conditions=["Stop after one schema-constrained model response."],
            required_permission_ids=["model.invoke.local"],
        ),
        context_policy=ContextPolicy(
            policy_id="context.openai_compatible_characterization",
            version="1",
            allowed_source_ids=["local.harness.fixture"],
            max_context_tokens=512,
            max_context_bytes=4096,
            compression_allowed=False,
            reset_between_trials=True,
            contamination_domains=["scientific.confirmatory.holdout"],
        ),
        model_policy=ModelPolicy(
            policy_id="model.openai_compatible_characterization",
            version="1",
            adapter_id=OpenAICompatibleHarnessAdapter.adapter_id,
            model_ref=model_ref,
            required_capabilities=["structured_output"],
            max_attempts=1,
            max_output_tokens=256,
            temperature=0.0,
            structured_output_required=True,
            deliberation="disabled",
        ),
        tool_policy=ToolPolicy(
            policy_id="tools.openai_compatible_characterization",
            version="1",
            tools=[],
            default_deny=True,
            sandbox_required=True,
            network_default_deny=True,
            max_tool_calls=0,
        ),
        memory_policy=MemoryPolicy(
            policy_id="memory.openai_compatible_characterization",
            version="1",
            vault_read=False,
            vault_write=False,
            allowed_vault_prefixes=[],
            short_term_state=True,
            run_cache=False,
            long_term_experience_write=False,
        ),
        state_policy=StatePolicy(
            policy_id="state.openai_compatible_characterization",
            version="1",
            append_only_events=True,
            checkpoint_every_events=1,
            resume_allowed=True,
            max_mutable_state_bytes=4096,
            terminal_is_immutable=True,
        ),
        permission_policy=PermissionPolicy(
            policy_id="permissions.openai_compatible_characterization",
            version="1",
            granted_permission_ids=["model.invoke.local"],
            approval_required_permission_ids=[],
            forbidden_permission_ids=[],
            deny_unknown=True,
            permission_expansion_allowed=False,
        ),
        verification_policy=VerificationPolicy(
            policy_id="verification.openai_compatible_characterization",
            version="1",
            required_grader_ids=["grader.status_ok"],
            require_output_artifact_hashes=False,
            fail_closed_on_grader_error=True,
            require_journal_seal=True,
        ),
        observability_policy=ObservabilityPolicy(
            policy_id="observability.openai_compatible_characterization",
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
            policy_id="failure.openai_compatible_characterization",
            version="1",
        ),
        cost_policy=CostPolicy(
            policy_id="cost.openai_compatible_characterization",
            version="1",
            max_total_tokens=512,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=300.0,
            max_tool_calls=0,
            require_known_cost=True,
        ),
        entropy_intervention_policy=EntropyInterventionPolicy(
            policy_id="entropy.openai_compatible_characterization",
            version="1",
            max_uncertainty=0.0,
            stop_when_uncertainty_exceeded=True,
            max_retries=0,
            max_human_interventions=0,
            allowed_interventions=[],
        ),
        evaluation_policy=EvaluationPolicy(
            policy_id="evaluation.openai_compatible_characterization",
            version="1",
            trial_count=1,
            graders=[
                GraderSpec(
                    grader_id="grader.status_ok",
                    version="1",
                    kind=GraderKind.DETERMINISTIC,
                    threshold=1.0,
                )
            ],
            require_environment_outcome=True,
            require_all_graders=True,
            promotion_threshold=1.0,
        ),
        change_prediction=(
            "The configurable OpenAI-compatible path will produce the same truthful "
            "episode semantics as the deterministic fixture."
        ),
        evaluation_scope=(
            "One local schema-constrained characterization call; no scientific "
            "claim or provider benchmark."
        ),
    )


def build_status_ok_grader() -> ExactFieldGrader:
    """Return the deterministic grader bound by the characterization spec."""

    return ExactFieldGrader(
        grader_id="grader.status_ok",
        grader_version="1",
        field_name="status",
        expected_value="ok",
    )


def _harness_messages(request: ModelInvocationRequest) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are executing a bounded AutoResearch harness characterization. "
                "Return exactly one JSON object matching the supplied schema. Do not "
                "use markdown fences. Do not reveal secrets, personal identifiers, "
                "endpoints, or unsupported scientific claims."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task:\n{request.instructions}\n\n"
                "Runtime input (canonical JSON):\n"
                f"{json.dumps(request.task_input, sort_keys=True, separators=(',', ':'))}"
            ),
        },
    ]


def _normalize_usage(
    usage: dict[str, Any],
    *,
    wall_time_seconds: float,
    estimated_cost_usd: float | None,
) -> ModelUsage:
    prompt_tokens = _usage_integer(usage, "prompt_tokens")
    completion_tokens = _usage_integer(usage, "completion_tokens")
    reported_total = _usage_integer(usage, "total_tokens")
    total_tokens = max(reported_total, prompt_tokens + completion_tokens)
    return ModelUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd or 0.0,
        cost_known=estimated_cost_usd is not None,
        wall_time_seconds=wall_time_seconds,
    )


def _usage_integer(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(int(value), 0)


def _adapter_error(
    error: LLMClientError,
    *,
    component_id: str,
) -> HarnessAdapterError:
    message = str(error).casefold()
    invalid_markers = (
        "not valid json",
        "top-level value is not an object",
        "response was not json",
        "did not include choices",
        "did not include a message",
        "message content",
    )
    if any(marker in message for marker in invalid_markers):
        return HarnessAdapterError(
            "OpenAI-compatible adapter returned an invalid structured response.",
            domain=FailureDomain.OUTPUT_VALIDATION,
            code="invalid_provider_response",
            component_id=component_id,
            retryable=True,
            blocked=False,
        )
    return HarnessAdapterError(
        "Configured OpenAI-compatible model is unavailable.",
        domain=FailureDomain.MODEL,
        code="model_unavailable",
        component_id=component_id,
        retryable=True,
        blocked=True,
    )
