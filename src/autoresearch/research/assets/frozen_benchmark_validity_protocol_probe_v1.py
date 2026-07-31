#!/usr/bin/env python3
"""Dependency-free replay probe for the Task 263.6.7.1 protocol freeze.

The probe receives only a result-free protocol projection.  It deliberately
rejects benchmark records, search results, admission cards, model outcomes,
and any non-zero extraction state.  Its sole purpose is to show that two
independent Python installations read the same prospective protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FORBIDDEN_KEYS = {
    "admission_cards",
    "benchmark_records",
    "candidate_model_outputs",
    "extracted_records",
    "model_outcomes",
    "search_results",
}
EXPECTED_PILOTS = {
    "autosdt-5k",
    "core-bench",
    "qrdata",
    "scienceagentbench",
}
EXPECTED_SOURCES = {"arxiv", "crossref", "dblp", "openalex"}
EXPECTED_LENSES = {
    "computational-reproduction",
    "data-analysis",
    "experiment-execution",
    "full-research-lifecycle",
    "hypothesis-validation",
    "literature-discovery",
    "scientific-programming",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _walk_forbidden(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_KEYS:
                raise ValueError(f"{path}.{key} is forbidden in a pre-extraction replay")
            _walk_forbidden(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


def _validate_projection(projection: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "protocol_id",
        "protocol_hash",
        "frozen_at",
        "primary_non_pilot_release_target",
        "pilot_release_ids",
        "pilot_primary_eligibility",
        "source_ids",
        "lens_ids",
        "query_binding_count",
        "critical_dual_code_field_ids",
        "primary_endpoint_ids",
        "stop_rule_ids",
        "extracted_record_count",
        "search_execution_started",
        "benchmark_outcomes_accessed",
        "candidate_model_calls",
        "research_question_issued",
        "confirmation_panel_created",
        "public_release_authorized",
        "external_submission_authorized",
    }
    missing = sorted(required - set(projection))
    if missing:
        raise ValueError(f"protocol projection is missing fields: {missing}")
    if projection["schema_version"] != "benchmark-validity-protocol-projection-v1":
        raise ValueError("unsupported protocol projection schema")
    if int(projection["primary_non_pilot_release_target"]) < 20:
        raise ValueError("primary prospective cohort must contain at least 20 releases")
    if set(projection["pilot_release_ids"]) != EXPECTED_PILOTS:
        raise ValueError("the four Task 263.6.6 pilots must remain explicit")
    eligibility = projection["pilot_primary_eligibility"]
    if set(eligibility) != EXPECTED_PILOTS or any(bool(value) for value in eligibility.values()):
        raise ValueError("protocol-development pilots cannot enter the primary cohort")
    if set(projection["source_ids"]) != EXPECTED_SOURCES:
        raise ValueError("the four frozen discovery indexes must remain unchanged")
    if set(projection["lens_ids"]) != EXPECTED_LENSES:
        raise ValueError("the seven construct lenses must remain unchanged")
    expected_bindings = len(EXPECTED_SOURCES) * len(EXPECTED_LENSES)
    if int(projection["query_binding_count"]) != expected_bindings:
        raise ValueError("every source must bind every construct lens exactly once")
    if len(projection["critical_dual_code_field_ids"]) < 8:
        raise ValueError("rights, lineage, construct, and seal need dual coding")
    if len(projection["primary_endpoint_ids"]) != 4:
        raise ValueError("the four descriptive primary endpoints must stay frozen")
    if len(projection["stop_rule_ids"]) < 8:
        raise ValueError("the prospective stop policy is incomplete")
    if int(projection["extracted_record_count"]) != 0:
        raise ValueError("protocol replay cannot contain extracted benchmark records")
    false_fields = (
        "search_execution_started",
        "benchmark_outcomes_accessed",
        "candidate_model_calls",
        "research_question_issued",
        "confirmation_panel_created",
        "public_release_authorized",
        "external_submission_authorized",
    )
    if any(bool(projection[field]) for field in false_fields):
        raise ValueError("pre-extraction protocol flags must all remain false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    payload = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    _walk_forbidden(payload)
    if set(payload) != {"expected_projection_sha256", "projection"}:
        raise ValueError("replay input must contain only projection and expected digest")
    projection = payload["projection"]
    if not isinstance(projection, dict):
        raise TypeError("projection must be a JSON object")
    _validate_projection(projection)
    projection_sha256 = _sha256(projection)
    if projection_sha256 != payload["expected_projection_sha256"]:
        raise ValueError("projection digest does not match the frozen replay input")

    output = {
        "schema_version": "frozen-benchmark-validity-protocol-probe-v1",
        "protocol_id": projection["protocol_id"],
        "protocol_hash": projection["protocol_hash"],
        "projection_sha256": projection_sha256,
        "query_binding_count": projection["query_binding_count"],
        "extracted_record_count": 0,
        "benchmark_outcomes_accessed": False,
        "candidate_model_calls": False,
    }
    output["output_sha256"] = _sha256(output)
    Path(arguments.output).write_text(_canonical_json(output) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
