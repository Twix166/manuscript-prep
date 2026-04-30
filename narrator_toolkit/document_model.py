"""Structured cleaned manuscript model and highlight span mapping."""

from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from narrator_toolkit.highlight_extraction import ExtractedHighlight
from narrator_toolkit.text_rules import is_chapter_heading, is_probable_heading, is_scene_break


SCHEMA_VERSION = "narrator-toolkit.cleaned-document.v1"
CLEANER_VERSION = "manuscriptprep-cleaner+highlight-map.v1"


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


def _find_in_context(
    clean_text: str,
    highlight_text: str,
    context_text: str,
    used_ranges: list[tuple[int, int]],
    preferred_start: int = 0,
) -> tuple[int, int] | None:
    if not context_text.strip():
        return None

    context_match = _find_exact(clean_text, context_text, used_ranges, preferred_start)
    if context_match is None:
        context_norm, context_map = _normalise_search_text(clean_text)
        context_match = _find_normalised_precomputed(
            context_norm,
            context_map,
            context_text,
            used_ranges,
            _normalise_search_text,
            preferred_start,
        )
    if context_match is None:
        context_norm, context_map = _normalise_punctuation_tolerant(clean_text)
        context_match = _find_normalised_precomputed(
            context_norm,
            context_map,
            context_text,
            used_ranges,
            _normalise_punctuation_tolerant,
            preferred_start,
        )
    if context_match is None:
        return None

    context_start, context_end = context_match
    segment = clean_text[context_start:context_end]
    inner = _find_exact(segment, highlight_text, [], 0)
    if inner is None:
        inner = _find_normalised(segment, highlight_text, [], _normalise_search_text, 0)
    if inner is None:
        inner = _find_normalised(segment, highlight_text, [], _normalise_punctuation_tolerant, 0)
    if inner is None:
        return None
    return context_start + inner[0], context_start + inner[1]


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


def _looks_like_running_header_or_footer(text: str) -> bool:
    s = text.strip()
    if not s or len(s) > 80:
        return False
    if re.search(r"[.!?]$", s):
        return False
    if re.fullmatch(r"(?:\d+|[ivxlcdm]+)", s, re.I):
        return True
    if re.fullmatch(r"(?:[A-Z0-9][A-Z0-9'’&\-]*)(?:\s+[A-Z0-9][A-Z0-9'’&\-]*){0,6}", s):
        return True
    if re.fullmatch(r"(?:[A-Z][a-z'’&\-]+)(?:\s+[A-Z][a-z'’&\-]+){0,6}", s):
        return True
    return False


def _detect_repeated_lines(lines: list[str]) -> set[str]:
    counts = Counter(line.strip() for line in lines if line.strip())
    return {
        line for line, count in counts.items()
        if count >= 3 and len(line) <= 120 and not is_chapter_heading(line)
    }


