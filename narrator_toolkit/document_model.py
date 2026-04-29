"""Structured cleaned manuscript model and highlight span mapping."""

from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from narrator_toolkit.highlight_extraction import ExtractedHighlight


SCHEMA_VERSION = "narrator-toolkit.cleaned-document.v1"
CLEANER_VERSION = "manuscriptprep-cleaner+highlight-map.v1"
CHAPTER_RE = re.compile(r"^\s*chapter\s+[ivxlcdm0-9]+\b", re.I)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _normalise_search_text(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    index_map: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not previous_space:
                out.append(" ")
                index_map.append(index)
                previous_space = True
            continue
        previous_space = False
        out.append(char.lower())
        index_map.append(index)
    return "".join(out).strip(), index_map


def _normalise_punctuation_tolerant(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    index_map: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isalnum():
            out.append(char.lower())
            index_map.append(index)
            previous_space = False
        elif char.isspace() and not previous_space:
            out.append(" ")
            index_map.append(index)
            previous_space = True
    return "".join(out).strip(), index_map


def _overlaps_existing(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < used_end and end > used_start for used_start, used_end in ranges)


def _find_exact(
    clean_text: str,
    highlight_text: str,
    used_ranges: list[tuple[int, int]],
    preferred_start: int = 0,
) -> tuple[int, int] | None:
    for initial_cursor in (preferred_start, 0):
        cursor = initial_cursor
        while True:
            start = clean_text.find(highlight_text, cursor)
            if start < 0:
                break
            end = start + len(highlight_text)
            if not _overlaps_existing(start, end, used_ranges):
                return start, end
            cursor = start + 1
    return None


def _find_normalised(
    clean_text: str,
    highlight_text: str,
    used_ranges: list[tuple[int, int]],
    normaliser,
    preferred_start: int = 0,
) -> tuple[int, int] | None:
    clean_norm, clean_map = normaliser(clean_text)
    highlight_norm, highlight_map = normaliser(highlight_text)
    if not highlight_norm:
        return None
    preferred_norm_start = 0
    for index, original_index in enumerate(clean_map):
        if original_index >= preferred_start:
            preferred_norm_start = index
            break
    for initial_cursor in (preferred_norm_start, 0):
        cursor = initial_cursor
        while True:
            norm_start = clean_norm.find(highlight_norm, cursor)
            if norm_start < 0:
                break
            norm_end = norm_start + len(highlight_norm) - 1
            start = clean_map[norm_start]
            end = clean_map[norm_end] + 1
            if highlight_map:
                end += len(highlight_text) - highlight_map[-1] - 1
            if not _overlaps_existing(start, end, used_ranges):
                return start, end
            cursor = norm_start + 1
    return None


def _find_normalised_precomputed(
    clean_norm: str,
    clean_map: list[int],
    highlight_text: str,
    used_ranges: list[tuple[int, int]],
    normaliser,
    preferred_start: int = 0,
) -> tuple[int, int] | None:
    highlight_norm, highlight_map = normaliser(highlight_text)
    if not highlight_norm:
        return None
    preferred_norm_start = 0
    for index, original_index in enumerate(clean_map):
        if original_index >= preferred_start:
            preferred_norm_start = index
            break
    for initial_cursor in (preferred_norm_start, 0):
        cursor = initial_cursor
        while True:
            norm_start = clean_norm.find(highlight_norm, cursor)
            if norm_start < 0:
                break
            norm_end = norm_start + len(highlight_norm) - 1
            start = clean_map[norm_start]
            end = clean_map[norm_end] + 1
            if highlight_map:
                end += len(highlight_text) - highlight_map[-1] - 1
            if not _overlaps_existing(start, end, used_ranges):
                return start, end
            cursor = norm_start + 1
    return None


def _find_fuzzy(clean_text: str, highlight_text: str, used_ranges: list[tuple[int, int]]) -> tuple[int, int, float] | None:
    words = re.findall(r"\S+", highlight_text)
    if not words:
        return None
    window_words = max(3, len(words) + 2)
    clean_words = list(re.finditer(r"\S+", clean_text))
    best: tuple[int, int, float] | None = None
    target = " ".join(words).lower()
    for start_word in range(0, max(len(clean_words) - window_words + 1, 1)):
        window = clean_words[start_word:start_word + window_words]
        if not window:
            continue
        start = window[0].start()
        end = window[-1].end()
        if _overlaps_existing(start, end, used_ranges):
            continue
        candidate = clean_text[start:end].lower()
        score = difflib.SequenceMatcher(None, target, candidate).ratio()
        if best is None or score > best[2]:
            best = (start, end, score)
    if best and best[2] >= 0.82:
        return best
    return None


def map_highlights_to_clean_text(
    clean_text: str,
    highlights: list[ExtractedHighlight],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    used_ranges: list[tuple[int, int]] = []
    warnings: list[dict[str, Any]] = []
    search_cursor = 0
    allow_fuzzy = len(highlights) <= 500
    clean_whitespace_norm, clean_whitespace_map = _normalise_search_text(clean_text)
    clean_punctuation_norm, clean_punctuation_map = _normalise_punctuation_tolerant(clean_text)

    for highlight in highlights:
        match = _find_exact(clean_text, highlight.text, used_ranges, search_cursor)
        method = "exact"
        confidence = 1.0
        if match is None:
            match = _find_normalised_precomputed(
                clean_whitespace_norm,
                clean_whitespace_map,
                highlight.text,
                used_ranges,
                _normalise_search_text,
                search_cursor,
            )
            method = "normalised_whitespace"
            confidence = 0.96
        if match is None:
            match = _find_normalised_precomputed(
                clean_punctuation_norm,
                clean_punctuation_map,
                highlight.text,
                used_ranges,
                _normalise_punctuation_tolerant,
                search_cursor,
            )
            method = "punctuation_tolerant"
            confidence = 0.9
        if match is None and allow_fuzzy:
            fuzzy = _find_fuzzy(clean_text, highlight.text, used_ranges)
            if fuzzy is not None:
                match = (fuzzy[0], fuzzy[1])
                method = "fuzzy"
                confidence = round(fuzzy[2], 3)
        if match is None:
            warnings.append(
                {
                    "source_annotation_id": highlight.source_annotation_id,
                    "source_page": highlight.source_page,
                    "text": highlight.text,
                    "warning": "unmapped_highlight",
                }
            )
            continue

        start, end = match
        search_cursor = end
        used_ranges.append((start, end))
        mapped.append(
            {
                "start_offset": start,
                "end_offset": end,
                "type": "highlight",
                "color": highlight.color,
                "source_page": highlight.source_page,
                "source_annotation_id": highlight.source_annotation_id,
                "character": None,
                "source_text": highlight.text,
                "mapping_method": method,
                "confidence": confidence,
            }
        )

    report = {
        "total_highlights": len(highlights),
        "mapped_highlights": len(mapped),
        "unmapped_highlights": len(highlights) - len(mapped),
        "mapping_warnings": warnings,
    }
    return mapped, report


def _paragraph_offsets(clean_text: str) -> list[tuple[str, int, int]]:
    paragraphs: list[tuple[str, int, int]] = []
    cursor = 0
    for paragraph in [item.strip() for item in clean_text.split("\n\n") if item.strip()]:
        start = clean_text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        paragraphs.append((paragraph, start, end))
        cursor = end
    return paragraphs


def _block_type(text: str) -> str:
    if CHAPTER_RE.match(text):
        return "heading"
    return "paragraph"


def build_cleaned_document(
    *,
    clean_text: str,
    title: str,
    source_file: str,
    highlights: list[ExtractedHighlight],
    extraction_warnings: list[str] | None = None,
    document_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mapped_highlights, report = map_highlights_to_clean_text(clean_text, highlights)
    if extraction_warnings:
        report["extraction_warnings"] = extraction_warnings

    paragraphs = _paragraph_offsets(clean_text)
    chapters: list[dict[str, Any]] = []
    current_chapter: dict[str, Any] | None = None

    def start_chapter(chapter_title: str | None, start_offset: int) -> dict[str, Any]:
        chapter = {
            "id": f"chapter-{len(chapters) + 1:03d}",
            "title": chapter_title or "Manuscript",
            "start_offset": start_offset,
            "end_offset": start_offset,
            "blocks": [],
        }
        chapters.append(chapter)
        return chapter

    for block_index, (text, start_offset, end_offset) in enumerate(paragraphs, start=1):
        is_chapter = CHAPTER_RE.match(text) is not None
        if current_chapter is None or is_chapter:
            current_chapter = start_chapter(text if is_chapter else None, start_offset)

        block_spans = []
        for highlight in mapped_highlights:
            span_start = max(start_offset, highlight["start_offset"])
            span_end = min(end_offset, highlight["end_offset"])
            if span_start < span_end:
                block_spans.append(
                    {
                        "start": span_start - start_offset,
                        "end": span_end - start_offset,
                        "type": "highlight",
                        "color": highlight["color"],
                        "source_page": highlight["source_page"],
                        "source_annotation_id": highlight["source_annotation_id"],
                        "character": None,
                        "mapping_method": highlight["mapping_method"],
                        "confidence": highlight["confidence"],
                    }
                )

        current_chapter["blocks"].append(
            {
                "id": f"block-{block_index:04d}",
                "type": _block_type(text),
                "text": text,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "spans": block_spans,
            }
        )
        current_chapter["end_offset"] = end_offset

    if not chapters:
        chapters.append(start_chapter("Manuscript", 0))

    palette_counts = Counter(item["color"] for item in mapped_highlights)
    document = {
        "schema_version": SCHEMA_VERSION,
        "document_format_version": 1,
        "id": document_id or str(uuid4()),
        "title": title,
        "source_file": str(source_file),
        "created_at": utc_now_iso(),
        "chapters": chapters,
        "highlight_palette": [
            {"color": color, "label": None, "usage_count": count}
            for color, count in sorted(palette_counts.items())
        ],
        "metadata": {
            "cleaner_version": CLEANER_VERSION,
            "source_type": Path(source_file).suffix.lower().lstrip(".") or "unknown",
            "has_highlights": bool(mapped_highlights),
            "highlight_report": report,
            "clean_word_count": count_words(clean_text),
        },
    }
    return document, report
