from __future__ import annotations

import pytest

import manuscriptprep_merger as merger
import manuscriptprep_orchestrator_tui_refactored as orchestrator
import manuscriptprep_resolver as resolver


pytestmark = pytest.mark.regression


def test_extract_json_recovers_embedded_object() -> None:
    raw = 'thinking...\n{\n  "status": "ok"\n}\nextra'
    assert orchestrator.extract_json(raw) == {"status": "ok"}


def test_build_dossier_input_contains_excerpt_and_extraction_payload() -> None:
    out = orchestrator.build_dossier_input(
        "Jim said hello.",
        {"characters": ["Jim Hawkins"]},
        {"dialogue": True},
    )
    assert "EXCERPT:" in out
    assert "EXTRACTION_DATA:" in out
    assert "Jim Hawkins" in out


def test_build_resolution_map_normalizes_variant_lookup() -> None:
    llm_results = [
        {
            "group_id": "g1",
            "canonical_name": "Jim Hawkins",
            "response": {
                "merge": True,
                "confidence": "safe",
                "members_to_merge": ["Jim", "Jim Hawkins"],
                "members_to_keep_separate": [],
                "reasons": ["Name variant"],
            },
            "input_members": ["Jim", "Jim Hawkins"],
        }
    ]
    mapping = resolver.build_resolution_map(llm_results)
    assert mapping["variant_to_canonical"]["jim"]["canonical_name"] == "Jim Hawkins"


def test_load_chunk_data_survives_malformed_json(tmp_path) -> None:
    chunk_dir = tmp_path / "chunk_000"
    chunk_dir.mkdir()
    (chunk_dir / "structure.json").write_text("{not json", encoding="utf-8")
    data = merger.load_chunk_data(chunk_dir, {})
    assert data.structure == {"_load_error": "Could not parse structure.json"}
