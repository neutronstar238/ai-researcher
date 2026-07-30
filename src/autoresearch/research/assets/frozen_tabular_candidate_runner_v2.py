"""Mixed-type compatibility layer for the frozen Task 263.5 candidate runner.

The v1 runner remains immutable because it is bound to the diagnostic first
matrix. This module verifies that dependency before replacing only the feature
preprocessor. Candidate definitions, learners, metrics, splits, resource
accounting, prediction replay, and the command-line contract remain v1.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.compose import ColumnTransformer, make_column_selector
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler, StandardScaler

try:
    from . import frozen_tabular_candidate_runner_v1 as _legacy
except ImportError:  # pragma: no cover - exercised by the clean subprocess
    import frozen_tabular_candidate_runner_v1 as _legacy

RUNNER_SCHEMA_VERSION = "frozen-tabular-candidate-runner-v2"
LEGACY_RUNNER_SHA256 = (
    "f7db15037f401be87b9428346802a14707f0d4036e452b3551d492e226cb303c"
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_legacy_path = Path(_legacy.__file__).resolve()
if _file_sha256(_legacy_path) != LEGACY_RUNNER_SHA256:
    raise RuntimeError("frozen v1 runner dependency hash mismatch")


def _wrap_preprocessing(estimator: BaseEstimator, kind: str) -> BaseEstimator:
    if kind == "none":
        return estimator

    numeric_steps: list[tuple[str, Any]] = [
        ("imputer", SimpleImputer(strategy="median"))
    ]
    if kind == "standardize":
        numeric_steps.append(("scaler", StandardScaler()))
    elif kind == "robust":
        numeric_steps.append(("scaler", RobustScaler()))

    numeric_pipeline = Pipeline(numeric_steps)
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "one_hot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
            ),
        ]
    )
    mixed_type_preprocessor = ColumnTransformer(
        [
            (
                "numeric",
                numeric_pipeline,
                make_column_selector(dtype_include=np.number),
            ),
            (
                "categorical",
                categorical_pipeline,
                make_column_selector(dtype_exclude=np.number),
            ),
        ],
        remainder="drop",
        sparse_threshold=0.0,
        verbose_feature_names_out=False,
    )
    return Pipeline(
        [
            ("mixed_type_preprocessor", mixed_type_preprocessor),
            ("model", estimator),
        ]
    )


_legacy.RUNNER_SCHEMA_VERSION = RUNNER_SCHEMA_VERSION
_legacy._wrap_preprocessing = _wrap_preprocessing
_fit_predict = _legacy._fit_predict


def main() -> int:
    return _legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
