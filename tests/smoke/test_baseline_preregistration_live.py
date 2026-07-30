"""Opt-in live clean-room baseline replay and causal preregistration smoke."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.baseline_preregistration import (
    BASELINE_RUNNER_SOURCE_PATH,
    BASELINE_SEED,
    FROZEN_DEPENDENCY_VERSIONS,
    FROZEN_ESTIMATOR_LIST,
    FROZEN_MAX_TRIALS,
    FROZEN_VALIDATION_FRACTION,
    REQUIRED_BASELINE_SOURCE_KEYS,
    REQUIRED_DESIGN_SOURCE_KEYS,
    BaselineEnvironmentLock,
    BaselineGateStatus,
    BaselineReproductionReport,
    BaselineTaskReplay,
    CausalSearchPreregistration,
    CleanBaselineSpecification,
    PinnedDistribution,
    baseline_preregistration_json_schemas,
    load_baseline_preregistration,
    write_baseline_preregistration,
)
from autoresearch.research.objective_evaluators import (
    classification_balanced_accuracy,
    regression_r2,
)
from autoresearch.research.objective_task_panel import (
    OpenObjectiveTaskPanelReport,
    OpenObjectiveTaskUnit,
    load_open_objective_task_panel,
)
from autoresearch.research.objective_task_registry import (
    ObjectiveTaskFamily,
    PanelPartition,
)

LIVE_ENV = "AUTORESEARCH_BASELINE_PREREGISTRATION_LIVE"
OUTPUT_ENV = "AUTORESEARCH_BASELINE_PREREGISTRATION_OUTPUT"
PANEL_PATH_ENV = "AUTORESEARCH_OBJECTIVE_TASK_PANEL_PATH"
EXPECTED_PANEL_HASH = "ab4435f059676bcfd11387495947527455734eddf239f77b0e92a1c434e8a3ac"
PYPI_JSON_TEMPLATE = "https://pypi.org/pypi/{name}/{version}/json"
BASELINE_SOURCE_URLS = {
    "flaml-paper": (
        "https://proceedings.mlsys.org/paper_files/paper/2021/hash/"
        "1ccc3bfa05cb37b917068778f3c4523a-Abstract.html"
    ),
    "flaml-license": ("https://raw.githubusercontent.com/microsoft/FLAML/v2.6.0/LICENSE"),
}
DESIGN_SOURCE_URLS = {
    "ai-scientist-nature": ("https://www.nature.com/articles/s41586-026-10265-5"),
    "paperbench": "https://proceedings.mlr.press/v267/starace25a.html",
    "ml-resource-benchmark": "https://arxiv.org/abs/2410.07095",
    "ml-agent-search": "https://arxiv.org/abs/2507.02554",
    "mlrc-bench": "https://arxiv.org/abs/2504.09702",
    "mars": "https://arxiv.org/abs/2602.02660",
    "flaml": BASELINE_SOURCE_URLS["flaml-paper"],
}
SOURCE_MARKERS = {
    "ai-scientist-nature": "Towards end-to-end automation of AI research",
    "paperbench": "PaperBench",
    "ml-resource-benchmark": "MLE-bench",
    "ml-agent-search": "AI Research Agents for Machine Learning",
    "mlrc-bench": "MLRC-Bench",
    "mars": "Modular Agent with Reflective Search",
    "flaml": "FLAML",
}
PACKAGE_LICENSES = {
    "flaml": "MIT",
    "joblib": "BSD-3-Clause",
    "lightgbm": "MIT",
    "narwhals": "MIT",
    "numpy": "BSD-3-Clause",
    "pandas": "BSD-3-Clause",
    "python-dateutil": "Apache-2.0 OR BSD-3-Clause",
    "pytz": "MIT",
    "scikit-learn": "BSD-3-Clause",
    "scipy": "BSD-3-Clause",
    "six": "MIT",
    "threadpoolctl": "BSD-3-Clause",
    "tzdata": "Apache-2.0",
    "xgboost": "Apache-2.0",
}
DISALLOWED_RUNNER_IMPORTS = {
    "aiohttp",
    "http",
    "requests",
    "socket",
    "urllib",
}

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to build two verified clean environments, replay "
        "the strong baseline on all seven development tasks, and freeze the "
        "result-free causal preregistration"
    ),
)


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=6,
        connect=6,
        read=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "AutoResearch/1.0 task-263.4.2-clean-baseline",
            "Connection": "close",
        }
    )
    return session


def _bounded_get(
    session: requests.Session,
    url: str,
    *,
    maximum_bytes: int,
    timeout: int = 120,
) -> bytes:
    response = session.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    content = bytearray()
    for chunk in response.iter_content(chunk_size=65_536):
        if not chunk:
            continue
        content.extend(chunk)
        if len(content) > maximum_bytes:
            response.close()
            raise AssertionError(f"source exceeded {maximum_bytes} bytes: {url}")
    response.close()
    return bytes(content)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _fetch_source_snapshots(
    session: requests.Session,
    source_dir: Path,
) -> tuple[dict[str, str], dict[str, str], dict[str, bytes]]:
    raw_sources: dict[str, bytes] = {}
    for source_id, url in {
        **BASELINE_SOURCE_URLS,
        **DESIGN_SOURCE_URLS,
    }.items():
        if source_id in raw_sources:
            continue
        raw = _bounded_get(session, url, maximum_bytes=5_000_000)
        raw_sources[source_id] = raw
        _write_bytes(source_dir / f"{source_id}.source", raw)
    for source_id, marker in SOURCE_MARKERS.items():
        assert (
            marker.casefold() in raw_sources[source_id].decode("utf-8", errors="replace").casefold()
        )
    assert (
        "mit license" in raw_sources["flaml-license"].decode("utf-8", errors="replace").casefold()
    )
    design_hashes = {
        source_id: _sha256_bytes(raw_sources[source_id])
        for source_id in REQUIRED_DESIGN_SOURCE_KEYS
    }
    baseline_hashes = {
        "flaml-paper": _sha256_bytes(raw_sources["flaml-paper"]),
        "flaml-license": _sha256_bytes(raw_sources["flaml-license"]),
    }
    return baseline_hashes, design_hashes, raw_sources


def _pypi_snapshots(
    session: requests.Session,
    source_dir: Path,
) -> tuple[dict[str, bytes], dict[str, dict[str, dict[str, Any]]]]:
    raw_by_name: dict[str, bytes] = {}
    files_by_name: dict[str, dict[str, dict[str, Any]]] = {}
    for name, version in FROZEN_DEPENDENCY_VERSIONS.items():
        raw = _bounded_get(
            session,
            PYPI_JSON_TEMPLATE.format(name=name, version=version),
            maximum_bytes=5_000_000,
        )
        payload = json.loads(raw)
        assert payload["info"]["version"] == version
        raw_by_name[name] = raw
        files_by_name[name] = {item["filename"]: item for item in payload["urls"]}
        _write_bytes(source_dir / f"pypi-{name}-{version}.json", raw)
    return raw_by_name, files_by_name


def _download_verified_wheels(
    output_dir: Path,
    raw_pypi: dict[str, bytes],
    pypi_files: dict[str, dict[str, dict[str, Any]]],
) -> list[PinnedDistribution]:
    wheelhouse = output_dir / "wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=False)
    requirements = [f"{name}=={version}" for name, version in FROZEN_DEPENDENCY_VERSIONS.items()]
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--no-deps",
        "--dest",
        str(wheelhouse),
        *requirements,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    (output_dir / "pip-download.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "pip-download.stderr.log").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr

    wheel_paths = sorted(wheelhouse.glob("*.whl"))
    assert len(wheel_paths) == len(FROZEN_DEPENDENCY_VERSIONS)
    distributions: list[PinnedDistribution] = []
    matched_names: set[str] = set()
    for wheel_path in wheel_paths:
        matches = [name for name, files in pypi_files.items() if wheel_path.name in files]
        assert len(matches) == 1, wheel_path.name
        name = matches[0]
        official = pypi_files[name][wheel_path.name]
        wheel_hash = _sha256_file(wheel_path)
        assert wheel_hash == official["digests"]["sha256"]
        matched_names.add(name)
        distributions.append(
            PinnedDistribution.create(
                name=name,
                version=FROZEN_DEPENDENCY_VERSIONS[name],
                filename=wheel_path.name,
                wheel_sha256=wheel_hash,
                pypi_json_sha256=_sha256_bytes(raw_pypi[name]),
                license_id=PACKAGE_LICENSES[name],
            )
        )
    assert matched_names == set(FROZEN_DEPENDENCY_VERSIONS)
    return distributions


def _venv_python(venv_root: Path) -> Path:
    return venv_root / "Scripts/python.exe" if os.name == "nt" else venv_root / "bin/python"


def _create_verified_venv(
    *,
    output_dir: Path,
    name: str,
    wheel_paths: list[Path],
) -> Path:
    venv_root = output_dir / name
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    python_path = _venv_python(venv_root)
    install = subprocess.run(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
            "--no-compile",
            *[str(path) for path in wheel_paths],
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    (output_dir / f"{name}-install.stdout.log").write_text(install.stdout, encoding="utf-8")
    (output_dir / f"{name}-install.stderr.log").write_text(install.stderr, encoding="utf-8")
    assert install.returncode == 0, install.stderr
    script = (
        "import importlib.metadata,json;"
        f"names={list(FROZEN_DEPENDENCY_VERSIONS)!r};"
        "print(json.dumps({name:importlib.metadata.version(name) "
        "for name in names},sort_keys=True))"
    )
    versions = subprocess.run(
        [str(python_path), "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert json.loads(versions.stdout) == FROZEN_DEPENDENCY_VERSIONS
    return python_path


_ATTRIBUTE_PATTERN = re.compile(
    r"""^@attribute\s+(?:'([^']+)'|"([^"]+)"|([^\s]+))\s+(.+)$""",
    flags=re.IGNORECASE,
)


