"""平台演示：跑一个真实科研问题（选题→文献检索→证据抽取→写作→PDF 导出）。

科研问题：深度学习能否预测蛋白质-小分子结合亲和力？
前置：后端 8000 + Celery worker。用法：cd backend && .\.venv\Scripts\python.exe scripts/demo_research.py
"""

from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}
QUESTION = "deep learning predict protein-ligand binding affinity"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=180)
    token = c.post("/api/v1/auth/login", json=OWNER).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    teams = c.get("/api/v1/teams", headers=h).json()
    pid = next(p["id"] for p in c.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=h).json() if p["slug"] == "protein-ligand-multimodal")
    cid = c.get(f"/api/v1/projects/{pid}/cycles", headers=h).json()[-1]["id"]

    print(f"=== 科研问题：{QUESTION} ===")

    # 1. 文献检索（异步 202 → 轮询）
    run = c.post(f"/api/v1/projects/{pid}/literature-search-runs", json={"query": QUESTION, "provider": "arxiv", "max_results": 5}, headers=h)
    rid = run.json()["run_id"]
    print(f"[1] 文献检索 Job 已创建：{rid}")
    final = None
    for _ in range(40):
        time.sleep(2)
        final = c.get(f"/api/v1/projects/{pid}/literature-search-runs/{rid}", headers=h).json()
        if final["status"] in {"succeeded", "failed"}:
            break
    papers = final.get("result", {}).get("results", []) if final else []
    print(f"[1] 检索完成：{final['status']}，命中 {len(papers)} 篇")
    for i, p in enumerate(papers[:5]):
        print(f"    {i+1}. {p['title'][:90]} ({p.get('publication_year')})")

    if not papers:
        print("无结果，结束")
        return

    # 2. 保存第一篇论文（若已加入则复用，保证脚本可重复运行）
    p0 = papers[0]
    saved = c.post(f"/api/v1/projects/{pid}/papers", json={"title": p0["title"], "abstract": p0.get("abstract"), "publication_year": p0.get("publication_year"), "source": p0.get("source", "arxiv"), "external_id": p0.get("external_id")}, headers=h)
    if saved.status_code != 201:
        existing_papers = c.get(f"/api/v1/projects/{pid}/papers", headers=h).json()
        paper = next(p for p in existing_papers if p["title"] == p0["title"])
        paper_id = paper["id"]
        print(f"[2] 论文已存在，复用：{paper['title'][:80]}")
    else:
        paper_id = saved.json()["id"]
        print(f"[2] 保存论文：{saved.json()['title'][:80]}")

    # 3. LLM 证据抽取
    ev = c.post(f"/api/v1/projects/{pid}/papers/{paper_id}:extract-evidence", headers=h).json()
    claims = ev.get("nodes", [])
    print(f"[3] 证据抽取：提取 {ev.get('extracted')} 条主张")
    for n in claims:
        print(f"    - [{n['node_type']}] {n['title'][:90]}")

    # 4. 写作：研究笔记 + PDF 导出
    body = "# 研究笔记：深度学习预测蛋白质-小分子结合亲和力\n\n## 摘要\n基于文献检索与证据抽取自动生成。\n\n## 证据主张\n"
    for n in claims:
        body += f"- {n['title']}\n"
    doc = c.post(f"/api/v1/projects/{pid}/documents", json={"cycle_id": cid, "title": f"研究笔记：{QUESTION[:40]}"}, headers=h).json()
    c.post(f"/api/v1/projects/{pid}/documents/{doc['id']}/versions", json={"content_markdown": body}, headers=h)
    export = c.post(f"/api/v1/projects/{pid}/documents/{doc['id']}:export?format=pdf", headers=h)
    print(f"[4] 研究笔记 PDF 导出：{export.status_code}，sha={export.json().get('sha256','')[:12]}")

    print("\n=== 演示完成：选题→文献→证据→写作→PDF 全链路跑通 ===")


if __name__ == "__main__":
    main()
