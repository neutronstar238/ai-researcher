"""ScanSci PDF integration metadata with legal-first defaults."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScanSciPdfIntegration:
    """Repository-tracked metadata for an optional ScanSci PDF backend."""

    integration_id: str
    label: str
    package_name: str
    runner_command: str
    source_url: str
    license: str
    install_commands: tuple[str, ...]
    verify_commands: tuple[str, ...]
    mcp_commands: tuple[str, ...]
    allowed_default_sources: tuple[str, ...]
    approval_required_sources: tuple[str, ...]
    policy_notes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-serialisable representation."""

        data = asdict(self)
        for field in (
            "install_commands",
            "verify_commands",
            "mcp_commands",
            "allowed_default_sources",
            "approval_required_sources",
            "policy_notes",
        ):
            data[field] = list(data[field])
        return data


SCANSCI_PDF_INTEGRATIONS: tuple[ScanSciPdfIntegration, ...] = (
    ScanSciPdfIntegration(
        integration_id="scansci-pdf-oa-first",
        label="ScanSci PDF optional OA-first source fetcher",
        package_name="scansci-pdf",
        runner_command="scansci-pdf",
        source_url="https://github.com/Rimagination/scansci-pdf",
        license="Apache-2.0",
        install_commands=(
            "python -m pip install scansci-pdf",
            "pipx install scansci-pdf",
        ),
        verify_commands=("scansci-pdf check",),
        mcp_commands=(
            "scansci-pdf run",
            "scansci-pdf run --mode streamable_http --host 127.0.0.1 --port 8000",
        ),
        allowed_default_sources=(
            "publisher_direct_open_access",
            "arxiv",
            "pubmed_central",
            "unpaywall",
            "openalex",
            "doaj",
            "core",
            "europe_pmc",
        ),
        approval_required_sources=(
            "sci-hub",
            "libgen",
            "institutional_webvpn",
            "carsi",
            "tor",
            "cloudflare_bypass",
            "credentialed_library_proxy",
        ),
        policy_notes=(
            "This repository records ScanSci PDF as an optional backend; it does not vendor or execute it.",
            "AI-Researcher default policy is OA/legal-first metadata and PDF retrieval only.",
            "Sources that bypass publisher, institutional, or network controls require explicit human approval and license review before use.",
            "Fetched PDFs must be linked to source metadata and stored as evidence; unsupported paper claims remain blocked.",
        ),
    ),
)


def iter_scansci_pdf_integrations() -> tuple[ScanSciPdfIntegration, ...]:
    """Return ScanSci PDF integration entries in deterministic order."""

    return SCANSCI_PDF_INTEGRATIONS


def get_scansci_pdf_integration(integration_id: str) -> ScanSciPdfIntegration:
    """Return one ScanSci PDF integration by ID."""

    normalized = integration_id.casefold()
    for integration in SCANSCI_PDF_INTEGRATIONS:
        if normalized == integration.integration_id.casefold():
            return integration
    msg = f"unknown ScanSci PDF integration: {integration_id}"
    raise KeyError(msg)


def scansci_pdf_manifest_payload() -> dict[str, object]:
    """Build the checked-in ScanSci PDF manifest payload."""

    return {
        "schema_version": 1,
        "generated_for": "AI-Researcher",
        "purpose": (
            "Reference metadata for using ScanSci PDF as an optional PDF retrieval "
            "backend while keeping AI-Researcher evidence, legality, and approval "
            "gates in control."
        ),
        "default_policy": {
            "mode": "oa_first_legal_only",
            "store_under": "autoresearch-vault/projects/<project-id>/sources/",
            "require_source_metadata": True,
            "require_approval_for_restricted_sources": True,
        },
        "approval_bridge": {
            "local_state": ".airesearcher/runtime-approvals.json",
            "approve_command": "airesearcher runtime approve latest --state .airesearcher/runtime-approvals.json",
            "runtime_command": "airesearcher serve --permission-mode approve-dangerous",
        },
        "security_notes": [
            "Do not store institutional credentials, cookies, or proxy state in this repository.",
            "Do not treat a downloaded PDF as evidence unless its source locator and license basis are recorded.",
            "Restricted or bypass-oriented sources are disabled by default and require human approval.",
        ],
        "integrations": [
            integration.to_json_dict()
            for integration in SCANSCI_PDF_INTEGRATIONS
        ],
    }


def write_scansci_pdf_manifest(output_path: Path | str) -> Path:
    """Write the ScanSci PDF manifest to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(scansci_pdf_manifest_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
