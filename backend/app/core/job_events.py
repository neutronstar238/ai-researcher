"""Job 状态事件发布（spec §13.x/§22.6 WebSocket Job 进度）。

通过 Redis pub/sub 桥接「Celery worker / API 进程」→「API 的 WebSocket 订阅者」。
频道：``project:{project_id}:jobs``。消息为 JSON（含 type/status/...）。
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings


def channel_for(project_id: str) -> str:
    return f"project:{project_id}:jobs"


async def publish_job_event(project_id: str, event: dict[str, Any]) -> None:
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        await client.publish(
            channel_for(project_id), json.dumps(event, ensure_ascii=False, default=str)
        )
    finally:
        await client.aclose()
