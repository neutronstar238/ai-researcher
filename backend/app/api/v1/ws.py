"""WebSocket Job 状态推送（spec §13.x/§22.6）。

客户端连 ``/api/v1/ws/projects/{project_id}/jobs`` 后持续收到该项目的 Job 状态事件
（由 Redis pub/sub 桥接）；断线后前端退避重连并用 REST 补齐（§13.5）。
"""

from __future__ import annotations

import uuid

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.job_events import channel_for

router = APIRouter(tags=["ws"])


@router.websocket("/ws/projects/{project_id}/jobs")
async def jobs_ws(websocket: WebSocket, project_id: uuid.UUID) -> None:
    await websocket.accept()
    client = redis.Redis.from_url(get_settings().redis_url)
    pubsub = client.pubsub()
    channel = channel_for(str(project_id))
    await pubsub.subscribe(channel)
    try:
        await websocket.send_text('{"type":"connected"}')
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            try:
                await websocket.send_text(message["data"].decode())
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await client.aclose()
