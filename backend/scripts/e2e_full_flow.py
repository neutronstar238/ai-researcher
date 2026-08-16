"""全流程 E2E 冒烟（spec §22.2）：逐条走主功能链路，打印每步 PASS/FAIL。

覆盖：登录(cookie) → 项目/周期 → 生命周期 → Dashboard → 选题采纳→阶段完成 →
文献异步检索 → 论文入库 → 实验运行 → Agent(LLM) → 写作+导出 → 资产上传下载 →
证据抽取(LLM) → 审计。任一步失败不中断（记录后继续）。

前置：后端 8000 + Celery worker 运行。用法：
  cd backend && .\.venv\Scripts\python.exe scripts/e2e_full_flow.py
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120)
    # 1. 登录 + 会话
    login = client.post("/api/v1/auth/login", json=OWNER)
    check("登录", login.status_code == 200)
    token = login.json().get("access_token", "")
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    check("鉴权 /me", me.status_code == 200 and me.json().get("email") == OWNER["email"])

    # 2. 团队/项目/周期
    teams = client.get("/api/v1/teams", headers=headers).json()
    pid = next(p["id"] for p in client.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=headers).json() if p["slug"] == "protein-ligand-multimodal")
    check("项目解析", bool(pid))
    cycles = client.get(f"/api/v1/projects/{pid}/cycles", headers=headers).json()
    check("周期列表", len(cycles) >= 1)

    # 3. 生命周期
    life = client.get(f"/api/v1/projects/{pid}/cycles/{cycles[-1]['id']}/lifecycle", headers=headers)
    check("生命周期 8 阶段", life.status_code == 200 and len(life.json()) == 8)

    # 4. Dashboard（真实统计）
    dash = client.get(f"/api/v1/projects/{pid}/dashboard", headers=headers).json()
    check("Dashboard 统计", set(dash["statistics"]) == {"papers", "experiment_runs", "datasets", "figures"})

    # 5. 选题采纳 → 阶段完成（用新周期）
    cycle = client.post(f"/api/v1/projects/{pid}/cycles", json={"name": "全流程冒烟周期"}, headers=headers).json()
    cid = cycle["id"]
    # 直插候选
    from app.db.models import TopicCandidate
    from app.db.session import dispose_engine, get_session_factory

    async def insert_candidate():
        f = get_session_factory()
        cand_id = uuid.uuid5(uuid.NAMESPACE_URL, f"e2e:cand:{cid}")
        async with f() as s:
            s.add(TopicCandidate(id=cand_id, project_id=uuid.UUID(pid), cycle_id=uuid.UUID(cid), title="全流程冒烟选题", evidence_strength=88, status="exploring"))
            await s.commit()
        await dispose_engine()
        return str(cand_id)

    cand_id = asyncio.run(insert_candidate())
    acc = client.post(f"/api/v1/projects/{pid}/topic-candidates/{cand_id}:accept", headers=headers)
    check("选题采纳", acc.status_code == 200)
    life2 = client.get(f"/api/v1/projects/{pid}/cycles/{cid}/lifecycle", headers=headers).json()
    topic_stage = next(s for s in life2 if s["stage_key"] == "topic")
    check("采纳→topic 阶段完成", topic_stage["status"] == "completed", topic_stage["status"])

    # 6. 文献异步检索（202 + 轮询）
    run = client.post(f"/api/v1/projects/{pid}/literature-search-runs", json={"query": "protein docking", "provider": "arxiv", "max_results": 3}, headers=headers)
    check("文献检索 202", run.status_code == 202)
    rid = run.json()["run_id"]
    final = None
    for _ in range(30):
        time.sleep(2)
        final = client.get(f"/api/v1/projects/{pid}/literature-search-runs/{rid}", headers=headers).json()
        if final["status"] in {"succeeded", "failed"}:
            break
    check("文献检索完成", final is not None and final["status"] == "succeeded", final["status"] if final else "?")

    # 7. 实验运行（本地子进程）
    exp = client.post(f"/api/v1/projects/{pid}/experiments", json={"cycle_id": cid, "code": "E2E", "name": "全流程实验", "entrypoint": 'python -c "print(42)"'}, headers=headers).json()
    erun = client.post(f"/api/v1/projects/{pid}/experiments/{exp['id']}/runs", json={}, headers=headers)
    check("实验运行", erun.status_code in (200, 201) and erun.json().get("status") == "succeeded", erun.json().get("status", "?"))

    # 8. Agent（真实 LLM）
    agents = client.get(f"/api/v1/projects/{pid}/agents?team_id={teams[0]['id']}", headers=headers).json()
    agent = agents[0]
    task = client.post(f"/api/v1/projects/{pid}/agent-tasks", json={"agent_version_id": agent["active_version_id"], "task_type": "literature_review", "input": {"topic": "protein-ligand"}}, headers=headers).json()
    arun = client.post(f"/api/v1/projects/{pid}/agent-tasks/{task['id']}:run", headers=headers)
    check("Agent(LLM) 执行", arun.status_code == 200 and arun.json().get("status") in {"succeeded", "waiting_approval"}, arun.json().get("status", "?"))

    # 9. 写作 + 导出
    doc = client.post(f"/api/v1/projects/{pid}/documents", json={"cycle_id": cid, "title": "全流程文档"}, headers=headers).json()
    ver = client.post(f"/api/v1/projects/{pid}/documents/{doc['id']}/versions", json={"content_markdown": "# 方法\n全流程验证。"}, headers=headers)
    check("写作版本", ver.status_code == 201)
    export = client.post(f"/api/v1/projects/{pid}/documents/{doc['id']}:export?format=pdf", headers=headers)
    check("PDF 导出", export.status_code == 200 and export.json().get("download_url", "").startswith("http"))

    # 10. 资产上传 + 下载
    init = client.post(f"/api/v1/projects/{pid}/assets/uploads:initiate", json={"original_name": "e2e.txt", "mime_type": "text/plain", "kind": "other"}, headers=headers).json()
    httpx.put(init["upload_url"], content=b"e2e flow asset")
    comp = client.post(f"/api/v1/projects/{pid}/assets/uploads/{init['upload_id']}:complete", json={"original_name": "e2e.txt", "mime_type": "text/plain", "kind": "other"}, headers=headers)
    check("资产上传(含扫描)", comp.status_code == 201 and comp.json().get("scan_status") in {"clean", "not_scanned", "scan_error"}, comp.json().get("scan_status", "?"))

    # 11. 证据抽取（LLM）
    paper_title = f"E2E Evidence Paper {uuid.uuid4().hex[:6]}"
    paper = client.post(f"/api/v1/projects/{pid}/papers", json={"title": paper_title, "abstract": "Graph neural networks improve molecular property prediction over fingerprints.", "source": "manual"}, headers=headers).json()
    ev = client.post(f"/api/v1/projects/{pid}/papers/{paper['id']}:extract-evidence", headers=headers)
    check("证据抽取(LLM)", ev.status_code == 200 and ev.json().get("extracted", 0) >= 1, f"extracted={ev.json().get('extracted')}")

    # 12. 审计日志
    logs = client.get(f"/api/v1/projects/{pid}/audit-logs", headers=headers)
    check("审计日志可查", logs.status_code == 200 and isinstance(logs.json(), list))

    # 清理冒烟周期
    asyncio.run(_cleanup(cid))

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n全流程结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


async def _cleanup(cycle_id: str) -> None:
    from sqlalchemy import delete

    from app.db.models import EvidenceEdge, EvidenceNode, ResearchCycle, TopicCandidate
    from app.db.session import dispose_engine, get_session_factory

    f = get_session_factory()
    cid = uuid.UUID(cycle_id)
    async with f() as s:
        await s.execute(delete(TopicCandidate).where(TopicCandidate.cycle_id == cid))
        await s.execute(delete(EvidenceEdge).where(EvidenceEdge.cycle_id == cid))
        await s.execute(delete(EvidenceNode).where(EvidenceNode.cycle_id == cid))
        cycle = await s.get(ResearchCycle, cid)
        if cycle is not None:
            await s.delete(cycle)
        await s.commit()
    await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
