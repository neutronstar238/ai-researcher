"""Tests for provider-neutral vNext event and graph contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from autoresearch.kernel import (
    ActorKind,
    ContractIntegrityError,
    ControlCyclePolicy,
    EventActor,
    EventStatus,
    GraphEdge,
    GraphNode,
    GraphPlane,
    GraphSnapshot,
    RunEvent,
    canonical_json,
    contract_json_schemas,
)

UTC_TIME = datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc)
PARENT_HASH = "a" * 64


def _actor() -> EventActor:
    return EventActor(actor_id="policy.kernel", kind=ActorKind.DETERMINISTIC_POLICY, version="1")


def _event(**updates: object) -> RunEvent:
    values: dict[str, object] = {
        "event_id": "evt_001",
        "run_id": "run_001",
        "task_id": "262.2",
        "sequence": 1,
        "occurred_at": UTC_TIME,
        "actor": _actor(),
        "event_type": "graph.snapshot.validated",
        "status": EventStatus.SUCCEEDED,
        "action": "Validate the frozen graph snapshot",
        "idempotency_key": "run_001:1",
        "input_artifact_ids": ["artifact_input"],
        "output_artifact_ids": ["artifact_output"],
        "payload": {"counts": {"nodes": 2, "edges": 1}, "valid": True},
    }
    values.update(updates)
    return RunEvent.create(**values)  # type: ignore[arg-type]


def _node(node_id: str, *, plane: GraphPlane = GraphPlane.CONTROL) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        plane=plane,
        node_type="stage",
        attributes={"ordinal": 1},
    )


def _edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    plane: GraphPlane = GraphPlane.CONTROL,
    cycle_boundary: bool = False,
) -> GraphEdge:
    return GraphEdge(
        edge_id=edge_id,
        plane=plane,
        edge_type="transitions_to",
        source_id=source_id,
        target_id=target_id,
        cycle_boundary=cycle_boundary,
    )


def test_run_event_round_trip_and_hash_are_deterministic() -> None:
    event = _event()

    loaded = RunEvent.model_validate_json(event.model_dump_json())

    assert loaded == event
    assert loaded.event_hash == loaded.calculated_hash()
    assert len(loaded.event_hash) == 64
    assert loaded.canonical_json() == event.canonical_json()
    loaded.verify_integrity()


def test_run_event_rejects_tampered_content_on_load() -> None:
    payload = _event().model_dump(mode="json")
    payload["action"] = "Silently changed action"

    with pytest.raises(ValidationError, match="event_hash mismatch"):
        RunEvent.model_validate(payload)


def test_run_event_detects_in_memory_nested_payload_mutation() -> None:
    event = _event()
    event.payload["valid"] = False

    with pytest.raises(ContractIntegrityError, match="failed integrity verification"):
        event.verify_integrity()


def test_run_event_requires_utc_time() -> None:
    non_utc = datetime(2026, 7, 28, 14, 0, tzinfo=timezone(timedelta(hours=8)))

    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        _event(occurred_at=non_utc)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"sequence": 2}, "require a parent event"),
        ({"parent_event_id": "evt_parent"}, "must be provided together"),
        ({"parent_run_id": "run_parent"}, "parent_run_id requires a parent event"),
        (
            {
                "parent_event_id": "evt_parent",
                "parent_event_hash": PARENT_HASH,
            },
            "sequence-1 fork parent requires parent_run_id",
        ),
        (
            {
                "parent_event_id": "evt_parent",
                "parent_event_hash": PARENT_HASH,
                "parent_run_id": "run_001",
            },
            "sequence-1 parent must belong to a different run",
        ),
        (
            {
                "sequence": 2,
                "parent_event_id": "evt_parent",
                "parent_event_hash": PARENT_HASH,
                "parent_run_id": "run_other",
            },
            "cannot switch parent runs",
        ),
    ],
)
def test_run_event_rejects_parent_field_mismatches(
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _event(**updates)


def test_run_event_supports_internal_parent_and_external_fork_parent() -> None:
    internal = _event(
        event_id="evt_002",
        sequence=2,
        parent_event_id="evt_001",
        parent_event_hash=PARENT_HASH,
    )
    fork = _event(
        event_id="evt_fork_001",
        run_id="run_fork",
        parent_event_id="evt_parent",
        parent_event_hash=PARENT_HASH,
        parent_run_id="run_parent",
    )

    assert internal.parent_run_id is None
    assert fork.sequence == 1
    assert fork.parent_run_id == "run_parent"


def test_run_event_rejects_duplicate_artifact_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate artifact IDs"):
        _event(input_artifact_ids=["artifact_a", "artifact_a"])


def test_run_event_normalizes_unordered_artifact_reference_sets() -> None:
    first = _event(
        input_artifact_ids=["artifact_b", "artifact_a"],
        output_artifact_ids=["artifact_d", "artifact_c"],
    )
    second = _event(
        input_artifact_ids=["artifact_a", "artifact_b"],
        output_artifact_ids=["artifact_c", "artifact_d"],
    )

    assert first.event_hash == second.event_hash
    assert first.input_artifact_ids == ["artifact_a", "artifact_b"]
    assert first.output_artifact_ids == ["artifact_c", "artifact_d"]


@pytest.mark.parametrize(
    "payload",
    [
        {"not_json": object()},
        {"not_finite": float("nan")},
        {"not_finite": float("inf")},
        {"tuple": ("not", "a", "json-array")},
    ],
)
def test_run_event_rejects_non_json_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="non-JSON|non-finite"):
        _event(payload=payload)


def test_run_event_rejects_non_string_payload_keys() -> None:
    with pytest.raises(ValidationError, match="non-string object key"):
        _event(payload={1: "not a JSON object key"})


def test_graph_snapshot_round_trip_and_content_hash() -> None:
    snapshot = GraphSnapshot(
        graph_id="research_loop",
        version=1,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.ACYCLIC,
        nodes=[_node("observe"), _node("diagnose")],
        edges=[_edge("observe_to_diagnose", "observe", "diagnose")],
        metadata={"frozen": True},
    )

    loaded = GraphSnapshot.model_validate_json(snapshot.model_dump_json())

    assert loaded == snapshot
    assert loaded.content_hash() == snapshot.content_hash()
    assert len(snapshot.content_hash()) == 64


def test_graph_snapshot_normalizes_unordered_node_and_edge_sets() -> None:
    first = GraphSnapshot(
        graph_id="normalized_graph",
        version=1,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.ACYCLIC,
        nodes=[_node("observe"), _node("report"), _node("diagnose")],
        edges=[
            _edge("observe_to_diagnose", "observe", "diagnose"),
            _edge("diagnose_to_report", "diagnose", "report"),
        ],
    )
    second = GraphSnapshot(
        graph_id="normalized_graph",
        version=1,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.ACYCLIC,
        nodes=list(reversed(first.nodes)),
        edges=list(reversed(first.edges)),
    )

    assert first.content_hash() == second.content_hash()
    assert [node.node_id for node in first.nodes] == ["diagnose", "observe", "report"]
    assert [edge.edge_id for edge in first.edges] == [
        "diagnose_to_report",
        "observe_to_diagnose",
    ]


def test_graph_snapshot_rejects_duplicate_node_and_edge_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate node IDs"):
        GraphSnapshot(
            graph_id="duplicate_nodes",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=[_node("observe"), _node("observe")],
        )

    with pytest.raises(ValidationError, match="duplicate edge IDs"):
        GraphSnapshot(
            graph_id="duplicate_edges",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=[_node("observe"), _node("diagnose")],
            edges=[
                _edge("transition", "observe", "diagnose"),
                _edge("transition", "observe", "diagnose"),
            ],
        )


@pytest.mark.parametrize(
    ("edge", "message"),
    [
        (_edge("missing_source", "missing", "diagnose"), "missing source node"),
        (_edge("missing_target", "observe", "missing"), "missing target node"),
        (_edge("self_loop", "observe", "observe"), "invalid self-loop"),
    ],
)
def test_graph_snapshot_rejects_invalid_endpoints(
    edge: GraphEdge,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        GraphSnapshot(
            graph_id="invalid_endpoints",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=[_node("observe"), _node("diagnose")],
            edges=[edge],
        )


def test_graph_snapshot_rejects_cross_plane_nodes_and_edges() -> None:
    with pytest.raises(ValidationError, match="not snapshot plane"):
        GraphSnapshot(
            graph_id="cross_plane_node",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=[_node("claim", plane=GraphPlane.PROVENANCE)],
        )

    with pytest.raises(ValidationError, match="not snapshot plane"):
        GraphSnapshot(
            graph_id="cross_plane_edge",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=[_node("observe"), _node("diagnose")],
            edges=[
                _edge(
                    "wrong_plane",
                    "observe",
                    "diagnose",
                    plane=GraphPlane.KNOWLEDGE,
                )
            ],
        )


def test_acyclic_control_graph_rejects_cycles_and_boundary_markers() -> None:
    nodes = [_node("observe"), _node("diagnose")]
    cycle = [
        _edge("forward", "observe", "diagnose"),
        _edge("back", "diagnose", "observe"),
    ]

    with pytest.raises(ValidationError, match="contains a directed cycle"):
        GraphSnapshot(
            graph_id="implicit_cycle",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=nodes,
            edges=cycle,
        )

    with pytest.raises(ValidationError, match="cannot declare cycle boundaries"):
        GraphSnapshot(
            graph_id="unused_boundary",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=nodes,
            edges=[_edge("forward", "observe", "diagnose", cycle_boundary=True)],
        )


def test_explicit_control_cycle_requires_a_marked_boundary_edge() -> None:
    nodes = [_node("observe"), _node("diagnose")]
    unmarked_cycle = [
        _edge("forward", "observe", "diagnose"),
        _edge("back", "diagnose", "observe"),
    ]

    with pytest.raises(ValidationError, match="must cross an explicit cycle_boundary"):
        GraphSnapshot(
            graph_id="unmarked_loop",
            version=1,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=ControlCyclePolicy.EXPLICIT_BOUNDARIES,
            nodes=nodes,
            edges=unmarked_cycle,
        )

    marked = GraphSnapshot(
        graph_id="marked_loop",
        version=1,
        plane=GraphPlane.CONTROL,
        control_cycle_policy=ControlCyclePolicy.EXPLICIT_BOUNDARIES,
        nodes=nodes,
        edges=[
            _edge("forward", "observe", "diagnose"),
            _edge("back", "diagnose", "observe", cycle_boundary=True),
        ],
    )

    assert any(edge.cycle_boundary for edge in marked.edges)


def test_cycle_policy_is_scoped_to_control_plane() -> None:
    knowledge_nodes = [
        _node("paper_a", plane=GraphPlane.KNOWLEDGE),
        _node("paper_b", plane=GraphPlane.KNOWLEDGE),
    ]
    knowledge_edges = [
        _edge(
            "a_to_b",
            "paper_a",
            "paper_b",
            plane=GraphPlane.KNOWLEDGE,
        ),
        _edge(
            "b_to_a",
            "paper_b",
            "paper_a",
            plane=GraphPlane.KNOWLEDGE,
        ),
    ]

    snapshot = GraphSnapshot(
        graph_id="knowledge_cycle",
        version=1,
        plane=GraphPlane.KNOWLEDGE,
        nodes=knowledge_nodes,
        edges=knowledge_edges,
    )
    assert len(snapshot.edges) == 2

    with pytest.raises(ValidationError, match="valid only for control graphs"):
        GraphSnapshot(
            graph_id="knowledge_with_control_policy",
            version=1,
            plane=GraphPlane.KNOWLEDGE,
            control_cycle_policy=ControlCyclePolicy.ACYCLIC,
            nodes=knowledge_nodes,
            edges=knowledge_edges,
        )

    with pytest.raises(ValidationError, match="must declare control_cycle_policy"):
        GraphSnapshot(
            graph_id="control_without_policy",
            version=1,
            plane=GraphPlane.CONTROL,
            nodes=[_node("observe")],
        )


def test_non_control_graph_rejects_cycle_boundary_marker() -> None:
    with pytest.raises(ValidationError, match="valid only for control graph edges"):
        GraphSnapshot(
            graph_id="knowledge_boundary",
            version=1,
            plane=GraphPlane.KNOWLEDGE,
            nodes=[
                _node("paper_a", plane=GraphPlane.KNOWLEDGE),
                _node("paper_b", plane=GraphPlane.KNOWLEDGE),
            ],
            edges=[
                _edge(
                    "citation",
                    "paper_a",
                    "paper_b",
                    plane=GraphPlane.KNOWLEDGE,
                    cycle_boundary=True,
                )
            ],
        )


def test_contract_json_schema_export_is_deterministic_and_complete() -> None:
    first = contract_json_schemas()
    second = contract_json_schemas()

    assert canonical_json(first) == canonical_json(second)
    assert set(first) == {
        "EventActor",
        "GraphNode",
        "GraphEdge",
        "GraphSnapshot",
        "RunEvent",
    }
    assert first["RunEvent"]["additionalProperties"] is False
    assert "event_hash" in first["RunEvent"]["properties"]
    assert first["GraphSnapshot"]["properties"]["schema_version"]["const"] == 1


json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=32),
)


@given(st.dictionaries(st.text(min_size=1, max_size=16), json_scalar, max_size=12))
def test_event_hash_is_independent_of_payload_key_insertion_order(
    payload: dict[str, object],
) -> None:
    reversed_payload = dict(reversed(list(payload.items())))

    first = _event(payload=payload)
    second = _event(payload=reversed_payload)

    assert first.event_hash == second.event_hash
    assert first.canonical_json() == second.canonical_json()
