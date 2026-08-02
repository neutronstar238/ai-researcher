"""Task 267.5: dictionary construction plus train-only set-level selection.

Replaces parent-conditioned multi-generation evolution as the PRIMARY search.

Why this exists
---------------
`arXiv:2607.04108` ("Dictionaries, Not Darwin") audited exactly the loop this
project used -- generate candidates, select winners, feed them back as parents --
and found that under matched LLM-call budgets, parent-conditioned evolution is
statistically indistinguishable from fresh independent sampling (median OOD NMSE
0.045 vs 0.049), instructed multi-parent crossover is worse, and final success is
predicted by initial proposal quality rather than by iteration. Operationally the
loop reduces to what it produces: a dictionary of candidate terms. Set-level
selectors solved 165-169 of 717 cells where single-term reductions solved 74-78.

Two further constraints come from adjacent 2026 work:

* `arXiv:2605.29184` (IGSR): scalar-metric feedback cannot attribute per-term
  credit, so this module reports per-term influence rather than one NMSE.
* `arXiv:2607.13608` (MEDA): numerical fitting alone retains trajectory-
  compatible but scientifically wrong equations, so a fit that is equivalent to
  the zero null is rejected instead of being scored.

The zero-null rejection is not theoretical here. Task 265.3 selected `branch-08`
with derivative NMSE `0.9999999999988402` and training-context sensitivity `0`:
a fit numerically indistinguishable from predicting zero.

Design boundaries
-----------------
* Deliberately dependency-free. Scientific packages live in the pinned container,
  so a small dense least-squares solve is implemented here directly. Term counts
  are bounded (at most 64 per equation by contract), so normal equations with
  ridge-stabilized Gaussian elimination are appropriate and keep this module
  testable outside the container.
* Selection reads TRAIN data only. Nothing in this module may see validation,
  test, or confirmation payloads.
* The evolutionary arm is retained only as a preregistered matched-budget
  comparator (Task 267.6 Route P2), never as the default engine.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

# Matches the exact factor whitelist enforced by the Harness runner and
# advertised by `build_scientific_interface_contract` (Task 267.1).
FactorKey = tuple[str, tuple[str, ...], int]

_MAX_TERMS_PER_EQUATION = 64
_RIDGE = 1e-10
_ZERO_NULL_NMSE_FLOOR = 0.999
_MIN_TRAIN_SENSITIVITY = 1e-9


class TermDictionaryError(ValueError):
    """Raised when dictionary construction or selection inputs are invalid."""


@dataclass(frozen=True)
class CandidateTerm:
    """One reusable term proposed by a model, in canonical contract form."""

    field_name: str
    derivative_axes: tuple[str, ...]
    power: int
    origin_proposal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.field_name:
            raise TermDictionaryError("term field name must be non-empty")
        if not 1 <= self.power <= 6:
            raise TermDictionaryError("term power must be within 1..6")
        for axis in self.derivative_axes:
            if axis not in {"x", "y", "z"}:
                raise TermDictionaryError(f"unsupported derivative axis {axis!r}")

    @property
    def key(self) -> FactorKey:
        """Return the identity used for cross-proposal deduplication."""

        return (self.field_name, self.derivative_axes, self.power)

    def to_factor(self) -> dict[str, object]:
        """Render this term in the exact contract factor shape."""

        return {
            "field": self.field_name,
            "derivative_axes": list(self.derivative_axes),
            "power": self.power,
        }


@dataclass(frozen=True)
class TermDictionary:
    """Per-problem dictionary of reusable terms from independent proposals.

    This is the object the paper's diagnosis reduces the evolutionary loop to:
    the loop's durable product is the dictionary, not the lineage.
    """

    terms: tuple[CandidateTerm, ...]
    proposal_count: int
    contributing_proposal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        keys = [term.key for term in self.terms]
        if len(keys) != len(set(keys)):
            raise TermDictionaryError("term dictionary contains duplicate supports")
        if self.proposal_count < 1:
            raise TermDictionaryError("dictionary requires at least one proposal")

    def __len__(self) -> int:
        return len(self.terms)


def extract_term_dictionary(
    proposals: Sequence[tuple[str, Sequence[CandidateTerm]]],
) -> TermDictionary:
    """Build one deduplicated dictionary from independent model proposals.

    Terms are pooled across proposals rather than inherited through a parent, and
    every term records which proposals contributed it so provenance survives.
    Ordering is deterministic so a selection replay is reproducible.
    """

    if not proposals:
        raise TermDictionaryError("dictionary extraction requires at least one proposal")

    merged: dict[FactorKey, list[str]] = {}
    for proposal_id, terms in proposals:
        if not proposal_id:
            raise TermDictionaryError("each proposal requires a non-empty id")
        for term in terms:
            merged.setdefault(term.key, [])
            if proposal_id not in merged[term.key]:
                merged[term.key].append(proposal_id)

    ordered_keys = sorted(merged)
    pooled = tuple(
        CandidateTerm(
            field_name=key[0],
            derivative_axes=key[1],
            power=key[2],
            origin_proposal_ids=tuple(merged[key]),
        )
        for key in ordered_keys
    )
    return TermDictionary(
        terms=pooled,
        proposal_count=len(proposals),
        contributing_proposal_ids=tuple(sorted({pid for pid, _ in proposals})),
    )


def solve_least_squares(
    design: Sequence[Sequence[float]],
    target: Sequence[float],
    *,
    ridge: float = _RIDGE,
) -> tuple[float, ...]:
    """Solve a small dense least-squares problem without external packages.

    Uses ridge-stabilized normal equations with partial-pivot Gaussian
    elimination. Adequate because the contract bounds a design to at most 64
    columns, and keeping this dependency-free is what lets selection be tested
    outside the pinned scientific container.
    """

    rows = len(design)
    if rows == 0:
        raise TermDictionaryError("least squares requires at least one row")
    if rows != len(target):
        raise TermDictionaryError("design row count differs from target length")
    columns = len(design[0])
    if columns == 0:
        return ()
    if any(len(row) != columns for row in design):
        raise TermDictionaryError("design rows have inconsistent width")

    # Normal equations: (X'X + ridge*I) beta = X'y
    gram = [[0.0] * columns for _ in range(columns)]
    moment = [0.0] * columns
    for row_index in range(rows):
        row = design[row_index]
        observed = target[row_index]
        for i in range(columns):
            moment[i] += row[i] * observed
            for j in range(i, columns):
                gram[i][j] += row[i] * row[j]
    for i in range(columns):
        for j in range(i):
            gram[i][j] = gram[j][i]
        gram[i][i] += ridge

    augmented = [[*gram[i], moment[i]] for i in range(columns)]
    for pivot in range(columns):
        best = max(range(pivot, columns), key=lambda r: abs(augmented[r][pivot]))
        if abs(augmented[best][pivot]) < 1e-300:
            # Singular column: leave its coefficient at zero rather than failing,
            # so a degenerate candidate set is scored rather than crashing.
            continue
        augmented[pivot], augmented[best] = augmented[best], augmented[pivot]
        pivot_value = augmented[pivot][pivot]
        for row_index in range(columns):
            if row_index == pivot:
                continue
            factor = augmented[row_index][pivot] / pivot_value
            if factor == 0.0:
                continue
            for column_index in range(pivot, columns + 1):
                augmented[row_index][column_index] -= factor * augmented[pivot][column_index]

    coefficients = []
    for index in range(columns):
        diagonal = augmented[index][index]
        coefficients.append(
            augmented[index][columns] / diagonal if abs(diagonal) > 1e-300 else 0.0
        )
    return tuple(coefficients)


def normalized_mse(target: Sequence[float], prediction: Sequence[float]) -> float:
    """Return NMSE using the same convention as the Harness runner."""

    if len(target) != len(prediction):
        raise TermDictionaryError("target and prediction lengths differ")
    numerator = sum((t - p) ** 2 for t, p in zip(target, prediction, strict=True))
    denominator = sum(value * value for value in target) + 1e-30
    result = numerator / denominator
    if not math.isfinite(result):
        raise TermDictionaryError("NMSE is not finite")
    return result


def _predict(design: Sequence[Sequence[float]], coefficients: Sequence[float]) -> list[float]:
    return [
        sum(row[i] * coefficients[i] for i in range(len(coefficients))) for row in design
    ]


def _fit_subset(
    design: Sequence[Sequence[float]],
    target: Sequence[float],
    subset: Sequence[int],
) -> tuple[tuple[float, ...], float]:
    if not subset:
        # The zero null: predict nothing at all.
        return (), normalized_mse(target, [0.0] * len(target))
    reduced = [[row[index] for index in subset] for row in design]
    coefficients = solve_least_squares(reduced, target)
    return coefficients, normalized_mse(target, _predict(reduced, coefficients))


@dataclass(frozen=True)
class SetSelectionResult:
    """Outcome of train-only set-level selection over a term dictionary."""

    selected_indices: tuple[int, ...]
    selected_terms: tuple[CandidateTerm, ...]
    coefficients: tuple[float, ...]
    train_nmse: float
    zero_null_nmse: float
    evaluated_set_count: int
    rejected_reason: str | None = None
    term_influences: tuple[float, ...] = ()

    @property
    def accepted(self) -> bool:
        """True only when a real, train-dependent, non-null fit was found."""

        return self.rejected_reason is None

    @property
    def zero_null_relative_improvement(self) -> float:
        """Fractional NMSE reduction versus predicting zero."""

        if self.zero_null_nmse <= 0.0:
            return 0.0
        return (self.zero_null_nmse - self.train_nmse) / self.zero_null_nmse


def term_influence_scores(
    design: Sequence[Sequence[float]],
    target: Sequence[float],
    selected_indices: Sequence[int],
) -> tuple[float, ...]:
    """Return each selected term's marginal contribution (IGSR-style feedback).

    Influence is the NMSE increase caused by dropping that single term and
    refitting the rest. Scalar-metric feedback cannot tell a model WHICH term
    carried the fit; this can, which is what the granular-feedback result calls
    for.
    """

    if not selected_indices:
        return ()
    _, full_nmse = _fit_subset(design, target, selected_indices)
    influences = []
    for position in range(len(selected_indices)):
        reduced = [
            index for offset, index in enumerate(selected_indices) if offset != position
        ]
        _, reduced_nmse = _fit_subset(design, target, reduced)
        influences.append(reduced_nmse - full_nmse)
    return tuple(influences)


def select_term_set(
    dictionary: TermDictionary,
    design: Sequence[Sequence[float]],
    target: Sequence[float],
    *,
    max_terms: int = 8,
    max_evaluated_sets: int = 20_000,
    require_train_dependence: bool = True,
) -> SetSelectionResult:
    """Choose a TERM SET, not per-term winners, using train data only.

    The central principle from the audit: underdetermined data identifies the
    joint behaviour of term sets, not reliable per-term credit. Selection is
    therefore over subsets, scored by BIC to penalize size, and a result that is
    equivalent to the zero null or independent of the training data is rejected
    rather than reported as a fit.
    """

    if len(dictionary) != len(design[0] if design else []):
        raise TermDictionaryError("design column count must match dictionary size")
    if not 1 <= max_terms <= _MAX_TERMS_PER_EQUATION:
        raise TermDictionaryError("max_terms must be within 1..64")

    sample_count = len(target)
    zero_null_nmse = normalized_mse(target, [0.0] * sample_count)

    best_subset: tuple[int, ...] = ()
    best_coefficients: tuple[float, ...] = ()
    best_nmse = zero_null_nmse
    best_bic = math.inf
    evaluated = 0

    for size in range(1, min(max_terms, len(dictionary)) + 1):
        for subset in itertools.combinations(range(len(dictionary)), size):
            if evaluated >= max_evaluated_sets:
                break
            evaluated += 1
            coefficients, nmse = _fit_subset(design, target, subset)
            residual = max(nmse * (sum(v * v for v in target) + 1e-30), 1e-300)
            bic = sample_count * math.log(residual / sample_count) + size * math.log(
                max(sample_count, 2)
            )
            if bic < best_bic:
                best_bic = bic
                best_subset = subset
                best_coefficients = coefficients
                best_nmse = nmse
        if evaluated >= max_evaluated_sets:
            break

    rejected: str | None = None
    if not best_subset:
        rejected = "no_term_set_improved_on_the_zero_null"
    elif best_nmse >= _ZERO_NULL_NMSE_FLOOR:
        # The exact Task 265.3 failure: NMSE 0.9999999999988402.
        rejected = "fit_is_zero_null_equivalent"
    elif require_train_dependence and _is_train_independent(best_coefficients):
        # The exact Task 265.3 companion failure: training sensitivity 0.
        rejected = "fit_is_independent_of_training_data"

    return SetSelectionResult(
        selected_indices=best_subset,
        selected_terms=tuple(dictionary.terms[index] for index in best_subset),
        coefficients=best_coefficients,
        train_nmse=best_nmse,
        zero_null_nmse=zero_null_nmse,
        evaluated_set_count=evaluated,
        rejected_reason=rejected,
        term_influences=(
            term_influence_scores(design, target, best_subset) if best_subset else ()
        ),
    )


def _is_train_independent(coefficients: Iterable[float]) -> bool:
    """True when every coefficient is numerically negligible."""

    return all(abs(value) < _MIN_TRAIN_SENSITIVITY for value in coefficients)


@dataclass(frozen=True)
class MatchedBudgetArm:
    """One arm of the Task 267.6 Route P2 matched-call-budget comparison."""

    arm_id: Literal["independent_sampling_set_level", "parent_conditioned_evolution"]
    llm_call_count: int
    proposal_count: int
    generations: int
    notes: str = ""
    provenance: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.llm_call_count < 1:
            raise TermDictionaryError("an arm must use at least one model call")
        if self.arm_id == "independent_sampling_set_level" and self.generations != 1:
            raise TermDictionaryError(
                "the set-level arm is one-generation by construction"
            )
        if self.arm_id == "parent_conditioned_evolution" and self.generations < 2:
            raise TermDictionaryError(
                "the evolutionary arm requires at least two generations"
            )


def validate_matched_budget(
    arms: Sequence[MatchedBudgetArm],
) -> tuple[MatchedBudgetArm, ...]:
    """Require both arms to spend the same number of model calls.

    Without a matched budget the comparison is uninterpretable: the audit result
    holds specifically UNDER matched call budgets, so an unmatched comparison
    could not reproduce or refute it.
    """

    if len(arms) != 2:
        raise TermDictionaryError("a matched comparison needs exactly two arms")
    ids = {arm.arm_id for arm in arms}
    if ids != {"independent_sampling_set_level", "parent_conditioned_evolution"}:
        raise TermDictionaryError("both named arms are required")
    budgets = {arm.llm_call_count for arm in arms}
    if len(budgets) != 1:
        raise TermDictionaryError(
            "arms must use an identical model-call budget to be comparable"
        )
    return tuple(sorted(arms, key=lambda arm: arm.arm_id))
