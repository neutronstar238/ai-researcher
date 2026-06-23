import importlib
import sys


def test_agent_message_import_does_not_eagerly_import_workflow() -> None:
    sys.modules.pop("autoresearch.agents", None)
    sys.modules.pop("autoresearch.agents.workflow", None)

    agents = importlib.import_module("autoresearch.agents")

    assert agents.AgentMessage
    assert "autoresearch.agents.workflow" not in sys.modules
