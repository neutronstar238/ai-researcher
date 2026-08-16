"""Experiment flow integration tests: real subprocess execution (spec §24 Phase 4).

``create_run`` 同步执行（Celery 接线待 live worker 集成测试后切换）。
"""

from __future__ import annotations

import time

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


def test_run_succeeds(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    exp = client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "cycle_id": cycle_id,
            "code": f"OK{int(time.time()) % 100000}",
            "name": "成功实验",
            "entrypoint": 'python -c "print(\'ok\')"',
        },
        headers=_headers(),
    )
    assert exp.status_code == 201, exp.text

    run = client.post(
        f"/api/v1/projects/{project_id}/experiments/{exp.json()['id']}/runs",
        json={},
        headers=_headers(),
    )
    assert run.status_code == 201
    result = run.json()
    assert result["status"] == "succeeded", result
    assert result["exit_code"] == 0
    assert "ok" in (result["log_output"] or "")


def test_run_fails_and_records_exit_code(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    exp = client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "cycle_id": cycle_id,
            "code": f"FAIL{int(time.time()) % 100000}",
            "name": "失败实验",
            "entrypoint": "python -c \"import sys; print('boom'); sys.exit(3)\"",
        },
        headers=_headers(),
    )
    assert exp.status_code == 201

    run = client.post(
        f"/api/v1/projects/{project_id}/experiments/{exp.json()['id']}/runs",
        json={},
        headers=_headers(),
    )
    assert run.status_code == 201
    result = run.json()
    assert result["status"] == "failed", result
    assert result["exit_code"] == 3
    assert "boom" in (result["log_output"] or "")
