"""Opt-in official-source smoke for Task 263.4.1."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research.objective_evaluators import (
    classification_balanced_accuracy,
    regression_r2,
)
from autoresearch.research.objective_task_panel import (
    ObjectiveFamilyProbe,
    OpenObjectiveTaskPanelReport,
    OpenObjectiveTaskUnit,
    OpenTaskPanelStatus,
    panel_power_scenarios,
    write_open_objective_task_panel,
)
from autoresearch.research.objective_task_registry import (
    OPENML_TERMS_URL,
    UCI_LICENSE_EVIDENCE_URL,
    FrozenSourceSpec,
    ObjectiveTaskFamily,
    PanelPartition,
    frozen_sources,
)

LIVE_ENV = "AUTORESEARCH_OBJECTIVE_TASK_PANEL_LIVE"
OUTPUT_ENV = "AUTORESEARCH_OBJECTIVE_TASK_PANEL_OUTPUT"
DIAGNOSIS_HASH = "7c4d06eb82eabb250cf1b509242480bf27f079f65eaec6fbe564593c54b4aa3c"
OPENML_API = "https://www.openml.org/api/v1/json"
BENCHMARK_DOCS_URL = "https://docs.openml.org/benchmark/"
EXPECTED_SUITE_COUNTS = {99: 72, 353: 35}

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to audit the frozen OpenML task panel, download "
        "one development task per family, and replay objective evaluators"
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
            "User-Agent": "AutoResearch/1.0 task-263.4.1-open-panel-audit",
            "Connection": "close",
        }
    )
    return session


def _bounded_get(
    session: requests.Session,
    url: str,
    *,
    maximum_bytes: int,
    timeout: int = 90,
) -> tuple[bytes, str]:
    response = session.get(
        url,
        timeout=timeout,
        stream=True,
        allow_redirects=True,
    )
    response.raise_for_status()
    content = bytearray()
    for chunk in response.iter_content(chunk_size=65_536):
        if not chunk:
            continue
        content.extend(chunk)
        if len(content) > maximum_bytes:
            response.close()
            raise AssertionError(f"bounded source exceeded {maximum_bytes} bytes")
    resolved_url = str(response.url)
    response.close()
    return bytes(content), resolved_url


def _json_bytes(
    session: requests.Session,
    url: str,
    *,
    maximum_bytes: int,
) -> tuple[Any, bytes]:
    content, _ = _bounded_get(session, url, maximum_bytes=maximum_bytes)
    return json.loads(content), content


def _quality_map(task: dict[str, Any]) -> dict[str, str]:
    return {str(item["name"]): str(item["value"]) for item in task.get("quality", [])}


def _input_map(task: dict[str, Any]) -> dict[str, str]:
    return {str(item["name"]): str(item["value"]) for item in task.get("input", [])}


def _source_reference_found(
    source: FrozenSourceSpec,
    description: dict[str, Any],
) -> bool:
    fields = [
        str(description.get("original_data_url") or ""),
        str(description.get("description") or ""),
        str(description.get("citation") or ""),
    ]
    joined = "\n".join(fields).lower()
    if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        return "archive.ics.uci.edu" in joined
    return bool(str(description.get("original_data_url") or "").strip())


def _fetch_data_detail(
    source: FrozenSourceSpec,
) -> tuple[tuple[ObjectiveTaskFamily, int], dict[str, Any], bytes]:
    session = _session()
    try:
        payload, raw = _json_bytes(
            session,
            f"{OPENML_API}/data/{source.data_id}",
            maximum_bytes=1_000_000,
        )
    finally:
        session.close()
    description = payload["data_set_description"]
    assert int(description["id"]) == source.data_id
    assert description["name"] == source.name
    assert description["status"] == "active"
    assert description["md5_checksum"] == source.data_md5
    assert int(description["file_id"]) == source.file_id
    assert description["url"] == (
        f"https://openml.org/data/v1/download/{source.file_id}/" f"{source.name}.arff"
    )
    if source.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        assert str(description["licence"]).lower() == "public"
    else:
        assert description["licence"] == source.declared_license
    assert _source_reference_found(source, description)
    return (source.family, source.task_id), description, raw


_ATTRIBUTE_PATTERN = re.compile(
    r"""^@attribute\s+(?:'([^']+)'|"([^"]+)"|([^\s]+))""",
    flags=re.IGNORECASE,
)


