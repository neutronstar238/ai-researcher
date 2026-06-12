import json
from pathlib import Path

from autoresearch.reports import (
    ReproducibilityArtifactInput,
    ReproducibilityArtifactRole,
    create_reproducibility_package,
    validate_reproducibility_package,
)
from autoresearch.schemas import ValidationStatus, file_hash


def test_create_reproducibility_package_manifest_hashes_included_artifacts(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "run"
    source_dir.mkdir()
    files = {
        "run.py": "print('ok')\n",
        "config.yaml": "seed: 7\n",
        "metrics.json": '{"accuracy": 0.91}\n',
        "report.md": "# Report\n",
        "evidence-map.json": '{"edges": []}\n',
        "validation-report.json": '{"status": "passed"}\n',
        ".env": "API_KEY=secret\n",
        "raw.csv": "x" * 32,
    }
    for name, content in files.items():
        (source_dir / name).write_text(content, encoding="utf-8")

    package = create_reproducibility_package(
        package_dir=tmp_path / "package",
        artifacts=[
            ReproducibilityArtifactInput(
                source_dir / "run.py",
                ReproducibilityArtifactRole.CODE,
            ),
            ReproducibilityArtifactInput(
                source_dir / "config.yaml",
                ReproducibilityArtifactRole.CONFIG,
            ),
            ReproducibilityArtifactInput(
                source_dir / "metrics.json",
                ReproducibilityArtifactRole.METRICS,
            ),
            ReproducibilityArtifactInput(
                source_dir / "report.md",
                ReproducibilityArtifactRole.REPORT,
            ),
            ReproducibilityArtifactInput(
                source_dir / "evidence-map.json",
                ReproducibilityArtifactRole.EVIDENCE_MAP,
            ),
            ReproducibilityArtifactInput(
                source_dir / "validation-report.json",
                ReproducibilityArtifactRole.VALIDATION,
            ),
            ReproducibilityArtifactInput(
                source_dir / ".env",
                ReproducibilityArtifactRole.CONFIG,
            ),
            ReproducibilityArtifactInput(
                source_dir / "raw.csv",
                ReproducibilityArtifactRole.RAW_DATA,
            ),
        ],
        project_id="project-001",
        run_id="run-001",
        run_commands=["poetry run airesearcher run-demo"],
        validation_status=ValidationStatus.PASSED,
        environment_notes=["poetry.lock present"],
        max_raw_data_bytes=10,
    )

    manifest = json.loads(Path(package.manifest_path).read_text(encoding="utf-8"))
    included = manifest["artifacts"]
    included_paths = {artifact["package_path"] for artifact in included}

    assert included_paths == {
        "code/run.py",
        "config/config.yaml",
        "metrics/metrics.json",
        "report/report.md",
        "evidence/evidence-map.json",
        "validation/validation-report.json",
    }
    assert all(artifact["sha256"] for artifact in included)
    for artifact in included:
        packaged_path = Path(package.package_dir) / artifact["package_path"]
        assert artifact["sha256"] == file_hash(packaged_path)

    excluded_reasons = {
        artifact["source_path"]: artifact["reason"]
        for artifact in manifest["excluded_artifacts"]
    }
    assert excluded_reasons[(source_dir / ".env").as_posix()] == "secret-like filename"
    assert excluded_reasons[(source_dir / "raw.csv").as_posix()] == (
        "large raw data excluded by default"
    )
    assert manifest["validation_status"] == "passed"
    assert "poetry run airesearcher run-demo" in Path(
        package.environment_notes_path
    ).read_text(encoding="utf-8")


def test_validate_reproducibility_package_reports_missing_artifacts(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "run.py"
    source_path.write_text("print('ok')\n", encoding="utf-8")
    package = create_reproducibility_package(
        package_dir=tmp_path / "package",
        artifacts=[
            ReproducibilityArtifactInput(
                source_path,
                ReproducibilityArtifactRole.CODE,
            )
        ],
        project_id="project-001",
        run_id="run-001",
        run_commands=["python code/run.py"],
        validation_status=ValidationStatus.PASSED,
    )

    passing_report = validate_reproducibility_package(package.manifest_path)
    (Path(package.package_dir) / "code" / "run.py").unlink()
    failing_report = validate_reproducibility_package(package.manifest_path)

    assert passing_report.status is ValidationStatus.PASSED
    assert failing_report.status is ValidationStatus.FAILED
    assert failing_report.checked_artifacts == 1
    assert any(
        issue.check == "artifact_exists"
        and issue.package_path == "code/run.py"
        for issue in failing_report.issues
    )
