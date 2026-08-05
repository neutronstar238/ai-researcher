"""Tasks 268.3 + 269.2: preregister a corrected baseline policy for a NEW lineage.

Why this module exists
----------------------
Task `268.1` (`P-20260802-070`) proved the frozen Task `266.1` protocol is
UNSATISFIABLE as written: the estimand carries
``all_domain_baseline_cells_must_succeed`` as an immutable ``Literal[True]``, yet
`heat_laser` and `heat_soil_uniform_2d_p1` fail every one of their 12 baseline
cells under the frozen baseline policy. Task `268.2` then routed the repair
decision into the system's OWN self-correction cycle, and the system authored
``declare_frozen_protocol_unsatisfiable_and_require_new_lineage`` for BOTH
systems, stably across five independent live runs.

This module carries that system-authored decision into a preregistered artifact
for a NEW lineage. It does three things and nothing else:

1. ``derive_carried_defects`` reads the retained evidence and produces the defect
   statements the new lineage's plan must carry, so the plan states what it is
   trying to fix. The frozen-protocol statement is the SYSTEM's own authored
   text, quoted verbatim from the `268.2` package; the zero-term statement is
   derived arithmetically from the retained cells. No agent prose is added.
2. ``preregister_baseline_policy`` writes the corrected per-system baseline
   handling BEFORE any numeric payload is opened, with its power cost stated.
3. Guards that make the fabricated-effect route unrepresentable rather than
   merely discouraged.

The guard that matters
----------------------
`P-20260802-063` and `P-20260802-065` record the trap: forcing a cell to complete
against an all-zero baseline model manufactures a large fake positive effect,
because any candidate trivially "beats" a zero-null. `heat_soil_uniform_2d_p1`
carries exactly that signature. So a system whose evidence says
``produces_all_zero_model`` CANNOT be given
``paired_against_pinned_baseline`` handling: the model refuses to validate. The
policy therefore cannot express the fabricated-effect route at all.

Excluding a system is honest only if it is declared. Every excluded system must
carry an explicit panel change and a stated power cost, so a reader sees the
thinned stratum instead of an unexplained 12-system panel.

Boundaries
----------
* Preregistration reads only retained cell STATUS and failure strings plus frozen
  metadata. It never opens a numeric payload, and it records that fact.
* Preregistration authorizes nothing. Execution still requires the recorded plan
  approval, and this artifact is process provenance, never evidence.
* The parent `266.1` lineage is immutable: this artifact binds the parent hashes
  and carries its own identity, following the `266.1.1` erratum pattern.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.schemas.provenance import file_hash

_POLICY_NAME = "preregistered-baseline-policy.json"

# A numeric payload lives in a per-cell `metrics.json`/`payload.npz`, or in the
# aggregate `*-results.json` numeric fields. Preregistration reads cell STATUS and
# failure strings only, so any of these being newer than the policy means the policy
# was written AFTER a numeric read and its "preregistered" claim is false.
_NUMERIC_PAYLOAD_GLOBS: tuple[str, ...] = (
    "cells/**/metrics.json",
    "cells/**/payload.npz",
    "cells/**/*.npy",
)

# How one system may be treated under the corrected policy.
PAIRED = "paired_against_pinned_baseline"
EXCLUDED = "excluded_from_paired_effect_declared_panel_change"

BASELINE_HANDLING_KINDS: tuple[str, ...] = (PAIRED, EXCLUDED)

# The zero-term marker the runner writes into a failed cell's failure reason.
_ZERO_TERM_MARKER = "returned 0 terms"


class BaselinePolicyError(RuntimeError):
    """Raised when a preregistered baseline policy boundary cannot be proved."""


class SystemBaselineHandling(StrictFrozenModel):
    """How ONE system is handled under the corrected baseline policy."""

    system_name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    handling: str
    # The Task 268.1 mechanism, carried from the retained evidence.
    mechanism: str | None = None
    # True when the retained evidence shows a forced completion would yield an
    # ALL-ZERO baseline model. Such a system can never be scored against.
    produces_all_zero_model: bool = False
    # Required for an excluded system: the panel change and what it costs.
    declared_panel_change: str | None = None
    power_cost: str | None = None
    # The SYSTEM's own authored justification, quoted from the 268.2 package.
    system_authored_resolution_kind: str | None = None
    system_authored_justification: str | None = None

    @model_validator(mode="after")
    def _validate_handling(self) -> SystemBaselineHandling:
        if self.handling not in BASELINE_HANDLING_KINDS:
            raise BaselinePolicyError(
                f"unsupported baseline handling kind: {self.handling}"
            )
        # THE fabricated-effect guard. A zero-null baseline cannot be scored
        # against, so this combination is unrepresentable rather than discouraged.
        if self.produces_all_zero_model and self.handling == PAIRED:
            raise BaselinePolicyError(
                f"{self.system_name} would complete with an all-zero baseline model, "
                f"so {PAIRED} manufactures a fake positive effect rather than "
                "measuring one (the P-20260802-063 and P-20260802-065 pattern); it "
                "must be excluded as a declared panel change instead"
            )
        if self.handling == EXCLUDED:
            # An exclusion is honest only when it is declared WITH its cost.
            if not (self.declared_panel_change or "").strip():
                raise BaselinePolicyError(
                    f"{self.system_name} is excluded without a declared panel "
                    "change; a silent repair is forbidden"
                )
            if not (self.power_cost or "").strip():
                raise BaselinePolicyError(
                    f"{self.system_name} is excluded without a stated power cost"
                )
        return self


class BaselineImageBinding(StrictFrozenModel):
    """Parent/child container binding, following the `266.1.1` erratum pattern."""

    parent_image_id: str = Field(min_length=1)
    parent_runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_repinned: bool
    new_image_id: str | None = None

    @model_validator(mode="after")
    def _validate_binding(self) -> BaselineImageBinding:
        if self.image_repinned:
            if not (self.new_image_id or "").strip():
                raise BaselinePolicyError(
                    "a re-pinned image must record its new image id"
                )
        elif self.new_image_id not in (None, self.parent_image_id):
            raise BaselinePolicyError(
                "the policy does not re-pin the image, so the recorded image id must "
                "remain the parent's"
            )
        return self


class CarriedDefect(StrictFrozenModel):
    """One diagnosed defect the new lineage carries into its plan."""

    problem_id: str = Field(min_length=1)
    # Where the statement's text came from, so a reader can tell system-authored
    # scientific reasoning from a deterministic arithmetic derivation.
    origin: Literal["system_authored", "deterministic_derivation"]
    source_artifact: str = Field(min_length=1)
    statement: str = Field(min_length=20)


class PreregisteredBaselinePolicy(StrictFrozenModel):
    """The corrected baseline policy for one NEW lineage, frozen before any read."""

    schema_version: Literal["preregistered-baseline-policy-v1"] = (
        "preregistered-baseline-policy-v1"
    )
    lineage_id: str = Field(min_length=1)
    # The immutable parent. Never edited, only bound.
    parent_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_lineage_id: str = Field(min_length=1)
    # The `268.2` self-correction package whose authored decision this carries.
    authored_decision_package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authored_decision_package_path: str = Field(min_length=1)
    # The retained baseline evidence this policy was derived from.
    baseline_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    systems: tuple[SystemBaselineHandling, ...] = Field(min_length=1)
    excluded_system_names: tuple[str, ...]
    paired_system_count: int = Field(ge=0)
    parent_paired_system_count: int = Field(ge=0)
    pde_stratum_size: int = Field(ge=0)
    parent_pde_stratum_size: int = Field(ge=0)
    power_cost_statement: str = Field(min_length=20)
    image_binding: BaselineImageBinding
    carried_defects: tuple[CarriedDefect, ...] = Field(min_length=1)
    # Hard boundaries. All three are permanent for this artifact.
    numeric_payload_opened_during_preregistration: Literal[False] = False
    scores_against_all_zero_baseline: Literal[False] = False
    is_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    created_at: datetime
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_policy(self) -> PreregisteredBaselinePolicy:
        names = [item.system_name for item in self.systems]
        if len(set(names)) != len(names):
            raise BaselinePolicyError("each system may carry only one handling")
        excluded = tuple(
            sorted(item.system_name for item in self.systems if item.handling == EXCLUDED)
        )
        if tuple(sorted(self.excluded_system_names)) != excluded:
            raise BaselinePolicyError(
                "excluded_system_names does not match the per-system handling"
            )
        # An exclusion may only thin the panel, never enlarge it. Checked before the
        # count-consistency check so an enlarged panel is named as such.
        if self.paired_system_count > self.parent_paired_system_count:
            raise BaselinePolicyError(
                "a corrected baseline policy cannot pair MORE systems than the parent "
                "panel; panel enlargement is not a baseline repair"
            )
        if excluded and self.paired_system_count >= self.parent_paired_system_count:
            raise BaselinePolicyError(
                "systems are excluded but the paired count did not fall, so the "
                "power cost is not being reported honestly"
            )
        paired = sum(1 for item in self.systems if item.handling == PAIRED)
        if paired != self.paired_system_count:
            raise BaselinePolicyError(
                f"paired_system_count {self.paired_system_count} contradicts the "
                f"{paired} systems actually paired by this policy"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"policy_hash", "output_path"})
        )
        if self.policy_hash != expected:
            raise BaselinePolicyError("baseline policy hash mismatch")
        return self


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BaselinePolicyError(f"missing required artifact: {path}")
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _scan_zero_term_cells(root: Path) -> list[dict[str, str]]:
    """Find retained cells whose failure reason carries the zero-term marker.

    The marker only became visible after the `P-20260802-067` term-cap fix improved
    the contract message. In the parent lineage the same failure was recorded as the
    ambiguous "equation must contain 1-64 concrete terms", so the zero-term evidence
    lives in the recheck cells rather than in the parent's aggregate results. Each
    per-cell `result.json` carries no identity, so the system and candidate names are
    read from its sibling `spec.json`'s `attempt` block.
    """

    found: list[dict[str, str]] = []
    for result_path in sorted(root.rglob("result.json")):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if _ZERO_TERM_MARKER not in str(payload.get("failure_reason") or ""):
            continue
        spec_path = result_path.with_name("spec.json")
        attempt: dict[str, Any] = {}
        if spec_path.is_file():
            attempt = dict(
                json.loads(spec_path.read_text(encoding="utf-8")).get("attempt") or {}
            )
        found.append(
            {
                "system_name": str(attempt.get("system_name") or "unknown"),
                "candidate_id": str(attempt.get("candidate_id") or "unknown"),
                "failure_reason": str(payload.get("failure_reason")),
                "path": result_path.as_posix(),
            }
        )
    return found


def derive_carried_defects(
    *,
    authored_decision_package_path: Path | str,
    zero_term_evidence_root: Path | str,
    prior_full_results_path: Path | str,
) -> tuple[CarriedDefect, ...]:
    """Derive the defect statements the new lineage's plan must carry.

    Neither statement is authored here. `P-20260802-070` is the SYSTEM's own
    ``contradiction_statement`` from the `268.2` package, quoted verbatim.
    `P-20260802-068` is derived arithmetically from the retained cells: the counts,
    the affected system, and the exact contract message are read out of evidence.
    """

    package_path = Path(authored_decision_package_path)
    package = _load_json(package_path)
    proposal = package["proposal"]

    defects = [
        CarriedDefect(
            problem_id="P-20260802-070",
            origin="system_authored",
            source_artifact=package_path.as_posix(),
            # Verbatim system-authored text. Not paraphrased, not summarised.
            statement=str(proposal["contradiction_statement"]),
        )
    ]

    evidence_root = Path(zero_term_evidence_root)
    zero_term = _scan_zero_term_cells(evidence_root)
    if not zero_term:
        raise BaselinePolicyError(
            f"no zero-term failure found under {evidence_root}; the P-20260802-068 "
            "defect cannot be carried from evidence that does not contain it"
        )
    affected = sorted({item["system_name"] for item in zero_term})
    candidates = sorted({item["candidate_id"] for item in zero_term})

    # The parent lineage's own totals, for the "system-specific, not broken" claim.
    results_path = Path(prior_full_results_path)
    parent = _load_json(results_path)
    selected_cells = [
        item
        for item in parent.get("results", [])
        if str(item.get("candidate_id")) in set(candidates)
    ]
    succeeded = sum(1 for item in selected_cells if item.get("status") == "succeeded")

    defects.append(
        CarriedDefect(
            problem_id="P-20260802-068",
            origin="deterministic_derivation",
            source_artifact=evidence_root.as_posix(),
            statement=(
                f"Candidate {', '.join(candidates)} returns zero terms on "
                f"{', '.join(affected)}, so its sparse selection collapses to the "
                f"empty set on that system's scaling and the cell is rejected by the "
                f"contract; the retained recheck records this as "
                f"{zero_term[0]['failure_reason']!r}. The same candidate succeeded on "
                f"{succeeded} of {len(selected_cells)} cells in the parent lineage, so "
                "the empty selection is specific to that system rather than a "
                "uniformly broken implementation."
            ),
        )
    )
    return tuple(defects)


def preregister_baseline_policy(
    *,
    lineage_id: str,
    parent_lineage_id: str,
    frozen_plan_path: Path | str,
    authored_decision_package_path: Path | str,
    parent_identity_path: Path | str,
    prior_baseline_results_path: Path | str,
    prior_full_results_path: Path | str,
    zero_term_evidence_root: Path | str,
    child_runner_sha256: str,
    output_dir: Path | str,
    repinned_image_id: str | None = None,
    clock: datetime | None = None,
) -> PreregisteredBaselinePolicy:
    """Freeze the corrected per-system baseline handling BEFORE any numeric read.

    Every per-system decision is taken from the SYSTEM's own authored resolutions
    in the `268.2` package plus the deterministic mechanism classification in its
    observation. This function chooses no science: it maps an authored resolution
    onto the handling that resolution implies, and refuses any combination that
    would fabricate an effect.
    """

    package_path = Path(authored_decision_package_path)
    package = _load_json(package_path)
    observation = package["observation"]
    proposal = package["proposal"]
    if not package["guard_audit"]["guard_accepted"]:
        raise BaselinePolicyError(
            "the authored decision failed its own guard audit, so it cannot be "
            "carried into a preregistered policy"
        )

    frozen = _load_json(Path(frozen_plan_path))
    parent_plan_hash = str(frozen["plan_hash"])
    # The parent's image and runner come from the parent lineage's OWN frozen
    # identity, so parent and child are bound on the same two quantities.
    parent_identity = _load_json(Path(parent_identity_path))
    parent_image_id = str(parent_identity["image_id"])
    parent_runner_sha256 = str(parent_identity["runner_sha256"])

    baseline_path = Path(prior_baseline_results_path)
    baseline_payload = _load_json(baseline_path)
    # Status and failure strings only. No numeric payload is opened here.
    all_systems: dict[str, str] = {}
    for item in baseline_payload.get("results", []):
        all_systems.setdefault(str(item["system_name"]), str(item.get("data_type", "")))

    resolutions = {
        str(item["system_name"]): item for item in proposal["per_system_resolutions"]
    }
    mechanisms = {
        str(item["system_name"]): item for item in observation["failing_systems"]
    }
    unresolved = sorted(set(mechanisms) - set(resolutions))
    if unresolved:
        raise BaselinePolicyError(
            f"the authored decision carries no resolution for {unresolved}, so their "
            "handling cannot be preregistered"
        )

    systems: list[SystemBaselineHandling] = []
    for system_name in sorted(all_systems):
        data_type = all_systems[system_name] or "unknown"
        failing = mechanisms.get(system_name)
        if failing is None:
            systems.append(
                SystemBaselineHandling(
                    system_name=system_name,
                    data_type=data_type,
                    handling=PAIRED,
                )
            )
            continue
        resolution = resolutions[system_name]
        produces_all_zero = bool(failing["produces_all_zero_model"])
        systems.append(
            SystemBaselineHandling(
                system_name=system_name,
                data_type=data_type,
                handling=EXCLUDED,
                mechanism=str(failing["mechanism"]),
                produces_all_zero_model=produces_all_zero,
                declared_panel_change=(
                    f"{system_name} is removed from the paired panel for this lineage. "
                    f"It failed {failing['failed_cell_count']} of "
                    f"{failing['total_cell_count']} retained baseline cells with "
                    f"mechanism {failing['mechanism']}, and the system's own audited "
                    "resolution is "
                    f"{resolution['resolution_kind']}. It is not scored, not imputed, "
                    "and not credited as a win."
                ),
                power_cost=(
                    "This removes one paired system from the effect and one system "
                    "from the PDE stratum, reducing the evidence available to the "
                    "estimand. The reduced power is carried as a stated limitation "
                    "rather than repaired."
                ),
                system_authored_resolution_kind=str(resolution["resolution_kind"]),
                system_authored_justification=str(resolution["justification"]),
            )
        )

    excluded = tuple(
        sorted(item.system_name for item in systems if item.handling == EXCLUDED)
    )
    paired_count = sum(1 for item in systems if item.handling == PAIRED)
    pde_paired = sum(
        1 for item in systems if item.handling == PAIRED and item.data_type == "pde"
    )
    parent_pde_total = sum(1 for value in all_systems.values() if value == "pde")

    carried = derive_carried_defects(
        authored_decision_package_path=package_path,
        zero_term_evidence_root=zero_term_evidence_root,
        prior_full_results_path=prior_full_results_path,
    )

    now = clock or datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "schema_version": "preregistered-baseline-policy-v1",
        "lineage_id": lineage_id,
        "parent_plan_hash": parent_plan_hash,
        "parent_lineage_id": parent_lineage_id,
        "authored_decision_package_hash": str(package["package_hash"]),
        "authored_decision_package_path": package_path.as_posix(),
        "baseline_results_sha256": file_hash(baseline_path),
        "systems": tuple(item.model_dump(mode="json") for item in systems),
        "excluded_system_names": excluded,
        "paired_system_count": paired_count,
        "parent_paired_system_count": len(all_systems),
        "pde_stratum_size": pde_paired,
        "parent_pde_stratum_size": parent_pde_total,
        "power_cost_statement": (
            f"The paired panel falls from {len(all_systems)} to {paired_count} systems "
            f"and the PDE stratum from {parent_pde_total} to {pde_paired}, because "
            f"{', '.join(excluded) or 'no system'} cannot produce a valid pinned "
            "baseline under the frozen configuration grid. The PDE stratum remains a "
            "directional qualification only and the reduced power is reported as a "
            "limitation, never repaired by forcing a cell to complete."
        ),
        "image_binding": BaselineImageBinding(
            parent_image_id=parent_image_id,
            parent_runner_sha256=parent_runner_sha256,
            child_runner_sha256=child_runner_sha256,
            image_repinned=repinned_image_id is not None,
            new_image_id=repinned_image_id or parent_image_id,
        ).model_dump(mode="json"),
        "carried_defects": tuple(item.model_dump(mode="json") for item in carried),
        "numeric_payload_opened_during_preregistration": False,
        "scores_against_all_zero_baseline": False,
        "is_evidence": False,
        "execution_authorized": False,
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload["policy_hash"] = canonical_model_hash(payload)
    output_path = Path(output_dir).resolve() / _POLICY_NAME
    payload["output_path"] = output_path.as_posix()
    policy = PreregisteredBaselinePolicy.model_validate(payload)
    write_json_model(output_path, policy)
    reloaded = PreregisteredBaselinePolicy.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    if reloaded.policy_hash != policy.policy_hash:
        raise BaselinePolicyError("written policy hash does not match the constructed one")
    return reloaded


def load_baseline_policy(*, output_dir: Path | str) -> PreregisteredBaselinePolicy:
    """Load a persisted policy, validating its hash and every boundary."""

    path = Path(output_dir).resolve() / _POLICY_NAME
    if not path.is_file():
        raise BaselinePolicyError(
            f"no preregistered baseline policy at {path}; the corrected policy must be "
            "frozen before any numeric payload is read"
        )
    return PreregisteredBaselinePolicy.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def assert_policy_precedes_numeric_payload(
    *,
    output_dir: Path | str,
    lineage_dir: Path | str | None = None,
) -> PreregisteredBaselinePolicy:
    """Prove the policy was frozen BEFORE this lineage opened a numeric payload.

    ``numeric_payload_opened_during_preregistration=False`` is a claim the artifact
    makes about itself, and a self-claim is not a proof. This checks the claim against
    the filesystem: if any numeric payload in the lineage is OLDER than the policy,
    then a numeric result existed before the policy was written and the policy could
    have been chosen to suit it. That is the ordering the preregistration exists to
    forbid, so it is refused rather than warned about.

    Only numeric payloads are considered. A cell's `spec.json` and `result.json`
    status/failure strings are what preregistration is allowed to read, so their
    timestamps are irrelevant here.
    """

    policy = load_baseline_policy(output_dir=output_dir)
    root = Path(lineage_dir if lineage_dir is not None else output_dir)
    policy_mtime = (Path(output_dir).resolve() / _POLICY_NAME).stat().st_mtime
    preexisting: list[str] = []
    for pattern in _NUMERIC_PAYLOAD_GLOBS:
        for payload_path in sorted(root.glob(pattern)):
            if payload_path.stat().st_mtime <= policy_mtime:
                preexisting.append(payload_path.as_posix())
    if preexisting:
        raise BaselinePolicyError(
            f"{len(preexisting)} numeric payload(s) in {root.as_posix()} predate the "
            f"preregistered policy (e.g. {preexisting[0]}), so the policy was not "
            "frozen before the numbers were available and cannot be called "
            "preregistered for this lineage"
        )
    return policy
