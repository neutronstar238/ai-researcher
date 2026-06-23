"""In-memory agent registry for MVP multi-agent coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from autoresearch.agents.base import BaseAgent
from autoresearch.agents.profiles import AgentProfile
from autoresearch.knowledge import AgentRole

AgentList: TypeAlias = list[BaseAgent]


class AgentRegistryError(RuntimeError):
    """Raised when registry invariants are violated."""


@dataclass
class AgentRegistry:
    """Track active agents and query them by role or capability."""

    _agents: dict[str, BaseAgent] = field(default_factory=dict)

    def add(self, agent: BaseAgent) -> BaseAgent:
        """Add an agent and reject duplicate IDs."""

        if agent.agent_id in self._agents:
            msg = f"agent already registered: {agent.agent_id}"
            raise AgentRegistryError(msg)
        self._agents[agent.agent_id] = agent
        return agent

    def remove(self, agent_id: str) -> BaseAgent | None:
        """Remove an agent by ID and return it if present."""

        return self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> BaseAgent | None:
        """Return an agent by ID."""

        return self._agents.get(agent_id)

    def assign_profile(self, agent_id: str, profile: AgentProfile) -> BaseAgent:
        """Attach a custom skill/MCP profile to a registered agent."""

        agent = self.get(agent_id)
        if agent is None:
            msg = f"agent is not registered: {agent_id}"
            raise AgentRegistryError(msg)
        agent.bind_profile(profile)
        return agent

    def list(self, *, role: AgentRole | None = None) -> AgentList:
        """List agents, optionally filtered by role."""

        agents = list(self._agents.values())
        if role is not None:
            agents = [agent for agent in agents if agent.role is role]
        return sorted(agents, key=lambda agent: agent.agent_id)

    def find_by_capability(self, capability: str) -> AgentList:
        """Return agents that advertise a capability."""

        return [
            agent
            for agent in self.list()
            if agent.has_capability(capability)
        ]

    def query(
        self,
        *,
        role: AgentRole | None = None,
        capability: str | None = None,
    ) -> AgentList:
        """Query agents by optional role and capability."""

        agents = self.list(role=role)
        if capability is None:
            return agents
        return [
            agent
            for agent in agents
            if agent.has_capability(capability)
        ]

    def __len__(self) -> int:
        return len(self._agents)
