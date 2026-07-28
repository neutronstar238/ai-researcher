"""LangGraph-backed research workflow runtime."""

from __future__ import annotations

import json
import warnings
from collections.abc import Hashable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class ResearchWorkflowStage(str, Enum):
    """Executable and terminal stages in the research pipeline."""

    LITERATURE = "literature"
    HYPOTHESIS = "hypothesis"
    EXPERIMENT = "experiment"
    REPORT = "report"
    COMPLETE = "complete"


EXECUTABLE_STAGES: tuple[ResearchWorkflowStage, ...] = (
    ResearchWorkflowStage.LITERATURE,
    ResearchWorkflowStage.HYPOTHESIS,
    ResearchWorkflowStage.EXPERIMENT,
    ResearchWorkflowStage.REPORT,
)

NEXT_STAGE: dict[ResearchWorkflowStage, ResearchWorkflowStage] = {
    ResearchWorkflowStage.LITERATURE: ResearchWorkflowStage.HYPOTHESIS,
    ResearchWorkflowStage.HYPOTHESIS: ResearchWorkflowStage.EXPERIMENT,
    ResearchWorkflowStage.EXPERIMENT: ResearchWorkflowStage.REPORT,
    ResearchWorkflowStage.REPORT: ResearchWorkflowStage.COMPLETE,
}


class WorkflowPayload(TypedDict):
    """Serializable state shape consumed by LangGraph."""

    workflow_id: str
    project_id: str
    stage: str
    completed_steps: list[str]
    paused: bool
    pause_after: str | None


@dataclass(frozen=True)
class ResearchWorkflowState:
    """Checkpointable research workflow state."""

    workflow_id: str
    project_id: str
    stage: ResearchWorkflowStage = ResearchWorkflowStage.LITERATURE
    completed_steps: tuple[ResearchWorkflowStage, ...] = field(default_factory=tuple)
    paused: bool = False

    def to_payload(self, pause_after: ResearchWorkflowStage | None = None) -> WorkflowPayload:
        """Convert the typed state into the LangGraph payload."""

        return {
            "workflow_id": self.workflow_id,
            "project_id": self.project_id,
            "stage": self.stage.value,
            "completed_steps": [step.value for step in self.completed_steps],
            "paused": self.paused,
            "pause_after": pause_after.value if pause_after is not None else None,
        }

    @classmethod
    def from_payload(cls, payload: WorkflowPayload | dict[str, Any]) -> ResearchWorkflowState:
        """Build a typed state from a graph or checkpoint payload."""

        return cls(
            workflow_id=str(payload["workflow_id"]),
            project_id=str(payload["project_id"]),
            stage=ResearchWorkflowStage(str(payload["stage"])),
            completed_steps=tuple(
                ResearchWorkflowStage(str(step)) for step in payload["completed_steps"]
            ),
            paused=bool(payload["paused"]),
        )


class WorkflowCheckpointStore:
    """JSON checkpoint store for resumable research workflows."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, state: ResearchWorkflowState) -> Path:
        """Persist a workflow state and return the checkpoint path."""

        path = self.path_for(state.workflow_id)
        payload = state.to_payload()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def load(self, workflow_id: str) -> ResearchWorkflowState:
        """Load a workflow checkpoint by ID."""

        path = self.path_for(workflow_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ResearchWorkflowState.from_payload(payload)

    def path_for(self, workflow_id: str) -> Path:
        """Return the checkpoint file path for a workflow ID."""

        clean_id = workflow_id.strip()
        if not clean_id or any(separator in clean_id for separator in ("\\", "/", ":")):
            msg = "workflow_id must be non-empty and cannot contain path separators"
            raise ValueError(msg)
        return self.root / f"{clean_id}.json"


class ResearchWorkflow:
    """Compatibility-only linear workflow retained for one reader window."""

    def __init__(self, checkpoint_store: WorkflowCheckpointStore) -> None:
        warnings.warn(
            "ResearchWorkflow is deprecated compatibility scaffolding; "
            "new durable runs must use ControlGraphRuntime",
            DeprecationWarning,
            stacklevel=2,
        )
        self.checkpoint_store = checkpoint_store
        self._graph = self._build_graph()

    def start(
        self,
        *,
        project_id: str,
        workflow_id: str,
        pause_after: ResearchWorkflowStage | None = None,
    ) -> ResearchWorkflowState:
        """Start a workflow and checkpoint its latest state."""

        state = ResearchWorkflowState(workflow_id=workflow_id, project_id=project_id)
        return self._run(state, pause_after=pause_after)

    def resume(self, workflow_id: str) -> ResearchWorkflowState:
        """Resume a checkpointed workflow until the next pause or completion."""

        state = self.checkpoint_store.load(workflow_id)
        resumed_state = ResearchWorkflowState(
            workflow_id=state.workflow_id,
            project_id=state.project_id,
            stage=state.stage,
            completed_steps=state.completed_steps,
            paused=False,
        )
        return self._run(resumed_state, pause_after=None)

    def _run(
        self,
        state: ResearchWorkflowState,
        *,
        pause_after: ResearchWorkflowStage | None,
    ) -> ResearchWorkflowState:
        payload = self._graph.invoke(state.to_payload(pause_after=pause_after))
        next_state = ResearchWorkflowState.from_payload(payload)
        self.checkpoint_store.save(next_state)
        return next_state

    def _build_graph(self) -> Any:
        graph = StateGraph(WorkflowPayload)
        graph.add_node("route", _route)
        graph.set_entry_point("route")
        graph.add_conditional_edges("route", _select_stage, _route_targets())

        for stage in EXECUTABLE_STAGES:
            graph.add_node(stage.value, _stage_runner(stage))
            graph.add_conditional_edges(stage.value, _select_next, _route_targets())

        return graph.compile()


def _route(state: WorkflowPayload) -> WorkflowPayload:
    return state


def _select_stage(state: WorkflowPayload) -> str:
    return state["stage"]


def _select_next(state: WorkflowPayload) -> str:
    if state["paused"]:
        return "pause"
    return state["stage"]


def _route_targets() -> dict[Hashable, str]:
    targets: dict[Hashable, str] = {stage.value: stage.value for stage in EXECUTABLE_STAGES}
    targets[ResearchWorkflowStage.COMPLETE.value] = END
    targets["pause"] = END
    return targets


def _stage_runner(stage: ResearchWorkflowStage) -> Any:
    def run_stage(state: WorkflowPayload) -> WorkflowPayload:
        next_stage = NEXT_STAGE[stage]
        completed_steps = [*state["completed_steps"], stage.value]
        return {
            "workflow_id": state["workflow_id"],
            "project_id": state["project_id"],
            "stage": next_stage.value,
            "completed_steps": completed_steps,
            "paused": state["pause_after"] == stage.value,
            "pause_after": state["pause_after"],
        }

    return run_stage
