"""Build reproducibility packages for validated research runs."""

from __future__ import annotations

import json
import platform
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from autoresearch.schemas import ValidationStatus, file_hash

DEFAULT_MAX_RAW_DATA_BYTES = 10 * 1024 * 1024
SECRET_NAME_FRAGMENTS = (
    ".env",
    "api_key",
    "apikey",
    "credential",
    "id_rsa",
    "password",
    "private_key",
    "secret",
    "token",
)


class ReproducibilityPackageError(ValueError):
    """Raised when a reproducibility package cannot be created."""


class ReproducibilityArtifactRole(str, Enum):
    """Artifact roles supported by a reproducibility package."""

    CODE = "code"
    CONFIG = "config"
    METRICS = "metrics"
    REPORT = "report"
    EVIDENCE_MAP = "evidence_map"
    VALIDATION = "validation"
    RAW_DATA = "raw_data"
    OTHER = "other"


@dataclass(frozen=True)
class ReproducibilityArtifactInput:
    """Source artifact to include or evaluate for packaging."""

    source_path: Path | str
    role: ReproducibilityArtifactRole
    package_path: str | None = None
    required: bool = True


@dataclass(frozen=True)
class ReproducibilityPackageArtifact:
    """Included artifact metadata stored in the package manifest."""

    role: ReproducibilityArtifactRole
    source_path: str
    package_path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "source_path": self.source_path,
            "package_path": self.package_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ExcludedReproducibilityArtifact:
    """Artifact intentionally excluded from the package."""

    role: ReproducibilityArtifactRole
    source_path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role.value,
            "source_path": self.source_path,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReproducibilityPackage:
    """Created reproducibility package paths and manifest metadata."""

    package_dir: str
    manifest_path: str
    environment_notes_path: str
    artifacts: tuple[ReproducibilityPackageArtifact, ...]
    excluded_artifacts: tuple[ExcludedReproducibilityArtifact, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_dir": self.package_dir,
            "manifest_path": self.manifest_path,
            "environment_notes_path": self.environment_notes_path,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "excluded_artifacts": [
                artifact.to_dict()
                for artifact in self.excluded_artifacts
            ],
        }


def create_reproducibility_package(
    *,
    package_dir: Path | str,
    artifacts: list[ReproducibilityArtifactInput],
    project_id: str,
    run_id: str,
    run_commands: list[str],
    validation_status: ValidationStatus | str,
    environment_notes: list[str] | None = None,
    include_large_raw_data: bool = False,
    max_raw_data_bytes: int = DEFAULT_MAX_RAW_DATA_BYTES,
) -> ReproducibilityPackage:
    """Copy reproducibility artifacts and write a hash-backed manifest."""

    target_dir = Path(package_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    included: list[ReproducibilityPackageArtifact] = []
    excluded: list[ExcludedReproducibilityArtifact] = []

    for artifact in artifacts:
        source_path = Path(artifact.source_path)
        if not source_path.exists():
            if artifact.required:
                raise ReproducibilityPackageError(
                    f"required artifact is missing: {source_path}"
                )
            excluded.append(
                ExcludedReproducibilityArtifact(
                    artifact.role,
                    source_path.as_posix(),
                    "missing optional artifact",
                )
            )
            continue
        if source_path.is_dir():
            for file_path in sorted(path for path in source_path.rglob("*") if path.is_file()):
                _copy_or_exclude(
                    file_path=file_path,
                    source_root=source_path,
                    artifact=artifact,
                    target_dir=target_dir,
                    included=included,
                    excluded=excluded,
                    include_large_raw_data=include_large_raw_data,
                    max_raw_data_bytes=max_raw_data_bytes,
                )
            continue
        _copy_or_exclude(
            file_path=source_path,
            source_root=source_path,
            artifact=artifact,
            target_dir=target_dir,
            included=included,
            excluded=excluded,
            include_large_raw_data=include_large_raw_data,
            max_raw_data_bytes=max_raw_data_bytes,
        )

    environment_notes_path = target_dir / "environment.md"
    environment_notes_path.write_text(
        _environment_markdown(run_commands, validation_status, environment_notes or []),
        encoding="utf-8",
    )
    manifest_path = target_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "run_id": run_id,
        "validation_status": _validation_status_value(validation_status),
        "run_commands": run_commands,
        "environment_notes_path": environment_notes_path.name,
        "artifacts": [artifact.to_dict() for artifact in included],
        "excluded_artifacts": [artifact.to_dict() for artifact in excluded],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return ReproducibilityPackage(
        package_dir=target_dir.as_posix(),
        manifest_path=manifest_path.as_posix(),
        environment_notes_path=environment_notes_path.as_posix(),
        artifacts=tuple(included),
        excluded_artifacts=tuple(excluded),
    )


def _copy_or_exclude(
    *,
    file_path: Path,
    source_root: Path,
    artifact: ReproducibilityArtifactInput,
    target_dir: Path,
    included: list[ReproducibilityPackageArtifact],
    excluded: list[ExcludedReproducibilityArtifact],
    include_large_raw_data: bool,
    max_raw_data_bytes: int,
) -> None:
    reason = _exclusion_reason(
        file_path,
        artifact.role,
        include_large_raw_data=include_large_raw_data,
        max_raw_data_bytes=max_raw_data_bytes,
    )
    if reason is not None:
        excluded.append(
            ExcludedReproducibilityArtifact(
                artifact.role,
                file_path.as_posix(),
                reason,
            )
        )
        return

    package_path = _package_path(file_path, source_root, artifact)
    destination = target_dir / package_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, destination)
    included.append(
        ReproducibilityPackageArtifact(
            role=artifact.role,
            source_path=file_path.resolve().as_posix(),
            package_path=package_path,
            sha256=file_hash(destination),
            size_bytes=destination.stat().st_size,
        )
    )


