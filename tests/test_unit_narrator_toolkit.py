from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from narrator_toolkit.document_model import build_cleaned_document
from narrator_toolkit.highlight_extraction import ExtractedHighlight, extract_pdf_highlights


pytestmark = pytest.mark.unit


def test_cleaned_document_preserves_highlight_spans_and_palette() -> None:
    clean_text = "CHAPTER I\n\nHello, said Sarah.\n\nThe room was quiet.\n"
    highlights = [
        ExtractedHighlight(
            text="Sarah",
            color="#ffd966",
            source_page=4,
            source_annotation_id="annot-1",
            rect=[0, 0, 10, 10],
        )
    ]

    document, report = build_cleaned_document(
        clean_text=clean_text,
        title="Voice Test",
        source_file="voice-test.pdf",
        highlights=highlights,
        document_id="voice_test",
    )

    paragraph = document["chapters"][0]["blocks"][1]
    assert document["schema_version"] == "narrator-toolkit.cleaned-document.v1"
    assert paragraph["text"] == "Hello, said Sarah."
    assert paragraph["spans"] == [
        {
            "start": 12,
            "end": 17,
            "type": "highlight",
            "color": "#ffd966",
            "source_page": 4,
            "source_annotation_id": "annot-1",
            "character": None,
            "mapping_method": "exact",
            "confidence": 1.0,
        }
    ]
    assert document["highlight_palette"] == [{"color": "#ffd966", "label": None, "usage_count": 1}]
    assert document["metadata"]["has_highlights"] is True
    assert report["mapped_highlights"] == 1
    assert report["unmapped_highlights"] == 0


def test_highlight_mapping_survives_cleaned_whitespace_changes() -> None:
    clean_text = "CHAPTER I\n\nHello, said Sarah.\n"
    highlights = [
        ExtractedHighlight(
            text="Hello,\nsaid   Sarah.",
            color="#93c47d",
            source_page=2,
            source_annotation_id="annot-2",
            rect=[0, 0, 10, 10],
        )
    ]

    document, report = build_cleaned_document(
        clean_text=clean_text,
        title="Whitespace Test",
        source_file="voice-test.pdf",
        highlights=highlights,
    )

    span = document["chapters"][0]["blocks"][1]["spans"][0]
    assert span["start"] == 0
    assert span["end"] == len("Hello, said Sarah.")
    assert span["mapping_method"] == "normalised_whitespace"
    assert report["mapped_highlights"] == 1


def test_highlight_mapping_prefers_source_context_for_repeated_text() -> None:
    clean_text = "CHAPTER I\n\nSarah waved.\n\nLater Sarah waved again.\n"
    highlights = [
        ExtractedHighlight(
            text="Sarah",
            color="#93c47d",
            source_page=2,
            source_annotation_id="annot-2",
            rect=[0, 0, 10, 10],
            source_context="Later Sarah waved again.",
        )
    ]

    document, report = build_cleaned_document(
        clean_text=clean_text,
        title="Context Test",
        source_file="voice-test.pdf",
        highlights=highlights,
    )

    later_block = document["chapters"][0]["blocks"][2]
    assert later_block["text"] == "Later Sarah waved again."
    assert later_block["spans"] == [
        {
            "start": 6,
            "end": 11,
            "type": "highlight",
            "color": "#93c47d",
            "source_page": 2,
            "source_annotation_id": "annot-2",
            "character": None,
            "mapping_method": "contextual",
            "confidence": 0.98,
        }
    ]
    assert report["mapped_highlights"] == 1


def test_highlight_mapping_uses_source_page_to_disambiguate_repeated_pages() -> None:
    raw_text = "CHAPTER I\n\nSarah waved.\n\fCHAPTER II\n\nSarah waved.\n"
    clean_text = "CHAPTER I\n\nSarah waved.\n\nCHAPTER II\n\nSarah waved.\n"
    highlights = [
        ExtractedHighlight(
            text="Sarah",
            color="#ffd966",
            source_page=2,
            source_annotation_id="annot-3",
            rect=[0, 0, 10, 10],
            source_context="Sarah waved.",
        )
    ]

    document, report = build_cleaned_document(
        clean_text=clean_text,
        raw_text=raw_text,
        title="Page Test",
        source_file="voice-test.pdf",
        highlights=highlights,
    )

    second_chapter = document["chapters"][1]
    assert second_chapter["blocks"][1]["text"] == "Sarah waved."
    assert second_chapter["blocks"][1]["spans"] == [
        {
            "start": 0,
            "end": 5,
            "type": "highlight",
            "color": "#ffd966",
            "source_page": 2,
            "source_annotation_id": "annot-3",
            "character": None,
            "mapping_method": "contextual",
            "confidence": 0.98,
        }
    ]
    assert report["mapped_highlights"] == 1


