import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research import confirmatory_evaluation as confirmation
from autoresearch.research.confirmatory_evaluation import (
    ConfirmationRevealLedger,
    ConfirmationStatus,
    ConfirmatoryLabels,
    ConfirmatoryStatisticalPolicy,
    ConfirmatoryTaskPolicyOutcome,
    FrozenPolicyMemory,
    audit_independent_execution_source,
    confirmation_status,
    exact_paired_risk_difference_interval,
)

SHA = "a" * 64


def test_statistical_policy_freezes_all_prospective_endpoint_checks() -> None:
    policy = ConfirmatoryStatisticalPolicy.create()

    assert policy.independent_task_count == 60
    assert policy.task_aggregation_rule == "at least two of three seed successes"
    assert "never across tasks" in policy.memory_independence_rule
    assert policy.primary_test == "two-sided exact McNemar/sign test"
    assert policy.paired_bootstrap_resamples == 20_000
    assert policy.domain_block_bootstrap_resamples == 20_000
    assert len(policy.secondary_comparison_ids) == 10
    assert len(policy.positive_endpoint_checks) == 13
    assert "null-control-zero-integrity-failures" in policy.positive_endpoint_checks
    assert "full-clean-room-scientific-projection-exact" in policy.positive_endpoint_checks


def test_development_memory_is_frozen_as_a_per_task_clone() -> None:
    memory = FrozenPolicyMemory.create(
        policy_id="portfolio_memory",
        state={
            "F1": {"linear": [0.1, -0.05]},
            "F2": {"linear": [0.02]},
        },
    )

    assert memory.source_partition == "development"
    assert memory.clone_per_confirmatory_unit is True
    assert memory.cross_confirmatory_unit_updates_allowed is False
    assert memory.within_unit_seed_updates_allowed is True
    assert len(memory.state_hash) == 64


def test_exact_paired_interval_is_symmetric_and_conservative() -> None:
    positive = exact_paired_risk_difference_interval(20, 5)
    negative = exact_paired_risk_difference_interval(5, 20)
    tied = exact_paired_risk_difference_interval(0, 0)

    assert positive == pytest.approx(
        (0.003625566910197553, 0.4620569001804539),
        abs=1e-14,
    )
    assert negative == pytest.approx((-positive[1], -positive[0]), abs=1e-14)
    assert tied == pytest.approx(
        (-0.07043056879850468, 0.07043056879850468),
        abs=1e-14,
    )
    assert exact_paired_risk_difference_interval(15, 0)[0] > 0


def test_bootstrap_sensitivities_are_deterministic_and_domain_blocked() -> None:
    values = [1.0, 0.0, -1.0, 1.0]
    differences = {f"u-{index}": value for index, value in enumerate(values)}
    domains = {
        "u-0": "domain-a",
        "u-1": "domain-a",
        "u-2": "domain-b",
        "u-3": "domain-b",
    }

    paired_first = confirmation._paired_bootstrap(
        values,
        seed_material="fixed",
        resamples=500,
    )
    paired_second = confirmation._paired_bootstrap(
        values,
        seed_material="fixed",
        resamples=500,
    )
    blocked_first = confirmation._domain_block_bootstrap(
        differences,
        domains,
        seed_material="fixed",
        resamples=500,
    )
    blocked_second = confirmation._domain_block_bootstrap(
        differences,
        domains,
        seed_material="fixed",
        resamples=500,
    )

    assert paired_first == paired_second
    assert blocked_first == blocked_second
    assert paired_first[0] <= paired_first[1]
    assert blocked_first[0] <= blocked_first[1]


def test_arff_parser_handles_sparse_nominal_defaults_and_quoted_commas() -> None:
    attributes, rows = confirmation._decode_arff(
        b"""@relation robust
@attribute numeric_feature numeric
@attribute nominal_feature {base,'red,blue'}
@attribute class {A,B}
@data
{0 3.5,2 B}
1,'red,blue',A
"""
    )

    assert [item[0] for item in attributes] == [
        "numeric_feature",
        "nominal_feature",
        "class",
    ]
    assert rows[0] == ["3.5", "base", "B"]
    assert rows[1] == ["1", "red,blue", "A"]


