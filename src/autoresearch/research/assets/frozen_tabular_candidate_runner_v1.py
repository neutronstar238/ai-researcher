"""Frozen, network-free evaluator for Task 263.5 tabular candidates.

This file is intentionally standalone.  The development-search controller
copies it into a content-addressed execution directory and launches it with the
clean Task 263.4.2 interpreter.  It accepts only a small declarative learner
grammar; generated Python and dynamic imports are not part of the protocol.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.base import BaseEstimator
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import balanced_accuracy_score, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, RobustScaler, StandardScaler
from xgboost import XGBClassifier, XGBRegressor

RUNNER_SCHEMA_VERSION = "frozen-tabular-candidate-runner-v1"
CONFIG_SCHEMA_VERSION = "tabular-candidate-execution-v1"
RESULT_SCHEMA_VERSION = "tabular-candidate-result-v1"
ALLOWED_STAGES = {"F1", "F2", "F3"}
ALLOWED_FAMILIES = {"tabular_classification", "tabular_regression"}
ALLOWED_LEARNERS = {
    "dummy",
    "linear",
    "lgbm",
    "xgboost",
    "rf",
    "extra_tree",
    "hist_gb",
    "lgbm_xgboost_ensemble",
    "invalid_probe",
}
ALLOWED_PREPROCESSING = {"none", "impute", "standardize", "robust"}
ALLOWED_HYPERPARAMETERS = {
    "n_estimators",
    "num_leaves",
    "max_depth",
    "max_iter",
    "max_leaf_nodes",
    "alpha",
    "C",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _peak_rss_mb() -> float:
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        process = get_current_process()
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        ok = get_process_memory_info(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        if ok:
            return float(counters.PeakWorkingSetSize) / (1024.0 * 1024.0)
        return 0.0
    try:
        import resource

        peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            return peak / (1024.0 * 1024.0)
        return peak / 1024.0
    except (ImportError, OSError):
        return 0.0


def _require_config(config: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "execution_id",
        "opaque_unit_id",
        "candidate_id",
        "candidate_hash",
        "family",
        "learner",
        "preprocessing",
        "hyperparameters",
        "stage",
        "training_fraction",
        "seed",
        "validation_fraction",
        "train_path",
        "test_path",
        "labels_path",
        "train_sha256",
        "test_sha256",
        "labels_sha256",
        "maximum_memory_mb",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"missing config fields: {', '.join(missing)}")
    if config["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise ValueError("unsupported execution config schema")
    if config["family"] not in ALLOWED_FAMILIES:
        raise ValueError("unsupported task family")
    if config["learner"] not in ALLOWED_LEARNERS:
        raise ValueError("unsupported learner")
    if config["preprocessing"] not in ALLOWED_PREPROCESSING:
        raise ValueError("unsupported preprocessing decision")
    if config["stage"] not in ALLOWED_STAGES:
        raise ValueError("unsupported fidelity stage")
    if not isinstance(config["hyperparameters"], dict):
        raise ValueError("hyperparameters must be an object")
    if len(config["hyperparameters"]) > 2:
        raise ValueError("candidate grammar permits at most two hyperparameters")
    unknown = sorted(set(config["hyperparameters"]) - ALLOWED_HYPERPARAMETERS)
    if unknown:
        raise ValueError(f"unsupported hyperparameters: {', '.join(unknown)}")
    fraction = float(config["training_fraction"])
    if not 0 < fraction <= 1:
        raise ValueError("training_fraction must be in (0, 1]")
    validation_fraction = float(config["validation_fraction"])
    if not 0 < validation_fraction < 0.5:
        raise ValueError("validation_fraction must be in (0, 0.5)")
    if int(config["maximum_memory_mb"]) <= 0:
        raise ValueError("maximum_memory_mb must be positive")
    if config["learner"] == "invalid_probe":
        raise ValueError("intentional unsupported-learner control reached execution")


def _subsample_indices(
    labels: np.ndarray,
    *,
    family: str,
    fraction: float,
    seed: int,
) -> np.ndarray:
    row_count = len(labels)
    requested = max(2, min(row_count, int(math.ceil(row_count * fraction))))
    all_indices = np.arange(row_count)
    if requested >= row_count:
        return all_indices
    stratify = labels if family == "tabular_classification" else None
    selected, _ = train_test_split(
        all_indices,
        train_size=requested,
        random_state=seed,
        shuffle=True,
        stratify=stratify,
    )
    return np.sort(selected)


def _preprocessor(kind: str) -> list[tuple[str, Any]]:
    if kind == "none":
        return []
    steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if kind == "standardize":
        steps.append(("scaler", StandardScaler()))
    elif kind == "robust":
        steps.append(("scaler", RobustScaler()))
    return steps


def _learner(
    learner: str,
    *,
    family: str,
    seed: int,
    hyperparameters: dict[str, Any],
) -> BaseEstimator | tuple[BaseEstimator, BaseEstimator]:
    classification = family == "tabular_classification"
    params = dict(hyperparameters)
    if learner == "dummy":
        return DummyClassifier(strategy="prior") if classification else DummyRegressor()
    if learner == "linear":
        if classification:
            return LogisticRegression(
                C=float(params.get("C", 1.0)),
                max_iter=int(params.get("max_iter", 250)),
                random_state=seed,
                n_jobs=1,
            )
        return Ridge(alpha=float(params.get("alpha", 1.0)))
    if learner == "lgbm":
        common = {
            "n_estimators": int(params.get("n_estimators", 48)),
            "num_leaves": int(params.get("num_leaves", 31)),
            "random_state": seed,
            "n_jobs": 1,
            "verbosity": -1,
            "deterministic": True,
            "force_col_wise": True,
        }
        return LGBMClassifier(**common) if classification else LGBMRegressor(**common)
    if learner == "xgboost":
        common = {
            "n_estimators": int(params.get("n_estimators", 48)),
            "max_depth": int(params.get("max_depth", 4)),
            "learning_rate": 0.08,
            "random_state": seed,
            "n_jobs": 1,
            "tree_method": "hist",
            "verbosity": 0,
        }
        return XGBClassifier(**common) if classification else XGBRegressor(**common)
    if learner == "rf":
        common = {
            "n_estimators": int(params.get("n_estimators", 48)),
            "max_depth": int(params.get("max_depth", 14)),
            "random_state": seed,
            "n_jobs": 1,
        }
        return RandomForestClassifier(**common) if classification else RandomForestRegressor(**common)
    if learner == "extra_tree":
        common = {
            "n_estimators": int(params.get("n_estimators", 48)),
            "max_depth": int(params.get("max_depth", 16)),
            "random_state": seed,
            "n_jobs": 1,
        }
        return ExtraTreesClassifier(**common) if classification else ExtraTreesRegressor(**common)
    if learner == "hist_gb":
        common = {
            "max_iter": int(params.get("max_iter", 64)),
            "max_leaf_nodes": int(params.get("max_leaf_nodes", 31)),
            "random_state": seed,
        }
        return (
            HistGradientBoostingClassifier(**common)
            if classification
            else HistGradientBoostingRegressor(**common)
        )
    if learner == "lgbm_xgboost_ensemble":
        first = _learner(
            "lgbm",
            family=family,
            seed=seed,
            hyperparameters={"n_estimators": int(params.get("n_estimators", 40))},
        )
        second = _learner(
            "xgboost",
            family=family,
            seed=seed,
            hyperparameters={
                "n_estimators": int(params.get("n_estimators", 40)),
                "max_depth": int(params.get("max_depth", 4)),
            },
        )
        if not isinstance(first, BaseEstimator) or not isinstance(second, BaseEstimator):
            raise TypeError("nested ensemble learner returned an invalid estimator")
        return first, second
    raise ValueError("learner was not handled")


def _wrap_preprocessing(estimator: BaseEstimator, kind: str) -> BaseEstimator:
    steps = _preprocessor(kind)
    if not steps:
        return estimator
    return Pipeline([*steps, ("model", estimator)])


def _fit_predict(
    config: dict[str, Any],
    x_fit: pd.DataFrame,
    y_fit: np.ndarray,
    x_eval: pd.DataFrame,
) -> np.ndarray:
    estimator = _learner(
        config["learner"],
        family=config["family"],
        seed=int(config["seed"]),
        hyperparameters=config["hyperparameters"],
    )
    preprocessing = str(config["preprocessing"])
    if isinstance(estimator, tuple):
        predictions: list[np.ndarray] = []
        probabilities: list[np.ndarray] = []
        for member in estimator:
            fitted = _wrap_preprocessing(member, preprocessing)
            fitted.fit(x_fit, y_fit)
            if config["family"] == "tabular_classification" and hasattr(
                fitted, "predict_proba"
            ):
                probabilities.append(np.asarray(fitted.predict_proba(x_eval), dtype=float))
            else:
                predictions.append(np.asarray(fitted.predict(x_eval), dtype=float))
        if probabilities:
            mean_probability = np.mean(np.stack(probabilities, axis=0), axis=0)
            return np.argmax(mean_probability, axis=1)
        return np.mean(np.stack(predictions, axis=0), axis=0)
    fitted = _wrap_preprocessing(estimator, preprocessing)
    fitted.fit(x_fit, y_fit)
    return np.asarray(fitted.predict(x_eval))


def _run(config: dict[str, Any]) -> dict[str, Any]:
    _require_config(config)
    train_path = Path(str(config["train_path"])).resolve()
    test_path = Path(str(config["test_path"])).resolve()
    labels_path = Path(str(config["labels_path"])).resolve()
    if _file_sha256(train_path) != config["train_sha256"]:
        raise ValueError("train input hash mismatch")
    if _file_sha256(test_path) != config["test_sha256"]:
        raise ValueError("test input hash mismatch")
    if _file_sha256(labels_path) != config["labels_sha256"]:
        raise ValueError("development labels file hash mismatch")

    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)
    labels_payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(labels_payload, dict):
        raise ValueError("development labels artifact is not an object")
    expected_label_hash = labels_payload.get("label_hash")
    label_body = dict(labels_payload)
    label_body.pop("label_hash", None)
    if (
        not isinstance(expected_label_hash, str)
        or _sha256_value(label_body) != expected_label_hash
    ):
        raise ValueError("development labels content hash mismatch")
    if labels_payload.get("confirmatory_source") is not False:
        raise ValueError("candidate runner refuses confirmatory labels")
    if labels_payload.get("opaque_unit_id") != config["opaque_unit_id"]:
        raise ValueError("development labels bind a different opaque unit")
    if "target" not in train or "row_id" not in test:
        raise ValueError("frozen input is missing target or row ID")
    feature_columns = [column for column in train.columns if column != "target"]
    if feature_columns != [column for column in test.columns if column != "row_id"]:
        raise ValueError("train/test feature columns differ")
    x_all = train.loc[:, feature_columns]
    x_test = test.loc[:, feature_columns]
    y_all_raw = train["target"].to_numpy()
    observed_row_ids = [int(value) for value in test["row_id"].to_list()]
    expected_row_ids = [int(value) for value in labels_payload.get("row_ids", [])]
    if observed_row_ids != expected_row_ids:
        raise ValueError("development labels/test row IDs differ")
    raw_labels = labels_payload.get("labels")
    if not isinstance(raw_labels, list) or len(raw_labels) != len(test):
        raise ValueError("development label count mismatch")
    y_test_raw = np.asarray(raw_labels)

    if config["family"] == "tabular_classification":
        encoder = LabelEncoder()
        encoder.fit(np.concatenate([y_all_raw, y_test_raw]))
        y_all = encoder.transform(y_all_raw)
        y_test = encoder.transform(y_test_raw)
        stratify = y_all
    else:
        y_all = np.asarray(y_all_raw, dtype=float)
        y_test = np.asarray(y_test_raw, dtype=float)
        stratify = None

    if config["stage"] == "F3":
        x_fit = x_all
        y_fit = y_all
        x_eval = x_test
        y_eval = y_test
        evaluation_split = "development_test"
    else:
        fit_indices, eval_indices = train_test_split(
            np.arange(len(y_all)),
            test_size=float(config["validation_fraction"]),
            random_state=int(config["seed"]),
            shuffle=True,
            stratify=stratify,
        )
        selected_local = _subsample_indices(
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

    predictions = _fit_predict(config, x_fit, y_fit, x_eval)
    if len(predictions) != len(y_eval):
        raise ValueError("prediction count mismatch")
    if not np.all(np.isfinite(np.asarray(predictions, dtype=float))):
        raise ValueError("predictions contain non-finite values")
    if config["family"] == "tabular_classification":
        score = float(balanced_accuracy_score(y_eval, predictions))
        metric_id = "balanced_accuracy"
        serialized_predictions: list[int | float] = [
            int(value) for value in np.asarray(predictions)
        ]
    else:
        score = float(r2_score(y_eval, predictions))
        metric_id = "r2"
        serialized_predictions = [
            float(value) for value in np.asarray(predictions, dtype=float)
        ]
    if not math.isfinite(score):
        raise ValueError("objective score is non-finite")

    peak_rss_mb = _peak_rss_mb()
    memory_valid = peak_rss_mb <= float(config["maximum_memory_mb"])
    payload: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
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
        "prediction_sha256": _sha256_value(serialized_predictions),
        "train_sha256": config["train_sha256"],
        "test_sha256": config["test_sha256"],
        "labels_sha256": config["labels_sha256"],
        "seed": int(config["seed"]),
        "training_fraction": float(config["training_fraction"]),
        "cpu_seconds": max(0.0, time.process_time() - cpu_started),
        "wall_seconds": max(0.0, time.perf_counter() - wall_started),
        "peak_rss_mb": peak_rss_mb,
        "maximum_memory_mb": int(config["maximum_memory_mb"]),
        "memory_valid": memory_valid,
        "network_allowed": False,
    }
    payload["result_hash"] = _sha256_value(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("execution config must be a JSON object")
    result = _run(config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
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
    temporary.replace(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
