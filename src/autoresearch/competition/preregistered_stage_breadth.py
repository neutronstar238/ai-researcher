"""Task 269.4: preregister this lineage's own pilot breadth, per `266.1.1`.

Why this exists
---------------
`P-20260804-077`: the official panel carries exactly 4 PDE systems, the preregistered
baseline policy excludes 2 of them because neither can produce a pinned baseline loss
under the frozen configuration grid, and the frozen Task `266.1` budget requires
`pilot_pde_system_count=3` with a derived `pilot_system_count=6`. On the narrowed
panel neither number is reachable.

The system's own self-correction cycle reached
``declare_frozen_pilot_breadth_unsatisfiable_and_require_new_preregistration`` in three
independent live runs with bounded reasoning enabled, with its guard accepting every
time. This module is that new preregistration.

What this is NOT
----------------
This is NOT the ``reduce_pilot_pde_breadth_to_available`` route, which the guard in
`pilot_breadth_contradiction.py` refuses. That route rewrites the frozen `266.1`
budget in place. This module leaves the frozen budget BYTE-IDENTICAL and gives the
child lineage its own preregistered breadth, binding the parent's numbers as evidence
of what was superseded. That is the `266.1.1` immutable-parent erratum pattern.

Why narrowing the pilot cannot bias the result
----------------------------------------------
The pilot is diagnostic and score-blind. `rank_pilot_finalists` ranks candidates by
median VALIDATION NMSE and never by the held-out loss that forms the reported effect,
and no pilot cell enters the estimand or the frozen gate. A smaller pilot therefore
buys less diagnostic signal for finalist selection; it cannot move the measured
effect. The cost is stated in the artifact rather than hidden.

Boundaries
----------
* The frozen parent budget is read and bound, never written.
* The derivation is deterministic: for each stratum, take the smaller of the frozen
  breadth and what the narrowed panel actually holds. No scientific choice is made
  here, because the arithmetic has only one answer.
* This artifact may only SHRINK the breadth. A lineage cannot use a new
  preregistration to buy MORE pilot systems than the frozen plan allowed.
* Both strata must keep at least one system, so a stratum is never silently dropped
  from the diagnostic signal entirely.
* Preregistration authorizes nothing. It is process provenance, never evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel

_BREADTH_NAME = "preregistered-stage-breadth.json"


class StageBreadthError(RuntimeError):
    """Raised when a preregistered stage breadth cannot be proved sound."""


class PreregisteredStageBreadth(StrictFrozenModel):
    """This lineage's own pilot breadth, superseding the parent's for this lineage."""

    schema_version: Literal["preregistered-stage-breadth-v1"] = (
        "preregistered-stage-breadth-v1"
    )
    lineage_id: str = Field(min_length=1)
    # The immutable parent, bound as evidence of exactly what was superseded.
    parent_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_pilot_ode_count: int = Field(ge=1)
    parent_pilot_pde_count: int = Field(ge=1)
    parent_pilot_system_count: int = Field(ge=2)
    # The policy that narrowed the panel, and the authored decision behind it.
    baseline_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contradiction_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_authored_resolution_kind: str = Field(min_length=1)
    # This lineage's own breadth, derived deterministically from the narrowed panel.
    available_ode_count: int = Field(ge=0)
    available_pde_count: int = Field(ge=0)
    pilot_ode_count: int = Field(ge=1)
    pilot_pde_count: int = Field(ge=1)
    pilot_system_count: int = Field(ge=2)
    breadth_reduced: bool
    power_cost_statement: str = Field(min_length=40)
    # Permanent boundaries.
    frozen_parent_budget_modified: Literal[False] = False
    pilot_enters_estimand: Literal[False] = False
    is_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    created_at: datetime
    breadth_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> PreregisteredStageBreadth:
        if self.pilot_ode_count + self.pilot_pde_count != self.pilot_system_count:
            raise StageBreadthError("pilot system count does not sum from its strata")
        if (
            self.parent_pilot_ode_count + self.parent_pilot_pde_count
            != self.parent_pilot_system_count
        ):
            raise StageBreadthError("parent pilot count does not sum from its strata")
        # A new preregistration may only SHRINK the breadth. Otherwise it becomes a
        # route to buying more pilot budget than the frozen plan allowed.
        if (
            self.pilot_ode_count > self.parent_pilot_ode_count
            or self.pilot_pde_count > self.parent_pilot_pde_count
        ):
            raise StageBreadthError(
                "a preregistered breadth cannot exceed the frozen parent breadth; "
                "this artifact may only narrow the pilot, never enlarge it"
            )
        # The breadth must be reachable on the panel it claims to describe.
        if (
            self.pilot_ode_count > self.available_ode_count
            or self.pilot_pde_count > self.available_pde_count
        ):
            raise StageBreadthError(
                "the preregistered breadth exceeds what the narrowed panel holds"
            )
        if self.breadth_reduced != (
            self.pilot_system_count < self.parent_pilot_system_count
        ):
            raise StageBreadthError(
                "the breadth_reduced flag contradicts the recorded counts"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"breadth_hash", "output_path"})
        )
        if self.breadth_hash != expected:
            raise StageBreadthError("preregistered stage breadth hash mismatch")
        return self


def preregister_stage_breadth(
    *,
    lineage_id: str,
    frozen_plan_path: Path | str,
    baseline_policy_hash: str,
    contradiction_package_path: Path | str,
    panel: dict[str, Any],
    excluded_system_names: tuple[str, ...],
    output_dir: Path | str,
    clock: datetime | None = None,
) -> PreregisteredStageBreadth:
    """Derive and persist this lineage's pilot breadth from the narrowed panel.

    Deterministic: for each stratum the breadth is ``min(frozen, available)``, so this
    function makes no scientific choice. It refuses unless the system's own authored
    resolution actually called for a new preregistration, so the artifact cannot be
    created to paper over a contradiction the loop never adjudicated.
    """

    frozen = json.loads(Path(frozen_plan_path).read_text(encoding="utf-8"))
    budget = frozen["search_budget"]
    parent_ode = int(budget["pilot_ode_system_count"])
    parent_pde = int(budget["pilot_pde_system_count"])

    package = json.loads(Path(contradiction_package_path).read_text(encoding="utf-8"))
    if not package["guard_audit"]["guard_accepted"]:
        raise StageBreadthError(
            "the authored resolution failed its own guard audit, so it cannot justify "
            "a new preregistration"
        )
    resolution = str(package["proposal"]["resolution_kind"])
    if not str(package["proposal"]["requires_new_preregistration"]):
        raise StageBreadthError(
            "the authored resolution does not call for a new preregistration"
        )
    if "require_new_preregistration" not in resolution:
        raise StageBreadthError(
            f"the authored resolution {resolution!r} is not a new-preregistration "
            "route, so this artifact would contradict the system's own decision"
        )

    excluded = set(excluded_system_names)
    kept = [
        item for item in panel["systems"] if str(item["system_name"]) not in excluded
    ]
    available_ode = sum(1 for item in kept if item["data_type"] == "ode")
    available_pde = sum(1 for item in kept if item["data_type"] == "pde")
    pilot_ode = min(parent_ode, available_ode)
    pilot_pde = min(parent_pde, available_pde)
    if pilot_ode < 1 or pilot_pde < 1:
        raise StageBreadthError(
            "the narrowed panel cannot supply at least one system per stratum, so a "
            "two-stratum pilot is impossible and the lineage cannot proceed"
        )

    total = pilot_ode + pilot_pde
    parent_total = parent_ode + parent_pde
    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "preregistered-stage-breadth-v1",
        "lineage_id": lineage_id,
        "parent_plan_hash": str(frozen["plan_hash"]),
        "parent_pilot_ode_count": parent_ode,
        "parent_pilot_pde_count": parent_pde,
        "parent_pilot_system_count": parent_total,
        "baseline_policy_hash": baseline_policy_hash,
        "contradiction_package_hash": str(package["package_hash"]),
        "system_authored_resolution_kind": resolution,
        "available_ode_count": available_ode,
        "available_pde_count": available_pde,
        "pilot_ode_count": pilot_ode,
        "pilot_pde_count": pilot_pde,
        "pilot_system_count": total,
        "breadth_reduced": total < parent_total,
        "power_cost_statement": (
            f"The pilot narrows from {parent_total} systems "
            f"({parent_ode} ODE, {parent_pde} PDE) to {total} "
            f"({pilot_ode} ODE, {pilot_pde} PDE), because the preregistered baseline "
            f"policy excluded {', '.join(sorted(excluded)) or 'no system'} and the "
            f"narrowed panel holds only {available_pde} PDE system(s). This buys LESS "
            "diagnostic signal for finalist selection. It cannot bias the reported "
            "effect: the pilot ranks candidates by validation NMSE only, and no pilot "
            "cell enters the estimand or the frozen gate. The frozen parent budget is "
            "bound above and is not modified."
        ),
        "frozen_parent_budget_modified": False,
        "pilot_enters_estimand": False,
        "is_evidence": False,
        "execution_authorized": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["breadth_hash"] = canonical_model_hash(payload)
    output_path = Path(output_dir).resolve() / _BREADTH_NAME
    payload["output_path"] = output_path.as_posix()
    breadth = PreregisteredStageBreadth.model_validate(payload)
    write_json_model(output_path, breadth)
    reloaded = PreregisteredStageBreadth.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    if reloaded.breadth_hash != breadth.breadth_hash:
        raise StageBreadthError("written stage breadth hash does not match")
    return reloaded


def load_stage_breadth(*, output_dir: Path | str) -> PreregisteredStageBreadth | None:
    """Load a persisted breadth, or None when this lineage never needed one."""

    path = Path(output_dir).resolve() / _BREADTH_NAME
    if not path.is_file():
        return None
    return PreregisteredStageBreadth.model_validate_json(
        path.read_text(encoding="utf-8")
    )
