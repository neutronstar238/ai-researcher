from __future__ import annotations

import pytest

from autoresearch.competition.contest_reference_policy import (
    build_postpilot_reference_catalog,
    project_locked_reference_selection,
    validate_locked_bibliography,
)


def test_projection_records_model_preferences_and_program_supplementation() -> None:
    catalog = tuple(f"real-paper-{index}" for index in range(1, 8))

    projection = project_locked_reference_selection([4, "[2]", "invented"], catalog)

    assert projection.references == catalog
    assert projection.model_selected_indices == (4, 2)
    assert projection.program_supplemented_indices == (1, 3, 5, 6, 7)


def test_final_acceptance_rejects_sparse_or_unlocked_bibliography() -> None:
    catalog = tuple(f"real-paper-{index}" for index in range(1, 8))

    with pytest.raises(ValueError, match="5–10"):
        validate_locked_bibliography(catalog[:2], catalog)
    with pytest.raises(ValueError, match="outside"):
        validate_locked_bibliography((*catalog[:4], "invented"), catalog)


def test_final_acceptance_rejects_different_text_that_repeats_one_doi() -> None:
    first = "Method paper. https://doi.org/10.1000/SAME.DOI"
    duplicate = "完整记录：DOI 10.1000/same.doi；来源 OpenAlex"
    distinct = tuple(f"real-paper-{index}" for index in range(1, 5))
    catalog = (first, duplicate, *distinct)

    with pytest.raises(ValueError, match="duplicate"):
        validate_locked_bibliography((first, duplicate, *distinct[:3]), catalog)


def test_final_acceptance_allows_background_and_method_entries_from_locked_catalog() -> None:
    catalog = tuple(f"real-paper-{index}" for index in range(1, 8))

    validate_locked_bibliography(catalog, catalog, require_exact_catalog=True)


def test_exact_catalog_acceptance_rejects_subset_or_reordered_bibliography() -> None:
    catalog = tuple(f"real-paper-{index}" for index in range(1, 8))

    with pytest.raises(ValueError, match="exact locked catalog order"):
        validate_locked_bibliography(catalog[:5], catalog, require_exact_catalog=True)
    with pytest.raises(ValueError, match="exact locked catalog order"):
        validate_locked_bibliography(
            (catalog[1], catalog[0], *catalog[2:]),
            catalog,
            require_exact_catalog=True,
        )


def test_postpilot_catalog_does_not_admit_adapter_references_outside_the_lock() -> None:
    planning = tuple(f"retrieved-paper-{index}" for index in range(1, 7))
    pilot = (
        "Method A. https://doi.org/10.1000/method-a",
        "unverifiable method note without DOI",
        "Method B. https://doi.org/10.1000/method-b",
    )

    catalog = build_postpilot_reference_catalog(planning, pilot)

    assert catalog == planning


def test_postpilot_catalog_is_a_deduplicated_bounded_projection_of_the_lock() -> None:
    planning = tuple(f"retrieved-paper-{index}" for index in range(1, 13))
    pilot = tuple(
        f"Method {index}. https://doi.org/10.1000/method-{index}" for index in range(1, 8)
    )

    catalog = build_postpilot_reference_catalog((*planning, planning[0]), pilot)

    assert len(catalog) == 10
    assert catalog == planning[:10]


def test_postpilot_catalog_preserves_locked_order_even_when_pilot_mentions_a_doi() -> None:
    pilot = ("Method paper. https://doi.org/10.1000/SAME.DOI",)
    planning = (
        "Locked catalog citation: DOI 10.1000/same.doi; source registry A",
        *(f"retrieved-paper-{index}" for index in range(1, 6)),
    )

    catalog = build_postpilot_reference_catalog(planning, pilot)

    assert catalog == planning
    assert pilot[0] not in catalog
    assert len(catalog) == 6


def test_postpilot_catalog_does_not_promote_a_late_locked_identity() -> None:
    planning = (
        *(f"locked-paper-{index}" for index in range(1, 11)),
        "Locked method record. https://doi.org/10.1000/locked-method",
    )
    pilot = (
        "Adapter citation variant. DOI 10.1000/LOCKED-METHOD",
        "Adapter-only reference. https://doi.org/10.1000/not-locked",
    )

    catalog = build_postpilot_reference_catalog(planning, pilot)

    assert catalog == planning[:10]
    assert planning[-1] not in catalog
    assert set(catalog).issubset(set(planning))
