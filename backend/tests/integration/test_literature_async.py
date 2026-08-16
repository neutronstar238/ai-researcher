"""Literature async search-run integration tests (spec §13.6/§3.3 202+Job).

只测 Job 生命周期（创建/查询/404）；真实执行由 Celery worker 在独立进程完成，
见 scripts/smoke_literature_async.py 的直播冒烟。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _login_and_project(client: TestClient) -> tuple[str, str]:
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@airesearcher.local", "password": "demo-password"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    teams = client.get("/api/v1/teams", headers=headers).json()
    projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=headers).json()
    project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
    return token, project_id


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        try:
            test_client.post(
                "/api/v1/auth/login",
                json={"email": "owner@airesearcher.local", "password": "demo-password"},
            )
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"database/seed unavailable: {exc}")
        yield test_client


def test_search_run_create_and_get(client: TestClient) -> None:
    token, project_id = _login_and_project(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        f"/api/v1/projects/{project_id}/literature-search-runs",
        json={"query": "protein docking", "provider": "arxiv", "max_results": 5},
        headers=headers,
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]

    got = client.get(
        f"/api/v1/projects/{project_id}/literature-search-runs/{run_id}", headers=headers
    )
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["id"] == run_id
    assert body["query"] == "protein docking"
    assert body["status"] in {"queued", "running", "succeeded", "failed"}

    listing = client.get(f"/api/v1/projects/{project_id}/literature-search-runs", headers=headers)
    assert listing.status_code == 200
    assert any(r["id"] == run_id for r in listing.json())


def test_get_unknown_run_404(client: TestClient) -> None:
    token, project_id = _login_and_project(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get(
        f"/api/v1/projects/{project_id}/literature-search-runs/{uuid.uuid4()}", headers=headers
    )
    assert response.status_code == 404
