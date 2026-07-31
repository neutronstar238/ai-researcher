"""Result-blind identifiability erratum for the Task 266 analytic sentinels.

Task 266.1 froze the scientific contract before implementation.  A subsequent
pre-implementation rank audit found that the 2D fixture used only modes with
equal x/y wave numbers, making ``u_xx`` and ``u_yy`` identical.  This module
binds that immutable parent, replaces only the aliased synthetic stimulus, and
proves expected-support identifiability before any candidate or official score
exists.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.scientific_contract_recovery import (
    ScientificContractRecoveryPlan,
    ScientificSentinelFixture,
    SentinelQuery,
    TensorPayload,
    load_scientific_contract_recovery_plan,
)
from autoresearch.schemas import file_hash

_ERRATUM_NAME = "sentinel-identifiability-erratum.json"
_MARKDOWN_NAME = "sentinel-identifiability-erratum.md"
_PROBE_NAME = "identifiability-probe.json"
_MODIFIED_SENTINEL_ID = "pde-advection-diffusion-2d"
_IMAGE_NAME = "autoresearch-mdbench:task260"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PROBE_PATH = (
    _REPOSITORY_ROOT
    / "deploy"
    / "experiments"
    / "mdbench"
    / "sentinel_identifiability_probe.py"
)


class SentinelIdentifiabilityError(RuntimeError):
    """Raised when an erratum drifts, leaks, or fails the rank audit."""


class TargetIdentifiabilityAudit(StrictFrozenModel):
    """One target equation audited against a generic linear feature universe."""

    target: str = Field(pattern=r"^u[0-9]+_t$")
    feature_labels: tuple[str, ...] = Field(min_length=1)
    feature_count: int = Field(ge=1)
    nonzero_feature_count: int = Field(ge=1)
    feature_matrix_rank: int = Field(ge=1)
    expected_support: tuple[str, ...] = Field(min_length=1)
    expected_coefficients: tuple[float, ...] = Field(min_length=1)
    fitted_expected_support_coefficients: tuple[float, ...] = Field(min_length=1)
    expected_reconstruction_nmse: float = Field(ge=0, allow_inf_nan=False)
    maximum_expected_coefficient_relative_error: float = Field(
        ge=0,
        allow_inf_nan=False,
    )
    maximum_active_null_component: float = Field(ge=0, allow_inf_nan=False)
    minimum_leave_active_out_nmse: float = Field(ge=0, allow_inf_nan=False)
    expected_support_condition_number: float = Field(gt=0, allow_inf_nan=False)
    expected_support_identifiable: bool
    passed: bool

    @model_validator(mode="after")
    def _validate_audit(self) -> TargetIdentifiabilityAudit:
        if self.feature_count != len(self.feature_labels):
            raise ValueError("identifiability feature count changed")
        if not (
            len(self.expected_support)
            == len(self.expected_coefficients)
            == len(self.fitted_expected_support_coefficients)
        ):
            raise ValueError("identifiability expected-support vectors differ")
        expected_pass = (
            self.expected_support_identifiable
            and self.expected_reconstruction_nmse <= 1e-20
            and self.maximum_expected_coefficient_relative_error <= 1e-8
            and self.maximum_active_null_component <= 1e-8
            and self.minimum_leave_active_out_nmse > 1e-10
            and self.expected_support_condition_number <= 1e10
        )
        if self.passed != expected_pass:
            raise ValueError("identifiability target verdict changed")
        return self


class FixtureIdentifiabilityAudit(StrictFrozenModel):
    """All target-support audits for one immutable fixture."""

    sentinel_id: str
    fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_audits: tuple[TargetIdentifiabilityAudit, ...] = Field(min_length=1)
    passed: bool

    @model_validator(mode="after")
    def _validate_fixture(self) -> FixtureIdentifiabilityAudit:
        if self.passed != all(item.passed for item in self.target_audits):
            raise ValueError("fixture identifiability verdict changed")
        return self


class SentinelIdentifiabilityProbe(StrictFrozenModel):
    """Exact offline audit of the original and corrected sentinel sets."""

    schema_version: Literal["sentinel-identifiability-probe-v1"] = (
        "sentinel-identifiability-probe-v1"
    )
    image: str
    image_id: str
    benchmark_revision: str
    python_version: str
    dependencies: dict[str, str]
    runner_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    network_used: Literal[False] = False
    official_artifact_reads: Literal[0] = 0
    original_audits: tuple[FixtureIdentifiabilityAudit, ...]
    corrected_audits: tuple[FixtureIdentifiabilityAudit, ...]
    original_non_identifiable_ids: tuple[str, ...]
    corrected_all_identifiable: bool
    probe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_probe(self) -> SentinelIdentifiabilityProbe:
        original_ids = tuple(item.sentinel_id for item in self.original_audits)
        corrected_ids = tuple(item.sentinel_id for item in self.corrected_audits)
        if len(original_ids) != 6 or original_ids != corrected_ids:
            raise ValueError("identifiability probe fixture order changed")
        failures = tuple(
            item.sentinel_id for item in self.original_audits if not item.passed
        )
        if self.original_non_identifiable_ids != failures:
            raise ValueError("original identifiability failure set changed")
        if self.corrected_all_identifiable != all(
            item.passed for item in self.corrected_audits
        ):
            raise ValueError("corrected identifiability aggregate changed")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"probe_hash"})
        )
        if self.probe_hash != expected:
            raise ValueError("sentinel identifiability probe hash mismatch")
        return self


class CorrectedSentinelArtifact(StrictFrozenModel):
    """One corrected-set fixture and its exact persisted identity."""

    sentinel_id: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed: bool


class SentinelIdentifiabilityErratum(StrictFrozenModel):
    """Immutable overlay that corrects one synthetic stimulus only."""

    schema_version: Literal["sentinel-identifiability-erratum-v1"] = (
        "sentinel-identifiability-erratum-v1"
    )
    parent_plan_path: str
    parent_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_sentinel_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corrected_sentinels: tuple[CorrectedSentinelArtifact, ...]
    corrected_sentinel_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    modified_sentinel_ids: tuple[Literal["pde-advection-diffusion-2d"], ...]
    unchanged_fixture_count: Literal[5] = 5
    probe: SentinelIdentifiabilityProbe
    defect: Literal["u_xx_equals_u_yy_under_equal_wave_number_modes"] = (
        "u_xx_equals_u_yy_under_equal_wave_number_modes"
    )
    correction: Literal["independent_x_y_wave_number_modes"] = (
        "independent_x_y_wave_number_modes"
    )
    result_blind_erratum: Literal[True] = True
    new_official_development_result_count: Literal[0] = 0
    candidate_answer_count: Literal[0] = 0
    model_interaction_count: Literal[0] = 0
    confirmation_identity_read_count: Literal[0] = 0
    confirmation_result_count: Literal[0] = 0
    harness_implementation_authorized: bool
    official_development_execution_authorized: Literal[False] = False
    confirmation_authorized: Literal[False] = False
    publication_ready: Literal[False] = False
    next_required_task: Literal["266.2"] = "266.2"
    created_at: datetime
    output_path: str
    erratum_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_erratum(self) -> SentinelIdentifiabilityErratum:
        if len(self.corrected_sentinels) != 6:
            raise ValueError("corrected sentinel set must contain six fixtures")
        changed = tuple(item.sentinel_id for item in self.corrected_sentinels if item.changed)
        if changed != (_MODIFIED_SENTINEL_ID,) or self.modified_sentinel_ids != changed:
            raise ValueError("erratum must change only the aliased 2D sentinel")
        if sum(not item.changed for item in self.corrected_sentinels) != 5:
            raise ValueError("erratum unchanged-fixture count changed")
        expected_registry_hash = canonical_model_hash(
            {
                "items": [
                    item.model_dump(mode="json") for item in self.corrected_sentinels
                ]
            }
        )
        if self.corrected_sentinel_registry_hash != expected_registry_hash:
            raise ValueError("corrected sentinel registry hash mismatch")
        if self.probe.original_non_identifiable_ids != (_MODIFIED_SENTINEL_ID,):
            raise ValueError("erratum diagnosis is not the single frozen 2D alias")
        expected_authorization = self.probe.corrected_all_identifiable
        if self.harness_implementation_authorized != expected_authorization:
            raise ValueError("Harness authorization contradicts identifiability audit")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"erratum_hash", "output_path"})
        )
        if self.erratum_hash != expected:
            raise ValueError("sentinel identifiability erratum hash mismatch")
        return self


IdentifiabilityProbe = Callable[
    [Sequence[ScientificSentinelFixture], Sequence[ScientificSentinelFixture], str],
    SentinelIdentifiabilityProbe,
]


def freeze_sentinel_identifiability_erratum(
    parent_plan_path: Path | str,
    output_dir: Path | str,
    *,
    image: str = _IMAGE_NAME,
    identifiability_probe: IdentifiabilityProbe | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SentinelIdentifiabilityErratum:
    """Audit and correct the frozen sentinel set without reading a result."""

    parent = load_scientific_contract_recovery_plan(parent_plan_path)
    _validate_parent_boundary(parent)
    root = Path(output_dir).resolve()
    erratum_path = root / _ERRATUM_NAME
    if erratum_path.is_file():
        return load_sentinel_identifiability_erratum(erratum_path)
    if root.exists() and any(root.iterdir()):
        raise SentinelIdentifiabilityError(
            "refusing an unbound partial identifiability erratum directory"
        )
    root.mkdir(parents=True, exist_ok=True)
    original = _load_parent_fixtures(parent)
    corrected = tuple(
        _correct_2d_fixture(item) if item.sentinel_id == _MODIFIED_SENTINEL_ID else item
        for item in original
    )
    runner = identifiability_probe or probe_sentinel_identifiability
    probe = runner(original, corrected, image)
    if probe.original_non_identifiable_ids != (_MODIFIED_SENTINEL_ID,):
        raise SentinelIdentifiabilityError(
            "rank audit did not reproduce only the frozen 2D alias defect"
        )
    if not probe.corrected_all_identifiable:
        raise SentinelIdentifiabilityError(
            "corrected sentinel set remains non-identifiable"
        )

    parent_hashes = {item.sentinel_id: item.fixture_hash for item in parent.sentinels}
    artifacts: list[CorrectedSentinelArtifact] = []
    sentinel_root = root / "sentinels"
    sentinel_root.mkdir(parents=True, exist_ok=True)
    for fixture in corrected:
        relative_path = f"sentinels/{fixture.sentinel_id}.json"
        path = root / relative_path
        write_json_model(path, fixture)
        artifacts.append(
            CorrectedSentinelArtifact(
                sentinel_id=fixture.sentinel_id,
                relative_path=relative_path,
                sha256=file_hash(path),
                fixture_hash=fixture.fixture_hash,
                parent_fixture_hash=parent_hashes[fixture.sentinel_id],
                changed=fixture.fixture_hash != parent_hashes[fixture.sentinel_id],
            )
        )
    write_json_model(root / _PROBE_NAME, probe)
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    payload: dict[str, Any] = {
        "schema_version": "sentinel-identifiability-erratum-v1",
        "parent_plan_path": Path(parent_plan_path).resolve().as_posix(),
        "parent_plan_hash": parent.plan_hash,
        "parent_sentinel_registry_hash": parent.sentinel_registry_hash,
        "corrected_sentinels": [item.model_dump(mode="json") for item in artifacts],
        "corrected_sentinel_registry_hash": canonical_model_hash(
            {"items": [item.model_dump(mode="json") for item in artifacts]}
        ),
        "modified_sentinel_ids": [_MODIFIED_SENTINEL_ID],
        "unchanged_fixture_count": 5,
        "probe": probe.model_dump(mode="json"),
        "defect": "u_xx_equals_u_yy_under_equal_wave_number_modes",
        "correction": "independent_x_y_wave_number_modes",
        "result_blind_erratum": True,
        "new_official_development_result_count": 0,
        "candidate_answer_count": 0,
        "model_interaction_count": 0,
        "confirmation_identity_read_count": 0,
        "confirmation_result_count": 0,
        "harness_implementation_authorized": True,
        "official_development_execution_authorized": False,
        "confirmation_authorized": False,
        "publication_ready": False,
        "next_required_task": "266.2",
        "created_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "output_path": erratum_path.as_posix(),
    }
    payload["erratum_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "output_path"}
    )
    erratum = SentinelIdentifiabilityErratum.model_validate(payload)
    write_json_model(erratum_path, erratum)
    (root / _MARKDOWN_NAME).write_text(_render_markdown(erratum), encoding="utf-8")
    return load_sentinel_identifiability_erratum(erratum_path)


def load_sentinel_identifiability_erratum(
    path: Path | str,
) -> SentinelIdentifiabilityErratum:
    """Strictly reload the erratum, parent, probe, and corrected fixtures."""

    erratum_path = Path(path).resolve()
    try:
        erratum = SentinelIdentifiabilityErratum.model_validate_json(
            erratum_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise SentinelIdentifiabilityError(
            f"cannot load sentinel identifiability erratum: {exc}"
        ) from exc
    if Path(erratum.output_path).resolve() != erratum_path:
        raise SentinelIdentifiabilityError("identifiability erratum output path changed")
    parent = load_scientific_contract_recovery_plan(erratum.parent_plan_path)
    _validate_parent_boundary(parent)
    if (
        parent.plan_hash != erratum.parent_plan_hash
        or parent.sentinel_registry_hash != erratum.parent_sentinel_registry_hash
    ):
        raise SentinelIdentifiabilityError("identifiability erratum parent changed")
    root = erratum_path.parent
    expected_files = {_ERRATUM_NAME, _MARKDOWN_NAME, _PROBE_NAME}
    parent_hashes = {item.sentinel_id: item.fixture_hash for item in parent.sentinels}
    for artifact in erratum.corrected_sentinels:
        fixture_path = _inside(root, artifact.relative_path)
        if file_hash(fixture_path) != artifact.sha256:
            raise SentinelIdentifiabilityError(
                f"corrected sentinel bytes changed: {artifact.sentinel_id}"
            )
        try:
            fixture = ScientificSentinelFixture.model_validate_json(
                fixture_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise SentinelIdentifiabilityError(
                f"corrected sentinel is invalid: {artifact.sentinel_id}: {exc}"
            ) from exc
        if fixture.fixture_hash != artifact.fixture_hash:
            raise SentinelIdentifiabilityError(
                f"corrected sentinel identity changed: {artifact.sentinel_id}"
            )
        if artifact.parent_fixture_hash != parent_hashes[artifact.sentinel_id]:
            raise SentinelIdentifiabilityError(
                f"corrected sentinel parent identity changed: {artifact.sentinel_id}"
            )
        expected_files.add(artifact.relative_path)
    try:
        probe = SentinelIdentifiabilityProbe.model_validate_json(
            (root / _PROBE_NAME).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise SentinelIdentifiabilityError(
            f"cannot load sentinel identifiability probe: {exc}"
        ) from exc
    if probe != erratum.probe:
        raise SentinelIdentifiabilityError("persisted identifiability probe changed")
    actual_files = {
        item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()
    }
    if actual_files != expected_files:
        raise SentinelIdentifiabilityError(
            "identifiability erratum file set changed: "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )
    expected_markdown = _render_markdown(erratum)
    if (root / _MARKDOWN_NAME).read_text(encoding="utf-8") != expected_markdown:
        raise SentinelIdentifiabilityError("identifiability erratum Markdown changed")
    return erratum


def load_corrected_sentinel_fixtures(
    erratum_path: Path | str,
) -> tuple[ScientificSentinelFixture, ...]:
    """Load the six corrected fixtures for the Task 266.2 Harness."""

    erratum = load_sentinel_identifiability_erratum(erratum_path)
    root = Path(erratum.output_path).parent
    return tuple(
        ScientificSentinelFixture.model_validate_json(
            (root / item.relative_path).read_text(encoding="utf-8")
        )
        for item in erratum.corrected_sentinels
    )


def probe_sentinel_identifiability(
    original: Sequence[ScientificSentinelFixture],
    corrected: Sequence[ScientificSentinelFixture],
    image: str = _IMAGE_NAME,
) -> SentinelIdentifiabilityProbe:
    """Run the exact NumPy rank/support probe in the pinned offline image."""

    if not _PROBE_PATH.is_file():
        raise SentinelIdentifiabilityError(
            f"sentinel identifiability probe is missing: {_PROBE_PATH}"
        )
    try:
        inspected = subprocess.run(
            ["docker", "image", "inspect", image],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        records = json.loads(inspected.stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("Docker image inspection returned an invalid record set")
        image_record = records[0]
        image_id = str(image_record["Id"])
        labels = image_record.get("Config", {}).get("Labels", {}) or {}
        benchmark_revision = str(labels.get("org.opencontainers.image.revision", ""))
        request_payload = {
            "schema_version": "sentinel-identifiability-probe-input-v1",
            "expected_runner_sha256": file_hash(_PROBE_PATH),
            "original_fixtures": [item.model_dump(mode="json") for item in original],
            "corrected_fixtures": [item.model_dump(mode="json") for item in corrected],
        }
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--network",
                "none",
                "--read-only",
                "--cpus",
                "2",
                "--memory",
                "4096m",
                "--pids-limit",
                "128",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                "--mount",
                _bind_mount(_PROBE_PATH, "/input/sentinel_identifiability_probe.py"),
                "--entrypoint",
                "python",
                image,
                "/input/sentinel_identifiability_probe.py",
            ],
            input=json.dumps(request_payload, allow_nan=False, sort_keys=True),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = json.loads(completed.stdout)
    except (
        FileNotFoundError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as exc:
        raise SentinelIdentifiabilityError(
            f"cannot prove sentinel identifiability: {exc}"
        ) from exc
    if output.get("schema_version") != "sentinel-identifiability-probe-output-v1":
        raise SentinelIdentifiabilityError("identifiability probe output schema changed")
    try:
        original_audits = tuple(
            FixtureIdentifiabilityAudit.model_validate(item)
            for item in output.get("original_audits", [])
        )
        corrected_audits = tuple(
            FixtureIdentifiabilityAudit.model_validate(item)
            for item in output.get("corrected_audits", [])
        )
    except ValidationError as exc:
        raise SentinelIdentifiabilityError(
            f"identifiability probe output is invalid: {exc}"
        ) from exc
    payload: dict[str, Any] = {
        "schema_version": "sentinel-identifiability-probe-v1",
        "image": image,
        "image_id": image_id,
        "benchmark_revision": benchmark_revision,
        "python_version": output.get("python_version"),
        "dependencies": output.get("dependencies"),
        "runner_sha256": file_hash(_PROBE_PATH),
        "network_used": output.get("network_used"),
        "official_artifact_reads": output.get("official_artifact_reads"),
        "original_audits": [item.model_dump(mode="json") for item in original_audits],
        "corrected_audits": [item.model_dump(mode="json") for item in corrected_audits],
        "original_non_identifiable_ids": [
            item.sentinel_id for item in original_audits if not item.passed
        ],
        "corrected_all_identifiable": bool(corrected_audits)
        and all(item.passed for item in corrected_audits),
    }
    payload["probe_hash"] = canonical_model_hash(payload)
    try:
        return SentinelIdentifiabilityProbe.model_validate(payload)
    except ValidationError as exc:
        raise SentinelIdentifiabilityError(
            f"identifiability probe evidence is invalid: {exc}"
        ) from exc


def _validate_parent_boundary(parent: ScientificContractRecoveryPlan) -> None:
    if (
        parent.new_official_development_result_count != 0
        or parent.confirmation_identity_read_count != 0
        or parent.confirmation_result_count != 0
        or parent.candidate_answer_count != 0
        or parent.model_interaction_count != 0
    ):
        raise SentinelIdentifiabilityError(
            "Task 266.1 parent no longer has a result-blind boundary"
        )
    if not parent.harness_implementation_authorized:
        raise SentinelIdentifiabilityError("Task 266.1 did not authorize a Harness")
    if (
        parent.official_development_execution_authorized
        or parent.confirmation_authorized
        or parent.publication_ready
    ):
        raise SentinelIdentifiabilityError("Task 266.1 authorization boundary changed")


def _load_parent_fixtures(
    parent: ScientificContractRecoveryPlan,
) -> tuple[ScientificSentinelFixture, ...]:
    root = Path(parent.output_path).parent
    fixtures: list[ScientificSentinelFixture] = []
    for artifact in parent.sentinels:
        try:
            fixture = ScientificSentinelFixture.model_validate_json(
                (root / artifact.relative_path).read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise SentinelIdentifiabilityError(
                f"cannot load parent sentinel {artifact.sentinel_id}: {exc}"
            ) from exc
        if fixture.fixture_hash != artifact.fixture_hash:
            raise SentinelIdentifiabilityError(
                f"parent sentinel identity changed: {artifact.sentinel_id}"
            )
        fixtures.append(fixture)
    return tuple(fixtures)


def _correct_2d_fixture(
    original: ScientificSentinelFixture,
) -> ScientificSentinelFixture:
    if original.sentinel_id != _MODIFIED_SENTINEL_ID:
        raise SentinelIdentifiabilityError("wrong fixture passed to 2D correction")
    if original.spatial_dimensions != 2 or original.field_names != ("u0",):
        raise SentinelIdentifiabilityError("frozen 2D fixture shape changed")
    primary_parameters = _parameters_from_equation(original.expected_equations[0])
    alternative_parameters = _parameters_from_equation(
        original.alternative_expected_equations[0]
    )
    train_state, train_derivative = _evaluate_corrected_2d(
        original.spatial_coordinates,
        original.train_times,
        primary_parameters,
    )
    alternative_state, alternative_derivative = _evaluate_corrected_2d(
        original.spatial_coordinates,
        original.train_times,
        alternative_parameters,
    )
    queries = tuple(
        SentinelQuery(
            query_id=item.query_id,
            time=item.time,
            state=_evaluate_corrected_2d(
                original.spatial_coordinates,
                (item.time,),
                primary_parameters,
            )[0],
            expected_derivative=_evaluate_corrected_2d(
                original.spatial_coordinates,
                (item.time,),
                primary_parameters,
            )[1],
        )
        for item in original.queries
    )
    payload = original.model_dump(mode="json", exclude={"fixture_hash"})
    payload.update(
        {
            "train_state": train_state.model_dump(mode="json"),
            "train_derivative": train_derivative.model_dump(mode="json"),
            "alternative_train_state": alternative_state.model_dump(mode="json"),
            "alternative_train_derivative": alternative_derivative.model_dump(
                mode="json"
            ),
            "queries": [item.model_dump(mode="json") for item in queries],
        }
    )
    payload["fixture_hash"] = canonical_model_hash(payload)
    return ScientificSentinelFixture.model_validate(payload)


def _parameters_from_equation(equation: Any) -> tuple[float, float]:
    speed: float | None = None
    diffusivity: float | None = None
    for term in equation.terms:
        if len(term.factors) != 1:
            continue
        axes = term.factors[0].derivative_axes
        if axes == ("x",):
            speed = -float(term.coefficient)
        elif axes == ("y", "y"):
            diffusivity = float(term.coefficient)
    if speed is None or diffusivity is None or speed <= 0 or diffusivity <= 0:
        raise SentinelIdentifiabilityError("cannot recover frozen 2D parameters")
    return speed, diffusivity


def _evaluate_corrected_2d(
    axes: Mapping[Any, tuple[float, ...]],
    times: Sequence[float],
    parameters: tuple[float, float],
) -> tuple[TensorPayload, TensorPayload]:
    speed, diffusivity = parameters
    modes = (
        (1.0, 1, 1),
        (0.35, 2, 1),
        (0.25, 1, 2),
        (0.15, 3, 2),
    )
    states: list[float] = []
    derivatives: list[float] = []
    for x_value, y_value in product(axes["x"], axes["y"]):
        for current_time in times:
            state = 0.0
            derivative = 0.0
            for amplitude, x_wave, y_wave in modes:
                phase = x_wave * (x_value - speed * current_time)
                value = amplitude * math.exp(
                    -diffusivity * y_wave * y_wave * current_time
                )
                value *= math.sin(phase) * math.cos(y_wave * y_value)
                state += value
                derivative += -speed * x_wave * amplitude * math.exp(
                    -diffusivity * y_wave * y_wave * current_time
                ) * math.cos(phase) * math.cos(y_wave * y_value)
                derivative -= diffusivity * y_wave * y_wave * value
            states.append(state)
            derivatives.append(derivative)
    shape = (len(axes["x"]), len(axes["y"]), len(times), 1)
    return (
        TensorPayload(shape=shape, values=tuple(states)),
        TensorPayload(shape=shape, values=tuple(derivatives)),
    )


def _render_markdown(erratum: SentinelIdentifiabilityErratum) -> str:
    original = {
        item.sentinel_id: item for item in erratum.probe.original_audits
    }[_MODIFIED_SENTINEL_ID]
    corrected = {
        item.sentinel_id: item for item in erratum.probe.corrected_audits
    }[_MODIFIED_SENTINEL_ID]
    original_target = original.target_audits[0]
    corrected_target = corrected.target_audits[0]
    return (
        "# Task 266.1.1 sentinel-identifiability erratum\n\n"
        f"- Erratum hash: `{erratum.erratum_hash}`\n"
        f"- Parent plan hash: `{erratum.parent_plan_hash}`\n"
        f"- Probe hash: `{erratum.probe.probe_hash}`\n"
        f"- Modified fixture: `{_MODIFIED_SENTINEL_ID}` only\n"
        f"- Original active-null component: "
        f"`{original_target.maximum_active_null_component}`\n"
        f"- Original leave-active-out NMSE: "
        f"`{original_target.minimum_leave_active_out_nmse}`\n"
        f"- Corrected active-null component: "
        f"`{corrected_target.maximum_active_null_component}`\n"
        f"- Corrected leave-active-out NMSE: "
        f"`{corrected_target.minimum_leave_active_out_nmse}`\n"
        f"- Corrected fixtures identifiable: "
        f"`{str(erratum.probe.corrected_all_identifiable).lower()}`\n"
        "- New official results / candidates / model interactions / confirmation reads: "
        "`0 / 0 / 0 / 0`\n"
        "- Next authorized task: `266.2` synthetic Harness implementation only\n\n"
        "The original Task 266.1 package remains immutable. This overlay changes no "
        "threshold, baseline, budget, official panel, or confirmation commitment.\n"
    )


def _bind_mount(source: Path, target: str) -> str:
    return f"type=bind,source={source.resolve()},target={target},readonly"


def _inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise SentinelIdentifiabilityError(
            f"corrected sentinel path escapes erratum root: {relative_path}"
        ) from exc
    if not candidate.is_file():
        raise SentinelIdentifiabilityError(
            f"corrected sentinel is missing: {relative_path}"
        )
    return candidate


__all__ = [
    "CorrectedSentinelArtifact",
    "FixtureIdentifiabilityAudit",
    "SentinelIdentifiabilityErratum",
    "SentinelIdentifiabilityError",
    "SentinelIdentifiabilityProbe",
    "TargetIdentifiabilityAudit",
    "freeze_sentinel_identifiability_erratum",
    "load_corrected_sentinel_fixtures",
    "load_sentinel_identifiability_erratum",
    "probe_sentinel_identifiability",
]
