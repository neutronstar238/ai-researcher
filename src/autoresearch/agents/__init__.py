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
    DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS,
    AgentMcpRuntimeContract,
    AgentMcpServerBinding,
    AgentProfile,
    AgentProfileReadinessCheck,
    AgentProfileReadinessReport,
    AgentProfileReadinessStatus,
    AgentSkillBinding,
    AgentSkillMaterializationStatus,
    AgentSkillMaterializedContext,
    AgentThinkingMode,
    McpApprovalPolicy,
    SkillImportPolicy,
    SkillSourceType,
    build_agent_mcp_runtime_contracts,
    evaluate_agent_profile_readiness,
    load_agent_profile,
    materialize_agent_skill_contexts,
    normalize_profile_stage,
    parse_mcp_approval_policy_specs,
    parse_mcp_env_key_specs,
    parse_mcp_spec,
    parse_server_tool_specs,
    parse_skill_policy_specs,
    parse_skill_spec,
    profile_contexts_by_stage,
    profile_contexts_for_stage,
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
    "AgentMcpRuntimeContract",
    "AgentProfile",
    "AgentProfileReadinessCheck",
    "AgentProfileReadinessReport",
    "AgentProfileReadinessStatus",
    "AgentRegistry",
    "AgentRegistryError",
    "AgentResult",
    "AgentResultStatus",
    "AgentSkillBinding",
    "AgentSkillMaterializationStatus",
    "AgentSkillMaterializedContext",
    "AgentTask",
    "AgentThinkingMode",
    "BaseAgent",
    "DEFAULT_SKILL_MATERIALIZATION_MAX_CHARS",
    "McpApprovalPolicy",
    "MessageRiskLevel",
    "ResearchWorkflow",
    "ResearchWorkflowStage",
    "ResearchWorkflowState",
    "SkillImportPolicy",
    "SkillSourceType",
    "WorkflowCheckpointStore",
    "build_agent_mcp_runtime_contracts",
    "evaluate_agent_profile_readiness",
    "load_agent_profile",
    "materialize_agent_skill_contexts",
    "normalize_profile_stage",
    "parse_mcp_approval_policy_specs",
    "parse_mcp_env_key_specs",
    "parse_mcp_spec",
    "parse_server_tool_specs",
    "parse_skill_policy_specs",
    "parse_skill_spec",
    "profile_contexts_by_stage",
    "profile_contexts_for_stage",
    "render_agent_profile_markdown",
    "write_agent_profile",
    "write_agent_profile_note",
]
