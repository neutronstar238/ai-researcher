"""Auth application service: credential login, refresh rotation, logout (spec §18.3)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import PermissionDeniedError, ValidationAppError
from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.models import RefreshSession, User


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def login(self, email: str, password: str) -> tuple[dict, str, str]:
        result = await self.session.execute(select(User).where(User.email == email.strip().lower()))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            raise PermissionDeniedError("邮箱或密码错误", code="INVALID_CREDENTIALS", status_code=401)
        if user.status != "active":
            raise PermissionDeniedError("账号已被禁用", code="ACCOUNT_DISABLED", status_code=403)

        family_id = uuid.uuid4()
        access, refresh, session_row = self._issue_pair(user, family_id)
        self.session.add(session_row)
        user.last_login_at = datetime.now(UTC)
        await self.session.commit()
        return self._user_out(user), access, refresh

    async def refresh(self, refresh_token: str) -> tuple[dict, str, str]:
        payload = self._decode_refresh(refresh_token)
        session_row = await self._find_session(hash_refresh_token(refresh_token))

        # 旧 Token 重放 -> 撤销整个 family（spec §11.3）
        if session_row is None:
            await self._revoke_family(str(payload["family_id"]))
            await self.session.commit()
            raise PermissionDeniedError("会话已失效", code="REFRESH_REUSED", status_code=401)
        if session_row.revoked_at is not None:
            await self._revoke_family(str(session_row.family_id))
            await self.session.commit()
            raise PermissionDeniedError("会话已失效", code="REFRESH_REUSED", status_code=401)

        user = await self.session.get(User, uuid.UUID(str(payload["sub"])))
        if user is None or user.status != "active":
            raise PermissionDeniedError("账号不可用", code="ACCOUNT_DISABLED", status_code=403)

        # 旋转：吊销旧会话，同一 family 签发新会话
        new_access, new_refresh, new_session = self._issue_pair(user, session_row.family_id)
        session_row.revoked_at = datetime.now(UTC)
        session_row.replaced_by = new_session.id
        self.session.add(new_session)
        await self.session.commit()
        return self._user_out(user), new_access, new_refresh

    async def logout(self, refresh_token: str) -> None:
        payload = self._decode_refresh(refresh_token)
        await self._revoke_family(str(payload["family_id"]))
        await self.session.commit()

    async def user_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    # -- internals ------------------------------------------------------

    def _issue_pair(self, user: User, family_id: uuid.UUID) -> tuple[str, str, RefreshSession]:
        sub = str(user.id)
        access = create_access_token(
            sub, self.settings.jwt_signing_key, ttl_minutes=self.settings.access_token_ttl_minutes
        )
        jti = str(uuid.uuid4())
        refresh = create_refresh_token(
            sub,
            self.settings.jwt_signing_key,
            family_id=str(family_id),
            jti=jti,
            ttl_days=self.settings.refresh_token_ttl_days,
        )
        session_row = RefreshSession(
            id=uuid.UUID(jti),
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            family_id=family_id,
            expires_at=datetime.now(UTC)
            + timedelta(days=self.settings.refresh_token_ttl_days),
        )
        return access, refresh, session_row

    async def _find_session(self, token_hash: str) -> RefreshSession | None:
        result = await self.session.execute(
            select(RefreshSession).where(RefreshSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def _revoke_family(self, family_id: str) -> None:
        sessions = (
            await self.session.execute(
                select(RefreshSession).where(RefreshSession.family_id == uuid.UUID(family_id))
            )
        ).scalars().all()
        now = datetime.now(UTC)
        for row in sessions:
            if row.revoked_at is None:
                row.revoked_at = now

    def _decode_refresh(self, token: str) -> dict:
        try:
            return decode_token(token, self.settings.jwt_signing_key, expected_type="refresh")
        except TokenError as exc:
            raise ValidationAppError("refresh token 无效", code="INVALID_REFRESH_TOKEN") from exc

    @staticmethod
    def _user_out(user: User) -> dict:
        return {
            "id": user.id,
            "email": str(user.email),
            "display_name": user.display_name,
            "locale": user.locale,
            "timezone": user.timezone,
            "status": user.status,
        }
