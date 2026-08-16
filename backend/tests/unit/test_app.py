"""Application wiring and contract tests (no database required)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_app_builds_and_serves_liveness() -> None:
    app = create_app()
    client = TestClient(app)
    with client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_openapi_exposes_phase1_routes() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/teams",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}/cycles",
        "/api/v1/system/health/summary",
    ):
        assert path in paths, f"missing route: {path}"


def test_unauthenticated_me_returns_401() -> None:
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"


def test_security_headers_present() -> None:
    app = create_app()
    client = TestClient(app)
    with client:
        response = client.get("/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
