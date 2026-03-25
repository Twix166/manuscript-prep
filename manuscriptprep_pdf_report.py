#!/usr/bin/env python3
"""
manuscriptprep_pdf_report.py

Create a formatted PDF report from merged ManuscriptPrep outputs.

Typical usage:
    python manuscriptprep_pdf_report.py \
      --input-dir merged/treasure_island \
      --output reports/treasure_island_report.pdf \
      --title "Treasure Island" \
      --subtitle "Merged ManuscriptPrep Analysis Report"

Requires:
    pip install reportlab
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


PAGE_WIDTH, PAGE_HEIGHT = A4


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def maybe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    if path.exists():
        return read_json(path)
    return None


def normalize_text(text: Any) -> str:
    return " ".join(str(text).split())


def truncate(text: Any, n: int = 160) -> str:
    text = normalize_text(text)
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


class ReportDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(
            18 * mm,
            18 * mm,
            PAGE_WIDTH - 36 * mm,
            PAGE_HEIGHT - 32 * mm,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="normal",
        )
        template = PageTemplate(id="main", frames=[frame], onPage=self._draw_page)
        self.addPageTemplates([template])

    def _draw_page(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#5B6C8F"))
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(18 * mm, PAGE_HEIGHT - 12 * mm, "ManuscriptPrep Book Report")
        canvas.setFillColor(colors.HexColor("#808080"))
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(PAGE_WIDTH - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and hasattr(flowable, "_bookmarkName"):
            level = getattr(flowable, "_headingLevel", None)
            text = flowable.getPlainText()
            if level is not None:
                self.notify("TOCEntry", (level, text, self.page))


def make_styles():
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#243B63"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSubtitle",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#5E6B7A"),
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#243B63"),
            spaceBefore=10,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#37507A"),
            spaceBefore=8,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=12.5,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=11,
            textColor=colors.HexColor("#1E3557"),
            spaceAfter=0,
            spaceBefore=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.1,
            leading=11.2,
            spaceAfter=0,
            spaceBefore=0,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCellCompact",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.2,
            spaceAfter=0,
            spaceBefore=0,
            wordWrap="CJK",
        )
    )
    return styles


def add_heading(story, text: str, styles, level: int = 0):
    style = styles["SectionHeading"] if level == 0 else styles["SubHeading"]
    p = Paragraph(text, style)
    p._bookmarkName = text.replace(" ", "_").replace("/", "_")
    p._headingLevel = level
    story.append(p)


def p(text: Any, style: ParagraphStyle) -> Paragraph:
    safe = normalize_text(text)
    return Paragraph(safe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def info_table(rows: List[List[Any]], styles, col_widths=None, compact=False):
    header_style = styles["TableHeader"]
    cell_style = styles["TableCellCompact"] if compact else styles["TableCell"]

    converted = []
    for r_idx, row in enumerate(rows):
        converted_row = []
        for cell in row:
            converted_row.append(p(cell, header_style if r_idx == 0 else cell_style))
        converted.append(converted_row)

    table = Table(converted, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3557")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C6D9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFE")]),
            ]
        )
    )
    return table


def add_summary_cards(story, styles, summary_items: List[tuple[str, str]]):
    rows = []
    card_row = []
    widths = [58 * mm, 58 * mm, 58 * mm]
    for label, value in summary_items:
        card = Table(
            [
                [Paragraph(f"<b>{label}</b>", styles["BodyText"])],
                [Paragraph(normalize_text(value), styles["BodySmall"])],
            ],
            colWidths=[54 * mm],
        )
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F9FD")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#C5D3E4")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DCE6F4")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        card_row.append(card)
        if len(card_row) == 3:
            rows.append(card_row)
            card_row = []
    if card_row:
        while len(card_row) < 3:
            card_row.append("")
        rows.append(card_row)
    grid = Table(rows, colWidths=widths, hAlign="LEFT")
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(grid)
    story.append(Spacer(1, 8))


def build_toc():
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            fontName="Helvetica",
            fontSize=10,
            name="TOCLevel0",
            leftIndent=10,
            firstLineIndent=-2,
            spaceBefore=3,
            leading=12,
        ),
        ParagraphStyle(
            fontName="Helvetica",
            fontSize=9,
            name="TOCLevel1",
            leftIndent=22,
            firstLineIndent=-2,
            spaceBefore=1,
            leading=11,
            textColor=colors.HexColor("#4B5B72"),
        ),
    ]
    return toc


def add_kv_paragraphs(story, styles, items: List[tuple[str, Any]]):
    for k, v in items:
        story.append(Paragraph(f"<b>{k}:</b> {normalize_text(v)}", styles["BodySmall"]))
    story.append(Spacer(1, 4))


def add_entities_section(story, styles, entities: Dict[str, Any]):
    add_heading(story, "Entities", styles, 0)
    story.append(
        Paragraph(
            "This section consolidates literal entity extraction across all chunks. "
            "Normalized tables help reveal surface-form variation without forcing aggressive identity merges.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4))

    for key, label in [
        ("characters", "Characters"),
        ("places", "Places"),
        ("objects", "Objects"),
        ("identity_notes", "Identity Notes"),
    ]:
        add_heading(story, label, styles, 1)
        items = entities.get(key, [])
        if items:
            rows = [["Value"]]
            rows.extend([[truncate(x, 160)] for x in items if isinstance(x, str)])
            story.append(info_table(rows, styles, col_widths=[170 * mm]))
        else:
            story.append(Paragraph("No entries recorded.", styles["BodySmall"]))
        story.append(Spacer(1, 6))

        norm_items = entities.get(f"{key}_normalized", [])
        if norm_items:
            rows = [["Canonical", "Variants", "Chunks"]]
            for item in norm_items[:40]:
                rows.append(
                    [
                        truncate(item.get("canonical", ""), 48),
                        truncate(", ".join(item.get("variants", [])), 120),
                        ", ".join(item.get("chunks", [])),
                    ]
                )
            story.append(info_table(rows, styles, col_widths=[40 * mm, 102 * mm, 28 * mm], compact=True))
            story.append(Spacer(1, 8))


def add_dossiers_section(story, styles, dossiers: Dict[str, Any]):
    add_heading(story, "Dossiers", styles, 0)
    dossier_list = dossiers.get("character_dossiers", [])
    story.append(
        Paragraph(
            "Merged dossiers preserve cross-chunk provenance and retain disagreements rather than forcing silent reconciliation.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 6))

    if not dossier_list:
        story.append(Paragraph("No merged dossiers were found.", styles["BodySmall"]))
        return

    for dossier in dossier_list:
        name = dossier.get("name", "Unknown")
        variants = ", ".join(dossier.get("variants", [])) or "—"
        aliases = ", ".join(dossier.get("aliases", [])) or "—"
        roles = ", ".join(dossier.get("roles", [])) or "—"
        accents = ", ".join(dossier.get("accents", [])) or "—"
        chunks = ", ".join(dossier.get("chunks", [])) or "—"
        traits = ", ".join(dossier.get("personality_traits", [])) or "—"
        bios = dossier.get("biographies", [])
        vocal_notes = ", ".join(dossier.get("vocal_notes", [])) or "—"
        spoken = ", ".join(str(x) for x in dossier.get("spoken_dialogue_values", [])) or "—"
        identity_status = ", ".join(dossier.get("identity_status_values", [])) or "—"

        add_heading(story, name, styles, 1)
        rows = [
            ["Field", "Value"],
            ["Variants", truncate(variants, 220)],
            ["Aliases", truncate(aliases, 220)],
            ["Roles", truncate(roles, 220)],
            ["Traits", truncate(traits, 220)],
            ["Accents", truncate(accents, 220)],
            ["Vocal notes", truncate(vocal_notes, 220)],
            ["Spoken dialogue values", truncate(spoken, 220)],
            ["Identity status values", truncate(identity_status, 220)],
            ["Chunks", truncate(chunks, 220)],
        ]
        story.append(info_table(rows, styles, col_widths=[46 * mm, 130 * mm], compact=True))
        story.append(Spacer(1, 4))

        if bios:
            story.append(Paragraph("<b>Biography evidence</b>", styles["BodySmall"]))
            for bio in bios:
                story.append(Paragraph(truncate(bio, 1000), styles["BodySmall"]))
                story.append(Spacer(1, 2))

        story.append(Spacer(1, 8))


def add_conflict_section(story, styles, conflict_report: Dict[str, Any]):
    add_heading(story, "Conflict Report", styles, 0)
    summary = conflict_report.get("summary", {})
    add_summary_cards(
        story,
        styles,
        [
            ("Character conflicts", str(summary.get("character_conflict_count", 0))),
            ("Entity variant notes", str(summary.get("entity_variant_note_count", 0))),
            ("Global conflicts", str(summary.get("global_conflict_count", 0))),
        ],
    )

    character_conflicts = conflict_report.get("character_conflicts", [])
    if character_conflicts:
        add_heading(story, "Character-Level Conflicts", styles, 1)
        rows = [["Name", "Conflict type(s)", "Severity / values"]]
        for item in character_conflicts[:60]:
            conflict_types = ", ".join(c.get("type", "") for c in item.get("conflicts", []))
            severity_values = []
            for c in item.get("conflicts", []):
                severity_values.append(f"{c.get('severity', '')}: {', '.join(map(str, c.get('values', [])))}")
            rows.append(
                [
                    truncate(item.get("name", ""), 36),
                    truncate(conflict_types, 48),
                    truncate(" | ".join(severity_values), 110),
                ]
            )
        story.append(info_table(rows, styles, col_widths=[38 * mm, 46 * mm, 92 * mm], compact=True))
        story.append(Spacer(1, 8))
    else:
        story.append(Paragraph("No character-level conflicts were detected.", styles["BodySmall"]))
        story.append(Spacer(1, 6))

    global_conflicts = conflict_report.get("global_conflicts", [])
    if global_conflicts:
        add_heading(story, "Global Conflicts", styles, 1)
        rows = [["Type", "Severity", "Values / note"]]
        for item in global_conflicts:
            rows.append(
                [
                    item.get("type", ""),
                    item.get("severity", ""),
                    truncate(f"{', '.join(map(str, item.get('values', [])))} — {item.get('message', '')}", 120),
                ]
            )
        story.append(info_table(rows, styles, col_widths=[42 * mm, 25 * mm, 109 * mm], compact=True))
        story.append(Spacer(1, 8))

    variant_notes = conflict_report.get("entity_variant_notes", {})
    if variant_notes:
        add_heading(story, "Entity Variant Notes", styles, 1)
        rows = [["Group", "Canonical", "Variants"]]
        total_rows = 0
        for group_name, notes in variant_notes.items():
            for note in notes[:20]:
                rows.append(
                    [
                        group_name,
                        truncate(note.get("canonical", ""), 30),
                        truncate(", ".join(note.get("variants", [])), 120),
                    ]
                )
                total_rows += 1
        if total_rows:
            story.append(info_table(rows, styles, col_widths=[40 * mm, 38 * mm, 98 * mm], compact=True))
        else:
            story.append(Paragraph("No entity variant notes were detected.", styles["BodySmall"]))


def build_story(data: Dict[str, Dict[str, Any]], title: str, subtitle: str):
    styles = make_styles()
    story = []

    book_merged = data.get("book_merged") or {}
    structure = data.get("structure_merged") or {}
    dialogue = data.get("dialogue_merged") or {}
    entities = data.get("entities_merged") or {}
    dossiers = data.get("dossiers_merged") or {}
    conflict_report = data.get("conflict_report") or {}
    merge_report = data.get("merge_report") or {}

    story.append(Spacer(1, 24))
    story.append(Paragraph(title, styles["ReportTitle"]))
    story.append(Paragraph(subtitle, styles["ReportSubtitle"]))

    summary_items = [
        ("Book slug", str(book_merged.get("book_slug", "—"))),
        ("Chunks merged", str(merge_report.get("chunk_count", "—"))),
        ("Dominant POV", str(dialogue.get("dominant_pov", "—"))),
        ("Chapters", str(len(structure.get("chapters", [])))),
        ("Characters", str(len(entities.get("characters", [])))),
        ("Merged dossiers", str(len(dossiers.get("character_dossiers", [])))),
    ]
    add_summary_cards(story, styles, summary_items)

    story.append(
        Paragraph(
            "This report consolidates the merged ManuscriptPrep outputs for a single manuscript. "
            "It includes document structure, dialogue summary, entity extraction, merged character dossiers, "
            "and conflict and merge diagnostics.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 12))

    add_heading(story, "Contents", styles, 0)
    story.append(build_toc())
    story.append(PageBreak())

    add_heading(story, "Executive Summary", styles, 0)
    add_kv_paragraphs(
        story,
        styles,
        [
            ("Book title", book_merged.get("book_title", "—")),
            ("Book slug", book_merged.get("book_slug", "—")),
            ("Source chunk manifest", book_merged.get("source_chunk_manifest", "—")),
            ("Chunks merged", merge_report.get("chunk_count", "—")),
        ],
    )

    timing = book_merged.get("timing_summary", {})
    if timing:
        story.append(Paragraph("<b>Timing summary</b>", styles["SubHeading"]))
        rows = [["Metric", "Value"]]
        rows.append(["Book total duration (s)", str(timing.get("book_total_duration_seconds", "—"))])
        for k, v in (timing.get("pass_total_duration_seconds", {}) or {}).items():
            rows.append([f"Total {k} duration (s)", str(v)])
        story.append(info_table(rows, styles, col_widths=[105 * mm, 70 * mm]))
        story.append(Spacer(1, 8))

    add_heading(story, "Structure", styles, 0)
    story.append(
        Paragraph(
            "Merged structure output lists observed chapter and part headings, scene break evidence, "
            "and chunk-level status notes.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 4))
    rows = [["Metric", "Value"]]
    rows.extend(
        [
            ["Chapters detected", str(len(structure.get("chapters", [])))],
            ["Parts detected", str(len(structure.get("parts", [])))],
            ["Scene breaks recorded", str(len(structure.get("scene_breaks", [])))],
        ]
    )
    story.append(info_table(rows, styles, col_widths=[95 * mm, 80 * mm]))
    story.append(Spacer(1, 8))

    if structure.get("chapters"):
        add_heading(story, "Chapter List", styles, 1)
        chapter_rows = [["#", "Chapter"]]
        for idx, ch in enumerate(structure.get("chapters", []), start=1):
            chapter_rows.append([str(idx), truncate(ch, 180)])
        story.append(info_table(chapter_rows, styles, col_widths=[12 * mm, 163 * mm], compact=True))
        story.append(Spacer(1, 8))

    if structure.get("parts"):
        add_heading(story, "Part List", styles, 1)
        part_rows = [["#", "Part"]]
        for idx, ptxt in enumerate(structure.get("parts", []), start=1):
            part_rows.append([str(idx), truncate(ptxt, 180)])
        story.append(info_table(part_rows, styles, col_widths=[12 * mm, 163 * mm], compact=True))
        story.append(Spacer(1, 8))

    add_heading(story, "Dialogue", styles, 0)
    rows = [["Metric", "Value"]]
    rows.extend(
        [
            ["Dominant POV", str(dialogue.get("dominant_pov", "—"))],
            ["Observed POV values", ", ".join(dialogue.get("observed_pov_values", [])) or "—"],
            ["Chunks with dialogue", str(dialogue.get("dialogue_present_in_chunks", 0))],
            ["Chunks with internal thought", str(dialogue.get("internal_thought_present_in_chunks", 0))],
            ["Chunks with unattributed dialogue", str(dialogue.get("unattributed_dialogue_present_in_chunks", 0))],
            ["Attributed speakers", ", ".join(dialogue.get("explicitly_attributed_speakers", [])) or "—"],
        ]
    )
    story.append(info_table(rows, styles, col_widths=[66 * mm, 109 * mm]))
    story.append(Spacer(1, 8))

    add_entities_section(story, styles, entities)
    story.append(PageBreak())
    add_dossiers_section(story, styles, dossiers)
    story.append(PageBreak())
    add_conflict_section(story, styles, conflict_report)

    add_heading(story, "Merge Report", styles, 0)
    present_counts = merge_report.get("present_counts", {})
    missing = merge_report.get("missing", {})
    rows = [["Artifact", "Present count", "Missing chunks"]]
    for key in ["structure", "dialogue", "entities", "dossiers", "timing"]:
        rows.append(
            [
                key,
                str(present_counts.get(key, 0)),
                ", ".join(missing.get(key, [])) or "—",
            ]
        )
    story.append(info_table(rows, styles, col_widths=[32 * mm, 30 * mm, 113 * mm], compact=True))

    return story


def parse_args():
    parser = argparse.ArgumentParser(description="Create a formatted PDF report from merged ManuscriptPrep outputs.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing merged JSON outputs")
    parser.add_argument("--output", type=Path, required=True, help="Destination PDF path")
    parser.add_argument("--title", default=None, help="Override report title")
    parser.add_argument("--subtitle", default="Merged ManuscriptPrep Analysis Report", help="Report subtitle")
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_dir}")

    data = {
        "book_merged": maybe_read_json(args.input_dir / "book_merged.json"),
        "structure_merged": maybe_read_json(args.input_dir / "structure_merged.json"),
        "dialogue_merged": maybe_read_json(args.input_dir / "dialogue_merged.json"),
        "entities_merged": maybe_read_json(args.input_dir / "entities_merged.json"),
        "dossiers_merged": maybe_read_json(args.input_dir / "dossiers_merged.json"),
        "conflict_report": maybe_read_json(args.input_dir / "conflict_report.json"),
        "merge_report": maybe_read_json(args.input_dir / "merge_report.json"),
    }

    book_title = args.title
    if not book_title:
        book_title = (
            (data.get("book_merged") or {}).get("book_title")
            or (data.get("book_merged") or {}).get("book_slug")
            or "ManuscriptPrep Book Report"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)

    doc = ReportDocTemplate(
        str(args.output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=book_title,
        author="OpenAI / ManuscriptPrep",
    )

    story = build_story(data, book_title, args.subtitle)
    doc.build(story)

    print(f"Wrote PDF report to {args.output}")


if __name__ == "__main__":
    main()
