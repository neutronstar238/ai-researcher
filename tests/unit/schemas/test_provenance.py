from pathlib import Path

from autoresearch.config import SystemConfig
from autoresearch.schemas import (
    ExecutionRun,
    artifact_uri,
    config_hash,
    data_hash,
    file_hash,
    generate_run_id,
)


def test_generate_run_id_creates_unique_prefixed_ids() -> None:
    first = generate_run_id()
    second = generate_run_id()

    assert first.startswith("run_")
    assert second.startswith("run_")
    assert first != second


def test_config_hash_is_stable_for_equivalent_mappings() -> None:
    left = {"b": 2, "a": {"x": 1}}
    right = {"a": {"x": 1}, "b": 2}

    assert config_hash(left) == config_hash(right)


def test_config_hash_accepts_pydantic_models() -> None:
    assert config_hash(SystemConfig()) == config_hash(SystemConfig())


def test_data_hash_and_file_hash_are_stable(tmp_path: Path) -> None:
    content = b"dataset bytes"
    path = tmp_path / "data.bin"
    path.write_bytes(content)

    assert data_hash(content) == file_hash(path)
    assert data_hash("dataset bytes") == file_hash(path)


def test_artifact_uri_normalizes_run_artifact_paths() -> None:
    assert artifact_uri("run_1", "/metrics.json") == "runs/run_1/artifacts/metrics.json"


def test_execution_run_stores_provenance_fields() -> None:
    run_id = generate_run_id()
    run = ExecutionRun(
        id=run_id,
        project_id="project_1",
        task_id="task_1",
        commit_sha="abc123",
        config_hash=config_hash({"lr": 0.1}),
        data_hash=data_hash("dataset"),
        metrics_path="metrics.json",
        artifact_uri=artifact_uri(run_id, "metrics.json"),
        cost_json={"tokens": 10},
        exit_code=0,
        stdout="ok",
        stderr="",
        limit_violations=[],
    )

    assert run.commit_sha == "abc123"
    assert run.config_hash
    assert run.data_hash
    assert run.artifact_uri == f"runs/{run_id}/artifacts/metrics.json"
    assert run.cost_json == {"tokens": 10}
    assert run.exit_code == 0
    assert run.stdout == "ok"
    assert run.limit_violations == []
