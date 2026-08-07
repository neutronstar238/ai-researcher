"""The system interprets its own result, and the guard makes that mean something.

Task `267.7` requires the system to author its own outcome. It authored the candidates,
the revisions, the protocol decisions, and every number, but the narrative was
hand-written by an agent. This module closes that gap.

The tests that matter most are the REFUSALS. "System-authored" is worthless if the
system can invent a number or claim success against a failed gate, so those paths are
tested explicitly rather than trusted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.competition.system_authored_outcome import (
    AuthoredInterpretation,
    SystemAuthoredOutcomeError,
    audit_numeric_traceability,
    author_outcome_interpretation,
    collect_evidence_numbers,
)
from autoresearch.llm.client import LLMJsonCompletionResult

_PACKAGE: dict[str, Any] = {
    "package_hash": "a" * 64,
    "selected_candidate_id": "official-07-r2",
    "selection_basis": "median validation NMSE over executed cells",
    "overall_median_log_effect": -0.8448548894388439,
    "bootstrap_lower": -1.4630988707200518,
    "bootstrap_upper": 0.04814249650803004,
    "ode_stratum_median": -0.6556574227708623,
    "pde_stratum_median": -1.594291281789289,
    "gate_checks": {
        "all_candidate_cells_succeeded": True,
        "all_baseline_cells_succeeded": True,
        "overall_median_at_least_minimum": False,
        "bootstrap_lower_above_zero": False,
        "budget_conformant": True,
    },
    "system_effects": [
        {"system_name": "sys-a", "data_type": "ode", "paired_log_effect": 3.5936959},
        {"system_name": "sys-b", "data_type": "pde", "paired_log_effect": -1.6315137},
    ],
}
_ESTIMAND: dict[str, Any] = {
    "minimum_overall_log_effect": 0.05129329438755058,
    "ode_stratum_median_minimum": 0.0,
    "pde_stratum_median_minimum": 0.0,
}


def _write_inputs(tmp_path: Path, *, gate: dict[str, bool] | None = None) -> tuple[Path, Path]:
    package = dict(_PACKAGE)
    if gate is not None:
        package["gate_checks"] = gate
    pkg_path = tmp_path / "package.json"
    pkg_path.write_text(json.dumps(package), encoding="utf-8")
    plan_path = tmp_path / "frozen.json"
    plan_path.write_text(json.dumps({"estimand": _ESTIMAND}), encoding="utf-8")
    return pkg_path, plan_path


def _interpretation(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": "claim_not_supported",
        "what_the_evidence_supports": (
            "Every cell executed on both arms, and the measured overall median of "
            "-0.8449 lies below the frozen minimum of 0.05129329438755058, so the "
            "method does not beat the pinned baseline on this panel."
        ),
        "what_the_evidence_does_not_support": (
            "This does not support any claim about the method class in general, nor "
            "about systems outside the measured panel, and it says nothing about the "
            "sealed confirmation data."
        ),
        "strongest_counter_reading": (
            "The bootstrap upper bound of 0.04814249650803004 is very close to zero, "
            "so a reader could argue the panel is too small to be decisive."
        ),
        "limitations": (
            "The PDE stratum median of -1.594291281789289 rests on few systems.",
            "One selected candidate is not the whole method class.",
        ),
        "claims_frozen_gate_passed": False,
    }
    payload.update(overrides)
    return payload


class _Stub:
    def __init__(self, payload: dict[str, Any], *, reasoning_tokens: int = 2_000) -> None:
        self.payload = payload
        self.reasoning_tokens = reasoning_tokens
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(self.payload),
            parsed_json=self.payload,
            usage={
                "prompt_tokens": 1_200,
                "completion_tokens": 700,
                "completion_tokens_details": {"reasoning_tokens": self.reasoning_tokens},
            },
            temperature=0.2,
            reasoning_text="weighing the interval against the frozen threshold",
            reasoning_transport="dashscope_enable_thinking",
        )


def _run(tmp_path: Path, stub: _Stub, *, gate: dict[str, bool] | None = None) -> Any:
    pkg_path, plan_path = _write_inputs(tmp_path, gate=gate)
    return author_outcome_interpretation(
        lineage_id="lineage-under-test",
        package_path=pkg_path,
        frozen_plan_path=plan_path,
        output_dir=tmp_path,
        completion=stub,
        clock=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


# --------------------------------------------------------------------------
# The guard: a number not in the evidence is a refusal
# --------------------------------------------------------------------------


def test_an_invented_number_is_refused(tmp_path: Path) -> None:
    """THE test that makes 'system-authored' mean something.

    Without this, the model could write a fluent narrative around numbers that were
    never measured, and the artifact would look authoritative while being fiction.
    """

    stub = _Stub(
        _interpretation(
            what_the_evidence_supports=(
                "The method improved the median by 42.7 percent over the baseline, "
                "which is a decisive result on this panel and warrants the claim."
            )
        )
    )
    outcome = _run(tmp_path, stub)
    assert outcome.accepted is False
    assert outcome.traceability.passed is False
    assert "42.7" in outcome.traceability.untraceable_numbers
    assert any("absent from its own evidence" in r for r in outcome.refusal_reasons)


def test_numbers_present_in_the_evidence_are_accepted(tmp_path: Path) -> None:
    outcome = _run(tmp_path, _Stub(_interpretation()))
    assert outcome.traceability.passed is True
    assert outcome.accepted is True
    assert outcome.traceability.untraceable_numbers == ()


def test_a_rounded_evidence_number_is_accepted() -> None:
    """A model writing -0.8449 for a recorded -0.8448548894388439 is being readable."""

    allowed = collect_evidence_numbers(_PACKAGE, _ESTIMAND)
    audit = audit_numeric_traceability(
        prose="the median was -0.8449 and the lower bound -1.4631", allowed_numbers=allowed
    )
    assert audit.passed is True


def test_a_plausible_but_unmeasured_number_is_caught() -> None:
    allowed = collect_evidence_numbers(_PACKAGE, _ESTIMAND)
    audit = audit_numeric_traceability(
        prose="the median was -0.7412, close to the threshold", allowed_numbers=allowed
    )
    assert audit.passed is False
    assert audit.untraceable_numbers == ("-0.7412",)


def test_the_audit_verdict_cannot_contradict_its_list() -> None:
    allowed = collect_evidence_numbers(_PACKAGE, _ESTIMAND)
    payload = json.loads(
        audit_numeric_traceability(prose="-0.9999", allowed_numbers=allowed).model_dump_json()
    )
    payload["passed"] = True
    with pytest.raises(SystemAuthoredOutcomeError, match="contradicts its own"):
        type(
            audit_numeric_traceability(prose="-0.9999", allowed_numbers=allowed)
        ).model_validate(payload)


# --------------------------------------------------------------------------
# The guard: the deterministic gate outranks the narrative
# --------------------------------------------------------------------------


def test_claiming_success_against_a_failed_gate_is_refused(tmp_path: Path) -> None:
    """A narrative cannot promote a failed measurement into a supported claim."""

    stub = _Stub(
        _interpretation(verdict="claim_supported", claims_frozen_gate_passed=True)
    )
    outcome = _run(tmp_path, stub)
    assert outcome.accepted is False
    assert outcome.verdict_consistent_with_gate is False
    assert any("gate outranks the narrative" in r for r in outcome.refusal_reasons)


def test_misreporting_the_gate_state_is_refused(tmp_path: Path) -> None:
    stub = _Stub(_interpretation(claims_frozen_gate_passed=True))
    outcome = _run(tmp_path, stub)
    assert outcome.accepted is False
    assert any("deterministic gate is False" in r for r in outcome.refusal_reasons)


def test_a_passing_gate_permits_a_supported_claim(tmp_path: Path) -> None:
    """The guard must not make a genuine success unreportable."""

    passing = {"all_candidate_cells_succeeded": True, "budget_conformant": True}
    stub = _Stub(
        _interpretation(verdict="claim_supported", claims_frozen_gate_passed=True)
    )
    outcome = _run(tmp_path, stub, gate=passing)
    assert outcome.frozen_gate_passed is True
    assert outcome.accepted is True


def test_an_interpretation_must_carry_limitations() -> None:
    """An interpretation listing only strengths is advocacy, not analysis."""

    with pytest.raises(ValidationError, match="at least 2 items"):
        AuthoredInterpretation.model_validate(
            {
                "schema_version": "authored-interpretation-v1",
                **_interpretation(limitations=()),
            }
        )


def test_an_unsupported_verdict_is_refused() -> None:
    with pytest.raises(SystemAuthoredOutcomeError, match="unsupported verdict"):
        AuthoredInterpretation.model_validate(
            {
                "schema_version": "authored-interpretation-v1",
                **_interpretation(verdict="it_worked_great"),
            }
        )


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_the_outcome_records_that_no_prose_was_hand_written(tmp_path: Path) -> None:
    outcome = _run(tmp_path, _Stub(_interpretation()))
    assert outcome.authored_by_model is True
    assert outcome.hand_written_prose_count == 0
    assert outcome.is_evidence is False
    assert outcome.publication_ready is False


def test_the_prompt_hands_the_model_its_own_numbers(tmp_path: Path) -> None:
    stub = _Stub(_interpretation())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    assert "-0.8448548894388439" in sent
    assert "0.05129329438755058" in sent
    # It must be told a null is acceptable, so it is not pushed toward a positive.
    assert "valid outcome" in sent
    # And it must be asked for the reading that argues against itself.
    assert "strongest_counter_reading" in sent


def test_the_cycle_uses_bounded_reasoning(tmp_path: Path) -> None:
    stub = _Stub(_interpretation())
    _run(tmp_path, stub)
    assert stub.calls[0]["thinking_mode"] == "enabled"
    assert 0 < stub.calls[0]["thinking_budget"] <= 32_000


def test_the_outcome_persists_and_round_trips(tmp_path: Path) -> None:
    outcome = _run(tmp_path, _Stub(_interpretation()))
    written = tmp_path / "system-authored-outcome.json"
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["outcome_hash"] == (
        outcome.outcome_hash
    )


def test_a_package_without_a_gate_is_refused(tmp_path: Path) -> None:
    """No deterministic verdict means no auditable interpretation."""

    pkg_path, plan_path = _write_inputs(tmp_path, gate={})
    with pytest.raises(SystemAuthoredOutcomeError, match="no gate checks"):
        author_outcome_interpretation(
            lineage_id="lineage-under-test",
            package_path=pkg_path,
            frozen_plan_path=plan_path,
            output_dir=tmp_path,
            completion=_Stub(_interpretation()),
        )
