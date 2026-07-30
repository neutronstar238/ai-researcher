"""Opt-in live feasibility diagnosis for Task 263.4.0."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import (
    BaselineReproductionAttempt,
    BenchmarkTaskAudit,
    ExactPairedPowerScenario,
    SearchPolicyFeasibilityReport,
    StudyFeasibilityStatus,
    TaskOutputKind,
    load_search_policy_feasibility,
    write_search_policy_feasibility,
)

LIVE_ENV = "AUTORESEARCH_SEARCH_POLICY_STUDY_LIVE"
OUTPUT_ENV = "AUTORESEARCH_SEARCH_POLICY_STUDY_OUTPUT"

CSV_URL = (
    "https://huggingface.co/datasets/osunlp/ScienceAgentBench/"
    "resolve/main/ScienceAgentBench.csv"
)
README_URL = (
    "https://raw.githubusercontent.com/OSU-NLP-Group/"
    "ScienceAgentBench/main/README.md"
)
GITHUB_TREE_URL = (
    "https://api.github.com/repos/OSU-NLP-Group/"
    "ScienceAgentBench/git/trees/main?recursive=1"
)
HF_TREE_URL = (
    "https://huggingface.co/api/datasets/osunlp/"
    "ScienceAgentBench/tree/main?recursive=true&expand=false"
)
ARTIFACT_URL = (
    "https://buckeyemailosu-my.sharepoint.com/:u:/g/personal/"
    "chen_8336_osu_edu/IQB870QrmuqwS5Ck33cHpJfkAVt3LsMeariREIwP3AT7byA"
    "?e=3ckueC"
)
EXPECTED_CSV_SHA256 = (
    "7f490f17f721a9c7e9415d3608a1a37d1a5315a26862cf556e3096ac4062face"
)
TOURNAMENT_REPORT_HASH = (
    "de4769b74098650a1ed7a7f92fdd853459f468d5a35e4b6d152f0169779bf0ff"
)
DEVELOPMENT_IDS = (1, 2, 4, 5)
CONFIRMATORY_IDS = tuple(range(61, 73))
SPECIAL_LICENSE_IDS = {3, 32, 46, 53, 54, 84}

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to audit the official ScienceAgentBench metadata, "
        "repository tree, evaluator/data availability, and exact prospective power"
    ),
)


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = (
        "AutoResearch/1.0 task-263.4.0-feasibility-audit"
    )
    return session


def _bounded_get(
    session: requests.Session,
    url: str,
    *,
    maximum_bytes: int,
) -> bytes:
    response = session.get(url, timeout=60, stream=True, allow_redirects=True)
    response.raise_for_status()
    content = bytearray()
    for chunk in response.iter_content(chunk_size=16_384):
        if not chunk:
            continue
        content.extend(chunk)
        if len(content) > maximum_bytes:
            response.close()
            raise AssertionError(f"bounded source exceeded {maximum_bytes} bytes")
    response.close()
    return bytes(content)


def _task_audit(row: dict[str, str]) -> BenchmarkTaskAudit:
    instance_id = int(row["instance_id"])
    output_path = row["output_fname"].strip()
    output_kind = (
        TaskOutputKind.IMAGE
        if Path(output_path).suffix.lower()
        in {".png", ".jpg", ".jpeg", ".svg", ".pdf"}
        else TaskOutputKind.STRUCTURED
    )
    assert instance_id not in SPECIAL_LICENSE_IDS
    return BenchmarkTaskAudit.create(
        benchmark_id="scienceagentbench",
        task_id=f"sab-{instance_id:03d}",
        domain=row["domain"].strip(),
        metadata_source_url=CSV_URL,
        output_path=output_path,
        evaluator_name=row["eval_script_name"].strip(),
        output_kind=output_kind,
        license_id="ScienceAgentBench-default-CC-BY-4.0",
        license_clear=True,
        data_bundle_available=False,
        evaluator_source_available=False,
        deterministic_evaluator=False,
        model_judge_required=output_kind is TaskOutputKind.IMAGE,
        metadata_only=True,
    )


def _json_paths(payload: Any) -> set[str]:
    assert isinstance(payload, list)
    return {
        str(item["path"])
        for item in payload
        if isinstance(item, dict) and "path" in item
    }


def test_live_search_policy_feasibility_diagnosis() -> None:
    session = _session()
    csv_bytes = _bounded_get(session, CSV_URL, maximum_bytes=400_000)
    csv_hash = hashlib.sha256(csv_bytes).hexdigest()
    assert csv_hash == EXPECTED_CSV_SHA256

    # Retain only evaluator-facing metadata; no task prompt, domain knowledge,
    # gold program, gold result, or evaluation result enters the diagnosis.
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    allowed_fields = {
        "instance_id",
        "domain",
        "output_fname",
        "eval_script_name",
    }
    rows: list[dict[str, str]] = []
    for remote_row in reader:
        rows.append({field: remote_row[field] for field in allowed_fields})
    assert len(rows) == 102
    selected_ids = set(DEVELOPMENT_IDS) | set(CONFIRMATORY_IDS)
    selected_rows = [
        row for row in rows if int(row["instance_id"]) in selected_ids
    ]
    assert {int(row["instance_id"]) for row in selected_rows} == selected_ids

    readme_bytes = _bounded_get(session, README_URL, maximum_bytes=32_000)
    readme = readme_bytes.decode("utf-8")
    assert "extract 102 tasks from 44 peer-reviewed publications" in readme
    assert "`benchmark_verified.zip`" in readme
    assert "GPT-4o to judge output visualizations" in readme
    assert "Most tasks in ScienceAgentBench is licensed" in readme
    assert all(
        f"Instance ID: {instance_id}" not in readme
        for instance_id in sorted(selected_ids)
    )

    github_tree_bytes = _bounded_get(
        session, GITHUB_TREE_URL, maximum_bytes=64_000
    )
    github_tree = json.loads(github_tree_bytes)
    assert github_tree["truncated"] is False
    github_paths = _json_paths(github_tree["tree"])
    assert "evaluation/harness/run_evaluation.py" in github_paths
    assert "gpt4_visual_judge.py" in github_paths
    assert "benchmark_verified.zip" not in github_paths
    assert not any(
        row["eval_script_name"] in github_paths for row in selected_rows
    )

    hf_tree_bytes = _bounded_get(session, HF_TREE_URL, maximum_bytes=16_000)
    hf_paths = _json_paths(json.loads(hf_tree_bytes))
    assert hf_paths == {
        ".gitattributes",
        "README.md",
        "ScienceAgentBench.csv",
        "data",
        "data/verified-00000-of-00001.parquet",
    }
    assert "benchmark_verified.zip" not in hf_paths

    try:
        # This separate no-retry probe avoids treating a private SharePoint
        # transport failure as evidence that the scientific artifact exists.
        artifact_response = requests.head(
            ARTIFACT_URL,
            headers={"User-Agent": session.headers["User-Agent"]},
            timeout=20,
            allow_redirects=True,
        )
        artifact_publicly_downloadable = (
            artifact_response.status_code == 200
            and "benchmark_verified.zip"
            in artifact_response.headers.get("Content-Disposition", "")
        )
        artifact_resolved_url = str(artifact_response.url)
        artifact_response.close()
    except requests.RequestException:
        artifact_publicly_downloadable = False
        artifact_resolved_url = ARTIFACT_URL
    assert artifact_publicly_downloadable is False
    assert "sharepoint.com" in artifact_resolved_url

    task_audits = [_task_audit(row) for row in selected_rows]
    assert sum(
        task.output_kind is TaskOutputKind.IMAGE
        for task in task_audits
        if task.task_id in {f"sab-{value:03d}" for value in CONFIRMATORY_IDS}
    ) == 9
    assert sum(
        task.output_kind is TaskOutputKind.STRUCTURED
        for task in task_audits
        if task.task_id in {f"sab-{value:03d}" for value in CONFIRMATORY_IDS}
    ) == 3

    source_hashes = sorted(
        {
            csv_hash,
            hashlib.sha256(readme_bytes).hexdigest(),
            hashlib.sha256(github_tree_bytes).hexdigest(),
            hashlib.sha256(hf_tree_bytes).hexdigest(),
        }
    )
    reproduction = BaselineReproductionAttempt.create(
        baseline_id="scienceagentbench-verified-baseline",
        claim_hash=canonical_sha256(
            {
                "claim": (
                    "portfolio plus memory improves objective paired task success "
                    "by at least 0.25 versus a linear self-loop"
                )
            }
        ),
        source_hashes=source_hashes,
        metric_id="objective-task-success",
        tolerance=0.0,
        attempted=False,
        blockers=[
            (
                "anonymous bounded probe did not return benchmark_verified.zip; "
                "task data and task-specific evaluator programs are not "
                "anonymously auditable"
            )
        ],
    )
    power_scenarios = [
        ExactPairedPowerScenario.create(
            independent_unit_count=len(CONFIRMATORY_IDS),
            alpha=0.05,
            target_power=0.80,
            minimum_effect=0.25,
            favorable_probability=0.25 + unfavorable,
            unfavorable_probability=unfavorable,
        )
        for unfavorable in (0.0, 0.05, 0.10)
    ]
    report = SearchPolicyFeasibilityReport.create(
        report_id="task-263.4.0-live-feasibility",
        tournament_report_hash=TOURNAMENT_REPORT_HASH,
        benchmark_id="scienceagentbench",
        benchmark_version="verified-2026-04-30-metadata-only",
        metadata_snapshot_hash=csv_hash,
        task_audits=task_audits,
        development_task_ids=[
            f"sab-{value:03d}" for value in DEVELOPMENT_IDS
        ],
        confirmatory_task_ids=[
            f"sab-{value:03d}" for value in CONFIRMATORY_IDS
        ],
        power_scenarios=power_scenarios,
        reproduction=reproduction,
    )
    assert report.status is StudyFeasibilityStatus.BLOCKED_REPRODUCTION_DIAGNOSIS
    assert report.required_confirmatory_task_count == 60
    assert [round(item.achieved_power, 6) for item in report.power_scenarios] == [
        0.054402,
        0.080152,
        0.095619,
    ]
    assert report.novelty_search_started is False
    assert report.confirmatory_results_revealed is False
    assert report.external_submission_authorized is False

    output = Path(
        os.getenv(
            OUTPUT_ENV,
            "runs/manual-live/task2634-search-policy-diagnosis-v1",
        )
    )
    manifest = write_search_policy_feasibility(output, report)
    assert manifest.report_hash == report.report_hash
    assert (
        load_search_policy_feasibility(
            output / "search-policy-feasibility.json"
        )
        == report
    )
