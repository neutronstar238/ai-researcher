"""Provider-neutral contracts for vNext run events and graph projections."""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

StableId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]*$",
    ),
]
TypeName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class ContractIntegrityError(ValueError):
    """Raised when a loaded contract no longer matches its integrity fields."""


class GraphPlane(str, Enum):
    """Independent graph planes derived from the shared event history."""

    CONTROL = "control"
    PROVENANCE = "provenance"
    KNOWLEDGE = "knowledge"
    EVALUATION_POLICY = "evaluation_policy"


class ControlCyclePolicy(str, Enum):
    """How a control snapshot represents intentional iteration."""

    ACYCLIC = "acyclic"
    EXPLICIT_BOUNDARIES = "explicit_boundaries"


class ActorKind(str, Enum):
    """Kinds of actors that can be responsible for a run event."""

    OPERATOR = "operator"
    SCHEDULER = "scheduler"
    AGENT = "agent"
    MODEL = "model"
    TOOL = "tool"
    DETERMINISTIC_POLICY = "deterministic_policy"
    SYSTEM = "system"


class EventStatus(str, Enum):
    """Portable event states without binding to one workflow runtime."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    PAUSED = "paused"
    NEGATIVE_RESULT = "negative_result"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class KernelContract(BaseModel):
    """Strict base model with deterministic canonical serialization."""

    model_config = ConfigDict(extra="forbid")

    def canonical_json(self) -> str:
        """Serialize this contract using the project-wide canonical JSON form."""

        return canonical_json(self)

    def content_hash(self) -> str:
        """Return the SHA-256 digest of this contract's canonical JSON."""

        return canonical_sha256(self)


class EventActor(KernelContract):
    """The human, model, tool, policy, or service responsible for an event."""

    actor_id: StableId
    kind: ActorKind
    version: NonEmptyText | None = None


class GraphNode(KernelContract):
    """A typed node in exactly one graph plane."""

    node_id: StableId
    plane: GraphPlane
    node_type: TypeName
    label: NonEmptyText | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("attributes", mode="before")
    @classmethod
    def _validate_attributes(cls, value: object) -> object:
        _ensure_json_value(value, path="attributes")
        return value


class GraphEdge(KernelContract):
    """A directed typed relation whose endpoints are resolved by a snapshot."""

    edge_id: StableId
    plane: GraphPlane
    edge_type: TypeName
    source_id: StableId
    target_id: StableId
    cycle_boundary: bool = False
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("attributes", mode="before")
    @classmethod
    def _validate_attributes(cls, value: object) -> object:
        _ensure_json_value(value, path="attributes")
        return value


class GraphSnapshot(KernelContract):
    """A versioned, internally consistent projection of one graph plane."""

    schema_version: Literal[1] = 1
    graph_id: StableId
    version: int = Field(ge=1)
    plane: GraphPlane
    control_cycle_policy: ControlCyclePolicy | None = None
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata(cls, value: object) -> object:
        _ensure_json_value(value, path="metadata")
        return value

    @model_validator(mode="after")
    def _validate_graph(self) -> GraphSnapshot:
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        _require_unique(node_ids, label="node")
        _require_unique(edge_ids, label="edge")

        nodes_by_id = {node.node_id: node for node in self.nodes}
        for node in self.nodes:
            if node.plane != self.plane:
                msg = (
                    f"node {node.node_id} belongs to plane {node.plane.value}, "
                    f"not snapshot plane {self.plane.value}"
                )
                raise ValueError(msg)

        for edge in self.edges:
            if edge.plane != self.plane:
                msg = (
                    f"edge {edge.edge_id} belongs to plane {edge.plane.value}, "
                    f"not snapshot plane {self.plane.value}"
                )
                raise ValueError(msg)
            if edge.source_id not in nodes_by_id:
                raise ValueError(
                    f"edge {edge.edge_id} references missing source node {edge.source_id}"
                )
            if edge.target_id not in nodes_by_id:
                raise ValueError(
                    f"edge {edge.edge_id} references missing target node {edge.target_id}"
                )
            if edge.source_id == edge.target_id:
                raise ValueError(f"edge {edge.edge_id} is an invalid self-loop")

        self.nodes = sorted(self.nodes, key=lambda node: node.node_id)
        self.edges = sorted(self.edges, key=lambda edge: edge.edge_id)
        self._validate_cycle_policy()
        return self

    def _validate_cycle_policy(self) -> None:
        if self.plane != GraphPlane.CONTROL:
            if self.control_cycle_policy is not None:
                raise ValueError("control_cycle_policy is valid only for control graphs")
            boundary_edges = [edge.edge_id for edge in self.edges if edge.cycle_boundary]
            if boundary_edges:
                raise ValueError(
                    "cycle_boundary is valid only for control graph edges: "
                    + ", ".join(sorted(boundary_edges))
                )
            return

        if self.control_cycle_policy is None:
            raise ValueError("control graphs must declare control_cycle_policy")

        if self.control_cycle_policy == ControlCyclePolicy.ACYCLIC:
            boundary_edges = [edge.edge_id for edge in self.edges if edge.cycle_boundary]
            if boundary_edges:
                raise ValueError(
                    "acyclic control graphs cannot declare cycle boundaries: "
                    + ", ".join(sorted(boundary_edges))
                )
            edges_to_check = self.edges
        else:
            edges_to_check = [edge for edge in self.edges if not edge.cycle_boundary]

        if _has_directed_cycle(
            node_ids=[node.node_id for node in self.nodes],
            edges=edges_to_check,
        ):
            if self.control_cycle_policy == ControlCyclePolicy.ACYCLIC:
                raise ValueError("acyclic control graph contains a directed cycle")
            raise ValueError(
                "every directed control cycle must cross an explicit cycle_boundary edge"
            )


