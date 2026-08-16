"""Celery tasks: experiment runs and outbox dispatch (spec §10.4)."""

from __future__ import annotations

import asyncio
import uuid

from app.workers.celery_app import celery_app


async def _execute_run(run_id: str) -> None:
    from app.db.session import dispose_engine, get_session_factory
    from app.domains.experiments.service import ExperimentService

    try:
        factory = get_session_factory()
        async with factory() as session:
            await ExperimentService(session)._execute(uuid.UUID(run_id))
    finally:
        await dispose_engine()


@celery_app.task(name="experiment.run", bind=True, max_retries=3, default_retry_delay=5)
def run_experiment_task(self, run_id: str) -> None:
    try:
        asyncio.run(_execute_run(run_id))
    except Exception as exc:  # noqa: BLE001 - Celery 重试约定
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc
        raise


async def _execute_literature_search(run_id: str) -> None:
    from app.db.session import dispose_engine, get_session_factory
    from app.domains.literature.service import LiteratureService

    try:
        factory = get_session_factory()
        async with factory() as session:
            await LiteratureService(session).execute_run(uuid.UUID(run_id))
    finally:
        await dispose_engine()


@celery_app.task(name="literature.search", bind=True, max_retries=2, default_retry_delay=5)
def literature_search_task(self, run_id: str) -> None:
    try:
        asyncio.run(_execute_literature_search(run_id))
    except Exception as exc:  # noqa: BLE001 - Celery 重试约定
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc
        raise


async def _dispatch_outbox() -> int:
    from app.db.session import dispose_engine
    from app.workers.dispatcher import dispatch_pending

    try:
        return await dispatch_pending()
    finally:
        await dispose_engine()


@celery_app.task(name="outbox.dispatch")
def dispatch_outbox_task() -> int:
    return asyncio.run(_dispatch_outbox())
