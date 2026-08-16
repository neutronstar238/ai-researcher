"""Reflection flow integration tests (spec §17.5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_token = ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


def _project_and_cycle(client: TestClient) -> tuple[str, str]:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=_headers()).json()
    project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
    cycles = client.get(f"/api/v1/projects/{project_id}/cycles", headers=_headers()).json()
    return project_id, cycles[-1]["id"]


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


def test_reflection_run_and_accept(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    run = client.post(
        f"/api/v1/projects/{project_id}/cycles/{cycle_id}/reflection-runs", headers=_headers()
    )
    assert run.status_code == 200, run.text
    report = run.json()
    assert report["metrics"]["stage_total"] == 8
    assert report["metrics"]["stage_completed"] == 3  # seed：选题/文献/假设完成
    assert report["metrics"]["unresolved_contradictions"] >= 1
    assert len(report["recommendations"]) >= 1

    # 采纳第一条建议 → 创建 research_action
    rec_id = report["recommendations"][0]["id"]
    accepted = client.post(
        f"/api/v1/projects/{project_id}/cycles/{cycle_id}/reflection/recommendations/{rec_id}:accept",
        headers=_headers(),
    )
    assert accepted.status_code == 200
    assert accepted.json()["action_id"]

    latest = client.get(
        f"/api/v1/projects/{project_id}/cycles/{cycle_id}/reflection", headers=_headers()
    ).json()
    assert latest["metrics"]["stage_total"] == 8
