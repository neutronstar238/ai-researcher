#!/usr/bin/env python3
"""Dependency-free replay probe for the Task 263.6.7.2 search Harness.

The probe accepts only a content-addressed capability projection.  Raw search
bytes stay in the sealed artifact package; scientific outcomes, screening
decisions, Admission Cards, human identities, and model outputs are rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_PROTOCOL_HASH = (
    "ed6088c225d5c7f7710ecb69507659003b5b97e06dc7c0ee005a81ed2712e8ed"
)
EXPECTED_SOURCES = {"arxiv", "crossref", "dblp", "openalex"}
REQUIRED_FORMAL_BLOCKER = "crossref-last-cursor-termination-mismatch"
FORBIDDEN_KEYS = {
    "actual_human_identity",
    "actual_human_identities",
    "admission_card",
    "admission_cards",
    "answer",
    "benchmark_outcome",
    "benchmark_outcomes",
    "candidate_model_output",
    "candidate_model_outputs",
    "gold",
    "gold_answer",
    "gold_hypothesis",
    "judge_output",
    "model_output",
    "model_outputs",
    "reference_answer",
    "reference_program",
    "reserve_result",
    "screening_decision",
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
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in FORBIDDEN_KEYS:
                raise ValueError(f"{path}.{raw_key} is forbidden in Harness replay")
            _walk_forbidden(item, path=f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


def _validate_false(projection: dict[str, Any], field: str) -> None:
    if bool(projection[field]):
        raise ValueError(f"{field} must remain false")


def _validate_projection(projection: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "protocol_hash",
        "adapter_hashes",
        "compatibility_finding_hashes",
        "formal_blocker_ids",
        "capability_probe_hashes",
        "capability_run_hashes",
        "journal_snapshot_hash",
        "paper_deduplication_hash",
        "known_item_recall_hash",
        "known_item_formal_recall_claim",
        "family_revision_deduplication_hash",
        "screening_form_hash",
        "empty_packet_template_hash",
        "raw_response_count",
        "bibliographic_record_count",
        "capability_probe_count",
        "formal_search_execution_count",
        "empty_evidence_packet_count",
        "admission_card_count",
        "actual_human_identities_assigned",
        "benchmark_outcomes_accessed",
        "candidate_model_calls",
        "mechanism_effect_claim_authorized",
        "public_release_authorized",
        "external_submission_authorized",
        "formal_census_authorized",
        "protocol_erratum_required",
    }
    missing = sorted(required - set(projection))
    extra = sorted(set(projection) - required)
    if missing or extra:
        raise ValueError(f"Harness projection shape changed; missing={missing}, extra={extra}")
    if projection["schema_version"] != "benchmark-validity-harness-projection-v1":
        raise ValueError("unsupported Harness projection schema")
    if projection["protocol_hash"] != EXPECTED_PROTOCOL_HASH:
        raise ValueError("Harness projection changed the frozen protocol")
    if set(projection["adapter_hashes"]) != EXPECTED_SOURCES:
        raise ValueError("all four source adapters are required")
    if len(projection["capability_probe_hashes"]) != 4:
        raise ValueError("exactly four capability probes are required")
    if len(projection["capability_run_hashes"]) != 4:
        raise ValueError("exactly four capability runs are required")
    if int(projection["capability_probe_count"]) != 4:
        raise ValueError("capability probe count changed")
    if int(projection["raw_response_count"]) < 4:
        raise ValueError("each source must retain at least one raw response")
    if int(projection["bibliographic_record_count"]) < 0:
        raise ValueError("bibliographic count cannot be negative")
    if REQUIRED_FORMAL_BLOCKER not in projection["formal_blocker_ids"]:
        raise ValueError("Crossref termination mismatch must remain explicit")
    zero_fields = (
        "formal_search_execution_count",
        "empty_evidence_packet_count",
        "admission_card_count",
    )
    if any(int(projection[field]) != 0 for field in zero_fields):
        raise ValueError("Task 263.6.7.2 cannot contain formal science objects")
    false_fields = (
        "known_item_formal_recall_claim",
        "actual_human_identities_assigned",
        "benchmark_outcomes_accessed",
        "candidate_model_calls",
        "mechanism_effect_claim_authorized",
        "public_release_authorized",
        "external_submission_authorized",
        "formal_census_authorized",
    )
    for field in false_fields:
        _validate_false(projection, field)
    if projection["protocol_erratum_required"] is not True:
        raise ValueError("formal census must remain blocked pending an erratum")


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
        raise TypeError("Harness projection must be a JSON object")
    _validate_projection(projection)
    projection_sha256 = _sha256(projection)
    if projection_sha256 != payload["expected_projection_sha256"]:
        raise ValueError("Harness projection digest mismatch")

    output = {
        "schema_version": "frozen-benchmark-validity-harness-probe-v1",
        "protocol_hash": projection["protocol_hash"],
        "projection_sha256": projection_sha256,
        "capability_probe_count": 4,
        "raw_response_count": projection["raw_response_count"],
        "bibliographic_record_count": projection["bibliographic_record_count"],
        "formal_search_execution_count": 0,
        "admission_card_count": 0,
        "benchmark_outcomes_accessed": False,
        "candidate_model_calls": False,
        "formal_census_authorized": False,
        "protocol_erratum_required": True,
    }
    output["output_sha256"] = _sha256(output)
    Path(arguments.output).write_text(_canonical_json(output) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
