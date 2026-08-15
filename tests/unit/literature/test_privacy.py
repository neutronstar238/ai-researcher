from __future__ import annotations

import pytest

from autoresearch.kernel import validate_persistable_content
from autoresearch.literature.models import AcademicPaper
from autoresearch.literature.privacy import (
    SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION,
    ScholarlyMetadataPrivacyError,
    ScholarlyMetadataPrivacyReceipt,
    normalize_untrusted_scholarly_papers,
    normalize_untrusted_scholarly_text,
)


def test_openalex_contact_email_shape_is_redacted_with_field_receipt() -> None:
    paper = AcademicPaper(
        title="A source-backed normalization method",
        authors=["A. Researcher"],
        abstract=(
            "AVAILABILITY: implementation is publicly available. "
            "CONTACT: first.last@example.ac.uk SUPPLEMENTARY INFORMATION: online."
        ),
        url="https://doi.org/10.1000/example",
        source="openalex",
    )

    normalized, receipt = normalize_untrusted_scholarly_papers((paper,))

    assert normalized[0].abstract == (
        "AVAILABILITY: implementation is publicly available. "
        "CONTACT: [REDACTED_DIRECT_EMAIL_IDENTIFIER] "
        "SUPPLEMENTARY INFORMATION: online."
    )
    assert receipt.policy_version == SCHOLARLY_METADATA_PRIVACY_POLICY_VERSION
    assert receipt.total_redactions == 1
    assert receipt.redaction_counts == {
        "api_key_pattern": 0,
        "bearer_credential": 0,
        "direct_email_identifier": 1,
        "private_key_material": 0,
    }
    assert receipt.field_redaction_counts == {"papers[0].abstract": {"direct_email_identifier": 1}}
    validate_persistable_content([item.model_dump(mode="json") for item in normalized])


def test_all_credential_patterns_are_removed_without_retaining_secret_hashes() -> None:
    paper = AcademicPaper(
        title="Authorization: Bearer abcdefghijklmnop",
        authors=["sk-proj-abcdefghijklmnop"],
        abstract=("-----BEGIN PRIVATE KEY-----\nprivate-material\n" "-----END PRIVATE KEY-----"),
        venue="Contact second.author@example.org",
        source="fixture",
    )

    normalized, receipt = normalize_untrusted_scholarly_papers((paper,))
    serialized = normalized[0].model_dump_json()

    assert "abcdefghijklmnop" not in serialized
    assert "private-material" not in serialized
    assert "example.org" not in serialized
    assert receipt.total_redactions == 4
    assert receipt.redaction_counts == {
        "api_key_pattern": 1,
        "bearer_credential": 1,
        "direct_email_identifier": 1,
        "private_key_material": 1,
    }
    receipt_payload = receipt.model_dump(mode="json")
    assert "original_value" not in receipt_payload
    assert "original_sha256" not in receipt_payload
    validate_persistable_content(normalized[0].model_dump(mode="json"))


def test_no_match_is_byte_preserving_and_records_zero_counts() -> None:
    paper = AcademicPaper(
        title="PKM2 and contact-angle measurements",
        authors=["A. Researcher"],
        abstract="ORCID 0000-0002-1825-0097; sklearn baseline; no contact address.",
        doi="10.1000/unchanged",
        source="fixture",
    )

    normalized, receipt = normalize_untrusted_scholarly_papers((paper,))

    assert normalized == (paper,)
    assert receipt.total_redactions == 0
    assert receipt.field_redaction_counts == {}
    assert set(receipt.redaction_counts.values()) == {0}


@pytest.mark.parametrize(
    ("untrusted", "category"),
    [
        ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890", "api_key_pattern"),
        ("github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456", "api_key_pattern"),
        ("AKIAIOSFODNN7EXAMPLE", "api_key_pattern"),
        ("ASIAIOSFODNN7EXAMPLE", "api_key_pattern"),
        ("AIzaSyDUMMYDUMMYDUMMYDUMMYDUMMYDUMMY", "api_key_pattern"),
        ("hf_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456", "api_key_pattern"),
        ("api_key=DUMMYSECRET12345678", "api_key_pattern"),
        ("研究者@例子.公司", "direct_email_identifier"),
        ("researcher@xn--fsqu00a.xn--55qx5d", "direct_email_identifier"),
        ("Authorization: Bearer abcdefghijklmnop", "bearer_credential"),
        ("Bearer opaque-token-12345678", "bearer_credential"),
    ],
)
def test_central_sensitive_rules_are_normalized_and_counted(
    untrusted: str,
    category: str,
) -> None:
    paper = AcademicPaper(title="Safe title", abstract=untrusted, source="fixture")

    normalized, receipt = normalize_untrusted_scholarly_papers((paper,))

    assert untrusted not in (normalized[0].abstract or "")
    assert receipt.total_redactions == 1
    assert receipt.redaction_counts[category] == 1
    validate_persistable_content(normalized[0].model_dump(mode="json"))


