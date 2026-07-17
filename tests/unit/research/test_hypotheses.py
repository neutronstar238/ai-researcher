import pytest

from autoresearch.research import generate_hypotheses
from autoresearch.schemas import CandidateStatus, ResearchCandidate


def _candidate(status: CandidateStatus = CandidateStatus.APPROVED) -> ResearchCandidate:
    return ResearchCandidate(
        id="candidate_1",
        title="Reduce limited reproducibility in transformer on autoresearch",
        description="A candidate.",
        research_gap="Repeated literature signals mention limited reproducibility.",
        novelty_score=0.7,
        feasibility_score=0.8,
        impact_score=0.6,
        evidence_refs=["doc_1", "doc_2"],
        status=status,
        metadata={
            "method": "transformer",
            "dataset": "autoresearch",
            "limitation": "limited reproducibility",
        },
    )


def test_generate_hypotheses_from_approved_candidate() -> None:
    hypotheses = generate_hypotheses(_candidate())

    assert len(hypotheses) == 1
    hypothesis = hypotheses[0]
    assert hypothesis.candidate_id == "candidate_1"
    assert hypothesis.metric == "reproducibility_rate"
    assert hypothesis.dataset_ref == "autoresearch"
    assert hypothesis.baseline == "best retrieved baseline"
    assert hypothesis.evidence_refs == ["doc_1", "doc_2"]
    assert "transformer" in hypothesis.statement
    assert "reproducibility_rate" in hypothesis.prediction


def test_generate_hypotheses_rejects_unapproved_candidate() -> None:
    with pytest.raises(PermissionError):
        generate_hypotheses(_candidate(CandidateStatus.READY_FOR_REVIEW))


def test_generate_hypotheses_respects_explicit_compiled_metric() -> None:
    candidate = _candidate().model_copy(
        update={"metadata": {**_candidate().metadata, "metric": "derivative_nmse"}}
    )

    hypothesis = generate_hypotheses(candidate)[0]

    assert hypothesis.metric == "derivative_nmse"
