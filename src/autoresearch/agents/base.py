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
            }
        return self.profile.to_runtime_context()

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
