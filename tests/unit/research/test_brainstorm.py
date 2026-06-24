from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.inspiration import InspirationItem, InspirationRefreshReport
from autoresearch.research import BrainstormConfig, run_inspiration_brainstorm
from autoresearch.schemas import ResearchCandidate


def _candidate() -> ResearchCandidate:
    return ResearchCandidate(
        id="candidate_brainstorm",
        title="Evidence-bound prototype retrieval",
        description="Use retrieval signals to improve evidence-bound experiment design.",
        research_gap="Research plans underuse broad inspiration before experiment design.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.65,
        evidence_refs=["seed"],
        metadata={
            "method": "evidence-aware candidate reranker",
            "dataset": "UCI Pendigits",
            "baseline": "nearest centroid baseline",
            "metric": "macro_f1",
        },
    )


def _inspiration_report() -> InspirationRefreshReport:
    return InspirationRefreshReport(
        queries=("machine learning benchmark dataset",),
        fetches=(),
        items=(
            InspirationItem(
                source="hacker_news",
                source_type="forum_signal",
                title="Show HN: SemHash",
                url="https://github.com/MinishLab/semhash",
                query="machine learning benchmark dataset",
                summary="Community signal for cleaner datasets.",
                score=42.0,
                retrieved_at=datetime.now(timezone.utc),
            ),
        ),
        summary_path=Path("vault/exploration/inspiration/inspiration.md"),
    )


def test_inspiration_brainstorm_records_prompts_raw_ideas_and_selected_summary(
    tmp_path: Path,
) -> None:
    temperatures: list[float] = []

    def fake_completion(prompt, messages, temperature):
        temperatures.append(temperature)
        assert prompt.role in messages[1]["content"]
        assert "inspiration_item_1" in messages[1]["content"]
        return {
            "ideas": [
                {
                    "title": f"{prompt.agent_id} idea",
                    "hypothesis": "A cleaner inspiration signal improves candidate evidence binding.",
                    "rationale": "It links broad community signals to a falsifiable benchmark run.",
                    "novelty_angle": "Use non-scholarly signals only to propose, not prove, research gaps.",
                    "experiment_sketch": (
                        "Compare nearest centroid baseline on UCI Pendigits with and without "
                        "the evidence-aware reranker using macro_f1; falsify if macro_f1 does not improve."
                    ),
                    "inspiration_refs": ["inspiration_item_1"],
                    "risks": ["Community signal may not transfer to the benchmark."],
                    "creativity_score": 0.91,
                    "feasibility_score": 0.76,
                }
            ]
        }

    report = run_inspiration_brainstorm(
        candidate=_candidate(),
        inspiration_report=_inspiration_report(),
        vault_root=tmp_path / "vault",
        output_dir=tmp_path / "brainstorm",
        config=BrainstormConfig(max_miniagents=2, ideas_per_agent=1, temperature=1.25),
        completion_runner=fake_completion,
    )

    assert report.status == "selected"
    assert len(report.ideas) == 2
    assert len(report.selected_ideas) == 2
    assert all(temperature >= 1.25 for temperature in temperatures)
    assert report.artifact_path is not None
    assert report.summary_path is not None
    assert report.prompt_set_path is not None
    payload = json.loads(report.artifact_path.read_text(encoding="utf-8"))
    assert payload["selected_ideas"][0]["inspiration_refs"] == ["inspiration_item_1"]
    assert "Temporary miniagents" in report.summary_path.read_text(encoding="utf-8")
    assert "Brainstorm Miniagent Prompt Set" in report.prompt_set_path.read_text(
        encoding="utf-8"
    )
