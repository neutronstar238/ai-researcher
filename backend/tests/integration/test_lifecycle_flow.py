"""Lifecycle + dashboard integration tests against live PostgreSQL (spec §24 Phase 2).

Skips when PostgreSQL/Redis are unavailable. Requires the demo seed to have run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}
_token = ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


def _project_and_cycle(client: TestClient) -> tuple[str, str]:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    team_id = teams[0]["id"]
    projects = client.get(f"/api/v1/projects?team_id={team_id}", headers=_headers()).json()
    project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
    cycles = client.get(f"/api/v1/projects/{project_id}/cycles", headers=_headers()).json()
    cycle_id = cycles[-1]["id"]
    return project_id, cycle_id


@pytest.fixture(scope="module")
def client():
    global _token
    app = create_app()
    with TestClient(app) as test_client:
        try:
            response = test_client.post("/api/v1/auth/login", json=OWNER)
            assert response.status_code == 200, response.text
            _token = response.json()["access_token"]
        except Exception as exc:  # noqa: BLE001 - DB/seed unavailable -> skip
            pytest.skip(f"database/seed unavailable: {exc}")
        yield test_client


def test_seeded_lifecycle_state(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    response = client.get(f"/api/v1/projects/{project_id}/cycles/{cycle_id}/lifecycle", headers=_headers())
    assert response.status_code == 200
    stages = response.json()
    assert len(stages) == 8
    by_key = {s["stage_key"]: s for s in stages}
    assert by_key["topic"]["status"] == "completed"
    assert by_key["literature"]["status"] == "completed"
    assert by_key["hypothesis"]["status"] == "completed"
    assert by_key["experiment"]["status"] == "running"
    assert by_key["validation"]["status"] == "pending"


def test_illegal_transition_returns_409(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/cycles/{cycle_id}/stages/validation:start",
        json={"expected_version": None},
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ILLEGAL_STAGE_TRANSITION"


def test_gate_failure_returns_422(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/cycles/{cycle_id}/stages/experiment:complete",
        json={"expected_version": None, "completion_note": "smoke"},
        headers=_headers(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "STAGE_GATE_FAILED"


def test_dashboard_aggregation(client: TestClient) -> None:
    project_id, _cycle_id = _project_and_cycle(client)
    response = client.get(f"/api/v1/projects/{project_id}/dashboard", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["current_stage"] == "experiment"
    assert body["project"]["progress_percent"] == 62
    assert body["project"]["next_action"] is not None
    assert len(body["lifecycle"]) == 8
    assert set(body["statistics"]) == {"papers", "experiment_runs", "datasets", "figures"}
