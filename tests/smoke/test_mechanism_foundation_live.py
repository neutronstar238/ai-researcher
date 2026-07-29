"""Opt-in live verification for the task 261.2.1 mechanism foundation."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.campaign import (
    LiteratureArea,
    build_task2612_research_brief,
    freeze_task2612_foundation,
    load_mechanism_foundation,
    load_parent_sprint_evidence,
)
from autoresearch.campaign.mechanism_round import (
    EXPECTED_PARENT_AUDIT_HASH,
    EXPECTED_PARENT_ENDPOINT_HASH,
    EXPECTED_PARENT_MANIFEST_HASH,
)
from autoresearch.competition.manifest import write_json_model

LIVE_ENV = "AUTORESEARCH_MECHANISM_FOUNDATION_LIVE"
PARENT_ENV = "AUTORESEARCH_MECHANISM_FOUNDATION_PARENT"
OUTPUT_ENV = "AUTORESEARCH_MECHANISM_FOUNDATION_OUTPUT"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to revalidate the formal clean-v2 parent and "
        "the official literature locators"
    ),
)

OFFICIAL_SOURCE_HOSTS = {
    "aclanthology.org",
    "arxiv.org",
    "conf.researchr.org",
    "csrc.nist.gov",
    "openreview.net",
    "papers.nips.cc",
    "www.nature.com",
}


def test_formal_parent_and_verified_sources_freeze_live() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    parent_root = Path(
        os.getenv(
            PARENT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task261-bounded-autonomous-clean-v2"
            ),
        )
    ).resolve()
    output_root = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task2612-mechanism-foundation-live-v3"
            ),
        )
    ).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise AssertionError("mechanism foundation smoke output must be absent or empty")

    parent_probe = load_parent_sprint_evidence(parent_root)
    brief_probe = build_task2612_research_brief(parent_probe)
    assert parent_probe.manifest_hash == EXPECTED_PARENT_MANIFEST_HASH
    assert parent_probe.endpoint_hash == EXPECTED_PARENT_ENDPOINT_HASH
    assert parent_probe.autonomy_audit_hash == EXPECTED_PARENT_AUDIT_HASH
    assert len(parent_probe.revealed_task_ids) == 10
    assert {
        area: sum(area in source.areas for source in brief_probe.sources)
        for area in LiteratureArea
    } == {
        LiteratureArea.SELECTIVE_FACTUALITY: 4,
        LiteratureArea.SCIENTIFIC_AGENT_EVALUATION: 3,
        LiteratureArea.GENERATED_CODE_SECURITY: 3,
        LiteratureArea.CLAIM_EVIDENCE_ALIGNMENT: 5,
    }

    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = (
        "AutoResearch/0.1 task-261.2.1 source-verification smoke"
    )
    observations: list[dict[str, object]] = []
    for source in brief_probe.sources:
        host = urlparse(source.source_url).hostname
        assert host in OFFICIAL_SOURCE_HOSTS
        response = session.get(source.source_url, timeout=30)
        response.raise_for_status()
        assert len(response.content) >= 1_000
        observations.append(
            {
                "source_id": source.source_id,
                "requested_url": source.source_url,
                "resolved_url": response.url,
                "status_code": response.status_code,
                "content_bytes": len(response.content),
            }
        )

    freeze_task2612_foundation(
        parent_sprint_dir=parent_root,
        output_dir=output_root,
        frozen_at=datetime.now(timezone.utc),
    )
    manifest, parent, brief = load_mechanism_foundation(output_root)
    assert parent == parent_probe
    assert brief == brief_probe
    assert manifest.external_submission_authorized is False
    write_json_model(
        output_root / "source-reachability.json",
        {
            "schema_version": "mechanism-source-reachability-v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "research_brief_hash": brief.brief_hash,
            "observations": observations,
            "external_submission_authorized": False,
        },
    )