def _decode_arff(content: bytes) -> tuple[list[str], list[list[str]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    attributes: list[str] = []
    data_lines: list[str] = []
    in_data = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%"):
            continue
        if not in_data:
            match = _ATTRIBUTE_PATTERN.match(line)
            if match:
                attributes.append(next(value for value in match.groups() if value))
            if line.lower() == "@data":
                in_data = True
            continue
        data_lines.append(line)
    assert attributes
    rows = [
        [value.strip() for value in row]
        for row in csv.reader(io.StringIO("\n".join(data_lines)))
        if row
    ]
    assert rows
    assert all(len(row) == len(attributes) for row in rows)
    return attributes, rows


def _split_is_structured(content: bytes) -> bool:
    text = content.decode("utf-8-sig", errors="replace").lower()
    if "@data" not in text or "@attribute" not in text:
        return False
    if "rowid" not in text and "row_id" not in text:
        return False
    _, data = text.split("@data", maxsplit=1)
    return any(line.strip() and not line.lstrip().startswith("%") for line in data.splitlines())


def _family_probe(
    *,
    unit: OpenObjectiveTaskUnit,
    detail_raw: bytes,
    uci_license_bytes: bytes,
) -> ObjectiveFamilyProbe:
    assert unit.partition is PanelPartition.DEVELOPMENT
    session = _session()
    try:
        data_bytes, _ = _bounded_get(
            session,
            unit.data_url,
            maximum_bytes=64 * 1024 * 1024,
            timeout=180,
        )
        split_bytes, _ = _bounded_get(
            session,
            unit.split_url,
            maximum_bytes=16 * 1024 * 1024,
            timeout=180,
        )
    finally:
        session.close()

    started = time.perf_counter()
    attributes, rows = _decode_arff(data_bytes)
    target_index = next(
        index
        for index, attribute in enumerate(attributes)
        if attribute.lower() == unit.target_feature.lower()
    )
    if unit.family is ObjectiveTaskFamily.TABULAR_CLASSIFICATION:
        expected = [row[target_index] for row in rows]
        counts = {label: expected.count(label) for label in set(expected)}
        majority = max(sorted(counts), key=lambda label: counts[label])
        predicted = [majority] * len(expected)
        score = classification_balanced_accuracy(expected, predicted)
        replay = classification_balanced_accuracy(expected, predicted)
        license_bytes = uci_license_bytes
    else:
        expected_float = [float(row[target_index]) for row in rows]
        mean = sum(expected_float) / len(expected_float)
        predicted_float = [mean] * len(expected_float)
        score = regression_r2(expected_float, predicted_float)
        replay = regression_r2(expected_float, predicted_float)
        license_bytes = detail_raw
    elapsed = time.perf_counter() - started

    assert len(rows) == unit.number_instances
    assert math.isfinite(score)
    return ObjectiveFamilyProbe.create(
        probe_id=f"task-263.4.1-{unit.family.value}-probe",
        family=unit.family,
        representative_unit_id=unit.unit_id,
        data_sha256=hashlib.sha256(data_bytes).hexdigest(),
        data_bytes=len(data_bytes),
        split_sha256=hashlib.sha256(split_bytes).hexdigest(),
        split_bytes=len(split_bytes),
        license_evidence_sha256=hashlib.sha256(license_bytes).hexdigest(),
        evaluator_source_hash=unit.evaluator_source_hash,
        evaluator_score=score,
        evaluator_replay_score=replay,
        rows_evaluated=len(rows),
        compute_seconds=elapsed,
        data_md5_verified=hashlib.md5(data_bytes).hexdigest() == unit.data_md5,
        split_verified=_split_is_structured(split_bytes),
        license_verified=True,
        task_metadata_verified=True,
    )


def test_live_open_objective_task_panel() -> None:
    root = Path(__file__).resolve().parents[2]
    sources = frozen_sources()
    session = _session()
    try:
        benchmark_docs, _ = _bounded_get(
            session,
            BENCHMARK_DOCS_URL,
            maximum_bytes=1_500_000,
        )
        docs_text = benchmark_docs.decode("utf-8", errors="replace")
        assert "standardized train-test splits" in docs_text
        assert "downloaded programmatically" in docs_text

        terms_bytes, _ = _bounded_get(
            session,
            OPENML_TERMS_URL,
            maximum_bytes=1_000_000,
        )
        terms_text = terms_bytes.decode("utf-8", errors="replace")
        assert "non-exclusive license" in terms_text
        assert "research purposes" in terms_text

        uci_license_bytes, _ = _bounded_get(
            session,
            UCI_LICENSE_EVIDENCE_URL,
            maximum_bytes=1_000_000,
        )
        uci_text = uci_license_bytes.decode("utf-8", errors="replace")
        assert "Creative Commons Attribution 4.0 International" in uci_text
        assert "sharing and adaptation" in uci_text

        suite_hashes: dict[str, str] = {}
        for suite_id, benchmark_id in ((99, "openml-cc18"), (353, "openml-ctr23")):
            payload, _ = _json_bytes(
                session,
                f"{OPENML_API}/study/{suite_id}",
                maximum_bytes=500_000,
            )
            study = payload["study"]
            task_ids = [int(value) for value in study["tasks"]["task_id"]]
            data_ids = [int(value) for value in study["data"]["data_id"]]
            assert study["status"] == "active"
            assert len(task_ids) == EXPECTED_SUITE_COUNTS[suite_id]
            assert len(data_ids) == EXPECTED_SUITE_COUNTS[suite_id]
            assert len(set(task_ids)) == len(task_ids)
            assert len(set(data_ids)) == len(data_ids)
            selected = {source.task_id for source in sources if source.suite_id == suite_id}
            assert selected <= set(task_ids)
            suite_hashes[benchmark_id] = canonical_sha256(
                {
                    "id": study["id"],
                    "name": study["name"],
                    "status": study["status"],
                    "tasks": task_ids,
                    "data": data_ids,
                }
            )

        task_rows: dict[tuple[ObjectiveTaskFamily, int], dict[str, Any]] = {}
        for family in ObjectiveTaskFamily:
            ids = [source.task_id for source in sources if source.family is family]
            payload, _ = _json_bytes(
                session,
                f"{OPENML_API}/task/list/task_id/{','.join(map(str, ids))}",
                maximum_bytes=2_000_000,
            )
            rows = payload["tasks"]["task"]
            if isinstance(rows, dict):
                rows = [rows]
            assert {int(row["task_id"]) for row in rows} == set(ids)
            for row in rows:
                task_rows[(family, int(row["task_id"]))] = row
    finally:
        session.close()

    details: dict[
        tuple[ObjectiveTaskFamily, int],
        tuple[dict[str, Any], bytes],
    ] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch_data_detail, source) for source in sources]
        for future in as_completed(futures):
            key, description, raw = future.result()
            details[key] = (description, raw)
    assert len(details) == len(sources)

    evaluator_path = root / "src/autoresearch/research/objective_evaluators.py"
    evaluator_hash = hashlib.sha256(evaluator_path.read_bytes()).hexdigest()
    units: list[OpenObjectiveTaskUnit] = []
    for source in sources:
        task = task_rows[(source.family, source.task_id)]
        detail, _ = details[(source.family, source.task_id)]
        inputs = _input_map(task)
        qualities = _quality_map(task)
        assert int(task["did"]) == source.data_id
        assert task["name"] == source.name
        assert task["status"] == "active"
        assert task["task_type"] in {
            "Supervised Classification",
            "Supervised Regression",
        }
        assert int(inputs["source_data"]) == source.data_id
        metadata_hash = canonical_sha256(
            {
                "task_id": int(task["task_id"]),
                "task_type": task["task_type"],
                "data_id": int(task["did"]),
                "target_feature": inputs["target_feature"],
                "estimation_procedure": inputs["estimation_procedure"],
                "number_instances": qualities["NumberOfInstances"],
                "number_features": qualities["NumberOfFeatures"],
                "data_md5": detail["md5_checksum"],
                "data_url": detail["url"],
                "declared_license": detail["licence"],
                "source_reference_found": _source_reference_found(source, detail),
            }
        )
        units.append(
            OpenObjectiveTaskUnit.create_from_source(
                source,
                target_feature=inputs["target_feature"],
                estimation_procedure_id=int(inputs["estimation_procedure"]),
                number_instances=int(float(qualities["NumberOfInstances"])),
                number_features=int(float(qualities["NumberOfFeatures"])),
                upstream_metadata_hash=metadata_hash,
                evaluator_source_hash=evaluator_hash,
                source_reference_found=_source_reference_found(source, detail),
                anonymous_data_available=bool(detail["url"]),
                fixed_split_available=True,
            )
        )
    assert all(unit.eligible_for_panel for unit in units)

    representatives = {
        family: min(
            (
                unit
                for unit in units
                if unit.family is family and unit.partition is PanelPartition.DEVELOPMENT
            ),
            key=lambda unit: unit.number_instances,
        )
        for family in ObjectiveTaskFamily
    }
    probes = [
        _family_probe(
            unit=representative,
            detail_raw=details[(representative.family, representative.upstream_task_id)][1],
            uci_license_bytes=uci_license_bytes,
        )
        for representative in representatives.values()
    ]
    assert all(probe.passed for probe in probes)

    license_hash = hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest()
    report = OpenObjectiveTaskPanelReport.create(
        report_id="task-263.4.1-open-objective-panel-live",
        feasibility_diagnosis_hash=DIAGNOSIS_HASH,
        source_suite_snapshot_hashes=suite_hashes,
        evaluator_code_license_hash=license_hash,
        task_units=units,
        family_probes=probes,
        power_scenarios=panel_power_scenarios(),
    )
    assert report.status is OpenTaskPanelStatus.READY_FOR_CLEAN_BASELINE
    assert report.baseline_reproduction_authorized is True
    assert len(report.confirmatory_unit_ids) == 60
    assert report.family_confirmatory_counts == {
        "tabular_classification": 41,
        "tabular_regression": 19,
    }
    assert report.confirmatory_payloads_downloaded is False
    assert report.study_outcomes_observed is False
    assert report.existing_public_runs_queried is False
    assert report.novelty_search_started is False

    output_dir = Path(
        os.getenv(
            OUTPUT_ENV,
            str(root / "runs/manual-live/task26341-open-objective-panel-v1"),
        )
    )
    manifest = write_open_objective_task_panel(output_dir, report)
    assert manifest.report_hash == report.report_hash
