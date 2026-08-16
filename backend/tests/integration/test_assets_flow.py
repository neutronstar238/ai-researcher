"""Asset upload/download integration tests against live MinIO (spec §24 Phase 3)."""

from __future__ import annotations

import hashlib

import httpx
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


def test_asset_upload_download_flow(client: TestClient) -> None:
    project_id = _project_id(client)

    init = client.post(
        f"/api/v1/projects/{project_id}/assets/uploads:initiate",
        json={"original_name": "test.txt", "mime_type": "text/plain", "kind": "other"},
        headers=_headers(),
    )
    assert init.status_code == 200, init.text
    body = init.json()

    content = b"hello ai-researcher, sha256 verified server-side"
    put = httpx.put(body["upload_url"], content=content, timeout=30)
    assert put.status_code == 200, put.text

    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/uploads/{body['upload_id']}:complete",
        json={"original_name": "test.txt", "mime_type": "text/plain", "kind": "other"},
        headers=_headers(),
    )
    assert complete.status_code == 201, complete.text
    asset = complete.json()
    assert asset["size_bytes"] == len(content)
    assert asset["sha256"] == hashlib.sha256(content).hexdigest()

    assets = client.get(f"/api/v1/projects/{project_id}/assets", headers=_headers()).json()
    assert any(a["id"] == asset["id"] for a in assets)

    download = client.get(
        f"/api/v1/projects/{project_id}/assets/{asset['id']}/download-url", headers=_headers()
    ).json()
    assert download["download_url"].startswith("http")


def test_multipart_upload_flow(client: TestClient) -> None:
    """分片上传（spec §9.7）：initiate(part_count>1) → 每片直传 → complete(etags)。"""
    project_id = _project_id(client)

    init = client.post(
        f"/api/v1/projects/{project_id}/assets/uploads:initiate",
        json={"original_name": "big.bin", "mime_type": "application/octet-stream", "kind": "dataset", "part_count": 2},
        headers=_headers(),
    )
    assert init.status_code == 200, init.text
    body = init.json()
    assert body["mode"] == "multipart"
    assert len(body["upload_urls"]) == 2

    part_a = b"A" * (6 * 1024 * 1024)  # 除最后一片外，每片须 ≥ 5 MiB（S3 约束）
    part_b = b"B" * 1000
    etags: list[dict] = []
    for index, chunk in enumerate((part_a, part_b), start=1):
        put = httpx.put(body["upload_urls"][index - 1], content=chunk, timeout=60)
        assert put.status_code == 200, put.text
        etags.append({"part_number": index, "etag": put.headers["ETag"].strip('"')})

    complete = client.post(
        f"/api/v1/projects/{project_id}/assets/uploads/{body['upload_id']}:complete",
        json={
            "original_name": "big.bin",
            "mime_type": "application/octet-stream",
            "kind": "dataset",
            "object_key": body["object_key"],
            "parts": etags,
        },
        headers=_headers(),
    )
    assert complete.status_code == 201, complete.text
    asset = complete.json()
    assert asset["size_bytes"] == len(part_a) + len(part_b)
    assert asset["sha256"] == hashlib.sha256(part_a + part_b).hexdigest()
