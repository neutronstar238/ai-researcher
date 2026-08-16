"""WebSocket Job 状态推送直播冒烟（spec §13.x/§22.6）。

流程：登录 → 连 WS → 触发文献检索 Job → 收 running/succeeded 事件 → 打印。
前置：后端 8000 + Celery worker 运行。用法：cd backend && .\.venv\Scripts\python.exe scripts/smoke_ws_jobs.py
"""

from __future__ import annotations

import asyncio
import json

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}


async def main() -> int:
    # 用 httpx 登录拿 project_id
    with httpx.Client(base_url=BASE, timeout=60) as client:
        login = client.post("/api/v1/auth/login", json=OWNER)
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        teams = client.get("/api/v1/teams", headers=headers).json()
        projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=headers).json()
        project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")

    events: list[dict] = []
    async with websockets.connect(f"{WS_BASE}/api/v1/ws/projects/{project_id}/jobs") as ws:
        first = await asyncio.wait_for(ws.recv(), timeout=5)
        print("first frame:", first)

        # 触发一个文献检索 Job
        async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
            login = await client.post("/api/v1/auth/login", json=OWNER)
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            created = await client.post(
                f"/api/v1/projects/{project_id}/literature-search-runs",
                json={"query": "graph neural network protein", "provider": "arxiv", "max_results": 3},
                headers=headers,
            )
            print("created run status:", created.status_code)

        # 收事件，直到收到 succeeded/failed（最多 60s）
        for _ in range(30):
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=2)
            except TimeoutError:
                continue
            event = json.loads(frame)
            if event.get("type") == "job" and event.get("kind") == "literature_search":
                events.append(event)
                print("event:", event["status"])
                if event["status"] in {"succeeded", "failed"}:
                    break

    print("collected:", [e["status"] for e in events])
    return 0 if any(e["status"] == "succeeded" for e in events) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