class _RunEventContent(KernelContract):
    """Validated event content before its canonical hash is attached."""

    schema_version: Literal[1] = 1
    event_id: StableId = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    run_id: StableId
    task_id: StableId | None = None
    sequence: int = Field(ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: EventActor
    event_type: TypeName
    status: EventStatus
    action: NonEmptyText
    parent_event_id: StableId | None = None
    parent_event_hash: Sha256 | None = None
    parent_run_id: StableId | None = None
    input_artifact_ids: list[StableId] = Field(default_factory=list)
    output_artifact_ids: list[StableId] = Field(default_factory=list)
    decision_id: StableId | None = None
    approval_id: StableId | None = None
    idempotency_key: StableId
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("occurred_at must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @field_validator("input_artifact_ids", "output_artifact_ids")
    @classmethod
    def _require_unique_artifacts(cls, value: list[str]) -> list[str]:
        _require_unique(value, label="artifact")
        return sorted(value)

    @field_validator("payload", mode="before")
    @classmethod
    def _validate_payload(cls, value: object) -> object:
        _ensure_json_value(value, path="payload")
        return value

    @model_validator(mode="after")
    def _validate_parent_fields(self) -> _RunEventContent:
        has_parent_id = self.parent_event_id is not None
        has_parent_hash = self.parent_event_hash is not None
        if has_parent_id != has_parent_hash:
            raise ValueError("parent_event_id and parent_event_hash must be provided together")
        if self.parent_run_id is not None and not has_parent_id:
            raise ValueError("parent_run_id requires a parent event")

        if self.sequence == 1:
            if has_parent_id:
                if self.parent_run_id is None:
                    raise ValueError("a sequence-1 fork parent requires parent_run_id")
                if self.parent_run_id == self.run_id:
                    raise ValueError("a sequence-1 parent must belong to a different run")
            return self

        if not has_parent_id:
            raise ValueError("events after sequence 1 require a parent event")
        if self.parent_run_id is not None and self.parent_run_id != self.run_id:
            raise ValueError("events after sequence 1 cannot switch parent runs")
        return self


class RunEvent(_RunEventContent):
    """A content-addressed, runtime-neutral record of one run transition."""

    event_hash: Sha256

    @model_validator(mode="after")
    def _validate_event_hash(self) -> RunEvent:
        expected = self.calculated_hash()
        if self.event_hash != expected:
            raise ValueError(
                f"event_hash mismatch for {self.event_id}: "
                f"expected {expected}, got {self.event_hash}"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        sequence: int,
        actor: EventActor,
        event_type: str,
        status: EventStatus,
        action: str,
        idempotency_key: str,
        event_id: str | None = None,
        task_id: str | None = None,
        occurred_at: datetime | None = None,
        parent_event_id: str | None = None,
        parent_event_hash: str | None = None,
        parent_run_id: str | None = None,
        input_artifact_ids: list[str] | None = None,
        output_artifact_ids: list[str] | None = None,
        decision_id: str | None = None,
        approval_id: str | None = None,
        payload: dict[str, JsonValue] | None = None,
    ) -> RunEvent:
        """Validate event content, attach its digest, and validate the final event."""

        raw: dict[str, Any] = {
            "run_id": run_id,
            "sequence": sequence,
            "actor": actor,
            "event_type": event_type,
            "status": status,
            "action": action,
            "idempotency_key": idempotency_key,
            "task_id": task_id,
            "parent_event_id": parent_event_id,
            "parent_event_hash": parent_event_hash,
            "parent_run_id": parent_run_id,
            "input_artifact_ids": input_artifact_ids or [],
            "output_artifact_ids": output_artifact_ids or [],
            "decision_id": decision_id,
            "approval_id": approval_id,
            "payload": payload or {},
        }
        if event_id is not None:
            raw["event_id"] = event_id
        if occurred_at is not None:
            raw["occurred_at"] = occurred_at

        content = _RunEventContent.model_validate(raw)
        content_payload = content.model_dump(mode="json")
        content_payload["event_hash"] = canonical_sha256(content)
        return cls.model_validate(content_payload)

    def calculated_hash(self) -> str:
        """Calculate the digest over all normalized fields except ``event_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"event_hash"}))

    def verify_integrity(self) -> None:
        """Fail closed if in-memory content was mutated after validation."""

        expected = self.calculated_hash()
        if self.event_hash != expected:
            raise ContractIntegrityError(
                f"event {self.event_id} failed integrity verification: "
                f"expected {expected}, got {self.event_hash}"
            )


CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    EventActor,
    GraphNode,
    GraphEdge,
    GraphSnapshot,
    RunEvent,
)


def contract_json_schemas() -> dict[str, dict[str, Any]]:
    """Export deterministic JSON Schema documents for public kernel contracts."""

    return {model.__name__: model.model_json_schema() for model in CONTRACT_MODELS}


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible content deterministically and reject NaN/Infinity."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    _ensure_json_value(payload, path="$")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    """Return a SHA-256 digest over canonical JSON bytes."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _ensure_json_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _ensure_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _ensure_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains non-JSON value of type {type(value).__name__}")


def _require_unique(values: list[str], *, label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {label} IDs: {', '.join(sorted(duplicates))}")


def _has_directed_cycle(*, node_ids: list[str], edges: list[GraphEdge]) -> bool:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree: dict[str, int] = dict.fromkeys(node_ids, 0)
    for edge in edges:
        adjacency[edge.source_id].append(edge.target_id)
        indegree[edge.target_id] += 1

    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    visited_count = 0
    while ready:
        node_id = ready.popleft()
        visited_count += 1
        for target_id in sorted(adjacency[node_id]):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
    return visited_count != len(node_ids)
