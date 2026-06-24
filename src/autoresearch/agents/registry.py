"""In-memory agent registry for MVP multi-agent coordination."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TypeAlias

from autoresearch.agents.base import BaseAgent
from autoresearch.agents.profiles import AgentProfile, AgentStageImportRequirement
from autoresearch.knowledge import AgentRole

AgentList: TypeAlias = list[BaseAgent]

STAGE_ROUTE_EVIDENCE_POLICY = (
    "Stage route selections are process metadata for assigning research-loop "
    "responsibility only. They do not prove scientific results, tool invocation, "
    "novelty, citation validity, benchmark metrics, publication readiness, or "
    "permission to bypass the agent task capability gate."
)


class AgentRegistryError(RuntimeError):
    """Raised when registry invariants are violated."""


@dataclass(frozen=True)
class AgentStageRoute:
    """One scheduler-facing route from a research stage to a runtime agent."""

    stage: str
    agent_id: str
    role: AgentRole
    capability: str | None
    eligible: bool
    capability_matched: bool
    matched_skill_ids: tuple[str, ...] = ()
    missing_skill_ids: tuple[str, ...] = ()
    matched_mcp_server_ids: tuple[str, ...] = ()
    missing_mcp_server_ids: tuple[str, ...] = ()
    matched_mcp_tool_refs: tuple[str, ...] = ()
    missing_mcp_tool_refs: tuple[str, ...] = ()
    evidence_policy: str = STAGE_ROUTE_EVIDENCE_POLICY


AgentStageRouteList: TypeAlias = list[AgentStageRoute]


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

    def find_by_skill(
        self,
        skill_id: str,
        *,
        task_type: str | None = None,
        role: AgentRole | None = None,
    ) -> AgentList:
        """Return agents whose profile binds a custom skill."""

        return [
            agent
            for agent in self.list(role=role)
            if agent.supports_skill(skill_id, task_type=task_type)
        ]

    def find_by_mcp_server(
        self,
        server_id: str,
        *,
        role: AgentRole | None = None,
    ) -> AgentList:
        """Return agents whose profile binds an MCP server."""

        return [
            agent
            for agent in self.list(role=role)
            if server_id in agent.bound_mcp_server_ids()
        ]

    def find_by_mcp_tool(
        self,
        tool_name: str,
        *,
        server_id: str | None = None,
        role: AgentRole | None = None,
    ) -> AgentList:
        """Return agents whose profile allowlists an MCP tool."""

        return [
            agent
            for agent in self.list(role=role)
            if agent.supports_mcp_tool(tool_name, server_id=server_id)
        ]

    def select_for_stage(
        self,
        stage: str,
        *,
        capability: str | None = None,
        required_skill_ids: Iterable[str] = (),
        required_mcp_server_ids: Iterable[str] = (),
        required_mcp_tool_refs: Iterable[str] = (),
        role: AgentRole | None = None,
        include_ineligible: bool = False,
    ) -> AgentStageRouteList:
        """Select stage-assigned agents that satisfy capability and import needs.

        This is the registry-level bridge for stage schedulers. Custom skills and
        MCP bindings narrow responsibility routing, while the ordinary task
        capability gate still decides whether an agent may execute a task.
        """

        requirement = AgentStageImportRequirement(
            stage=stage,
            required_skill_ids=tuple(required_skill_ids),
            required_mcp_server_ids=tuple(required_mcp_server_ids),
            required_mcp_tool_refs=tuple(required_mcp_tool_refs),
        )
        routes: AgentStageRouteList = []
        for agent in self.list(role=role):
            profile = agent.profile
            if profile is None or requirement.stage not in profile.assigned_stages:
                continue
            capability_matched = capability is None or agent.has_capability(capability)
            agent_mcp_server_ids = agent.bound_mcp_server_ids()
            agent_mcp_tool_refs = agent.bound_mcp_tool_refs()
            matched_skill_ids = tuple(
                skill_id
                for skill_id in requirement.required_skill_ids
                if agent.supports_skill(skill_id, task_type=capability)
            )
            missing_skill_ids = tuple(
                skill_id
                for skill_id in requirement.required_skill_ids
                if not agent.supports_skill(skill_id, task_type=capability)
            )
            matched_mcp_server_ids = tuple(
                server_id
                for server_id in requirement.required_mcp_server_ids
                if server_id in agent_mcp_server_ids
            )
            missing_mcp_server_ids = tuple(
                server_id
                for server_id in requirement.required_mcp_server_ids
                if server_id not in agent_mcp_server_ids
            )
            matched_mcp_tool_refs = tuple(
                tool_ref
                for tool_ref in requirement.required_mcp_tool_refs
                if tool_ref in agent_mcp_tool_refs
            )
            missing_mcp_tool_refs = tuple(
                tool_ref
                for tool_ref in requirement.required_mcp_tool_refs
                if tool_ref not in agent_mcp_tool_refs
            )
            eligible = capability_matched and not (
                missing_skill_ids
                or missing_mcp_server_ids
                or missing_mcp_tool_refs
            )
            if not eligible and not include_ineligible:
                continue
            routes.append(
                AgentStageRoute(
                    stage=requirement.stage,
                    agent_id=agent.agent_id,
                    role=agent.role,
                    capability=capability,
                    eligible=eligible,
                    capability_matched=capability_matched,
                    matched_skill_ids=matched_skill_ids,
                    missing_skill_ids=missing_skill_ids,
                    matched_mcp_server_ids=matched_mcp_server_ids,
                    missing_mcp_server_ids=missing_mcp_server_ids,
                    matched_mcp_tool_refs=matched_mcp_tool_refs,
                    missing_mcp_tool_refs=missing_mcp_tool_refs,
                )
            )
        return sorted(routes, key=lambda route: (not route.eligible, route.agent_id))

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
