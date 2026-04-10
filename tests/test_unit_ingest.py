from __future__ import annotations

from pathlib import Path

import pytest

import manuscriptprep_ingest as ingest


pytestmark = pytest.mark.unit


class StubLogger:
    def log(self, message: str) -> None:
        pass


def build_test_mobi(text: str) -> bytes:
    payload = text.encode("utf-8")
    record_size = 4096
    text_records = [payload[index:index + record_size] for index in range(0, len(payload), record_size)]
    text_record_count = len(text_records)
    record_count = 1 + text_record_count

    record_zero = bytearray(256)
    record_zero[0:2] = (1).to_bytes(2, "big")
    record_zero[4:8] = len(payload).to_bytes(4, "big")
    record_zero[8:10] = text_record_count.to_bytes(2, "big")
    record_zero[10:12] = record_size.to_bytes(2, "big")
    record_zero[16:20] = b"MOBI"
    record_zero[20:24] = (232).to_bytes(4, "big")
    record_zero[28:32] = (65001).to_bytes(4, "big")

    pdb_header = bytearray(78)
    pdb_header[0:32] = b"Unit_Test_MOBI".ljust(32, b"\x00")
    pdb_header[60:64] = b"BOOK"
    pdb_header[64:68] = b"MOBI"
    pdb_header[76:78] = record_count.to_bytes(2, "big")

    offsets = []
    current_offset = 78 + (record_count * 8)
    records = [bytes(record_zero), *text_records]
    for index, record in enumerate(records):
        offsets.append(current_offset)
        current_offset += len(record)

    record_table = bytearray()
    for index, offset in enumerate(offsets):
        record_table.extend(offset.to_bytes(4, "big"))
        record_table.extend(index.to_bytes(4, "big"))

    return bytes(pdb_header + record_table + b"".join(records))


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


def test_extract_raw_text_supports_plain_text_sources(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("CHAPTER I\n\nCall me Ishmael.\n", encoding="utf-8")
    raw = tmp_path / "raw.txt"
    raw_ocr = tmp_path / "raw_ocr.txt"

    info = ingest.extract_raw_text(
        source_path=source,
        raw_txt_path=raw,
        raw_ocr_txt_path=raw_ocr,
        tmp_dir=tmp_path,
        classification=ingest.PdfClassification(
            source_format="txt",
            pdf_type="text",
            needs_ocr=False,
            native_sample_chars=0,
            page_count=None,
            warnings=[],
        ),
        force_ocr=False,
        logger=StubLogger(),
    )

    assert info["extractor"] == "plain_text"
    assert raw.read_text(encoding="utf-8").startswith("CHAPTER I")


def test_extract_raw_text_supports_mobi_sources(tmp_path: Path) -> None:
    source = tmp_path / "novel.mobi"
    source.write_bytes(
        build_test_mobi(
            "<html><body><h1>Moby-Dick</h1><p>Call me Ishmael. Some years ago...</p></body></html>"
        )
    )
    raw = tmp_path / "raw.txt"
    raw_ocr = tmp_path / "raw_ocr.txt"

    info = ingest.extract_raw_text(
        source_path=source,
        raw_txt_path=raw,
        raw_ocr_txt_path=raw_ocr,
        tmp_dir=tmp_path,
        classification=ingest.PdfClassification(
            source_format="mobi",
            pdf_type="text",
            needs_ocr=False,
            native_sample_chars=0,
            page_count=None,
            warnings=[],
        ),
        force_ocr=False,
        logger=StubLogger(),
    )

    assert info["extractor"] == "ebook_heuristic"
    text = raw.read_text(encoding="utf-8")
    assert "Moby-Dick" in text
    assert "Call me Ishmael" in text
