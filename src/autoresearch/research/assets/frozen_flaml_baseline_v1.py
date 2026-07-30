"""Standalone, network-free FLAML baseline runner for Task 263.4.2.

This file is copied into two clean workspaces and executed with two separately
created virtual environments.  It intentionally imports no AutoResearch code.
The parent audit process prepares train/test CSV files from the official OpenML
split and evaluates the emitted raw predictions with the separately pinned
objective evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("baseline result contains a non-finite value")
    return value


def _encode_features(
    train_frame: Any,
    test_frame: Any,
    *,
    feature_columns: list[str],
    numeric_columns: list[str],
    categorical_columns: list[str],
) -> tuple[Any, Any]:
    import numpy as np
    import pandas as pd

    if set(numeric_columns) | set(categorical_columns) != set(feature_columns):
        raise ValueError("numeric and categorical columns must partition features")
    if set(numeric_columns) & set(categorical_columns):
        raise ValueError("feature type partitions overlap")

    train_values: list[Any] = []
    test_values: list[Any] = []
    for column in feature_columns:
        if column in numeric_columns:
            train_column = pd.to_numeric(train_frame[column], errors="coerce")
            test_column = pd.to_numeric(test_frame[column], errors="coerce")
            median = float(train_column.median())
            if not math.isfinite(median):
                median = 0.0
            train_values.append(train_column.fillna(median).to_numpy(dtype="float64"))
            test_values.append(test_column.fillna(median).to_numpy(dtype="float64"))
            continue

        missing = "__AUTORESEARCH_MISSING__"
        train_column = train_frame[column].astype("string").fillna(missing)
        test_column = test_frame[column].astype("string").fillna(missing)
        categories = sorted(str(value) for value in train_column.unique())
        mapping = {value: index for index, value in enumerate(categories)}
        train_values.append(train_column.map(mapping).fillna(-1).to_numpy(dtype="float64"))
        test_values.append(test_column.map(mapping).fillna(-1).to_numpy(dtype="float64"))

    return (
        np.column_stack(train_values),
        np.column_stack(test_values),
    )


def _balanced_accuracy_metric(
    x_test: Any,
    y_test: Any,
    estimator: Any,
    labels: Any,
    x_train: Any,
    y_train: Any,
    weight_test: Any = None,
    weight_train: Any = None,
    config: Any = None,
    groups_test: Any = None,
    groups_train: Any = None,
) -> tuple[float, dict[str, float]]:
    del (
        labels,
        x_train,
        y_train,
        weight_train,
        config,
        groups_test,
        groups_train,
    )
    from sklearn.metrics import balanced_accuracy_score

    predicted = estimator.predict(x_test)
    score = float(balanced_accuracy_score(y_test, predicted, sample_weight=weight_test))
    return 1.0 - score, {"balanced_accuracy": score}


def _count_trials(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    count = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        if "record_id" in json.loads(line):
            count += 1
    return count


def run(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    import flaml
    import lightgbm
    import numpy as np
    import pandas as pd
    import sklearn
    import xgboost
    from flaml import AutoML

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "clean-baseline-input-v1":
        raise ValueError("unsupported clean baseline input schema")
    if manifest.get("network_allowed") is not False:
        raise ValueError("baseline execution must be network denied")
    if int(manifest["n_jobs"]) != 1:
        raise ValueError("baseline execution must use one training thread")
    if int(manifest["max_trials"]) < 1:
        raise ValueError("max_trials must be positive")

    input_dir = manifest_path.parent
    train_path = input_dir / manifest["train_file"]
    test_path = input_dir / manifest["test_file"]
    if _sha256(train_path) != manifest["train_sha256"]:
        raise ValueError("training CSV hash mismatch")
    if _sha256(test_path) != manifest["test_sha256"]:
        raise ValueError("test CSV hash mismatch")

    feature_columns = list(manifest["feature_columns"])
    target_column = str(manifest["target_column"])
    train_frame = pd.read_csv(train_path)
    test_frame = pd.read_csv(test_path)
    required_train = set(feature_columns) | {target_column}
    required_test = set(feature_columns) | {"row_id"}
    if set(train_frame.columns) != required_train:
        raise ValueError("training CSV columns do not match the manifest")
    if set(test_frame.columns) != required_test:
        raise ValueError("test CSV columns do not match the manifest")

    x_train, x_test = _encode_features(
        train_frame,
        test_frame,
        feature_columns=feature_columns,
        numeric_columns=list(manifest["numeric_columns"]),
        categorical_columns=list(manifest["categorical_columns"]),
    )
    family = str(manifest["family"])
    if family == "tabular_classification":
        y_train = train_frame[target_column].astype("string").to_numpy()
        task = "classification"
        metric: Any = _balanced_accuracy_metric
        split_type = "stratified"
    elif family == "tabular_regression":
        y_train = pd.to_numeric(train_frame[target_column], errors="raise").to_numpy(
            dtype="float64"
        )
        task = "regression"
        metric = "r2"
        split_type = "uniform"
    else:
        raise ValueError(f"unsupported task family: {family}")

    output_dir.mkdir(parents=True, exist_ok=False)
    log_path = output_dir / "flaml-trials.log"
    started = time.perf_counter()
    automl = AutoML()
    automl.fit(
        X_train=x_train,
        y_train=y_train,
        task=task,
        metric=metric,
        estimator_list=list(manifest["estimator_list"]),
        max_iter=int(manifest["max_trials"]),
        time_budget=-1,
        eval_method="holdout",
        split_type=split_type,
        split_ratio=float(manifest["validation_fraction"]),
        seed=int(manifest["seed"]),
        n_jobs=1,
        retrain_full=True,
        log_file_name=str(log_path),
        log_type="all",
        model_history=False,
        keep_search_state=False,
        verbose=0,
    )
    predicted = automl.predict(x_test)
    elapsed = time.perf_counter() - started

    rows: list[dict[str, Any]] = []
    for row_id, prediction in zip(
        test_frame["row_id"].tolist(),
        predicted,
        strict=True,
    ):
        if family == "tabular_classification":
            normalized_prediction: str | float = str(prediction)
        else:
            normalized_prediction = float(prediction)
            if not math.isfinite(normalized_prediction):
                raise ValueError("regression prediction is non-finite")
        rows.append(
            {
                "row_id": int(row_id),
                "prediction": normalized_prediction,
            }
        )
    rows.sort(key=lambda item: item["row_id"])
    prediction_bytes = (_canonical_json(rows) + "\n").encode("utf-8")
    prediction_path = output_dir / "predictions.json"
    prediction_path.write_bytes(prediction_bytes)

    versions = {
        "flaml": flaml.__version__,
        "lightgbm": lightgbm.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "python": sys.version.split()[0],
        "scikit-learn": sklearn.__version__,
        "xgboost": xgboost.__version__,
    }
    result = {
        "schema_version": "clean-baseline-run-result-v1",
        "unit_id": manifest["unit_id"],
        "family": family,
        "seed": int(manifest["seed"]),
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "input_manifest_sha256": _sha256(manifest_path),
        "train_sha256": manifest["train_sha256"],
        "test_sha256": manifest["test_sha256"],
        "prediction_sha256": hashlib.sha256(prediction_bytes).hexdigest(),
        "prediction_count": len(rows),
        "best_estimator": str(automl.best_estimator),
        "best_config": _jsonable(automl.best_config),
        "best_loss": float(automl.best_loss),
        "trial_count": _count_trials(log_path),
        "elapsed_seconds": elapsed,
        "versions": versions,
        "process_id": os.getpid(),
        "network_allowed": False,
    }
    result_path = output_dir / "runner-result.json"
    result_path.write_text(_canonical_json(result) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.manifest.resolve(), arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
