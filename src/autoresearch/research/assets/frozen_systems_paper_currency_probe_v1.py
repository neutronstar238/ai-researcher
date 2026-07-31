"""Pure-stdlib replay probe for the Task 263.7.0 task-unit analysis."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def addressed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return result


def quantile(values: list[float], probability: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def bootstrap(values: list[float], *, resamples: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(
        statistics.fmean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    )
    return quantile(samples, 0.025), quantile(samples, 0.975)


def sign_test(values: list[float]) -> tuple[int, int, int, float, float]:
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    ties = sum(value == 0 for value in values)
    non_ties = wins + losses
    denominator = 2**non_ties
    upper = sum(math.comb(non_ties, k) for k in range(wins, non_ties + 1)) / denominator
    lower = sum(math.comb(non_ties, k) for k in range(0, wins + 1)) / denominator
    return wins, losses, ties, upper, min(1.0, 2.0 * min(upper, lower))


def project(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "systems-paper-statistical-replay-input-v1":
        raise ValueError("unexpected replay input schema")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 10:
        raise ValueError("replay requires ten task units")
    resamples = int(payload["bootstrap_resamples"])
    seed = int(payload["bootstrap_seed"])
    if resamples != 20_000 or seed != 2604:
        raise ValueError("frozen bootstrap settings changed")
    task_ids = [str(item["task_id"]) for item in tasks]
    families = [str(item["family"]) for item in tasks]
    values = [float(item["difference"]) for item in tasks]
    if len(set(task_ids)) != 10 or set(families) != {"uci", "mdbench"}:
        raise ValueError("replay task identities or families changed")
    family_values: dict[str, list[float]] = defaultdict(list)
    for family, value in zip(families, values, strict=True):
        family_values[family].append(value)
    family_means = {
        family: statistics.fmean(items)
        for family, items in sorted(family_values.items())
    }
    wins, losses, ties, one_sided, two_sided = sign_test(values)
    result = {
        "schema_version": "systems-paper-statistical-projection-v1",
        "task_ids": task_ids,
        "task_families": families,
        "task_differences": values,
        "task_count": 10,
        "seed_pair_count": 30,
        "bootstrap_resamples": resamples,
        "bootstrap_seed": seed,
        "task_mean": statistics.fmean(values),
        "ci95": list(bootstrap(values, resamples=resamples, seed=seed)),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "sign_test_one_sided_p": one_sided,
        "sign_test_two_sided_p": two_sided,
        "family_means": family_means,
        "family_balanced_mean": statistics.fmean(family_means.values()),
    }
    return addressed(result, "projection_sha256")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: probe.py INPUT_JSON OUTPUT_JSON")
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    result = project(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
