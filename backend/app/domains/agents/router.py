"""Agent API routes (spec §16.9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_project_role
from app.db.models import User
from app.domains.agents.schemas import AgentOut, TaskCreate, TaskOut, ToolCallIn, ToolCallOut
from app.domains.agents.service import AgentService

router = APIRouter(tags=["agents"])

require_view = require_project_role("view")
require_launch = require_project_role("launch_agent")


@router.get("/projects/{project_id}/agents", response_model=list[AgentOut])
async def list_agents(
    project_id: uuid.UUID,
    session: SessionDep,
    team_id: uuid.UUID = Query(...),
    _user: User = Depends(require_view),
) -> list[AgentOut]:
    agents = await AgentService(session).list_agents(team_id)
    return [AgentOut.model_validate(a, from_attributes=True) for a in agents]


@router.post("/projects/{project_id}/agent-tasks", response_model=TaskOut, status_code=201)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_launch),
) -> TaskOut:
    task = await AgentService(session).create_task(project_id, payload, user.id)
    return TaskOut.model_validate(task, from_attributes=True)


@router.get("/projects/{project_id}/agent-tasks", response_model=list[TaskOut])
async def list_tasks(
    project_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[TaskOut]:
    tasks = await AgentService(session).list_tasks(project_id)
    return [TaskOut.model_validate(t, from_attributes=True) for t in tasks]


@router.get("/projects/{project_id}/agent-tasks/{task_id}", response_model=TaskOut)
async def get_task(
    project_id: uuid.UUID, task_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> TaskOut:
    task = await AgentService(session).get_task(task_id)
    return TaskOut.model_validate(task, from_attributes=True)


@router.post("/projects/{project_id}/agent-tasks/{task_id}:cancel", response_model=TaskOut)
async def cancel_task(
    project_id: uuid.UUID, task_id: uuid.UUID, session: SessionDep, _owner: User = Depends(require_launch)
) -> TaskOut:
    task = await AgentService(session).cancel_task(task_id)
    return TaskOut.model_validate(task, from_attributes=True)


@router.post("/projects/{project_id}/agent-tasks/{task_id}:retry", response_model=TaskOut)
async def retry_task(
    project_id: uuid.UUID, task_id: uuid.UUID, session: SessionDep, _owner: User = Depends(require_launch)
) -> TaskOut:
    task = await AgentService(session).retry_task(task_id)
    return TaskOut.model_validate(task, from_attributes=True)


@router.post("/projects/{project_id}/agent-tasks/{task_id}:run", response_model=TaskOut)
async def run_task(
    project_id: uuid.UUID, task_id: uuid.UUID, session: SessionDep, _owner: User = Depends(require_launch)
) -> TaskOut:
    """真实执行：调用已配置的 LLM（OpenAI 兼容），产出存 output/token_usage。"""
    task = await AgentService(session).run_task(task_id)
    return TaskOut.model_validate(task, from_attributes=True)


@router.post(
    "/projects/{project_id}/agent-tasks/{task_id}/tool-calls",
    response_model=ToolCallOut,
    status_code=201,
)
async def record_tool_call(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: ToolCallIn,
    user: CurrentUser,
    session: SessionDep,
    _owner: User = Depends(require_launch),
) -> ToolCallOut:
    call = await AgentService(session).record_tool_call(task_id, payload, project_id, user.id)
    return ToolCallOut.model_validate(call, from_attributes=True)


@router.get("/projects/{project_id}/agent-tasks/{task_id}/tool-calls", response_model=list[ToolCallOut])
async def list_tool_calls(
    project_id: uuid.UUID, task_id: uuid.UUID, session: SessionDep, _user: User = Depends(require_view)
) -> list[ToolCallOut]:
    calls = await AgentService(session).list_tool_calls(task_id)
    return [ToolCallOut.model_validate(c, from_attributes=True) for c in calls]
