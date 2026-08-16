"""Audit-log integration tests against live PostgreSQL (spec §19.6).

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


def _project_id(client: TestClient) -> str:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    team_id = teams[0]["id"]
    projects = client.get(f"/api/v1/projects?team_id={team_id}", headers=_headers()).json()
    return next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")


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


def test_audit_logs_list_endpoint(client: TestClient) -> None:
    project_id = _project_id(client)
    response = client.get(f"/api/v1/projects/{project_id}/audit-logs", headers=_headers())
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


def test_approval_decision_records_audit(client: TestClient) -> None:
    project_id = _project_id(client)
    before = client.get(f"/api/v1/projects/{project_id}/audit-logs", headers=_headers()).json()
    approvals = client.get(
        f"/api/v1/projects/{project_id}/approvals?status=pending", headers=_headers()
    ).json()
    assert approvals, "seed should provide at least one pending approval"
    target = approvals[0]

    response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{target['id']}:reject",
        json={"comment": "audit smoke test"},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text

    logs = client.get(f"/api/v1/projects/{project_id}/audit-logs", headers=_headers()).json()
    assert len(logs) == len(before) + 1
    actions = {entry["action"] for entry in logs}
    assert "approval.rejected" in actions
    rejected = next(entry for entry in logs if entry["action"] == "approval.rejected")
    assert rejected["actor_type"] == "user"
    assert rejected["target_type"] == "approval"
    assert rejected["created_at"]