def _decode_arff(content: bytes) -> tuple[list[tuple[str, str]], list[list[str]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    attributes: list[tuple[str, str]] = []
    data_lines: list[str] = []
    in_data = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%"):
            continue
        if not in_data:
            match = _ATTRIBUTE_PATTERN.match(line)
            if match:
                name = next(value for value in match.groups()[:3] if value is not None)
                attributes.append((name, match.group(4).strip()))
            if line.casefold() == "@data":
                in_data = True
            continue
        if line.startswith("{"):
            raise AssertionError("frozen development panel unexpectedly uses sparse ARFF")
        data_lines.append(line)
    rows = [
        [value.strip() for value in row]
        for row in csv.reader(io.StringIO("\n".join(data_lines)))
        if row
    ]
    assert attributes and rows
    assert all(len(row) == len(attributes) for row in rows)
    return attributes, rows


def _split_rows(content: bytes) -> tuple[list[int], list[int]]:
    attributes, rows = _decode_arff(content)
    index = {name.casefold(): position for position, (name, _) in enumerate(attributes)}
    assert set(index) >= {"type", "rowid", "repeat", "fold"}
    train: list[int] = []
    test: list[int] = []
    for row in rows:
        if int(float(row[index["repeat"]])) != 0:
            continue
        if int(float(row[index["fold"]])) != 0:
            continue
        row_id = int(float(row[index["rowid"]]))
        split_type = row[index["type"]].casefold()
        if split_type == "train":
            train.append(row_id)
        elif split_type == "test":
            test.append(row_id)
        else:
            raise AssertionError(f"unknown split type: {split_type}")
    assert train and test
    assert not set(train) & set(test)
    return sorted(train), sorted(test)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _prepare_task_bundle(
    *,
    unit: OpenObjectiveTaskUnit,
    data_bytes: bytes,
    split_bytes: bytes,
    output_dir: Path,
) -> tuple[Path, list[int], list[str | float], str]:
    attributes, rows = _decode_arff(data_bytes)
    attribute_names = [name for name, _ in attributes]
    target_index = next(
        index
        for index, name in enumerate(attribute_names)
        if name.casefold() == unit.target_feature.casefold()
    )
    feature_indexes = [index for index in range(len(attributes)) if index != target_index]
    feature_columns = [f"x_{position:04d}" for position in range(len(feature_indexes))]
    numeric_columns = [
        feature_columns[position]
        for position, source_index in enumerate(feature_indexes)
        if attributes[source_index][1].casefold() in {"numeric", "real", "integer"}
    ]
    categorical_columns = [column for column in feature_columns if column not in numeric_columns]
    train_ids, test_ids = _split_rows(split_bytes)
    assert max(train_ids + test_ids) < len(rows)

    opaque_id = "opaque-" + hashlib.sha256(unit.unit_id.encode()).hexdigest()[:16]
    bundle_dir = output_dir / opaque_id
    bundle_dir.mkdir(parents=True, exist_ok=False)
    train_path = bundle_dir / "train.csv"
    test_path = bundle_dir / "test.csv"
    train_rows = [
        [rows[row_id][index] for index in feature_indexes] + [rows[row_id][target_index]]
        for row_id in train_ids
    ]
    test_rows = [
        [str(row_id)] + [rows[row_id][index] for index in feature_indexes] for row_id in test_ids
    ]
    _write_csv(
        train_path,
        feature_columns + ["target"],
        train_rows,
    )
    _write_csv(
        test_path,
        ["row_id"] + feature_columns,
        test_rows,
    )
    manifest = {
        "schema_version": "clean-baseline-input-v1",
        "unit_id": opaque_id,
        "family": unit.family.value,
        "feature_columns": feature_columns,
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "target_column": "target",
        "train_file": "train.csv",
        "test_file": "test.csv",
        "train_sha256": _sha256_file(train_path),
        "test_sha256": _sha256_file(test_path),
        "seed": BASELINE_SEED,
        "max_trials": FROZEN_MAX_TRIALS,
        "validation_fraction": FROZEN_VALIDATION_FRACTION,
        "estimator_list": FROZEN_ESTIMATOR_LIST,
        "n_jobs": 1,
        "network_allowed": False,
    }
    manifest_path = bundle_dir / "input-manifest.json"
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    expected: list[str | float]
    if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        expected = [rows[row_id][target_index] for row_id in test_ids]
    else:
        expected = [float(rows[row_id][target_index]) for row_id in test_ids]
    return (
        manifest_path,
        test_ids,
        expected,
        canonical_sha256(manifest),
    )


def _runner_static_network_audit(runner_path: Path) -> bool:
    tree = ast.parse(runner_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", maxsplit=1)[0])
    source = runner_path.read_text(encoding="utf-8").casefold()
    return (
        not imported & DISALLOWED_RUNNER_IMPORTS
        and "http://" not in source
        and "https://" not in source
    )


def _copy_bundle(manifest_path: Path, workspace: Path, runner_path: Path) -> Path:
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=False)
    for source in manifest_path.parent.iterdir():
        if source.is_file():
            shutil.copy2(source, input_dir / source.name)
    shutil.copy2(runner_path, workspace / "runner.py")
    return input_dir / manifest_path.name


def _start_runner(
    *,
    python_path: Path,
    workspace: Path,
    manifest_path: Path,
) -> tuple[subprocess.Popen[str], Any, Any]:
    stdout_handle = (workspace / "runner.stdout.log").open("w", encoding="utf-8")
    stderr_handle = (workspace / "runner.stderr.log").open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
        }
    )
    process = subprocess.Popen(
        [
            str(python_path),
            str(workspace / "runner.py"),
            "--manifest",
            str(manifest_path),
            "--output",
            str(workspace / "result"),
        ],
        cwd=workspace,
        env=environment,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    return process, stdout_handle, stderr_handle


def _finish_runner(
    process: subprocess.Popen[str],
    stdout_handle: Any,
    stderr_handle: Any,
    *,
    workspace: Path,
) -> dict[str, Any]:
    try:
        return_code = process.wait(timeout=720)
    finally:
        stdout_handle.close()
        stderr_handle.close()
    if return_code != 0:
        stderr = (workspace / "runner.stderr.log").read_text(encoding="utf-8")
        raise AssertionError(f"clean runner failed with {return_code}: {stderr[-4000:]}")
    result = json.loads((workspace / "result/runner-result.json").read_text(encoding="utf-8"))
    assert int(result["process_id"]) > 0
    assert result["network_allowed"] is False
    return result


def _prediction_rows(workspace: Path) -> list[dict[str, Any]]:
    rows = json.loads((workspace / "result/predictions.json").read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def _score_predictions(
    *,
    unit: OpenObjectiveTaskUnit,
    expected_row_ids: list[int],
    expected: list[str | float],
    prediction_rows: list[dict[str, Any]],
) -> float:
    assert [row["row_id"] for row in prediction_rows] == expected_row_ids
    predicted = [row["prediction"] for row in prediction_rows]
    if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        return classification_balanced_accuracy(
            [str(value) for value in expected],
            [str(value) for value in predicted],
        )
    return regression_r2(
        [float(value) for value in expected],
        [float(value) for value in predicted],
    )


def _artifact_hashes(
    output_dir: Path,
    unit_id: str,
    workspace_a: Path,
    workspace_b: Path,
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for label, workspace in (("a", workspace_a), ("b", workspace_b)):
        for relative in (
            "input/input-manifest.json",
            "input/train.csv",
            "input/test.csv",
            "result/flaml-trials.log",
            "result/predictions.json",
            "result/runner-result.json",
            "runner.py",
            "runner.stderr.log",
            "runner.stdout.log",
        ):
            path = workspace / relative
            key = path.relative_to(output_dir).as_posix()
            artifacts[f"{unit_id}/{label}/{key}"] = _sha256_file(path)
    return dict(sorted(artifacts.items()))


def test_live_clean_baseline_and_causal_preregistration() -> None:
    root = Path(__file__).resolve().parents[2]
    output_dir = Path(
        os.getenv(
            OUTPUT_ENV,
            str(root / "runs/manual-live/task26342-clean-baseline-preregistration-v1"),
        )
    ).resolve()
    assert (
        not output_dir.exists()
    ), "live output already exists; choose a new content-addressed output path"
    output_dir.mkdir(parents=True)
    source_dir = output_dir / "source-snapshots"
    source_dir.mkdir()

    panel_path = Path(
        os.getenv(
            PANEL_PATH_ENV,
            str(
                root / "runs/manual-live/task26341-open-objective-panel-v1/"
                "open-objective-task-panel.json"
            ),
        )
    ).resolve()
    panel: OpenObjectiveTaskPanelReport = load_open_objective_task_panel(panel_path)
    assert panel.report_hash == EXPECTED_PANEL_HASH
    assert panel.confirmatory_payloads_downloaded is False
    assert panel.study_outcomes_observed is False
    assert panel.existing_public_runs_queried is False

    session = _session()
    try:
        baseline_hashes, design_hashes, _ = _fetch_source_snapshots(
            session,
            source_dir,
        )
        raw_pypi, pypi_files = _pypi_snapshots(session, source_dir)
        baseline_hashes["flaml-pypi"] = _sha256_bytes(raw_pypi["flaml"])
        baseline_hashes["scikit-learn-pypi"] = _sha256_bytes(raw_pypi["scikit-learn"])
        assert set(baseline_hashes) == REQUIRED_BASELINE_SOURCE_KEYS
        assert set(design_hashes) == REQUIRED_DESIGN_SOURCE_KEYS

        distributions = _download_verified_wheels(
            output_dir,
            raw_pypi,
            pypi_files,
        )
        environment = BaselineEnvironmentLock.create(
            python_version=sys.version.split()[0],
            platform_tag=sysconfig.get_platform().replace("-", "_").replace(".", "_"),
            base_interpreter_sha256=_sha256_file(Path(sys.executable)),
            distributions=distributions,
        )
        wheel_paths = sorted((output_dir / "wheelhouse").glob("*.whl"))
        python_a = _create_verified_venv(
            output_dir=output_dir,
            name="clean-venv-a",
            wheel_paths=wheel_paths,
        )
        python_b = _create_verified_venv(
            output_dir=output_dir,
            name="clean-venv-b",
            wheel_paths=wheel_paths,
        )

        runner_path = root / BASELINE_RUNNER_SOURCE_PATH
        runner_hash = _sha256_file(runner_path)
        assert _runner_static_network_audit(runner_path)
        specification = CleanBaselineSpecification.create_from_panel(
            panel,
            baseline_source_snapshot_hashes=baseline_hashes,
            runner_source_hash=runner_hash,
            environment_hash=environment.environment_hash,
        )

        development_units = [
            unit for unit in panel.task_units if unit.partition is PanelPartition.DEVELOPMENT
        ]
        assert len(development_units) == 7
        confirmatory_urls = {
            url
            for unit in panel.task_units
            if unit.partition is PanelPartition.CONFIRMATORY
            for url in (unit.data_url, unit.split_url)
        }
        requested_urls: set[str] = set()
        prepared: dict[
            str,
            tuple[Path, list[int], list[str | float], str, str, str],
        ] = {}
        input_root = output_dir / "prepared-development-inputs"
        input_root.mkdir()
        for unit in development_units:
            data_bytes = _bounded_get(
                session,
                unit.data_url,
                maximum_bytes=64 * 1024 * 1024,
                timeout=240,
            )
            requested_urls.add(unit.data_url)
            split_bytes = _bounded_get(
                session,
                unit.split_url,
                maximum_bytes=16 * 1024 * 1024,
                timeout=240,
            )
            requested_urls.add(unit.split_url)
            assert hashlib.md5(data_bytes).hexdigest() == unit.data_md5
            manifest_path, row_ids, expected, bundle_hash = _prepare_task_bundle(
                unit=unit,
                data_bytes=data_bytes,
                split_bytes=split_bytes,
                output_dir=input_root,
            )
            prepared[unit.unit_id] = (
                manifest_path,
                row_ids,
                expected,
                bundle_hash,
                _sha256_bytes(data_bytes),
                _sha256_bytes(split_bytes),
            )
        assert not requested_urls & confirmatory_urls
    finally:
        session.close()

    command_template_hash = canonical_sha256(
        [
            "{clean-python}",
            "{runner}",
            "--manifest",
            "{input-manifest}",
            "--output",
            "{result-dir}",
        ]
    )
    task_replays: list[BaselineTaskReplay] = []
    for unit in development_units:
        (
            source_manifest,
            row_ids,
            expected,
            bundle_hash,
            data_hash,
            split_hash,
        ) = prepared[unit.unit_id]
        workspace_a = output_dir / "clean-run-a" / unit.unit_id
        workspace_b = output_dir / "clean-run-b" / unit.unit_id
        workspace_a.mkdir(parents=True)
        workspace_b.mkdir(parents=True)
        manifest_a = _copy_bundle(source_manifest, workspace_a, runner_path)
        manifest_b = _copy_bundle(source_manifest, workspace_b, runner_path)
        process_a, stdout_a, stderr_a = _start_runner(
            python_path=python_a,
            workspace=workspace_a,
            manifest_path=manifest_a,
        )
        process_b, stdout_b, stderr_b = _start_runner(
            python_path=python_b,
            workspace=workspace_b,
            manifest_path=manifest_b,
        )
        result_a = _finish_runner(
            process_a,
            stdout_a,
            stderr_a,
            workspace=workspace_a,
        )
        result_b = _finish_runner(
            process_b,
            stdout_b,
            stderr_b,
            workspace=workspace_b,
        )
        predictions_a = _prediction_rows(workspace_a)
        predictions_b = _prediction_rows(workspace_b)
        score_a = _score_predictions(
            unit=unit,
            expected_row_ids=row_ids,
            expected=expected,
            prediction_rows=predictions_a,
        )
        score_b = _score_predictions(
            unit=unit,
            expected_row_ids=row_ids,
            expected=expected,
            prediction_rows=predictions_b,
        )
        assert result_a["versions"] == result_b["versions"]
        assert result_a["runner_sha256"] == runner_hash
        assert result_b["runner_sha256"] == runner_hash
        task_replays.append(
            BaselineTaskReplay.create(
                replay_id=f"task-263.4.2-{unit.unit_id}-replay",
                unit_id=unit.unit_id,
                family=unit.family,
                metric_id=unit.objective_metric,
                data_sha256=data_hash,
                split_sha256=split_hash,
                input_bundle_hash=bundle_hash,
                runner_source_hash=runner_hash,
                environment_hash=environment.environment_hash,
                command_template_hash=command_template_hash,
                run_a_id=f"clean-a-{unit.unit_id}",
                run_b_id=f"clean-b-{unit.unit_id}",
                run_a_workspace_hash=canonical_sha256(
                    {
                        "run_id": f"clean-a-{unit.unit_id}",
                        "root": str(workspace_a),
                    }
                ),
                run_b_workspace_hash=canonical_sha256(
                    {
                        "run_id": f"clean-b-{unit.unit_id}",
                        "root": str(workspace_b),
                    }
                ),
                run_a_process_id=int(result_a["process_id"]),
                run_b_process_id=int(result_b["process_id"]),
                run_a_prediction_hash=result_a["prediction_sha256"],
                run_b_prediction_hash=result_b["prediction_sha256"],
                prediction_count=int(result_a["prediction_count"]),
                run_a_score=score_a,
                run_b_score=score_b,
                run_a_trial_count=int(result_a["trial_count"]),
                run_b_trial_count=int(result_b["trial_count"]),
                run_a_seconds=float(result_a["elapsed_seconds"]),
                run_b_seconds=float(result_b["elapsed_seconds"]),
                artifact_hashes=_artifact_hashes(
                    output_dir,
                    unit.unit_id,
                    workspace_a,
                    workspace_b,
                ),
            )
        )

    report = BaselineReproductionReport.create(
        report_id="task-263.4.2-clean-baseline-live",
        specification=specification,
        environment=environment,
        task_replays=task_replays,
        install_lock_verified=True,
        runner_static_network_audit_passed=True,
        workspace_roots_disjoint=True,
    )
    assert report.status is BaselineGateStatus.BASELINE_REPRODUCED
    assert len(report.task_replays) == 7
    assert all(item.passed for item in report.task_replays)
    assert all(item.prediction_replay_exact for item in report.task_replays)
    assert report.confirmatory_payloads_downloaded is False
    assert report.public_benchmark_runs_queried is False

    preregistration = CausalSearchPreregistration.create_from_reproduction(
        preregistration_id="task-263.4.2-causal-preregistration-live",
        panel=panel,
        reproduction=report,
        design_source_snapshot_hashes=design_hashes,
    )
    assert preregistration.status is (BaselineGateStatus.READY_FOR_DEVELOPMENT_SEARCH)
    assert len(preregistration.task_thresholds) == 60
    assert len(preregistration.randomization_assignments) == 67 * 3 * 4
    assert preregistration.result_record_count == 0
    assert preregistration.confirmatory_payloads_downloaded is False
    assert preregistration.development_search_started is False
    assert preregistration.external_submission_authorized is False

    manifest = write_baseline_preregistration(
        output_dir,
        report,
        preregistration,
    )
    loaded_report, loaded_preregistration, loaded_manifest = load_baseline_preregistration(
        output_dir
    )
    assert loaded_report.report_hash == report.report_hash
    assert loaded_preregistration.preregistration_hash == preregistration.preregistration_hash
    assert loaded_manifest.manifest_hash == manifest.manifest_hash
    schema_bundle_hash = canonical_sha256(baseline_preregistration_json_schemas())
    (output_dir / "live-summary.json").write_bytes(
        _canonical_json_bytes(
            {
                "schema_version": "task-263.4.2-live-summary-v1",
                "panel_report_hash": panel.report_hash,
                "baseline_report_hash": report.report_hash,
                "preregistration_hash": preregistration.preregistration_hash,
                "manifest_hash": manifest.manifest_hash,
                "environment_hash": environment.environment_hash,
                "dependency_lock_hash": environment.dependency_lock_hash,
                "runner_source_hash": runner_hash,
                "randomization_schedule_hash": (preregistration.randomization_schedule_hash),
                "schema_bundle_hash": schema_bundle_hash,
                "development_replay_count": len(report.task_replays),
                "confirmatory_task_count": len(preregistration.confirmatory_unit_ids),
                "confirmatory_payloads_downloaded": False,
                "result_record_count": 0,
                "public_release_authorized": False,
                "external_submission_authorized": False,
            }
        )
    )
