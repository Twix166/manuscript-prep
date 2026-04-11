from __future__ import annotations

import json
from pathlib import Path

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


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_resolver_uses_ollama_host_when_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["timeout"] = str(timeout)
        body = json.loads(req.data.decode("utf-8"))
        seen["model"] = body["model"]
        return _FakeHttpResponse({"response": '{"merge": true, "canonical_name": "Jim Hawkins"}'})

    monkeypatch.setattr(resolver.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(resolver.shutil, "which", lambda _cmd: None)

    settings = resolver.ResolverRuntimeSettings(
        input_dir=tmp_path,
        output_dir=tmp_path,
        model="manuscriptprep-resolver",
        timeout=30,
        min_variant_count=2,
        max_group_size=8,
        config_path=None,
        ollama_host="http://ollama.test:11434",
        ollama_command="ollama",
    )

    response = resolver.ask_ollama(
        "manuscriptprep-resolver",
        {"group_id": "group_001", "members": []},
        30,
        settings,
    )

    assert response["merge"] is True
    assert seen["url"] == "http://ollama.test:11434/api/generate"
    assert seen["model"] == "manuscriptprep-resolver"
    assert seen["timeout"] == "30"
