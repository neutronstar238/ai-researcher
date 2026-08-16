"""API 性能基线（spec §22.6）。

对运行中的实例做顺序请求，输出各端点的 P50/P95/P99/max。只读、不修改数据。
用法：
    cd backend && .\.venv\Scripts\python.exe -m scripts.benchmark_api
（依赖已在 requirements.txt：httpx）
"""

from __future__ import annotations

import argparse
import statistics
import time

import httpx

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}


def measure(client: httpx.Client, method: str, url: str, *, n: int, headers: dict, body=None) -> dict:
    samples: list[float] = []
    statuses: dict[int, int] = {}
    for _ in range(n):
        start = time.perf_counter()
        response = client.request(method, url, headers=headers, json=body)
        samples.append((time.perf_counter() - start) * 1000)
        statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
    samples.sort()
    p50 = samples[int(len(samples) * 0.5)]
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    p99 = samples[min(len(samples) - 1, int(len(samples) * 0.99))]
    return {
        "n": n,
        "mean_ms": round(statistics.fmean(samples), 1),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "max_ms": round(samples[-1], 1),
        "statuses": statuses,
    }


def run(n: int) -> dict:
    with httpx.Client(base_url=BASE, timeout=30) as client:
        login = client.post("/api/v1/auth/login", json=OWNER)
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        teams = client.get("/api/v1/teams", headers=headers).json()
        team_id = teams[0]["id"]
        projects = client.get(f"/api/v1/projects?team_id={team_id}", headers=headers).json()
        project_id = next(p["id"] for p in projects if p["slug"] == "protein-ligand-multimodal")
        cycles = client.get(f"/api/v1/projects/{project_id}/cycles", headers=headers).json()
        cycle_id = cycles[-1]["id"]

        results = {
            "dashboard": measure(
                client, "GET", f"/api/v1/projects/{project_id}/dashboard", n=n, headers=headers
            ),
            "projects_list": measure(
                client, "GET", f"/api/v1/projects?team_id={team_id}", n=n, headers=headers
            ),
            "evidence_graph": measure(
                client,
                "GET",
                f"/api/v1/projects/{project_id}/cycles/{cycle_id}/evidence-graph",
                n=n,
                headers=headers,
            ),
            "topic_candidates": measure(
                client, "GET", f"/api/v1/projects/{project_id}/topic-candidates", n=n, headers=headers
            ),
        }
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Researcher API 性能基线")
    parser.add_argument("--n", type=int, default=30, help="每个端点的请求次数（默认 30）")
    args = parser.parse_args()

    results = run(args.n)
    print(f"API 性能基线（每端点 {args.n} 次顺序请求，单位 ms）：")
    for name, metrics in results.items():
        print(
            f"  {name:16s} p50={metrics['p50_ms']:>7} p95={metrics['p95_ms']:>7} "
            f"p99={metrics['p99_ms']:>7} max={metrics['max_ms']:>7} mean={metrics['mean_ms']:>7} "
            f"status={metrics['statuses']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
