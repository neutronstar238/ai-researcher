from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from autoresearch.kernel import (
    Activity,
    ActivityKind,
    Agent,
    Association,
    Claim,
    Decision,
    Derivation,
    Entity,
    EntityKind,
    Evidence,
    EvidenceDirection,
    Generation,
    Plan,
    ProvenanceAgentKind,
    ProvenanceBundle,
    SourceSnapshot,
    Usage,
    Validation,
    canonical_sha256,
)
from autoresearch.reports import (
    ArtifactAccess,
    ArtifactTransform,
    Contributor,
    JsonAssertion,
    OpenScienceExportError,
    PublicationApproval,
    ResearchObjectArtifact,
    ResearchObjectMetadata,
    ResearchObjectView,
    export_open_science_research_object,
    run_clean_directory_reproduction,
    validate_open_science_view,
)
from autoresearch.schemas import ValidationStatus, file_hash

T0 = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=1)
T2 = T1 + timedelta(minutes=1)
COMMIT = "a" * 40


def _digest(value: object) -> str:
    return canonical_sha256(value)


def _bundle() -> ProvenanceBundle:
    source = Entity(
        entity_id="entity.source",
        kind=EntityKind.SOURCE_SNAPSHOT,
        label="Frozen benchmark input",
        content_digest=_digest("source"),
        source_uri="dataset://fixture/frozen",
        media_type="application/json",
        valid_from=T0,
    )
    result = Entity(
        entity_id="entity.result",
        kind=EntityKind.ARTIFACT,
        label="Frozen evaluation result",
        content_digest=_digest("result"),
        source_uri="run://fixture/result",
        media_type="application/json",
        valid_from=T1,
    )
    decision_artifact = Entity(
        entity_id="entity.decision",
        kind=EntityKind.DECISION,
        label="Next-round decision",
        content_digest=_digest("decision"),
        source_uri="run://fixture/decision",
        media_type="application/json",
        valid_from=T2,
    )
    evaluate = Activity(
        activity_id="activity.evaluate",
        kind=ActivityKind.EXECUTION,
        label="Frozen evaluation",
        started_at=T0,
        ended_at=T1,
        valid_from=T0,
    )
    decide = Activity(
        activity_id="activity.decide",
        kind=ActivityKind.DECISION,
        label="Deterministic contribution gate",
        started_at=T1,
        ended_at=T2,
        valid_from=T1,
    )
    software = Agent(
        agent_id="agent.software",
        kind=ProvenanceAgentKind.SOFTWARE,
        label="Frozen evaluator",
        implementation_hash=_digest("software"),
        valid_from=T0,
    )
    policy = Agent(
        agent_id="agent.policy",
        kind=ProvenanceAgentKind.DETERMINISTIC_POLICY,
        label="Frozen decision policy",
        implementation_hash=_digest("policy"),
        valid_from=T0,
    )
    plan = Plan(
        plan_id="plan.frozen",
        title="Frozen protocol",
        description="Evaluate once and apply the preregistered contribution gate.",
        content_digest=_digest("plan"),
        valid_from=T0,
    )
    validation = Validation(
        validation_id="validation.gate",
        subject_id="evidence.gate",
        activity_id="activity.evaluate",
        agent_id="agent.policy",
        status=ValidationStatus.PASSED,
        summary="The persisted gate result is internally consistent.",
        checked_at=T1,
        artifact_entity_id="entity.result",
        valid_from=T1,
    )
    return ProvenanceBundle.create(
        bundle_id="bundle.open-science-fixture",
        project_id="project-open-science",
        run_id="run-open-science",
        created_at=T2,
        entities=[source, result, decision_artifact],
        activities=[evaluate, decide],
        agents=[software, policy],
        plans=[plan],
        usages=[
            Usage(
                usage_id="usage.evaluate",
                activity_id="activity.evaluate",
                entity_id="entity.source",
                role="frozen input",
                at_time=T0,
                valid_from=T0,
            ),
            Usage(
                usage_id="usage.decide",
                activity_id="activity.decide",
                entity_id="entity.result",
                role="validated result",
                at_time=T1,
                valid_from=T1,
            ),
        ],
        generations=[
            Generation(
                generation_id="generation.result",
                entity_id="entity.result",
                activity_id="activity.evaluate",
                at_time=T1,
                valid_from=T1,
            ),
            Generation(
                generation_id="generation.decision",
                entity_id="entity.decision",
                activity_id="activity.decide",
                at_time=T2,
                valid_from=T2,
            ),
        ],
        derivations=[
            Derivation(
                derivation_id="derivation.result",
                generated_entity_id="entity.result",
                used_entity_id="entity.source",
                activity_id="activity.evaluate",
                valid_from=T1,
            )
        ],
        associations=[
            Association(
                association_id="association.evaluate",
                activity_id="activity.evaluate",
                agent_id="agent.software",
                role="executor",
                plan_id="plan.frozen",
                at_time=T0,
                valid_from=T0,
            ),
            Association(
                association_id="association.validate",
                activity_id="activity.evaluate",
                agent_id="agent.policy",
                role="validator",
                plan_id="plan.frozen",
                at_time=T1,
                valid_from=T1,
            ),
            Association(
                association_id="association.decide",
                activity_id="activity.decide",
                agent_id="agent.policy",
                role="decision policy",
                plan_id="plan.frozen",
                at_time=T1,
                valid_from=T1,
            ),
        ],
        source_snapshots=[
            SourceSnapshot(
                snapshot_id="snapshot.source",
                entity_id="entity.source",
                source_uri="dataset://fixture/frozen",
                retrieved_at=T0,
                content_digest=_digest("source"),
                valid_from=T0,
            )
        ],
        claims=[
            Claim(
                claim_id="claim.gate",
                statement="The frozen gate selected a next-round decision.",
                project_id="project-open-science",
                confidence=1.0,
                core=True,
                valid_from=T1,
            )
        ],
        evidence=[
            Evidence(
                evidence_id="evidence.gate",
                claim_id="claim.gate",
                artifact_entity_id="entity.result",
                source_entity_id="entity.source",
                source_snapshot_id="snapshot.source",
                generating_activity_id="activity.evaluate",
                responsible_agent_ids=["agent.software"],
                validation_ids=["validation.gate"],
                summary="The negative result satisfies the next-round rule.",
                confidence=1.0,
                direction=EvidenceDirection.SUPPORTS,
                valid_from=T1,
            )
        ],
        validations=[validation],
        decisions=[
            Decision(
                decision_id="decision.next",
                claim_ids=["claim.gate"],
                activity_id="activity.decide",
                responsible_agent_id="agent.policy",
                validation_ids=["validation.gate"],
                artifact_entity_id="entity.decision",
                outcome="next_round",
                rationale="Two preregistered checks failed.",
                decided_at=T2,
                valid_from=T2,
            )
        ],
        metadata={"fixture": True},
    )


