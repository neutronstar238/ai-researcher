from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.scientific_contract_harness import (
    ScientificContractHarnessError,
    ScientificContractHarnessObservation,
    ScientificContractRuntimeEnvironment,
    build_scientific_contract_harness_package,
    load_scientific_contract_harness_package,
    review_scientific_contract_source,
)
from autoresearch.competition.scientific_contract_recovery import (
    load_scientific_contract_recovery_plan,
)
from autoresearch.competition.sentinel_identifiability import (
    load_corrected_sentinel_fixtures,
    load_sentinel_identifiability_erratum,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.schemas import file_hash

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = (
    ROOT
    / "runs"
    / "manual-live"
    / "task2661-scientific-contract-recovery-plan-v1"
    / "scientific-contract-recovery-plan.json"
)
ERRATUM_PATH = (
    ROOT
    / "runs"
    / "manual-live"
    / "task26611-sentinel-identifiability-erratum-v1"
    / "sentinel-identifiability-erratum.json"
)
RUNNER_PATH = (
    ROOT
    / "deploy"
    / "experiments"
    / "mdbench"
    / "scientific_contract_harness_runner.py"
)

GENERAL_SPARSE_CANDIDATE = '''"""General train-dependent sparse equation discovery test fixture."""
import itertools
import numpy as np

AXIS_NAMES = ("x", "y", "z")


def _array(tensor):
    return np.asarray(tensor["values"], dtype=float).reshape(tuple(tensor["shape"]))


def _tensor(values):
    values = np.asarray(values, dtype=float)
    return {"shape": list(values.shape), "values": values.reshape(-1).tolist()}


def _spectral(values, coordinates, axis):
    coordinates = np.asarray(coordinates, dtype=float)
    count = coordinates.size - 1
    period = coordinates[-1] - coordinates[0]
    core = np.take(values, np.arange(count), axis=axis)
    frequencies = 2.0 * np.pi * np.fft.fftfreq(count, d=period / count)
    shape = [1] * core.ndim
    shape[axis] = count
    transformed = np.fft.fft(core, axis=axis)
    result = np.fft.ifft(1j * frequencies.reshape(shape) * transformed, axis=axis).real
    return np.concatenate([result, np.take(result, [0], axis=axis)], axis=axis)


def _features(state, field_names, coordinates):
    axes = [name for name in AXIS_NAMES if name in coordinates]
    values = []
    supports = []
    for field_index, field in enumerate(field_names):
        raw = state[..., field_index]
        values.append(raw.reshape(-1))
        supports.append((field, ()))
        for axis_index, axis_name in enumerate(axes):
            first = _spectral(raw, coordinates[axis_name], axis_index)
            second = _spectral(first, coordinates[axis_name], axis_index)
            values.extend((first.reshape(-1), second.reshape(-1)))
            supports.extend(((field, (axis_name,)), (field, (axis_name, axis_name))))
    return np.column_stack(values), supports


def _sparse_fit(design, target):
    target_power = max(float(np.sum(target * target)), 1e-30)
    best = None
    best_nmse = float("inf")
    maximum_terms = min(3, design.shape[1])
    for term_count in range(1, maximum_terms + 1):
        exact = []
        for indices in itertools.combinations(range(design.shape[1]), term_count):
            matrix = design[:, indices]
            coefficients = np.linalg.lstsq(matrix, target, rcond=None)[0]
            residual = target - matrix @ coefficients
            nmse = float(np.sum(residual * residual)) / target_power
            if nmse < best_nmse:
                best_nmse = nmse
                best = (indices, coefficients)
            if nmse <= 1e-20:
                exact.append((nmse, indices, coefficients))
        if exact:
            exact.sort(key=_first)
            return exact[0][1], exact[0][2]
    return best


def _first(item):
    return item[0]


def fit_equations(payload):
    state = _array(payload["train_state"])
    derivative = _array(payload["train_derivative"])
    field_names = list(payload["field_names"])
    design, supports = _features(state, field_names, payload["spatial_coordinates"])
    equations = []
    for field_index, field in enumerate(field_names):
        indices, coefficients = _sparse_fit(design, derivative[..., field_index].reshape(-1))
        terms = []
        for feature_index, coefficient in zip(indices, coefficients):
            feature_field, axes = supports[feature_index]
            terms.append(
                {
                    "coefficient": float(coefficient),
                    "factors": [
                        {
                            "field": feature_field,
                            "derivative_axes": list(axes),
                            "power": 1,
                        }
                    ],
                }
            )
        equations.append({"target": field + "_t", "intercept": 0.0, "terms": terms})
    scaling = [
        {
            "field": field,
            "state_offset": 0.0,
            "state_scale": 1.0,
            "derivative_offset": 0.0,
            "derivative_scale": 1.0,
        }
        for field in field_names
    ]
    return {
        "equations": equations,
        "equation_coordinate_system": "physical-unscaled-v1",
        "field_scaling": scaling,
        "diagnostics": {
            "solver_id": "general-exhaustive-sparse-linear-v1",
            "design_feature_count": int(design.shape[1]),
            "warnings": [],
        },
    }


def _evaluate(artifact, state, coordinates):
    field_names = list(artifact["field_names"])
    axes = [name for name in AXIS_NAMES if name in coordinates]
    field_index = {field: index for index, field in enumerate(field_names)}
    outputs = []
    for equation in artifact["equations"]:
        value = np.full(state.shape[:-1], float(equation["intercept"]), dtype=float)
        for term in equation["terms"]:
            product = np.ones(state.shape[:-1], dtype=float)
            for factor in term["factors"]:
                factor_value = state[..., field_index[factor["field"]]]
                for axis_name in factor["derivative_axes"]:
                    factor_value = _spectral(
                        factor_value,
                        coordinates[axis_name],
                        axes.index(axis_name),
                    )
                product = product * factor_value ** int(factor["power"])
            value = value + float(term["coefficient"]) * product
        outputs.append(value)
    return np.stack(outputs, axis=-1)


def predict_derivative(payload):
    artifact = payload["artifact"]
    prediction = _evaluate(
        artifact,
        _array(payload["state"]),
        payload["spatial_coordinates"],
    )
    return {
        "schema_version": "scientific-predict-response-v1",
        "query_id": payload["query_id"],
        "artifact_hash": artifact["artifact_hash"],
        "derivative_prediction": _tensor(prediction),
        "fit_calls_during_prediction": 0,
        "artifact_mutation_count": 0,
        "equation_evaluator_id": "trusted-equation-evaluator-v1",
    }
'''


def test_exact_runner_recovers_all_corrected_known_laws(tmp_path: Path) -> None:
    plan = load_scientific_contract_recovery_plan(PLAN_PATH)
    erratum = load_sentinel_identifiability_erratum(ERRATUM_PATH)
    fixtures = load_corrected_sentinel_fixtures(ERRATUM_PATH)
    review = review_scientific_contract_source(GENERAL_SPARSE_CANDIDATE)
    assert review.approved, review.findings
    candidate_path = tmp_path / "candidate.py"
    candidate_path.write_text(GENERAL_SPARSE_CANDIDATE, encoding="utf-8")
    request = {
        "schema_version": "scientific-contract-harness-input-v1",
        "expected_runner_sha256": file_hash(RUNNER_PATH),
        "candidate_source_sha256": file_hash(candidate_path),
        "plan_hash": plan.plan_hash,
        "erratum_hash": erratum.erratum_hash,
        "corrected_sentinel_registry_hash": erratum.corrected_sentinel_registry_hash,
        "contract_gate": plan.contract_gate.model_dump(mode="json"),
        "fixtures": [item.model_dump(mode="json") for item in fixtures],
    }
    completed = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--candidate", str(candidate_path)],
        input=json.dumps(request, allow_nan=False, sort_keys=True),
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    observation = ScientificContractHarnessObservation.model_validate_json(
        completed.stdout
    )
    assert observation.passed
    assert observation.passed_sentinel_count == 6
    assert observation.fit_call_count == 18
    assert observation.predict_call_count == 36
    assert all(item["primary_term_support_f1"] == 1.0 for item in observation.sentinel_results)
    assert all(item["primary_prediction_nmse"] <= 1e-6 for item in observation.sentinel_results)
    assert all(all(item["checks"].values()) for item in observation.sentinel_results)


def test_runner_serializes_unbounded_scientific_metrics_as_failures(
    tmp_path: Path,
) -> None:
    plan = load_scientific_contract_recovery_plan(PLAN_PATH)
    erratum = load_sentinel_identifiability_erratum(ERRATUM_PATH)
    fixtures = load_corrected_sentinel_fixtures(ERRATUM_PATH)
    candidate_source = GENERAL_SPARSE_CANDIDATE.replace(
        'equations.append({"target": field + "_t", "intercept": 0.0, "terms": terms})',
        'equations.append({"target": field + "_t", "intercept": 0.0, '
        '"terms": [{"coefficient": 1.0, "factors": [{"field": field, '
        '"derivative_axes": [], "power": 1}]}]})',
    )
    candidate_path = tmp_path / "missing-support-candidate.py"
    candidate_path.write_text(candidate_source, encoding="utf-8")
    request = {
        "schema_version": "scientific-contract-harness-input-v1",
        "expected_runner_sha256": file_hash(RUNNER_PATH),
        "candidate_source_sha256": file_hash(candidate_path),
        "plan_hash": plan.plan_hash,
        "erratum_hash": erratum.erratum_hash,
        "corrected_sentinel_registry_hash": erratum.corrected_sentinel_registry_hash,
        "contract_gate": plan.contract_gate.model_dump(mode="json"),
        "fixtures": [item.model_dump(mode="json") for item in fixtures],
    }
    completed = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--candidate", str(candidate_path)],
        input=json.dumps(request, allow_nan=False, sort_keys=True),
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "Infinity" not in completed.stdout
    observation = ScientificContractHarnessObservation.model_validate_json(
        completed.stdout
    )
    assert not observation.passed
    unbounded_results = [
        item
        for item in observation.sentinel_results
        if item.get("primary_coefficient_relative_error") is None
    ]
    assert len(unbounded_results) == 5
    for item in unbounded_results:
        assert item["primary_coefficient_relative_error"] is None
        assert "primary_coefficient_relative_error" in item["nonfinite_metrics"]
        assert (
            "nonfinite_metric:primary_coefficient_relative_error"
            in item["failure_codes"]
        )


def test_runner_rejects_tampered_fixture_and_static_review_blocks_leakage(
    tmp_path: Path,
) -> None:
    plan = load_scientific_contract_recovery_plan(PLAN_PATH)
    erratum = load_sentinel_identifiability_erratum(ERRATUM_PATH)
    fixtures = [item.model_dump(mode="json") for item in load_corrected_sentinel_fixtures(ERRATUM_PATH)]
    fixtures[0]["train_state"]["values"][0] += 1.0
    candidate_path = tmp_path / "candidate.py"
    candidate_path.write_text(GENERAL_SPARSE_CANDIDATE, encoding="utf-8")
    request = {
        "schema_version": "scientific-contract-harness-input-v1",
        "expected_runner_sha256": file_hash(RUNNER_PATH),
        "candidate_source_sha256": file_hash(candidate_path),
        "plan_hash": plan.plan_hash,
        "erratum_hash": erratum.erratum_hash,
        "corrected_sentinel_registry_hash": erratum.corrected_sentinel_registry_hash,
        "contract_gate": plan.contract_gate.model_dump(mode="json"),
        "fixtures": fixtures,
    }
    completed = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--candidate", str(candidate_path)],
        input=json.dumps(request, allow_nan=False, sort_keys=True),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0
    assert "fixture hash changed" in completed.stderr

    leaking = GENERAL_SPARSE_CANDIDATE.replace(
        "def predict_derivative(payload):",
        'def predict_derivative(payload):\n    open("official_development.json")',
    )
    review = review_scientific_contract_source(leaking)
    assert not review.approved
    assert {item.code for item in review.findings} >= {
        "dynamic_execution",
        "frozen_target_marker",
    }


def test_runner_returns_candidate_owned_error_location_without_fixture_values(
    tmp_path: Path,
) -> None:
    plan = load_scientific_contract_recovery_plan(PLAN_PATH)
    erratum = load_sentinel_identifiability_erratum(ERRATUM_PATH)
    fixtures = load_corrected_sentinel_fixtures(ERRATUM_PATH)
    candidate_path = tmp_path / "candidate.py"
    candidate_path.write_text(
        "def fit_equations(payload):\n"
        "    state = payload['train_state']\n"
        "    return state.shape[1]\n\n"
        "def predict_derivative(payload):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    request = {
        "schema_version": "scientific-contract-harness-input-v1",
        "expected_runner_sha256": file_hash(RUNNER_PATH),
        "candidate_source_sha256": file_hash(candidate_path),
        "plan_hash": plan.plan_hash,
        "erratum_hash": erratum.erratum_hash,
        "corrected_sentinel_registry_hash": erratum.corrected_sentinel_registry_hash,
        "contract_gate": plan.contract_gate.model_dump(mode="json"),
        "fixtures": [item.model_dump(mode="json") for item in fixtures],
    }
    completed = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--candidate", str(candidate_path)],
        input=json.dumps(request, allow_nan=False, sort_keys=True),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observation = ScientificContractHarnessObservation.model_validate_json(
        completed.stdout
    )
    assert not observation.passed
    assert all(
        "candidate_location=candidate.py:3 in fit_equations: return state.shape[1]"
        in item["error_message"]
        for item in observation.sentinel_results
    )
    assert all(
        item["sentinel_id"] not in item["error_message"]
        for item in observation.sentinel_results
    )


def test_model_origin_package_is_replayable_and_authorizes_only_task_266_3(
    tmp_path: Path,
) -> None:
    completion = _FixtureCompletion(
        GENERAL_SPARSE_CANDIDATE,
        bad_first=True,
        patch_repair=True,
    )
    runtime = ScientificContractRuntimeEnvironment.create(
        image_id="sha256:6c8928e967cc4ff2995626c90ef57771df603028ddd6e17dbc60894ffa017c78"
    )
    output_dir = tmp_path / "package"
    package = build_scientific_contract_harness_package(
        PLAN_PATH,
        ERRATUM_PATH,
        output_dir,
        completion=completion,
        clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
        runtime_environment=runtime,
        harness_executor=_passing_executor,
    )
    assert package.synthetic_contract_gate_passed
    assert package.task_266_3_authorized
    assert package.next_required_task == "266.3"
    assert package.selected_source_sha256 == file_hash(
        output_dir / package.revisions[-1].source_relative_path
    )
    assert not package.revisions[0].static_review.approved
    assert (
        output_dir.joinpath(package.revisions[1].source_relative_path).read_text(
            encoding="utf-8"
        )
        == GENERAL_SPARSE_CANDIDATE
    )
    assert package.model_only_repair_count == 1
    assert completion.calls == 2
    assert package.official_development_result_count == 0
    assert package.confirmation_result_count == 0
    assert package.system_generated_manuscript_count == 0
    first_user_payload = json.loads(completion.requests[0]["messages"][1]["content"])
    repair_schema = completion.requests[1]["response_schema"]
    assert isinstance(repair_schema, dict)
    assert "oneOf" not in repair_schema
    assert repair_schema["properties"]["response_type"]["enum"] == [
        "scientific_contract_patch"
    ]
    interface = first_user_payload["interface_contract"]
    assert interface["source_transport_contract"] == {
        "entire_response_is_one_json_object": True,
        "hard_source_byte_count_maximum": 80_000,
        "hard_each_ophis_narrative_character_count_maximum": 8_000,
        "preferred_source_character_count_maximum": 12_000,
        "regenerate_whole_object_never_continue_a_prior_fragment": True,
        "response_first_character": "{",
        "response_last_character": "}",
        "source_field_name": "source_lines",
        "source_lines_contract": (
            "Emit source as a JSON array of strings named source_lines, with "
            "exactly one array element per physical line of Python. Do NOT emit "
            "a single source_text string and do NOT write newline escapes "
            "anywhere. The orchestrator joins your array elements with newlines "
            "to reconstruct the file byte-for-byte."
        ),
        "source_lines_example": [
            "import numpy as np",
            "",
            "",
            "def fit_equations(payload):",
            "    train_state = payload['train_state']",
            "    return {}",
        ],
        "source_lines_rules": {
            "one_element_per_line": True,
            "no_trailing_newline_inside_an_element": True,
            "preserve_leading_indentation_spaces_in_each_element": True,
            "empty_string_element_means_a_blank_line": True,
        },
        "repair_modes": {
            "orchestrator_role": "hash verification and deterministic replacement only",
            "patch_content_origin": "all old_text and new_text are model-authored",
            "patch_old_text_requirement": (
                "each old_text must match exactly once when applied in order"
            ),
            "required": (
                "scientific_contract_patch with parent_source_sha256 and 1..16 ordered "
                "exact old_text/new_text replacements"
            ),
            "whole_source_rewrite": (
                "one replacement whose old_text is the exact whole parent source and whose "
                "new_text is the complete model-authored replacement source"
            ),
        },
    }
    assert "classes" in interface["static_source_contract"]["forbidden_constructs"]
    assert "numpy" in interface["static_source_contract"]["allowed_import_roots"]
    assert interface["json_transport"]["tensor_bound_fields"] == [
        "fit.train_state",
        "fit.train_derivative",
        "predict.state",
        "predict_response.derivative_prediction",
    ]
    assert interface["json_transport"]["axis_layout"] == {
        "field_axis_index": -1,
        "ode": ["time", "field"],
        "pde": ["zero_to_three_spatial_axes_in_x_y_z_order", "time", "field"],
        "spatial_axis_indices_start_at": 0,
        "time_axis_index": -2,
        "train_state_and_train_derivative_have_identical_shape": True,
    }
    assert interface["json_transport"]["query_state_already_has_penultimate_time_axis"]
    assert not interface["fit_response_rules"]["candidate_returns_private_artifact"]
    assert (
        interface["fit_response_rules"]["equation_coordinate_system_exact_value"]
        == "physical-unscaled-v1"
    )
    assert interface["frozen_artifact_rules"]["prediction_must_evaluate_standard_equations"]
    assert interface["field_scaling"]["container"].startswith("list with exactly one")
    assert interface["equation"]["container"].startswith("list with exactly one")
    assert load_scientific_contract_harness_package(package.output_path) == package

    extra = output_dir / "unexpected.txt"
    extra.write_text("tamper", encoding="utf-8")
    with pytest.raises(ScientificContractHarnessError, match="file set changed"):
        load_scientific_contract_harness_package(package.output_path)


def test_model_authored_exact_patch_is_hash_bound_and_replayable(tmp_path: Path) -> None:
    completion = _FixtureCompletion(
        GENERAL_SPARSE_CANDIDATE,
        bad_first=True,
        patch_repair=True,
    )
    runtime = ScientificContractRuntimeEnvironment.create(
        image_id="sha256:6c8928e967cc4ff2995626c90ef57771df603028ddd6e17dbc60894ffa017c78"
    )
    output_dir = tmp_path / "patch-package"
    package = build_scientific_contract_harness_package(
        PLAN_PATH,
        ERRATUM_PATH,
        output_dir,
        completion=completion,
        clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
        runtime_environment=runtime,
        harness_executor=_passing_executor,
    )
    patched = package.revisions[1]
    assert package.synthetic_contract_gate_passed
    assert package.model_authored_patch_count == 1
    assert not patched.exact_model_source_unmodified
    assert patched.source_derivation is not None
    assert patched.source_derivation.parent_source_sha256 == package.revisions[0].source_sha256
    assert (
        output_dir.joinpath(patched.source_relative_path).read_text(encoding="utf-8")
        == GENERAL_SPARSE_CANDIDATE
    )
    assert load_scientific_contract_harness_package(package.output_path) == package


def test_model_authored_patch_preserves_redundant_noop_evidence(
    tmp_path: Path,
) -> None:
    completion = _FixtureCompletion(
        GENERAL_SPARSE_CANDIDATE,
        bad_first=True,
        patch_repair=True,
        redundant_noop_patch=True,
    )
    runtime = ScientificContractRuntimeEnvironment.create(
        image_id="sha256:6c8928e967cc4ff2995626c90ef57771df603028ddd6e17dbc60894ffa017c78"
    )
    output_dir = tmp_path / "redundant-noop-patch-package"
    package = build_scientific_contract_harness_package(
        PLAN_PATH,
        ERRATUM_PATH,
        output_dir,
        completion=completion,
        clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
        runtime_environment=runtime,
        harness_executor=_passing_executor,
    )
    patched = package.revisions[1]
    assert package.synthetic_contract_gate_passed
    assert patched.source_derivation is not None
    assert patched.source_derivation.replacement_count == 2
    assert len(patched.ophis_response.replacements) == 2
    assert (
        patched.ophis_response.replacements[1].old_text
        == patched.ophis_response.replacements[1].new_text
    )
    assert all(
        item.old_text_required is True
        for item in patched.ophis_response.replacements
    )
    assert load_scientific_contract_harness_package(package.output_path) == package


def test_model_authored_patch_rejects_entirely_unchanged_source(
    tmp_path: Path,
) -> None:
    completion = _FixtureCompletion(
        GENERAL_SPARSE_CANDIDATE,
        bad_first=True,
        patch_repair=True,
        noop_only_patch=True,
    )
    runtime = ScientificContractRuntimeEnvironment.create(
        image_id="sha256:6c8928e967cc4ff2995626c90ef57771df603028ddd6e17dbc60894ffa017c78"
    )
    with pytest.raises(ScientificContractHarnessError, match="left source unchanged"):
        build_scientific_contract_harness_package(
            PLAN_PATH,
            ERRATUM_PATH,
            tmp_path / "noop-only-patch-package",
            completion=completion,
            clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
            runtime_environment=runtime,
            harness_executor=_passing_executor,
        )


class _FixtureCompletion:
    def __init__(
        self,
        source: str,
        *,
        bad_first: bool = False,
        patch_repair: bool = False,
        redundant_noop_patch: bool = False,
        noop_only_patch: bool = False,
    ) -> None:
        self.source = source
        self.bad_first = bad_first
        self.patch_repair = patch_repair
        self.redundant_noop_patch = redundant_noop_patch
        self.noop_only_patch = noop_only_patch
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> LLMJsonCompletionResult:
        self.calls += 1
        self.requests.append(dict(kwargs))
        parent_source = "import os\n" + self.source
        payload: dict[str, Any] = {
            "response_type": "scientific_contract_source",
            "observation": "Training arrays and a strict fit/freeze/query contract are available.",
            "problem": "Recover sparse physical-unit laws without query targets or stored state.",
            "hypothesis": "A train-dependent sparse search can identify reusable concrete laws.",
            "intervention": "Fit candidate terms once and evaluate only frozen equations later.",
            "expected_effect": "Known laws and alternate coefficients will be recovered consistently.",
            "implementation_summary": "General sparse train-only equation discovery with frozen evaluation.",
            "source_lines": (
                ("import os\n" + self.source)
                if self.bad_first and self.calls == 1
                else self.source
            ).split("\n"),
        }
        if self.patch_repair and self.calls == 2:
            replacements = [
                {
                    "old_text": "import os\n",
                    "new_text": "import os\n" if self.noop_only_patch else "",
                    **(
                        {"old_text_required": True}
                        if self.redundant_noop_patch
                        else {}
                    ),
                }
            ]
            if self.redundant_noop_patch:
                replacements.append(
                    {
                        "old_text": "import itertools\n",
                        "new_text": "import itertools\n",
                        "old_text_required": True,
                    }
                )
            payload = {
                "response_type": "scientific_contract_patch",
                "observation": "Static review rejects one unnecessary import in the parent source.",
                "problem": "The forbidden import prevents evaluation of otherwise valid code.",
                "hypothesis": "Removing only that import preserves the scientific implementation.",
                "intervention": "Delete the exact unique import line with a hash-bound patch.",
                "expected_effect": "Static review should pass without changing scientific behavior.",
                "implementation_summary": "Model-authored exact deletion of one forbidden import.",
                "parent_source_sha256": hashlib.sha256(
                    parent_source.encode("utf-8")
                ).hexdigest(),
                "replacements": replacements,
            }
        response_text = json.dumps(payload, sort_keys=True)
        return LLMJsonCompletionResult(
            provider="fixture-openai-compatible",
            base_url="https://provider.example/v1",
            model_name="fixture-scientist",
            endpoint="https://provider.example/v1/chat/completions",
            response_text=response_text,
            parsed_json=payload,
            usage={"prompt_tokens": 100, "completion_tokens": 100},
            temperature=float(kwargs["temperature"]),
        )


def _passing_executor(**kwargs: Any) -> ScientificContractHarnessObservation:
    fixtures = kwargs["fixtures"]
    results = [
        {
            "sentinel_id": item.sentinel_id,
            "data_type": item.data_type,
            "spatial_dimensions": item.spatial_dimensions,
            "field_count": len(item.field_names),
            "query_shape": list(item.queries[0].state.shape),
            "failure_codes": [],
            "passed": True,
        }
        for item in fixtures
    ]
    payload = {
        "schema_version": "scientific-contract-harness-observation-v1",
        "plan_hash": kwargs["plan"].plan_hash,
        "erratum_hash": kwargs["erratum"].erratum_hash,
        "corrected_sentinel_registry_hash": (
            kwargs["erratum"].corrected_sentinel_registry_hash
        ),
        "candidate_source_sha256": file_hash(kwargs["candidate_path"]),
        "runner_sha256": file_hash(kwargs["runner_path"]),
        "network_used": False,
        "official_development_artifact_reads": 0,
        "confirmation_identity_reads": 0,
        "confirmation_result_reads": 0,
        "sentinel_results": results,
        "sentinel_count": 6,
        "passed_sentinel_count": 6,
        "fit_call_count": 18,
        "predict_call_count": 36,
        "passed": True,
    }
    payload["observation_hash"] = canonical_model_hash(payload)
    return ScientificContractHarnessObservation.model_validate(payload)
