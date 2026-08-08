"""The system authors its own plan; the graders teach rather than merely reject.

`P-20260804-086`: the previous plan generator made no model call and carried hardcoded
prose, so the scientific framing was an agent's. These tests pin the inversion: the
model writes every prose field, and deterministic graders decide acceptance.

The important tests are the REFUSALS and the TEACHING loop. A grader that cannot refuse
teaches nothing, and a refusal that does not say why teaches nothing either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.system_authored_plan import (
    SystemAuthoredPlanError,
    author_research_plan,
    guard_authored_plan,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.plans import ResearchPlan, ResearchPlanStatus

_FROZEN: dict[str, Any] = {
    "frozen_thresholds": {
        "minimum_overall_log_effect": 0.05129329438755058,
        "stratum_median_minimum": 0.0,
    },
    "retained_evidence": {
        "prior_overall_median": -0.8448548894388439,
        "prior_win_count": 3,
        "prior_system_count": 12,
        "failure_reasons": ["container wall-time budget exceeded"],
    },
}


def _authored(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Noise-robust sparse recovery under held-out complexity selection",
        "abstract": (
            "Background: the prior lineage reached an overall median of "
            "-0.8448548894388439 across 12 systems. Method: choose model complexity on "
            "held-out evidence rather than fitting once at maximum capacity. Expected "
            "result: the transfer gap narrows and the paired effect exceeds "
            "0.05129329438755058; a null result would refute the mechanism."
        ),
        "problem_statement": (
            "Across 12 systems the prior lineage reached an overall median of "
            "-0.8448548894388439, winning 3, so held-out accuracy did not follow from "
            "training accuracy and the selection rule is the suspected mechanism."
        ),
        "rationale": (
            "If complexity is chosen on held-out evidence rather than fixed at "
            "maximum capacity, the transfer gap should narrow. This is a mechanism "
            "claim and it is testable against the same panel."
        ),
        "technical_details": (
            "Each candidate fits on the training split only, emits concrete numeric "
            "equations, and the orchestrator freezes and hashes that artifact before "
            "prediction reads it."
        ),
        "methods": (
            "Compare against the pinned baseline using derivative NMSE as the cell "
            "loss, aggregating by median within a system and then across systems."
        ),
        "experiments": [
            "Author independent candidates and reject any that fails static review.",
            "Run a bounded pilot and return each candidate its own diagnostics.",
            "Execute the baseline on every system, retaining every failure.",
            "Run the full stage and compute a paired effect with a fixed-seed bootstrap.",
        ],
        "baselines": [
            "the pinned tuned symbolic-regression baseline on the same frozen cells",
        ],
        "metrics": [
            "derivative NMSE as the per-cell loss",
            "paired log effect aggregated by median within and then across systems",
        ],
        "expected_results": (
            "It is expected, and not yet observed, that the paired effect exceeds "
            "0.05129329438755058. A negative or null result would refute the "
            "selection-rule mechanism and is a valid outcome that will be reported."
        ),
        "code_agent_brief": (
            "Run python /harness/runner.py --spec ... --data ... per frozen cell with "
            "network disabled, then validate with pytest before any official cell."
        ),
        "risks_and_alternatives": [
            "A candidate may overfit the validation window; the transfer gap is fed back.",
            "A baseline may fail on a system, leaving it unpaired and excluded.",
        ],
        "dataset_source": "the pinned processed archive, clean and noisy conditions",
        "dataset_target": "a chronologically disjoint held-out split of the same systems",
        "references": ["retained prior lineage package"],
    }
    payload.update(overrides)
    return payload


class _Stub:
    """Returns a queued payload per call, so the teaching loop can be observed."""

    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload),
            parsed_json=payload,
            usage={
                "prompt_tokens": 900,
                "completion_tokens": 1_100,
                "completion_tokens_details": {"reasoning_tokens": 2_100},
            },
            temperature=0.3,
            reasoning_text="considering which mechanism the prior gap implicates",
            reasoning_transport="dashscope_enable_thinking",
        )


def _run(tmp_path: Path, stub: _Stub, **kw: Any) -> Any:
    evidence = tmp_path / "prior-package.json"
    evidence.write_text("{}", encoding="utf-8")
    return author_research_plan(
        lineage_id="lineage-under-test",
        project_id="project-under-test",
        candidate_id="candidate-under-test",
        frozen_context=_FROZEN,
        evidence_paths=[evidence],
        output_dir=tmp_path,
        completion=stub,
        container_entry_points=kw.pop("container_entry_points", ("/harness/runner.py",)),
        **kw,
    )


def _plan(**overrides: Any) -> ResearchPlan:
    authored = _authored(**overrides)
    return ResearchPlan.model_validate(
        {
            "project_id": "p",
            "candidate_id": "c",
            "title": authored["title"],
            "problem_statement": authored["problem_statement"],
            "rationale": authored["rationale"],
            "technical_details": authored["technical_details"],
            "datasets": {
                "source": authored["dataset_source"],
                "target": authored["dataset_target"],
            },
            "methods": authored["methods"],
            "experiments": list(authored["experiments"]),
            "expected_results": authored["expected_results"],
            "code_agent_brief": authored["code_agent_brief"],
            "risks_and_alternatives": list(authored["risks_and_alternatives"]),
            "references": list(authored["references"]),
            "evidence_refs": ["prior-package.json"],
            "status": ResearchPlanStatus.DRAFT,
        }
    )


# --------------------------------------------------------------------------
# The system authors, and the artifact records that no prose was ours
# --------------------------------------------------------------------------


def test_the_model_authors_every_prose_field(tmp_path: Path) -> None:
    artifact = _run(tmp_path, _Stub(_authored()))
    assert artifact.authored_by_model is True
    assert artifact.hand_written_prose_field_count == 0
    assert artifact.plan["title"] == _authored()["title"]
    assert artifact.plan["problem_statement"] == _authored()["problem_statement"]
    assert artifact.reasoning_tokens == 2_100
    assert artifact.guard_report.accepted is True


def test_the_prompt_supplies_constraints_but_no_science(tmp_path: Path) -> None:
    """The teacher sets the standard; it must not hand over the answer."""

    stub = _Stub(_authored())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    # Frozen constraints and its own retained evidence are supplied.
    assert "0.05129329438755058" in sent
    assert "-0.8448548894388439" in sent
    # It is told to author its own framing and what would refute it.
    assert "author your own research plan" in sent.lower()
    assert "REFUTE" in sent
    # No hypothesis, mechanism, or title is supplied for it to copy.
    assert "held-out complexity selection" not in sent
    assert "selection rule" not in sent.lower()


def test_evidence_refs_are_derived_not_authored(tmp_path: Path) -> None:
    """A model must not be able to cite a package that was never written."""

    artifact = _run(tmp_path, _Stub(_authored()))
    refs = artifact.plan["evidence_refs"]
    assert refs and all(Path(item).exists() for item in refs)


def test_authoring_against_missing_evidence_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemAuthoredPlanError, match="does not exist"):
        author_research_plan(
            lineage_id="l",
            project_id="p",
            candidate_id="c",
            frozen_context=_FROZEN,
            evidence_paths=[tmp_path / "never-written.json"],
            output_dir=tmp_path,
            completion=_Stub(_authored()),
        )


# --------------------------------------------------------------------------
# The graders refuse, and each refusal says why
# --------------------------------------------------------------------------


def test_an_invented_number_is_refused() -> None:
    """The plan may only reason with numbers its own evidence contains."""

    report = guard_authored_plan(
        plan=_plan(
            problem_statement=(
                "The prior lineage lost 47.3 percent of its accuracy, so the "
                "selection rule is implicated across the panel."
            )
        ),
        evidence_numbers={"0.05129329438755058", "-0.8448548894388439", "3", "12"},
        cited_evidence=[],
    )
    assert report.numbers_traceable is False
    assert "47.3" in report.untraceable_numbers
    assert any("invented rather than derived" in f for f in report.findings)


def test_an_unfalsifiable_expectation_is_refused() -> None:
    """A plan that only describes success is an announcement, not a plan."""

    report = guard_authored_plan(
        plan=_plan(
            expected_results=(
                "The paired effect is expected to exceed the frozen minimum on every "
                "stratum, confirming the mechanism."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.states_falsifiable_expectation is False
    assert any("would REFUTE" in f for f in report.findings)


def test_claiming_an_achieved_result_is_refused() -> None:
    """No measurement exists when a plan is written."""

    report = guard_authored_plan(
        plan=_plan(
            rationale=(
                "We observed that held-out selection narrows the gap, so the same "
                "mechanism should hold here as a valid null is possible."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.claims_no_unobserved_result is False
    assert any("before any measurement exists" in f for f in report.findings)


def test_a_nonexistent_cited_artifact_is_refused(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(),
        evidence_numbers=set(),
        cited_evidence=[tmp_path / "absent.json"],
    )
    assert report.all_cited_evidence_exists is False
    assert any("do not exist on disk" in f for f in report.findings)


def test_the_shared_quality_gate_still_applies() -> None:
    """This module must not invent a second, weaker standard."""

    report = guard_authored_plan(
        plan=_plan(methods="A qualitative comparison with no metric at all."),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.quality_gate_passed is False
    assert any(f.startswith("quality gate:") for f in report.findings)


def test_the_guard_verdict_cannot_contradict_its_findings() -> None:
    report = guard_authored_plan(
        plan=_plan(), evidence_numbers=set(), cited_evidence=[]
    )
    payload = json.loads(report.model_dump_json())
    payload["accepted"] = not payload["accepted"]
    with pytest.raises(SystemAuthoredPlanError, match="contradicts its own"):
        type(report).model_validate(payload)


# --------------------------------------------------------------------------
# Teaching: a refusal returns the finding, and the model can repair
# --------------------------------------------------------------------------


def test_a_refusal_is_fed_back_and_the_model_repairs(tmp_path: Path) -> None:
    """A grader that only says no teaches nothing. The finding must go back."""

    bad = _authored(
        expected_results="The effect will exceed the frozen minimum on every stratum."
    )
    stub = _Stub(bad, _authored())
    artifact = _run(tmp_path, stub)

    assert artifact.authoring_attempts == 2
    assert artifact.guard_report.accepted is True
    # The second prompt carried the exact finding, not a generic complaint.
    second = json.dumps(stub.calls[1]["messages"])
    assert "REFUSED by the graders" in second
    assert "would REFUTE" in second
    # And it was told to change only what the findings name.
    assert "keep the rest of your plan" in second


def test_a_model_that_cannot_meet_the_standard_fails_loudly(tmp_path: Path) -> None:
    """Bounded, so a non-conforming model cannot spin, and never downgraded."""

    bad = _authored(
        expected_results="The effect will exceed the frozen minimum on every stratum."
    )
    stub = _Stub(bad)
    with pytest.raises(SystemAuthoredPlanError, match="could not author a plan"):
        _run(tmp_path, stub, max_attempts=3)
    assert len(stub.calls) == 3


def test_a_refused_plan_is_never_persisted_as_accepted(tmp_path: Path) -> None:
    bad = _authored(
        expected_results="The effect will exceed the frozen minimum on every stratum."
    )
    with pytest.raises(SystemAuthoredPlanError):
        _run(tmp_path, _Stub(bad), max_attempts=2)
    assert not (tmp_path / "system-authored-research-plan.json").is_file()


def test_the_cycle_uses_bounded_reasoning(tmp_path: Path) -> None:
    stub = _Stub(_authored())
    _run(tmp_path, stub)
    assert stub.calls[0]["thinking_mode"] == "enabled"
    assert 0 < stub.calls[0]["thinking_budget"] <= 32_000


def test_the_artifact_persists_and_round_trips(tmp_path: Path) -> None:
    artifact = _run(tmp_path, _Stub(_authored()))
    written = tmp_path / "system-authored-research-plan.json"
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["artifact_hash"] == (
        artifact.artifact_hash
    )
    assert artifact.execution_authorized is False
    assert artifact.is_evidence is False


# --------------------------------------------------------------------------
# The graders must be FAIR as well as strict (P-20260804-087)
# --------------------------------------------------------------------------


def test_sentence_ending_digits_are_not_treated_as_invented_numbers() -> None:
    """A grader that penalises correct prose teaches the wrong lesson.

    The first live authoring run was refused partly for the token `7.`, which came from
    a sentence ending in "step 7." and can never appear in evidence. That was my bug,
    not the system's.
    """

    report = guard_authored_plan(
        plan=_plan(
            technical_details=(
                "The orchestrator freezes the artifact before prediction, as described "
                "in stage 7. Prediction then reads only that artifact."
            )
        ),
        evidence_numbers={"0.05129329438755058"},
        cited_evidence=[],
    )
    assert "7." not in report.untraceable_numbers


def test_budget_arithmetic_is_reachable_from_evidence() -> None:
    """A plan legitimately multiplies its own budget numbers.

    Writing "6 systems by 3 seeds is 18 cells" is sound reasoning, so refusing 18
    because it is absent from the frozen evidence penalises correct work.
    """

    from autoresearch.competition.system_authored_plan import plan_reachable_numbers

    reachable = plan_reachable_numbers({"6", "3"})
    assert "18" in reachable
    assert "9" in reachable


def test_an_expectation_phrased_with_outperform_is_permitted() -> None:
    """"is expected to outperform" is an expectation, not a claimed result."""

    report = guard_authored_plan(
        plan=_plan(
            expected_results=(
                "The candidate is expected to outperform the pinned baseline, and a "
                "negative result would refute the mechanism and is a valid outcome."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.claims_no_unobserved_result is True


def test_a_past_tense_result_claim_is_still_refused() -> None:
    """The relaxation must not open the door to asserting an achieved result."""

    report = guard_authored_plan(
        plan=_plan(
            rationale=(
                "The results showed that held-out selection narrows the gap, and a "
                "null outcome remains possible."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
    )
    assert report.claims_no_unobserved_result is False


def test_the_prompt_names_the_literal_words_the_grader_looks_for(tmp_path: Path) -> None:
    """Teach the standard before enforcing it."""

    stub = _Stub(_authored())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    assert "pytest" in sent
    assert "COMMAND-ORIENTED" in sent


# --------------------------------------------------------------------------
# A brief must be RUNNABLE, not merely command-shaped (P-20260804-089)
# --------------------------------------------------------------------------


def test_a_brief_naming_a_nonexistent_script_is_refused(tmp_path: Path) -> None:
    """The defect found in the second live authoring run.

    The system wrote `pytest test_candidate.py --stratum-templates=stratified`, which
    contains the word `pytest` and so satisfied the quality rubric, but neither the
    script nor the flags exist anywhere. Command-shaped is not the same as runnable.
    """

    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python -m pytest test_candidate.py --stratum-templates=strict "
                "to execute the full evaluation."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    assert report.named_scripts_exist is False
    assert "test_candidate.py" in report.missing_script_paths
    assert any("cannot be executed as written" in f for f in report.findings)


def test_a_brief_naming_an_existing_script_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "runner_entry.py").write_text("", encoding="utf-8")
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python runner_entry.py --spec ... per frozen cell, then validate."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    assert report.named_scripts_exist is True


def test_a_declared_container_path_passes_the_host_check(tmp_path: Path) -> None:
    """A brief legitimately references the pinned container, IF it was declared.

    This test originally asserted that any absolute path skips checking. That was the
    escape hatch: the system then invented `/app/...` paths to satisfy the guard. The
    exemption is now an allowlist rather than a blanket pass.
    """

    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /harness/runner.py --spec ... --data ... per frozen cell "
                "with network disabled."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )
    assert report.named_scripts_exist is True
    assert report.missing_script_paths == ()


def test_the_script_verdict_cannot_contradict_its_list(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief="Run python absent_thing.py --spec ... per frozen cell."
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    payload = json.loads(report.model_dump_json())
    payload["named_scripts_exist"] = True
    with pytest.raises(SystemAuthoredPlanError, match="contradicts its own missing"):
        type(report).model_validate(payload)


def test_the_prompt_warns_against_inventing_a_script(tmp_path: Path) -> None:
    stub = _Stub(_authored())
    _run(tmp_path, stub)
    sent = json.dumps(stub.calls[0]["messages"])
    assert "must NOT invent a script name" in sent
    assert "RUNNABLE" in sent


def test_an_invented_container_path_is_refused(tmp_path: Path) -> None:
    """The escape hatch my first fix opened.

    Exempting absolute paths so a brief could reference the pinned container let the
    system satisfy the guard by inventing CONTAINER paths instead. An absolute path is
    now only accepted if the caller declared it as a real entry point.
    """

    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /app/run_grammar_conditioned_search.py --pilot-systems all "
                "to execute the pipeline."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )
    assert report.named_scripts_exist is False
    assert "/app/run_grammar_conditioned_search.py" in report.missing_script_paths


def test_a_declared_container_entry_point_is_accepted(tmp_path: Path) -> None:
    report = guard_authored_plan(
        plan=_plan(
            code_agent_brief=(
                "Run python /harness/runner.py --spec ... --data ... per frozen cell "
                "with network disabled."
            )
        ),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
        container_entry_points=("/harness/runner.py",),
    )
    assert report.named_scripts_exist is True
    assert report.missing_script_paths == ()


def test_no_declared_entry_point_means_no_absolute_path_is_accepted(
    tmp_path: Path,
) -> None:
    """Silence must not be permission."""

    report = guard_authored_plan(
        plan=_plan(code_agent_brief="Run python /harness/runner.py --spec ... per cell."),
        evidence_numbers=set(),
        cited_evidence=[],
        repo_root=tmp_path,
    )
    assert report.named_scripts_exist is False


def test_the_prompt_lists_the_only_real_entry_points(tmp_path: Path) -> None:
    """Teach what exists, or the system can only guess."""

    evidence = tmp_path / "prior.json"
    evidence.write_text("{}", encoding="utf-8")
    stub = _Stub(_authored())
    author_research_plan(
        lineage_id="l",
        project_id="p",
        candidate_id="c",
        frozen_context=_FROZEN,
        evidence_paths=[evidence],
        output_dir=tmp_path,
        completion=stub,
        container_entry_points=("/harness/runner.py",),
    )
    sent = json.dumps(stub.calls[0]["messages"])
    assert "/harness/runner.py" in sent
    assert "ONLY entry points that exist" in sent
