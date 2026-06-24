from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import autoresearch.research.brainstorm as brainstorm_module
from autoresearch.inspiration import InspirationItem, InspirationRefreshReport
from autoresearch.literature import AcademicPaper, LiteratureRefreshReport
from autoresearch.research import (
    BrainstormConfig,
    BrainstormEvidenceSignal,
    BrainstormIdea,
    BrainstormIdeaEvidenceReview,
    run_brainstorm_evidence_review,
    run_inspiration_brainstorm,
)
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


def test_inspiration_brainstorm_records_selection_and_deferred_rationales(
    tmp_path: Path,
) -> None:
    def fake_completion(_prompt, _messages, _temperature):
        return {
            "ideas": [
                {
                    "title": "Feasible creative reranker",
                    "hypothesis": "Source-backed inspiration improves first-pass experiment design.",
                    "rationale": "The idea is creative but still testable with one benchmark.",
                    "novelty_angle": "Uses broad signals only to propose falsifiable candidates.",
                    "experiment_sketch": (
                        "Compare nearest centroid on UCI Pendigits with an evidence-aware "
                        "reranker using macro_f1; falsify if no improvement appears."
                    ),
                    "inspiration_refs": ["inspiration_item_1"],
                    "risks": ["The signal may be too generic."],
                    "creativity_score": 0.92,
                    "feasibility_score": 0.81,
                },
                {
                    "title": "Unbound speculative leap",
                    "hypothesis": "A vague community trend may imply a new method.",
                    "rationale": "It sounds interesting but lacks a concrete first test.",
                    "novelty_angle": "Speculative transfer.",
                    "experiment_sketch": "Try a new model later.",
                    "inspiration_refs": [],
                    "risks": ["No evidence binding."],
                    "creativity_score": 0.45,
                    "feasibility_score": 0.32,
                },
            ]
        }

    report = run_inspiration_brainstorm(
        candidate=_candidate(),
        inspiration_report=_inspiration_report(),
        vault_root=tmp_path / "vault",
        output_dir=tmp_path / "brainstorm",
        config=BrainstormConfig(
            max_miniagents=1,
            ideas_per_agent=2,
            temperature=1.4,
            min_selected_ideas=1,
        ),
        completion_runner=fake_completion,
    )

    assert len(report.selected_ideas) == 1
    assert report.selected_ideas[0].selection_reason.startswith("Selected")
    deferred = [idea for idea in report.ideas if not idea.selected]
    assert deferred
    assert deferred[0].selection_reason.startswith("Deferred")
    assert report.artifact_path is not None
    payload = json.loads(report.artifact_path.read_text(encoding="utf-8"))
    assert payload["ideas"][0]["selection_reason"].startswith("Selected")
    assert payload["ideas"][1]["selection_reason"].startswith("Deferred")
    assert report.summary_path is not None
    summary = report.summary_path.read_text(encoding="utf-8")
    assert "## Selection Argument" in summary
    assert "## Deferred Ideas" in summary


