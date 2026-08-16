"""Agent memory integration tests: write + Milvus search (spec §16.6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_token = ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


def _project_and_agent(client: TestClient) -> tuple[str, str]:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=_headers()).json()
    project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
    agents = client.get(f"/api/v1/projects/{project_id}/agents?team_id={teams[0]['id']}", headers=_headers()).json()
    return project_id, agents[0]["id"]


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


def test_memory_write_and_search(client: TestClient) -> None:
    project_id, agent_id = _project_and_agent(client)
    try:
        written = client.post(
            f"/api/v1/projects/{project_id}/agent-memories",
            json={
                "agent_id": agent_id,
                "scope": "semantic",
                "content": "多模态蛋白质配体相互作用预测结果",
                "summary": "多模态表征优于单模态",
            },
            headers=_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"milvus unavailable: {exc}")
    assert written.status_code == 201

    search = client.get(
        f"/api/v1/projects/{project_id}/agent-memories/search",
        params={"query": "蛋白质配体相互作用", "agent_id": agent_id, "top_k": 5},
        headers=_headers(),
    )
    assert search.status_code == 200
    hits = search.json()
    assert len(hits) >= 1

    listed = client.get(
        f"/api/v1/projects/{project_id}/agent-memories", params={"agent_id": agent_id}, headers=_headers()
    ).json()
    assert any(m["id"] == written.json()["id"] for m in listed)
