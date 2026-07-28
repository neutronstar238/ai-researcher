"""Development vertical proving Harness episodes feed the canonical Control Graph."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from autoresearch.kernel import (
    AdapterStep,
    ControlGraphRuntime,
    DeterministicLoopExecutor,
    EventJournal,
    HarnessRunner,
    HarnessRunRequest,
    LoopBudgetPolicy,
    LoopEdgeKind,
    LoopEdgeSpec,
    LoopGuardKind,
    LoopGuardSpec,
    LoopHoldoutPolicy,
    LoopNodeKind,
    LoopNodeOutcome,
    LoopNodeSpec,
    LoopPermissionPolicy,
    LoopRunStatus,
    LoopSpec,
    LoopStartRequest,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelUsage,
    StepOutcome,
    TrajectoryKind,
    always_guard,
    loop_result_from_episode,
)
from autoresearch.llm import (
    build_openai_compatible_characterization_spec,
    build_status_ok_grader,
)

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)
MODEL_REF = "qwen3.5-sprint:9b-8k"


class _OpenAICompatibleFixtureAdapter:
    """Protocol fixture whose identity matches the real provider-neutral adapter."""

    adapter_id = "openai.compatible"
    adapter_version = "1"

    def __init__(self) -> None:
        self.invocations = 0

    def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        self.invocations += 1
        return ModelInvocationResult(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            provider_ref="local.fixture",
            model_ref=request.model_ref,
            capabilities=["structured_output"],
            attempts=1,
            structured_output={
                "status": "ok",
                "summary": (
                    "Deterministic Harness-to-Control-Graph characterization only; "
                    "this is not a scientific result."
                ),
            },
            usage=ModelUsage(
                prompt_tokens=4,
                completion_tokens=3,
                total_tokens=7,
                estimated_cost_usd=0.0,
                cost_known=True,
                wall_time_seconds=0.01,
            ),
            steps=[
                AdapterStep(
                    step_id="adapter_model_1",
                    kind=TrajectoryKind.MODEL,
                    outcome=StepOutcome.SUCCEEDED,
                    summary="Returned one frozen schema-valid fixture.",
                )
            ],
        )


def _loop_spec() -> LoopSpec:
    return LoopSpec.create(
        spec_id="loop.harness_vertical",
        version="1",
        graph_version=1,
        task_id="task.harness_vertical",
        entry_node_id="start",
        nodes=[
            LoopNodeSpec(
                node_id="start",
                version="1",
                kind=LoopNodeKind.START,
            ),
            LoopNodeSpec(
                node_id="harness",
                version="1",
                kind=LoopNodeKind.ACTION,
                handler_id="handler.harness",
            ),
            LoopNodeSpec(
                node_id="done",
                version="1",
                kind=LoopNodeKind.TERMINAL,
                terminal_status=LoopRunStatus.SUCCEEDED,
            ),
        ],
        edges=[
            LoopEdgeSpec(
                edge_id="edge.start.harness",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id="start",
                target_node_id="harness",
                guards=[always_guard("guard.start.harness")],
            ),
            LoopEdgeSpec(
                edge_id="edge.harness.done",
                version="1",
                kind=LoopEdgeKind.NEXT,
                source_node_id="harness",
                target_node_id="done",
                guards=[
                    LoopGuardSpec(
                        guard_id="guard.harness.succeeded",
                        kind=LoopGuardKind.OUTCOME,
                        outcomes=[LoopNodeOutcome.SUCCEEDED],
                    )
                ],
            ),
        ],
        budget_policy=LoopBudgetPolicy(
            policy_id="budget.harness_vertical",
            version="1",
            max_steps=3,
            max_tokens=20,
            max_estimated_cost_usd=0.0,
            max_wall_time_seconds=10.0,
            max_tool_calls=0,
            max_total_retries=0,
            max_failures=0,
            max_human_interventions=0,
        ),
        permission_policy=LoopPermissionPolicy(
            policy_id="permission.harness_vertical",
            version="1",
        ),
        holdout_policy=LoopHoldoutPolicy(
            policy_id="holdout.harness_vertical",
            version="1",
        ),
    )


def test_verified_harness_episode_drives_one_canonical_loop_run(
    tmp_path: Path,
) -> None:
    harness_run_id = "run.vertical.episode"
    harness_journal = EventJournal.create(
        tmp_path / "episode-journal",
        run_id=harness_run_id,
        created_at=NOW,
    )
    adapter = _OpenAICompatibleFixtureAdapter()
    harness = HarnessRunner(
        spec=build_openai_compatible_characterization_spec(
            model_ref=MODEL_REF
        ),
        journal=harness_journal,
        model_adapter=adapter,
        graders={"grader.status_ok": build_status_ok_grader()},
        clock=lambda: NOW,
    )
    episode = harness.run(
        HarnessRunRequest(
            run_id=harness_run_id,
            episode_id="episode.vertical",
            task_input={"scope": "deterministic_development_vertical"},
        )
    )

    loop_result = loop_result_from_episode(episode)
    loop_run_id = "run.vertical.loop"
    loop_journal = EventJournal.create(
        tmp_path / "loop-journal",
        run_id=loop_run_id,
        created_at=NOW,
    )
    runtime = ControlGraphRuntime(
        spec=_loop_spec(),
        journal=loop_journal,
        executor=DeterministicLoopExecutor(
            {"handler.harness": [loop_result]}
        ),
        clock=lambda: NOW,
    )
    snapshot = runtime.start(
        LoopStartRequest(
            run_id=loop_run_id,
            task_id="task.harness_vertical",
            mechanism_family="harness_characterization",
        )
    )
    harness_snapshot = harness_journal.snapshot()
    loop_journal_snapshot = loop_journal.snapshot()

    assert adapter.invocations == 1
    assert episode.final_outcome.status.value == "succeeded"
    assert harness_snapshot.seal is not None
    assert episode.journal_seal_hash == harness_snapshot.seal.seal_hash
    assert snapshot.state.status == LoopRunStatus.SUCCEEDED
    assert snapshot.state.consumed_usage.tokens == 7
    assert snapshot.state.variables["harness_episode_hash"] == episode.episode_hash
    assert snapshot.state.variables["harness_episode_status"] == "succeeded"
    assert snapshot.state.variables["harness_failure_codes"] == []
    assert loop_journal_snapshot.seal is not None
    assert snapshot.seal_hash == loop_journal_snapshot.seal.seal_hash
