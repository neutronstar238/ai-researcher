import pytest
from hypothesis import given
from hypothesis import strategies as st

from autoresearch.agents import (
    AgentCapabilityError,
    AgentLifecycleState,
    AgentRegistry,
    AgentRegistryError,
    AgentResult,
    AgentResultStatus,
    AgentTask,
    BaseAgent,
)
from autoresearch.knowledge import AgentRole

AGENT_IDS = st.from_regex(r"agent-[a-z0-9]{1,12}", fullmatch=True)


class StubAgent(BaseAgent):
    def execute_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status=AgentResultStatus.SUCCESS,
            output={"task_type": task.task_type},
        )


@given(agent_ids=st.lists(AGENT_IDS, min_size=1, max_size=8, unique=True))
def test_registry_add_get_list_and_remove_preserve_unique_ids(
    agent_ids: list[str],
) -> None:
    registry = AgentRegistry()

    for agent_id in agent_ids:
        agent = _agent(agent_id)
        registry.add(agent)
        assert registry.get(agent_id) is agent

    assert len(registry) == len(agent_ids)
    assert [agent.agent_id for agent in registry.list()] == sorted(agent_ids)

    removed = registry.remove(agent_ids[0])

    assert removed is not None
    assert removed.agent_id == agent_ids[0]
    assert registry.get(agent_ids[0]) is None
    assert len(registry) == len(agent_ids) - 1


@given(agent_id=AGENT_IDS)
def test_registry_rejects_duplicate_agent_ids(agent_id: str) -> None:
    registry = AgentRegistry()
    registry.add(_agent(agent_id))

    with pytest.raises(AgentRegistryError, match=agent_id):
        registry.add(_agent(agent_id))


@given(
    agent_ids=st.lists(AGENT_IDS, min_size=2, max_size=8, unique=True),
    shared_capability=st.from_regex(r"[a-z][a-z0-9_]{1,12}", fullmatch=True),
)
def test_registry_capability_query_returns_only_matching_agents(
    agent_ids: list[str],
    shared_capability: str,
) -> None:
    registry = AgentRegistry()
    expected_ids = set(agent_ids[::2])
    for index, agent_id in enumerate(agent_ids):
        capabilities = (
            frozenset({shared_capability, "common"})
            if index % 2 == 0
            else frozenset({"common"})
        )
        registry.add(_agent(agent_id, capabilities=capabilities))

    matches = registry.find_by_capability(shared_capability)

    assert {agent.agent_id for agent in matches} == expected_ids


def test_base_agent_run_task_enforces_capability_and_lifecycle_state() -> None:
    agent = _agent("agent-runtime", capabilities=frozenset({"summarize"}))

    result = agent.run_task(AgentTask(task_id="task_1", task_type="summarize"))

    assert result.status is AgentResultStatus.SUCCESS
    assert agent.state is AgentLifecycleState.IDLE
    with pytest.raises(AgentCapabilityError):
        agent.run_task(AgentTask(task_id="task_2", task_type="execute"))


def _agent(
    agent_id: str,
    *,
    capabilities: frozenset[str] = frozenset({"common"}),
    role: AgentRole = AgentRole.FIXED_AGENT,
) -> StubAgent:
    return StubAgent(
        agent_id=agent_id,
        role=role,
        capabilities=capabilities,
    )
