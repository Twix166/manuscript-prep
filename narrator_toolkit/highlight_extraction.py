"""PDF highlight annotation extraction for Narrator's Toolkit."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class ExtractedHighlight:
    text: str
    color: str
    source_page: int
    source_annotation_id: str
    rect: list[float]
    extraction_method: str = "pymupdf_annotation_words"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rgb_to_hex(rgb: Any) -> str:
    if not rgb:
        return "#ffff00"
    values = []
    for value in list(rgb)[:3]:
        value = max(0.0, min(1.0, float(value)))
        values.append(round(value * 255))
    while len(values) < 3:
        values.append(0)
    return "#{:02x}{:02x}{:02x}".format(*values)


def _rect_intersects(rect_a: Any, rect_b: Any) -> bool:
    return not (
        rect_a.x1 < rect_b.x0
        or rect_a.x0 > rect_b.x1
        or rect_a.y1 < rect_b.y0
        or rect_a.y0 > rect_b.y1
    )


def _highlight_rects(fitz: Any, annot: Any) -> list[Any]:
    vertices = getattr(annot, "vertices", None)
    if vertices:
        rects = []
        for index in range(0, len(vertices), 4):
            quad = vertices[index:index + 4]
            if len(quad) == 4:
                rects.append(fitz.Quad(quad).rect)
        if rects:
            return rects
    return [annot.rect]


def _words_under_annotation(fitz: Any, page: Any, annot: Any) -> str:
    rects = _highlight_rects(fitz, annot)
    return _words_under_rects(fitz, page, rects)


def _words_under_rects(fitz: Any, page: Any, rects: list[Any]) -> str:
    words = []
    for word in page.get_text("words"):
        word_rect = fitz.Rect(word[:4])
        if any(_rect_intersects(word_rect, rect) for rect in rects):
            words.append(word)
    words.sort(key=lambda item: (round(float(item[1]), 1), float(item[0])))
    return " ".join(str(item[4]) for item in words).strip()


def _looks_like_flattened_highlight(fill: Any, rect: Any) -> bool:
    if not fill or rect is None:
        return False
    rgb = [float(value) for value in list(fill)[:3]]
    if len(rgb) < 3:
        return False
    if all(value > 0.95 for value in rgb):
        return False
    if max(rgb) - min(rgb) < 0.05:
        return False
    width = float(rect.x1 - rect.x0)
    height = float(rect.y1 - rect.y0)
    area = width * height
    return width >= 8 and 5 <= height <= 40 and area >= 80


def _extract_flattened_highlights(fitz: Any, pdf_path: Path) -> tuple[list[ExtractedHighlight], list[str]]:
    highlights: list[ExtractedHighlight] = []
    warnings: list[str] = []
    seen: set[tuple[int, str, int, int, int, int]] = set()
    with fitz.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            flattened_index = 0
            for drawing in page.get_drawings():
                fill = drawing.get("fill")
                rect = drawing.get("rect")
                if not _looks_like_flattened_highlight(fill, rect):
                    continue
                color = _rgb_to_hex(fill)
                key = (
                    page_index,
                    color,
                    round(float(rect.x0)),
                    round(float(rect.y0)),
                    round(float(rect.x1)),
                    round(float(rect.y1)),
                )
                if key in seen:
                    continue
                seen.add(key)
                text = _words_under_rects(fitz, page, [rect])
                if not text:
                    warnings.append(f"empty_flattened_highlight_text:page-{page_index + 1}-rect-{flattened_index}")
                    flattened_index += 1
                    continue
                highlights.append(
                    ExtractedHighlight(
                        text=text,
                        color=color,
                        source_page=page_index + 1,
                        source_annotation_id=f"page-{page_index + 1}-flattened-{flattened_index}",
                        rect=[float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                        extraction_method="pymupdf_flattened_highlight_rect",
                    )
                )
                flattened_index += 1
    return highlights, warnings


def extract_pdf_highlights(pdf_path: Path) -> tuple[list[ExtractedHighlight], list[str]]:
    """Return highlight annotations with covered text and source colours.

    PyMuPDF is imported lazily so non-PDF ingest and unit tests can run without
    the optional PDF annotation dependency installed. Install `PyMuPDF` for real
    highlighted PDF extraction.
    """

    warnings: list[str] = []
    try:
        import fitz  # type: ignore
    except ImportError:
        return [], ["pymupdf_not_installed"]

    highlights: list[ExtractedHighlight] = []
    try:
        with fitz.open(pdf_path) as doc:
            for page_index, page in enumerate(doc):
                annot = page.first_annot
                annot_index = 0
                while annot:
                    annot_type = annot.type[1] if getattr(annot, "type", None) else ""
                    if str(annot_type).lower() == "highlight":
                        text = _words_under_annotation(fitz, page, annot)
                        color = _rgb_to_hex((getattr(annot, "colors", {}) or {}).get("stroke"))
                        if text:
                            rect = annot.rect
                            highlights.append(
                                ExtractedHighlight(
                                    text=text,
                                    color=color,
                                    source_page=page_index + 1,
                                    source_annotation_id=f"page-{page_index + 1}-annot-{annot_index}",
                                    rect=[float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                                )
                            )
                        else:
                            warnings.append(f"empty_highlight_text:page-{page_index + 1}-annot-{annot_index}")
                    annot = annot.next
                    annot_index += 1
    except Exception as exc:
        return [], [f"pdf_highlight_extraction_failed:{exc}"]
    if not highlights:
        try:
            flattened, flattened_warnings = _extract_flattened_highlights(fitz, pdf_path)
        except Exception as exc:
            return [], [*warnings, f"flattened_highlight_extraction_failed:{exc}"]
        if flattened:
            return flattened, [*warnings, "pdf_highlight_annotations_not_found_used_flattened_rectangles", *flattened_warnings]
        warnings.extend(flattened_warnings)
    return highlights, warnings
