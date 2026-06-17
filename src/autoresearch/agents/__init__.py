"""Agent runtime primitives."""

from typing import TYPE_CHECKING, Any

from .base import (
    AgentCapabilityError,
    AgentLifecycleState,
    AgentResult,
    AgentResultStatus,
    AgentTask,
    BaseAgent,
)
from .messages import AgentMessage, MessageRiskLevel
from .registry import AgentRegistry, AgentRegistryError

if TYPE_CHECKING:
    from .workflow import (
        ResearchWorkflow,
        ResearchWorkflowStage,
        ResearchWorkflowState,
        WorkflowCheckpointStore,
    )

_WORKFLOW_EXPORTS = {
    "ResearchWorkflow",
    "ResearchWorkflowStage",
    "ResearchWorkflowState",
    "WorkflowCheckpointStore",
}


def __getattr__(name: str) -> Any:
    if name in _WORKFLOW_EXPORTS:
        from . import workflow

        return getattr(workflow, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AgentCapabilityError",
    "AgentLifecycleState",
    "AgentMessage",
    "AgentRegistry",
    "AgentRegistryError",
    "AgentResult",
    "AgentResultStatus",
    "AgentTask",
    "BaseAgent",
    "MessageRiskLevel",
    "ResearchWorkflow",
    "ResearchWorkflowStage",
    "ResearchWorkflowState",
    "WorkflowCheckpointStore",
]
