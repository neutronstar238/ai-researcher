"""文献异步检索直播冒烟（spec §13.6/§3.3）。

前置：后端 8000 运行 + Celery worker 运行（`celery -A app.workers.celery_app worker`）。
创建 search-run → 轮询直到 succeeded → 打印命中数。
用法：cd backend && .\.venv\Scripts\python.exe scripts/smoke_literature_async.py
"""

from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        login = client.post("/api/v1/auth/login", json=OWNER)
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        teams = client.get("/api/v1/teams", headers=headers).json()
        projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=headers).json()
        project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")

        created = client.post(
            f"/api/v1/projects/{project_id}/literature-search-runs",
            json={"query": "protein-ligand docking deep learning", "provider": "arxiv", "max_results": 5},
            headers=headers,
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        print(f"run_id={run_id} status={created.json()['status']}")

        for _ in range(30):
            time.sleep(2)
            run = client.get(
                f"/api/v1/projects/{project_id}/literature-search-runs/{run_id}", headers=headers
            ).json()
            if run["status"] in {"succeeded", "failed"}:
                break
        print(f"final status={run['status']}")
        if run["status"] == "succeeded":
            print(f"命中数={run['result']['count']}")
            for r in run["result"]["results"][:3]:
                print(f"  - {r['title'][:80]}")
        else:
            print(f"error={run.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