def _metadata() -> ResearchObjectMetadata:
    return ResearchObjectMetadata(
        identifier="urn:autoresearch:fixture:round-001",
        title="AutoResearch frozen round fixture",
        description="A versioned, evidence-bound research object.",
        version="1.0.0",
        publisher="AutoResearch Test Team",
        published_at=T2,
        license_id="Apache-2.0",
        repository_url="https://example.org/autoresearch.git",
        commit_sha=COMMIT,
        swhid=f"swh:1:rev:{COMMIT}",
        contributors=(
            Contributor(
                family_names="Research Team",
                roles=("Conceptualization", "Software", "Validation"),
                affiliation="AutoResearch Test Team",
            ),
        ),
        keywords=("automated research", "provenance"),
    )


def _artifacts(tmp_path: Path) -> tuple[list[ResearchObjectArtifact], list[JsonAssertion]]:
    source = tmp_path / "source"
    source.mkdir()
    gate = source / "gate.json"
    gate.write_text(
        json.dumps(
            {
                "checks": {
                    "bootstrap_ci_lower_above_zero": False,
                    "three_ablations_complete": False,
                    "mandatory_evidence_complete": True,
                },
                "passed": False,
                "evidence_paths": [
                    "E:/private/workspace/results/unseen.json",
                ],
            }
        ),
        encoding="utf-8",
    )
    decision = source / "decision.json"
    decision.write_text(
        json.dumps(
            {
                "decision": "next_round",
                "outcome": "negative_result",
                "source": "E:/private/workspace/results/gate.json",
            }
        ),
        encoding="utf-8",
    )
    artifacts = [
        ResearchObjectArtifact(
            source_path=gate,
            crate_path="data/contribution-gate.json",
            role="validation",
            media_type="application/json",
            license_id="LicenseRef-Internal-Research",
            access=ArtifactAccess.REVIEW,
            provenance_entity_id="entity.result",
            expected_sha256=file_hash(gate),
            transform=ArtifactTransform.SANITIZE_JSON,
            description="Frozen contribution gate.",
        ),
        ResearchObjectArtifact(
            source_path=decision,
            crate_path="data/round-decision.json",
            role="decision",
            media_type="application/json",
            license_id="LicenseRef-Internal-Research",
            access=ArtifactAccess.REVIEW,
            provenance_entity_id="entity.decision",
            expected_sha256=file_hash(decision),
            transform=ArtifactTransform.SANITIZE_JSON,
            description="Frozen next-round decision.",
        ),
    ]
    assertions = [
        JsonAssertion(
            crate_path="data/contribution-gate.json",
            json_pointer="/passed",
            expected=False,
            label="contribution gate remains negative",
        ),
        JsonAssertion(
            crate_path="data/contribution-gate.json",
            json_pointer="/checks/bootstrap_ci_lower_above_zero",
            expected=False,
            label="confidence lower bound check remains failed",
        ),
        JsonAssertion(
            crate_path="data/round-decision.json",
            json_pointer="/decision",
            expected="next_round",
            label="negative result keeps the next-round decision",
        ),
    ]
    return artifacts, assertions


