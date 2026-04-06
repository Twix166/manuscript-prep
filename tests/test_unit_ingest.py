from __future__ import annotations

from pathlib import Path

import pytest

import manuscriptprep_ingest as ingest


pytestmark = pytest.mark.unit


class StubLogger:
    def log(self, message: str) -> None:
        pass


def test_clean_text_removes_page_markers_and_repeated_headers() -> None:
    raw = "\n".join(
        [
            "Project Gutenberg License",
            "1",
            "",
            "CHAPTER I",
            "",
            "Jim spoke softly.",
            "",
            "Project Gutenberg License",
            "2",
            "",
            "Jim thought again.",
            "",
            "Project Gutenberg License",
            "3",
        ]
    )
    cleaned, stats = ingest.clean_text(raw, StubLogger())
    assert "1\n" not in cleaned
    assert "2\n" not in cleaned
    assert "Project Gutenberg License" not in cleaned
    assert "CHAPTER I" in cleaned
    assert stats["removed_page_markers"] == 3


def test_chunk_clean_text_writes_chunks_and_preserves_chapter_hint(tmp_path: Path) -> None:
    text = "\n\n".join(
        [
            "CHAPTER I",
            "Jim Hawkins walked to the inn.",
            "Long John Silver waited by the road.",
            "CHAPTER II",
            "Jim Hawkins returned with the map.",
        ]
    )
    chunks, stats = ingest.chunk_clean_text(
        clean_text_value=text,
        book_title="Treasure Island",
        chunks_root=tmp_path,
        min_chunk_words=1,
        target_chunk_words=5,
        max_chunk_words=8,
        logger=StubLogger(),
    )
    assert stats["chunk_count"] >= 2
    assert chunks[0].chapter_hint == "CHAPTER I"
    assert Path(chunks[0].path).exists()
