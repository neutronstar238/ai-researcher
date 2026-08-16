"""Evidence graph integration tests (spec §14/§24 Phase 3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_token = ""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token}"}


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"email": "owner@airesearcher.local", "password": "demo-password"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _project_and_cycle(client: TestClient) -> tuple[str, str]:
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    team_id = teams[0]["id"]
    projects = client.get(f"/api/v1/projects?team_id={team_id}", headers=_headers()).json()
    project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
    cycles = client.get(f"/api/v1/projects/{project_id}/cycles", headers=_headers()).json()
    return project_id, cycles[-1]["id"]


@pytest.fixture(scope="module")
def client():
    global _token
    with TestClient(create_app()) as test_client:
        try:
            _token = _login(test_client)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"database/seed unavailable: {exc}")
        yield test_client


def test_seeded_evidence_graph(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    response = client.get(f"/api/v1/projects/{project_id}/cycles/{cycle_id}/evidence-graph", headers=_headers())
    assert response.status_code == 200
    graph = response.json()
    assert len(graph["nodes"]) == 7
    assert len(graph["edges"]) == 5
    by_code = {n["code"]: n for n in graph["nodes"]}
    assert by_code["C1"]["has_unresolved_contradiction"] is True
    relations = {e["relation"] for e in graph["edges"]}
    assert "supports" in relations and "contradicts" in relations


def test_create_node_and_invalid_edge(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    node = client.post(
        f"/api/v1/projects/{project_id}/evidence/nodes",
        json={"cycle_id": cycle_id, "node_type": "dataset", "code": "D1", "title": "分子对接数据集"},
        headers=_headers(),
    )
    assert node.status_code == 201

    # dataset 不能 contradicts claim
    invalid = client.post(
        f"/api/v1/projects/{project_id}/evidence/edges",
        json={
            "cycle_id": cycle_id,
            "source_node_id": node.json()["id"],
            "target_node_id": _node_id(client, project_id, cycle_id, "C1"),
            "relation": "contradicts",
        },
        headers=_headers(),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_RELATION_FOR_TYPES"


def test_duplicate_edge_rejected(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    e1 = _node_id(client, project_id, cycle_id, "E1")
    d1 = _node_id(client, project_id, cycle_id, "D1")
    first = client.post(
        f"/api/v1/projects/{project_id}/evidence/edges",
        json={"cycle_id": cycle_id, "source_node_id": e1, "target_node_id": d1, "relation": "uses"},
        headers=_headers(),
    )
    assert first.status_code == 201
    dup = client.post(
        f"/api/v1/projects/{project_id}/evidence/edges",
        json={"cycle_id": cycle_id, "source_node_id": e1, "target_node_id": d1, "relation": "uses"},
        headers=_headers(),
    )
    assert dup.status_code == 422
    assert dup.json()["error"]["code"] == "EDGE_ALREADY_EXISTS"


def test_cross_project_edge_rejected(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    teams = client.get("/api/v1/teams", headers=_headers()).json()
    team_id = teams[0]["id"]
    # 新建第二个项目 + 一个节点
    p2 = client.post(
        "/api/v1/projects",
        json={"team_id": team_id, "name": "跨项目隔离测试", "slug": "isolation-test"},
        headers=_headers(),
    )
    assert p2.status_code == 201
    p2_id = p2.json()["id"]
    p2_cycle = client.post(
        f"/api/v1/projects/{p2_id}/cycles",
        json={"name": "第 1 周期"},
        headers=_headers(),
    )
    assert p2_cycle.status_code == 201
    p2_node = client.post(
        f"/api/v1/projects/{p2_id}/evidence/nodes",
        json={"cycle_id": p2_cycle.json()["id"], "node_type": "paper", "code": "X1", "title": "另一项目的论文"},
        headers=_headers(),
    )
    assert p2_node.status_code == 201

    target = _node_id(client, project_id, cycle_id, "C1")
    cross = client.post(
        f"/api/v1/projects/{project_id}/evidence/edges",
        json={
            "cycle_id": cycle_id,
            "source_node_id": p2_node.json()["id"],
            "target_node_id": target,
            "relation": "supports",
        },
        headers=_headers(),
    )
    assert cross.status_code == 403
    assert cross.json()["error"]["code"] == "CROSS_PROJECT_EDGE"


def _node_id(client: TestClient, project_id: str, cycle_id: str, code: str) -> str:
    graph = client.get(f"/api/v1/projects/{project_id}/cycles/{cycle_id}/evidence-graph", headers=_headers()).json()
    return next(n["id"] for n in graph["nodes"] if n["code"] == code)