def test_export_builds_valid_internal_and_review_views_without_publication(
    tmp_path: Path,
) -> None:
    artifacts, assertions = _artifacts(tmp_path)
    original_hashes = {
        Path(artifact.source_path): file_hash(Path(artifact.source_path))
        for artifact in artifacts
    }

    exported = export_open_science_research_object(
        export_dir=tmp_path / "open-science",
        bundle=_bundle(),
        metadata=_metadata(),
        artifacts=artifacts,
        reproduction_assertions=assertions,
        created_at=T2,
    )

    assert exported.public is None
    assert set(exported.public_blocked_reasons) == {
        "explicit human publication approval is missing",
        "no artifact is explicitly approved for the public view",
    }
    assert not (Path(exported.export_dir) / "public").exists()
    assert validate_open_science_view(
        exported.internal.crate_dir,
        view=ResearchObjectView.INTERNAL,
    ).status == "passed"
    review_validation = validate_open_science_view(
        exported.review.crate_dir,
        view=ResearchObjectView.REVIEW,
    )
    assert review_validation.status == "passed"
    assert all(
        file_hash(path) == digest for path, digest in original_hashes.items()
    )

    review_dir = Path(exported.review.crate_dir)
    review_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in review_dir.rglob("*")
        if path.is_file()
    )
    assert "E:/private/workspace" not in review_text
    assert not (review_dir / "internal/provenance-bundle.json").exists()
    assert (
        review_dir / "provenance/prov.jsonld"
    ).read_text(encoding="utf-8").count("prov:") > 10
    crate = json.loads(
        (review_dir / "ro-crate-metadata.json").read_text(encoding="utf-8")
    )
    nodes = {node["@id"]: node for node in crate["@graph"]}
    assert {
        "https://w3id.org/ro/crate/1.3",
        "https://w3id.org/ro/crate/1.1",
        "https://w3id.org/workflowhub/workflow-ro-crate/1.0",
    }.issubset(
        {
            profile["@id"]
            for profile in nodes["ro-crate-metadata.json"]["conformsTo"]
        }
    )
    assert nodes["README.md"]["about"] == {"@id": "./"}
    assert nodes["README.md"]["encodingFormat"] == "text/markdown"
    workflow = nodes["workflow/workflow.json"]
    assert workflow["conformsTo"] == {
        "@id": (
            "https://bioschemas.org/profiles/"
            "ComputationalWorkflow/1.0-RELEASE"
        )
    }
    create_actions = [
        node for node in crate["@graph"] if "CreateAction" in node.get("@type", [])
    ]
    root_mentions = {
        mention["@id"] for mention in nodes["./"]["mentions"]
    }
    assert {action["@id"] for action in create_actions}.issubset(root_mentions)
    assert all(
        action["actionStatus"]
        == "http://schema.org/CompletedActionStatus"
        for action in create_actions
    )
    tools = [
        node
        for node in crate["@graph"]
        if "SoftwareApplication" in node.get("@type", [])
    ]
    assert tools
    assert all(tool["@id"].startswith("https://") for tool in tools)
    assert all("softwareVersion" not in tool for tool in tools)

    datacite = json.loads(
        (review_dir / "metadata/datacite-4.7-draft.json").read_text(
            encoding="utf-8"
        )
    )
    assert datacite["schemaVersion"] == "4.7"
    assert datacite["depositReady"] is False
    assert datacite["identifier"] is None
    cff = yaml.safe_load(
        (review_dir / "metadata/CITATION.cff").read_text(encoding="utf-8")
    )
    assert cff["cff-version"] == "1.2.0"
    assert cff["identifiers"][-1]["type"] == "swh"
    attestation = json.loads(
        (review_dir / "supply-chain/attestation-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert attestation == {
        "schema_version": 1,
        "scientific_result_attestation": False,
        "scope": "local construction of this research-object view",
        "signed": False,
        "slsa_format": "https://slsa.dev/provenance/v1",
        "slsa_level_claimed": None,
        "trusted_builder_claimed": False,
    }


def test_clean_directory_reproduction_and_tamper_detection(tmp_path: Path) -> None:
    artifacts, assertions = _artifacts(tmp_path)
    exported = export_open_science_research_object(
        export_dir=tmp_path / "open-science",
        bundle=_bundle(),
        metadata=_metadata(),
        artifacts=artifacts,
        reproduction_assertions=assertions,
        created_at=T2,
    )
    result = run_clean_directory_reproduction(
        exported.review.crate_dir,
        clean_dir=tmp_path / "independent-clean-room",
    )

    assert result.status == "passed"
    assert result.assertion_count == 3
    assert result.checked_files == 2
    assert result.scientific_experiment_reexecuted is False

    gate_path = Path(exported.review.crate_dir) / "data/contribution-gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["passed"] = True
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    validation = validate_open_science_view(
        exported.review.crate_dir,
        view=ResearchObjectView.REVIEW,
    )
    assert validation.status == "failed"
    assert {
        issue.check
        for issue in validation.issues
        if issue.severity.value == "failed"
    }.issuperset({"hash_manifest_entry", "slsa_subject"})


def test_public_view_requires_approval_open_license_and_clean_payload(
    tmp_path: Path,
) -> None:
    public_source = tmp_path / "public-result.json"
    public_source.write_text(
        '{"outcome":"negative_result","decision":"next_round"}\n',
        encoding="utf-8",
    )
    artifacts = [
        ResearchObjectArtifact(
            source_path=public_source,
            crate_path="data/public-result.json",
            role="result",
            media_type="application/json",
            license_id="Apache-2.0",
            access=ArtifactAccess.PUBLIC,
            provenance_entity_id="entity.result",
        )
    ]
    assertions = [
        JsonAssertion(
            crate_path="data/public-result.json",
            json_pointer="/decision",
            expected="next_round",
            label="public decision",
        )
    ]
    metadata = _metadata()
    exported = export_open_science_research_object(
        export_dir=tmp_path / "approved-export",
        bundle=_bundle(),
        metadata=metadata,
        artifacts=artifacts,
        reproduction_assertions=assertions,
        publication_approval=PublicationApproval(
            approval_id="approval-public-fixture",
            approver="human-reviewer",
            approved_at=T2,
            scope_identifier=metadata.identifier,
        ),
        created_at=T2,
    )

    assert exported.public is not None
    assert exported.public_blocked_reasons == ()
    assert validate_open_science_view(
        exported.public.crate_dir,
        view=ResearchObjectView.PUBLIC,
    ).status == "passed"
    policy = json.loads(
        (
            Path(exported.public.crate_dir) / "export-policy.json"
        ).read_text(encoding="utf-8")
    )
    assert policy["publication_approved"] is True
    assert policy["publication_performed"] is False

    restricted = replace(artifacts[0], license_id="LicenseRef-Restricted")
    blocked = export_open_science_research_object(
        export_dir=tmp_path / "blocked-export",
        bundle=_bundle(),
        metadata=metadata,
        artifacts=[restricted],
        reproduction_assertions=assertions,
        publication_approval=PublicationApproval(
            approval_id="approval-public-fixture",
            approver="human-reviewer",
            approved_at=T2,
            scope_identifier=metadata.identifier,
        ),
        created_at=T2,
    )
    assert blocked.public is None
    assert blocked.public_blocked_reasons == (
        "artifact data/public-result.json lacks a public-compatible license",
    )

    closed_metadata = replace(
        metadata,
        license_id="LicenseRef-Internal-Research",
    )
    metadata_blocked = export_open_science_research_object(
        export_dir=tmp_path / "metadata-license-blocked-export",
        bundle=_bundle(),
        metadata=closed_metadata,
        artifacts=artifacts,
        reproduction_assertions=assertions,
        publication_approval=PublicationApproval(
            approval_id="approval-public-fixture",
            approver="human-reviewer",
            approved_at=T2,
            scope_identifier=closed_metadata.identifier,
        ),
        created_at=T2,
    )
    assert metadata_blocked.public is None
    assert metadata_blocked.public_blocked_reasons == (
        "research-object metadata lacks a public-compatible license",
    )


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (
            replace(_metadata(), doi="not-a-doi"),
            "invalid DOI",
        ),
        (
            replace(_metadata(), swhid=f"swh:1:rev:{'b' * 40}"),
            "SWHID revision digest",
        ),
        (
            replace(
                _metadata(),
                contributors=(
                    Contributor(
                        family_names="Research Team",
                        roles=("Unknown role",),
                    ),
                ),
            ),
            "unknown CRediT role",
        ),
    ],
)
def test_identifier_and_contribution_metadata_fail_closed(
    tmp_path: Path,
    metadata: ResearchObjectMetadata,
    message: str,
) -> None:
    artifacts, assertions = _artifacts(tmp_path)
    with pytest.raises(OpenScienceExportError, match=message):
        export_open_science_research_object(
            export_dir=tmp_path / "invalid-export",
            bundle=_bundle(),
            metadata=metadata,
            artifacts=artifacts,
            reproduction_assertions=assertions,
            created_at=T2,
        )


