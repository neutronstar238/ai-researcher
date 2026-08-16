"""Audit domain: immutable operation trail (spec §19.6)."""

from app.domains.audit.router import router

__all__ = ["router"]