def _detect_page_edge_repeated_lines(raw_text: str, min_count: int = 2, edge_lines: int = 3) -> set[str]:
    pages = raw_text.split("\f") if "\f" in raw_text else [raw_text]
    if len(pages) < 2:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if not lines:
            continue
        candidates = set(lines[:edge_lines]) | set(lines[-edge_lines:])
        for candidate in candidates:
            if len(candidate) > 120 or is_chapter_heading(candidate) or not _looks_like_running_header_or_footer(candidate):
                continue
            counts[candidate] += 1
    threshold = max(min_count, max(2, len(pages) // 3))
    return {line for line, count in counts.items() if count >= threshold}


def _clean_page_segment(page_text: str, repeated_lines: set[str]) -> str:
    page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = page_text.split("\n")

    cleaned_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if stripped in repeated_lines and not is_probable_heading(stripped):
            continue
        if re.match(r"^\s*(?:page\s+\d+|\d+/\d+|\d+)\s*$", stripped, re.I):
            continue
        cleaned_lines.append(line.rstrip())

    text = "\n".join(cleaned_lines)
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)

    lines = text.split("\n")
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        para = "\n".join(part.rstrip() for part in buffer if part.strip())
        if para:
            paragraphs.append(para)
        buffer = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_buffer()
            continue
        if is_probable_heading(stripped) or is_scene_break(stripped):
            flush_buffer()
            paragraphs.append(stripped)
            continue
        if re.search(r"\.{3,}\s*\d+\s*$", stripped):
            flush_buffer()
            paragraphs.append(stripped)
            continue
        buffer.append(line)

    flush_buffer()
    return "\n\n".join(paragraphs).rstrip() + "\n"


def _build_page_segments(raw_text: str) -> list[str]:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    repeated_lines = _detect_repeated_lines(normalized.split("\n"))
    repeated_lines |= _detect_page_edge_repeated_lines(normalized)
    pages = normalized.split("\f")
    return [_clean_page_segment(page, repeated_lines) for page in pages]


def _locate_page_segments(clean_text: str, page_segments: list[str]) -> list[int | None]:
    offsets: list[int | None] = []
    cursor = 0
    for segment in page_segments:
        page_segment = segment.strip()
        if not page_segment:
            offsets.append(cursor)
            continue
        match = _find_exact(clean_text, page_segment, [], cursor)
        if match is None:
            match = _find_normalised_precomputed(
                *_normalise_search_text(clean_text),
                page_segment,
                [],
                _normalise_search_text,
                cursor,
            )
        if match is None:
            match = _find_normalised_precomputed(
                *_normalise_punctuation_tolerant(clean_text),
                page_segment,
                [],
                _normalise_punctuation_tolerant,
                cursor,
            )
        if match is None:
            offsets.append(None)
            continue
        offsets.append(match[0])
        cursor = match[1]
    return offsets


def _find_highlight_match(
    text: str,
    highlight: ExtractedHighlight,
    used_ranges: list[tuple[int, int]],
    preferred_start: int = 0,
    allow_fuzzy: bool = True,
    scope_cache: dict[str, tuple[str, list[int]]] | None = None,
) -> tuple[tuple[int, int] | None, str, float]:
    cache = scope_cache or _build_scope_cache(text)
    return _find_highlight_in_scope_cached(
        text,
        cache,
        highlight,
        used_ranges,
        preferred_start=preferred_start,
        allow_fuzzy=allow_fuzzy,
    )


def _page_window_bounds(
    clean_text: str,
    page_offsets: list[int | None],
    page_index: int,
    pad: int = 1200,
) -> tuple[int, int] | None:
    if page_index < 0 or page_index >= len(page_offsets):
        return None
    current_start = page_offsets[page_index]
    if current_start is None:
        return None

    next_start = len(clean_text)
    for candidate in page_offsets[page_index + 1:]:
        if candidate is not None:
            next_start = candidate
            break

    start = max(0, current_start - pad)
    end = min(len(clean_text), next_start + pad)
    if end <= start:
        return None
    return start, end


def _ranges_in_window(ranges: list[tuple[int, int]], window_start: int, window_end: int) -> list[tuple[int, int]]:
    local: list[tuple[int, int]] = []
    for start, end in ranges:
        if start < window_end and end > window_start:
            local.append((max(0, start - window_start), min(end, window_end) - window_start))
    return local


def _build_scope_cache(text: str) -> dict[str, tuple[str, list[int]]]:
    return {
        "search": _normalise_search_text(text),
        "punct": _normalise_punctuation_tolerant(text),
    }


def _find_highlight_in_scope_cached(
    scope_text: str,
    scope_cache: dict[str, tuple[str, list[int]]],
    highlight: ExtractedHighlight,
    used_ranges: list[tuple[int, int]],
    preferred_start: int = 0,
    allow_fuzzy: bool = True,
) -> tuple[tuple[int, int] | None, str, float]:
    context_text = getattr(highlight, "source_context", "") or ""

    if context_text.strip():
        context_match = _find_exact(scope_text, context_text, used_ranges, preferred_start)
        if context_match is None:
            context_match = _find_normalised_precomputed(
                *scope_cache["search"],
                context_text,
                used_ranges,
                _normalise_search_text,
                preferred_start,
            )
        if context_match is None:
            context_match = _find_normalised_precomputed(
                *scope_cache["punct"],
                context_text,
                used_ranges,
                _normalise_punctuation_tolerant,
                preferred_start,
            )
        if context_match is not None:
            context_start, context_end = context_match
            segment = scope_text[context_start:context_end]
            inner = _find_exact(segment, highlight.text, [], 0)
            if inner is None:
                inner = _find_normalised(segment, highlight.text, [], _normalise_search_text, 0)
            if inner is None:
                inner = _find_normalised(segment, highlight.text, [], _normalise_punctuation_tolerant, 0)
            if inner is not None:
                return (context_start + inner[0], context_start + inner[1]), "contextual", 0.98

    exact = _find_exact(scope_text, highlight.text, used_ranges, preferred_start)
    if exact is not None:
        return exact, "exact", 1.0

    match = _find_normalised_precomputed(
        *scope_cache["search"],
        highlight.text,
        used_ranges,
        _normalise_search_text,
        preferred_start,
    )
    if match is not None:
        return match, "normalised_whitespace", 0.96

    match = _find_normalised_precomputed(
        *scope_cache["punct"],
        highlight.text,
        used_ranges,
        _normalise_punctuation_tolerant,
        preferred_start,
    )
    if match is not None:
        return match, "punctuation_tolerant", 0.9

    if allow_fuzzy:
        fuzzy = _find_fuzzy(scope_text, highlight.text, used_ranges)
        if fuzzy is not None:
            return (fuzzy[0], fuzzy[1]), "fuzzy", round(fuzzy[2], 3)

    return None, "exact", 1.0


def map_highlights_to_clean_text(
    clean_text: str,
    highlights: list[ExtractedHighlight],
    raw_text: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    used_ranges: list[tuple[int, int]] = []
    warnings: list[dict[str, Any]] = []
    page_segments: list[str] = []
    page_offsets: list[int | None] = []
    if raw_text:
        page_segments = _build_page_segments(raw_text)
        page_offsets = _locate_page_segments(clean_text, page_segments)

    page_groups: dict[int, list[ExtractedHighlight]] = {}
    fallback_groups: dict[int, list[ExtractedHighlight]] = {}
    global_fallback: list[ExtractedHighlight] = []
    for highlight in highlights:
        page_index = int(highlight.source_page or 0) - 1
        if 0 <= page_index < len(page_segments) and page_offsets[page_index] is not None:
            page_groups.setdefault(page_index, []).append(highlight)
        else:
            global_fallback.append(highlight)

    page_totals = len(page_segments)
    clean_scope_cache = _build_scope_cache(clean_text)

    def emit_progress(**fields: Any) -> None:
        if progress_callback is not None:
            progress_callback(fields)

    def record_match(highlight: ExtractedHighlight, start: int, end: int, method: str, confidence: float) -> None:
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

    emit_progress(
        event_type="highlight_fallback_started",
        current_stage="highlight extraction",
        current_step="map highlights",
        pages_total=page_totals or None,
        page_highlights=sum(len(items) for items in fallback_groups.values()),
        global_highlights=len(global_fallback),
        mapped_highlights=len(mapped),
        unmapped_highlights=len(highlights) - len(mapped),
        message=(
            f"Entering fallback mapping for {sum(len(items) for items in fallback_groups.values())} "
            f"page-linked highlights and {len(global_fallback)} global highlights."
        ),
        stage_percent=0.0,
        overall_percent=65.0,
    )

    for page_index in range(page_totals):
        page_text = page_segments[page_index]
        page_start = page_offsets[page_index] if page_index < len(page_offsets) else None
        page_highlights = page_groups.get(page_index, [])
        page_mapped = 0
        page_unmapped = 0
        page_cache = _build_scope_cache(page_text)

        emit_progress(
            event_type="highlight_page_start",
            current_stage="highlight extraction",
            current_step="map highlights",
            current_page=page_index + 1,
            pages_total=page_totals,
            page_highlights=len(page_highlights),
            mapped_highlights=len(mapped),
            unmapped_highlights=len(highlights) - len(mapped),
            stage_percent=round((page_index / max(page_totals, 1)) * 100, 1),
            overall_percent=58.0 + round((page_index / max(page_totals, 1)) * 7.0, 1),
            message=f"Mapping highlights on page {page_index + 1} of {page_totals}.",
        )

        if page_start is None:
            fallback_groups.setdefault(page_index, []).extend(page_highlights)
            page_unmapped = len(page_highlights)
            emit_progress(
                event_type="highlight_page_complete",
                current_stage="highlight extraction",
                current_step="map highlights",
                current_page=page_index + 1,
                pages_total=page_totals,
                page_highlights=len(page_highlights),
                page_mapped=0,
                page_unmapped=page_unmapped,
                mapped_highlights=len(mapped),
                unmapped_highlights=len(highlights) - len(mapped),
                stage_percent=round(((page_index + 1) / max(page_totals, 1)) * 100, 1),
                overall_percent=58.0 + round(((page_index + 1) / max(page_totals, 1)) * 7.0, 1),
                message=f"Finished page {page_index + 1}; unable to align this page to cleaned text.",
            )
            continue

        page_search_cursor = 0
        page_used_ranges: list[tuple[int, int]] = []
        for highlight in page_highlights:
            local_match, method, confidence = _find_highlight_match(
                page_text,
                highlight,
                page_used_ranges,
                page_search_cursor,
                scope_cache=page_cache,
            )
            if local_match is None:
                fallback_groups.setdefault(page_index, []).append(highlight)
                page_unmapped += 1
            else:
                local_start, local_end = local_match
                start = page_start + local_start
                end = page_start + local_end
                if _overlaps_existing(start, end, used_ranges):
                    fallback_groups.setdefault(page_index, []).append(highlight)
                    page_unmapped += 1
                else:
                    page_search_cursor = local_end
                    page_used_ranges.append((local_start, local_end))
                    record_match(highlight, start, end, method, confidence)
                    page_mapped += 1

        emit_progress(
            event_type="highlight_page_complete",
            current_stage="highlight extraction",
            current_step="map highlights",
            current_page=page_index + 1,
            pages_total=page_totals,
            page_highlights=len(page_highlights),
            page_mapped=page_mapped,
            page_unmapped=page_unmapped,
            mapped_highlights=len(mapped),
            unmapped_highlights=len(highlights) - len(mapped),
            stage_percent=round(((page_index + 1) / max(page_totals, 1)) * 100, 1),
            overall_percent=58.0 + round(((page_index + 1) / max(page_totals, 1)) * 7.0, 1),
            message=(
                f"Finished page {page_index + 1} of {page_totals}: "
                f"{page_mapped} mapped, {page_unmapped} unmapped."
            ),
        )

    fallback_total = sum(len(items) for items in fallback_groups.values()) + len(global_fallback)
    fallback_processed = 0

    def emit_fallback_progress(page_index: int | None, page_mapped: int, page_unmapped: int) -> None:
        progress_fraction = fallback_processed / max(fallback_total, 1)
        emit_progress(
            event_type="highlight_fallback_progress",
            current_stage="highlight extraction",
            current_step="map highlights",
            current_page=(page_index + 1) if page_index is not None else None,
            pages_total=page_totals or None,
            page_mapped=page_mapped,
            page_unmapped=page_unmapped,
            mapped_highlights=len(mapped),
            unmapped_highlights=len(highlights) - len(mapped),
            page_highlights=(page_mapped + page_unmapped) if page_index is not None else len(global_fallback),
            message=(
                f"Fallback mapping progress: {fallback_processed}/{fallback_total} highlights processed. "
                f"Page {page_index + 1 if page_index is not None else 'global'}: "
                f"{page_mapped} mapped, {page_unmapped} unmapped."
            ),
            stage_percent=round(progress_fraction * 100, 1),
            overall_percent=round(65.0 + progress_fraction * 5.0, 1),
        )

    def search_without_fuzzy(
        scope_text: str,
        scope_cache: dict[str, tuple[str, list[int]]],
        highlight: ExtractedHighlight,
        scope_used_ranges: list[tuple[int, int]],
        preferred_start: int = 0,
        allow_fuzzy: bool = False,
    ) -> tuple[tuple[int, int] | None, str, float]:
        return _find_highlight_in_scope_cached(
            scope_text,
            scope_cache,
            highlight,
            scope_used_ranges,
            preferred_start=preferred_start,
            allow_fuzzy=allow_fuzzy,
        )

    for page_index in sorted(fallback_groups):
        highlights_for_page = fallback_groups[page_index]
        page_window = _page_window_bounds(clean_text, page_offsets, page_index)
        if page_window is None:
            window_start, window_end = 0, len(clean_text)
        else:
            window_start, window_end = page_window
        window_text = clean_text[window_start:window_end]
        window_cache = _build_scope_cache(window_text)
        local_used_ranges = _ranges_in_window(used_ranges, window_start, window_end)
        page_mapped = 0
        page_unmapped = 0

        emit_progress(
            event_type="highlight_fallback_page_start",
            current_stage="highlight extraction",
            current_step="map highlights",
            current_page=page_index + 1,
            pages_total=page_totals or None,
            page_highlights=len(highlights_for_page),
            mapped_highlights=len(mapped),
            unmapped_highlights=len(highlights) - len(mapped),
            page_mapped=page_mapped,
            page_unmapped=page_unmapped,
            fallback_mode="page-window",
            fallback_remaining=fallback_total - fallback_processed,
            message=(
                f"Fallback mapping page {page_index + 1} of {page_totals}. "
                f"{len(highlights_for_page)} highlights queued for this page."
            ),
            stage_percent=round((fallback_processed / max(fallback_total, 1)) * 100, 1),
            overall_percent=round(65.0 + (fallback_processed / max(fallback_total, 1)) * 5.0, 1),
        )

        for highlight in highlights_for_page:
            preferred_start = max(0, (page_offsets[page_index] or window_start) - window_start)
            match, method, confidence = search_without_fuzzy(
                window_text,
                window_cache,
                highlight,
                local_used_ranges,
                preferred_start,
            )
            if match is None:
                match, method, confidence = _find_highlight_match(
                    clean_text,
                    highlight,
                    used_ranges,
                    preferred_start=page_offsets[page_index] or 0,
                    allow_fuzzy=False,
                    scope_cache=clean_scope_cache,
                )
            if match is None:
                page_unmapped += 1
                warnings.append(
                    {
                        "source_annotation_id": highlight.source_annotation_id,
                        "source_page": highlight.source_page,
                        "text": highlight.text,
                        "warning": "unmapped_highlight",
                    }
                )
                fallback_processed += 1
                if fallback_processed == fallback_total or fallback_processed % 5 == 0:
                    emit_fallback_progress(page_index, page_mapped, page_unmapped)
                continue

            start, end = match
            if window_start:
                start += window_start
                end += window_start
            record_match(highlight, start, end, method, confidence)
            local_used_ranges.append((max(0, start - window_start), max(0, end - window_start)))
            page_mapped += 1
            fallback_processed += 1
            if fallback_processed == fallback_total or fallback_processed % 5 == 0:
                emit_fallback_progress(page_index, page_mapped, page_unmapped)

        emit_progress(
            event_type="highlight_fallback_page_complete",
            current_stage="highlight extraction",
            current_step="map highlights",
            current_page=page_index + 1,
            pages_total=page_totals or None,
            page_highlights=len(highlights_for_page),
            page_mapped=page_mapped,
            page_unmapped=page_unmapped,
            mapped_highlights=len(mapped),
            unmapped_highlights=len(highlights) - len(mapped),
            message=f"Fallback page {page_index + 1} complete: {page_mapped} mapped, {page_unmapped} unmapped.",
            stage_percent=round((fallback_processed / max(fallback_total, 1)) * 100, 1),
            overall_percent=round(65.0 + (fallback_processed / max(fallback_total, 1)) * 5.0, 1),
        )

    for highlight in global_fallback:
        match, method, confidence = search_without_fuzzy(
            clean_text,
            clean_scope_cache,
            highlight,
            used_ranges,
            0,
        )
        if match is None:
            warnings.append(
                {
                    "source_annotation_id": highlight.source_annotation_id,
                    "source_page": highlight.source_page,
                    "text": highlight.text,
                    "warning": "unmapped_highlight",
                }
            )
            fallback_processed += 1
            if fallback_processed == fallback_total or fallback_processed % 5 == 0:
                emit_fallback_progress(None, 0, len(global_fallback))
            continue

        start, end = match
        record_match(highlight, start, end, method, confidence)
        fallback_processed += 1
        if fallback_processed == fallback_total or fallback_processed % 5 == 0:
            emit_fallback_progress(None, 0, 0)

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
    for paragraph in [item.rstrip("\n") for item in clean_text.split("\n\n") if item.strip()]:
        start = clean_text.find(paragraph, cursor)
        if start < 0:
            start = cursor
        end = start + len(paragraph)
        paragraphs.append((paragraph, start, end))
        cursor = end
    return paragraphs


def _block_type(text: str) -> str:
    if is_chapter_heading(text):
        return "heading"
    return "paragraph"


def build_cleaned_document(
    *,
    clean_text: str,
    raw_text: str | None = None,
    title: str,
    source_file: str,
    highlights: list[ExtractedHighlight],
    extraction_warnings: list[str] | None = None,
    document_id: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mapped_highlights, report = map_highlights_to_clean_text(
        clean_text,
        highlights,
        raw_text=raw_text,
        progress_callback=progress_callback,
    )
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
        is_chapter = is_chapter_heading(text)
        if current_chapter is None or is_chapter:
            current_chapter = start_chapter(text.strip() if is_chapter else None, start_offset)

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
