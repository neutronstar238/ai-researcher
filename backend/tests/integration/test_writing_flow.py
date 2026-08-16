"""Writing flow integration tests (spec §24 Phase 6)."""

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


def test_document_version_and_integrity(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    doc = client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={"cycle_id": cycle_id, "title": "测试论文"},
        headers=_headers(),
    )
    assert doc.status_code == 201

    ver = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc.json()['id']}/versions",
        json={"content_markdown": "# 方法\n多模态表征优于单模态。", "change_summary": "初稿"},
        headers=_headers(),
    )
    assert ver.status_code == 201
    assert len(ver.json()["content_sha256"]) == 64

    # 关联证据主张（用 seed 的 C1 主张节点）
    graph = client.get(
        f"/api/v1/projects/{project_id}/cycles/{cycle_id}/evidence-graph", headers=_headers()
    ).json()
    c1 = next(n for n in graph["nodes"] if n["code"] == "C1")
    claim = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc.json()['id']}/claims",
        json={"evidence_node_id": c1["id"], "support_status": "supports"},
        headers=_headers(),
    )
    assert claim.status_code == 201

    integrity = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc.json()['id']}:integrity-check", headers=_headers()
    ).json()
    assert integrity["passed"] is True
    assert integrity["errors"] == []


def test_citation_and_export(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    doc = client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={"cycle_id": cycle_id, "title": "引用导出测试"},
        headers=_headers(),
    ).json()
    client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/versions",
        json={"content_markdown": "# 引言\n多模态方法见 [ref1]。"},
        headers=_headers(),
    )

    papers = client.get(f"/api/v1/projects/{project_id}/papers", headers=_headers()).json()
    paper = papers[0]
    citation = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/citations",
        json={"paper_id": paper["id"], "citation_key": "ref1"},
        headers=_headers(),
    )
    assert citation.status_code == 201

    exported = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}:export", headers=_headers()
    ).json()
    assert exported["sha256"] and len(exported["sha256"]) == 64
    assert exported["download_url"].startswith("http")
    assert exported["manifest"]["citation_count"] == 1
