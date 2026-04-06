from __future__ import annotations

import pytest

import manuscriptprep_merger as merger
import manuscriptprep_resolver as resolver


pytestmark = pytest.mark.unit


def test_merge_entities_preserves_variants_and_normalized_records() -> None:
    chunk = merger.ChunkData(
        chunk_id="chunk_000",
        chunk_dir=None,  # type: ignore[arg-type]
        structure=None,
        dialogue=None,
        entities={
            "characters": ["Jim", "Jim Hawkins"],
            "places": ["Admiral Benbow Inn"],
            "objects": ["map"],
            "identity_notes": ["Jim may be Jim Hawkins"],
        },
        dossiers=None,
        timing=None,
    )
    merged = merger.merge_entities([chunk])
    assert merged["characters"] == ["Jim", "Jim Hawkins"]
    normalized = merged["characters_normalized"]
    assert any(item["canonical"] == "Jim" for item in normalized)


def test_apply_resolution_to_book_adds_resolved_characters_and_dossier_annotations() -> None:
    book = {
        "entities": {"characters": ["Jim", "Long John Silver"]},
        "dossiers": {
            "character_dossiers": [
                {"name": "Jim", "surface_variants": ["Jim", "Jim Hawkins"]},
                {"name": "Long John Silver", "surface_variants": ["Long John Silver"]},
            ]
        },
    }
    resolution_map = {
        "resolutions": [],
        "variant_to_canonical": {
            "jim": {
                "variant": "Jim",
                "canonical_name": "Jim Hawkins",
                "confidence": "safe",
                "reasons": ["Given name variant"],
            }
        },
    }
    resolved = resolver.apply_resolution_to_book(book, resolution_map)
    assert resolved["entities"]["characters_resolved"] == ["Jim Hawkins", "Long John Silver"]
    assert resolved["dossiers"]["character_dossiers"][0]["resolved_canonical_name"] == "Jim Hawkins"
