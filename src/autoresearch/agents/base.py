"""Base agent contract for the multi-agent runtime."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from autoresearch.agents.profiles import AgentProfile
from autoresearch.knowledge import AgentRole


class AgentLifecycleState(str, Enum):
    """Lifecycle states shared by local agent implementations."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class AgentResultStatus(str, Enum):
    """Task execution status returned by an agent."""

    SUCCESS = "success"
    FAILED = "failed"


class AgentCapabilityError(RuntimeError):
    """Raised when an agent is asked to run an unsupported task."""


@dataclass(frozen=True)
class AgentTask:
    """Structured task passed to an agent."""

    task_id: str
    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    project_id: str | None = None


@dataclass(frozen=True)
class AgentResult:
    """Structured result returned by an agent."""

    task_id: str
    agent_id: str
    status: AgentResultStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class BaseAgent(ABC):
    """Minimal base class every runtime agent must implement."""

    agent_id: str
    role: AgentRole
    capabilities: frozenset[str]
    permissions: frozenset[str] = field(default_factory=frozenset)
    state: AgentLifecycleState = AgentLifecycleState.IDLE
    project_id: str | None = None
    profile: AgentProfile | None = None

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            msg = "agent_id must be non-empty"
            raise ValueError(msg)
        if not self.capabilities:
            msg = "agent capabilities must be non-empty"
            raise ValueError(msg)
        self.capabilities = frozenset(self.capabilities)
        self.permissions = frozenset(self.permissions)
        if self.profile is not None:
            self.bind_profile(self.profile)

    def has_capability(self, capability: str) -> bool:
        """Return whether this agent can handle a capability."""

        return capability in self.capabilities

    def bound_skill_ids(self) -> frozenset[str]:
        """Return custom skill IDs attached through this agent's runtime profile."""

        if self.profile is None:
            return frozenset()
        return frozenset(skill.skill_id for skill in self.profile.skills)

    def bound_mcp_server_ids(self) -> frozenset[str]:
        """Return MCP server IDs attached through this agent's runtime profile."""

        if self.profile is None:
            return frozenset()
        return frozenset(server.server_id for server in self.profile.mcp_servers)

    def bound_mcp_tool_refs(self) -> frozenset[str]:
        """Return scoped MCP tool refs as ``server_id:tool_name`` strings."""

        if self.profile is None:
            return frozenset()
        return frozenset(
            f"{server.server_id}:{tool_name}"
            for server in self.profile.mcp_servers
            for tool_name in server.allowed_tools
        )

    def supports_skill(self, skill_id: str, *, task_type: str | None = None) -> bool:
        """Return whether the profile routes a skill to this agent for a task."""

        if self.profile is None:
            return False
        for skill in self.profile.skills:
            if skill.skill_id != skill_id:
                continue
            return task_type is None or not skill.allowed_tasks or task_type in skill.allowed_tasks
        return False

    def supports_mcp_tool(
        self,
        tool_name: str,
        *,
        server_id: str | None = None,
    ) -> bool:
        """Return whether the profile allowlists an MCP tool for this agent."""

        if self.profile is None:
            return False
        scoped_server_id = server_id
        scoped_tool_name = tool_name
        if scoped_server_id is None and ":" in tool_name:
            scoped_server_id, scoped_tool_name = tool_name.split(":", 1)
        for server in self.profile.mcp_servers:
            if scoped_server_id is not None and server.server_id != scoped_server_id:
                continue
            if scoped_tool_name in server.allowed_tools:
                return True
        return False

    def profile_runtime_capabilities(self) -> dict[str, object]:
        """Return skill/MCP routing metadata without changing task capabilities."""

        return {
            "skill_ids": sorted(self.bound_skill_ids()),
            "mcp_server_ids": sorted(self.bound_mcp_server_ids()),
            "mcp_tool_refs": sorted(self.bound_mcp_tool_refs()),
            "evidence_policy": (
                "Profile runtime capabilities are routing metadata only; they do not "
                "prove scientific results, tool invocation, novelty, citation validity, "
                "publication readiness, or permission to bypass the agent task "
                "capability gate."
            ),
        }

    def bind_profile(self, profile: AgentProfile) -> None:
        """Attach a validated custom skill/MCP profile to this agent."""

        if profile.agent_id != self.agent_id:
            msg = f"profile agent_id {profile.agent_id} does not match {self.agent_id}"
            raise ValueError(msg)
        if profile.role is not self.role:
            msg = f"profile role {profile.role.value} does not match {self.role.value}"
            raise ValueError(msg)
        self.profile = profile

    def runtime_context(self) -> dict[str, Any]:
        """Return the profile context that may be attached to structured messages."""

        if self.profile is None:
            return {
                "agent_id": self.agent_id,
                "role": self.role.value,
                "skills": [],
                "mcp_servers": [],
                "profile_runtime_capabilities": self.profile_runtime_capabilities(),
            }
        context = self.profile.to_runtime_context()
        context["profile_runtime_capabilities"] = self.profile_runtime_capabilities()
        return context

    def run_task(self, task: AgentTask) -> AgentResult:
        """Execute a task while enforcing capability and lifecycle state."""

        if not self.has_capability(task.task_type):
            msg = f"agent {self.agent_id} lacks capability {task.task_type}"
            raise AgentCapabilityError(msg)
        self.state = AgentLifecycleState.RUNNING
        try:
            result = self.execute_task(task)
        except Exception:
            self.state = AgentLifecycleState.FAILED
            raise
        self.state = AgentLifecycleState.IDLE
        return result

    @abstractmethod
    def execute_task(self, task: AgentTask) -> AgentResult:
        """Execute a supported task and return a structured result."""
