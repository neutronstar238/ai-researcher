"""Auth domain: login, refresh-token rotation, logout, current user (spec §18.3)."""

from app.domains.auth.router import router
from app.domains.auth.service import AuthService

__all__ = ["AuthService", "router"]
