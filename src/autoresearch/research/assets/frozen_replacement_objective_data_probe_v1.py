"""Dependency-free candidate admission projection for Task 263.6.6.

The runner receives only result-blind lineage group identifiers, prospective
capacity bounds, and pre-outcome gate observations. It never receives task
prompts, reference programs, answers, model outputs, evaluator outputs, or
reserve labels. Candidate names are data: the runner requires at least four
distinct candidates but does not contain a preferred benchmark or winner.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

GATE_NAMES = (
    "revision",
    "lineage",
    "license",
    "objective_endpoint",
    "construct_coherence",
    "strong_baseline",
    "bounded_local_compute",
    "reserve_seal",
)
GATE_BLOCKERS = {
    "revision": "official-revisions-not-fully-frozen",
    "lineage": "independent-source-lineage-incomplete",
    "license": "per-source-license-gate-failed",
    "objective_endpoint": "deterministic-primary-endpoint-gate-failed",
    "construct_coherence": "construct-coherence-gate-failed",
    "strong_baseline": "strong-baseline-unavailable",
    "bounded_local_compute": "bounded-local-compute-gate-failed",
    "reserve_seal": "reserve-seal-gate-failed",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return value


def _require_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _candidate_projection(
    candidate: dict[str, Any],
    *,
    required_development: int,
    required_reserve: int,
) -> dict[str, Any]:
    candidate_id = candidate.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a non-empty string")
    group_ids = candidate.get("capacity_group_ids")
    if not isinstance(group_ids, list) or not all(
        isinstance(item, str) and item for item in group_ids
    ):
        raise ValueError(f"{candidate_id}: capacity_group_ids must be strings")
    if len(set(group_ids)) != len(group_ids):
        raise ValueError(f"{candidate_id}: duplicate capacity group identifier")
    group_ids = sorted(group_ids)

    task_count = _require_int(
        candidate.get("task_count"),
        field=f"{candidate_id}.task_count",
        minimum=1,
    )
    unlineaged = _require_int(
        candidate.get("declared_unlineaged_group_upper_bound"),
        field=f"{candidate_id}.declared_unlineaged_group_upper_bound",
    )
    development_capacity = _require_int(
        candidate.get("development_group_capacity"),
        field=f"{candidate_id}.development_group_capacity",
    )
    potential_reserve = _require_int(
        candidate.get("potential_reserve_group_capacity"),
        field=f"{candidate_id}.potential_reserve_group_capacity",
    )
    sealed_reserve = _require_int(
        candidate.get("sealed_reserve_group_capacity"),
        field=f"{candidate_id}.sealed_reserve_group_capacity",
    )
    independent_upper_bound = len(group_ids) + unlineaged
    if independent_upper_bound > task_count:
        raise ValueError(
            f"{candidate_id}: independent group upper bound exceeds task count"
        )
    if development_capacity + potential_reserve > independent_upper_bound:
        raise ValueError(
            f"{candidate_id}: development plus reserve exceeds group upper bound"
        )
    if sealed_reserve > potential_reserve:
        raise ValueError(
            f"{candidate_id}: sealed reserve exceeds potential reserve"
        )

    gates = candidate.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(GATE_NAMES):
        raise ValueError(f"{candidate_id}: exact gate vector is required")
    normalized_gates = {
        name: _require_bool(
            gates[name],
            field=f"{candidate_id}.gates.{name}",
        )
        for name in GATE_NAMES
    }
    if normalized_gates["lineage"] and unlineaged:
        raise ValueError(
            f"{candidate_id}: lineage cannot pass with unlineaged groups"
        )
    if normalized_gates["reserve_seal"] and sealed_reserve != potential_reserve:
        raise ValueError(
            f"{candidate_id}: reserve seal cannot pass for a partial reserve"
        )

    blockers = [
        GATE_BLOCKERS[name] for name in GATE_NAMES if not normalized_gates[name]
    ]
    if development_capacity < required_development:
        blockers.append("development-source-groups-below-required")
    if potential_reserve < required_reserve:
        blockers.append("potential-reserve-source-groups-below-required")
    if sealed_reserve < required_reserve:
        blockers.append("sealed-reserve-source-groups-below-required")
    blockers = sorted(set(blockers))

    projection = {
        "schema_version": "replacement-candidate-projection-v1",
        "candidate_id": candidate_id,
        "task_count": task_count,
        "lineaged_capacity_group_count": len(group_ids),
        "declared_unlineaged_group_upper_bound": unlineaged,
        "independent_group_upper_bound": independent_upper_bound,
        "development_group_capacity": development_capacity,
        "potential_reserve_group_capacity": potential_reserve,
        "sealed_reserve_group_capacity": sealed_reserve,
        "required_development_groups": required_development,
        "required_reserve_groups": required_reserve,
        "passed_gate_count": sum(normalized_gates.values()),
        "gates": normalized_gates,
        "blockers": blockers,
        "eligible": not blockers,
    }
    projection["projection_sha256"] = _sha256(projection)
    return projection


def _tournament_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != (
        "replacement-objective-data-replay-input-v1"
    ):
        raise ValueError("unsupported replay input schema")
    if payload.get("outcome_values_included") is not False:
        raise ValueError("outcome values must not enter the replay")
    if payload.get("candidate_model_calls_run") is not False:
        raise ValueError("candidate model calls are forbidden before admission")
    if payload.get("heterogeneous_post_result_combination_allowed") is not False:
        raise ValueError("post-result benchmark combination must remain forbidden")

    required_development = _require_int(
        payload.get("required_development_groups"),
        field="required_development_groups",
        minimum=1,
    )
    required_reserve = _require_int(
        payload.get("required_reserve_groups"),
        field="required_reserve_groups",
        minimum=1,
    )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 4:
        raise ValueError("at least four candidate panels are required")
    if not all(isinstance(item, dict) for item in candidates):
        raise ValueError("candidate records must be objects")
    ids = [item.get("candidate_id") for item in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("candidate identifiers must be unique")

    projections = [
        _candidate_projection(
            item,
            required_development=required_development,
            required_reserve=required_reserve,
        )
        for item in candidates
    ]
    ranked = sorted(
        projections,
        key=lambda item: (
            -int(item["eligible"]),
            -item["passed_gate_count"],
            -item["sealed_reserve_group_capacity"],
            -item["development_group_capacity"],
            item["candidate_id"],
        ),
    )
    eligible = [item["candidate_id"] for item in ranked if item["eligible"]]
    selected = eligible[0] if eligible else None
    decision = {
        "schema_version": "replacement-tournament-decision-v1",
        "status": (
            "candidate-qualified-for-baseline-reproduction"
            if selected is not None
            else "all-candidates-rejected"
        ),
        "selected_candidate_id": selected,
        "eligible_candidate_ids": eligible,
        "ranked_candidate_ids": [item["candidate_id"] for item in ranked],
        "candidate_projection_hashes": {
            item["candidate_id"]: item["projection_sha256"]
            for item in sorted(projections, key=lambda value: value["candidate_id"])
        },
        "baseline_reproduction_authorized": selected is not None,
        "evaluator_or_critic_construction_authorized": False,
        "provider_credentials_collected": False,
        "research_question_issued": False,
        "confirmation_panel_created_or_read": False,
        "heterogeneous_post_result_combination_authorized": False,
        "publication_claim_authorized": False,
        "public_release_authorized": False,
        "submission_authorized": False,
        "next_action": (
            "reproduce-qualified-strong-baseline-before-rq"
            if selected is not None
            else "repair-or-broaden-objective-data-before-model-calls"
        ),
    }
    decision["decision_sha256"] = _sha256(decision)
    result = {
        "schema_version": "replacement-tournament-projection-v1",
        "candidate_projections": sorted(
            projections, key=lambda item: item["candidate_id"]
        ),
        "decision": decision,
    }
    result["projection_sha256"] = _sha256(result)
    return result


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: frozen_replacement_objective_data_probe_v1.py INPUT"
        )
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("replay input must be a JSON object")
    result = _tournament_projection(payload)
    sys.stdout.write(
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