def test_brainstorm_evidence_review_downranks_duplicate_without_penalizing_novel_gap(
    tmp_path: Path,
) -> None:
    def fake_completion(_prompt, _messages, _temperature):
        return {
            "ideas": [
                {
                    "title": "Evidence-bound prototype retrieval",
                    "hypothesis": "A previously proposed evidence-bound retrieval method is repeated.",
                    "rationale": "It repeats a close prior title.",
                    "novelty_angle": "Same-direction duplicate risk.",
                    "experiment_sketch": (
                        "Compare a baseline on UCI Pendigits using macro_f1 and falsify "
                        "if the delta is not positive."
                    ),
                    "inspiration_refs": ["inspiration_item_1"],
                    "risks": ["High duplicate risk."],
                    "creativity_score": 0.97,
                    "feasibility_score": 0.93,
                },
                {
                    "title": "Cross-modal failure cards for research-loop repair",
                    "hypothesis": "Failure cards can guide repair choices in a new research loop.",
                    "rationale": "It borrows from workflow memory rather than cloning a paper.",
                    "novelty_angle": "Adjacent-source borrowing with a new evaluation target.",
                    "experiment_sketch": (
                        "Compare the nearest centroid baseline and a failure-card reranker "
                        "on UCI Pendigits using macro_f1; falsify if macro_f1 or recovery "
                        "delta does not improve."
                    ),
                    "inspiration_refs": ["inspiration_item_1"],
                    "risks": ["The borrowed signal may not transfer."],
                    "creativity_score": 0.84,
                    "feasibility_score": 0.82,
                },
            ]
        }

    def fake_review_runner(candidate, ideas, vault_root, cache_root, config):
        assert candidate.id == "candidate_brainstorm"
        assert vault_root == tmp_path / "vault"
        assert cache_root == tmp_path / "brainstorm" / "evidence-cache"
        assert config.max_reviewed_ideas == 2
        return (
            BrainstormIdeaEvidenceReview(
                idea_id=ideas[0].idea_id,
                queries=("evidence bound prototype retrieval",),
                signals=(
                    BrainstormEvidenceSignal(
                        source="openalex",
                        source_type="literature",
                        title="Evidence-bound prototype retrieval",
                        url="https://example.com/duplicate",
                        query="evidence bound prototype retrieval",
                        summary="Close same-direction prior work.",
                        relevance_score=0.95,
                    ),
                ),
                literature_count=1,
                dataset_count=0,
                code_count=0,
                forum_count=0,
                duplicate_risk="high",
                verifiability="strong",
                doability="strong",
                decision="defer",
                score_adjustment=-0.48,
                reason="High duplicate risk from a close same-direction title match.",
            ),
            BrainstormIdeaEvidenceReview(
                idea_id=ideas[1].idea_id,
                queries=("cross modal failure cards research loop",),
                signals=(),
                literature_count=0,
                dataset_count=0,
                code_count=0,
                forum_count=0,
                duplicate_risk="low",
                verifiability="strong",
                doability="strong",
                decision="promote",
                score_adjustment=0.30,
                reason=(
                    "No close prior-work match; doability comes from a complete dataset, "
                    "baseline, metric, and falsification plan."
                ),
            ),
        )

    report = run_inspiration_brainstorm(
        candidate=_candidate(),
        inspiration_report=_inspiration_report(),
        vault_root=tmp_path / "vault",
        output_dir=tmp_path / "brainstorm",
        config=BrainstormConfig(
            max_miniagents=1,
            ideas_per_agent=2,
            temperature=1.4,
            min_selected_ideas=1,
        ),
        completion_runner=fake_completion,
        evidence_review_runner=fake_review_runner,
        evidence_review_config=brainstorm_module.BrainstormEvidenceReviewConfig(
            max_reviewed_ideas=2
        ),
    )

    assert len(report.evidence_reviews) == 2
    assert len(report.selected_ideas) == 1
    assert report.selected_ideas[0].title == "Cross-modal failure cards for research-loop repair"
    assert "evidence reviewer promoted" in report.selected_ideas[0].selection_reason
    duplicate = next(idea for idea in report.ideas if idea.idea_id.endswith("_1"))
    assert duplicate.selected is False
    assert "duplicate risk `high`" in duplicate.selection_reason
    assert report.artifact_path is not None
    payload = json.loads(report.artifact_path.read_text(encoding="utf-8"))
    assert payload["evidence_reviews"][0]["decision"] == "defer"
    assert report.summary_path is not None
    assert "## Evidence Reviewer" in report.summary_path.read_text(encoding="utf-8")


def test_brainstorm_live_reviewer_treats_missing_close_match_as_novelty_not_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    idea = BrainstormIdea(
        idea_id="novel_1",
        agent_id="unit",
        title="Cross-modal failure cards for research-loop repair",
        hypothesis="Failure cards can guide repair choices in a new research loop.",
        rationale="The idea borrows from workflow memory, not a same-direction clone.",
        novelty_angle="Adjacent borrowing.",
        experiment_sketch=(
            "Compare a nearest centroid baseline and failure-card reranker on UCI "
            "Pendigits using macro_f1; falsify if macro_f1 does not improve."
        ),
        inspiration_refs=("inspiration_item_1",),
        risks=("Transfer may fail.",),
        creativity_score=0.84,
        feasibility_score=0.82,
        evidence_binding_score=1.0,
        selection_score=0.86,
    )

    def fake_literature_sources(**_kwargs):
        return LiteratureRefreshReport(
            queries=(),
            fetches=(),
            papers=(
                AcademicPaper(
                    title="Unrelated graph neural networks for molecule property prediction",
                    abstract="A distant machine learning paper.",
                    url="https://example.com/unrelated",
                    source="openalex",
                ),
            ),
            documents=(),
            summary_path=None,
        )

    def fake_ecosystem_sources(**_kwargs):
        return InspirationRefreshReport(
            queries=("cross modal failure cards research loop",),
            fetches=(),
            items=(),
            summary_path=None,
        )

    monkeypatch.setattr(brainstorm_module, "_review_literature_sources", fake_literature_sources)
    monkeypatch.setattr(brainstorm_module, "_review_ecosystem_sources", fake_ecosystem_sources)

    reviews = run_brainstorm_evidence_review(
        candidate=_candidate(),
        ideas=(idea,),
        vault_root=tmp_path / "vault",
        cache_root=tmp_path / "cache",
    )

    assert len(reviews) == 1
    assert reviews[0].duplicate_risk == "low"
    assert reviews[0].doability == "strong"
    assert reviews[0].verifiability == "strong"
    assert reviews[0].decision == "revise"
    assert "novelty potential" in reviews[0].reason
