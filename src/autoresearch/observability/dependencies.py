"""Dependency diagnostics for local verification commands."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from importlib import metadata


class DependencyStatus(str, Enum):
    """Doctor-facing dependency health status."""

    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class DependencyDiagnostic:
    """One dependency health finding for CLI and logs."""

    name: str
    status: DependencyStatus
    detail: str

    @property
    def blocks_doctor(self) -> bool:
        """Return whether this finding should make doctor exit non-zero."""

        return self.status is DependencyStatus.FAIL


def diagnose_requests_dependency_set(
    versions: Mapping[str, str | None] | None = None,
) -> DependencyDiagnostic:
    """Check the installed Requests dependency set without importing Requests."""

    installed = _load_versions(versions)
    requests_version = installed["requests"]
    urllib3_version = installed["urllib3"]
    charset_version = installed["charset-normalizer"]
    chardet_version = installed["chardet"]
    detail = _format_versions(installed)

    if requests_version is None:
        return DependencyDiagnostic(
            name="requests dependency set",
            status=DependencyStatus.FAIL,
            detail=f"{detail}; requests is declared but not installed",
        )
    if urllib3_version is None:
        return DependencyDiagnostic(
            name="requests dependency set",
            status=DependencyStatus.FAIL,
            detail=f"{detail}; urllib3 is required by requests but not installed",
        )

    warnings: list[str] = []
    if not _in_range(urllib3_version, minimum=(1, 21, 1), maximum=(3, 0, 0)):
        warnings.append("urllib3 should be >=1.21.1 and <3")

    charset_ok = charset_version is not None and _in_range(
        charset_version,
        minimum=(2, 0, 0),
        maximum=(4, 0, 0),
    )
    chardet_ok = chardet_version is not None and _in_range(
        chardet_version,
        minimum=(3, 0, 2),
        maximum=(6, 0, 0),
    )
    if charset_version is None and chardet_version is None:
        warnings.append("either charset-normalizer or chardet should be installed")
    if charset_version is not None and not charset_ok:
        warnings.append("charset-normalizer should be >=2 and <4")
    if chardet_version is not None and not chardet_ok:
        warnings.append("chardet should be >=3.0.2 and <6")

    if warnings:
        return DependencyDiagnostic(
            name="requests dependency set",
            status=DependencyStatus.WARN,
            detail=f"{detail}; {'; '.join(warnings)}",
        )

    return DependencyDiagnostic(
        name="requests dependency set",
        status=DependencyStatus.OK,
        detail=detail,
    )


def _load_versions(
    versions: Mapping[str, str | None] | None,
) -> dict[str, str | None]:
    package_names = ("requests", "urllib3", "charset-normalizer", "chardet")
    if versions is not None:
        return {name: versions.get(name) for name in package_names}
    return {name: _metadata_version(name) for name in package_names}


def _metadata_version(package_name: str) -> str | None:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def _format_versions(versions: Mapping[str, str | None]) -> str:
    return ", ".join(
        f"{name} {value if value is not None else 'not installed'}"
        for name, value in versions.items()
    )


def _in_range(
    version: str,
    *,
    minimum: tuple[int, int, int],
    maximum: tuple[int, int, int],
) -> bool:
    parsed = _parse_version(version)
    return parsed >= minimum and parsed < maximum


def _parse_version(version: str) -> tuple[int, int, int]:
    match = re.match(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if match is None:
        return (0, 0, 0)
    parts = [int(value) if value is not None else 0 for value in match.groups()]
    return (parts[0], parts[1], parts[2])
