"""Literature flow integration tests (spec §13/§24 Phase 3)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_token = ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


def _project_id(client: TestClient) -> str:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=_headers()).json()
    return next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")


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


def test_save_and_list_paper(client: TestClient) -> None:
    project_id = _project_id(client)
    unique_title = f"测试论文-{uuid.uuid4().hex[:8]}"
    saved = client.post(
        f"/api/v1/projects/{project_id}/papers",
        json={"title": unique_title, "publication_year": 2025, "source": "manual"},
        headers=_headers(),
    )
    assert saved.status_code == 201

    papers = client.get(f"/api/v1/projects/{project_id}/papers", headers=_headers()).json()
    assert any(p["title"] == unique_title for p in papers)

    # 重复加入应 422
    dup = client.post(
        f"/api/v1/projects/{project_id}/papers",
        json={"title": unique_title},
        headers=_headers(),
    )
    assert dup.status_code == 422


def test_dashboard_papers_count(client: TestClient) -> None:
    project_id = _project_id(client)
    dash = client.get(f"/api/v1/projects/{project_id}/dashboard", headers=_headers()).json()
    assert dash["statistics"]["papers"] >= 3
