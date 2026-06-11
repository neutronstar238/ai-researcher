"""Structured inter-agent message protocol."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _message_id() -> str:
    return f"msg_{uuid4().hex}"


class MessageRiskLevel(str, Enum):
    """Risk level for an inter-agent request."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentMessage(BaseModel):
    """Strict structured message exchanged between agents."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=_message_id)
    from_agent: str = Field(min_length=1)
    to_agent: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    input_refs: list[str] = Field(default_factory=list)
    expected_output_schema: dict[str, Any] = Field(min_length=1)
    deadline: datetime | None = None
    budget: dict[str, int | float] = Field(default_factory=dict)
    risk_level: MessageRiskLevel = MessageRiskLevel.LOW
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
