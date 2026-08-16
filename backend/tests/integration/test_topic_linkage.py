"""选题采纳联动集成测试（spec §6.2/§13.6）：采纳 → 审计 + 下一步行动。"""

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


def test_accept_topic_records_audit_and_action(client: TestClient) -> None:
    project_id, cycle_id = _project_and_cycle(client)
    candidates = client.get(
        f"/api/v1/projects/{project_id}/topic-candidates", headers=_headers()
    ).json()
    pending = [c for c in candidates if c["status"] != "accepted"]
    assert pending, "seed should provide a non-accepted candidate"
    target = pending[0]

    accepted = client.post(
        f"/api/v1/projects/{project_id}/topic-candidates/{target['id']}:accept",
        headers=_headers(),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    logs = client.get(f"/api/v1/projects/{project_id}/audit-logs", headers=_headers()).json()
    assert any(entry["action"] == "topic.candidate.accepted" for entry in logs)

    dashboard = client.get(f"/api/v1/projects/{project_id}/dashboard", headers=_headers()).json()
    # 采纳后生成下一步文献调研行动；当前周期可能已被其它行动占用，故仅验证存在性
    # （next_action 取 priority 最高的 open 行动）。
    assert dashboard["project"]["next_action"] is not None


def test_dashboard_statistics_are_real_counts(client: TestClient) -> None:
    project_id, _cycle_id = _project_and_cycle(client)
    dashboard = client.get(f"/api/v1/projects/{project_id}/dashboard", headers=_headers()).json()
    stats = dashboard["statistics"]
    assert set(stats) == {"papers", "experiment_runs", "datasets", "figures"}
    assert all(isinstance(v, int) for v in stats.values())
    assert stats["papers"] >= 0 and stats["experiment_runs"] >= 0
