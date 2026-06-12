from pathlib import Path

from autoresearch.compliance import (
    LicenseFindingSeverity,
    LicenseMetadataStatus,
    LicensePolicy,
    LicenseScanTarget,
    LicenseScanTargetType,
    scan_license_metadata,
)


def test_project_notice_tracks_third_party_reference_policy() -> None:
    root = Path(__file__).resolve().parents[3]
    notice = (root / "NOTICE").read_text(encoding="utf-8")
    third_party = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "THIRD_PARTY_NOTICES.md" in notice
    for required in (
        "HKUDS AI-Researcher",
        "aiming-lab/AutoResearchClaw",
        "karpathy/autoresearch",
        "Thysrael/Horizon",
        "UltraClr/agent-arxiv-daily",
        "Microsoft SkillOpt",
        "OpenClaw",
        "farion1231/cc-switch",
        "larksuite/openclaw-lark",
        "Tencent/openclaw-weixin",
        "WecomTeam/wecom-openclaw-plugin",
        "OpenClaw official channel plugins",
        "UCI Pen-Based Recognition of Handwritten Digits",
        "OpenAlex",
        "IEEEtran",
        "ACM acmart",
        "Springer Nature LaTeX authoring template",
    ):
        assert required in third_party
    assert "copy, vendor, adapt, or redistribute" in third_party
    assert "Do not copy or adapt" in third_party


def test_license_scanner_accepts_dataset_code_and_package_metadata(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    third_party = tmp_path / "vendor-lib"
    package = tmp_path / "package"
    dataset.mkdir()
    third_party.mkdir()
    package.mkdir()
    (dataset / "metadata.json").write_text('{"license": "CC-BY-4.0"}', encoding="utf-8")
    (third_party / "LICENSE").write_text("MIT License", encoding="utf-8")
    (package / "manifest.json").write_text(
        '{"licenses": [{"name": "Apache-2.0"}]}',
        encoding="utf-8",
    )

    report = scan_license_metadata(
        (
            LicenseScanTarget(dataset, LicenseScanTargetType.DATASET),
            LicenseScanTarget(third_party, LicenseScanTargetType.THIRD_PARTY_CODE),
            LicenseScanTarget(package, LicenseScanTargetType.GENERATED_PACKAGE),
        )
    )

    assert report.passed
    assert report.warning_count == 0
    assert report.failure_count == 0
    assert {finding.status for finding in report.findings} == {LicenseMetadataStatus.FOUND}


def test_missing_license_metadata_uses_default_policy(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    third_party = tmp_path / "vendor-lib"
    package = tmp_path / "package"
    dataset.mkdir()
    third_party.mkdir()
    package.mkdir()

    report = scan_license_metadata(
        (
            LicenseScanTarget(dataset, LicenseScanTargetType.DATASET, label="benchmark dataset"),
            LicenseScanTarget(third_party, LicenseScanTargetType.THIRD_PARTY_CODE),
            LicenseScanTarget(package, LicenseScanTargetType.GENERATED_PACKAGE),
        )
    )

    severities = [finding.severity for finding in report.findings]
    assert not report.passed
    assert report.warning_count == 1
    assert report.failure_count == 2
    assert severities == [
        LicenseFindingSeverity.WARNING,
        LicenseFindingSeverity.FAILURE,
        LicenseFindingSeverity.FAILURE,
    ]
    assert "benchmark dataset" in report.findings[0].message


def test_policy_can_downgrade_generated_package_missing_license_to_warning(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    report = scan_license_metadata(
        (LicenseScanTarget(package, LicenseScanTargetType.GENERATED_PACKAGE),),
        policy=LicensePolicy(missing_generated_package=LicenseFindingSeverity.WARNING),
    )

    assert report.passed
    assert report.warning_count == 1
    assert report.failure_count == 0


def test_empty_json_license_metadata_is_reported_missing(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text('{"license": ""}', encoding="utf-8")

    report = scan_license_metadata(
        (LicenseScanTarget(package, LicenseScanTargetType.GENERATED_PACKAGE),)
    )

    assert not report.passed
    assert report.findings[0].status is LicenseMetadataStatus.MISSING
    assert report.findings[0].severity is LicenseFindingSeverity.FAILURE
