"""DashScope embedding 端点冒烟测试。"""

from __future__ import annotations

import httpx

from app.core.config import get_settings


def main() -> None:
    s = get_settings()
    response = httpx.post(
        f"{s.llm_base_url}/embeddings",
        json={"model": "text-embedding-v3", "input": "hello world"},
        headers={"Authorization": f"Bearer {s.llm_api_key}"},
        timeout=60,
    )
    print("status", response.status_code)
    if response.status_code == 200:
        embedding = response.json()["data"][0]["embedding"]
        print("dim", len(embedding))
    else:
        print(response.text[:300])


if __name__ == "__main__":
    main()
