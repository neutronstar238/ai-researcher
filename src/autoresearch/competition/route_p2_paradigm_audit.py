"""Task 267.6 Route P2: matched-budget audit of the search paradigm.

What this measures
------------------
`arXiv:2607.04108` audited the loop this project used -- generate candidates,
select winners, feed them back as parents -- and found that under MATCHED LLM-call
budgets, parent-conditioned evolution is statistically indistinguishable from
fresh independent sampling (median OOD NMSE 0.045 vs 0.049), with final success
predicted by initial proposal quality rather than by iteration.

This module runs that comparison on the frozen Task `266.1.1` sentinels:

* ``parent_conditioned_evolution`` -- one initial proposal, then K-1 sequential
  repairs, each conditioned on the parent source and its observed failures. This
  is exactly what the existing Harness does.
* ``independent_sampling_set_level`` -- K independent proposals with identical
  context, no parent and no failure feedback, then train-only selection over the
  pooled results.

Both arms spend the same number of model calls, which is the condition under which
the audit result holds. An unmatched comparison could neither replicate nor refute
it.

Why either outcome is publishable
---------------------------------
The reported quantity is the paired effect and its interval, not a win. Under the
Task `267.6` preregistration an informative null REPLICATES the audit finding,
while an interval wider than twice the preregistered minimum detectable effect is
refused as underpowered rather than reported as "no effect".

Boundaries
----------
* Selection inside each arm uses train-only evidence. The evaluator's own
  pass/fail verdict is never used to pick a winner, or the comparison would be
  contaminated by the outcome it is trying to measure.
* Every model interaction is recorded with provenance by the existing helper.
* This module supplies no scientific method. It arranges calls and counts cells.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.autonomous_engine import (
    JsonCompletion,
    _call_and_record,
)
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.scientific_contract_harness import (
    _RUNNER_SOURCE,
    _SOURCE_RESPONSE_SCHEMA,
    ScientificContractHarnessError,
    ScientificContractRuntimeEnvironment,
    ScientificContractSourceResponse,
    build_scientific_interface_contract,
    execute_scientific_contract_container,
    inspect_scientific_contract_runtime,
    review_scientific_contract_source,
)
from autoresearch.competition.scientific_contract_recovery import (
    load_scientific_contract_recovery_plan,
)
from autoresearch.competition.sentinel_identifiability import (
    load_corrected_sentinel_fixtures,
    load_sentinel_identifiability_erratum,
)
from autoresearch.llm.client import run_llm_json_completion

ArmId = Literal["independent_sampling_set_level", "parent_conditioned_evolution"]

_PACKAGE_NAME = "route-p2-paradigm-audit-package.json"
_BOOTSTRAP_RESAMPLES = 2_000
_BOOTSTRAP_SEED = 2676
# Matches the frozen Task 266.1 estimand so the two are comparable.
_LOSS_CAP = 1e12
# The frozen Task 266.1 estimand uses a 1e-12 floor, which suits noisy official
# MDBench cells. It is far too coarse here: the synthetic sentinels admit near-exact
# fits, and live run v2 produced prediction NMSE between 2.4e-32 and 4.5e-28. Every
# one of those clipped to 1e-12, flattening both arms to identical losses and
# reporting a genuine log ratio of 5.80 as exactly 0.0. The floor is therefore set
# below double precision resolution so it only guards log(0), never real signal.
_LOSS_FLOOR = 1e-300


class RouteP2AuditError(RuntimeError):
    """Raised when a Route P2 boundary cannot be proved."""


class ArmCellResult(StrictFrozenModel):
    """One executed candidate measured on one sentinel."""

    arm_id: ArmId
    proposal_index: int = Field(ge=1)
    sentinel_id: str
    data_type: Literal["ode", "pde"]
    candidate_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Train-only quantity, usable for selection.
    training_nmse: float | None = None
    # Held-out quantity, used ONLY for the reported effect, never for selection.
    prediction_nmse: float | None = None
    passed: bool
    failure_codes: tuple[str, ...] = ()


class ArmOutcome(StrictFrozenModel):
    """One arm's selected implementation and its per-sentinel losses."""

    arm_id: ArmId
    model_call_count: int = Field(ge=1)
    proposal_count: int = Field(ge=1)
    generations: int = Field(ge=1)
    selected_proposal_index: int = Field(ge=1)
    selection_basis: Literal["train_only_median_nmse"] = "train_only_median_nmse"
    per_sentinel_loss: dict[str, float]
    cells: tuple[ArmCellResult, ...]

    @model_validator(mode="after")
    def _validate_arm(self) -> ArmOutcome:
        if self.arm_id == "independent_sampling_set_level" and self.generations != 1:
            raise RouteP2AuditError("the independent arm is one-generation by construction")
        if self.arm_id == "parent_conditioned_evolution" and self.generations < 2:
            raise RouteP2AuditError("the evolutionary arm requires at least two generations")
        return self


