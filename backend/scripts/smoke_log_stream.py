"""实验运行实时日志流直播冒烟（§15）。

流程：连 WS → 创建多行延迟输出实验 → 触发运行 → 收 log 事件。
前置：后端 8000 运行。用法：cd backend && .\.venv\Scripts\python.exe scripts/smoke_log_stream.py
"""

from __future__ import annotations

import asyncio
import json

import httpx
import websockets

BASE = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}

ENTRYPOINT = (
    'python -c "import time; '
    "print('line1'); time.sleep(1); "
    "print('line2'); time.sleep(1); "
    "print('line3')\""
)


async def main() -> int:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        token = client.post("/api/v1/auth/login", json=OWNER).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        teams = client.get("/api/v1/teams", headers=headers).json()
        projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=headers).json()
        pid = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
        cycles = client.get(f"/api/v1/projects/{pid}/cycles", headers=headers).json()
        cid = cycles[-1]["id"]
        exp = client.post(
            f"/api/v1/projects/{pid}/experiments",
            json={"cycle_id": cid, "code": "STREAM", "name": "日志流冒烟", "entrypoint": ENTRYPOINT},
            headers=headers,
        ).json()

    async with websockets.connect(f"{WS}/api/v1/ws/projects/{pid}/jobs") as ws:
        await asyncio.wait_for(ws.recv(), timeout=5)  # connected

        async with httpx.AsyncClient(base_url=BASE, timeout=120) as ac:
            await ac.post(
                f"/api/v1/projects/{pid}/experiments/{exp['id']}/runs",
                json={},
                headers={"Authorization": f"Bearer {token}"},
            )

        logs: list[str] = []
        for _ in range(12):
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=3)
            except TimeoutError:
                break
            event = json.loads(frame)
            if event.get("type") == "log":
                logs.append(event.get("line", "").strip())

    print("streamed log lines:", logs)
    return 0 if len(logs) >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
