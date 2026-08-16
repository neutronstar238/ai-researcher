"""500 节点 / 1,500 边子图性能基准（spec §22.6）。

在隔离项目（slug=benchmark-500）写入 500 证据节点 + 1,500 条 related_to 边，
测量 `/evidence-graph` P50/P95，随后删除该基准项目。真实 API + 真实 DB。
用法：cd backend && .\.venv\Scripts\python.exe scripts/benchmark_graph.py
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx
from sqlalchemy import delete, select

from app.db.models import (
    EvidenceEdge,
    EvidenceNode,
    Project,
    ProjectMember,
    ResearchCycle,
    Team,
    User,
)
from app.db.session import dispose_engine, get_session_factory

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}
BENCH_SLUG = "benchmark-500"


async def seed_benchmark() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as session:
        owner = (
            await session.execute(select(User).where(User.email == OWNER["email"]))
        ).scalar_one()
        team = (await session.execute(select(Team))).scalars().first()
        project_id = uuid.uuid5(uuid.NAMESPACE_URL, "benchmark:500")

        project = Project(
            id=project_id,
            team_id=team.id,
            name="500 节点基准",
            slug=BENCH_SLUG,
            created_by=owner.id,
        )
        session.add(project)
        await session.flush()
        session.add(ProjectMember(project_id=project_id, user_id=owner.id, role="owner"))
        cycle = ResearchCycle(
            project_id=project_id,
            sequence_no=1,
            name="基准周期",
            created_by=owner.id,
        )
        session.add(cycle)
        await session.flush()

        node_ids: list[uuid.UUID] = []
        for i in range(500):
            node_id = uuid.uuid5(uuid.NAMESPACE_URL, f"benchmark:node:{i}")
            node_ids.append(node_id)
            session.add(
                EvidenceNode(
                    id=node_id,
                    project_id=project_id,
                    cycle_id=cycle.id,
                    node_type="evidence",
                    code=f"N{i:03d}",
                    title=f"基准证据节点 {i}",
                    status="active",
                    created_by=owner.id,
                )
            )
        await session.flush()  # 先落库节点，边才能引用
        for i in range(1500):
            session.add(
                EvidenceEdge(
                    project_id=project_id,
                    cycle_id=cycle.id,
                    source_node_id=node_ids[i % 500],
                    target_node_id=node_ids[(i * 7 + 3) % 500],
                    relation="related_to",
                    stance="neutral",
                    created_by=owner.id,
                )
            )
        await session.commit()
    await dispose_engine()
    return str(project_id), str(cycle.id)


async def cleanup(project_id: str) -> None:
    factory = get_session_factory()
    pid = uuid.UUID(project_id)
    async with factory() as session:
        await session.execute(delete(EvidenceEdge).where(EvidenceEdge.project_id == pid))
        await session.execute(delete(EvidenceNode).where(EvidenceNode.project_id == pid))
        await session.execute(delete(ResearchCycle).where(ResearchCycle.project_id == pid))
        await session.execute(delete(ProjectMember).where(ProjectMember.project_id == pid))
        project = await session.get(Project, pid)
        if project is not None:
            await session.delete(project)
        await session.commit()
    await dispose_engine()


def measure_graph(project_id: str, cycle_id: str, n: int) -> dict:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        login = client.post("/api/v1/auth/login", json=OWNER)
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        samples: list[float] = []
        for _ in range(n):
            start = time.perf_counter()
            response = client.get(
                f"/api/v1/projects/{project_id}/cycles/{cycle_id}/evidence-graph",
                headers=headers,
            )
            response.raise_for_status()
            samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {
        "n": n,
        "p50_ms": round(samples[int(len(samples) * 0.5)], 1),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 1),
        "max_ms": round(samples[-1], 1),
    }


async def main() -> int:
    print("seeding 500 nodes / 1500 edges ...")
    project_id, cycle_id = await seed_benchmark()
    try:
        result = measure_graph(project_id, cycle_id, n=20)
        print(
            f"evidence-graph (500 节点/1,500 边) P95={result['p95_ms']}ms "
            f"p50={result['p50_ms']}ms max={result['max_ms']}ms"
        )
        print("PASS (< 1s)" if result["p95_ms"] < 1000 else "FAIL (> 1s)")
    finally:
        print("cleaning up benchmark project ...")
        await cleanup(project_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
