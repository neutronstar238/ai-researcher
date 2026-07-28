from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from autoresearch.evidence import (
    build_campaign_round_provenance,
    project_evidence_v1,
)
from autoresearch.kernel import (
    ClaimTraceError,
    EvidenceDirection,
    ProvenanceBundle,
    ProvenanceIntegrityError,
)
from autoresearch.knowledge import project_provenance_to_vault

LIVE_ENV = "AUTORESEARCH_PROVENANCE_REAL_ROUND"
CAMPAIGN_ENV = "AUTORESEARCH_PROVENANCE_CAMPAIGN"
OUTPUT_ENV = "AUTORESEARCH_PROVENANCE_OUTPUT"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=f"set {LIVE_ENV}=1 to query the validated task260 campaign round",
)


def test_real_campaign_round_has_tamper_blocking_source_to_decision_trace(
    tmp_path: Path,
) -> None:
    campaign_dir = Path(
        os.getenv(
            CAMPAIGN_ENV,
            "runs/manual-live/task260-autonomous-ccfb-v1",
        )
    ).resolve()
    if not campaign_dir.is_dir():
        pytest.fail(f"configured real campaign directory does not exist: {campaign_dir}")
    output_root = Path(os.getenv(OUTPUT_ENV, str(tmp_path))).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    projection = build_campaign_round_provenance(campaign_dir, "round-001")
    bundle = projection.bundle
    trace = bundle.require_claim_trace(projection.core_claim_id)
    legacy = project_evidence_v1(bundle)
    legacy.require_core_claim_coverage([projection.core_claim_id])
    vault_result = project_provenance_to_vault(
        bundle,
        output_root / "vault",
        approved_record_ids=projection.approved_record_ids,
    )

    assert bundle.metadata["round_manifest_hash"] == (
        "3d62d24e37c417a78931010f284909b701857bbd56f1457586f9ccdd4d2c9c5e"
    )
    assert trace.agent_ids == [
        "agent.task260-autonomous-ccfb-v1.round-001.adjudicator",
        "agent.task260-autonomous-ccfb-v1.round-001.official-executor",
    ]
    assert {
        "entity.task260-autonomous-ccfb-v1.round-001.frozen-protocol",
        "entity.task260-autonomous-ccfb-v1.round-001.official-executor",
        "entity.task260-autonomous-ccfb-v1.round-001.unseen-evaluation",
    }.issubset(trace.input_entity_ids)
    assert trace.validation_ids == [
        "validation.task260-autonomous-ccfb-v1.round-001.failed-gate"
    ]
    assert trace.decision_ids == [
        "decision.task260-autonomous-ccfb-v1.round-001.next-round"
    ]
    hypothesis_directions = {
        item.direction
        for item in bundle.evidence
        if item.claim_id == projection.hypothesis_claim_id
    } | {
        item.direction
        for item in bundle.counterevidence
        if item.claim_id == projection.hypothesis_claim_id
    }
    assert hypothesis_directions == {
        EvidenceDirection.CONTRADICTS,
        EvidenceDirection.LIMITS,
    }
    assert len(vault_result.written_paths) == len(projection.approved_record_ids)
    serialized = bundle.model_dump_json()
    assert "E:/AIResearch" not in serialized
    assert "E:\\\\AIResearch" not in serialized

    tampered = bundle.model_copy(deep=True)
    tampered.entities[0].label = "tampered after bundle validation"
    with pytest.raises(ProvenanceIntegrityError, match="failed integrity"):
        tampered.require_claim_trace(projection.core_claim_id)

    payload: dict[str, Any] = bundle.model_dump(
        mode="python",
        exclude={"bundle_hash"},
    )
    payload["generations"] = [
        generation
        for generation in payload["generations"]
        if generation["entity_id"]
        != "entity.task260-autonomous-ccfb-v1.round-001.contribution-gate"
    ]
    missing_required_node = ProvenanceBundle.create(**payload)
    with pytest.raises(ClaimTraceError, match="artifact generation"):
        missing_required_node.require_claim_trace(projection.core_claim_id)

    bundle.save_json(output_root / "provenance-bundle.json")
    legacy.save_json(output_root / "evidence-v1-compatibility.json")
    (output_root / "claim-trace.json").write_text(
        trace.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (output_root / "smoke-summary.json").write_text(
        json.dumps(
            {
                "bundle_hash": bundle.bundle_hash,
                "core_claim_id": projection.core_claim_id,
                "trace": trace.model_dump(mode="json"),
                "v1_claim_count": len(legacy.claims),
                "v1_evidence_count": len(legacy.evidence),
                "vault_written_paths": vault_result.written_paths,
                "tamper_blocked": True,
                "missing_generation_blocked": True,
                "private_paths_included": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
