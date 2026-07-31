from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from autoresearch.research.opportunity_tournament import (
    LiveResourceProbe,
    ResourceKind,
)
from autoresearch.research.portfolio import (
    NearestWorkDelta,
    PortfolioIntegrityError,
    ResearchSource,
    SourceMaturity,
)
from autoresearch.research.socratic_development_vertical import (
    AnswerKeySummary,
    DiscoveryBenchSourceKind,
    InventoryReplayCertificate,
    InventoryReplayObservation,
    LicenseScope,
    LicenseScopeEvidence,
    SocraticInventoryStatus,
    SocraticVerticalStopped,
    build_inventory_projection,
    build_inventory_replay_payload,
    build_socratic_development_inventory,
    load_socratic_development_inventory,
    require_socratic_evaluator_admission,
    socratic_inventory_json_schemas,
    write_socratic_development_inventory,
)
from autoresearch.research.workload_qualified_opportunity import InterpreterRuntime

CHECKED_AT = datetime(2026, 7, 31, 6, 0, tzinfo=timezone.utc)
REVISION = "e54ec033049d3a0fd95d3c746919cc8c01c25781"

REAL_TRAIN = [
    "evolution_freshwater_fish",
    "immigration_offshoring_effect_on_employment",
    "nls_bmi",
    "nls_bmi_raw",
]
REAL_TEST = [
    "archaeology",
    "introduction_pathways_non-native_plants",
    "meta_regression",
    "meta_regression_raw",
    "nls_incarceration",
    "nls_raw",
    "nls_ses",
    "requirements_engineering_for_ML_enabled_systems",
    "worldbank_education_gdp",
    "worldbank_education_gdp_indicators",
]


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _oid(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()


def _synthetic_names(
    *,
    prefix: str,
    group_count: int,
    folder_count: int,
) -> list[str]:
    base = folder_count // group_count
    remainder = folder_count % group_count
    names: list[str] = []
    for group_index in range(group_count):
        levels = base + (1 if group_index < remainder else 0)
        names.extend(
            f"{prefix}-{group_index}_{group_index}_{level}"
            for level in range(levels)
        )
    assert len(names) == folder_count
    return names


def _tree() -> tuple[list[dict[str, Any]], list[str], list[str]]:
    synth_train = _synthetic_names(
        prefix="train-domain",
        group_count=64,
        folder_count=100,
    )
    synth_test = _synthetic_names(
        prefix="test-domain",
        group_count=35,
        folder_count=75,
    )
    entries: list[dict[str, Any]] = []
    for kind, split, names in (
        ("real", "train", REAL_TRAIN),
        ("real", "test", REAL_TEST),
        ("synth", "train", synth_train),
        ("synth", "test", synth_test),
    ):
        for name in names:
            folder = f"discoverybench/{kind}/{split}/{name}"
            entries.extend(
                [
                    {
                        "type": "directory",
                        "path": folder,
                        "oid": _oid(f"directory:{folder}"),
                        "size": 0,
                    },
                    {
                        "type": "file",
                        "path": f"{folder}/data.csv",
                        "oid": _oid(f"data:{folder}"),
                        "size": 100,
                    },
                    {
                        "type": "file",
                        "path": f"{folder}/metadata_0.json",
                        "oid": _oid(f"metadata:{folder}"),
                        "size": 50,
                    },
                ]
            )
    entries.extend(
        [
            {
                "type": "file",
                "path": "answer_key/answer_key_real.csv",
                "oid": _oid("real-answer"),
                "size": 100,
            },
            {
                "type": "file",
                "path": "answer_key/answer_key_synth.csv",
                "oid": _oid("synth-answer"),
                "size": 100,
            },
        ]
    )
    return entries, synth_train, synth_test


def _answer_bytes(names: list[str]) -> bytes:
    rows = ["dataset,metadataid,query_id,gold_hypo"]
    rows.extend(f'{name},0,0,"sealed hypothesis {index}"' for index, name in enumerate(names))
    return ("\n".join(rows) + "\n").encode()


def _answer_keys(
    tree: list[dict[str, Any]],
    synth_test: list[str],
) -> list[AnswerKeySummary]:
    by_path = {item["path"]: item for item in tree}
    return [
        AnswerKeySummary.create(
            source_kind=DiscoveryBenchSourceKind.REAL,
            path="answer_key/answer_key_real.csv",
            git_object_id=by_path["answer_key/answer_key_real.csv"]["oid"],
            raw_bytes=_answer_bytes(REAL_TEST),
        ),
        AnswerKeySummary.create(
            source_kind=DiscoveryBenchSourceKind.SYNTHETIC,
            path="answer_key/answer_key_synth.csv",
            git_object_id=by_path["answer_key/answer_key_synth.csv"]["oid"],
            raw_bytes=_answer_bytes(synth_test),
        ),
    ]


def _database_license() -> LicenseScopeEvidence:
    return LicenseScopeEvidence.create(
        resource_id="discoverybench-database-license",
        evidence_url="https://example.org/discovery-license",
        observed_license_id="ODC-By-1.0",
        license_file_object_id=_oid("discovery-license"),
        license_text_sha256=_sha("odc-by"),
        scope=LicenseScope.DATABASE_RIGHTS,
        database_use_verified=True,
        software_reuse_verified=False,
        individual_contents_redistribution_verified=False,
        attribution_required=True,
        interpretation="Database rights only; software and content rights are separate.",
    )


def _harness_license() -> LicenseScopeEvidence:
    return LicenseScopeEvidence.create(
        resource_id="astabench-software-license",
        evidence_url="https://example.org/asta-license",
        observed_license_id="Apache-2.0",
        license_file_object_id=_oid("asta-license"),
        license_text_sha256=_sha("apache"),
        scope=LicenseScope.SOFTWARE,
        database_use_verified=False,
        software_reuse_verified=True,
        individual_contents_redistribution_verified=False,
        attribution_required=True,
        interpretation="Apache-2.0 software evidence does not license dataset contents.",
    )


def _runtime(role: str) -> InterpreterRuntime:
    return InterpreterRuntime.create(
        role_id=role,
        executable_locator_hash=_sha(f"{role}:locator"),
        executable_sha256=_sha(f"{role}:executable"),
        python_version="Python 3.10.20",
    )


def _replay_certificate(
    projection_sha256: str,
    replay_payload: dict[str, Any],
) -> InventoryReplayCertificate:
    runner_sha = _sha("frozen-inventory-runner")
    input_sha = hashlib.sha256(
        (
            json.dumps(
                replay_payload,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
    ).hexdigest()
    runtimes = [_runtime("clean-a"), _runtime("clean-b")]
    observations = [
        InventoryReplayObservation.create(
            role_id=runtime.role_id,
            interpreter_environment_hash=runtime.environment_hash,
            command_hash=_sha(f"{runtime.role_id}:command"),
            input_sha256=input_sha,
            runner_sha256=runner_sha,
            stdout_sha256=_sha(f"{runtime.role_id}:stdout"),
            stderr_sha256=_sha(""),
            projection_sha256=projection_sha256,
            observed_at=CHECKED_AT,
        )
        for runtime in runtimes
    ]
    return InventoryReplayCertificate.create(
        runner_sha256=runner_sha,
        input_sha256=input_sha,
        interpreter_runtimes=runtimes,
        observations=observations,
        expected_projection_sha256=projection_sha256,
    )


def _source_material() -> tuple[
    list[ResearchSource],
    list[NearestWorkDelta],
    list[LiveResourceProbe],
]:
    ids = [
        "ahois",
        "astabench",
        "autosdt",
        "discoverybench",
        "popper",
        "scienceagentbench",
        "sciagentarena",
    ]
    probes = []
    sources = []
    deltas = []
    for index, source_id in enumerate(ids):
        sample = f"{source_id}:sample".encode()
        probe = LiveResourceProbe.create(
            resource_id=source_id,
            kind=ResourceKind.LITERATURE,
            requested_url=f"https://example.org/{source_id}",
            resolved_url=f"https://example.org/{source_id}",
            status_code=200,
            sample_bytes=len(sample),
            sample_sha256=hashlib.sha256(sample).hexdigest(),
            reachable=True,
            checked_at=CHECKED_AT,
            error=None,
        )
        probes.append(probe)
        sources.append(
            ResearchSource(
                source_id=source_id,
                title=f"Verified primary work {index}",
                year=2024 + index % 3,
                locator=f"arxiv:{source_id}",
                source_url=probe.requested_url,
                maturity=SourceMaturity.PEER_REVIEWED,
                source_fingerprint=probe.sample_sha256,
            )
        )
        deltas.append(
            NearestWorkDelta(
                source_id=source_id,
                shared_scope="objective evaluation of scientific agents",
                claimed_delta="source-group-valid fault detection under equal budgets",
                overlap_risk="existing work may subsume the intended critic",
                decisive_comparison="paired source-group ablation with exact labels",
            )
        )
    return sources, deltas, probes


def _report() -> tuple[Any, dict[str, Any]]:
    tree, _, synth_test = _tree()
    answers = _answer_keys(tree, synth_test)
    database_license = _database_license()
    folders, projection = build_inventory_projection(
        tree_entries=tree,
        answer_keys=answers,
        database_license=database_license,
    )
    assert len(folders) == 189
    replay_payload = build_inventory_replay_payload(
        tree_entries=tree,
        answer_keys=answers,
    )
    replay = _replay_certificate(projection.projection_sha256, replay_payload)
    sources, deltas, probes = _source_material()
    report = build_socratic_development_inventory(
        study_id="task26365-unit",
        created_at=CHECKED_AT,
        literature_cutoff=date(2026, 7, 31),
        research_questions=[
            "Can provenance clustering retain 30 development and 84 reserve groups?",
            "Can the four fault classes be scored without a model judge?",
            "Does a full critic improve paired objective correctness under equal budgets?",
        ],
        sources=sources,
        nearest_work=deltas,
        source_probes=probes,
        dataset_metadata={
            "sha": REVISION,
            "lastModified": CHECKED_AT.isoformat(),
            "gated": False,
            "private": False,
            "cardData": {"license": "odc-by"},
        },
        tree_entries=tree,
        answer_keys=answers,
        database_license=database_license,
        harness_license=_harness_license(),
        replay_certificate=replay,
    )
    return report, replay_payload


def test_inventory_clustering_stops_before_evaluator_or_model_calls() -> None:
    report, _ = _report()
    projection = report.projection

    assert projection.provisional_folder_count == 189
    assert projection.train_folder_count == 104
    assert projection.test_folder_count == 85
    assert projection.conservative_source_group_count == 107
    assert projection.conservative_train_group_count == 67
    assert projection.conservative_test_group_count == 41
    assert projection.cross_split_group_count == 1
    assert projection.maximum_reserve_after_development == 41
    assert projection.optimistic_development_upper_bound == 103
    assert projection.optimistic_reserve_upper_bound == 81
    assert report.decision.status is SocraticInventoryStatus.STOPPED_AT_INVENTORY
    assert report.decision.evaluator_construction_authorized is False
    assert report.decision.baseline_execution_authorized is False
    assert report.decision.provider_configuration_collected is False
    assert report.decision.confirmatory_panel_created_or_read is False
    assert report.decision.blockers == [
        "conservative-reserve-groups-below-84",
        "independent-source-group-total-below-114",
        "optimistic-reserve-upper-bound-below-84",
    ]


def test_real_raw_processed_and_synthetic_levels_share_source_groups() -> None:
    report, _ = _report()
    by_name = {item.folder_name: item for item in report.folders}

    assert (
        by_name["meta_regression"].source_group_id
        == by_name["meta_regression_raw"].source_group_id
    )
    assert (
        by_name["worldbank_education_gdp"].source_group_id
        == by_name["worldbank_education_gdp_indicators"].source_group_id
    )
    assert (
        by_name["nls_bmi"].source_group_id
        == by_name["nls_incarceration"].source_group_id
    )
    assert (
        by_name["test-domain-0_0_0"].source_group_id
        == by_name["test-domain-0_0_1"].source_group_id
    )
    assert by_name["archaeology"].answer_key_dataset_present is True
    assert by_name["evolution_freshwater_fish"].answer_key_path is None


def test_downstream_socratic_construction_fails_closed() -> None:
    report, _ = _report()

    with pytest.raises(SocraticVerticalStopped, match="inventory"):
        require_socratic_evaluator_admission(report)


def test_answer_key_duplicate_and_report_tamper_are_rejected() -> None:
    duplicate = (
        b"dataset,metadataid,query_id,gold_hypo\n"
        b'item,0,0,"one"\n'
        b'item,0,0,"two"\n'
    )
    with pytest.raises(ValueError, match="duplicate answer-key key"):
        AnswerKeySummary.create(
            source_kind=DiscoveryBenchSourceKind.REAL,
            path="answer_key/answer_key_real.csv",
            git_object_id=_oid("duplicate"),
            raw_bytes=duplicate,
        )

    report, _ = _report()
    payload = report.model_dump(mode="json")
    payload["projection"]["optimistic_reserve_upper_bound"] = 84
    with pytest.raises(
        ValidationError,
        match="inventory projection hash mismatch",
    ):
        type(report).model_validate(payload)


def test_answer_key_strictly_records_windows_1252_fallback() -> None:
    raw = (
        "dataset,metadataid,query_id,gold_hypo\r\n"
        'item,0,0,"researcher’s hypothesis"\r\n'
    ).encode("cp1252")
    summary = AnswerKeySummary.create(
        source_kind=DiscoveryBenchSourceKind.REAL,
        path="answer_key/answer_key_real.csv",
        git_object_id=_oid("cp1252"),
        raw_bytes=raw,
    )

    assert summary.decoded_encoding == "windows-1252"
    assert summary.row_count == 1
    assert summary.gold_hypothesis_text_retained is False


def test_answer_key_inventory_does_not_inspect_gold_hypothesis_values() -> None:
    raw = b"dataset,metadataid,query_id,gold_hypo\nitem,0,0,\n"
    summary = AnswerKeySummary.create(
        source_kind=DiscoveryBenchSourceKind.REAL,
        path="answer_key/answer_key_real.csv",
        git_object_id=_oid("sealed-gold"),
        raw_bytes=raw,
    )

    assert summary.row_count == 1
    assert summary.dataset_names == ["item"]
    assert summary.gold_hypothesis_text_retained is False


def test_frozen_standard_library_runner_matches_local_projection(
    tmp_path: Path,
) -> None:
    report, replay_payload = _report()
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(replay_payload, sort_keys=True),
        encoding="utf-8",
    )
    runner = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_discoverybench_inventory_probe_v1.py"
    )
    completed = subprocess.run(
        [sys.executable, str(runner), str(input_path)],
        capture_output=True,
        check=True,
        text=True,
    )
    output = json.loads(completed.stdout)

    assert output["projection_sha256"] == report.projection.projection_sha256
    assert output["optimistic_reserve_upper_bound"] == 81
    assert output["maximum_reserve_after_development"] == 41


def test_persistence_manifest_and_schema_are_deterministic(
    tmp_path: Path,
) -> None:
    report, replay_payload = _report()
    runner = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_discoverybench_inventory_probe_v1.py"
    )
    (tmp_path / "inventory-replay-input.json").write_text(
        json.dumps(
            replay_payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = write_socratic_development_inventory(
        report,
        tmp_path,
        runner_path=runner,
    )
    loaded, loaded_manifest = load_socratic_development_inventory(tmp_path)

    assert loaded == report
    assert loaded_manifest == manifest
    assert socratic_inventory_json_schemas() == socratic_inventory_json_schemas()
    assert manifest.inventory_runner_sha256 == hashlib.sha256(
        runner.read_bytes()
    ).hexdigest()

    report_path = tmp_path / manifest.report_filename
    report_path.write_text(report_path.read_text() + " ", encoding="utf-8")
    with pytest.raises(PortfolioIntegrityError, match="report file hash mismatch"):
        load_socratic_development_inventory(tmp_path)
