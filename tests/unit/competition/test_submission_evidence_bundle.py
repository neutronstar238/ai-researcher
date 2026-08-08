"""Task 270.4: one missing proof must keep the submission bundle blocked."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_final_research_report import _lineage

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.submission_evidence_bundle import (
    SubmissionEvidenceBundle,
    SubmissionEvidenceError,
    audit_submission_evidence_bundle,
)

ROOT = Path(__file__).resolve().parents[3]


def _checks(bundle: SubmissionEvidenceBundle) -> dict[str, bool]:
    return {item.name: item.passed for item in bundle.checks}


def test_bundle_is_written_but_never_ready_with_missing_required_proofs(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )

    checks = _checks(bundle)
    assert bundle.submission_ready is False
    assert bundle.publication_ready is False
    assert checks["publication_readiness"] is False
    assert checks["required_audits_present"] is False
    assert checks["broad_quality_gates"] is False
    assert checks["innovation_evidence_audited"] is False
    assert checks["independent_scientific_reexecution"] is False
    assert bundle.human_approval_is_scientific_evidence is False
    assert Path(bundle.output_path).is_file()
    markdown = Path(bundle.output_path).with_suffix(".md").read_text(encoding="utf-8")
    assert "禁止宣称可提交" in markdown
    assert "不生成研究假设、结果解释或创新性主张" in markdown


def test_configured_and_recorded_model_identity_mismatch_blocks(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    config = tmp_path / "mismatch.yaml"
    config.write_text(
        """\
deployment:
  llm:
    provider: another-provider
    base_url: https://example.invalid/v1
    model_name: another-model
    api_key_env: TEST_KEY
""",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=config,
        repository_root=ROOT,
        run_quality_gates=False,
    )

    assert _checks(bundle)["configured_model_identity_matches"] is False
    assert bundle.submission_ready is False


def test_red_broad_quality_command_blocks_even_when_receipt_exists(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    commands = {
        "pytest": (sys.executable, "-c", "print('1 passed')"),
        "ruff": (sys.executable, "-c", "raise SystemExit(1)"),
        "mypy": (sys.executable, "-c", "print('Success')"),
    }
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=True,
        quality_commands=commands,
    )

    assert _checks(bundle)["broad_quality_gates"] is False
    assert bundle.submission_ready is False


def test_hash_valid_package_with_missing_observed_metric_is_still_blocked(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    package_path = lineage / "official-development-search-package.json"
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    payload["overall_median_log_effect"] = None
    payload["package_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"package_hash", "output_path"}
        }
    )
    package_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )

    package_check = next(
        item for item in bundle.checks if item.name == "signed_package_semantics"
    )
    assert package_check.passed is False
    assert any("缺少总体" in finding for finding in package_check.findings)
    assert bundle.submission_ready is False


def test_schema_forbids_submission_ready_while_publication_is_false(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    bundle = audit_submission_evidence_bundle(
        lineage_dir=lineage,
        config_path=ROOT / "config.yaml",
        repository_root=ROOT,
        run_quality_gates=False,
    )
    payload = bundle.model_dump(mode="json")
    payload["submission_ready"] = True
    payload["bundle_hash"] = canonical_model_hash(
        {
            key: value
            for key, value in payload.items()
            if key not in {"bundle_hash", "output_path"}
        }
    )

    with pytest.raises(SubmissionEvidenceError, match="submission-ready"):
        SubmissionEvidenceBundle.model_validate(payload)
