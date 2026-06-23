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
from .profiles import (
    AgentMcpServerBinding,
    AgentProfile,
    AgentSkillBinding,
    AgentThinkingMode,
    McpApprovalPolicy,
    SkillImportPolicy,
    SkillSourceType,
    load_agent_profile,
    parse_mcp_spec,
    parse_server_tool_specs,
    parse_skill_spec,
    render_agent_profile_markdown,
    write_agent_profile,
    write_agent_profile_note,
)
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
    "AgentMcpServerBinding",
    "AgentProfile",
    "AgentRegistry",
    "AgentRegistryError",
    "AgentResult",
    "AgentResultStatus",
    "AgentSkillBinding",
    "AgentTask",
    "AgentThinkingMode",
    "BaseAgent",
    "McpApprovalPolicy",
    "MessageRiskLevel",
    "ResearchWorkflow",
    "ResearchWorkflowStage",
    "ResearchWorkflowState",
    "SkillImportPolicy",
    "SkillSourceType",
    "WorkflowCheckpointStore",
    "load_agent_profile",
    "parse_mcp_spec",
    "parse_server_tool_specs",
    "parse_skill_spec",
    "render_agent_profile_markdown",
    "write_agent_profile",
    "write_agent_profile_note",
]
