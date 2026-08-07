"""The counter-reading guard must grade substance, not vocabulary.

`P-20260807-092`: the guard matched a hand-enumerated list of literal phrases, and
refused a CORRECT counter-reading authored live in
`task2699-system-authored-lineage-v2`. It failed two ways at once.

1. LEXICALLY. The list held "few systems" but the model wrote "rests on only 2
   systems". Identical meaning, absent vocabulary.
2. DIRECTIONALLY. Every phrase argued a POSITIVE claim was overstated. For a
   `claim_not_supported` verdict the adversarial direction inverts: the strongest case
   against the conclusion is that the result is HARSHER than the method warrants. The
   list could not express that, so a negative verdict could not satisfy the guard
   except by accident.

The guard must still refuse a bare restatement. These tests pin both directions.
"""

from __future__ import annotations

from autoresearch.competition.system_authored_outcome import (
    _COUNTER_READING_CONCEPTS,
    audit_numeric_traceability,
    collect_evidence_numbers,
)

# The exact text the live system authored and the old guard refused.
_LIVE_REFUSED_COUNTER_READING = (
    "The PDE stratum median of -15.41311654930732 is driven almost entirely by a "
    "single catastrophic failure on reaction_diffusion_cylinder (paired_log_effect of "
    "-29.51550192036587 due to 0/6 candidate cells succeeding), meaning the PDE result "
    "rests on only 2 systems and is not representative of PDE performance broadly. "
    "Additionally, the candidate was selected on 'median validation NMSE over executed "
    "cells, failures penalised', yet still failed all cells on one system, suggesting "
    "the selection criterion did not prevent overfitting to validation conditions that "
    "did not transfer to test."
)


def _matches(text: str) -> list[int]:
    """Which concept groups a counter-reading satisfies."""

    lowered = text.lower()
    return [
        index
        for index, group in enumerate(_COUNTER_READING_CONCEPTS)
        if any(phrase in lowered for phrase in group)
    ]


def test_the_live_refused_counter_reading_is_now_accepted() -> None:
    """The regression that motivated this fix."""

    matched = _matches(_LIVE_REFUSED_COUNTER_READING)
    assert matched, (
        "the live counter-reading names a thin stratum, a dominating single failure, "
        "and a selection confound; refusing it grades vocabulary rather than substance"
    )


def test_a_thin_stratum_is_recognised_in_several_phrasings() -> None:
    """Semantically identical statements must not depend on word choice."""

    for phrasing in (
        "the stratum rests on only 2 systems",
        "this stratum has too few members to carry the conclusion",
        "the median is driven almost entirely by a single failure",
        "the result is sensitive to a single system",
        "the PDE stratum is dominated by one capped cell",
    ):
        assert _matches(phrasing), phrasing


def test_a_negative_verdict_can_argue_the_result_is_too_harsh() -> None:
    """The inverted adversarial direction the original list could not express.

    For `claim_not_supported`, arguing AGAINST the conclusion means arguing the method
    was judged more harshly than it deserves.
    """

    for phrasing in (
        "the loss was capped at the frozen failure loss, so this reflects "
        "infrastructure rather than science",
        "those cells timed out on the container wall-time budget",
        "excluding that system the overall median would be less negative",
        "the failure loss overstates the failure of the method itself",
    ):
        assert _matches(phrasing), phrasing


def test_an_interval_that_fails_to_exclude_zero_is_recognised() -> None:
    for phrasing in (
        "the interval crosses zero",
        "the bootstrap interval includes zero",
        "the lower bound sits far below zero, indicating substantial uncertainty",
    ):
        assert _matches(phrasing), phrasing


def test_a_bare_restatement_is_still_refused() -> None:
    """The guard must keep its teeth: restating the conclusion is not an argument."""

    for restatement in (
        "The method performed worse than the baseline overall.",
        "The candidate did not beat the baseline and the gate failed.",
        "Performance was poor and the median effect was negative.",
        "The evidence shows the method is not an improvement.",
    ):
        assert not _matches(restatement), restatement


def test_traceability_still_rejects_an_invented_number() -> None:
    """The numeric guard is independent and must remain strict."""

    allowed = collect_evidence_numbers({"overall": -0.6859100612592094})
    audit = audit_numeric_traceability(
        prose="the effect was -0.99 which appears nowhere in evidence",
        allowed_numbers=allowed,
    )
    assert not audit.passed
    assert "-0.99" in audit.untraceable_numbers


def test_traceability_accepts_a_rounded_evidence_number() -> None:
    """A model may legitimately round a recorded value."""

    allowed = collect_evidence_numbers({"overall": -0.6859100612592094})
    audit = audit_numeric_traceability(
        prose="the overall median was -0.685910", allowed_numbers=allowed
    )
    assert audit.passed
