import json
from pathlib import Path

import pytest

from autoresearch.integrations.scansci_pdf import (
    get_scansci_pdf_integration,
    iter_scansci_pdf_integrations,
    scansci_pdf_manifest_payload,
    write_scansci_pdf_manifest,
)


def test_scansci_pdf_manifest_is_oa_first_and_approval_gated(tmp_path: Path) -> None:
    output = tmp_path / "integrations" / "scansci-pdf" / "pdf-source.json"

    write_scansci_pdf_manifest(output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == scansci_pdf_manifest_payload()
    assert payload["default_policy"]["mode"] == "oa_first_legal_only"
    integration = payload["integrations"][0]
    assert integration["license"] == "Apache-2.0"
    assert "arxiv" in integration["allowed_default_sources"]
    assert "unpaywall" in integration["allowed_default_sources"]
    assert "sci-hub" in integration["approval_required_sources"]
    assert "libgen" in integration["approval_required_sources"]


def test_scansci_pdf_lookup_rejects_unknown_id() -> None:
    integrations = iter_scansci_pdf_integrations()

    assert get_scansci_pdf_integration(integrations[0].integration_id) == integrations[0]
    with pytest.raises(KeyError) as exc:
        get_scansci_pdf_integration("missing")
    assert "unknown ScanSci PDF integration" in str(exc.value)
