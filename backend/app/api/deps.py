"""FastAPI dependencies: current-user resolution and project-role authorization."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import PermissionDeniedError
from app.core.authorization import can
from app.core.config import get_settings
from app.core.security import decode_token, token_subject
from app.db.models import ProjectMember, User
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PermissionDeniedError("缺少访问令牌", code="UNAUTHENTICATED", status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise PermissionDeniedError("缺少访问令牌", code="UNAUTHENTICATED", status_code=401)
    return token


async def get_current_user(
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _extract_bearer(authorization)
    try:
        payload = decode_token(token, get_settings().jwt_signing_key, expected_type="access")
    except Exception as exc:  # noqa: BLE001 - re-raised as permission error
        raise PermissionDeniedError("访问令牌无效或已过期", code="UNAUTHENTICATED", status_code=401) from exc
    user_id = uuid.UUID(token_subject(payload))
    user = await session.get(User, user_id)
    if user is None or user.status != "active":
        raise PermissionDeniedError("账号不可用", code="UNAUTHENTICATED", status_code=401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def resolve_project_role(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> str:
    result = await session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise PermissionDeniedError("无权访问该项目", code="FORBIDDEN", status_code=403)
    return member.role


def require_project_role(capability: str) -> Callable:
    """Factory returning a dependency that enforces ``capability`` on the path project."""

    async def dependency(
        project_id: uuid.UUID,
        user: CurrentUser,
        session: SessionDep,
    ) -> User:
        role = await resolve_project_role(session, project_id, user.id)
        if not can(role, capability):
            raise PermissionDeniedError(
                f"当前角色 {role} 无权执行该操作",
                code="FORBIDDEN",
                status_code=403,
            )
        return user

    return dependency
