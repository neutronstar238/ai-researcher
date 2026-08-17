"""通过真实 API 走一遍多文献源检索（异步 Job），验证 provider 选择与门控。"""

from __future__ import annotations

import time
from collections import Counter

import httpx

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}


def run(c: httpx.Client, h: dict, pid: str, provider: str, query: str, max_results: int = 6) -> dict:
    created = c.post(
        f"/api/v1/projects/{pid}/literature-search-runs",
        json={"query": query, "provider": provider, "max_results": max_results},
        headers=h,
    )
    assert created.status_code == 202, created.text
    rid = created.json()["run_id"]
    final = None
    for _ in range(60):
        time.sleep(2)
        final = c.get(f"/api/v1/projects/{pid}/literature-search-runs/{rid}", headers=h).json()
        if final["status"] in {"succeeded", "failed"}:
            break
    return final


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=120)
    token = c.post("/api/v1/auth/login", json=OWNER).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    teams = c.get("/api/v1/teams", headers=h).json()
    pid = next(
        p["id"]
        for p in c.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=h).json()
        if p["slug"] == "protein-ligand-multimodal"
    )

    for provider, query in [
        ("all", "protein ligand binding affinity"),
        ("pubmed", "protein ligand binding affinity"),   # 医药 → 应命中
        ("pubmed", "quantum error correction codes"),    # 非医药 → 应空 + note
    ]:
        final = run(c, h, pid, provider, query)
        results = (final.get("result") or {}).get("results", [])
        sources = Counter(r["source"] for r in results)
        note = (final.get("result") or {}).get("note")
        print(f"[provider={provider:<8}] status={final['status']} count={len(results)} sources={dict(sources)}")
        if note:
            print(f"    note={note}")
        for r in results[:3]:
            print(f"    - [{r['source']}] {r['title'][:70]}")


if __name__ == "__main__":
    main()
