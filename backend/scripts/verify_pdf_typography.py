"""PDF 排版升级验证：中文 + 数学公式 + 表格。"""

from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:8000"
OWNER = {"email": "owner@airesearcher.local", "password": "demo-password"}

MARKDOWN = r"""# 多模态表征学习研究计划

## 摘要

误差目标 $\mathcal{L} = \sum_{i=1}^{N}(y_i - \hat{y}_i)^2$，节点特征 $x_v \in \mathbb{R}^{d}$，多模态 AUROC $\approx 0.92$。

## 方法对比

| 方法 | 维度 | AUROC |
|------|------|-------|
| 分子指纹 | 1024 | 0.82 |
| 图神经网络 | 300 | 0.87 |
| 多模态融合 | 1024 | 0.92 |

## 结论

多模态表征显著优于单模态（$p < 0.05$），数学符号 $\pi \sum \int \approx \in \mathbb{R}$ 渲染正常。
"""


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=300) as c:
        token = c.post("/api/v1/auth/login", json=OWNER).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        teams = c.get("/api/v1/teams", headers=h).json()
        pid = next(p["id"] for p in c.get(f"/api/v1/projects?team_id={teams[0]['id']}", headers=h).json() if p["slug"] == "protein-ligand-multimodal")
        cid = c.get(f"/api/v1/projects/{pid}/cycles", headers=h).json()[-1]["id"]

        doc = c.post(f"/api/v1/projects/{pid}/documents", json={"cycle_id": cid, "title": "排版升级验证"}, headers=h).json()
        c.post(f"/api/v1/projects/{pid}/documents/{doc['id']}/versions", json={"content_markdown": MARKDOWN}, headers=h)
        r = c.post(f"/api/v1/projects/{pid}/documents/{doc['id']}:export?format=pdf", headers=h)
        print("PDF export status:", r.status_code)
        if r.status_code == 200:
            body = r.json()
            print("sha256:", body["sha256"][:12], "url_ok:", body["download_url"].startswith("http"))
        else:
            print("body:", r.text[:400])


if __name__ == "__main__":
    main()