class RouteP2AuditPackage(StrictFrozenModel):
    """Complete, hash-bound Route P2 comparison evidence."""

    schema_version: Literal["route-p2-paradigm-audit-package-v1"] = (
        "route-p2-paradigm-audit-package-v1"
    )
    preregistration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    erratum_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_model_call_budget: int = Field(ge=2)
    reasoning_mode: Literal["disabled", "enabled"]
    arms: tuple[ArmOutcome, ...] = Field(min_length=2, max_length=2)
    paired_effects: dict[str, float]
    median_paired_effect: float
    bootstrap_lower: float
    bootstrap_upper: float
    bootstrap_resamples: int = Field(ge=1_000)
    ode_stratum_median: float | None = None
    pde_stratum_median: float | None = None
    # Route P2 reports an effect, never a method claim.
    official_development_result_count: Literal[0] = 0
    confirmation_identity_read_count: Literal[0] = 0
    system_generated_manuscript_count: Literal[0] = 0
    publication_ready: Literal[False] = False
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate_package(self) -> RouteP2AuditPackage:
        arm_ids = {item.arm_id for item in self.arms}
        if arm_ids != {
            "independent_sampling_set_level",
            "parent_conditioned_evolution",
        }:
            raise RouteP2AuditError("both named arms are required")
        budgets = {item.model_call_count for item in self.arms}
        if budgets != {self.matched_model_call_budget}:
            raise RouteP2AuditError(
                "arms must spend an identical model-call budget to be comparable"
            )
        if not self.bootstrap_lower <= self.median_paired_effect <= self.bootstrap_upper:
            raise RouteP2AuditError("median effect must lie inside its interval")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"package_hash", "output_path"})
        )
        if self.package_hash != expected:
            raise RouteP2AuditError("Route P2 package hash mismatch")
        return self


def _clip(value: float | None) -> float:
    """Clip a loss into the frozen estimand bounds, penalising a failed cell."""

    if value is None or not math.isfinite(value):
        return _LOSS_CAP
    return min(max(value, _LOSS_FLOOR), _LOSS_CAP)


def _paired_effect(evolution_loss: float, independent_loss: float) -> float:
    """Positive means evolution produced the LOWER loss, matching the frozen sign."""

    return math.log(_clip(independent_loss) / _clip(evolution_loss))


