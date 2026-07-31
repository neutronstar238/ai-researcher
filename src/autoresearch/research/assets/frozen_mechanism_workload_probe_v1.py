"""Frozen, dependency-free workload probe for task 263.6.4.

This executable does not score scientific outcomes.  It exercises three
representative mechanism kernels with a fixed algorithmic work-unit budget and
emits an exact deterministic projection plus non-scientific runtime telemetry.
The parent qualification harness owns orchestration deadlines and concurrency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
import tracemalloc
from typing import Any

MASK_64 = (1 << 64) - 1
TRACKS = {
    "external-feedback",
    "socratic-falsification",
    "structured-world-model",
}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _structured_world_model(*, work_units: int, seed: int) -> dict[str, int | str]:
    accumulator = seed & MASK_64
    supported = 0
    contradictions = 0
    frontier = [((seed + index * 104_729) & MASK_64) for index in range(257)]
    for index in range(work_units):
        left = frontier[index % 257]
        right_index = (index * 17 + 29) % 257
        right = frontier[right_index]
        relation = (
            left
            ^ ((right << 13) & MASK_64)
            ^ (right >> 7)
            ^ (index * 0x9E3779B185EBCA87)
        ) & MASK_64
        evidence = ((relation >> 11) ^ (relation >> 37) ^ index) & 0xFF
        supported += int(evidence < 173)
        contradictions += int(evidence in {17, 31, 127, 251})
        accumulator = (
            accumulator * 6_364_136_223_846_793_005
            + relation
            + 1_442_695_040_888_963_407
        ) & MASK_64
        frontier[right_index] = accumulator
    return {
        "coherence_digest": f"{accumulator:016x}",
        "contradictions": contradictions,
        "supported_relations": supported,
    }


def _socratic_falsification(*, work_units: int, seed: int) -> dict[str, int | str]:
    state = seed & MASK_64
    causal_failures = 0
    constraint_failures = 0
    counterexamples = 0
    falsifiers = 0
    for index in range(work_units):
        state = (
            state * 2_862_933_555_777_941_757
            + 3_037_000_493
            + index * 97
        ) & MASK_64
        causal = (state ^ (state >> 19) ^ index) & 0x3FF
        constraint = ((state >> 13) + index * 11) & 0x1FF
        counterexample = ((state >> 29) ^ (index * 131)) & 0xFF
        falsifier = ((state >> 43) + causal + constraint) & 0x7F
        causal_failures += int(causal % 19 == 0)
        constraint_failures += int(constraint % 23 == 0)
        counterexamples += int(counterexample in {3, 5, 8, 13, 21})
        falsifiers += int(falsifier < 9)
    return {
        "causal_failures": causal_failures,
        "constraint_failures": constraint_failures,
        "counterexamples": counterexamples,
        "falsification_digest": f"{state:016x}",
        "falsifiers": falsifiers,
    }


def _external_feedback(*, work_units: int, seed: int) -> dict[str, int | str]:
    state = seed & 0xFFFFFFFF
    accepted = 0
    rejected = 0
    interventions = 0
    reward_sum = 0
    for index in range(work_units):
        proposed = (
            state * 1_664_525 + 1_013_904_223 + index * 31
        ) & 0xFFFFFFFF
        observation = (
            proposed ^ (proposed >> 15) ^ (index * 2_654_435_761)
        ) & 0xFFFFFFFF
        constraint_ok = (observation % 29) not in {0, 1, 2}
        human_gate = ((observation >> 9) & 0x3F) != 0
        if constraint_ok and human_gate:
            accepted += 1
            state = (proposed + observation) & 0xFFFFFFFF
            reward_sum += int((observation >> 17) & 0x3F)
        else:
            rejected += 1
            interventions += int(not human_gate)
            state = (state ^ (observation >> 3) ^ index) & 0xFFFFFFFF
    return {
        "accepted_actions": accepted,
        "environment_digest": f"{state:08x}",
        "human_interventions": interventions,
        "rejected_actions": rejected,
        "reward_sum": reward_sum,
    }


def run_probe(*, track_id: str, work_units: int, seed: int) -> dict[str, Any]:
    if track_id not in TRACKS:
        raise ValueError(f"unknown track_id: {track_id}")
    if work_units < 1:
        raise ValueError("work_units must be positive")

    tracemalloc.start()
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    if track_id == "structured-world-model":
        projection = _structured_world_model(work_units=work_units, seed=seed)
    elif track_id == "socratic-falsification":
        projection = _socratic_falsification(work_units=work_units, seed=seed)
    else:
        projection = _external_feedback(work_units=work_units, seed=seed)
    cpu_seconds = time.process_time() - cpu_started
    elapsed_seconds = time.perf_counter() - wall_started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "schema_version": "mechanism-workload-output-v1",
        "track_id": track_id,
        "algorithmic_work_units": work_units,
        "projection": projection,
        "projection_hash": _canonical_sha256(projection),
        "telemetry": {
            "algorithmic_cpu_seconds": cpu_seconds,
            "algorithmic_elapsed_seconds": elapsed_seconds,
            "interpreter_implementation": platform.python_implementation(),
            "peak_traced_bytes": peak_bytes,
            "python_version": platform.python_version(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track-id", required=True, choices=sorted(TRACKS))
    parser.add_argument("--work-units", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    arguments = parser.parse_args()
    result = run_probe(
        track_id=arguments.track_id,
        work_units=arguments.work_units,
        seed=arguments.seed,
    )
    sys.stdout.write(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
