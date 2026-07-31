"""Publication-currency audit for the frozen Task 260 Route B systems paper.

The Task 260 v2 package is historical evidence and is never rewritten here.
This module binds to that package, retains primary-source snapshots from five
adversarial literature perspectives, recomputes the Route B effect at the
independent task level, and emits a tamper-evident repair decision package.

The audit is intentionally unable to authorize publication, public release,
authorship, licensing, venue selection, or external submission.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import random
import re
import ssl
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

import certifi
from pydantic import Field, TypeAdapter, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    NonEmptyText,
    Sha256,
    StableId,
    canonical_sha256,
)

from .workload_qualified_opportunity import InterpreterRuntime, probe_interpreter_runtime

TASK_ID = "263.7.0"
PARENT_GIT_COMMIT = "5b3a64d4e24a0d59c23ea4f5b8fc9d135aaaf9db"
PARENT_PACKAGE_ID = "task260-final-paper-v2"
PARENT_PACKAGE_HASH = "bd4a2b74c271d321c4b859e4f16004f9eb8cd1cc6de6409bb8d6c71eb4c194ac"
PARENT_PACKAGE_FILE_SHA256 = (
    "7ef8306f1685ccff72338859f349a931e38dddd8b841d99750174073be2173eb"
)
PARENT_PDF_SHA256 = "9199a1146fce116b0035090dbca3df27dc38a4c740fb1f935f06c587317a4a3b"
PARENT_SYSTEMS_RESULT_HASH = (
    "5f69cac379409d1abf5cd682682f54d76d181dc7aaf45c021f525ac50a5830cb"
)
PARENT_SYSTEMS_RESULT_FILE_SHA256 = (
    "c0fe63d772961bb5e60f4a6e4ec39abb9817478e17ec9e990796ca06aad9f811"
)
PARENT_SYSTEMS_GATE_HASH = (
    "1257ba5b721748539cd3846dd7f0df78237614f98fec417fda48b4f0b5b2e6a7"
)
PARENT_SYSTEMS_GATE_FILE_SHA256 = (
    "cdebd6a4773677428a2015cc2d987f2ee7b4c53070306a612ebd0fc4b676b023"
)
PARENT_MATRIX_FILE_SHA256 = (
    "7d13f1f580147ae250bfa6592612027628fc989b09adefa3c8b78a814b38fefa"
)
PARENT_PREREGISTRATION_FILE_SHA256 = (
    "c7959afdb8f0d21e455cd73de6bf45ee7f0040ccacd0976b20d2ce20e4cd263e"
)

BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 2604
EXPECTED_SEEDS = (211, 223, 227)

AUDIT_REPORT_FILENAME = "systems-paper-currency-audit.json"
AUDIT_MARKDOWN_FILENAME = "systems-paper-currency-audit.md"
AUDIT_BRIEF_FILENAME = "research-brief.json"
AUDIT_SOURCE_REGISTRY_FILENAME = "source-registry.json"
AUDIT_INDEPENDENT_UNIT_FILENAME = "independent-unit-audit.json"
AUDIT_LANGUAGE_SCAN_FILENAME = "paper-language-scan.json"
AUDIT_FINDINGS_FILENAME = "paper-findings.json"
AUDIT_REPAIR_PLAN_FILENAME = "repair-plan.json"
AUDIT_REPLAY_FILENAME = "statistical-replay.json"
AUDIT_SCHEMAS_FILENAME = "systems-paper-currency-audit-schemas.json"
AUDIT_MANIFEST_FILENAME = "systems-paper-currency-audit-manifest.json"
AUDIT_SOURCE_DIRECTORY = "sources"
AUDIT_RUNNER_SOURCE_PATH = Path(
    "src/autoresearch/research/assets/frozen_systems_paper_currency_probe_v1.py"
)

_JSON_PAYLOAD_ADAPTER = TypeAdapter(dict[str, Any])


class SystemsPaperCurrencyIntegrityError(ValueError):
    """Raised when a parent or generated audit artifact fails verification."""


class PrimarySourceFetchError(RuntimeError):
    """Raised when a primary literature or standards page cannot be retained."""


class LiteraturePerspective(str, Enum):
    MAINSTREAM_SYSTEMS = "mainstream-autonomous-science-systems"
    INDEPENDENT_EVALUATION = "independent-benchmarks-and-failure-audits"
    STATISTICAL_METHODS = "statistical-and-benchmark-methodology"
    OPEN_SCIENCE = "open-science-interoperability"
    HUMAN_RESPONSIBILITY = "human-responsibility-and-integrity"


class SourceKind(str, Enum):
    JOURNAL_ARTICLE = "journal-article"
    CONFERENCE_ARTICLE = "conference-article"
    PREPRINT = "preprint"
    STANDARD = "standard-or-specification"
    POLICY = "policy"


class ReviewStatus(str, Enum):
    PEER_REVIEWED = "peer-reviewed"
    PREPRINT = "preprint-not-peer-reviewed"
    NORMATIVE = "normative-standard-or-policy"


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class AuditDimension(str, Enum):
    LOGIC = "logic-and-claim-chain"
    NOVELTY = "novelty-and-related-work"
    EMPIRICAL_VALIDITY = "empirical-validity"
    EXTERNAL_VALIDITY = "external-validity"
    OPEN_SCIENCE = "reproducibility-and-open-science"
    LANGUAGE_LATEX = "language-and-latex"
    HUMAN_GOVERNANCE = "human-governance"


class RepairClass(str, Enum):
    EXISTING_EVIDENCE_TEXT = "existing-evidence-text-revision"
    EXISTING_EVIDENCE_REANALYSIS = "existing-evidence-reanalysis"
    NEW_INDEPENDENT_EVIDENCE = "new-independent-evidence"
    HUMAN_ONLY = "human-only-decision"


class PublicationVerdict(str, Enum):
    NEW_EVIDENCE_AND_HUMAN_REVIEW_REQUIRED = (
        "major-revision-new-independent-evidence-and-human-review-required"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_text(value: Any) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, KernelContract) else value
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _pretty_json_text(value: Any) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, KernelContract) else value
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_bytes_once(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise SystemsPaperCurrencyIntegrityError(
                f"content-addressed source path changed: {path}"
            )
        return
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _addressed_payload(payload: dict[str, Any], hash_field: str) -> dict[str, Any]:
    normalized = _JSON_PAYLOAD_ADAPTER.dump_python(payload, mode="json")
    result = dict(payload)
    result[hash_field] = canonical_sha256(normalized)
    return result


def _normalized_source_text(body: bytes) -> str:
    decoded = body.decode("utf-8", errors="replace")
    decoded = html.unescape(decoded)
    decoded = re.sub(r"<script\b[^>]*>.*?</script>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<style\b[^>]*>.*?</style>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<[^>]+>", " ", decoded)
    decoded = decoded.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", decoded).strip().casefold()


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    title: str
    year: int
    url: str
    source_kind: SourceKind
    review_status: ReviewStatus
    identifier: str
    perspectives: tuple[LiteraturePerspective, ...]
    required_markers: tuple[str, ...]
    finding: str
    limitation: str


@dataclass(frozen=True)
class SourceResponse:
    status_code: int
    media_type: str
    body: bytes
    final_url: str


SourceFetcher = Callable[[str], SourceResponse]


def source_definitions() -> list[SourceDefinition]:
    """Return the primary-source registry frozen for the current-field audit."""

    mainstream = LiteraturePerspective.MAINSTREAM_SYSTEMS
    independent = LiteraturePerspective.INDEPENDENT_EVALUATION
    methods = LiteraturePerspective.STATISTICAL_METHODS
    openness = LiteraturePerspective.OPEN_SCIENCE
    human = LiteraturePerspective.HUMAN_RESPONSIBILITY
    return [
        SourceDefinition(
            source_id="ai-scientist-nature-2026",
            title="Towards end-to-end automation of AI research",
            year=2026,
            url="https://www.nature.com/articles/s41586-026-10265-5",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1038/s41586-026-10265-5",
            perspectives=(mainstream, human),
            required_markers=(
                "towards end-to-end automation of ai research",
                "manually filtered the most promising outputs",
                "cannot yet meet the standards of top-tier publications",
            ),
            finding=(
                "End-to-end ideation, experimentation, writing, and automated review are now "
                "peer-reviewed system capabilities; one of three selected manuscripts cleared "
                "a workshop review, not a main-conference standard."
            ),
            limitation=(
                "The submitted outputs were manually filtered, only one of three cleared a "
                "70-percent-acceptance workshop threshold, and the authors report recurring "
                "implementation, rigor, hallucination, and citation failures."
            ),
        ),
        SourceDefinition(
            source_id="co-scientist-nature-2026",
            title="Accelerating scientific discovery with Co-Scientist",
            year=2026,
            url="https://www.nature.com/articles/s41586-026-10644-y",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1038/s41586-026-10644-y",
            perspectives=(mainstream, human),
            required_markers=(
                "accelerating scientific discovery with co-scientist",
                "generate, debate and evolve research hypotheses",
                "expert-in-the-loop",
            ),
            finding=(
                "A multi-agent generate-debate-evolve loop with memory, ranking, evolution, "
                "expert steering, and experimental feedback makes generic iterative-agent "
                "architecture an insufficient novelty claim."
            ),
            limitation=(
                "The article calls for broader objective evaluation, more domain experts, "
                "rigorous peer review, and guardrails; expert preference is not objective truth."
            ),
        ),
        SourceDefinition(
            source_id="robin-nature-2026",
            title="A multi-agent system for automating scientific discovery",
            year=2026,
            url="https://www.nature.com/articles/s41586-026-10652-y",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1038/s41586-026-10652-y",
            perspectives=(mainstream, human),
            required_markers=(
                "a multi-agent system for automating scientific discovery",
                "reviewed by human scientists",
                "the cycle continues until a human has a satisfactory drug candidate",
            ),
            finding=(
                "Robin couples literature search, hypothesis generation, human-run experiments, "
                "multi-trajectory analysis, and iterative follow-up in experimental biology."
            ),
            limitation=(
                "Human scientists selected candidates and executed a human-generated protocol; "
                "the system is semi-autonomous rather than an evidence-free replacement for people."
            ),
        ),
        SourceDefinition(
            source_id="era-nature-2026",
            title="An AI system to help scientists write expert-level empirical software",
            year=2026,
            url="https://www.nature.com/articles/s41586-026-10658-6",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1038/s41586-026-10658-6",
            perspectives=(mainstream, methods),
            required_markers=(
                "an ai system to help scientists write expert-level empirical software",
                "maximize a quality metric",
                "critical distinction between optimizing empirical predictive models and performing genuine scientific discovery",
            ),
            finding=(
                "ERA uses tree search and machine-scored empirical software optimization across "
                "domains, while explicitly separating score optimization from scientific discovery."
            ),
            limitation=(
                "Scorable software performance does not establish causal or theoretical discovery; "
                "this distinction applies directly to Route B's constructed workflow score."
            ),
        ),
        SourceDefinition(
            source_id="kosmos-preprint-2025",
            title="Kosmos: An AI Scientist for Autonomous Discovery",
            year=2025,
            url="https://arxiv.org/abs/2511.02824",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2511.02824v2",
            perspectives=(mainstream, openness),
            required_markers=(
                "kosmos: an ai scientist for autonomous discovery",
                "structured world model",
                "ensuring its reasoning is traceable",
            ),
            finding=(
                "Kosmos demonstrates long-horizon parallel literature and data-analysis loops with "
                "a structured world model and claim-level traceability."
            ),
            limitation=(
                "The source is a preprint and its claimed discoveries require independent audit."
            ),
        ),
        SourceDefinition(
            source_id="astabench-iclr-2026",
            title="AstaBench: Rigorous Benchmarking of AI Agents with a Scientific Research Suite",
            year=2026,
            url="https://arxiv.org/abs/2510.21652",
            source_kind=SourceKind.CONFERENCE_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="arXiv:2510.21652v2; ICLR 2026",
            perspectives=(independent, methods),
            required_markers=(
                "astabench: rigorous benchmarking of ai agents with a scientific research suite",
                "57 agents across 22 agent classes",
                "far from solving the challenge of science research assistance",
            ),
            finding=(
                "A broad controlled suite across 57 agents finds progress on components but no "
                "solution to scientific research assistance."
            ),
            limitation=(
                "A benchmark measures the tasks and environments it samples; it does not itself "
                "establish open-ended discovery."
            ),
        ),
        SourceDefinition(
            source_id="paperbench-2025",
            title="PaperBench: Evaluating AI's Ability to Replicate AI Research",
            year=2025,
            url="https://arxiv.org/abs/2504.01848",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2504.01848v3",
            perspectives=(independent, human),
            required_markers=(
                "paperbench: evaluating ai's ability to replicate ai research",
                "21.0%",
                "models do not yet outperform the human baseline",
            ),
            finding=(
                "The strongest reported agent averaged 21 percent on AI-paper replication and did "
                "not exceed the recruited ML-PhD baseline."
            ),
            limitation=(
                "Paper replication is narrower than original discovery, but it is a necessary "
                "capability and exposes the weakness of self-evaluated local demonstrations."
            ),
        ),
        SourceDefinition(
            source_id="core-bench-2026-revision",
            title="CORE-Bench: Fostering the Credibility of Published Research Through a Computational Reproducibility Agent Benchmark",
            year=2026,
            url="https://arxiv.org/abs/2409.11363",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2409.11363v2",
            perspectives=(independent, methods),
            required_markers=(
                "core-bench: fostering the credibility of published research",
                "270 tasks based on 90 scientific papers",
                "best agent achieved an accuracy of 21%",
            ),
            finding=(
                "On 270 reproducibility tasks derived from 90 papers, the strongest baseline "
                "reached 21 percent on the hardest level."
            ),
            limitation=(
                "Reproducing supplied work is not novel discovery, but poor performance here "
                "undercuts broad autonomy claims."
            ),
        ),
        SourceDefinition(
            source_id="repro-bench-acl-2025",
            title="REPRO-Bench: Can Agentic AI Systems Assess the Reproducibility of Social Science Research?",
            year=2025,
            url="https://arxiv.org/abs/2507.18901",
            source_kind=SourceKind.CONFERENCE_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="arXiv:2507.18901v1; ACL 2025 Findings",
            perspectives=(independent, human),
            required_markers=(
                "repro-bench: can agentic ai systems assess the reproducibility of social science research?",
                "112 task instances",
                "accuracy of only 21.4%",
            ),
            finding=(
                "Realistic paper-plus-package reproducibility assessment remains difficult: the "
                "best representative agent achieved 21.4 percent before a task-specific improvement."
            ),
            limitation=(
                "The domain is social science and the endpoint is assessment rather than discovery."
            ),
        ),
        SourceDefinition(
            source_id="sciintegrity-bench-2026",
            title="SciIntegrity-Bench: A Benchmark for Evaluating Academic Integrity in AI Scientist Systems",
            year=2026,
            url="https://arxiv.org/abs/2605.10246",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2605.10246v2",
            perspectives=(independent, human),
            required_markers=(
                "sciintegrity-bench: a benchmark for evaluating academic integrity in ai scientist systems",
                "overall integrity problem rate reaches 34.2%",
                "honest acknowledgment of failure is the only correct response",
            ),
            finding=(
                "Across failure dilemmas, completion pressure elicited fabrication and no tested "
                "model had zero integrity failures, supporting explicit negative-result gates."
            ),
            limitation=(
                "This is a recent preprint; its value here is as adversarial risk evidence, not a "
                "settled field prevalence estimate."
            ),
        ),
        SourceDefinition(
            source_id="kosmos-independent-audit-2025",
            title="When AI Does Science: Evaluating the Autonomous AI Scientist KOSMOS in Radiation Biology",
            year=2025,
            url="https://arxiv.org/abs/2511.13825",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2511.13825v1",
            perspectives=(independent, human, methods),
            required_markers=(
                "when ai does science: evaluating the autonomous ai scientist kosmos in radiation biology",
                "one false hypothesis",
                "rigorous auditing against appropriate null models",
            ),
            finding=(
                "An independent reanalysis found one supported, one uncertain, and one false "
                "hypothesis, showing why plausible outputs need explicit null models."
            ),
            limitation=(
                "The audit covers one domain and a small set of hypotheses, and is itself a preprint."
            ),
        ),
        SourceDefinition(
            source_id="demsar-jmlr-2006",
            title="Statistical Comparisons of Classifiers over Multiple Data Sets",
            year=2006,
            url="https://jmlr.org/papers/v7/demsar06a.html",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="JMLR 7:1-30",
            perspectives=(methods,),
            required_markers=(
                "statistical comparisons of classifiers over multiple data sets",
                "janez dem",
                "multiple data sets",
            ),
            finding=(
                "Cross-dataset algorithm inference treats independent datasets, not repeated runs "
                "within a dataset, as the sampling units for generalization across tasks."
            ),
            limitation=(
                "The paper addresses classifier comparison, so its unit-of-analysis principle is "
                "applied here by analogy to independent workflow tasks."
            ),
        ),
        SourceDefinition(
            source_id="popper-2025",
            title="Automated Hypothesis Validation with Agentic Sequential Falsifications",
            year=2025,
            url="https://arxiv.org/abs/2502.09858",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2502.09858v1",
            perspectives=(mainstream, methods),
            required_markers=(
                "automated hypothesis validation with agentic sequential falsifications",
                "strict type-i error control",
                "design and execute falsification experiments",
            ),
            finding=(
                "Popper centers sequential falsification and explicit Type-I error control, raising "
                "the methodological bar beyond an internally scored repair loop."
            ),
            limitation=(
                "The retrieved version is a preprint and reports validation rather than a universal "
                "research-agent evaluation."
            ),
        ),
        SourceDefinition(
            source_id="ai-agents-that-matter-2024",
            title="AI Agents That Matter",
            year=2024,
            url="https://arxiv.org/abs/2407.01502",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2407.01502v1",
            perspectives=(independent, methods),
            required_markers=(
                "ai agents that matter",
                "inadequate holdout sets",
                "lack of reproducibility",
            ),
            finding=(
                "Agent evaluations need cost control, adequate holdouts, simple baselines, and "
                "standardized reproducible evaluation before architecture gains are credible."
            ),
            limitation=(
                "The examples are broader agent benchmarks rather than autonomous-science systems."
            ),
        ),
        SourceDefinition(
            source_id="benchmarkcards-2024",
            title="BenchmarkCards: Standardized Documentation for Large Language Model Benchmarks",
            year=2024,
            url="https://arxiv.org/abs/2410.12974",
            source_kind=SourceKind.PREPRINT,
            review_status=ReviewStatus.PREPRINT,
            identifier="arXiv:2410.12974v3",
            perspectives=(methods, openness),
            required_markers=(
                "benchmarkcards: standardized documentation for large language model benchmarks",
                "arxiv:2410.12974",
                "simplify benchmark selection and enhance transparency",
            ),
            finding=(
                "Structured benchmark documentation should expose intended risks, task properties, "
                "evaluation methods, and limitations instead of relying on a positioning check table."
            ),
            limitation=(
                "BenchmarkCards documents evaluation objects but does not define correctness or "
                "replace an independent validation study."
            ),
        ),
        SourceDefinition(
            source_id="ro-crate-specification-1-3",
            title="RO-Crate Specification",
            year=2026,
            url="https://www.researchobject.org/ro-crate/specification.html",
            source_kind=SourceKind.STANDARD,
            review_status=ReviewStatus.NORMATIVE,
            identifier="RO-Crate 1.3",
            perspectives=(openness,),
            required_markers=(
                "ro-crate specification",
                "ro-crate 1.3 specification has been released",
                "current long term release",
            ),
            finding=(
                "RO-Crate 1.3 provides a current interoperable JSON-LD packaging target for data, "
                "software, workflows, provenance, and contextual entities."
            ),
            limitation=(
                "Conformance metadata improves interoperability but does not validate a scientific claim."
            ),
        ),
        SourceDefinition(
            source_id="prov-o-w3c-2013",
            title="PROV-O: The PROV Ontology",
            year=2013,
            url="https://www.w3.org/TR/prov-o/",
            source_kind=SourceKind.STANDARD,
            review_status=ReviewStatus.NORMATIVE,
            identifier="W3C Recommendation 30 April 2013",
            perspectives=(openness, methods),
            required_markers=(
                "prov-o: the prov ontology",
                "w3c recommendation",
                "represent provenance information",
            ),
            finding=(
                "PROV-O supplies interoperable entity, activity, agent, generation, use, and "
                "derivation relations for machine-readable lineage."
            ),
            limitation=(
                "A provenance ontology records lineage; it cannot by itself establish correctness."
            ),
        ),
        SourceDefinition(
            source_id="fair4rs-2022",
            title="Introducing the FAIR Principles for research software",
            year=2022,
            url="https://www.nature.com/articles/s41597-022-01710-x",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1038/s41597-022-01710-x",
            perspectives=(openness,),
            required_markers=(
                "introducing the fair principles for research software",
                "fair principles for research software",
                "findable, accessible, interoperable and reusable",
            ),
            finding=(
                "Research software should be findable, accessible, interoperable, and reusable; "
                "hash completeness alone addresses only part of that target."
            ),
            limitation=(
                "FAIR is a stewardship framework, not a guarantee of reproducibility or validity."
            ),
        ),
        SourceDefinition(
            source_id="workflow-run-ro-crate-2024",
            title="Recording provenance of workflow runs with RO-Crate",
            year=2024,
            url=(
                "https://journals.plos.org/plosone/article?id="
                "10.1371%2Fjournal.pone.0309210"
            ),
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1371/journal.pone.0309210",
            perspectives=(openness, methods),
            required_markers=(
                "recording provenance of workflow runs with ro-crate",
                "provenance run crate profile",
                "inputs, outputs, code",
            ),
            finding=(
                "Workflow Run RO-Crate profiles capture prospective and retrospective execution "
                "provenance and bind code, inputs, outputs, and actions in a portable object."
            ),
            limitation=(
                "Profile adoption adds machine actionability but still requires domain validation "
                "and independent result checks."
            ),
        ),
        SourceDefinition(
            source_id="acm-artifact-policy-1-1",
            title="Artifact Review and Badging - Current",
            year=2020,
            url=(
                "https://prod-www.acm.bloomreach.cloud/publications/policies/"
                "artifact-review-and-badging-current"
            ),
            source_kind=SourceKind.POLICY,
            review_status=ReviewStatus.NORMATIVE,
            identifier="ACM Artifact Review and Badging v1.1",
            perspectives=(openness, human),
            required_markers=(
                "artifact review and badging",
                "independent audit",
                "results validated",
            ),
            finding=(
                "ACM separates artifact availability/functionality from independently validated "
                "results, so a clean rerun by the authors is not independent confirmation."
            ),
            limitation=(
                "The generic policy must be combined with the rules of a human-selected target venue."
            ),
        ),
        SourceDefinition(
            source_id="ai-scientist-risks-nature-communications-2025",
            title="Risks of AI scientists: prioritizing safeguarding over autonomy",
            year=2025,
            url="https://www.nature.com/articles/s41467-025-63913-1",
            source_kind=SourceKind.JOURNAL_ARTICLE,
            review_status=ReviewStatus.PEER_REVIEWED,
            identifier="doi:10.1038/s41467-025-63913-1",
            perspectives=(human,),
            required_markers=(
                "risks of ai scientists: prioritizing safeguarding over autonomy",
                "human regulation",
                "robust benchmarks",
            ),
            finding=(
                "AI-scientist governance requires human regulation, agent safeguards, environmental "
                "feedback, audits, domain expertise, benchmarks, and review gates."
            ),
            limitation=(
                "This is a risk-scoping perspective, not an empirical performance comparison."
            ),
        ),
    ]


def fetch_source_response(url: str) -> SourceResponse:
    """Fetch one public primary source with bounded retries and byte size."""

    context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "AutoResearch-Task263.7.0/1.0 (+local publication audit)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise PrimarySourceFetchError(f"source exceeds 8 MB: {url}")
                return SourceResponse(
                    status_code=int(response.status),
                    media_type=response.headers.get_content_type(),
                    body=body,
                    final_url=response.geturl(),
                )
        except (OSError, urllib.error.URLError, PrimarySourceFetchError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise PrimarySourceFetchError(f"source fetch failed for {url}: {last_error}")


class PrimarySourceSnapshot(KernelContract):
    schema_version: Literal["systems-paper-primary-source-snapshot-v1"] = (
        "systems-paper-primary-source-snapshot-v1"
    )
    source_id: StableId
    requested_url: NonEmptyText
    final_url: NonEmptyText
    retrieved_at: datetime
    status_code: int = Field(ge=100, le=599)
    media_type: NonEmptyText
    byte_count: int = Field(ge=1, le=8_000_000)
    body_sha256: Sha256
    required_markers: list[NonEmptyText]
    relative_path: NonEmptyText
    snapshot_hash: Sha256

    @field_validator("retrieved_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source retrieval time must be timezone aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_snapshot(self) -> PrimarySourceSnapshot:
        if self.status_code != 200:
            raise PrimarySourceFetchError(
                f"source {self.source_id} returned status {self.status_code}"
            )
        if self.snapshot_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("source snapshot hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        definition: SourceDefinition,
        response: SourceResponse,
        retrieved_at: datetime,
    ) -> PrimarySourceSnapshot:
        if response.status_code != 200:
            raise PrimarySourceFetchError(
                f"source {definition.source_id} returned status {response.status_code}"
            )
        if not response.body:
            raise PrimarySourceFetchError(f"source {definition.source_id} returned no bytes")
        normalized = _normalized_source_text(response.body)
        missing = [
            marker
            for marker in definition.required_markers
            if marker.casefold() not in normalized
        ]
        if missing:
            raise PrimarySourceFetchError(
                f"source {definition.source_id} is missing markers: {missing}"
            )
        body_hash = _sha256_bytes(response.body)
        suffix = "html" if "html" in response.media_type.casefold() else "bin"
        relative_path = f"{AUDIT_SOURCE_DIRECTORY}/{definition.source_id}--{body_hash}.{suffix}"
        payload = {
            "schema_version": "systems-paper-primary-source-snapshot-v1",
            "source_id": definition.source_id,
            "requested_url": definition.url,
            "final_url": response.final_url,
            "retrieved_at": retrieved_at,
            "status_code": response.status_code,
            "media_type": response.media_type,
            "byte_count": len(response.body),
            "body_sha256": body_hash,
            "required_markers": sorted(definition.required_markers),
            "relative_path": relative_path,
        }
        return cls.model_validate(_addressed_payload(payload, "snapshot_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"snapshot_hash"}))


class VerifiedSourceRecord(KernelContract):
    schema_version: Literal["systems-paper-verified-source-v1"] = (
        "systems-paper-verified-source-v1"
    )
    source_id: StableId
    title: NonEmptyText
    year: int = Field(ge=1900, le=2100)
    url: NonEmptyText
    identifier: NonEmptyText
    source_kind: SourceKind
    review_status: ReviewStatus
    perspectives: list[LiteraturePerspective]
    evidence_locator: NonEmptyText
    finding: NonEmptyText
    limitation: NonEmptyText
    snapshot: PrimarySourceSnapshot
    record_hash: Sha256

    @field_validator("perspectives")
    @classmethod
    def _sort_perspectives(
        cls, value: list[LiteraturePerspective]
    ) -> list[LiteraturePerspective]:
        normalized = sorted(set(value), key=lambda item: item.value)
        if not normalized:
            raise ValueError("source must cover at least one perspective")
        return normalized

    @model_validator(mode="after")
    def _validate_record(self) -> VerifiedSourceRecord:
        if self.source_id != self.snapshot.source_id:
            raise ValueError("source record and snapshot IDs differ")
        if self.record_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("source record hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        definition: SourceDefinition,
        snapshot: PrimarySourceSnapshot,
    ) -> VerifiedSourceRecord:
        payload = {
            "schema_version": "systems-paper-verified-source-v1",
            "source_id": definition.source_id,
            "title": definition.title,
            "year": definition.year,
            "url": definition.url,
            "identifier": definition.identifier,
            "source_kind": definition.source_kind,
            "review_status": definition.review_status,
            "perspectives": sorted(definition.perspectives, key=lambda item: item.value),
            "evidence_locator": f"{definition.url}#verified-markers",
            "finding": definition.finding,
            "limitation": definition.limitation,
            "snapshot": snapshot,
        }
        return cls.model_validate(_addressed_payload(payload, "record_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"record_hash"}))


class VerifiedSourceRegistry(KernelContract):
    schema_version: Literal["systems-paper-source-registry-v1"] = (
        "systems-paper-source-registry-v1"
    )
    audit_cutoff: datetime
    sources: list[VerifiedSourceRecord]
    perspective_counts: dict[LiteraturePerspective, int]
    peer_reviewed_count: int = Field(ge=1)
    preprint_count: int = Field(ge=1)
    normative_count: int = Field(ge=1)
    registry_hash: Sha256

    @field_validator("audit_cutoff")
    @classmethod
    def _cutoff_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit cutoff must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator("sources")
    @classmethod
    def _sort_sources(cls, value: list[VerifiedSourceRecord]) -> list[VerifiedSourceRecord]:
        normalized = sorted(value, key=lambda item: item.source_id)
        if len(normalized) != len({item.source_id for item in normalized}):
            raise ValueError("source IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_registry(self) -> VerifiedSourceRegistry:
        expected_counts = Counter(
            perspective for source in self.sources for perspective in source.perspectives
        )
        if dict(expected_counts) != self.perspective_counts:
            raise ValueError("source perspective counts are stale")
        if set(self.perspective_counts) != set(LiteraturePerspective):
            raise ValueError("all five literature perspectives are required")
        if any(count < 3 for count in self.perspective_counts.values()):
            raise ValueError("each literature perspective needs at least three sources")
        statuses = Counter(source.review_status for source in self.sources)
        if self.peer_reviewed_count != statuses[ReviewStatus.PEER_REVIEWED]:
            raise ValueError("peer-reviewed source count mismatch")
        if self.preprint_count != statuses[ReviewStatus.PREPRINT]:
            raise ValueError("preprint source count mismatch")
        if self.normative_count != statuses[ReviewStatus.NORMATIVE]:
            raise ValueError("normative source count mismatch")
        if self.registry_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("source registry hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        audit_cutoff: datetime,
        sources: Sequence[VerifiedSourceRecord],
    ) -> VerifiedSourceRegistry:
        ordered = sorted(sources, key=lambda item: item.source_id)
        counts = Counter(perspective for item in ordered for perspective in item.perspectives)
        statuses = Counter(item.review_status for item in ordered)
        payload = {
            "schema_version": "systems-paper-source-registry-v1",
            "audit_cutoff": audit_cutoff,
            "sources": ordered,
            "perspective_counts": dict(sorted(counts.items(), key=lambda item: item[0].value)),
            "peer_reviewed_count": statuses[ReviewStatus.PEER_REVIEWED],
            "preprint_count": statuses[ReviewStatus.PREPRINT],
            "normative_count": statuses[ReviewStatus.NORMATIVE],
        }
        return cls.model_validate(_addressed_payload(payload, "registry_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"registry_hash"}))


class AuditResearchBrief(KernelContract):
    schema_version: Literal["systems-paper-currency-brief-v1"] = (
        "systems-paper-currency-brief-v1"
    )
    task_id: Literal["263.7.0"] = "263.7.0"
    frozen_before_reanalysis: Literal[True] = True
    research_questions: list[NonEmptyText]
    evidence_perspectives: list[LiteraturePerspective]
    central_angle: NonEmptyText
    intended_reader: NonEmptyText
    non_goals: list[NonEmptyText]
    brief_hash: Sha256

    @model_validator(mode="after")
    def _validate_brief(self) -> AuditResearchBrief:
        if len(self.research_questions) != 3:
            raise ValueError("currency audit requires exactly three research questions")
        if set(self.evidence_perspectives) != set(LiteraturePerspective):
            raise ValueError("currency audit requires five evidence perspectives")
        if self.brief_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("research brief hash mismatch")
        return self

    @classmethod
    def create(cls) -> AuditResearchBrief:
        payload = {
            "schema_version": "systems-paper-currency-brief-v1",
            "task_id": TASK_ID,
            "frozen_before_reanalysis": True,
            "research_questions": [
                (
                    "RQ1: After the 2025-2026 AI Scientist, Co-Scientist, Robin, ERA, "
                    "Kosmos, and current scientific-agent benchmarks, does Task 260 Route B's "
                    "central systems claim remain differentiated?"
                ),
                (
                    "RQ2: Does the 10-task by 3-deterministic-seed design support independent-unit "
                    "inference for the reported paired effect and interval?"
                ),
                (
                    "RQ3: Which minimum repairs can use the frozen evidence, and which require "
                    "new independent experiments or human judgment?"
                ),
            ],
            "evidence_perspectives": list(LiteraturePerspective),
            "central_angle": (
                "The package is a strong hash-linked research object but a weak confirmatory "
                "identification design: deterministic seed duplicates, co-designed faults and "
                "repairs, limited external comparators, and stale related work constrain its claim."
            ),
            "intended_reader": (
                "The project owner deciding whether to repair the manuscript from existing evidence "
                "or commission an independently authored confirmation matrix."
            ),
            "non_goals": [
                "Do not rewrite or replace the immutable Task 260 v2 package.",
                "Do not authorize publication, public release, venue choice, or submission.",
                "Do not substitute automated review for independent human scientific review.",
            ],
        }
        return cls.model_validate(_addressed_payload(payload, "brief_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"brief_hash"}))


class ParentSystemsPaperEvidence(KernelContract):
    schema_version: Literal["task260-parent-systems-paper-evidence-v1"] = (
        "task260-parent-systems-paper-evidence-v1"
    )
    parent_git_commit: StableId
    package_relative_path: NonEmptyText
    package_id: Literal["task260-final-paper-v2"] = "task260-final-paper-v2"
    package_hash: Sha256
    package_file_sha256: Sha256
    manuscript_pdf_sha256: Sha256
    systems_result_hash: Sha256
    systems_result_file_sha256: Sha256
    systems_gate_hash: Sha256
    systems_gate_file_sha256: Sha256
    matrix_file_sha256: Sha256
    preregistration_file_sha256: Sha256
    external_submission_authorized: Literal[False] = False
    immutable_parent: Literal[True] = True
    parent_evidence_hash: Sha256

    @model_validator(mode="after")
    def _validate_parent(self) -> ParentSystemsPaperEvidence:
        expected = {
            "parent_git_commit": PARENT_GIT_COMMIT,
            "package_hash": PARENT_PACKAGE_HASH,
            "package_file_sha256": PARENT_PACKAGE_FILE_SHA256,
            "manuscript_pdf_sha256": PARENT_PDF_SHA256,
            "systems_result_hash": PARENT_SYSTEMS_RESULT_HASH,
            "systems_result_file_sha256": PARENT_SYSTEMS_RESULT_FILE_SHA256,
            "systems_gate_hash": PARENT_SYSTEMS_GATE_HASH,
            "systems_gate_file_sha256": PARENT_SYSTEMS_GATE_FILE_SHA256,
            "matrix_file_sha256": PARENT_MATRIX_FILE_SHA256,
            "preregistration_file_sha256": PARENT_PREREGISTRATION_FILE_SHA256,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise SystemsPaperCurrencyIntegrityError(
                    f"Task 260 parent binding changed: {field_name}"
                )
        if self.parent_evidence_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("parent evidence hash mismatch")
        return self

    @classmethod
    def from_package(
        cls,
        package_dir: Path,
        *,
        package_relative_path: str = "runs/manual-live/task260-final-paper-v2",
    ) -> ParentSystemsPaperEvidence:
        root = package_dir.resolve()
        package_path = root / "paper-package.json"
        result_path = root / "frozen-inputs/systems-benchmark-result.json"
        gate_path = root / "frozen-inputs/systems-contribution-gate.json"
        matrix_path = root / "frozen-inputs/systems-matrix-manifest.json"
        prereg_path = root / "frozen-inputs/systems-preregistration.json"
        pdf_path = root / "paper/source/main.pdf"
        for required in (
            package_path,
            result_path,
            gate_path,
            matrix_path,
            prereg_path,
            pdf_path,
        ):
            if not required.is_file():
                raise SystemsPaperCurrencyIntegrityError(f"parent artifact missing: {required}")
        package = json.loads(package_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if package.get("package_id") != PARENT_PACKAGE_ID:
            raise SystemsPaperCurrencyIntegrityError("unexpected parent package ID")
        if package.get("package_hash") != PARENT_PACKAGE_HASH:
            raise SystemsPaperCurrencyIntegrityError("unexpected parent package hash")
        if package.get("systems_result_hash") != PARENT_SYSTEMS_RESULT_HASH:
            raise SystemsPaperCurrencyIntegrityError("parent package result binding changed")
        if package.get("systems_gate_hash") != PARENT_SYSTEMS_GATE_HASH:
            raise SystemsPaperCurrencyIntegrityError("parent package gate binding changed")
        if result.get("result_hash") != PARENT_SYSTEMS_RESULT_HASH:
            raise SystemsPaperCurrencyIntegrityError("parent systems result hash changed")
        if gate.get("gate_hash") != PARENT_SYSTEMS_GATE_HASH:
            raise SystemsPaperCurrencyIntegrityError("parent systems gate hash changed")
        if any(
            item.get("external_submission_authorized") is not False
            for item in (package, result, gate)
        ):
            raise SystemsPaperCurrencyIntegrityError("parent submission boundary changed")
        payload = {
            "schema_version": "task260-parent-systems-paper-evidence-v1",
            "parent_git_commit": PARENT_GIT_COMMIT,
            "package_relative_path": package_relative_path,
            "package_id": PARENT_PACKAGE_ID,
            "package_hash": PARENT_PACKAGE_HASH,
            "package_file_sha256": _file_sha256(package_path),
            "manuscript_pdf_sha256": _file_sha256(pdf_path),
            "systems_result_hash": PARENT_SYSTEMS_RESULT_HASH,
            "systems_result_file_sha256": _file_sha256(result_path),
            "systems_gate_hash": PARENT_SYSTEMS_GATE_HASH,
            "systems_gate_file_sha256": _file_sha256(gate_path),
            "matrix_file_sha256": _file_sha256(matrix_path),
            "preregistration_file_sha256": _file_sha256(prereg_path),
            "external_submission_authorized": False,
            "immutable_parent": True,
        }
        return cls.model_validate(_addressed_payload(payload, "parent_evidence_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"parent_evidence_hash"}))


class TaskLevelComparison(KernelContract):
    schema_version: Literal["systems-paper-task-level-comparison-v1"] = (
        "systems-paper-task-level-comparison-v1"
    )
    task_id: StableId
    family: Literal["uci", "mdbench"]
    seeds: list[int]
    full_loop_success_by_seed: dict[str, bool]
    execute_once_success_by_seed: dict[str, bool]
    full_loop_scientific_hashes: list[Sha256]
    execute_once_scientific_hashes: list[Sha256]
    deterministic_seed_duplicate: Literal[True] = True
    task_difference: float = Field(ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def _validate_task(self) -> TaskLevelComparison:
        if self.seeds != list(EXPECTED_SEEDS):
            raise ValueError("unexpected Task 260 seed set")
        if len(set(self.full_loop_scientific_hashes)) != 1:
            raise ValueError("full-loop scientific results vary across deterministic seeds")
        if len(set(self.execute_once_scientific_hashes)) != 1:
            raise ValueError("execute-once scientific results vary across deterministic seeds")
        full = set(self.full_loop_success_by_seed.values())
        baseline = set(self.execute_once_success_by_seed.values())
        if len(full) != 1 or len(baseline) != 1:
            raise ValueError("seed success outcomes are not duplicates")
        expected = float(next(iter(full))) - float(next(iter(baseline)))
        if self.task_difference != expected:
            raise ValueError("task-level difference does not match collapsed outcomes")
        return self


def _quantile(values: Sequence[float], probability: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def bootstrap_mean_interval(
    values: Sequence[float], *, resamples: int, seed: int
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires observations")
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(
        statistics.fmean(values[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    )
    return _quantile(samples, 0.025), _quantile(samples, 0.975)


def exact_sign_test(values: Sequence[float]) -> tuple[int, int, int, float, float]:
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    ties = sum(value == 0 for value in values)
    non_ties = wins + losses
    if non_ties == 0:
        return wins, losses, ties, 1.0, 1.0
    denominator = 2**non_ties
    upper = sum(math.comb(non_ties, k) for k in range(wins, non_ties + 1)) / denominator
    lower = sum(math.comb(non_ties, k) for k in range(0, wins + 1)) / denominator
    return wins, losses, ties, upper, min(1.0, 2.0 * min(upper, lower))


class IndependentUnitAudit(KernelContract):
    schema_version: Literal["systems-paper-independent-unit-audit-v1"] = (
        "systems-paper-independent-unit-audit-v1"
    )
    parent_evidence_hash: Sha256
    task_comparisons: list[TaskLevelComparison]
    seed_cell_pair_count: Literal[30] = 30
    independent_task_count: Literal[10] = 10
    deterministic_seed_duplicate_group_count: Literal[20] = 20
    all_mode_task_seed_outputs_duplicate: Literal[True] = True
    frozen_seed_pair_differences: list[float]
    frozen_seed_pair_mean: float
    frozen_seed_pair_ci95: tuple[float, float]
    task_level_differences: list[float]
    task_level_mean: float
    task_level_bootstrap_resamples: Literal[20000] = 20_000
    task_level_bootstrap_seed: Literal[2604] = 2604
    task_level_ci95: tuple[float, float]
    sign_test_wins: int = Field(ge=0)
    sign_test_losses: int = Field(ge=0)
    sign_test_ties: int = Field(ge=0)
    sign_test_one_sided_p: float = Field(ge=0.0, le=1.0)
    sign_test_two_sided_p: float = Field(ge=0.0, le=1.0)
    family_task_counts: dict[Literal["uci", "mdbench"], int]
    family_mean_differences: dict[Literal["uci", "mdbench"], float]
    family_balanced_mean: float
    original_interval_valid_for_independent_task_inference: Literal[False] = False
    original_contribution_gate_reusable_for_publication_inference: Literal[False] = False
    conclusion: NonEmptyText
    audit_hash: Sha256

    @field_validator("task_comparisons")
    @classmethod
    def _unique_tasks(cls, value: list[TaskLevelComparison]) -> list[TaskLevelComparison]:
        if len(value) != 10 or len({item.task_id for item in value}) != 10:
            raise ValueError("independent-unit audit requires ten unique tasks")
        return value

    @model_validator(mode="after")
    def _validate_audit(self) -> IndependentUnitAudit:
        expected_task = [item.task_difference for item in self.task_comparisons]
        if self.task_level_differences != expected_task:
            raise ValueError("task-level differences and comparisons differ")
        if self.frozen_seed_pair_differences != expected_task * 3:
            raise ValueError("frozen seed-pair vector is not three exact task-vector copies")
        if not math.isclose(self.task_level_mean, statistics.fmean(expected_task)):
            raise ValueError("task-level mean mismatch")
        expected_ci = bootstrap_mean_interval(
            expected_task,
            resamples=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
        )
        if self.task_level_ci95 != expected_ci:
            raise ValueError("task-level bootstrap interval mismatch")
        wins, losses, ties, one_sided, two_sided = exact_sign_test(expected_task)
        observed = (
            self.sign_test_wins,
            self.sign_test_losses,
            self.sign_test_ties,
            self.sign_test_one_sided_p,
            self.sign_test_two_sided_p,
        )
        expected_sign = (wins, losses, ties, one_sided, two_sided)
        if observed != expected_sign:
            raise ValueError("exact sign test mismatch")
        if self.audit_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("independent-unit audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> IndependentUnitAudit:
        payload = {
            "schema_version": "systems-paper-independent-unit-audit-v1",
            "seed_cell_pair_count": 30,
            "independent_task_count": 10,
            "deterministic_seed_duplicate_group_count": 20,
            "all_mode_task_seed_outputs_duplicate": True,
            "task_level_bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "task_level_bootstrap_seed": BOOTSTRAP_SEED,
            "original_interval_valid_for_independent_task_inference": False,
            "original_contribution_gate_reusable_for_publication_inference": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "audit_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"audit_hash"}))


def build_independent_unit_audit(
    package_dir: Path,
    *,
    parent: ParentSystemsPaperEvidence,
) -> IndependentUnitAudit:
    """Recompute Route B at the independent task unit from frozen cell artifacts."""

    root = package_dir.resolve()
    prereg = json.loads(
        (root / "frozen-inputs/systems-preregistration.json").read_text(encoding="utf-8")
    )
    matrix = json.loads(
        (root / "frozen-inputs/systems-matrix-manifest.json").read_text(encoding="utf-8")
    )
    frozen_result = json.loads(
        (root / "frozen-inputs/systems-benchmark-result.json").read_text(encoding="utf-8")
    )
    if tuple(prereg.get("seeds", [])) != EXPECTED_SEEDS:
        raise SystemsPaperCurrencyIntegrityError("Task 260 seed set changed")
    tasks = prereg.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 10:
        raise SystemsPaperCurrencyIntegrityError("Task 260 task list changed")
    cells = matrix.get("cells")
    if not isinstance(cells, list) or len(cells) != 210:
        raise SystemsPaperCurrencyIntegrityError("Task 260 matrix size changed")
    matrix_index = {str(item["cell_id"]): item for item in cells}
    comparisons: list[TaskLevelComparison] = []
    for task in tasks:
        task_id = str(task["task_id"])
        family = str(task["family"])
        mode_success: dict[str, dict[str, bool]] = {
            "full_loop": {},
            "execute_once": {},
        }
        mode_hashes: dict[str, list[str]] = {"full_loop": [], "execute_once": []}
        for mode in ("full_loop", "execute_once"):
            for seed in EXPECTED_SEEDS:
                cell_id = f"{mode}--seed-{seed}--{task_id}"
                entry = matrix_index.get(cell_id)
                if entry is None:
                    raise SystemsPaperCurrencyIntegrityError(f"matrix cell missing: {cell_id}")
                path = (
                    root
                    / "dossier/route-b-systems-benchmark/cells"
                    / cell_id
                    / "cell-result.json"
                )
                cell = json.loads(path.read_text(encoding="utf-8"))
                if cell.get("cell_id") != cell_id:
                    raise SystemsPaperCurrencyIntegrityError(f"cell identity changed: {cell_id}")
                if cell.get("result_hash") != entry.get("result_hash"):
                    raise SystemsPaperCurrencyIntegrityError(f"cell result hash changed: {cell_id}")
                if cell.get("scientific_result_hash") != entry.get("scientific_result_hash"):
                    raise SystemsPaperCurrencyIntegrityError(
                        f"cell scientific hash changed: {cell_id}"
                    )
                if cell.get("task_id") != task_id or cell.get("family") != family:
                    raise SystemsPaperCurrencyIntegrityError(f"cell task metadata changed: {cell_id}")
                if cell.get("mode") != mode or cell.get("seed") != seed:
                    raise SystemsPaperCurrencyIntegrityError(f"cell mode/seed changed: {cell_id}")
                mode_success[mode][str(seed)] = bool(cell["task_success"])
                mode_hashes[mode].append(str(cell["scientific_result_hash"]))
        full_success = next(iter(mode_success["full_loop"].values()))
        baseline_success = next(iter(mode_success["execute_once"].values()))
        comparisons.append(
            TaskLevelComparison(
                task_id=task_id,
                family=cast(Literal["uci", "mdbench"], family),
                seeds=list(EXPECTED_SEEDS),
                full_loop_success_by_seed=mode_success["full_loop"],
                execute_once_success_by_seed=mode_success["execute_once"],
                full_loop_scientific_hashes=mode_hashes["full_loop"],
                execute_once_scientific_hashes=mode_hashes["execute_once"],
                deterministic_seed_duplicate=True,
                task_difference=float(full_success) - float(baseline_success),
            )
        )
    task_differences = [item.task_difference for item in comparisons]
    frozen_differences = [float(value) for value in frozen_result["paired_differences"]]
    if frozen_differences != task_differences * 3:
        raise SystemsPaperCurrencyIntegrityError(
            "Task 260 paired vector is not three exact copies of the task vector"
        )
    task_ci = bootstrap_mean_interval(
        task_differences,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
    )
    wins, losses, ties, one_sided, two_sided = exact_sign_test(task_differences)
    family_values: dict[str, list[float]] = defaultdict(list)
    for item in comparisons:
        family_values[item.family].append(item.task_difference)
    family_means = {
        cast(Literal["uci", "mdbench"], family): statistics.fmean(values)
        for family, values in sorted(family_values.items())
    }
    family_counts = {
        cast(Literal["uci", "mdbench"], family): len(values)
        for family, values in sorted(family_values.items())
    }
    return IndependentUnitAudit.create(
        parent_evidence_hash=parent.parent_evidence_hash,
        task_comparisons=comparisons,
        frozen_seed_pair_differences=frozen_differences,
        frozen_seed_pair_mean=float(frozen_result["paired_mean_gain_vs_execute_once"]),
        frozen_seed_pair_ci95=(
            float(frozen_result["bootstrap_ci95_lower"]),
            float(frozen_result["bootstrap_ci95_upper"]),
        ),
        task_level_differences=task_differences,
        task_level_mean=statistics.fmean(task_differences),
        task_level_ci95=task_ci,
        sign_test_wins=wins,
        sign_test_losses=losses,
        sign_test_ties=ties,
        sign_test_one_sided_p=one_sided,
        sign_test_two_sided_p=two_sided,
        family_task_counts=family_counts,
        family_mean_differences=family_means,
        family_balanced_mean=statistics.fmean(family_means.values()),
        conclusion=(
            "The 30 task-seed pairs contain only 10 independent task outcomes. The three seeds "
            "are byte-level scientific duplicates within every mode-task group and support "
            "idempotency, not sampling variation. Publication inference must therefore use the "
            "task-level interval [0.2, 0.8], disclose the two-sided sign-test p-value 0.0625, and "
            "treat the original internal gate as historical engineering evidence only."
        ),
    )


BANNED_AI_TONE_TERMS = (
    "innovative",
    "pioneering",
    "revolutionary paradigm",
    "transformative framework",
    "superior",
    "surpass",
    "excel",
    "remarkable",
    "unprecedented",
    "achieves sota",
    "breakthrough performance",
    "general-purpose",
    "is capable of",
    "notably",
    "yet",
    "yielding",
    "at its essence",
    "encompass",
    "differentiate",
    "reveal",
    "underscore",
    "exhibit superior capability",
    "exceed",
    "pave the way for",
    "highlight the potential of",
    "profound challenges",
    "stems from",
    "rigid",
    "impede",
)


class LanguagePatternHit(KernelContract):
    schema_version: Literal["systems-paper-language-pattern-hit-v1"] = (
        "systems-paper-language-pattern-hit-v1"
    )
    pattern_kind: Literal["banned-ai-tone", "em-dash"]
    pattern: NonEmptyText
    relative_path: NonEmptyText
    line_number: int = Field(ge=1)
    line_excerpt: NonEmptyText
    severity: FindingSeverity


class PaperLanguageScan(KernelContract):
    schema_version: Literal["systems-paper-language-scan-v1"] = (
        "systems-paper-language-scan-v1"
    )
    scanned_extensions: list[Literal[".tex", ".bib"]]
    scanned_files: list[NonEmptyText]
    banned_terms: list[NonEmptyText]
    term_counts: dict[NonEmptyText, int]
    em_dash_count: int = Field(ge=0)
    hits: list[LanguagePatternHit]
    no_banned_tone_or_em_dash: bool
    external_plagiarism_checker_still_required: Literal[True] = True
    language_scan_hash: Sha256

    @model_validator(mode="after")
    def _validate_scan(self) -> PaperLanguageScan:
        if self.scanned_extensions != [".bib", ".tex"]:
            raise ValueError("paper scan extension set changed")
        if self.no_banned_tone_or_em_dash != (not self.hits):
            raise ValueError("paper language scan verdict is stale")
        if self.em_dash_count != sum(hit.pattern_kind == "em-dash" for hit in self.hits):
            raise ValueError("paper em-dash count mismatch")
        calculated_counts = Counter(
            hit.pattern for hit in self.hits if hit.pattern_kind == "banned-ai-tone"
        )
        if dict(sorted(calculated_counts.items())) != self.term_counts:
            raise ValueError("paper banned-term counts mismatch")
        if self.language_scan_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("paper language scan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaperLanguageScan:
        payload = {
            "schema_version": "systems-paper-language-scan-v1",
            "scanned_extensions": [".bib", ".tex"],
            "external_plagiarism_checker_still_required": True,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "language_scan_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"language_scan_hash"}))


def scan_paper_language(package_dir: Path) -> PaperLanguageScan:
    """Scan all manuscript source and bibliography files under the frozen paper source."""

    paper_root = package_dir.resolve() / "paper/source"
    files = sorted(
        path
        for path in paper_root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".tex", ".bib"}
    )
    if not files:
        raise SystemsPaperCurrencyIntegrityError("no Task 260 paper source files found")
    raw_hits: list[tuple[str, str, int, str]] = []
    for path in files:
        relative = path.relative_to(package_dir.resolve()).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            folded = line.casefold()
            for term in BANNED_AI_TONE_TERMS:
                start = 0
                while True:
                    index = folded.find(term, start)
                    if index < 0:
                        break
                    raw_hits.append(("banned-ai-tone", term, line_number, f"{relative}\n{line}"))
                    start = index + max(1, len(term))
            for _match in re.finditer("—", line):
                raw_hits.append(("em-dash", "—", line_number, f"{relative}\n{line}"))
    term_counts = Counter(pattern for kind, pattern, _, _ in raw_hits if kind == "banned-ai-tone")
    hits: list[LanguagePatternHit] = []
    for kind, pattern, line_number, combined in raw_hits:
        relative, excerpt = combined.split("\n", 1)
        severity = (
            FindingSeverity.MAJOR
            if kind == "em-dash" or term_counts[pattern] >= 3
            else FindingSeverity.MINOR
        )
        hits.append(
            LanguagePatternHit(
                pattern_kind=cast(Literal["banned-ai-tone", "em-dash"], kind),
                pattern=pattern,
                relative_path=relative,
                line_number=line_number,
                line_excerpt=excerpt.strip() or "<blank>",
                severity=severity,
            )
        )
    relative_files = [path.relative_to(package_dir.resolve()).as_posix() for path in files]
    return PaperLanguageScan.create(
        scanned_files=relative_files,
        banned_terms=sorted(BANNED_AI_TONE_TERMS),
        term_counts=dict(sorted(term_counts.items())),
        em_dash_count=sum(kind == "em-dash" for kind, _, _, _ in raw_hits),
        hits=hits,
        no_banned_tone_or_em_dash=not hits,
    )


class PaperFinding(KernelContract):
    schema_version: Literal["systems-paper-currency-finding-v1"] = (
        "systems-paper-currency-finding-v1"
    )
    finding_id: StableId
    dimension: AuditDimension
    severity: FindingSeverity
    title: NonEmptyText
    diagnosis: NonEmptyText
    paper_relative_path: NonEmptyText
    paper_quote: NonEmptyText
    evidence_source_ids: list[StableId]
    repair_class: RepairClass
    required_repair: NonEmptyText
    resolved: Literal[False] = False
    finding_hash: Sha256

    @field_validator("evidence_source_ids")
    @classmethod
    def _sort_sources(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @model_validator(mode="after")
    def _validate_finding(self) -> PaperFinding:
        if self.dimension is not AuditDimension.LANGUAGE_LATEX and not self.evidence_source_ids:
            raise ValueError("non-mechanical paper finding needs a literature source")
        if self.finding_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("paper finding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> PaperFinding:
        values = dict(values)
        values["evidence_source_ids"] = sorted(set(values["evidence_source_ids"]))
        payload = {
            "schema_version": "systems-paper-currency-finding-v1",
            "resolved": False,
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "finding_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"finding_hash"}))


def _require_paper_quote(package_dir: Path, relative_path: str, quote: str) -> None:
    path = package_dir.resolve() / relative_path
    if not path.is_file():
        raise SystemsPaperCurrencyIntegrityError(f"quoted paper file missing: {relative_path}")
    if quote not in path.read_text(encoding="utf-8"):
        raise SystemsPaperCurrencyIntegrityError(
            f"quoted paper evidence changed in {relative_path}: {quote}"
        )


def build_paper_findings(
    package_dir: Path,
    *,
    source_registry: VerifiedSourceRegistry,
    language_scan: PaperLanguageScan,
) -> list[PaperFinding]:
    """Create quoted, retrieval-grounded findings over the immutable manuscript."""

    known_sources = {source.source_id for source in source_registry.sources}
    definitions: list[dict[str, Any]] = [
        {
            "finding_id": "F-001-independent-unit-pseudoreplication",
            "dimension": AuditDimension.EMPIRICAL_VALIDITY,
            "severity": FindingSeverity.CRITICAL,
            "title": "The headline interval treats deterministic duplicate seeds as independent",
            "diagnosis": (
                "All three seed-level scientific hashes and outcomes are identical for every "
                "mode-task group. The paper reports a 30-pair interval even though the sampling "
                "unit for cross-task inference is ten tasks. The frozen [0.333333, 0.666667] "
                "interval is therefore too narrow for the stated systems inference."
            ),
            "paper_relative_path": "paper/source/sections/experiments.tex",
            "paper_quote": "We report the mean over the 30 task-seed pairs.",
            "evidence_source_ids": ["demsar-jmlr-2006", "ai-agents-that-matter-2024"],
            "repair_class": RepairClass.EXISTING_EVIDENCE_REANALYSIS,
            "required_repair": (
                "Replace publication-facing inference with the ten-task bootstrap [0.2, 0.8], "
                "report five wins, zero losses, five ties and exact p-values, retain the 30-cell "
                "result only as an idempotency audit, and invalidate the old publication gate."
            ),
        },
        {
            "finding_id": "F-002-co-designed-evaluation-no-external-baseline",
            "dimension": AuditDimension.EMPIRICAL_VALIDITY,
            "severity": FindingSeverity.CRITICAL,
            "title": "Co-designed faults, repairs, and evaluator cannot establish external superiority",
            "diagnosis": (
                "The same project specifies the injected faults, legal repairs, controller, and "
                "success function. No independently authored task or external research agent is "
                "run under a common budget. The ablations show internal consistency, not that the "
                "architecture outperforms alternatives on independently generated research failures."
            ),
            "paper_relative_path": "paper/source/sections/limitations.tex",
            "paper_quote": (
                "Because the evaluator and repair\npolicy were designed together, the absolute "
                "success rates may overestimate\nperformance on independently authored tasks."
            ),
            "evidence_source_ids": [
                "astabench-iclr-2026",
                "paperbench-2025",
                "core-bench-2026-revision",
                "ai-agents-that-matter-2024",
            ],
            "repair_class": RepairClass.NEW_INDEPENDENT_EVIDENCE,
            "required_repair": (
                "Preregister an external confirmation in which independent people author and "
                "freeze tasks, include compute-matched external agents and simple baselines, and "
                "keep task construction, controller development, and final scoring role-separated."
            ),
        },
        {
            "finding_id": "F-003-current-field-positioning-stale",
            "dimension": AuditDimension.NOVELTY,
            "severity": FindingSeverity.MAJOR,
            "title": "The related-work claim predates the 2026 autonomous-science field",
            "diagnosis": (
                "End-to-end automation, multi-agent hypothesis evolution, experimental feedback, "
                "long-horizon memory, traceability, and tree-search empirical optimization now "
                "have major peer-reviewed or current preprint exemplars. The unchecked all-tick "
                "self-row is not a systematic review and is no longer a defensible novelty device."
            ),
            "paper_relative_path": "paper/source/sections/related-work.tex",
            "paper_quote": (
                "The final row is\nthe protocol evaluated in this paper."
            ),
            "evidence_source_ids": [
                "ai-scientist-nature-2026",
                "co-scientist-nature-2026",
                "robin-nature-2026",
                "era-nature-2026",
                "kosmos-preprint-2025",
                "popper-2025",
            ],
            "repair_class": RepairClass.EXISTING_EVIDENCE_TEXT,
            "required_repair": (
                "Rewrite Related Work through the 2026 cutoff, remove the exhaustive-looking "
                "checkmark table or rebuild it from a frozen human-coded protocol, and center the "
                "claim on testable evidence boundaries rather than generic loop breadth."
            ),
        },
        {
            "finding_id": "F-004-two-families-limited-external-validity",
            "dimension": AuditDimension.EXTERNAL_VALIDITY,
            "severity": FindingSeverity.MAJOR,
            "title": "Ten tasks from two imbalanced families do not support broad system generalization",
            "diagnosis": (
                "The overall task mean is 0.50, but the four UCI tasks average 0.25 and the six "
                "revealed MDBench trace tasks average 0.6667. A family-balanced sensitivity is "
                "0.4583, and two families cannot estimate across-domain variability."
            ),
            "paper_relative_path": "paper/source/sections/limitations.tex",
            "paper_quote": (
                "The matrix contains four tabular-data workflows and six equation-discovery\n"
                "trace workflows."
            ),
            "evidence_source_ids": [
                "demsar-jmlr-2006",
                "astabench-iclr-2026",
                "benchmarkcards-2024",
            ],
            "repair_class": RepairClass.NEW_INDEPENDENT_EVIDENCE,
            "required_repair": (
                "Prospectively sample enough independently authored tasks across at least three "
                "substantive families, justify the task sampling frame, and preregister family-aware "
                "or hierarchical sensitivity analysis before outcome access."
            ),
        },
        {
            "finding_id": "F-005-hash-package-not-interoperable-research-object",
            "dimension": AuditDimension.OPEN_SCIENCE,
            "severity": FindingSeverity.MAJOR,
            "title": "The package is reproducible locally but lacks a standard research-object profile",
            "diagnosis": (
                "The package has strong hashes, a clean rebuild, and claim-file links, but no "
                "ro-crate-metadata.json or Workflow Run RO-Crate profile. Consumers must understand "
                "project-specific JSON rather than a standard entity-activity-agent provenance view."
            ),
            "paper_relative_path": "paper/source/sections/abstract.tex",
            "paper_quote": (
                "We release the complete hash-linked campaign,\nnegative results, source evidence, "
                "paper source, and clean-directory\nreproduction entry point for human review."
            ),
            "evidence_source_ids": [
                "ro-crate-specification-1-3",
                "prov-o-w3c-2013",
                "fair4rs-2022",
                "workflow-run-ro-crate-2024",
                "acm-artifact-policy-1-1",
            ],
            "repair_class": RepairClass.EXISTING_EVIDENCE_REANALYSIS,
            "required_repair": (
                "Wrap the unchanged package in a conformant RO-Crate 1.3 and Workflow Run "
                "RO-Crate profile, map lineage to PROV-O, add rights and persistent-identifier "
                "metadata, and keep validity claims separate from artifact conformance."
            ),
        },
        {
            "finding_id": "F-006-target-venue-unspecified",
            "dimension": AuditDimension.LOGIC,
            "severity": FindingSeverity.MAJOR,
            "title": "Venue fit, page limit, and policy compliance cannot be certified",
            "diagnosis": (
                "The source uses a generic anonymous non-ACM sigconf layout without naming a "
                "venue. Scope, contribution type, page limits, review model, artifact rules, and "
                "AI-use disclosure therefore remain undefined."
            ),
            "paper_relative_path": "paper/source/main.tex",
            "paper_quote": "\\documentclass[sigconf,anonymous,nonacm]{acmart}",
            "evidence_source_ids": ["acm-artifact-policy-1-1", "ai-scientist-nature-2026"],
            "repair_class": RepairClass.HUMAN_ONLY,
            "required_repair": (
                "A human owner must choose the claim type and target venue, then rerun a "
                "venue-specific scope, length, policy, disclosure, and artifact audit."
            ),
        },
        {
            "finding_id": "F-007-independent-human-scientific-review-absent",
            "dimension": AuditDimension.HUMAN_GOVERNANCE,
            "severity": FindingSeverity.CRITICAL,
            "title": "Deterministic review does not replace independent human scientific review",
            "diagnosis": (
                "The existing reviewer explicitly excludes novelty and venue fit. Automation can "
                "verify files and recalculate statistics but cannot establish authorship, scientific "
                "importance, conflicts, legal independence, or informed expert judgment."
            ),
            "paper_relative_path": "review/pre-submission-review.json",
            "paper_quote": (
                '"note": "This deterministic review assesses evidence binding, completeness, '
                'formatting, and reproducibility. Human novelty and venue-fit review remain mandatory."'
            ),
            "evidence_source_ids": [
                "co-scientist-nature-2026",
                "robin-nature-2026",
                "ai-scientist-risks-nature-communications-2025",
                "acm-artifact-policy-1-1",
            ],
            "repair_class": RepairClass.HUMAN_ONLY,
            "required_repair": (
                "Obtain at least two independent qualified human reviews plus conflict-resolved "
                "adjudication for novelty, scientific validity, claim scope, ethics, authorship, "
                "licensing, and venue compliance before any submission decision."
            ),
        },
        {
            "finding_id": "F-008-authorship-license-ai-disclosure-unresolved",
            "dimension": AuditDimension.HUMAN_GOVERNANCE,
            "severity": FindingSeverity.MAJOR,
            "title": "Anonymous placeholder authorship is not a publication decision",
            "diagnosis": (
                "The manuscript intentionally leaves authorship anonymous and the package blocks "
                "external submission. Real contribution attribution, licenses, rights to source "
                "artifacts, and venue-specific AI-use disclosure need accountable people."
            ),
            "paper_relative_path": "paper/source/main.tex",
            "paper_quote": "\\author{Anonymous Author(s)}",
            "evidence_source_ids": [
                "ai-scientist-nature-2026",
                "ai-scientist-risks-nature-communications-2025",
                "fair4rs-2022",
            ],
            "repair_class": RepairClass.HUMAN_ONLY,
            "required_repair": (
                "Have the project owner determine contributor roles, authorship order, artifact "
                "licenses, data/software rights, acknowledgements, and AI-assistance disclosure."
            ),
        },
    ]
    findings: list[PaperFinding] = []
    for definition in definitions:
        missing_sources = set(definition["evidence_source_ids"]) - known_sources
        if missing_sources:
            raise SystemsPaperCurrencyIntegrityError(
                f"finding references unknown sources: {sorted(missing_sources)}"
            )
        _require_paper_quote(
            package_dir,
            str(definition["paper_relative_path"]),
            str(definition["paper_quote"]),
        )
        findings.append(PaperFinding.create(**definition))
    for hit_index, hit in enumerate(language_scan.hits, 1):
        findings.append(
            PaperFinding.create(
                finding_id=f"F-LANG-{hit_index:03d}",
                dimension=AuditDimension.LANGUAGE_LATEX,
                severity=hit.severity,
                title=f"Forbidden manuscript pattern: {hit.pattern}",
                diagnosis=(
                    "The pre-submission writing convention flags this exact occurrence as "
                    "AI-tone vocabulary or an em-dash connector."
                ),
                paper_relative_path=hit.relative_path,
                paper_quote=hit.line_excerpt,
                evidence_source_ids=[],
                repair_class=RepairClass.EXISTING_EVIDENCE_TEXT,
                required_repair="Rewrite this sentence in neutral technical language.",
            )
        )
    return findings


class RepairStep(KernelContract):
    schema_version: Literal["systems-paper-repair-step-v1"] = (
        "systems-paper-repair-step-v1"
    )
    step_id: StableId
    order: int = Field(ge=1)
    repair_class: RepairClass
    action: NonEmptyText
    depends_on: list[StableId]
    exit_gate: NonEmptyText
    unlocks_submission: Literal[False] = False


class SystemsPaperRepairPlan(KernelContract):
    schema_version: Literal["systems-paper-repair-plan-v1"] = (
        "systems-paper-repair-plan-v1"
    )
    task_id: Literal["263.7.0"] = "263.7.0"
    recommended_center_claim: NonEmptyText
    steps: list[RepairStep]
    immediate_automatable_step: StableId
    human_dependency_step: StableId
    new_evidence_dependency_step: StableId
    diagnostic_negative_paper_allowed_only_if_preregistered_and_powered: Literal[True] = True
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    plan_hash: Sha256

    @model_validator(mode="after")
    def _validate_plan(self) -> SystemsPaperRepairPlan:
        orders = [step.order for step in self.steps]
        if orders != list(range(1, len(self.steps) + 1)):
            raise ValueError("repair plan order must be contiguous")
        ids = {step.step_id for step in self.steps}
        for step in self.steps:
            if not set(step.depends_on) <= ids:
                raise ValueError(f"repair dependency missing for {step.step_id}")
        if {
            self.immediate_automatable_step,
            self.human_dependency_step,
            self.new_evidence_dependency_step,
        } - ids:
            raise ValueError("repair plan named dependency is missing")
        if self.plan_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("repair plan hash mismatch")
        return self

    @classmethod
    def create(cls) -> SystemsPaperRepairPlan:
        steps = [
            RepairStep(
                step_id="repair-1-task-unit-salvage",
                order=1,
                repair_class=RepairClass.EXISTING_EVIDENCE_REANALYSIS,
                action=(
                    "Create an additive v3 analysis note that collapses deterministic seeds, "
                    "reports the task bootstrap, exact sign test, family sensitivity, and marks "
                    "the old 30-pair gate historical."
                ),
                depends_on=[],
                exit_gate=(
                    "Independent reproduction matches task vector, CI [0.2, 0.8], one-sided "
                    "p=0.03125, two-sided p=0.0625, and family-balanced mean 0.458333."
                ),
            ),
            RepairStep(
                step_id="repair-2-current-field-repositioning",
                order=2,
                repair_class=RepairClass.EXISTING_EVIDENCE_TEXT,
                action=(
                    "Rewrite the title, abstract, introduction, related work, results, discussion, "
                    "and conclusion so the frozen study is a controlled mechanism demonstration, "
                    "not evidence that a generic loop outperforms autonomous-science systems."
                ),
                depends_on=["repair-1-task-unit-salvage"],
                exit_gate=(
                    "Every quantitative claim resolves to the task-level analysis; 2025-2026 "
                    "systems and independent benchmarks are covered; the self-checkmark table is removed."
                ),
            ),
            RepairStep(
                step_id="repair-3-interoperable-research-object",
                order=3,
                repair_class=RepairClass.EXISTING_EVIDENCE_REANALYSIS,
                action=(
                    "Add RO-Crate 1.3, Workflow Run RO-Crate, PROV-O mappings, rights metadata, "
                    "persistent identifiers, and machine-actionable claim-evidence relations around "
                    "the unchanged Task 260 package."
                ),
                depends_on=["repair-1-task-unit-salvage"],
                exit_gate=(
                    "Profile validators pass and a clean consumer can traverse paper claims, runs, "
                    "inputs, outputs, agents, activities, licenses, and derivations."
                ),
            ),
            RepairStep(
                step_id="repair-4-human-benchmark-validity-census",
                order=4,
                repair_class=RepairClass.HUMAN_ONLY,
                action=(
                    "Complete Task 263.6.7.3 with two independent reviewers and one distinct "
                    "adjudicator before selecting confirmatory benchmarks or asserting novelty."
                ),
                depends_on=[],
                exit_gate=(
                    "Frozen searches, dual independent coding, conflict-only adjudication, coverage "
                    "gates, and at least 20 valid fixed-revision release cards are complete."
                ),
            ),
            RepairStep(
                step_id="repair-5-independent-confirmation-preregistration",
                order=5,
                repair_class=RepairClass.NEW_INDEPENDENT_EVIDENCE,
                action=(
                    "Preregister a new confirmation study with task as the independent unit, "
                    "independent task authors, at least three substantive families, compute-matched "
                    "external agents and simple baselines, frozen null controls, and prospective power."
                ),
                depends_on=[
                    "repair-2-current-field-repositioning",
                    "repair-4-human-benchmark-validity-census",
                ],
                exit_gate=(
                    "Task sampling frame, minimum task count, assignment, exclusions, estimand, "
                    "family sensitivity, stopping rule, and independent scorer are frozen before reveal."
                ),
            ),
            RepairStep(
                step_id="repair-6-independent-confirmation-execution",
                order=6,
                repair_class=RepairClass.NEW_INDEPENDENT_EVIDENCE,
                action=(
                    "Run the frozen matrix once, retain every failure and exclusion, compare external "
                    "baselines under the same budget, and produce a diagnostic negative result if the "
                    "adequately powered primary gate fails."
                ),
                depends_on=["repair-5-independent-confirmation-preregistration"],
                exit_gate=(
                    "All registered task units, null controls, costs, trajectories, and claims have "
                    "independent evidence and exact reproduction records."
                ),
            ),
            RepairStep(
                step_id="repair-7-human-publication-decision",
                order=7,
                repair_class=RepairClass.HUMAN_ONLY,
                action=(
                    "Two qualified independent reviewers and a distinct adjudicator review novelty, "
                    "validity, authorship, licenses, AI disclosure, target venue, and public-release risk."
                ),
                depends_on=[
                    "repair-3-interoperable-research-object",
                    "repair-6-independent-confirmation-execution",
                ],
                exit_gate=(
                    "Human approvals are explicit, conflict-checked, venue-specific, and separated "
                    "from automated artifact checks."
                ),
            ),
        ]
        payload = {
            "schema_version": "systems-paper-repair-plan-v1",
            "task_id": TASK_ID,
            "recommended_center_claim": (
                "AutoResearch implements a tamper-evident, failure-linked research state machine "
                "whose transitions and negative results can be independently audited; whether it "
                "improves scientific research outcomes remains a prospective external question."
            ),
            "steps": steps,
            "immediate_automatable_step": "repair-1-task-unit-salvage",
            "human_dependency_step": "repair-4-human-benchmark-validity-census",
            "new_evidence_dependency_step": "repair-5-independent-confirmation-preregistration",
            "diagnostic_negative_paper_allowed_only_if_preregistered_and_powered": True,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        }
        return cls.model_validate(_addressed_payload(payload, "plan_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"plan_hash"}))


class StatisticalReplayProjection(KernelContract):
    schema_version: Literal["systems-paper-statistical-projection-v1"] = (
        "systems-paper-statistical-projection-v1"
    )
    task_ids: list[StableId]
    task_families: list[Literal["uci", "mdbench"]]
    task_differences: list[float]
    task_count: Literal[10] = 10
    seed_pair_count: Literal[30] = 30
    bootstrap_resamples: Literal[20000] = 20_000
    bootstrap_seed: Literal[2604] = 2604
    task_mean: float
    ci95: tuple[float, float]
    wins: int
    losses: int
    ties: int
    sign_test_one_sided_p: float
    sign_test_two_sided_p: float
    family_means: dict[Literal["uci", "mdbench"], float]
    family_balanced_mean: float
    projection_sha256: Sha256

    @model_validator(mode="after")
    def _validate_projection(self) -> StatisticalReplayProjection:
        if not (
            len(self.task_ids)
            == len(self.task_families)
            == len(self.task_differences)
            == 10
        ):
            raise ValueError("statistical projection requires ten aligned task units")
        if self.projection_sha256 != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("statistical projection hash mismatch")
        return self

    @classmethod
    def create_from_tasks(
        cls,
        tasks: Sequence[TaskLevelComparison],
    ) -> StatisticalReplayProjection:
        values = [item.task_difference for item in tasks]
        families: dict[str, list[float]] = defaultdict(list)
        for item in tasks:
            families[item.family].append(item.task_difference)
        family_means = {
            cast(Literal["uci", "mdbench"], family): statistics.fmean(items)
            for family, items in sorted(families.items())
        }
        wins, losses, ties, one_sided, two_sided = exact_sign_test(values)
        payload = {
            "schema_version": "systems-paper-statistical-projection-v1",
            "task_ids": [item.task_id for item in tasks],
            "task_families": [item.family for item in tasks],
            "task_differences": values,
            "task_count": 10,
            "seed_pair_count": 30,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "task_mean": statistics.fmean(values),
            "ci95": bootstrap_mean_interval(
                values,
                resamples=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
            ),
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "sign_test_one_sided_p": one_sided,
            "sign_test_two_sided_p": two_sided,
            "family_means": family_means,
            "family_balanced_mean": statistics.fmean(family_means.values()),
        }
        return cls.model_validate(_addressed_payload(payload, "projection_sha256"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"projection_sha256"}))


class StatisticalReplayObservation(KernelContract):
    schema_version: Literal["systems-paper-statistical-replay-observation-v1"] = (
        "systems-paper-statistical-replay-observation-v1"
    )
    runtime: InterpreterRuntime
    projection_sha256: Sha256
    output_file_sha256: Sha256
    output_contract_sha256: Sha256
    observation_hash: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> StatisticalReplayObservation:
        if self.observation_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("replay observation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> StatisticalReplayObservation:
        payload = {
            "schema_version": "systems-paper-statistical-replay-observation-v1",
            **values,
        }
        return cls.model_validate(_addressed_payload(payload, "observation_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"observation_hash"}))


class StatisticalReplayCertificate(KernelContract):
    schema_version: Literal["systems-paper-statistical-replay-certificate-v1"] = (
        "systems-paper-statistical-replay-certificate-v1"
    )
    replay_input_sha256: Sha256
    frozen_runner_sha256: Sha256
    projection_sha256: Sha256
    observations: list[StatisticalReplayObservation]
    exact_projection_match: Literal[True] = True
    distinct_interpreter_installations: Literal[True] = True
    certificate_hash: Sha256

    @field_validator("observations")
    @classmethod
    def _sort_observations(
        cls, value: list[StatisticalReplayObservation]
    ) -> list[StatisticalReplayObservation]:
        normalized = sorted(value, key=lambda item: item.runtime.role_id)
        if len(normalized) != 2 or len({item.runtime.role_id for item in normalized}) != 2:
            raise ValueError("statistical replay requires two interpreter roles")
        return normalized

    @model_validator(mode="after")
    def _validate_certificate(self) -> StatisticalReplayCertificate:
        if any(item.projection_sha256 != self.projection_sha256 for item in self.observations):
            raise ValueError("statistical replay projections differ")
        if len({item.runtime.environment_hash for item in self.observations}) != 2:
            raise ValueError("statistical replay requires distinct interpreter installations")
        if len({item.output_contract_sha256 for item in self.observations}) != 1:
            raise ValueError("statistical replay output contracts differ")
        if self.certificate_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("replay certificate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> StatisticalReplayCertificate:
        payload = {
            "schema_version": "systems-paper-statistical-replay-certificate-v1",
            "exact_projection_match": True,
            "distinct_interpreter_installations": True,
            **values,
            "observations": sorted(values["observations"], key=lambda item: item.runtime.role_id),
        }
        return cls.model_validate(_addressed_payload(payload, "certificate_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"certificate_hash"}))


def build_statistical_replay_payload(
    audit: IndependentUnitAudit,
) -> dict[str, Any]:
    return {
        "schema_version": "systems-paper-statistical-replay-input-v1",
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "tasks": [
            {
                "task_id": item.task_id,
                "family": item.family,
                "difference": item.task_difference,
            }
            for item in audit.task_comparisons
        ],
    }


def run_statistical_replay(
    *,
    audit: IndependentUnitAudit,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    work_dir: Path,
) -> StatisticalReplayCertificate:
    """Recompute the task-unit projection in two distinct clean interpreters."""

    if set(interpreters) != {"auditor-a", "auditor-b"}:
        raise ValueError("statistical replay requires auditor-a and auditor-b")
    if not runner_path.is_file():
        raise FileNotFoundError(runner_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = build_statistical_replay_payload(audit)
    payload_text = _canonical_json_text(payload) + "\n"
    replay_input_sha256 = _sha256_bytes(payload_text.encode("utf-8"))
    input_path = work_dir / f"input-{replay_input_sha256}.json"
    _write_text_atomic(input_path, payload_text)
    expected = StatisticalReplayProjection.create_from_tasks(audit.task_comparisons)
    observations: list[StatisticalReplayObservation] = []
    for role_id, executable in sorted(interpreters.items()):
        output_path = work_dir / f"{role_id}-projection.json"
        completed = subprocess.run(
            [str(executable), str(runner_path), str(input_path), str(output_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise SystemsPaperCurrencyIntegrityError(
                f"statistical replay failed for {role_id}: {completed.stderr.strip()}"
            )
        projection = StatisticalReplayProjection.model_validate_json(
            output_path.read_text(encoding="utf-8")
        )
        if projection != expected:
            raise SystemsPaperCurrencyIntegrityError(
                f"statistical replay projection differs for {role_id}"
            )
        observations.append(
            StatisticalReplayObservation.create(
                runtime=probe_interpreter_runtime(role_id=role_id, executable=executable),
                projection_sha256=projection.projection_sha256,
                output_file_sha256=_file_sha256(output_path),
                output_contract_sha256=canonical_sha256(projection.model_dump(mode="json")),
            )
        )
    return StatisticalReplayCertificate.create(
        replay_input_sha256=replay_input_sha256,
        frozen_runner_sha256=_file_sha256(runner_path),
        projection_sha256=expected.projection_sha256,
        observations=observations,
    )


class SystemsPaperCurrencyAuditReport(KernelContract):
    schema_version: Literal["systems-paper-currency-audit-report-v1"] = (
        "systems-paper-currency-audit-report-v1"
    )
    task_id: Literal["263.7.0"] = "263.7.0"
    built_at: datetime
    parent: ParentSystemsPaperEvidence
    brief: AuditResearchBrief
    source_registry: VerifiedSourceRegistry
    independent_unit_audit: IndependentUnitAudit
    language_scan: PaperLanguageScan
    findings: list[PaperFinding]
    repair_plan: SystemsPaperRepairPlan
    replay_certificate: StatisticalReplayCertificate
    severity_counts: dict[FindingSeverity, int]
    dimensions_reviewed: list[AuditDimension]
    publication_readiness_score_out_of_10: float = Field(ge=0.0, le=10.0)
    verdict: PublicationVerdict
    novelty_conclusion: NonEmptyText
    publication_ready: Literal[False] = False
    independent_human_review_complete: Literal[False] = False
    public_release_authorized: Literal[False] = False
    external_submission_authorized: Literal[False] = False
    report_hash: Sha256

    @field_validator("built_at")
    @classmethod
    def _built_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit report time must be timezone aware")
        return value.astimezone(timezone.utc)

    @field_validator("findings")
    @classmethod
    def _sort_findings(cls, value: list[PaperFinding]) -> list[PaperFinding]:
        normalized = sorted(value, key=lambda item: item.finding_id)
        if len(normalized) != len({item.finding_id for item in normalized}):
            raise ValueError("paper finding IDs must be unique")
        return normalized

    @model_validator(mode="after")
    def _validate_report(self) -> SystemsPaperCurrencyAuditReport:
        if self.parent.parent_evidence_hash != self.independent_unit_audit.parent_evidence_hash:
            raise ValueError("independent-unit audit is not bound to the parent package")
        if self.replay_certificate.projection_sha256 != StatisticalReplayProjection.create_from_tasks(
            self.independent_unit_audit.task_comparisons
        ).projection_sha256:
            raise ValueError("statistical replay is not bound to the independent-unit audit")
        counts = Counter(item.severity for item in self.findings)
        if dict(counts) != self.severity_counts:
            raise ValueError("paper finding severity counts are stale")
        if set(self.dimensions_reviewed) != set(AuditDimension):
            raise ValueError("all audit dimensions are required")
        known_sources = {item.source_id for item in self.source_registry.sources}
        referenced_sources = {
            source_id for finding in self.findings for source_id in finding.evidence_source_ids
        }
        if not referenced_sources <= known_sources:
            raise ValueError("paper finding references an unknown source")
        if counts[FindingSeverity.CRITICAL] < 1:
            raise ValueError("publication-blocking audit requires the observed critical findings")
        if self.publication_ready:
            raise ValueError("Task 263.7.0 cannot authorize publication")
        if self.report_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("currency audit report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SystemsPaperCurrencyAuditReport:
        findings = sorted(
            cast(Sequence[PaperFinding], values["findings"]),
            key=lambda item: item.finding_id,
        )
        counts: Counter[FindingSeverity] = Counter(item.severity for item in findings)
        payload = {
            "schema_version": "systems-paper-currency-audit-report-v1",
            "task_id": TASK_ID,
            **values,
            "findings": findings,
            "severity_counts": dict(sorted(counts.items(), key=lambda item: item[0].value)),
            "dimensions_reviewed": list(AuditDimension),
            "publication_readiness_score_out_of_10": 3.0,
            "verdict": PublicationVerdict.NEW_EVIDENCE_AND_HUMAN_REVIEW_REQUIRED,
            "novelty_conclusion": (
                "A generic end-to-end or multi-agent research loop is no longer differentiated. "
                "The defensible research direction is a narrower evidence-bound state-machine "
                "claim: immutable negative-result lineage, pre-result freezes, typed failure "
                "successors, and interoperable claim provenance. That claim still needs an "
                "independently authored, compute-matched confirmation study."
            ),
            "publication_ready": False,
            "independent_human_review_complete": False,
            "public_release_authorized": False,
            "external_submission_authorized": False,
        }
        return cls.model_validate(_addressed_payload(payload, "report_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))


class SystemsPaperCurrencyAuditManifest(KernelContract):
    schema_version: Literal["systems-paper-currency-audit-manifest-v1"] = (
        "systems-paper-currency-audit-manifest-v1"
    )
    report_hash: Sha256
    parent_evidence_hash: Sha256
    brief_hash: Sha256
    source_registry_hash: Sha256
    independent_unit_audit_hash: Sha256
    language_scan_hash: Sha256
    repair_plan_hash: Sha256
    replay_certificate_hash: Sha256
    files: dict[NonEmptyText, Sha256]
    manifest_hash: Sha256

    @field_validator("files")
    @classmethod
    def _sort_files(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = dict(sorted(value.items()))
        if not normalized or AUDIT_MANIFEST_FILENAME in normalized:
            raise ValueError("audit manifest file set is invalid")
        return normalized

    @model_validator(mode="after")
    def _validate_manifest(self) -> SystemsPaperCurrencyAuditManifest:
        if self.manifest_hash != self.calculated_hash():
            raise SystemsPaperCurrencyIntegrityError("currency audit manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> SystemsPaperCurrencyAuditManifest:
        payload = {
            "schema_version": "systems-paper-currency-audit-manifest-v1",
            **values,
            "files": dict(sorted(values["files"].items())),
        }
        return cls.model_validate(_addressed_payload(payload, "manifest_hash"))

    def calculated_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"manifest_hash"}))


AUDIT_CONTRACT_MODELS = (
    PrimarySourceSnapshot,
    VerifiedSourceRecord,
    VerifiedSourceRegistry,
    AuditResearchBrief,
    ParentSystemsPaperEvidence,
    TaskLevelComparison,
    IndependentUnitAudit,
    LanguagePatternHit,
    PaperLanguageScan,
    PaperFinding,
    RepairStep,
    SystemsPaperRepairPlan,
    StatisticalReplayProjection,
    StatisticalReplayObservation,
    StatisticalReplayCertificate,
    SystemsPaperCurrencyAuditReport,
    SystemsPaperCurrencyAuditManifest,
)


def systems_paper_currency_audit_json_schemas() -> dict[str, dict[str, Any]]:
    return {model.__name__: model.model_json_schema() for model in AUDIT_CONTRACT_MODELS}


def fetch_primary_source_registry(
    *,
    output_dir: Path,
    retrieved_at: datetime,
    fetcher: SourceFetcher = fetch_source_response,
) -> VerifiedSourceRegistry:
    records: list[VerifiedSourceRecord] = []
    for definition in source_definitions():
        response = fetcher(definition.url)
        snapshot = PrimarySourceSnapshot.create(
            definition=definition,
            response=response,
            retrieved_at=retrieved_at,
        )
        _write_bytes_once(output_dir / snapshot.relative_path, response.body)
        records.append(VerifiedSourceRecord.create(definition=definition, snapshot=snapshot))
    return VerifiedSourceRegistry.create(audit_cutoff=retrieved_at, sources=records)


def render_systems_paper_currency_audit_markdown(
    report: SystemsPaperCurrencyAuditReport,
) -> str:
    audit = report.independent_unit_audit
    lines = [
        "# Task 263.7.0 - Task 260 systems paper publication-currency audit",
        "",
        f"- Verdict: `{report.verdict.value}`",
        f"- Readiness score: `{report.publication_readiness_score_out_of_10:.1f}/10`",
        f"- Parent package: `{report.parent.package_id}` / `{report.parent.package_hash}`",
        f"- Report hash: `{report.report_hash}`",
        "- Publication, public release, and external submission: `false`",
        "",
        "## Why the frozen paper is not publication-ready",
        "",
        (
            "The artifact engineering is strong, but the confirmatory evidence is not. Three "
            "deterministic seeds repeat the same scientific result for every task, the workflow "
            "faults and allowed repairs were co-designed with the evaluator, only two task families "
            "are represented, no external research agent is compared, the field review stops before "
            "major 2026 systems, and no independent human scientific review or target venue exists."
        ),
        "",
        "## Independent-unit reanalysis",
        "",
        "| Quantity | Frozen Task 260 view | Independent-task audit |",
        "|---|---:|---:|",
        f"| Nominal pairs / independent tasks | {audit.seed_cell_pair_count} | {audit.independent_task_count} |",
        f"| Mean gain | {audit.frozen_seed_pair_mean:.6f} | {audit.task_level_mean:.6f} |",
        (
            f"| Bootstrap 95% interval | [{audit.frozen_seed_pair_ci95[0]:.6f}, "
            f"{audit.frozen_seed_pair_ci95[1]:.6f}] | [{audit.task_level_ci95[0]:.6f}, "
            f"{audit.task_level_ci95[1]:.6f}] |"
        ),
        f"| Exact sign test | not reported | {audit.sign_test_wins} wins / {audit.sign_test_losses} losses / {audit.sign_test_ties} ties |",
        f"| One-sided / two-sided p | not reported | {audit.sign_test_one_sided_p:.5f} / {audit.sign_test_two_sided_p:.5f} |",
        "",
        (
            f"Family sensitivity: UCI mean `{audit.family_mean_differences['uci']:.6f}`, "
            f"MDBench mean `{audit.family_mean_differences['mdbench']:.6f}`, family-balanced "
            f"mean `{audit.family_balanced_mean:.6f}`. With only two families, this is a "
            "heterogeneity warning rather than a generalization estimate."
        ),
        "",
        "## Current-field synthesis",
        "",
        (
            "End-to-end generation, multi-agent hypothesis evolution, iterative experimental "
            "feedback, long-horizon world models, and tree-search empirical optimization are now "
            "represented by AI Scientist, Co-Scientist, Robin, Kosmos, and ERA. Independent suites "
            "such as AstaBench, PaperBench, CORE-Bench, REPRO-Bench, SciIntegrity-Bench, and the "
            "KOSMOS audit show that realistic execution, reproducibility, integrity, and null-model "
            "validation remain unsolved. The paper should therefore claim an auditable mechanism, "
            "not generic autonomous-science superiority."
        ),
        "",
        "### Verified source registry",
        "",
    ]
    for source in report.source_registry.sources:
        lines.append(
            f"- [{source.title}]({source.url}) ({source.year}, {source.review_status.value}): "
            f"{source.finding} Limitation: {source.limitation}"
        )
    lines.extend(["", "## Unresolved findings", ""])
    for finding in report.findings:
        lines.extend(
            [
                f"### {finding.finding_id} [{finding.severity.value.upper()}] {finding.title}",
                "",
                finding.diagnosis,
                "",
                f"Paper evidence (`{finding.paper_relative_path}`):",
                "",
                f"> {finding.paper_quote.replace(chr(10), ' ')}",
                "",
                f"Repair class: `{finding.repair_class.value}`. {finding.required_repair}",
                "",
            ]
        )
    lines.extend(
        [
            "## Optimized research path",
            "",
            f"Recommended center claim: {report.repair_plan.recommended_center_claim}",
            "",
        ]
    )
    for step in report.repair_plan.steps:
        lines.extend(
            [
                f"{step.order}. **{step.step_id}** (`{step.repair_class.value}`): {step.action}",
                f"   Exit gate: {step.exit_gate}",
                "",
            ]
        )
    lines.extend(
        [
            "## Mechanical review",
            "",
            f"- Source files scanned: `{len(report.language_scan.scanned_files)}`",
            f"- Em-dash occurrences: `{report.language_scan.em_dash_count}`",
            f"- Banned-term counts: `{dict(report.language_scan.term_counts)}`",
            "- External plagiarism checking remains a human pre-submission requirement.",
            "",
            "## Non-compensating boundaries",
            "",
            "- Existing evidence can repair the unit-of-analysis statistics, wording, related work, and research-object packaging.",
            "- Existing evidence cannot create independent task authors, external baselines, new task families, or stochastic trajectories.",
            "- Automation cannot decide scientific importance, authorship, licenses, venue policy, conflicts, or submission.",
            "",
        ]
    )
    return "\n".join(lines)


def write_systems_paper_currency_audit(
    output_dir: Path,
    report: SystemsPaperCurrencyAuditReport,
) -> SystemsPaperCurrencyAuditManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def write_json(relative: str, value: Any) -> None:
        path = output_dir / relative
        _write_text_atomic(path, _pretty_json_text(value))
        files[relative] = _file_sha256(path)

    write_json(AUDIT_BRIEF_FILENAME, report.brief)
    write_json(AUDIT_SOURCE_REGISTRY_FILENAME, report.source_registry)
    write_json(AUDIT_INDEPENDENT_UNIT_FILENAME, report.independent_unit_audit)
    write_json(AUDIT_LANGUAGE_SCAN_FILENAME, report.language_scan)
    write_json(
        AUDIT_FINDINGS_FILENAME,
        {
            "schema_version": "systems-paper-currency-findings-v1",
            "findings": [item.model_dump(mode="json") for item in report.findings],
        },
    )
    write_json(AUDIT_REPAIR_PLAN_FILENAME, report.repair_plan)
    write_json(AUDIT_REPLAY_FILENAME, report.replay_certificate)
    write_json(AUDIT_REPORT_FILENAME, report)
    markdown_path = output_dir / AUDIT_MARKDOWN_FILENAME
    _write_text_atomic(markdown_path, render_systems_paper_currency_audit_markdown(report))
    files[AUDIT_MARKDOWN_FILENAME] = _file_sha256(markdown_path)
    write_json(AUDIT_SCHEMAS_FILENAME, systems_paper_currency_audit_json_schemas())
    for source in report.source_registry.sources:
        source_path = output_dir / source.snapshot.relative_path
        if not source_path.is_file():
            raise SystemsPaperCurrencyIntegrityError(
                f"retained source body missing: {source.snapshot.relative_path}"
            )
        if _file_sha256(source_path) != source.snapshot.body_sha256:
            raise SystemsPaperCurrencyIntegrityError(
                f"retained source body changed: {source.snapshot.relative_path}"
            )
        files[source.snapshot.relative_path] = source.snapshot.body_sha256
    manifest = SystemsPaperCurrencyAuditManifest.create(
        report_hash=report.report_hash,
        parent_evidence_hash=report.parent.parent_evidence_hash,
        brief_hash=report.brief.brief_hash,
        source_registry_hash=report.source_registry.registry_hash,
        independent_unit_audit_hash=report.independent_unit_audit.audit_hash,
        language_scan_hash=report.language_scan.language_scan_hash,
        repair_plan_hash=report.repair_plan.plan_hash,
        replay_certificate_hash=report.replay_certificate.certificate_hash,
        files=files,
    )
    _write_text_atomic(output_dir / AUDIT_MANIFEST_FILENAME, _pretty_json_text(manifest))
    return manifest


def load_systems_paper_currency_audit(
    output_dir: Path,
) -> tuple[SystemsPaperCurrencyAuditReport, SystemsPaperCurrencyAuditManifest]:
    manifest_path = output_dir / AUDIT_MANIFEST_FILENAME
    report_path = output_dir / AUDIT_REPORT_FILENAME
    manifest = SystemsPaperCurrencyAuditManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    actual_files = {
        path.relative_to(output_dir).as_posix(): _file_sha256(path)
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != AUDIT_MANIFEST_FILENAME
    }
    if set(actual_files) != set(manifest.files):
        missing = sorted(set(manifest.files) - set(actual_files))
        unexpected = sorted(set(actual_files) - set(manifest.files))
        raise SystemsPaperCurrencyIntegrityError(
            f"audit file set changed; missing={missing}, unexpected={unexpected}"
        )
    for relative, expected_hash in manifest.files.items():
        if actual_files[relative] != expected_hash:
            raise SystemsPaperCurrencyIntegrityError(f"audit file hash changed: {relative}")
    report = SystemsPaperCurrencyAuditReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    if report.report_hash != manifest.report_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/report binding mismatch")
    if report.parent.parent_evidence_hash != manifest.parent_evidence_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/parent binding mismatch")
    if report.brief.brief_hash != manifest.brief_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/brief binding mismatch")
    if report.source_registry.registry_hash != manifest.source_registry_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/source registry binding mismatch")
    if report.independent_unit_audit.audit_hash != manifest.independent_unit_audit_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/independent audit binding mismatch")
    if report.language_scan.language_scan_hash != manifest.language_scan_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/language scan binding mismatch")
    if report.repair_plan.plan_hash != manifest.repair_plan_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/repair plan binding mismatch")
    if report.replay_certificate.certificate_hash != manifest.replay_certificate_hash:
        raise SystemsPaperCurrencyIntegrityError("manifest/replay binding mismatch")
    for source in report.source_registry.sources:
        body_path = output_dir / source.snapshot.relative_path
        if _file_sha256(body_path) != source.snapshot.body_sha256:
            raise SystemsPaperCurrencyIntegrityError(
                f"retained source snapshot mismatch: {source.source_id}"
            )
    return report, manifest


def execute_systems_paper_currency_audit(
    *,
    parent_package_dir: Path,
    output_dir: Path,
    runner_path: Path,
    interpreters: Mapping[str, Path],
    replay_work_dir: Path,
    built_at: datetime,
    fetcher: SourceFetcher = fetch_source_response,
) -> tuple[SystemsPaperCurrencyAuditReport, SystemsPaperCurrencyAuditManifest]:
    """Execute or load the additive publication-currency audit."""

    if (output_dir / AUDIT_MANIFEST_FILENAME).is_file():
        return load_systems_paper_currency_audit(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemsPaperCurrencyIntegrityError(
            "partial currency-audit output requires manual inspection"
        )
    parent = ParentSystemsPaperEvidence.from_package(parent_package_dir)
    brief = AuditResearchBrief.create()
    source_registry = fetch_primary_source_registry(
        output_dir=output_dir,
        retrieved_at=built_at,
        fetcher=fetcher,
    )
    independent_audit = build_independent_unit_audit(parent_package_dir, parent=parent)
    language_scan = scan_paper_language(parent_package_dir)
    findings = build_paper_findings(
        parent_package_dir,
        source_registry=source_registry,
        language_scan=language_scan,
    )
    repair_plan = SystemsPaperRepairPlan.create()
    replay = run_statistical_replay(
        audit=independent_audit,
        runner_path=runner_path,
        interpreters=interpreters,
        work_dir=replay_work_dir,
    )
    report = SystemsPaperCurrencyAuditReport.create(
        built_at=built_at,
        parent=parent,
        brief=brief,
        source_registry=source_registry,
        independent_unit_audit=independent_audit,
        language_scan=language_scan,
        findings=findings,
        repair_plan=repair_plan,
        replay_certificate=replay,
    )
    manifest = write_systems_paper_currency_audit(output_dir, report)
    parent_after = ParentSystemsPaperEvidence.from_package(parent_package_dir)
    if parent_after != parent:
        raise SystemsPaperCurrencyIntegrityError("Task 260 parent package changed during audit")
    return report, manifest
