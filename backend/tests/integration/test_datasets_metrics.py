"""Datasets, metrics and reproducibility integration tests (spec §24 Phase 4)."""

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


def test_dataset_and_version(client: TestClient) -> None:
    project_id, _cycle_id = _project_and_cycle(client)
    ds = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": f"ds-{int(time.time()) % 100000}", "description": "测试数据集"},
        headers=_headers(),
    )
    assert ds.status_code == 201, ds.text

    ver = client.post(
        f"/api/v1/projects/{project_id}/datasets/{ds.json()['id']}/versions",
        json={"manifest_sha256": "a" * 64, "row_count": 100, "size_bytes": 2048},
        headers=_headers(),
    )
    assert ver.status_code == 201
    assert ver.json()["version_no"] == 1

    datasets = client.get(f"/api/v1/projects/{project_id}/datasets", headers=_headers()).json()
    assert any(d["id"] == ds.json()["id"] for d in datasets)


def test_metrics_and_reproducibility(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    exp = client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "cycle_id": cycle_id,
            "code": f"REP{int(time.time()) % 100000}",
            "name": "复现实验",
            "entrypoint": 'python -c "print(42)"',
        },
        headers=_headers(),
    ).json()

    run = client.post(
        f"/api/v1/projects/{project_id}/experiments/{exp['id']}/runs",
        json={"random_seed": 7},
        headers=_headers(),
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    recorded = client.post(
        f"/api/v1/projects/{project_id}/experiment-runs/{run_id}/metrics",
        json=[{"name": "accuracy", "step": 1, "value": 0.93}],
        headers=_headers(),
    )
    assert recorded.status_code == 201

    repro = client.get(
        f"/api/v1/projects/{project_id}/experiment-runs/{run_id}/reproducibility", headers=_headers()
    ).json()
    assert repro["run_id"] == run_id
    assert repro["random_seed"] == 7
    assert repro["metrics"][0]["value"] == 0.93


def test_run_dataset_binding_in_reproducibility(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    ds = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": f"dsbind-{int(time.time()) % 100000}"},
        headers=_headers(),
    ).json()
    ver = client.post(
        f"/api/v1/projects/{project_id}/datasets/{ds['id']}/versions",
        json={"manifest_sha256": "b" * 64},
        headers=_headers(),
    ).json()

    exp = client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "cycle_id": cycle_id,
            "code": f"BIND{int(time.time()) % 100000}",
            "name": "绑定实验",
            "entrypoint": 'python -c "print(1)"',
        },
        headers=_headers(),
    ).json()
    run = client.post(
        f"/api/v1/projects/{project_id}/experiments/{exp['id']}/runs", json={}, headers=_headers()
    ).json()

    bound = client.post(
        f"/api/v1/projects/{project_id}/experiment-runs/{run['id']}/datasets",
        json={"dataset_version_id": ver["id"], "mount_path": "/data", "access_mode": "read_only"},
        headers=_headers(),
    )
    assert bound.status_code == 201

    repro = client.get(
        f"/api/v1/projects/{project_id}/experiment-runs/{run['id']}/reproducibility", headers=_headers()
    ).json()
    assert len(repro["datasets"]) == 1
    assert repro["datasets"][0]["manifest_sha256"] == "b" * 64
