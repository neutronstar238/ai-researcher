"""Document-suggestion (Agent Diff) integration tests (spec §17.4)."""

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


def test_suggestion_lifecycle(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    doc = client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={"cycle_id": cycle_id, "title": "建议生命周期测试"},
        headers=_headers(),
    ).json()
    base = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/versions",
        json={"content_markdown": "# 结论\n旧结论"},
        headers=_headers(),
    ).json()

    # 生成建议（Agent Diff：提案新增一行）
    suggestion = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}:suggestions",
        json={
            "base_version_id": base["id"],
            "proposed_markdown": "# 结论\n旧结论\n新结论",
            "target_section_key": "conclusion",
        },
        headers=_headers(),
    )
    assert suggestion.status_code == 201
    body = suggestion.json()
    assert body["status"] == "pending"
    assert body["patch"]["additions"] == 1
    assert "+新结论" in (body["rendered_preview"] or "")

    # 接受 → 创建新版本，不覆盖基准版本
    accepted = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/suggestions/{body['id']}:accept",
        headers=_headers(),
    )
    assert accepted.status_code == 200
    assert accepted.json()["version_no"] == 2

    versions = client.get(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/versions", headers=_headers()
    ).json()
    assert [v["version_no"] for v in versions] == [2, 1]

    listing = client.get(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/suggestions", headers=_headers()
    ).json()
    assert listing[0]["status"] == "accepted"


def test_reject_suggestion(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    doc = client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={"cycle_id": cycle_id, "title": "建议拒绝测试"},
        headers=_headers(),
    ).json()
    base = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/versions",
        json={"content_markdown": "原内容"},
        headers=_headers(),
    ).json()
    suggestion = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}:suggestions",
        json={"base_version_id": base["id"], "proposed_markdown": "被拒绝的改动"},
        headers=_headers(),
    ).json()
    rejected = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/suggestions/{suggestion['id']}:reject",
        headers=_headers(),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    # 拒绝后不可再次决定
    again = client.post(
        f"/api/v1/projects/{project_id}/documents/{doc['id']}/suggestions/{suggestion['id']}:accept",
        headers=_headers(),
    )
    assert again.status_code == 409
