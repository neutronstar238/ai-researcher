"""Deterministic bibliography policy for evidence-bound research plans.

The retrieval/planning stage owns scientific relevance, order, and provenance.
Plan authors may express which locked entries are most central, but that
preference is audit metadata only: it must never renumber the citation
namespace or silently collapse an otherwise useful bibliography.  This module
therefore projects the bounded locked catalog in its canonical order.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MIN_RESEARCH_PLAN_REFERENCES = 5
MAX_RESEARCH_PLAN_REFERENCES = 10
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class LockedReferenceProjection:
    """Auditable projection of model preferences into the locked catalog."""

    references: tuple[str, ...]
    model_selected_indices: tuple[int, ...]
    program_supplemented_indices: tuple[int, ...]
    catalog_count: int


def project_locked_references(
    value: Any,
    catalog: Sequence[str],
) -> tuple[str, ...]:
    """Project a model selection into the bounded canonical bibliography."""

    return project_locked_reference_selection(value, catalog).references


def project_locked_reference_selection(
    value: Any,
    catalog: Sequence[str],
) -> LockedReferenceProjection:
    """Return both the bibliography and model/program contribution audit."""

    locked = tuple(dict.fromkeys(str(entry).strip() for entry in catalog if str(entry).strip()))
    if not locked:
        return LockedReferenceProjection((), (), (), 0)

    bounded = locked[:MAX_RESEARCH_PLAN_REFERENCES]
    items = value if isinstance(value, list | tuple) else (value,)
    selected_indices: list[int] = []
    for item in items:
        index = _catalog_index(item, locked)
        if index is not None and index <= len(bounded) and index not in selected_indices:
            selected_indices.append(index)
    supplemented_indices = [
        index for index in range(1, len(bounded) + 1) if index not in selected_indices
    ]
    return LockedReferenceProjection(
        bounded,
        tuple(selected_indices),
        tuple(supplemented_indices),
        len(locked),
    )


def validate_locked_bibliography(
    references: Sequence[str],
    catalog: Sequence[str],
    *,
    minimum: int = MIN_RESEARCH_PLAN_REFERENCES,
    maximum: int = MAX_RESEARCH_PLAN_REFERENCES,
    require_exact_catalog: bool = False,
) -> None:
    """Fail closed when a final bibliography is sparse, oversized, or unlocked."""

    if minimum < 1 or maximum < minimum:
        raise ValueError("invalid locked bibliography bounds")
    locked = tuple(dict.fromkeys(str(entry).strip() for entry in catalog if str(entry).strip()))
    distinct_locked = _deduplicate_references(locked)
    final = tuple(str(entry).strip() for entry in references)
    if (
        any(not entry for entry in final)
        or len(set(final)) != len(final)
        or len({_reference_identity(entry) for entry in final}) != len(final)
    ):
        raise ValueError("final bibliography contains blank or duplicate entries")
    if len(distinct_locked) < minimum:
        raise ValueError(
            f"locked real catalog has fewer than {minimum} references; broaden retrieval"
        )
    if not minimum <= len(final) <= maximum:
        raise ValueError(f"final bibliography must contain {minimum}–{maximum} locked references")
    unknown = tuple(entry for entry in final if entry not in set(locked))
    if unknown:
        raise ValueError("final bibliography contains entries outside the locked real catalog")
    if require_exact_catalog and final != distinct_locked[:maximum]:
        raise ValueError("final bibliography must preserve the exact locked catalog order")


def build_postpilot_reference_catalog(
    planning_references: Sequence[str],
    pilot_references: Sequence[str],
) -> tuple[str, ...]:
    """Keep the bounded planning lock unchanged after the pilot.

    Adapter-bundled references are execution metadata, not a second retrieval
    channel and not authority to renumber the citation namespace.
    """

    planning = _deduplicate_references(planning_references)
    _ = pilot_references
    return planning[:MAX_RESEARCH_PLAN_REFERENCES]


def _reference_identity(entry: str) -> str:
    match = _DOI.search(entry)
    if match is not None:
        return "doi:" + match.group(0).rstrip(".,;)]}").casefold()
    return "text:" + re.sub(r"\s+", " ", entry).strip().casefold()


def _deduplicate_references(entries: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    identities: set[str] = set()
    for raw in entries:
        entry = str(raw).strip()
        if not entry:
            continue
        identity = _reference_identity(entry)
        if identity in identities:
            continue
        selected.append(entry)
        identities.add(identity)
    return tuple(selected)


def _catalog_index(item: Any, catalog: tuple[str, ...]) -> int | None:
    if isinstance(item, int) and not isinstance(item, bool):
        return item if 1 <= item <= len(catalog) else None
    text = str(item).strip()
    if text in catalog:
        return catalog.index(text) + 1
    match = re.fullmatch(r"\[?\s*(\d+)\s*\]?", text)
    if match is None:
        return None
    index = int(match.group(1))
    return index if 1 <= index <= len(catalog) else None
