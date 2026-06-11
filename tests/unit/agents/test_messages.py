from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from autoresearch.agents import AgentMessage, MessageRiskLevel


def test_agent_message_accepts_structured_payload_and_round_trips() -> None:
    message = AgentMessage(
        from_agent="main",
        to_agent="literature",
        task_id="task_001",
        intent="retrieve_literature",
        input_refs=["candidate_001"],
        expected_output_schema={"papers": "list[DocumentRecord]"},
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        budget={"max_results": 10, "max_cost_usd": 0.0},
        risk_level=MessageRiskLevel.MEDIUM,
    )

    restored = AgentMessage.model_validate(message.model_dump(mode="json"))

    assert message.message_id.startswith("msg_")
    assert restored.intent == "retrieve_literature"
    assert restored.expected_output_schema == {"papers": "list[DocumentRecord]"}
    assert restored.risk_level is MessageRiskLevel.MEDIUM


def test_agent_message_rejects_missing_intent() -> None:
    with pytest.raises(ValidationError):
        AgentMessage(
            from_agent="main",
            to_agent="literature",
            task_id="task_001",
            intent="",
            expected_output_schema={"papers": "list[DocumentRecord]"},
        )


def test_agent_message_rejects_missing_expected_output_schema() -> None:
    with pytest.raises(ValidationError):
        AgentMessage.model_validate(
            {
                "from_agent": "main",
                "to_agent": "literature",
                "task_id": "task_001",
                "intent": "retrieve_literature",
            }
        )


def test_agent_message_rejects_empty_expected_output_schema() -> None:
    with pytest.raises(ValidationError):
        AgentMessage(
            from_agent="main",
            to_agent="literature",
            task_id="task_001",
            intent="retrieve_literature",
            expected_output_schema={},
        )


def test_agent_message_rejects_free_text_only_messages() -> None:
    with pytest.raises(ValidationError):
        AgentMessage.model_validate(
            {
                "from_agent": "main",
                "to_agent": "literature",
                "task_id": "task_001",
                "content": "please look up recent papers",
            }
        )
