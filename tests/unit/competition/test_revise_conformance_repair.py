"""Revision must repair a non-conformant response, like generation does.

`P-20260807-091`: `revise_official_candidates` validated the model's response EXACTLY
ONCE, while `generate_official_candidates` retried with the exact validation errors.
Both call the same provider with the same ~12k-token source payload, so the same
`P-20260804-079` dropped-metadata-field failure applies to both. A single omitted
`response_type` aborted the whole revise stage of
`task2699-system-authored-lineage-v2` AFTER its generation budget was already spent,
stranding the lineage mid-run.

These tests pin the repair loop: a first-attempt omission is repaired and the revision
still lands, the repair prompt carries the offending field name so the model can act on
it, and a model that never conforms fails loudly rather than silently dropping the
candidate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.official_development_search import (
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialDevelopmentSearchError,
    revise_official_candidates,
)

_SOURCE_LINES = [
    "import numpy as np",
    "",
    "",
    "def fit_equations(payload):",
    "    return {'equations': []}",
    "",
    "",
    "def predict_derivative(payload):",
    "    return {'derivative_prediction': {'shape': [1], 'values': [0.0]}}",
]

_PANEL: dict[str, Any] = {
    "systems": [],
    "conditions": ["clean", "snr_20"],
    "seeds": [101],
}

_BUDGET: dict[str, Any] = {
    "maximum_seconds_per_cell": 300,
    "maximum_memory_mb_per_cell": 4096,
    "maximum_cpu_cores_per_cell": 2,
}

_NARRATIVE = {
    "observation": "my previous run behaved this way on held-out evidence",
    "problem": "the selection overfitted the validation window",
    "hypothesis": "selecting complexity on held-out evidence transfers better",
    "intervention": "choose support size by held-out score",
    "expected_effect": "smaller generalization gap on unseen slices",
    "implementation_summary": "revised to select support on held-out evidence",
}


def _Result(payload: dict[str, Any]) -> Any:
    """Build a real completion result, so the recorder sees the true contract."""

    from autoresearch.llm.client import LLMJsonCompletionResult

    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.example/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload),
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.2,
        reasoning_text="diagnosing my own generalization gap",
        reasoning_transport="dashscope_enable_thinking",
    )


def _conformant() -> dict[str, Any]:
    return {
        "response_type": "scientific_contract_source",
        "source_lines": list(_SOURCE_LINES),
        **_NARRATIVE,
    }


def _missing_response_type() -> dict[str, Any]:
    """Exactly the live failure: every field present EXCEPT response_type."""

    return {"source_lines": list(_SOURCE_LINES), **_NARRATIVE}


def _fixture(
    tmp_path: Path,
) -> tuple[OfficialCandidateRecord, list[OfficialCellResult], list]:
    parent_dir = tmp_path / "candidates" / "official-01"
    parent_dir.mkdir(parents=True)
    (parent_dir / "candidate.py").write_text("\n".join(_SOURCE_LINES), encoding="utf-8")
    record = OfficialCandidateRecord(
        candidate_id="official-01",
        generation=1,
        interaction_id="official-generate-01",
        source_relative_path="candidates/official-01/candidate.py",
        source_sha256="0" * 64,
        static_review_approved=True,
        static_review_findings=(),
        implementation_summary="parent",
    )
    # At least one executed cell, or the revise loop skips this candidate entirely.
    results = [
        OfficialCellResult(
            attempt_id="pilot-official-01-sysA-clean-101",
            method_kind="candidate",
            candidate_id="official-01",
            stage="pilot",
            system_name="sysA",
            data_type="ode",
            condition="clean",
            seed=101,
            status="succeeded",
            derivative_nmse=0.5,
            validation_nmse=0.4,
            selected_term_count=3,
            wall_time_seconds=1.0,
            result_hash="a" * 64,
        )
    ]
    return record, results, []


def test_revision_repairs_a_missing_field_and_still_lands(tmp_path: Path) -> None:
    """The exact live failure must no longer abort the stage."""

    record, results, calls = _fixture(tmp_path)
    responses = [_missing_response_type(), _conformant()]

    def completion(**kwargs: Any) -> _Result:
        calls.append(kwargs)
        return _Result(responses[len(calls) - 1])

    revised = revise_official_candidates(
        candidates=[record],
        results=results,
        panel=_PANEL,
        budget=_BUDGET,
        output_dir=tmp_path,
        completion=completion,
    )

    assert len(revised) == 1
    assert revised[0].candidate_id == "official-01-r2"
    assert revised[0].generation == 2
    # Two provider calls: the failed attempt and its repair.
    assert len(calls) == 2
    # Both attempts are recorded on disk, so the repair is auditable rather than
    # silently swallowed. The retry carries its own interaction id.
    recorded = sorted(p.name for p in (tmp_path / "interactions").glob("*.json"))
    assert "official-revise-official-01.json" in recorded
    assert any(name.endswith("-repair2.json") for name in recorded)


def test_repair_prompt_names_the_offending_field(tmp_path: Path) -> None:
    """A refusal that does not say what was wrong teaches the model nothing."""

    record, results, calls = _fixture(tmp_path)
    responses = [_missing_response_type(), _conformant()]

    def completion(**kwargs: Any) -> _Result:
        calls.append(kwargs)
        return _Result(responses[len(calls) - 1])

    revise_official_candidates(
        candidates=[record],
        results=results,
        panel=_PANEL,
        budget=_BUDGET,
        output_dir=tmp_path,
        completion=completion,
    )

    repair_text = json.dumps(calls[1]["messages"])
    assert "response_type" in repair_text
    assert "failed strict local validation" in repair_text


def test_a_model_that_never_conforms_fails_loudly(tmp_path: Path) -> None:
    """Bounded, not infinite: the frozen budget must not fund an endless retry loop."""

    record, results, calls = _fixture(tmp_path)

    def completion(**kwargs: Any) -> _Result:
        calls.append(kwargs)
        return _Result(_missing_response_type())

    with pytest.raises(OfficialDevelopmentSearchError) as excinfo:
        revise_official_candidates(
            candidates=[record],
            results=results,
            panel=_PANEL,
            budget=_BUDGET,
            output_dir=tmp_path,
            completion=completion,
        )

    assert "schema-conformant revision" in str(excinfo.value)
    assert "response_type" in str(excinfo.value)
    # Bounded at the same constant generation uses, not unbounded.
    assert len(calls) == 3
