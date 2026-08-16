"""Evidence graph primitives (spec §14): node types, relations, edge-direction rules.

Pure and unit-testable. The relation matrix rejects meaningless edges
(e.g. Dataset contradicts User, Experiment cites Claim) server-side.
"""

from __future__ import annotations

EVIDENCE_NODE_TYPES = (
    "research_question",
    "paper",
    "evidence",
    "hypothesis",
    "experiment",
    "result",
    "validation",
    "claim",
    "dataset",
    "method",
)

EVIDENCE_RELATIONS = (
    "supports",
    "contradicts",
    "derived_from",
    "cites",
    "uses",
    "tested_by",
    "validated_by",
    "produces",
    "related_to",
)

EVIDENCE_STANCES = ("supports", "contradicts", "neutral", "uncertain")

# relation -> (allowed source node types, allowed target node types)
RELATION_MATRIX: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "supports": (frozenset({"paper", "evidence", "result"}), frozenset({"hypothesis", "claim"})),
    "contradicts": (frozenset({"paper", "evidence", "result"}), frozenset({"hypothesis", "claim"})),
    "derived_from": (frozenset({"claim"}), frozenset({"evidence", "result", "validation"})),
    "cites": (frozenset({"paper"}), frozenset({"paper"})),
    "uses": (frozenset({"experiment", "method"}), frozenset({"dataset"})),
    "tested_by": (frozenset({"hypothesis"}), frozenset({"experiment"})),
    "validated_by": (frozenset({"result"}), frozenset({"validation"})),
    "produces": (frozenset({"experiment"}), frozenset({"result"})),
    # 弱关系：任意类型，但要求 rationale
    "related_to": (frozenset(EVIDENCE_NODE_TYPES), frozenset(EVIDENCE_NODE_TYPES)),
}


def is_node_type(value: str) -> bool:
    return value in EVIDENCE_NODE_TYPES


def is_relation(value: str) -> bool:
    return value in EVIDENCE_RELATIONS


def relation_allowed(source_type: str, relation: str, target_type: str) -> bool:
    sources, targets = RELATION_MATRIX.get(relation, (frozenset(), frozenset()))
    return source_type in sources and target_type in targets


def self_loop_allowed(relation: str) -> bool:
    return relation == "related_to"
