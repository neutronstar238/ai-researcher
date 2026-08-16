"""Vector store integration tests against live Milvus (spec §24 Phase 3)."""

from __future__ import annotations

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


def test_vector_store_and_search(client: TestClient) -> None:
    project_id = _project_id(client)
    try:
        store = client.post(
            f"/api/v1/projects/{project_id}/vector/store",
            json={"text": "multimodal protein ligand interaction prediction", "paper_id": "p1"},
            headers=_headers(),
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"milvus unavailable: {exc}")
    assert store.status_code == 201
    assert store.json()["embedding_model"] == "hash-dev"

    search = client.post(
        f"/api/v1/projects/{project_id}/vector/search",
        json={"query": "protein ligand interaction", "top_k": 3},
        headers=_headers(),
    )
    assert search.status_code == 200
    hits = search.json()["hits"]
    assert any(h["paper_id"] == "p1" for h in hits)
