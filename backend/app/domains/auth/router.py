"""Auth API routes (spec §18.3).

refresh token 用 HttpOnly Cookie 下发（``ar_refresh``，Path=/api/v1/auth，SameSite=Lax，
生产 Secure）；access token 仍走 Authorization 头。Cookie 化的 refresh/logout 端点做
Origin CSRF 校验（§19.3）；请求体回退保留以兼容旧客户端。
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser, SessionDep
from app.api.errors import AppError
from app.core.config import get_settings
from app.core.rate_limit import RateLimiter
from app.domains.auth.schemas import LoginRequest, LogoutRequest, RefreshRequest, TokenPair, UserOut
from app.domains.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "ar_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.refresh_token_ttl_days * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path="/api/v1/auth")


def _csrf_origin_ok(request: Request) -> bool:
    """Origin 存在时须在白名单内（§19.3）；无 Origin 的非浏览器客户端放行。"""
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    return origin in get_settings().cors_origins


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, session: SessionDep, response: Response) -> TokenPair:
    # 登录限流（spec §19.3）：每 IP 每分钟 20 次
    limiter = RateLimiter()
    if not await limiter.allow(f"login:{request.client.host if request.client else 'unknown'}", 20):
        raise AppError("请求过于频繁，请稍后再试", code="RATE_LIMITED", status_code=429)
    service = AuthService(session)
    user, access, refresh = await service.login(payload.email, payload.password)
    _set_refresh_cookie(response, refresh)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=service.settings.access_token_ttl_minutes * 60,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    payload: RefreshRequest | None = None,
) -> TokenPair:
    if not _csrf_origin_ok(request):
        raise AppError("Origin 校验失败", code="CSRF_ORIGIN_MISMATCH", status_code=403)
    service = AuthService(session)
    token = request.cookies.get(REFRESH_COOKIE) or (payload.refresh_token if payload else None)
    if not token:
        raise AppError("缺少 refresh token", code="MISSING_REFRESH_TOKEN", status_code=401)
    _, access, new_refresh = await service.refresh(token)
    _set_refresh_cookie(response, new_refresh)
    return TokenPair(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=service.settings.access_token_ttl_minutes * 60,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    payload: LogoutRequest | None = None,
) -> Response:
    if not _csrf_origin_ok(request):
        raise AppError("Origin 校验失败", code="CSRF_ORIGIN_MISMATCH", status_code=403)
    service = AuthService(session)
    token = request.cookies.get(REFRESH_COOKIE) or (payload.refresh_token if payload else None)
    if token:
        await service.logout(token)
    _clear_refresh_cookie(response)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)
