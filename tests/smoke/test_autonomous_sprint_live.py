from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from autoresearch.campaign.sprint import (
    AutonomousResearchSprint,
    SprintLiteratureItem,
    SprintLiteratureSnapshot,
    SprintSpec,
    _stamp_model,
    _topic_selection_messages,
    installed_sprint_programs,
)
from autoresearch.literature import ArxivClient


@pytest.mark.skipif(
    os.getenv("AUTORESEARCH_RUN_LIVE_SPRINT_SMOKE") != "1",
    reason="set AUTORESEARCH_RUN_LIVE_SPRINT_SMOKE=1 for live ArXiv/Ollama smoke",
)
def test_live_local_qwen_selects_three_executable_sprint_programs() -> None:
    os.environ.setdefault("AUTORESEARCH_LOCAL_OLLAMA_API_KEY", "ollama-local")
    queries = (
        'all:"autonomous research" AND all:evidence',
        'all:"AI scientist" AND all:benchmark',
        'all:"scientific discovery" AND all:agent',
    )
    client = ArxivClient()
    items: list[SprintLiteratureItem] = []
    for query in queries:
        papers = client.search(query, limit=1)
        assert papers, f"ArXiv returned no live evidence for {query}"
        paper = papers[0]
        items.append(
            SprintLiteratureItem(
                evidence_id=f"L{len(items) + 1:03d}",
                title=paper.title,
                authors=tuple(paper.authors),
                abstract=(paper.abstract or "No abstract returned.")[:2_400],
                publication_date=paper.publication_date,
                venue=paper.venue,
                doi=paper.doi,
                url=paper.url or "https://arxiv.org",
                source=paper.source,
                retrieval_query=query,
            )
        )
    snapshot = _stamp_model(
        SprintLiteratureSnapshot(
            sprint_id="live-sprint-smoke",
            retrieved_at=datetime.now(timezone.utc),
            queries=queries,
            items=tuple(items),
        ),
        "snapshot_hash",
    )
    programs = installed_sprint_programs()
    spec = SprintSpec(
        sprint_id="live-sprint-smoke",
        project_id="live-sprint-smoke",
        high_level_brief=(
            "Select the strongest falsifiable local task-level experiment about "
            "evidence-bound autonomous research loops."
        ),
        deadline=datetime.now(timezone.utc) + timedelta(days=30),
        route_a_campaign_path="route-a",
        route_a_manifest_sha256="a" * 64,
        llm_config_path="configs/campaign/ollama-qwen35-sprint-8k.yaml",
        llm_config_sha256="b" * 64,
        program_ids=tuple(program.program_id for program in programs),
        created_at=datetime.now(timezone.utc),
    )
    service = AutonomousResearchSprint()
    _, selection = service._generate_topic_selection(
        spec,
        snapshot,
        programs,
        _topic_selection_messages(spec, snapshot, programs),
    )

    assert selection.model_name == "qwen3.5-sprint:9b-8k"
    assert selection.used_fallback is False
    assert len(selection.candidates) == 3
    assert {candidate.program_id for candidate in selection.candidates} == {
        program.program_id for program in programs
    }
