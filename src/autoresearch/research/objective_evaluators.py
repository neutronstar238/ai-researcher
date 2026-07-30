"""Deterministic, model-free evaluators for the open objective task panel.

The functions in this module deliberately have no network, model, or framework
dependencies.  Task 263.4.1 pins the byte hash of this file; Task 263.4.2 must
freeze task-specific success thresholds before any confirmatory predictions are
revealed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence


def classification_balanced_accuracy(
    y_true: Sequence[str],
    y_pred: Sequence[str],
) -> float:
    """Return macro-average recall across classes present in ``y_true``."""

    if not y_true or len(y_true) != len(y_pred):
        raise ValueError("classification labels must be non-empty and aligned")

    totals: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    for expected, observed in zip(y_true, y_pred, strict=True):
        if not expected or not observed:
            raise ValueError("classification labels must be non-empty strings")
        totals[expected] += 1
        if expected == observed:
            correct[expected] += 1
    return sum(correct[label] / totals[label] for label in totals) / len(totals)


def regression_r2(
    y_true: Sequence[float],
    y_pred: Sequence[float],
) -> float:
    """Return the deterministic coefficient of determination."""

    if not y_true or len(y_true) != len(y_pred):
        raise ValueError("regression values must be non-empty and aligned")
    expected = [float(value) for value in y_true]
    observed = [float(value) for value in y_pred]
    if not all(math.isfinite(value) for value in expected + observed):
        raise ValueError("regression values must be finite")

    mean = sum(expected) / len(expected)
    denominator = sum((value - mean) ** 2 for value in expected)
    if denominator <= 0:
        raise ValueError("R2 requires non-constant reference values")
    numerator = sum(
        (reference - prediction) ** 2
        for reference, prediction in zip(expected, observed, strict=True)
    )
    return 1.0 - numerator / denominator


def meets_frozen_success_threshold(
    *,
    score: float,
    threshold: float,
    higher_is_better: bool,
    artifact_valid: bool,
    replay_valid: bool,
    budget_valid: bool,
) -> bool:
    """Return task success from frozen numeric and integrity evidence."""

    if not math.isfinite(score) or not math.isfinite(threshold):
        raise ValueError("score and threshold must be finite")
    metric_passed = score >= threshold if higher_is_better else score <= threshold
    return metric_passed and artifact_valid and replay_valid and budget_valid
