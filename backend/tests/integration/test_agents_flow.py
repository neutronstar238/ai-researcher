"""Agent flow integration tests (spec §24 Phase 5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_token = ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


def _project_and_team(client: TestClient) -> tuple[str, str]:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=_headers()).json()
    project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
    return project_id, teams[0]["id"]


@pytest.fixture(scope="module")
def client():
    global _token
    with TestClient(create_app()) as test_client:
        try:
            response = test_client.post(
                "/api/v1/auth/login",
                json={"email": "owner@airesearcher.local", "password": "demo-password"},
            )
            assert response.status_code == 200, response.text
            _token = response.json()["access_token"]
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"database/seed unavailable: {exc}")
        yield test_client


def test_list_agents(client: TestClient) -> None:
    project_id, team_id = _project_and_team(client)
    agents = client.get(f"/api/v1/projects/{project_id}/agents?team_id={team_id}", headers=_headers()).json()
    assert len(agents) >= 6
    assert any(a["key"] == "literature" for a in agents)


def test_create_and_cancel_task(client: TestClient) -> None:
    project_id, team_id = _project_and_team(client)
    agents = client.get(f"/api/v1/projects/{project_id}/agents?team_id={team_id}", headers=_headers()).json()
    version_id = agents[0]["active_version_id"]
    assert version_id is not None

    task = client.post(
        f"/api/v1/projects/{project_id}/agent-tasks",
        json={"agent_version_id": version_id, "task_type": "literature.evidence_extract", "input": {"objective": "提取证据"}},
        headers=_headers(),
    )
    assert task.status_code == 201
    assert task.json()["status"] == "queued"

    cancelled = client.post(
        f"/api/v1/projects/{project_id}/agent-tasks/{task.json()['id']}:cancel", headers=_headers()
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_tool_call_risk_and_approval(client: TestClient) -> None:
    project_id, team_id = _project_and_team(client)
    agents = client.get(f"/api/v1/projects/{project_id}/agents?team_id={team_id}", headers=_headers()).json()
    version_id = agents[0]["active_version_id"]

    task = client.post(
        f"/api/v1/projects/{project_id}/agent-tasks",
        json={"agent_version_id": version_id, "task_type": "test", "input": {}},
        headers=_headers(),
    ).json()

    # 低风险工具：无需审批
    low = client.post(
        f"/api/v1/projects/{project_id}/agent-tasks/{task['id']}/tool-calls",
        json={"tool_name": "project.read", "arguments": {}},
        headers=_headers(),
    )
    assert low.status_code == 201
    assert low.json()["risk_level"] == "read"
    assert low.json()["status"] == "queued"
    assert low.json()["approval_id"] is None

    # 高风险工具：需审批
    high = client.post(
        f"/api/v1/projects/{project_id}/agent-tasks/{task['id']}/tool-calls",
        json={"tool_name": "experiment.run", "arguments": {}},
        headers=_headers(),
    )
    assert high.status_code == 201
    assert high.json()["risk_level"] == "write_high"
    assert high.json()["status"] == "waiting_approval"
    assert high.json()["approval_id"] is not None