def test_highlight_mapping_emits_page_progress_callbacks() -> None:
    raw_text = "CHAPTER I\n\nAlpha one.\n\fCHAPTER II\n\nBeta two.\n"
    clean_text = "CHAPTER I\n\nAlpha one.\n\nCHAPTER II\n\nBeta two.\n"
    highlights = [
        ExtractedHighlight(
            text="Alpha",
            color="#ffd966",
            source_page=1,
            source_annotation_id="annot-1",
            rect=[0, 0, 10, 10],
            source_context="Alpha one.",
        ),
        ExtractedHighlight(
            text="Beta",
            color="#ffd966",
            source_page=2,
            source_annotation_id="annot-2",
            rect=[0, 0, 10, 10],
            source_context="Beta two.",
        ),
    ]
    events: list[dict[str, object]] = []

    document, report = build_cleaned_document(
        clean_text=clean_text,
        raw_text=raw_text,
        title="Progress Test",
        source_file="voice-test.pdf",
        highlights=highlights,
        progress_callback=events.append,
    )

    assert report["mapped_highlights"] == 2
    assert document["metadata"]["has_highlights"] is True
    assert any(event.get("event_type") == "highlight_page_start" for event in events)
    assert any(event.get("event_type") == "highlight_page_complete" for event in events)
    assert any(event.get("current_page") == 1 for event in events)
    assert any(event.get("current_page") == 2 for event in events)
    assert any(event.get("page_mapped") == 1 for event in events)


def test_highlight_extraction_reads_fake_pymupdf_annotations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeRect:
        def __init__(self, values):
            self.x0, self.y0, self.x1, self.y1 = values

    class FakeAnnot:
        type = (8, "Highlight")
        rect = FakeRect((0, 0, 100, 20))
        vertices = None
        colors = {"stroke": (1.0, 0.85, 0.4)}
        next = None

    class FakePage:
        first_annot = FakeAnnot()

        def get_text(self, mode):
            if mode == "words":
                return [
                    (0, 0, 30, 10, "Hello", 0, 0, 0),
                    (35, 0, 70, 10, "Sarah", 0, 0, 1),
                    (110, 0, 140, 10, "Outside", 0, 0, 2),
                ]
            assert mode == "text"
            return "Hello Sarah\nOutside"

    class FakeDoc:
        def __enter__(self):
            return [FakePage()]

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_fitz = SimpleNamespace(
        Rect=lambda values: FakeRect(values),
        Quad=lambda values: SimpleNamespace(rect=FakeRect((0, 0, 100, 20))),
        open=lambda path: FakeDoc(),
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    highlights, warnings = extract_pdf_highlights(tmp_path / "sample.pdf")

    assert warnings == []
    assert len(highlights) == 1
    assert highlights[0].text == "Hello Sarah"
    assert highlights[0].color == "#ffd966"
    assert highlights[0].source_page == 1


def test_highlight_extraction_prefers_quad_geometry_over_rect_overlap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakePoint:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    class FakeRect:
        def __init__(self, values):
            self.x0, self.y0, self.x1, self.y1 = values

    class FakeAnnot:
        type = (8, "Highlight")
        rect = FakeRect((0, 0, 180, 20))
        vertices = [
            FakePoint(0, 0),
            FakePoint(0, 20),
            FakePoint(120, 20),
            FakePoint(120, 0),
        ]
        colors = {"stroke": (1.0, 0.85, 0.4)}
        next = None

    class FakePage:
        first_annot = FakeAnnot()

        def get_text(self, mode):
            if mode == "words":
                return [
                    (0, 0, 40, 10, "Hello", 0, 0, 0),
                    (45, 0, 85, 10, "Sarah", 0, 0, 1),
                    (130, 0, 175, 10, "Neighbor", 0, 0, 2),
                ]
            assert mode == "text"
            return "Hello Sarah Neighbor"

    class FakeDoc:
        def __enter__(self):
            return [FakePage()]

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_fitz = SimpleNamespace(
        Rect=lambda values: FakeRect(values),
        Quad=lambda values: SimpleNamespace(rect=FakeRect((0, 0, 120, 20))),
        open=lambda path: FakeDoc(),
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    highlights, warnings = extract_pdf_highlights(tmp_path / "sample.pdf")

    assert warnings == []
    assert len(highlights) == 1
    assert highlights[0].text == "Hello Sarah"


def test_flattened_highlight_rect_selection_ignores_nearby_line_overlap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeRect:
        def __init__(self, values):
            self.x0, self.y0, self.x1, self.y1 = values

    class FakeAnnot:
        type = (8, "Highlight")
        rect = FakeRect((0, 0, 120, 20))
        vertices = None
        colors = {"stroke": (1.0, 0.85, 0.4)}
        next = None

    class FakePage:
        first_annot = FakeAnnot()

        def get_text(self, mode):
            if mode == "words":
                return [
                    (0, 2, 40, 12, "Hello", 0, 0, 0),
                    (45, 2, 85, 12, "Sarah", 0, 0, 1),
                    (0, 18, 40, 28, "Neighbor", 0, 0, 2),
                ]
            assert mode == "text"
            return "Hello Sarah Neighbor"

    class FakeDoc:
        def __enter__(self):
            return [FakePage()]

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_fitz = SimpleNamespace(
        Rect=lambda values: FakeRect(values),
        Quad=lambda values: SimpleNamespace(rect=FakeRect((0, 0, 120, 20))),
        open=lambda path: FakeDoc(),
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    highlights, warnings = extract_pdf_highlights(tmp_path / "sample.pdf")

    assert warnings == []
    assert len(highlights) == 1
    assert highlights[0].text == "Hello Sarah"
