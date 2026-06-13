import json
from pathlib import Path

import pytest

from autoresearch.runtime import (
    AgentSessionError,
    AgentSessionStatus,
    claim_agent_session,
    list_agent_sessions,
    release_agent_session,
)


def test_agent_session_claim_blocks_overlapping_active_paths(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "agent-sessions.json"

    first = claim_agent_session(
        state_path=state,
        session_id="session_a",
        agent_name="Codex A",
        task_id="72.2",
        claimed_paths=("src/autoresearch/reports",),
    )
    second = claim_agent_session(
        state_path=state,
        session_id="session_b",
        agent_name="Codex B",
        task_id="72.2",
        claimed_paths=("src/autoresearch/reports/evidence_gate.py",),
    )

    assert first.allowed is True
    assert first.session is not None
    assert first.session.claimed_paths == ("src/autoresearch/reports",)
    assert second.allowed is False
    assert second.session is None
    assert len(second.conflicts) == 1
    assert second.conflicts[0].session_id == "session_a"
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert [session["session_id"] for session in payload["sessions"]] == ["session_a"]


def test_agent_session_release_allows_later_overlap(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "agent-sessions.json"
    claim_agent_session(
        state_path=state,
        session_id="session_a",
        agent_name="Codex A",
        task_id="72.2",
        claimed_paths=("src/autoresearch/runtime",),
    )

    released = release_agent_session(state, "session_a")
    second = claim_agent_session(
        state_path=state,
        session_id="session_b",
        agent_name="Codex B",
        task_id="72.2",
        claimed_paths=("src/autoresearch/runtime/sessions.py",),
    )

    assert released.status is AgentSessionStatus.RELEASED
    assert second.allowed is True
    active = list_agent_sessions(state)
    all_sessions = list_agent_sessions(state, include_released=True)
    assert [session.session_id for session in active] == ["session_b"]
    assert [session.session_id for session in all_sessions] == ["session_a", "session_b"]


def test_agent_session_claim_normalizes_paths_and_updates_same_session(
    tmp_path: Path,
) -> None:
    state = tmp_path / ".airesearcher" / "agent-sessions.json"

    first = claim_agent_session(
        state_path=state,
        session_id="session_a",
        agent_name="Codex A",
        task_id="72.2",
        claimed_paths=(".\\SRC\\AutoResearch\\Runtime\\",),
    )
    second = claim_agent_session(
        state_path=state,
        session_id="session_a",
        agent_name="Codex A",
        task_id="72.2b",
        claimed_paths=("./src/autoresearch/runtime/sessions.py",),
    )

    assert first.allowed is True
    assert second.allowed is True
    assert second.session is not None
    assert second.session.claimed_paths == ("src/autoresearch/runtime/sessions.py",)
    assert list_agent_sessions(state)[0].task_id == "72.2b"


def test_agent_session_claim_times_out_when_state_lock_is_active(tmp_path: Path) -> None:
    state = tmp_path / ".airesearcher" / "agent-sessions.json"
    lock_path = state.with_name(f"{state.name}.lock")
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("active lock", encoding="utf-8")

    with pytest.raises(AgentSessionError, match="agent session state is locked"):
        claim_agent_session(
            state_path=state,
            session_id="session_a",
            agent_name="Codex A",
            task_id="72.3",
            claimed_paths=("src/autoresearch/runtime",),
            lock_timeout_seconds=0.0,
        )

    assert lock_path.exists()
