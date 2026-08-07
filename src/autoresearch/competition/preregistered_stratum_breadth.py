"""Domain-agnostic preregistered stage breadth, keyed by stratum name.

Why this exists alongside `preregistered_stage_breadth`
------------------------------------------------------
The v1 module hardcoded MDBench's taxonomy into the METHODOLOGY layer: it carried
`pilot_ode_count`, `available_pde_count`, and similar fields, so the general rule
"a child lineage may narrow its pilot breadth, but only downward, and never by
dropping a stratum" could not be reused for any other panel. That is the wrong
coupling. A methodology module should describe strata; which strata exist is domain
knowledge and belongs in a skill or in the panel data.

`official_lineage._split_smoke_wave` already had this right: it keys on
`(candidate_id, data_type)` generically and never names a specific data type. This
module brings the breadth artifact to the same standard.

Retained artifacts are NOT rewritten. `preregistered_stage_breadth.py` stays as the
reader for lineages `task2693` through `task2696`, whose `breadth_hash` covers the
v1 field names, exactly as the `266.1.1` immutable-parent pattern requires. New
lineages preregister with this module.

The invariants, stated once and independent of any domain
--------------------------------------------------------
* Breadth may only SHRINK. A new preregistration must never buy more budget than the
  frozen parent allowed, or preregistration becomes a loophole.
* Every stratum keeps at least one member. Dropping a stratum entirely is not a
  narrowing, it is a change of question.
* The breadth must be reachable on the panel it claims to describe.
* The frozen parent is bound as evidence and never written.
* Preregistration authorizes nothing and is never evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel

_BREADTH_NAME = "preregistered-stratum-breadth.json"


class StratumBreadthError(RuntimeError):
    """Raised when a preregistered stratum breadth cannot be proved sound."""


class PreregisteredStratumBreadth(StrictFrozenModel):
    """One lineage's own per-stratum breadth, superseding its parent's for itself."""

    schema_version: Literal["preregistered-stratum-breadth-v1"] = (
        "preregistered-stratum-breadth-v1"
    )
    lineage_id: str = Field(min_length=1)
    parent_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Stratum name -> count. The names come from the panel, never from this module.
    parent_breadth: dict[str, int] = Field(min_length=1)
    available_breadth: dict[str, int] = Field(min_length=1)
    breadth: dict[str, int] = Field(min_length=1)
    total_breadth: int = Field(ge=1)
    parent_total_breadth: int = Field(ge=1)
    breadth_reduced: bool
    narrowed_strata: tuple[str, ...]
    power_cost_statement: str = Field(min_length=40)
    # Why narrowing this stage cannot bias a result. Asserted, not argued.
    stage_enters_estimand: Literal[False] = False
    frozen_parent_budget_modified: Literal[False] = False
    is_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    created_at: datetime
    breadth_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> PreregisteredStratumBreadth:
        if set(self.breadth) != set(self.parent_breadth):
            raise StratumBreadthError(
                "the child breadth must name exactly the parent's strata; adding or "
                "removing a stratum changes the question rather than narrowing it"
            )
        if not set(self.breadth) <= set(self.available_breadth):
            raise StratumBreadthError(
                "the breadth names a stratum the panel does not supply"
            )
        if sum(self.breadth.values()) != self.total_breadth:
            raise StratumBreadthError("total breadth does not sum from its strata")
        if sum(self.parent_breadth.values()) != self.parent_total_breadth:
            raise StratumBreadthError(
                "parent total breadth does not sum from its strata"
            )
        # Only downward. Otherwise a new preregistration buys extra budget.
        over = sorted(
            name
            for name, count in self.breadth.items()
            if count > self.parent_breadth[name]
        )
        if over:
            raise StratumBreadthError(
                f"a preregistered breadth cannot exceed the frozen parent breadth on "
                f"{over}; this artifact may only narrow, never enlarge"
            )
        unreachable = sorted(
            name
            for name, count in self.breadth.items()
            if count > self.available_breadth.get(name, 0)
        )
        if unreachable:
            raise StratumBreadthError(
                f"the preregistered breadth exceeds what the panel holds on "
                f"{unreachable}"
            )
        # A stratum reduced to nothing is a dropped question, not a narrowing.
        empty = sorted(name for name, count in self.breadth.items() if count < 1)
        if empty:
            raise StratumBreadthError(
                f"stratum {empty} would keep no members; dropping a stratum entirely "
                "is a change of question, not a narrowing of breadth"
            )
        expected_narrowed = tuple(
            sorted(
                name
                for name, count in self.breadth.items()
                if count < self.parent_breadth[name]
            )
        )
        if self.narrowed_strata != expected_narrowed:
            raise StratumBreadthError(
                "narrowed_strata contradicts the recorded per-stratum counts"
            )
        if self.breadth_reduced != (self.total_breadth < self.parent_total_breadth):
            raise StratumBreadthError(
                "the breadth_reduced flag contradicts the recorded totals"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"breadth_hash", "output_path"})
        )
        if self.breadth_hash != expected:
            raise StratumBreadthError("preregistered stratum breadth hash mismatch")
        return self


def derive_available_breadth(
    *,
    members: list[Mapping[str, Any]],
    stratum_key: str,
    excluded_names: tuple[str, ...] = (),
    name_key: str = "system_name",
) -> dict[str, int]:
    """Count panel members per stratum after exclusions.

    `stratum_key` and `name_key` are supplied by the caller, so this function never
    needs to know what the strata are called or what a member represents.
    """

    excluded = set(excluded_names)
    counts: dict[str, int] = {}
    for item in members:
        if str(item[name_key]) in excluded:
            continue
        counts[str(item[stratum_key])] = counts.get(str(item[stratum_key]), 0) + 1
    if not counts:
        raise StratumBreadthError("the exclusions leave no panel member in any stratum")
    return counts


def preregister_stratum_breadth(
    *,
    lineage_id: str,
    parent_plan_hash: str,
    parent_breadth: Mapping[str, int],
    available_breadth: Mapping[str, int],
    output_dir: Path | str,
    reason: str,
    stage_name: str = "pilot",
    clock: datetime | None = None,
) -> PreregisteredStratumBreadth:
    """Derive and persist a child lineage's breadth. Deterministic per stratum.

    For each stratum the breadth is ``min(parent, available)``, so this function makes
    no scientific choice: the arithmetic has exactly one answer. `reason` is the
    caller's own account of why the panel narrowed, and it is recorded verbatim.
    """

    if set(parent_breadth) - set(available_breadth):
        raise StratumBreadthError(
            f"the panel supplies no member for stratum "
            f"{sorted(set(parent_breadth) - set(available_breadth))}, so a breadth "
            "over the parent's strata cannot be derived"
        )
    breadth = {
        name: min(int(count), int(available_breadth[name]))
        for name, count in parent_breadth.items()
    }
    starved = sorted(name for name, count in breadth.items() if count < 1)
    if starved:
        raise StratumBreadthError(
            f"stratum {starved} cannot supply a single member, so this stage is "
            "impossible on the narrowed panel and the lineage cannot proceed"
        )

    total = sum(breadth.values())
    parent_total = sum(int(v) for v in parent_breadth.values())
    narrowed = tuple(
        sorted(name for name, count in breadth.items() if count < parent_breadth[name])
    )
    detail = ", ".join(
        f"{name} {parent_breadth[name]}->{breadth[name]}" for name in sorted(breadth)
    )
    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "preregistered-stratum-breadth-v1",
        "lineage_id": lineage_id,
        "parent_plan_hash": parent_plan_hash,
        "parent_breadth": {k: int(v) for k, v in parent_breadth.items()},
        "available_breadth": {k: int(v) for k, v in available_breadth.items()},
        "breadth": breadth,
        "total_breadth": total,
        "parent_total_breadth": parent_total,
        "breadth_reduced": total < parent_total,
        "narrowed_strata": narrowed,
        "power_cost_statement": (
            f"The {stage_name} stage narrows from {parent_total} to {total} members "
            f"({detail}). Reason given by the caller: {reason} This buys LESS "
            f"diagnostic breadth. It cannot bias the reported effect, because no "
            f"{stage_name} observation enters the estimand or the frozen gate. The "
            "frozen parent breadth is bound above and is not modified."
        ),
        "stage_enters_estimand": False,
        "frozen_parent_budget_modified": False,
        "is_evidence": False,
        "execution_authorized": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["breadth_hash"] = canonical_model_hash(payload)
    output_path = Path(output_dir).resolve() / _BREADTH_NAME
    payload["output_path"] = output_path.as_posix()
    breadth_model = PreregisteredStratumBreadth.model_validate(payload)
    write_json_model(output_path, breadth_model)
    reloaded = PreregisteredStratumBreadth.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    if reloaded.breadth_hash != breadth_model.breadth_hash:
        raise StratumBreadthError("written stratum breadth hash does not match")
    return reloaded


def load_stratum_breadth(
    *, output_dir: Path | str
) -> PreregisteredStratumBreadth | None:
    """Load a persisted breadth, or None when this lineage never needed one."""

    path = Path(output_dir).resolve() / _BREADTH_NAME
    if not path.is_file():
        return None
    return PreregisteredStratumBreadth.model_validate_json(
        path.read_text(encoding="utf-8")
    )
