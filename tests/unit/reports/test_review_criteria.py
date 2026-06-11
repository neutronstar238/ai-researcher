from pathlib import Path

from autoresearch.reports import (
    PaperReviewContext,
    ReviewDimension,
    load_review_criteria,
    simulate_paper_review,
)


def test_load_review_criteria_returns_generic_default_and_unknown_fallback() -> None:
    generic = load_review_criteria()
    fallback = load_review_criteria("Missing Venue")

    assert generic.venue == "generic"
    assert generic.acceptance_threshold == 0.70
    assert set(generic.dimension_weights) == set(ReviewDimension)
    assert generic.required_compliance_checks == ("has_limitations", "has_references")

    assert fallback.venue == "generic"
    assert fallback.requested_venue == "Missing Venue"
    assert fallback.is_fallback is True


def test_load_review_criteria_uses_custom_venue_file(tmp_path: Path) -> None:
    criteria_path = tmp_path / "review-criteria.yaml"
    criteria_path.write_text(
        """
venues:
  demo-conf:
    display_name: Demo Conference
    acceptance_threshold: 0.83
    dimension_weights:
      novelty: 2.0
      technical_soundness: 1.5
    rubric:
      novelty: Must make a clear venue-specific contribution.
      technical_soundness: Must trace core claims to validated evidence.
    formatting_requirements:
      - has_demo_template
    content_policies:
      - has_ethics_statement
""".strip(),
        encoding="utf-8",
    )

    criteria = load_review_criteria("Demo Conf", criteria_path=criteria_path)

    assert criteria.venue == "demo-conf"
    assert criteria.display_name == "Demo Conference"
    assert criteria.acceptance_threshold == 0.83
    assert criteria.dimension_weights[ReviewDimension.NOVELTY] == 2.0
    assert criteria.rubric[ReviewDimension.TECHNICAL_SOUNDNESS].startswith("Must trace")
    assert criteria.required_compliance_checks == (
        "has_demo_template",
        "has_ethics_statement",
    )


def test_review_simulator_records_custom_criteria_in_report(tmp_path: Path) -> None:
    criteria_path = tmp_path / "review-criteria.yaml"
    criteria_path.write_text(
        """
venues:
  demo-conf:
    display_name: Demo Conference
    acceptance_threshold: 0.83
    dimension_weights:
      compliance: 2.0
    formatting_requirements:
      - has_demo_template
    content_policies:
      - has_ethics_statement
""".strip(),
        encoding="utf-8",
    )

    report = simulate_paper_review(
        PaperReviewContext(
            title="Demo Paper",
            target_venue="demo-conf",
            criteria_path=criteria_path,
            compliance_checks={
                "has_demo_template": True,
                "has_ethics_statement": True,
            },
        )
    )

    payload = report.to_dict()

    assert report.criteria.venue == "demo-conf"
    assert report.criteria.source == criteria_path.as_posix()
    assert report.criteria.acceptance_threshold == 0.83
    assert report.score_for(ReviewDimension.COMPLIANCE) == 0.8
    assert payload["criteria"]["venue"] == "demo-conf"
    assert payload["meets_acceptance_threshold"] is False
