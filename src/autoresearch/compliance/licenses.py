"""License metadata scanner for datasets, third-party code, and packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class LicenseScanTargetType(str, Enum):
    """Supported license scan target families."""

    DATASET = "dataset"
    THIRD_PARTY_CODE = "third_party_code"
    GENERATED_PACKAGE = "generated_package"


class LicenseFindingSeverity(str, Enum):
    """Policy outcome for a license scanner finding."""

    INFO = "info"
    WARNING = "warning"
    FAILURE = "failure"


class LicenseMetadataStatus(str, Enum):
    """Whether license metadata was found for a target."""

    FOUND = "found"
    MISSING = "missing"


@dataclass(frozen=True)
class LicensePolicy:
    """Policy for missing license metadata by target type."""

    missing_dataset: LicenseFindingSeverity = LicenseFindingSeverity.WARNING
    missing_third_party_code: LicenseFindingSeverity = LicenseFindingSeverity.FAILURE
    missing_generated_package: LicenseFindingSeverity = LicenseFindingSeverity.FAILURE

    def missing_severity(self, target_type: LicenseScanTargetType) -> LicenseFindingSeverity:
        """Return severity for one missing license metadata target."""

        if target_type is LicenseScanTargetType.DATASET:
            return self.missing_dataset
        if target_type is LicenseScanTargetType.THIRD_PARTY_CODE:
            return self.missing_third_party_code
        return self.missing_generated_package


@dataclass(frozen=True)
class LicenseScanTarget:
    """One path that must declare license metadata before release."""

    path: Path
    target_type: LicenseScanTargetType
    label: str | None = None


@dataclass(frozen=True)
class LicenseFinding:
    """License metadata scan result for one target."""

    target: LicenseScanTarget
    status: LicenseMetadataStatus
    severity: LicenseFindingSeverity
    message: str
    metadata_path: Path | None = None


@dataclass(frozen=True)
class LicenseScanReport:
    """Aggregated license metadata scan report."""

    findings: tuple[LicenseFinding, ...]

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity is LicenseFindingSeverity.WARNING)

    @property
    def failure_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity is LicenseFindingSeverity.FAILURE)

    @property
    def passed(self) -> bool:
        return self.failure_count == 0


def scan_license_metadata(
    targets: tuple[LicenseScanTarget, ...],
    *,
    policy: LicensePolicy | None = None,
) -> LicenseScanReport:
    """Scan release targets for explicit license metadata."""

    active_policy = policy or LicensePolicy()
    findings = tuple(_scan_target(target, active_policy) for target in targets)
    return LicenseScanReport(findings=findings)


def _scan_target(target: LicenseScanTarget, policy: LicensePolicy) -> LicenseFinding:
    metadata_path = _find_license_metadata(target.path)
    label = target.label or target.path.name
    if metadata_path is not None:
        return LicenseFinding(
            target=target,
            status=LicenseMetadataStatus.FOUND,
            severity=LicenseFindingSeverity.INFO,
            message=f"license metadata found for {label}",
            metadata_path=metadata_path,
        )

    return LicenseFinding(
        target=target,
        status=LicenseMetadataStatus.MISSING,
        severity=policy.missing_severity(target.target_type),
        message=f"missing license metadata for {label}",
    )


def _find_license_metadata(path: Path) -> Path | None:
    if path.is_file():
        return path if _file_has_license_metadata(path) else None
    if not path.exists():
        return None

    for candidate in _candidate_metadata_paths(path):
        if candidate.is_file() and _file_has_license_metadata(candidate):
            return candidate
    return None


def _candidate_metadata_paths(root: Path) -> tuple[Path, ...]:
    return tuple(
        root / name
        for name in (
            "LICENSE",
            "LICENSE.md",
            "LICENSE.txt",
            "COPYING",
            "NOTICE",
            "license.json",
            "metadata.json",
            "manifest.json",
            "dataset-card.md",
            "datasheet.md",
            "README.md",
        )
    )


def _file_has_license_metadata(path: Path) -> bool:
    if path.suffix.casefold() == ".json":
        return _json_has_license_metadata(path)

    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return False
    if path.name.casefold().startswith(("license", "copying", "notice")):
        return True
    return "license:" in text.casefold() or "license =" in text.casefold()


def _json_has_license_metadata(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False

    for key in ("license", "licenses", "license_metadata"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and value:
            return True
    return False
