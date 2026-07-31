"""Dependency-free DiscoveryBench provenance projection for Task 263.6.5.

The runner reads a result-blind inventory payload.  It never opens dataset
values, metadata JSON bodies, or gold hypotheses.  Its only scientific inputs
are repository tree paths/object IDs and the dataset-name keys (not answer
text) extracted from the two sealed test answer-key files.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SOURCE_FOLDER_RE = re.compile(
    r"^discoverybench/(?P<kind>real|synth)/"
    r"(?P<split>train|test)/(?P<folder>[^/]+)$"
)
SYNTHETIC_FAMILY_RE = re.compile(
    r"^(?P<domain>.+)_(?P<tree_index>[0-9]+)_(?P<level_index>[0-9]+)$"
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _real_group(folder: str) -> str:
    if folder.startswith("nls_"):
        return "real:nls"
    if folder in {"meta_regression", "meta_regression_raw"}:
        return "real:meta-regression"
    if folder in {
        "worldbank_education_gdp",
        "worldbank_education_gdp_indicators",
    }:
        return "real:worldbank-education-gdp"
    return f"real:{folder.replace('_', '-')}"


def _source_group(kind: str, folder: str) -> str:
    if kind == "real":
        return _real_group(folder)
    match = SYNTHETIC_FAMILY_RE.fullmatch(folder)
    if match is None:
        raise ValueError(f"invalid synthetic folder name: {folder}")
    return (
        f"synth:{match.group('domain')}:"
        f"semantic-tree-{int(match.group('tree_index'))}"
    )


def _folder_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("tree_entries")
    if not isinstance(entries, list):
        raise ValueError("tree_entries must be a list")
    directory_paths = {
        item.get("path")
        for item in entries
        if isinstance(item, dict) and item.get("type") == "directory"
    }
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in directory_paths if isinstance(item, str)):
        match = SOURCE_FOLDER_RE.fullmatch(path)
        if match is None:
            continue
        prefix = f"{path}/"
        files = [
            item
            for item in entries
            if isinstance(item, dict)
            and item.get("type") == "file"
            and isinstance(item.get("path"), str)
            and item["path"].startswith(prefix)
        ]
        metadata = sorted(
            item["path"]
            for item in files
            if re.search(r"/metadata_[0-9]+\.json$", item["path"])
        )
        data = sorted(
            item["path"]
            for item in files
            if item["path"] not in metadata
        )
        if not metadata or not data:
            raise ValueError(f"folder lacks metadata or data files: {path}")
        kind = match.group("kind")
        split = match.group("split")
        folder = match.group("folder")
        records.append(
            {
                "folder_path": path,
                "folder_name": folder,
                "kind": kind,
                "split": split,
                "source_group_id": _source_group(kind, folder),
                "metadata_file_count": len(metadata),
                "data_file_count": len(data),
            }
        )
    return records


def _projection(payload: dict[str, Any]) -> dict[str, Any]:
    records = _folder_records(payload)
    answer_key_names = payload.get("answer_key_dataset_names")
    if not isinstance(answer_key_names, dict):
        raise ValueError("answer_key_dataset_names must be an object")
    real_keys = set(answer_key_names.get("real", []))
    synth_keys = set(answer_key_names.get("synth", []))

    test_records = [item for item in records if item["split"] == "test"]
    missing_test_lineage = sorted(
        item["folder_path"]
        for item in test_records
        if item["folder_name"]
        not in (real_keys if item["kind"] == "real" else synth_keys)
    )

    train_groups = {
        item["source_group_id"] for item in records if item["split"] == "train"
    }
    test_groups = {
        item["source_group_id"] for item in records if item["split"] == "test"
    }
    all_groups = train_groups | test_groups
    train_only = train_groups - test_groups
    test_only = test_groups - train_groups
    cross_split = train_groups & test_groups

    optimistic_train = {
        (
            item["source_group_id"]
            if item["kind"] == "real"
            else f"synth-folder:{item['folder_name']}"
        )
        for item in records
        if item["split"] == "train"
    }
    optimistic_test = {
        (
            item["source_group_id"]
            if item["kind"] == "real"
            else f"synth-folder:{item['folder_name']}"
        )
        for item in records
        if item["split"] == "test"
    }

    required_development = int(payload.get("required_development_groups", 30))
    required_reserve = int(payload.get("required_reserve_groups", 84))
    maximum_reserve_after_development = len(test_only) + len(cross_split)
    blockers: list[str] = []
    if len(all_groups) < required_development + required_reserve:
        blockers.append("independent-source-group-total-below-114")
    if maximum_reserve_after_development < required_reserve:
        blockers.append("conservative-reserve-groups-below-84")
    if len(optimistic_test) < required_reserve:
        blockers.append("optimistic-reserve-upper-bound-below-84")
    if missing_test_lineage:
        blockers.append("test-answer-key-lineage-incomplete")

    projection = {
        "schema_version": "discoverybench-inventory-projection-v1",
        "provisional_folder_count": len(records),
        "train_folder_count": sum(
            item["split"] == "train" for item in records
        ),
        "test_folder_count": sum(item["split"] == "test" for item in records),
        "real_folder_count": sum(item["kind"] == "real" for item in records),
        "synthetic_folder_count": sum(
            item["kind"] == "synth" for item in records
        ),
        "conservative_source_group_count": len(all_groups),
        "conservative_train_group_count": len(train_groups),
        "conservative_test_group_count": len(test_groups),
        "train_only_group_count": len(train_only),
        "test_only_group_count": len(test_only),
        "cross_split_group_count": len(cross_split),
        "maximum_reserve_after_development": maximum_reserve_after_development,
        "optimistic_development_upper_bound": len(optimistic_train),
        "optimistic_reserve_upper_bound": len(optimistic_test),
        "required_development_groups": required_development,
        "required_reserve_groups": required_reserve,
        "test_answer_key_lineage_complete": not missing_test_lineage,
        "missing_test_answer_key_folders": missing_test_lineage,
        "source_group_ids": sorted(all_groups),
        "blockers": sorted(blockers),
    }
    projection["projection_sha256"] = _sha256(projection)
    return projection


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: frozen_discoverybench_inventory_probe_v1.py INPUT")
    input_path = Path(sys.argv[1])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("inventory payload must be a JSON object")
    result = _projection(payload)
    sys.stdout.write(
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
