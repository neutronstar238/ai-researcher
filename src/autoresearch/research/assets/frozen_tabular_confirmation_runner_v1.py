"""Network-free confirmation adapter for the frozen tabular candidate runner.

The scientific learner, preprocessing, sampling, metric, and prediction logic
remain delegated to the hash-pinned Task 263.5 v2 runner.  This adapter changes
only the evidence boundary: it accepts a one-use confirmatory-label artifact,
binds it to the confirmation freeze/reveal, and confines every readable or
writable path to the assigned confirmation workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]
from sklearn.preprocessing import LabelEncoder  # type: ignore[import-not-found]

try:
    from . import frozen_tabular_candidate_runner_v2 as _development
except ImportError:  # pragma: no cover - exercised by the clean subprocess
    _development = importlib.import_module("frozen_tabular_candidate_runner_v2")

RUNNER_SCHEMA_VERSION = "frozen-tabular-confirmation-runner-v1"
DEVELOPMENT_RUNNER_V2_SHA256 = "6bffee04762d864a8719b650da105e917d825a5e9fc3cbbcb5876637d2e67126"
LABEL_SCHEMA_VERSION = "confirmatory-labels-v1"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_development_path = Path(_development.__file__).resolve()
if _file_sha256(_development_path) != DEVELOPMENT_RUNNER_V2_SHA256:
    raise RuntimeError("frozen Task 263.5 v2 runner dependency hash mismatch")


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_confirmation_config(config: dict[str, Any]) -> tuple[Path, Path, Path]:
    _development._legacy._require_config(config)
    required = {
        "allowed_root",
        "confirmation_freeze_hash",
        "reveal_hash",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"missing confirmation config fields: {', '.join(missing)}")
    root = Path(str(config["allowed_root"])).resolve()
    if not root.is_dir():
        raise ValueError("confirmation allowed root does not exist")
    train_path = Path(str(config["train_path"])).resolve()
    test_path = Path(str(config["test_path"])).resolve()
    labels_path = Path(str(config["labels_path"])).resolve()
    paths = (train_path, test_path, labels_path)
    if not all(_within(path, root) for path in paths):
        raise ValueError("confirmation input escaped its assigned workspace")
    return paths


def _load_labels(
    path: Path,
    *,
    config: dict[str, Any],
    observed_row_ids: list[int],
) -> np.ndarray:
    labels_payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(labels_payload, dict):
        raise ValueError("confirmatory labels artifact is not an object")
    expected_hash = labels_payload.get("label_hash")
    body = dict(labels_payload)
    body.pop("label_hash", None)
    if not isinstance(expected_hash, str) or _canonical_sha256(body) != expected_hash:
        raise ValueError("confirmatory labels content hash mismatch")
    required_bindings = {
        "schema_version": LABEL_SCHEMA_VERSION,
        "partition": "confirmatory",
        "one_use_reveal": True,
        "opaque_unit_id": config["opaque_unit_id"],
        "confirmation_freeze_hash": config["confirmation_freeze_hash"],
        "reveal_hash": config["reveal_hash"],
    }
    for key, expected in required_bindings.items():
        if labels_payload.get(key) != expected:
            raise ValueError(f"confirmatory labels {key} binding mismatch")
    expected_row_ids = [int(value) for value in labels_payload.get("row_ids", [])]
    if observed_row_ids != expected_row_ids:
        raise ValueError("confirmatory labels/test row IDs differ")
    raw_labels = labels_payload.get("labels")
    if not isinstance(raw_labels, list) or len(raw_labels) != len(observed_row_ids):
        raise ValueError("confirmatory label count mismatch")
    return np.asarray(raw_labels)


def _run(config: dict[str, Any]) -> dict[str, Any]:
    train_path, test_path, labels_path = _require_confirmation_config(config)
    if _file_sha256(train_path) != config["train_sha256"]:
        raise ValueError("train input hash mismatch")
    if _file_sha256(test_path) != config["test_sha256"]:
        raise ValueError("test input hash mismatch")
    if _file_sha256(labels_path) != config["labels_sha256"]:
        raise ValueError("confirmatory labels file hash mismatch")

    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)
    if "target" not in train or "row_id" not in test:
        raise ValueError("frozen input is missing target or row ID")
    feature_columns = [column for column in train.columns if column != "target"]
    if feature_columns != [column for column in test.columns if column != "row_id"]:
        raise ValueError("train/test feature columns differ")
    x_all = train.loc[:, feature_columns]
    x_test = test.loc[:, feature_columns]
    y_all_raw = train["target"].to_numpy()
    observed_row_ids = [int(value) for value in test["row_id"].to_list()]
    y_test_raw = (
        _load_labels(
            labels_path,
            config=config,
            observed_row_ids=observed_row_ids,
        )
        if config["stage"] == "F3"
        else None
    )

    if config["family"] == "tabular_classification":
        encoder = LabelEncoder()
        encoder.fit(y_all_raw)
        y_all = encoder.transform(y_all_raw)
        stratify = y_all
    else:
        y_all = np.asarray(y_all_raw, dtype=float)
        stratify = None

    if config["stage"] == "F3":
        if y_test_raw is None:
            raise ValueError("confirmatory test labels are missing at F3")
        x_fit = x_all
        y_fit = y_all
        x_eval = x_test
        y_eval = y_test_raw
        evaluation_split = "confirmatory_test"
    else:
        (
            fit_indices,
            eval_indices,
        ) = _development._legacy.train_test_split(
            np.arange(len(y_all)),
            test_size=float(config["validation_fraction"]),
            random_state=int(config["seed"]),
            shuffle=True,
            stratify=stratify,
        )
        selected_local = _development._legacy._subsample_indices(
            y_all[fit_indices],
            family=config["family"],
            fraction=float(config["training_fraction"]),
            seed=int(config["seed"]) + (1 if config["stage"] == "F1" else 2),
        )
        selected = np.sort(fit_indices[selected_local])
        x_fit = x_all.iloc[selected]
        y_fit = y_all[selected]
        x_eval = x_all.iloc[np.sort(eval_indices)]
        y_eval = y_all[np.sort(eval_indices)]
        evaluation_split = "internal_validation"

    predictions = _development._fit_predict(config, x_fit, y_fit, x_eval)
    if len(predictions) != len(y_eval):
        raise ValueError("prediction count mismatch")
    if not np.all(np.isfinite(np.asarray(predictions, dtype=float))):
        raise ValueError("predictions contain non-finite values")
    if config["family"] == "tabular_classification":
        if config["stage"] == "F3":
            scored_predictions = encoder.inverse_transform(np.asarray(predictions, dtype=int))
        else:
            scored_predictions = predictions
        score = float(
            _development._legacy.balanced_accuracy_score(
                y_eval,
                scored_predictions,
            )
        )
        metric_id = "balanced_accuracy"
        serialized_predictions: list[int | float] = [
            int(value) for value in np.asarray(predictions)
        ]
    else:
        score = float(_development._legacy.r2_score(y_eval, predictions))
        metric_id = "r2"
        serialized_predictions = [float(value) for value in np.asarray(predictions, dtype=float)]
    if not math.isfinite(score):
        raise ValueError("objective score is non-finite")

    peak_rss_mb = _development._legacy._peak_rss_mb()
    memory_valid = peak_rss_mb <= float(config["maximum_memory_mb"])
    payload: dict[str, Any] = {
        "schema_version": "tabular-confirmation-candidate-result-v1",
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "development_runner_v2_sha256": DEVELOPMENT_RUNNER_V2_SHA256,
        "execution_id": config["execution_id"],
        "opaque_unit_id": config["opaque_unit_id"],
        "candidate_id": config["candidate_id"],
        "candidate_hash": config["candidate_hash"],
        "stage": config["stage"],
        "family": config["family"],
        "metric_id": metric_id,
        "score": score,
        "higher_is_better": True,
        "evaluation_split": evaluation_split,
        "fit_row_count": len(x_fit),
        "evaluation_row_count": len(x_eval),
        "feature_count": len(feature_columns),
        "prediction_count": len(serialized_predictions),
        "prediction_sha256": _canonical_sha256(serialized_predictions),
        "train_sha256": config["train_sha256"],
        "test_sha256": config["test_sha256"],
        "labels_sha256": config["labels_sha256"],
        "confirmation_freeze_hash": config["confirmation_freeze_hash"],
        "reveal_hash": config["reveal_hash"],
        "seed": int(config["seed"]),
        "training_fraction": float(config["training_fraction"]),
        "cpu_seconds": max(0.0, time.process_time() - cpu_started),
        "wall_seconds": max(0.0, time.perf_counter() - wall_started),
        "peak_rss_mb": peak_rss_mb,
        "maximum_memory_mb": int(config["maximum_memory_mb"]),
        "memory_valid": memory_valid,
        "network_allowed": False,
    }
    payload["result_hash"] = _canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("execution config must be a JSON object")
    root = Path(str(config.get("allowed_root", ""))).resolve()
    output_path = args.output.resolve()
    if not _within(output_path, root):
        raise ValueError("confirmation output escaped its assigned workspace")
    result = _run(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
