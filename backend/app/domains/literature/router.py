"""Literature API routes (spec §13.6)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.literature.schemas import (
    IngestPdfRequest,
    PaperOut,
    SavePaperRequest,
    SearchRequest,
    SearchRunOut,
)
from app.domains.literature.service import LiteratureService

router = APIRouter(tags=["literature"])

require_view = require_project_role("view")
require_edit = require_project_role("edit_content")


@router.post("/projects/{project_id}/literature-search-runs", status_code=202)
async def create_search_run(
    project_id: uuid.UUID,
    payload: SearchRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_view),
) -> dict:
    """外部文献检索异步化（spec §3.3）：202 + Job；由 Celery `literature.search` 消费。"""
    run = await LiteratureService(session).create_run(
        project_id, payload.query, payload.provider, payload.max_results, user.id
    )
    from app.workers.tasks import literature_search_task

    # 在独立线程里 publish，避免 kombu 与异步事件循环在 Windows 的交互问题（spec §3.3）
    await asyncio.to_thread(literature_search_task.delay, str(run.id))
    return {"run_id": str(run.id), "status": run.status}


@router.get("/projects/{project_id}/literature-search-runs", response_model=list[SearchRunOut])
async def list_search_runs(
    project_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[SearchRunOut]:
    runs = await LiteratureService(session).list_runs(project_id)
    return [SearchRunOut.model_validate(r, from_attributes=True) for r in runs]


@router.get("/projects/{project_id}/literature-search-runs/{run_id}", response_model=SearchRunOut)
async def get_search_run(
    project_id: uuid.UUID, run_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> SearchRunOut:
    run = await LiteratureService(session).get_run(run_id)
    return SearchRunOut.model_validate(run, from_attributes=True)


@router.get("/projects/{project_id}/papers", response_model=list[PaperOut])
async def list_papers(
    project_id: uuid.UUID,
    session: SessionDep,
    _user: User = Depends(require_view),
) -> list[PaperOut]:
    papers = await LiteratureService(session).list_papers(project_id)
    return [PaperOut.model_validate(p, from_attributes=True) for p in papers]


@router.post("/projects/{project_id}/papers", response_model=PaperOut, status_code=201)
async def save_paper(
    project_id: uuid.UUID,
    payload: SavePaperRequest,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> PaperOut:
    paper = await LiteratureService(session).save_paper(project_id, payload, user.id)
    return PaperOut.model_validate(paper, from_attributes=True)


@router.post("/projects/{project_id}/papers/{paper_id}:ingest-pdf")
async def ingest_pdf(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    payload: IngestPdfRequest,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    """解析 PDF 资产 → 分块 → 哈希嵌入 → PG `paper_chunks` + Milvus（§13.x）。"""
    return await LiteratureService(session).ingest_pdf(project_id, paper_id, payload.asset_id)


@router.post("/projects/{project_id}/papers/{paper_id}:extract-evidence")
async def extract_evidence(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_edit),
) -> dict:
    """LLM 抽取主张 → 证据节点（§13.x 自动证据抽取）。"""
    return await LiteratureService(session).extract_evidence(project_id, paper_id, user.id)