@pytest.mark.parametrize(
    "private_material",
    [
        (
            "-----BEGIN PRIVATE KEY-----\nSUPERSECRETMATERIAL1234567890\n"
            "-----END RSA PRIVATE KEY-----"
        ),
        (
            "-----BEGIN ENCRYPTED PRIVATE KEY-----\nSUPERSECRETMATERIAL1234567890\n"
            "-----END ENCRYPTED PRIVATE KEY-----"
        ),
        (
            "-----BEGIN DSA PRIVATE KEY-----\nSUPERSECRETMATERIAL1234567890\n"
            "-----END DSA PRIVATE KEY-----"
        ),
        (
            "-----BEGIN PGP PRIVATE KEY BLOCK-----\nSUPERSECRETMATERIAL1234567890\n"
            "-----END PGP PRIVATE KEY BLOCK-----"
        ),
    ],
)
def test_private_key_envelopes_remove_material_instead_of_only_the_begin_marker(
    private_material: str,
) -> None:
    paper = AcademicPaper(
        title="Safe title",
        abstract=f"prefix\n{private_material}\nsafe-tail",
        source="fixture",
    )

    normalized, receipt = normalize_untrusted_scholarly_papers((paper,))

    abstract = normalized[0].abstract or ""
    assert "SUPERSECRETMATERIAL" not in abstract
    assert "BEGIN" not in abstract
    assert "END" not in abstract
    assert "safe-tail" in abstract
    assert receipt.redaction_counts["private_key_material"] == 1
    validate_persistable_content(normalized[0].model_dump(mode="json"))


def test_truncated_private_key_fails_closed_instead_of_dropping_trailing_evidence() -> None:
    paper = AcademicPaper(
        title="Safe title",
        abstract=(
            "prefix\n-----BEGIN PRIVATE KEY-----\n" "SUPERSECRETMATERIAL1234567890\nsafe-tail"
        ),
        source="fixture",
    )

    with pytest.raises(ScholarlyMetadataPrivacyError) as caught:
        normalize_untrusted_scholarly_papers((paper,))

    assert "SUPERSECRETMATERIAL" not in str(caught.value)
    assert caught.value.receipt.total_redactions == 1
    assert caught.value.receipt.redaction_counts["private_key_material"] == 1
    assert caught.value.receipt.field_redaction_counts == {
        "papers[0].abstract": {"private_key_material": 1}
    }


def test_bearer_noun_phrase_is_not_normalized_as_a_credential() -> None:
    paper = AcademicPaper(
        title="The bearer certificate remained valid.",
        abstract="Bearer abcdefghijklmnop is an ambiguous unscoped phrase.",
        source="fixture",
    )

    normalized, receipt = normalize_untrusted_scholarly_papers((paper,))

    assert normalized == (paper,)
    assert receipt.total_redactions == 0


@pytest.mark.parametrize(
    "field_path",
    [
        "input-contact@example.org",
        "papers[-1].abstract",
        "papers[0].abstract/api_key",
    ],
)
def test_text_normalizer_rejects_untrusted_or_nonstructural_receipt_field_paths(
    field_path: str,
) -> None:
    with pytest.raises(ValueError, match="safe structural field path"):
        normalize_untrusted_scholarly_text(
            "contact@example.org",
            field_path=field_path,
        )


def test_privacy_receipt_model_rejects_sensitive_field_count_keys() -> None:
    with pytest.raises(ValueError, match="safe structural field path"):
        ScholarlyMetadataPrivacyReceipt.create(
            redaction_counts={
                "api_key_pattern": 0,
                "bearer_credential": 0,
                "direct_email_identifier": 1,
                "private_key_material": 0,
            },
            field_redaction_counts={"input-contact@example.org": {"direct_email_identifier": 1}},
        )
