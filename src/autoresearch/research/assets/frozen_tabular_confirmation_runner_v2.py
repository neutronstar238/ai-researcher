"""Result-blind v2 confirmation evaluator with canonical label semantics.

This standalone runner repairs only the evaluator boundary exposed by the
first Task 263.6 endpoint.  The scientific learner implementation remains the
hash-pinned Task 263.5 mixed-type runner.  Classification targets are treated
as lexical tokens across CSV and JSON, non-F3 stages cannot receive a label
path, and every failure is assigned to an explicit input, candidate, or
evaluator domain.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import time
from pathlib import Path
from typing import Any, Literal, NoReturn

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]
from sklearn.preprocessing import LabelEncoder  # type: ignore[import-not-found]

try:
    from . import frozen_tabular_candidate_runner_v2 as _development
except ImportError:  # pragma: no cover - exercised by clean subprocesses
    _development = importlib.import_module("frozen_tabular_candidate_runner_v2")

RUNNER_SCHEMA_VERSION = "frozen-tabular-confirmation-runner-v2"
RESULT_SCHEMA_VERSION = "tabular-confirmation-candidate-result-v2"
CONFIG_SCHEMA_VERSION = "tabular-candidate-execution-v1"
LABEL_SCHEMA_VERSION = "confirmatory-labels-v1"
LABEL_TOKEN_CONTRACT = "canonical-string-label-v2"
REGRESSION_LABEL_CONTRACT = "finite-float-label-v1"
DEVELOPMENT_RUNNER_V2_SHA256 = (
    "6bffee04762d864a8719b650da105e917d825a5e9fc3cbbcb5876637d2e67126"
)
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
FailureDomain = Literal["input", "candidate", "evaluator"]


class RunnerFailure(Exception):
    """Sanitized structured failure that is safe to retain in result artifacts."""

    def __init__(self, domain: FailureDomain, code: str, error_type: str) -> None:
        super().__init__(code)
        self.domain = domain
        self.code = code
        self.error_type = error_type


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


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(
    domain: FailureDomain,
    code: str,
    error: BaseException | str,
) -> NoReturn:
    error_type = error if isinstance(error, str) else type(error).__name__
    raise RunnerFailure(domain, code, error_type)


def _require_config(config: dict[str, Any]) -> tuple[Path, Path, Path | None]:
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
        "train_sha256",
        "test_sha256",
        "maximum_memory_mb",
        "allowed_root",
        "confirmation_freeze_hash",
        "reveal_hash",
    }
    missing = sorted(required - set(config))
    if missing:
        _fail("input", "config_missing_fields", "ValueError")
    if config["schema_version"] != CONFIG_SCHEMA_VERSION:
        _fail("input", "config_schema_unsupported", "ValueError")
    if config["family"] not in ALLOWED_FAMILIES:
        _fail("input", "task_family_unsupported", "ValueError")
    if config["learner"] not in ALLOWED_LEARNERS:
        _fail("input", "learner_token_unsupported", "ValueError")
    if config["preprocessing"] not in ALLOWED_PREPROCESSING:
        _fail("input", "preprocessing_token_unsupported", "ValueError")
    if config["stage"] not in ALLOWED_STAGES:
        _fail("input", "fidelity_stage_unsupported", "ValueError")
    if not isinstance(config["hyperparameters"], dict):
        _fail("input", "hyperparameters_not_object", "ValueError")
    if len(config["hyperparameters"]) > 2:
        _fail("input", "hyperparameter_budget_exceeded", "ValueError")
    unknown = sorted(set(config["hyperparameters"]) - ALLOWED_HYPERPARAMETERS)
    if unknown:
        _fail("input", "hyperparameter_token_unsupported", "ValueError")
    if not 0 < float(config["training_fraction"]) <= 1:
        _fail("input", "training_fraction_invalid", "ValueError")
    if not 0 < float(config["validation_fraction"]) < 0.5:
        _fail("input", "validation_fraction_invalid", "ValueError")
    if int(config["maximum_memory_mb"]) <= 0:
        _fail("input", "memory_budget_invalid", "ValueError")
    if not all(
        _is_sha256(config.get(field))
        for field in (
            "candidate_hash",
            "train_sha256",
            "test_sha256",
            "confirmation_freeze_hash",
            "reveal_hash",
        )
    ):
        _fail("input", "content_hash_invalid", "ValueError")

    root = Path(str(config["allowed_root"])).resolve()
    if not root.is_dir():
        _fail("input", "allowed_root_missing", "ValueError")
    train_path = Path(str(config["train_path"])).resolve()
    test_path = Path(str(config["test_path"])).resolve()
    if not all(_within(path, root) for path in (train_path, test_path)):
        _fail("input", "input_path_escape", "ValueError")

    labels_path: Path | None = None
    if config["stage"] == "F3":
        if "labels_path" not in config or "labels_sha256" not in config:
            _fail("input", "f3_labels_binding_missing", "ValueError")
        if not _is_sha256(config["labels_sha256"]):
            _fail("input", "labels_hash_invalid", "ValueError")
        labels_path = Path(str(config["labels_path"])).resolve()
        if not _within(labels_path, root):
            _fail("input", "labels_path_escape", "ValueError")
    elif any(
        field in config and config[field] is not None
        for field in ("labels_path", "labels_sha256")
    ):
        _fail("input", "non_f3_labels_exposed", "ValueError")
    return train_path, test_path, labels_path


def _read_labels(
    path: Path,
    *,
    config: dict[str, Any],
    observed_row_ids: list[int],
) -> list[str] | list[float]:
    try:
        labels_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail("input", "labels_unreadable", exc)
    if not isinstance(labels_payload, dict):
        _fail("input", "labels_not_object", "ValueError")
    expected_hash = labels_payload.get("label_hash")
    body = dict(labels_payload)
    body.pop("label_hash", None)
    if not isinstance(expected_hash, str) or _canonical_sha256(body) != expected_hash:
        _fail("input", "labels_content_hash_mismatch", "ValueError")
    required_bindings = {
        "schema_version": LABEL_SCHEMA_VERSION,
        "partition": "confirmatory",
        "one_use_reveal": True,
        "opaque_unit_id": config["opaque_unit_id"],
        "confirmation_freeze_hash": config["confirmation_freeze_hash"],
        "reveal_hash": config["reveal_hash"],
    }
    if any(labels_payload.get(key) != value for key, value in required_bindings.items()):
        _fail("input", "labels_binding_mismatch", "ValueError")
    try:
        expected_row_ids = [int(value) for value in labels_payload.get("row_ids", [])]
    except (TypeError, ValueError) as exc:
        _fail("input", "labels_row_ids_invalid", exc)
    if observed_row_ids != expected_row_ids:
        _fail("input", "labels_row_alignment_mismatch", "ValueError")
    raw_labels = labels_payload.get("labels")
    if not isinstance(raw_labels, list) or len(raw_labels) != len(observed_row_ids):
        _fail("input", "labels_count_mismatch", "ValueError")
    if config["family"] == "tabular_classification":
        if not all(isinstance(value, str) for value in raw_labels):
            _fail("input", "classification_labels_not_strings", "TypeError")
        return [str(value) for value in raw_labels]
    try:
        labels = [float(value) for value in raw_labels]
    except (TypeError, ValueError) as exc:
        _fail("input", "regression_labels_not_numeric", exc)
    if not all(math.isfinite(value) for value in labels):
        _fail("input", "regression_labels_non_finite", "ValueError")
    return labels


def _failure_payload(
    config: dict[str, Any],
    *,
    failure: RunnerFailure,
    wall_started: float,
    cpu_started: float,
    labels_accessed: bool,
    train_sha256: str | None = None,
    test_sha256: str | None = None,
    labels_sha256: str | None = None,
    feature_count: int | None = None,
    fit_row_count: int | None = None,
    evaluation_row_count: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "development_runner_v2_sha256": DEVELOPMENT_RUNNER_V2_SHA256,
        "status": "failed",
        "failure_domain": failure.domain,
        "failure_code": failure.code,
        "failure_error_type": failure.error_type,
        "execution_id": str(config.get("execution_id", "unknown-execution")),
        "opaque_unit_id": str(config.get("opaque_unit_id", "unknown-unit")),
        "candidate_id": str(config.get("candidate_id", "unknown-candidate")),
        "candidate_hash": config.get("candidate_hash"),
        "stage": config.get("stage"),
        "family": config.get("family"),
        "metric_id": None,
        "score": None,
        "higher_is_better": True,
        "evaluation_split": None,
        "fit_row_count": fit_row_count,
        "evaluation_row_count": evaluation_row_count,
        "feature_count": feature_count,
        "prediction_count": 0,
        "prediction_sha256": None,
        "train_sha256": train_sha256,
        "test_sha256": test_sha256,
        "labels_sha256": labels_sha256,
        "labels_accessed": labels_accessed,
        "label_token_contract": (
            LABEL_TOKEN_CONTRACT
            if config.get("family") == "tabular_classification"
            else REGRESSION_LABEL_CONTRACT
        ),
        "confirmation_freeze_hash": config.get("confirmation_freeze_hash"),
        "reveal_hash": config.get("reveal_hash"),
        "seed": config.get("seed"),
        "training_fraction": config.get("training_fraction"),
        "cpu_seconds": max(0.0, time.process_time() - cpu_started),
        "wall_seconds": max(0.0, time.perf_counter() - wall_started),
        "peak_rss_mb": float(_development._legacy._peak_rss_mb()),
        "maximum_memory_mb": config.get("maximum_memory_mb"),
        "memory_valid": None,
        "network_allowed": False,
    }
    payload["result_hash"] = _canonical_sha256(payload)
    return payload


def _run(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    labels_accessed = False
    train_sha: str | None = None
    test_sha: str | None = None
    labels_sha: str | None = None
    feature_count: int | None = None
    fit_row_count: int | None = None
    evaluation_row_count: int | None = None
    try:
        train_path, test_path, labels_path = _require_config(config)
        try:
            train_sha = _file_sha256(train_path)
            test_sha = _file_sha256(test_path)
        except OSError as exc:
            _fail("input", "input_unreadable", exc)
        if train_sha != config["train_sha256"]:
            _fail("input", "train_hash_mismatch", "ValueError")
        if test_sha != config["test_sha256"]:
            _fail("input", "test_hash_mismatch", "ValueError")
        if labels_path is not None:
            labels_accessed = True
            try:
                labels_sha = _file_sha256(labels_path)
            except OSError as exc:
                _fail("input", "labels_unreadable", exc)
            if labels_sha != config["labels_sha256"]:
                _fail("input", "labels_file_hash_mismatch", "ValueError")

        try:
            if config["family"] == "tabular_classification":
                train = pd.read_csv(train_path, dtype={"target": "string"})
            else:
                train = pd.read_csv(train_path)
            test = pd.read_csv(test_path)
        except (OSError, UnicodeError, ValueError) as exc:
            _fail("input", "tabular_input_unreadable", exc)
        if "target" not in train or "row_id" not in test:
            _fail("input", "tabular_columns_missing", "ValueError")
        feature_columns = [column for column in train.columns if column != "target"]
        if not feature_columns:
            _fail("input", "feature_columns_empty", "ValueError")
        if feature_columns != [column for column in test.columns if column != "row_id"]:
            _fail("input", "feature_columns_mismatch", "ValueError")
        feature_count = len(feature_columns)
        x_all = train.loc[:, feature_columns]
        x_test = test.loc[:, feature_columns]
        try:
            observed_row_ids = [int(value) for value in test["row_id"].to_list()]
        except (TypeError, ValueError) as exc:
            _fail("input", "test_row_ids_invalid", exc)
        if observed_row_ids != sorted(observed_row_ids) or len(observed_row_ids) != len(
            set(observed_row_ids)
        ):
            _fail("input", "test_row_ids_not_unique_sorted", "ValueError")

        if config["family"] == "tabular_classification":
            raw_training = train["target"].to_list()
            if any(pd.isna(value) or not isinstance(value, str) for value in raw_training):
                _fail("input", "classification_train_labels_not_strings", "TypeError")
            training_tokens = [str(value) for value in raw_training]
            encoder = LabelEncoder()
            try:
                encoder.fit(training_tokens)
                y_all = encoder.transform(training_tokens)
            except (TypeError, ValueError) as exc:
                _fail("input", "classification_train_labels_invalid", exc)
            stratify: np.ndarray | None = y_all
        else:
            try:
                y_all = pd.to_numeric(train["target"], errors="raise").to_numpy(dtype=float)
            except (TypeError, ValueError) as exc:
                _fail("input", "regression_train_labels_not_numeric", exc)
            if not np.all(np.isfinite(y_all)):
                _fail("input", "regression_train_labels_non_finite", "ValueError")
            encoder = None
            stratify = None

        if config["stage"] == "F3":
            if labels_path is None:
                _fail("input", "f3_labels_binding_missing", "ValueError")
            raw_test_labels = _read_labels(
                labels_path,
                config=config,
                observed_row_ids=observed_row_ids,
            )
            if config["family"] == "tabular_classification":
                try:
                    y_eval = encoder.transform(raw_test_labels)
                except (TypeError, ValueError) as exc:
                    _fail("input", "classification_test_label_out_of_vocabulary", exc)
            else:
                y_eval = np.asarray(raw_test_labels, dtype=float)
            x_fit = x_all
            y_fit = y_all
            x_eval = x_test
            evaluation_split = "confirmatory_test"
        else:
            try:
                fit_indices, eval_indices = _development._legacy.train_test_split(
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
                    seed=int(config["seed"])
                    + (1 if config["stage"] == "F1" else 2),
                )
            except (TypeError, ValueError) as exc:
                _fail("input", "internal_split_invalid", exc)
            selected = np.sort(fit_indices[selected_local])
            ordered_eval = np.sort(eval_indices)
            x_fit = x_all.iloc[selected]
            y_fit = y_all[selected]
            x_eval = x_all.iloc[ordered_eval]
            y_eval = y_all[ordered_eval]
            evaluation_split = "internal_validation"
        fit_row_count = len(x_fit)
        evaluation_row_count = len(x_eval)

        if config["learner"] == "invalid_probe":
            _fail("candidate", "intentional_invalid_probe", "IntentionalInvalidProbe")
        try:
            predictions = _development._fit_predict(config, x_fit, y_fit, x_eval)
        except Exception as exc:  # noqa: BLE001 - failure domain is the contract
            _fail("candidate", "candidate_fit_or_predict_failure", exc)
        try:
            numeric_predictions = np.asarray(predictions, dtype=float)
            if len(predictions) != len(y_eval):
                _fail("evaluator", "prediction_count_mismatch", "ValueError")
            if not np.all(np.isfinite(numeric_predictions)):
                _fail("evaluator", "predictions_non_finite", "ValueError")
            if config["family"] == "tabular_classification":
                serialized_predictions: list[int | float] = [
                    int(value) for value in np.asarray(predictions)
                ]
                score = float(
                    _development._legacy.balanced_accuracy_score(
                        y_eval,
                        serialized_predictions,
                    )
                )
                metric_id = "balanced_accuracy"
            else:
                serialized_predictions = [
                    float(value) for value in numeric_predictions
                ]
                score = float(_development._legacy.r2_score(y_eval, predictions))
                metric_id = "r2"
            if not math.isfinite(score):
                _fail("evaluator", "objective_score_non_finite", "ValueError")
        except RunnerFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - failure domain is the contract
            _fail("evaluator", "objective_evaluation_failure", exc)

        peak_rss_mb = float(_development._legacy._peak_rss_mb())
        memory_valid = peak_rss_mb <= float(config["maximum_memory_mb"])
        payload: dict[str, Any] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "runner_schema_version": RUNNER_SCHEMA_VERSION,
            "development_runner_v2_sha256": DEVELOPMENT_RUNNER_V2_SHA256,
            "status": "succeeded",
            "failure_domain": None,
            "failure_code": None,
            "failure_error_type": None,
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
            "fit_row_count": fit_row_count,
            "evaluation_row_count": evaluation_row_count,
            "feature_count": feature_count,
            "prediction_count": len(serialized_predictions),
            "prediction_sha256": _canonical_sha256(serialized_predictions),
            "train_sha256": train_sha,
            "test_sha256": test_sha,
            "labels_sha256": labels_sha,
            "labels_accessed": labels_accessed,
            "label_token_contract": (
                LABEL_TOKEN_CONTRACT
                if config["family"] == "tabular_classification"
                else REGRESSION_LABEL_CONTRACT
            ),
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
        return payload, 0
    except RunnerFailure as failure:
        payload = _failure_payload(
            config,
            failure=failure,
            wall_started=wall_started,
            cpu_started=cpu_started,
            labels_accessed=labels_accessed,
            train_sha256=train_sha,
            test_sha256=test_sha,
            labels_sha256=labels_sha,
            feature_count=feature_count,
            fit_row_count=fit_row_count,
            evaluation_row_count=evaluation_row_count,
        )
        return payload, 0 if failure.domain == "candidate" else 2


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
    if not root.is_dir() or not _within(output_path, root):
        raise ValueError("confirmation output escaped its assigned workspace")
    result, return_code = _run(config)
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
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
