"""选题采纳→topic 阶段自动完成 直播冒烟（spec §6.2）。

流程：建新周期（topic=ready）→ 直插候选 → 采纳 → 校验 topic 阶段 completed → 清理。
前置：后端 8000 运行。用法：cd backend && .\.venv\Scripts\python.exe scripts/smoke_topic_linkage.py
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from sqlalchemy import delete

from app.db.models import LifecycleStage, ResearchCycle, TopicCandidate
from app.db.session import dispose_engine, get_session_factory

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}


def insert_candidate(cycle_id: str, project_id: str, owner_id: str) -> str:
    async def run():
        factory = get_session_factory()
        cid = uuid.uuid5(uuid.NAMESPACE_URL, f"smoke:candidate:{cycle_id}")
        async with factory() as session:
            session.add(
                TopicCandidate(
                    id=cid,
                    project_id=uuid.UUID(project_id),
                    cycle_id=uuid.UUID(cycle_id),
                    title="冒烟选题：自动推进 topic 阶段",
                    evidence_strength=90,
                    status="exploring",
                )
            )
            await session.commit()
        await dispose_engine()
        return str(cid)

    return asyncio.run(run())


def cleanup(cycle_id: str) -> None:
    async def run():
        factory = get_session_factory()
        cid = uuid.UUID(cycle_id)
        async with factory() as session:
            await session.execute(delete(TopicCandidate).where(TopicCandidate.cycle_id == cid))
            await session.execute(delete(LifecycleStage).where(LifecycleStage.cycle_id == cid))
            cycle = await session.get(ResearchCycle, cid)
            if cycle is not None:
                await session.delete(cycle)
            await session.commit()
        await dispose_engine()

    asyncio.run(run())


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        login = client.post("/api/v1/auth/login", json=OWNER)
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/v1/auth/me", headers=headers).json()

        teams = client.get("/api/v1/teams", headers=headers).json()
        projects = client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=headers).json()
        project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")

        cycle = client.post(
            f"/api/v1/projects/{project_id}/cycles",
            json={"name": "冒烟周期-选题联动"},
            headers=headers,
        ).json()
        cycle_id = cycle["id"]

        candidate_id = insert_candidate(cycle_id, project_id, me["id"])

        accepted = client.post(
            f"/api/v1/projects/{project_id}/topic-candidates/{candidate_id}:accept",
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text

        lifecycle = client.get(
            f"/api/v1/projects/{project_id}/cycles/{cycle_id}/lifecycle", headers=headers
        ).json()
        topic = next(s for s in lifecycle if s["stage_key"] == "topic")
        print(f"topic stage status after accept: {topic['status']}")
        print("PASS" if topic["status"] == "completed" else "FAIL")

        cleanup(cycle_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