def test_baseline_resume_preserves_failed_attempt_and_uses_next_exact_success(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in ("input-manifest.json", "train.csv", "test.csv"):
        (bundle / name).write_text(name, encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text("raise SystemExit(99)\n", encoding="utf-8")
    attempts = tmp_path / "output" / "baseline-replay" / "primary" / "opaque-unit" / "attempts"
    for number, return_code in ((1, 1), (2, 0)):
        attempt = attempts / f"attempt-{number:02d}"
        result_dir = attempt / "result"
        result_dir.mkdir(parents=True)
        (result_dir / "runner-result.json").write_text(
            json.dumps({"attempt": number}),
            encoding="utf-8",
        )
        (attempt / "attempt-status.json").write_text(
            json.dumps(
                {
                    "return_code": return_code,
                    "timed_out": False,
                    "result_exists": True,
                }
            ),
            encoding="utf-8",
        )

    result, workspace = confirmation._run_baseline_once(
        role="primary",
        unit_id="opaque-unit",
        bundle_dir=bundle,
        output_dir=tmp_path / "output",
        interpreter=tmp_path / "unused-python",
        runner_source=runner,
        timeout=1,
    )

    assert result == {"attempt": 2}
    assert workspace.name == "attempt-02"
    assert (attempts / "attempt-01/attempt-status.json").exists()


def test_task_outcome_uses_two_of_three_without_seed_pseudoreplication() -> None:
    outcome = ConfirmatoryTaskPolicyOutcome.create(
        unit_id="unit-1",
        policy_id="portfolio_memory",
        family="tabular_classification",
        benchmark_id="OpenML-CC18",
        domain="medical",
        seed_successes={"1729": True, "3253": False, "7919": True},
        seed_margins={"1729": 1.2, "3253": 0.8, "7919": 1.1},
        successful_seed_count=2,
        task_success=True,
        median_margin=1.1,
        attributable_failure_seed_count=0,
    )

    assert outcome.task_success is True
    assert outcome.successful_seed_count == 2
    with pytest.raises(ValidationError):
        ConfirmatoryTaskPolicyOutcome.create(
            unit_id="unit-1",
            policy_id="portfolio_memory",
            family="tabular_classification",
            benchmark_id="OpenML-CC18",
            domain="medical",
            seed_successes={"1729": True, "3253": False, "7919": True},
            seed_margins={"1729": 1.2, "3253": 0.8, "7919": 1.1},
            successful_seed_count=2,
            task_success=False,
            median_margin=1.1,
            attributable_failure_seed_count=0,
        )


def test_confirmation_labels_require_one_use_confirmatory_binding() -> None:
    labels = ConfirmatoryLabels.create(
        unit_id="unit-1",
        opaque_unit_id="opaque-unit-1",
        family="tabular_classification",
        confirmation_freeze_hash=SHA,
        reveal_hash="b" * 64,
        row_ids=[3, 5],
        labels=["A", "B"],
        data_sha256="c" * 64,
        split_sha256="d" * 64,
        source_data_md5="e" * 32,
    )

    assert labels.partition == "confirmatory"
    assert labels.one_use_reveal is True
    tampered = labels.model_dump(mode="json")
    tampered["partition"] = "development"
    with pytest.raises(ValidationError):
        ConfirmatoryLabels.model_validate(tampered)


def test_reveal_ledger_is_single_use_and_result_blind() -> None:
    ledger = ConfirmationRevealLedger.create(
        freeze_hash=SHA,
        preregistration_hash="b" * 64,
        confirmatory_unit_ids=[f"unit-{index:02d}" for index in range(60)],
        opened_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert ledger.reveal_ordinal == 1
    assert ledger.previous_reveal_exists is False
    assert ledger.result_record_count_at_open == 0
    assert ledger.outcome_adaptive_change_authorized is False


def test_independent_source_audit_rejects_network_and_development_locator(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe.py"
    networked = tmp_path / "networked.py"
    development_locator = tmp_path / "development_locator.py"
    safe.write_text("import json\nprint(json.dumps({}))\n", encoding="utf-8")
    networked.write_text("import requests\nrequests.get('x')\n", encoding="utf-8")
    development_locator.write_text(
        "print('task2635-development-search')\n",
        encoding="utf-8",
    )

    assert audit_independent_execution_source(safe) is True
    assert audit_independent_execution_source(networked) is False
    assert audit_independent_execution_source(development_locator) is False
    assert audit_independent_execution_source(
        Path("src/autoresearch/research/assets/" "frozen_confirmation_policy_controller_v1.py")
    )
    assert audit_independent_execution_source(
        Path("src/autoresearch/research/assets/" "frozen_tabular_confirmation_runner_v1.py")
    )
    controller_source = Path(
        "src/autoresearch/research/assets/" "frozen_confirmation_policy_controller_v1.py"
    ).read_text(encoding="utf-8")
    assert "memory_by_policy_unit" in controller_source
    assert "cross_confirmatory_unit_memory_updates_allowed" in controller_source


def test_confirmation_runner_keeps_labels_out_of_low_fidelity_selection() -> None:
    source = Path(
        "src/autoresearch/research/assets/" "frozen_tabular_confirmation_runner_v1.py"
    ).read_text(encoding="utf-8")

    assert 'if config["stage"] == "F3"' in source
    assert "else None" in source
    assert "encoder.fit(y_all_raw)" in source
    assert "encoder.fit(np.concatenate" not in source
    assert "scored_predictions = encoder.inverse_transform" in source


def test_report_status_is_a_strict_validity_and_endpoint_conjunction() -> None:
    assert (
        confirmation_status({"effect": True}, {"valid": True})
        is ConfirmationStatus.POSITIVE_CONFIRMATION
    )
    assert (
        confirmation_status({"effect": False}, {"valid": True})
        is ConfirmationStatus.CREDIBLE_NEGATIVE_CONFIRMATION
    )
    assert (
        confirmation_status({"effect": True}, {"valid": False})
        is ConfirmationStatus.INVALID_CONFIRMATION
    )
