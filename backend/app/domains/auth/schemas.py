"""Auth request/response schemas (spec §18.1 envelope is applied by routers)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    expires_in: int


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    locale: str
    timezone: str
    status: str

    model_config = {"from_attributes": True}
