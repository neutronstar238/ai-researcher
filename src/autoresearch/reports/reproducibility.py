"""Build reproducibility packages for validated research runs."""

from __future__ import annotations

import json
import platform
import shlex
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


@dataclass(frozen=True)
class ReproducibilityPackageIssue:
    """One package validation issue."""

    check: str
    message: str
    severity: ValidationStatus = ValidationStatus.FAILED
    package_path: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "check": self.check,
            "message": self.message,
            "severity": self.severity.value,
            "package_path": self.package_path,
        }


@dataclass(frozen=True)
class ReproducibilityPackageValidation:
    """Validation report for one reproducibility package."""

    manifest_path: str
    package_dir: str
    status: ValidationStatus
    checked_artifacts: int
    issues: tuple[ReproducibilityPackageIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": self.manifest_path,
            "package_dir": self.package_dir,
            "status": self.status.value,
            "checked_artifacts": self.checked_artifacts,
            "issues": [issue.to_dict() for issue in self.issues],
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


def validate_reproducibility_package(
    manifest_path: Path | str,
) -> ReproducibilityPackageValidation:
    """Validate package artifact presence, hashes, and self-contained paths."""

    path = Path(manifest_path)
    package_dir = path.parent
    if not path.is_file():
        issue = ReproducibilityPackageIssue(
            "manifest_exists",
            f"manifest is missing: {path}",
            package_path=path.as_posix(),
        )
        return ReproducibilityPackageValidation(
            manifest_path=path.as_posix(),
            package_dir=package_dir.as_posix(),
            status=ValidationStatus.FAILED,
            checked_artifacts=0,
            issues=(issue,),
        )

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issue = ReproducibilityPackageIssue(
            "manifest_json",
            f"manifest is not valid JSON: line {exc.lineno}, column {exc.colno}",
            package_path=path.as_posix(),
        )
        return ReproducibilityPackageValidation(
            manifest_path=path.as_posix(),
            package_dir=package_dir.as_posix(),
            status=ValidationStatus.FAILED,
            checked_artifacts=0,
            issues=(issue,),
        )

    issues: list[ReproducibilityPackageIssue] = []
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        issues.append(
            ReproducibilityPackageIssue(
                "manifest_artifacts",
                "manifest artifacts must be a list",
            )
        )
        artifacts = []

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            issues.append(
                ReproducibilityPackageIssue(
                    "manifest_artifact_shape",
                    "artifact entry must be an object",
                )
            )
            continue
        issues.extend(_validate_manifest_artifact(package_dir, artifact))

    run_commands = manifest.get("run_commands", [])
    if isinstance(run_commands, list):
        for command in run_commands:
            if isinstance(command, str):
                issues.extend(_validate_command(command))
            else:
                issues.append(
                    ReproducibilityPackageIssue(
                        "run_command_shape",
                        "run command entries must be strings",
                    )
                )
    else:
        issues.append(
            ReproducibilityPackageIssue(
                "run_commands_shape",
                "manifest run_commands must be a list",
            )
        )

    status = ValidationStatus.FAILED if issues else ValidationStatus.PASSED
    return ReproducibilityPackageValidation(
        manifest_path=path.as_posix(),
        package_dir=package_dir.as_posix(),
        status=status,
        checked_artifacts=len(artifacts),
        issues=tuple(issues),
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


def _validate_manifest_artifact(
    package_dir: Path,
    artifact: dict[str, Any],
) -> list[ReproducibilityPackageIssue]:
    issues: list[ReproducibilityPackageIssue] = []
    package_path_value = artifact.get("package_path")
    expected_hash = artifact.get("sha256")
    if not isinstance(package_path_value, str) or not package_path_value:
        return [
            ReproducibilityPackageIssue(
                "artifact_package_path",
                "artifact package_path must be a non-empty string",
            )
        ]
    if not isinstance(expected_hash, str) or not expected_hash:
        issues.append(
            ReproducibilityPackageIssue(
                "artifact_hash",
                "artifact sha256 must be a non-empty string",
                package_path=package_path_value,
            )
        )
        expected_hash = ""

    package_path = Path(package_path_value)
    if package_path.is_absolute() or ".." in package_path.parts:
        issues.append(
            ReproducibilityPackageIssue(
                "artifact_path_self_contained",
                "artifact package_path must stay inside the package",
                package_path=package_path_value,
            )
        )
        return issues

    resolved_path = package_dir / package_path
    if not resolved_path.is_file():
        issues.append(
            ReproducibilityPackageIssue(
                "artifact_exists",
                f"packaged artifact is missing: {package_path_value}",
                package_path=package_path_value,
            )
        )
        return issues
    actual_hash = file_hash(resolved_path)
    if expected_hash and actual_hash != expected_hash:
        issues.append(
            ReproducibilityPackageIssue(
                "artifact_hash_match",
                "packaged artifact hash does not match manifest sha256",
                package_path=package_path_value,
            )
        )
    return issues


def _validate_command(command: str) -> list[ReproducibilityPackageIssue]:
    issues: list[ReproducibilityPackageIssue] = []
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return [
            ReproducibilityPackageIssue(
                "run_command_parse",
                f"run command cannot be parsed: {exc}",
            )
        ]
    for token in tokens:
        clean_token = token.strip("\"'")
        if not _looks_like_path(clean_token):
            continue
        token_path = Path(clean_token)
        if token_path.is_absolute() or ".." in token_path.parts:
            issues.append(
                ReproducibilityPackageIssue(
                    "run_command_self_contained",
                    f"run command references a package-external path: {clean_token}",
                    package_path=clean_token,
                )
            )
    return issues


def _looks_like_path(token: str) -> bool:
    if token.startswith("-") or "://" in token:
        return False
    return (
        "/" in token
        or "\\" in token
        or token.startswith(".")
        or Path(token).suffix != ""
    )
