"""Literature provider contract (spec §10.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PaperResult:
    title: str
    doi: str | None = None
    publication_year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    external_id: str | None = None
    source: str = ""


@runtime_checkable
class LiteratureProvider(Protocol):
    name: str

    async def search(self, query: str, max_results: int = 20) -> list[PaperResult]: ...
