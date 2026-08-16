"""Approvals / topic-candidates / coverage integration tests (spec §24 Phase 2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_token = ""


def _headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or _token}"}


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _project_id(client: TestClient) -> str:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=_headers()).json()
    return next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")


@pytest.fixture(scope="module")
def client():
    global _token
    with TestClient(create_app()) as test_client:
        try:
            _token = _login(test_client, "owner@airesearcher.local", "demo-password")
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"database/seed unavailable: {exc}")
        yield test_client


def test_list_approvals(client: TestClient) -> None:
    project_id = _project_id(client)
    response = client.get(f"/api/v1/projects/{project_id}/approvals?status=pending", headers=_headers())
    assert response.status_code == 200
    approvals = response.json()
    assert len(approvals) >= 3
    assert all(a["status"] == "pending" for a in approvals)


def test_approve_and_reject_flow(client: TestClient) -> None:
    project_id = _project_id(client)
    approvals = client.get(f"/api/v1/projects/{project_id}/approvals?status=pending", headers=_headers()).json()
    target = approvals[0]

    response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{target['id']}:approve",
        json={"comment": "已确认风险可控"},
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    # 再次审批应 409（不可重复决定）
    response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{target['id']}:approve",
        json={"comment": "再次"},
        headers=_headers(),
    )
    assert response.status_code == 409


def test_guest_cannot_approve(client: TestClient) -> None:
    project_id = _project_id(client)
    guest_token = _login(client, "guest@airesearcher.local", "demo-password")
    approvals = client.get(f"/api/v1/projects/{project_id}/approvals?status=pending", headers=_headers()).json()
    response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{approvals[0]['id']}:approve",
        json={},
        headers=_headers(guest_token),
    )
    assert response.status_code == 403


def test_topic_candidates_list_and_accept(client: TestClient) -> None:
    project_id = _project_id(client)
    candidates = client.get(f"/api/v1/projects/{project_id}/topic-candidates", headers=_headers()).json()
    assert len(candidates) >= 3

    target = candidates[0]
    response = client.post(
        f"/api/v1/projects/{project_id}/topic-candidates/{target['id']}:accept",
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_evidence_coverage_trend(client: TestClient) -> None:
    project_id = _project_id(client)
    response = client.get(f"/api/v1/projects/{project_id}/evidence-coverage?cycles=6", headers=_headers())
    assert response.status_code == 200
    trend = response.json()
    assert [p["label"] for p in trend] == ["T-5", "T-4", "T-3", "T-2", "T-1", "当前"]
    assert [p["coverage"] for p in trend] == [48, 55, 61, 67, 69, 62]
