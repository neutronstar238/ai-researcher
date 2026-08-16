"""Agent memory: write/retrieve with Milvus embedding (spec §16.6/§11.10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.api.errors import NotFoundError
from app.core.config import get_settings
from app.db.models import AgentMemory, User
from app.domains.agents.schemas import MemoryWrite
from app.integrations.embeddings.hash import get_provider
from app.integrations.vector_store.agent_memories import AgentMemoryVectorStore

router = APIRouter(tags=["agent-memories"])
require_view = require_project_role("view")
require_launch = require_project_role("launch_agent")


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.store = AgentMemoryVectorStore()
        self.store.ensure_collection()

    def _embed(self, text: str):
        provider = get_provider(get_settings().embedding_provider)
        return provider.embed(text), provider

    async def write(
        self, project_id: uuid.UUID, payload, requested_by: uuid.UUID
    ) -> AgentMemory:
        memory = AgentMemory(
            project_id=project_id,
            agent_id=payload.agent_id,
            scope=payload.scope,
            content=payload.content,
            summary=payload.summary,
            source_refs=payload.source_refs,
            importance=payload.importance,
        )
        self.session.add(memory)
        await self.session.flush()
        vector, provider = self._embed(payload.content)
        self.store.insert(str(memory.id), str(project_id), str(payload.agent_id), vector, provider.name)
        memory.embedding_ref = str(memory.id)
        await self.session.commit()
        return memory

    async def list(self, project_id: uuid.UUID, agent_id: uuid.UUID | None) -> list[AgentMemory]:
        query = select(AgentMemory).where(AgentMemory.project_id == project_id)
        if agent_id is not None:
            query = query.where(AgentMemory.agent_id == agent_id)
        result = await self.session.execute(query.order_by(AgentMemory.created_at.desc()))
        return list(result.scalars().all())

    async def search(self, project_id: uuid.UUID, agent_id: uuid.UUID, query: str, top_k: int) -> list[dict]:
        vector, _ = self._embed(query)
        hits = self.store.search(vector, str(project_id), str(agent_id), top_k)
        memories = []
        for hit in hits:
            memory = await self.session.get(AgentMemory, uuid.UUID(hit["id"]))
            if memory is not None:
                memories.append(
                    {
                        "id": str(memory.id),
                        "scope": memory.scope,
                        "summary": memory.summary,
                        "content": memory.content[:500],
                        "score": hit["score"],
                    }
                )
        return memories

    async def delete(self, memory_id: uuid.UUID) -> None:
        memory = await self.session.get(AgentMemory, memory_id)
        if memory is None:
            raise NotFoundError("记忆不存在")
        self.store.delete(str(memory_id))
        await self.session.delete(memory)
        await self.session.commit()


@router.post("/projects/{project_id}/agent-memories", status_code=201)
async def write_memory(
    project_id: uuid.UUID,
    payload: MemoryWrite,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_launch),
) -> dict:
    memory = await MemoryService(session).write(project_id, payload, user.id)
    return {"id": str(memory.id), "scope": memory.scope, "summary": memory.summary}


@router.get("/projects/{project_id}/agent-memories")
async def list_memories(
    project_id: uuid.UUID,
    session: SessionDep,
    agent_id: uuid.UUID | None = Query(default=None),
    _user: User = Depends(require_view),
) -> list[dict]:
    memories = await MemoryService(session).list(project_id, agent_id)
    return [
        {"id": str(m.id), "agent_id": str(m.agent_id), "scope": m.scope, "summary": m.summary, "created_at": m.created_at.isoformat()}
        for m in memories
    ]


@router.get("/projects/{project_id}/agent-memories/search")
async def search_memories(
    project_id: uuid.UUID,
    session: SessionDep,
    query: str = Query(min_length=1),
    agent_id: uuid.UUID = Query(...),
    top_k: int = Query(default=5, ge=1, le=50),
    _user: User = Depends(require_view),
) -> list[dict]:
    return await MemoryService(session).search(project_id, agent_id, query, top_k)