def _bootstrap_median_interval(
    values: Sequence[float],
    *,
    resamples: int = _BOOTSTRAP_RESAMPLES,
    seed: int = _BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Fixed-seed percentile bootstrap over independent sentinels."""

    if not values:
        raise RouteP2AuditError("bootstrap requires at least one sentinel effect")
    generator = random.Random(seed)
    medians = []
    count = len(values)
    for _ in range(resamples):
        sample = [values[generator.randrange(count)] for _ in range(count)]
        medians.append(_median(sample))
    medians.sort()
    lower = medians[int(0.025 * (resamples - 1))]
    upper = medians[int(0.975 * (resamples - 1))]
    return lower, upper


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _independent_messages(brief: dict[str, Any]) -> list[dict[str, str]]:
    """Identical context for every independent proposal: no parent, no feedback."""

    return [
        {
            "role": "system",
            "content": (
                "You are the autonomous scientist authoring an equation-discovery "
                "method. Return exactly one JSON object matching the supplied schema. "
                "Encode exact standalone Python as the JSON array source_lines, one "
                "array element per physical line, with no newline escapes anywhere. "
                "The source MUST define exactly the two top-level functions "
                "fit_equations(payload) and predict_derivative(payload), each taking "
                "one positional argument. Obey static_source_contract in the supplied "
                "interface_contract: only allowlisted imports, no classes, no lambdas, "
                "no async, no while loops, no attribute mutation, no print, no dunder "
                "access, no dynamic execution, and no top-level statements other than "
                "imports, literal constants, and function definitions. Derive equations "
                "only from the fit payload's training arrays."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(brief, ensure_ascii=False, sort_keys=True),
        },
    ]


def _evolution_messages(
    brief: dict[str, Any],
    *,
    parent_source: str,
    parent_failures: Sequence[str],
) -> list[dict[str, str]]:
    """Parent-conditioned context: the previous source and what it got wrong."""

    messages = _independent_messages(brief)
    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                {
                    "previous_attempt_source": parent_source,
                    "previous_attempt_failures": list(parent_failures),
                    "instruction": (
                        "Improve on the previous attempt. Return a complete "
                        "replacement as source_lines."
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
    )
    return messages


def run_route_p2_paradigm_audit(
    *,
    output_dir: Path | str,
    preregistration_hash: str,
    plan_path: Path | str,
    erratum_path: Path | str,
    matched_model_call_budget: int = 4,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    provider_timeout_seconds: int = 300,
    container_timeout_seconds: int = 600,
    completion: JsonCompletion = run_llm_json_completion,
    clock: Callable[[], datetime] | None = None,
    runtime_environment: ScientificContractRuntimeEnvironment | None = None,
) -> RouteP2AuditPackage:
    """Execute both arms under a matched budget and report the paired effect."""

    if matched_model_call_budget < 2:
        raise RouteP2AuditError(
            "the evolutionary arm needs at least two calls to have a parent"
        )
    now = clock or (lambda: datetime.now(timezone.utc))
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    plan = load_scientific_contract_recovery_plan(plan_path)
    erratum = load_sentinel_identifiability_erratum(erratum_path)
    fixtures = load_corrected_sentinel_fixtures(erratum_path)
    runtime = runtime_environment or inspect_scientific_contract_runtime()
    runner_path = output_root / "runner" / _RUNNER_SOURCE.name
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    if not runner_path.is_file():
        runner_path.write_bytes(_RUNNER_SOURCE.read_bytes())

    # Reuse the SAME full interface contract the Harness gives its candidates.
    # A thinner brief is not a fair test of the search paradigm: the first attempt
    # produced 8/8 static-review rejections (`missing_interface`,
    # `dynamic_structure`, `module_mutation`) in BOTH arms, so every cell took the
    # worst-case loss and the paired effect was a trivial zero. That measured the
    # brief, not the paradigm.
    brief = {
        "task": (
            "author a fit-once/freeze/predict equation-discovery candidate for ODE "
            "and PDE systems"
        ),
        "objective": "minimise derivative NMSE under the frozen sentinels",
        "interface_contract": build_scientific_interface_contract(),
        "contract_gate": plan.contract_gate.model_dump(mode="json"),
        "sentinel_shapes": [
            {
                "data_type": item.data_type,
                "spatial_dimensions": item.spatial_dimensions,
                "field_count": len(item.field_names),
                "train_shape": list(item.train_state.shape),
                "query_shape": list(item.queries[0].state.shape),
            }
            for item in fixtures
        ],
    }

    arms: list[ArmOutcome] = []
    for arm_id in (
        "independent_sampling_set_level",
        "parent_conditioned_evolution",
    ):
        arm_cells: list[ArmCellResult] = []
        parent_source: str | None = None
        parent_failures: tuple[str, ...] = ()
        for index in range(1, matched_model_call_budget + 1):
            interaction_id = f"route-p2-{arm_id}-{index:02d}"
            if arm_id == "parent_conditioned_evolution" and parent_source is not None:
                messages = _evolution_messages(
                    brief,
                    parent_source=parent_source,
                    parent_failures=parent_failures,
                )
            else:
                messages = _independent_messages(brief)
            result, _ = _call_and_record(
                completion=completion,
                messages=messages,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=provider_timeout_seconds,
                max_tokens=12_000,
                response_schema=_SOURCE_RESPONSE_SCHEMA,
                response_schema_name="scientific_contract_source",
                interaction_id=interaction_id,
                stage="scientific_contract_implementation",
                candidate_id=f"{arm_id}-{index:02d}",
                output_root=output_root,
                now=now,
            )
            response = ScientificContractSourceResponse.model_validate(result.parsed_json)
            source_text = response.source_text
            candidate_path = (
                output_root / "candidates" / f"{arm_id}-{index:02d}" / "candidate.py"
            )
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            with candidate_path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(source_text)

            review = review_scientific_contract_source(source_text)
            if not review.approved:
                codes = tuple(f"static:{item.code}" for item in review.findings)
                for fixture in fixtures:
                    arm_cells.append(
                        ArmCellResult(
                            arm_id=arm_id,  # type: ignore[arg-type]
                            proposal_index=index,
                            sentinel_id=fixture.sentinel_id,
                            data_type=fixture.data_type,
                            candidate_source_sha256=review.source_sha256,
                            passed=False,
                            failure_codes=codes,
                        )
                    )
                parent_source, parent_failures = source_text, codes
                continue

            try:
                observation = execute_scientific_contract_container(
                    candidate_path=candidate_path,
                    runner_path=runner_path,
                    fixtures=fixtures,
                    plan=plan,
                    erratum=erratum,
                    runtime=runtime,
                    timeout_seconds=container_timeout_seconds,
                )
            except ScientificContractHarnessError as exc:
                codes = ("container:execution_error",)
                for fixture in fixtures:
                    arm_cells.append(
                        ArmCellResult(
                            arm_id=arm_id,  # type: ignore[arg-type]
                            proposal_index=index,
                            sentinel_id=fixture.sentinel_id,
                            data_type=fixture.data_type,
                            candidate_source_sha256=review.source_sha256,
                            passed=False,
                            failure_codes=codes,
                        )
                    )
                parent_source = source_text
                parent_failures = (str(exc)[:400],)
                continue

            write_json_model(
                output_root / "observations" / f"{arm_id}-{index:02d}.json",
                observation,
            )
            failures: list[str] = []
            for item in observation.sentinel_results:
                diagnostics = (item.get("primary_artifact") or {}).get(
                    "diagnostics"
                ) or {}
                codes = tuple(item.get("failure_codes", ()))
                failures.extend(codes)
                arm_cells.append(
                    ArmCellResult(
                        arm_id=arm_id,  # type: ignore[arg-type]
                        proposal_index=index,
                        sentinel_id=str(item.get("sentinel_id")),
                        data_type=str(item.get("data_type")),  # type: ignore[arg-type]
                        candidate_source_sha256=observation.candidate_source_sha256,
                        training_nmse=diagnostics.get("training_nmse"),
                        prediction_nmse=item.get("primary_prediction_nmse"),
                        passed=bool(item.get("passed")),
                        failure_codes=codes,
                    )
                )
            parent_source = source_text
            parent_failures = tuple(dict.fromkeys(failures))[:12]

        arms.append(
            _select_arm_outcome(
                arm_id=arm_id,  # type: ignore[arg-type]
                cells=tuple(arm_cells),
                model_call_count=matched_model_call_budget,
                generations=1
                if arm_id == "independent_sampling_set_level"
                else matched_model_call_budget,
            )
        )

    return _finalize_package(
        output_root=output_root,
        preregistration_hash=preregistration_hash,
        plan_hash=plan.plan_hash,
        erratum_hash=erratum.erratum_hash,
        runner_sha256=_file_sha256(runner_path),
        runtime=runtime,
        matched_model_call_budget=matched_model_call_budget,
        arms=tuple(arms),
        fixtures=fixtures,
    )


def _select_arm_outcome(
    *,
    arm_id: ArmId,
    cells: tuple[ArmCellResult, ...],
    model_call_count: int,
    generations: int,
) -> ArmOutcome:
    """Pick the arm's winner using TRAIN-ONLY evidence.

    Using the evaluator's verdict here would contaminate the comparison with the
    outcome it is trying to measure.
    """

    if not cells:
        raise RouteP2AuditError(f"arm {arm_id} produced no cells")
    indices = sorted({item.proposal_index for item in cells})
    best_index, best_loss = indices[0], math.inf
    for index in indices:
        losses = [
            _clip(item.training_nmse)
            for item in cells
            if item.proposal_index == index
        ]
        candidate_loss = _median(losses) if losses else math.inf
        if candidate_loss < best_loss:
            best_index, best_loss = index, candidate_loss
    selected = [item for item in cells if item.proposal_index == best_index]
    return ArmOutcome(
        arm_id=arm_id,
        model_call_count=model_call_count,
        proposal_count=len(indices),
        generations=generations,
        selected_proposal_index=best_index,
        per_sentinel_loss={
            item.sentinel_id: _clip(item.prediction_nmse) for item in selected
        },
        cells=cells,
    )


def _finalize_package(
    *,
    output_root: Path,
    preregistration_hash: str,
    plan_hash: str,
    erratum_hash: str,
    runner_sha256: str,
    runtime: ScientificContractRuntimeEnvironment,
    matched_model_call_budget: int,
    arms: tuple[ArmOutcome, ...],
    fixtures: Sequence[Any],
) -> RouteP2AuditPackage:
    """Compute the paired effect, its interval, and the strata medians."""

    evolution = next(
        item for item in arms if item.arm_id == "parent_conditioned_evolution"
    )
    independent = next(
        item for item in arms if item.arm_id == "independent_sampling_set_level"
    )
    shared = sorted(set(evolution.per_sentinel_loss) & set(independent.per_sentinel_loss))
    if not shared:
        raise RouteP2AuditError("arms share no sentinel, so no paired effect exists")

    # Guard against a degenerate comparison. If every cell in both arms hit the
    # worst-case loss, the paired effect is a trivial zero that measures nothing.
    # The first live attempt did exactly this: 8/8 candidates failed static review,
    # so the effect was 0.0 with a zero-width interval. Reporting that as an
    # informative null would have been a false finding.
    if all(
        _clip(value) >= _LOSS_CAP
        for arm in (evolution, independent)
        for value in arm.per_sentinel_loss.values()
    ):
        raise RouteP2AuditError(
            "every cell in both arms took the worst-case loss, so no candidate ever "
            "executed. The paired effect would be a trivial zero that measures the "
            "prompt rather than the search paradigm; fix candidate viability first."
        )

    effects = {
        key: _paired_effect(
            evolution.per_sentinel_loss[key],
            independent.per_sentinel_loss[key],
        )
        for key in shared
    }
    values = [effects[key] for key in shared]
    median_effect = _median(values)
    lower, upper = _bootstrap_median_interval(values)

    data_types = {item.sentinel_id: item.data_type for item in fixtures}
    ode_values = [effects[key] for key in shared if data_types.get(key) == "ode"]
    pde_values = [effects[key] for key in shared if data_types.get(key) == "pde"]

    payload: dict[str, Any] = {
        "schema_version": "route-p2-paradigm-audit-package-v1",
        "preregistration_hash": preregistration_hash,
        "plan_hash": plan_hash,
        "erratum_hash": erratum_hash,
        "runner_sha256": runner_sha256,
        "runtime_environment_hash": runtime.environment_hash,
        "matched_model_call_budget": matched_model_call_budget,
        # Factual: the provenance helper records thinking_mode="disabled".
        "reasoning_mode": "disabled",
        "arms": [item.model_dump(mode="json") for item in arms],
        "paired_effects": effects,
        "median_paired_effect": median_effect,
        "bootstrap_lower": lower,
        "bootstrap_upper": upper,
        "bootstrap_resamples": _BOOTSTRAP_RESAMPLES,
        "ode_stratum_median": _median(ode_values) if ode_values else None,
        "pde_stratum_median": _median(pde_values) if pde_values else None,
        "official_development_result_count": 0,
        "confirmation_identity_read_count": 0,
        "system_generated_manuscript_count": 0,
        "publication_ready": False,
    }
    payload["package_hash"] = canonical_model_hash(payload)
    payload["output_path"] = (output_root / _PACKAGE_NAME).as_posix()
    package = RouteP2AuditPackage.model_validate(payload)
    write_json_model(output_root / _PACKAGE_NAME, package)
    return package


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
