import json
from pathlib import Path

from autoresearch.reports import (
    StrategyEvolutionReportContext,
    generate_strategy_evolution_report,
)


def test_strategy_evolution_report_includes_required_fields_and_links(
    tmp_path: Path,
) -> None:
    context = StrategyEvolutionReportContext(
        strategy_id="strategy_retrieval_policy_v2",
        strategy_card_refs=(
            "autoresearch-vault/exploration/strategy_cards/strategy_retrieval_policy_v2.md",
            "autoresearch-vault/exploration/strategy_cards/strategy_retrieval_policy_v1.md",
        ),
        reason="Shadow evaluation improved recall without reducing citation checks.",
        evidence_refs=(
            "autoresearch-vault/exploration/evidence/shadow_eval_v2",
            "autoresearch-vault/exploration/evidence/golden_suite_mvp",
        ),
        evaluation_summary="Golden suite passed and evidence coverage increased.",
        reward_delta=0.145,
        risks=("Higher retrieval cost during gray release.",),
        release_history=(
            "2026-06-12 shadow evaluation passed.",
            "2026-06-12 promoted to 5 percent gray release.",
        ),
        rollback_target=(
            "autoresearch-vault/exploration/strategy_cards/strategy_retrieval_policy_v1.md"
        ),
        final_decision="Continue gray release with rollback target retained.",
    )

    artifact = generate_strategy_evolution_report(context, output_dir=tmp_path)

    assert artifact.markdown_path == (tmp_path / "strategy-evolution-report.md").as_posix()
    assert artifact.json_path == (tmp_path / "strategy-evolution-report.json").as_posix()

    markdown = (tmp_path / "strategy-evolution-report.md").read_text(encoding="utf-8")
    required_headings = (
        "## Strategy Cards",
        "## Reason",
        "## Evidence",
        "## Evaluation",
        "## Reward Delta",
        "## Risks",
        "## Release History",
        "## Rollback Target",
        "## Final Decision",
    )

    for heading in required_headings:
        assert heading in markdown

    assert (
        "[[autoresearch-vault/exploration/strategy_cards/strategy_retrieval_policy_v2]]"
        in markdown
    )
    assert (
        "[[autoresearch-vault/exploration/strategy_cards/strategy_retrieval_policy_v1]]"
        in markdown
    )
    assert "`+0.145000`" in markdown
    assert "Continue gray release" in markdown

    payload = json.loads(
        (tmp_path / "strategy-evolution-report.json").read_text(encoding="utf-8")
    )
    assert payload["context"]["strategy_id"] == "strategy_retrieval_policy_v2"
    assert payload["context"]["reward_delta"] == 0.145