def _exclusion_reason(
    path: Path,
    role: ReproducibilityArtifactRole,
    *,
    include_large_raw_data: bool,
    max_raw_data_bytes: int,
) -> str | None:
    lower_name = path.name.casefold()
    if any(fragment in lower_name for fragment in SECRET_NAME_FRAGMENTS):
        return "secret-like filename"
    if (
        role is ReproducibilityArtifactRole.RAW_DATA
        and not include_large_raw_data
        and path.stat().st_size > max_raw_data_bytes
    ):
        return "large raw data excluded by default"
    return None


def _package_path(
    file_path: Path,
    source_root: Path,
    artifact: ReproducibilityArtifactInput,
) -> str:
    if artifact.package_path is not None:
        base = Path(artifact.package_path)
        if file_path == source_root:
            return _safe_package_path(base)
        return _safe_package_path(base / file_path.relative_to(source_root))
    return _safe_package_path(Path(_role_dir(artifact.role)) / file_path.name)


def _safe_package_path(path: Path) -> str:
    if path.is_absolute() or ".." in path.parts:
        raise ReproducibilityPackageError(f"unsafe package path: {path}")
    return path.as_posix()


def _role_dir(role: ReproducibilityArtifactRole) -> str:
    if role is ReproducibilityArtifactRole.EVIDENCE_MAP:
        return "evidence"
    if role is ReproducibilityArtifactRole.RAW_DATA:
        return "data"
    return str(role.value)


def _environment_markdown(
    run_commands: list[str],
    validation_status: ValidationStatus | str,
    environment_notes: list[str],
) -> str:
    lines = [
        "# Reproducibility Environment",
        "",
        f"- Python: `{platform.python_version()}`",
        f"- Platform: `{platform.platform()}`",
        f"- Validation status: `{_validation_status_value(validation_status)}`",
        "",
        "## Run Commands",
        "",
    ]
    if run_commands:
        lines.extend(f"- `{command}`" for command in run_commands)
    else:
        lines.append("- No run commands were provided.")
    lines.extend(["", "## Notes", ""])
    if environment_notes:
        lines.extend(f"- {note}" for note in environment_notes)
    else:
        lines.append("- No additional environment notes were provided.")
    return "\n".join(lines).rstrip() + "\n"


def _validation_status_value(status: ValidationStatus | str) -> str:
    return status.value if isinstance(status, ValidationStatus) else str(status)
