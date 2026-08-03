"""Task 266.3: a candidate must see its own failures, and nothing else.

The first pilot generated eight candidates once and judged them immediately, so no
candidate ever saw its own behaviour. That made the negative result uninformative as
science: it measured a first draft, not a search. Task 266.2 only reached a passing
gate after its candidates could see their own diagnostics.

Pilot v2 showed exactly the signal that was being withheld:
  official-01  57 terms, validation 8.869 -> test 92.01   gap +83.14
  official-04   1 term,  validation 8.32e-27 -> test 2.888e-26
  official-03  15 terms, validation 0.1282 -> test 0.04159  gap -0.087  (beat baseline)

The feedback must stay score-blind: a candidate may see its own metrics but never a
baseline loss and never another candidate's result, or a revision could be tuned
toward the comparison it is measured by.
"""

from __future__ import annotations

import json

from autoresearch.competition.official_development_search import (
    OfficialCellResult,
    build_candidate_self_observation,
)


def _cell(
    *,
    candidate_id: str,
    system: str,
    validation: float | None,
    test: float | None,
    terms: int | None = 10,
    status: str = "succeeded",
    method_kind: str = "candidate",
    data_type: str = "ode",
    train_dependent: bool | None = True,
    failure_reason: str | None = None,
) -> OfficialCellResult:
    return OfficialCellResult(
        attempt_id=f"{candidate_id}-{system}",
        method_kind=method_kind,  # type: ignore[arg-type]
        candidate_id=candidate_id,
        stage="pilot",
        system_name=system,
        data_type=data_type,  # type: ignore[arg-type]
        condition="snr_20",
        seed=101,
        status=status,  # type: ignore[arg-type]
        derivative_nmse=test,
        validation_nmse=validation,
        selected_term_count=terms,
        equation_changed_on_shuffled_training=train_dependent,
        failure_reason=failure_reason,
        result_hash="a" * 64,
    )


def test_observation_exposes_the_generalization_gap() -> None:
    """The exact signal that was withheld from official-01 in pilot v2."""

    observation = build_candidate_self_observation(
        candidate_id="official-01",
        results=[
            _cell(
                candidate_id="official-01",
                system="driven-pendulum",
                validation=8.869,
                test=92.01,
                terms=57,
            )
        ],
    )

    cell = observation["your_cells"][0]
    assert cell["your_selected_term_count"] == 57
    assert cell["your_generalization_gap"] > 80.0


def test_observation_shows_a_negative_gap_when_the_method_transfers() -> None:
    """official-03 generalized BETTER than it validated; that must be visible too."""

    observation = build_candidate_self_observation(
        candidate_id="official-03",
        results=[
            _cell(
                candidate_id="official-03",
                system="aizawa-attractor",
                validation=0.1282,
                test=0.04159,
                terms=15,
            )
        ],
    )

    assert observation["your_cells"][0]["your_generalization_gap"] < 0.0


def test_observation_never_leaks_a_baseline_loss() -> None:
    """A revision tuned toward the baseline would contaminate the comparison."""

    results = [
        _cell(candidate_id="official-03", system="s1", validation=0.5, test=0.6),
        _cell(
            candidate_id="operon_or_pdefind",
            system="s1",
            validation=0.01,
            test=0.0123456789,
            method_kind="baseline",
        ),
    ]

    observation = build_candidate_self_observation(
        candidate_id="official-03", results=results
    )
    flat = json.dumps(observation)

    assert "0.0123456789" not in flat
    assert "operon" not in flat.casefold()
    assert observation["executed_cell_count"] == 1


def test_observation_never_leaks_another_candidate() -> None:
    results = [
        _cell(candidate_id="official-03", system="s1", validation=0.5, test=0.6),
        _cell(candidate_id="official-04", system="s1", validation=0.111222333, test=0.7),
    ]

    observation = build_candidate_self_observation(
        candidate_id="official-03", results=results
    )
    flat = json.dumps(observation)

    assert "0.111222333" not in flat
    assert "official-04" not in flat


def test_observation_aggregates_failure_reasons() -> None:
    """A candidate that crashed must learn HOW it crashed."""

    results = [
        _cell(
            candidate_id="official-05",
            system="s1",
            validation=None,
            test=None,
            status="failed",
            failure_reason="ValueError: all input arrays must have the same shape",
        ),
        _cell(
            candidate_id="official-05",
            system="s2",
            validation=None,
            test=None,
            status="failed",
            failure_reason="ValueError: all input arrays must have the same shape",
        ),
    ]

    observation = build_candidate_self_observation(
        candidate_id="official-05", results=results
    )

    assert observation["succeeded_cell_count"] == 0
    assert sum(observation["your_failure_counts"].values()) == 2


def test_observation_reports_the_train_dependence_control() -> None:
    observation = build_candidate_self_observation(
        candidate_id="official-03",
        results=[
            _cell(
                candidate_id="official-03",
                system="s1",
                validation=0.5,
                test=0.6,
                train_dependent=False,
            )
        ],
    )

    assert observation["your_cells"][0]["your_fit_depended_on_training_target"] is False


def test_observation_of_an_unexecuted_candidate_is_empty() -> None:
    observation = build_candidate_self_observation(candidate_id="ghost", results=[])

    assert observation == {"executed_cell_count": 0}


def test_observation_states_the_overfitting_interpretation() -> None:
    """The model must be told what a large positive gap means."""

    observation = build_candidate_self_observation(
        candidate_id="official-01",
        results=[
            _cell(candidate_id="official-01", system="s1", validation=1.0, test=90.0)
        ],
    )

    assert "generalization gap" in observation["note"]
    assert "no baseline loss" in observation["note"].casefold()
