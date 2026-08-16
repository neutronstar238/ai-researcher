"""Celery application (spec §10.4)."""

from __future__ import annotations

import os

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "airesearcher",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["app.workers.tasks"],
)

# 测试/开发可用 eager 模式同步执行；生产由真实 worker 消费。
celery_app.conf.task_always_eager = os.environ.get("CELERY_TASK_ALWAYS_EAGER") == "1"
celery_app.conf.task_eager_propagates = True
celery_app.conf.task_track_started = True
celery_app.conf.task_acks_late = True

celery_app.conf.task_routes = {
    "experiment.run": {"queue": "experiment"},
    "outbox.dispatch": {"queue": "default"},
    "literature.search": {"queue": "default"},
}

# 周期投影（spec §3.4）：定时把 outbox_events 消费到 Neo4j。间隔可用环境变量覆盖，
# 便于测试缩短周期；生产默认 30s。
_outbox_interval = float(os.environ.get("OUTBOX_DISPATCH_INTERVAL", "30"))
celery_app.conf.beat_schedule = {
    "outbox-dispatch": {"task": "outbox.dispatch", "schedule": _outbox_interval},
}
