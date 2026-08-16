"""Rate limiting (spec §19.3): fixed-window limiter backed by Redis.

登录、密码重置、搜索 Provider、Agent 启动、签名 URL 端点分别限流。
每次调用建立独立短连接，避免跨请求连接池与事件循环绑定问题。
"""

from __future__ import annotations

import time

from redis.asyncio import Redis

from app.core.config import get_settings


class RateLimiter:
    def __init__(self, window_seconds: int = 60) -> None:
        self.window = window_seconds

    async def allow(self, key: str, limit: int) -> bool:
        """固定窗口限流；返回是否放行。Redis 不可用时降级放行（开发不锁死）。"""
        bucket = int(time.time()) // self.window
        redis_key = f"ratelimit:{key}:{bucket}"
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            current = await client.incr(redis_key)
            if current == 1:
                await client.expire(redis_key, self.window)
            return current <= limit
        except Exception:  # noqa: BLE001 - Redis 不可用时不锁死本地开发
            return True
        finally:
            await client.aclose()