def test_secret_content_blocks_every_view(tmp_path: Path) -> None:
    source = tmp_path / "secret-source.json"
    source.write_text('{"api_key":"sk-proj-not-allowed-123456789"}', encoding="utf-8")
    artifact = ResearchObjectArtifact(
        source_path=source,
        crate_path="data/source.json",
        role="input",
        media_type="application/json",
        license_id="Apache-2.0",
        access=ArtifactAccess.REVIEW,
        transform=ArtifactTransform.COPY,
    )
    with pytest.raises(OpenScienceExportError, match="secret-like content"):
        export_open_science_research_object(
            export_dir=tmp_path / "secret-export",
            bundle=_bundle(),
            metadata=_metadata(),
            artifacts=[artifact],
            reproduction_assertions=[
                JsonAssertion(
                    crate_path="data/source.json",
                    json_pointer="/api_key",
                    expected="redacted",
                    label="must never run",
                )
            ],
            created_at=T2,
        )


def test_artifact_cannot_overwrite_generated_crate_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "supplied-readme.md"
    source.write_text("# User supplied file\n", encoding="utf-8")
    artifact = ResearchObjectArtifact(
        source_path=source,
        crate_path="readme.md",
        role="documentation",
        media_type="text/markdown",
        license_id="Apache-2.0",
        access=ArtifactAccess.REVIEW,
    )

    with pytest.raises(OpenScienceExportError, match="collides"):
        export_open_science_research_object(
            export_dir=tmp_path / "collision-export",
            bundle=_bundle(),
            metadata=_metadata(),
            artifacts=[artifact],
            reproduction_assertions=[],
            created_at=T2,
        )
