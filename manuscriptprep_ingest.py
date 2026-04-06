#!/usr/bin/env python3
"""
manuscriptprep_ingest.py

End-to-end ingest pipeline for ManuscriptPrep.

Stages:
1. Create workspace
2. Classify PDF as text-based or OCR-needed
3. Extract raw text
4. Clean raw text
5. Detect structure hints
6. Chunk cleaned text into chunks/<book_slug>/
7. Write manifests and logs

Typical usage:
    python manuscriptprep_ingest.py \
      --input source/book.pdf \
      --workdir work \
      --title "Treasure Island"

Optional:
    python manuscriptprep_ingest.py \
      --input source/book.pdf \
      --workdir work \
      --title "Treasure Island" \
      --chunk-words 1200 \
      --min-chunk-words 800 \
      --max-chunk-words 1500 \
      --strip-front-matter \
      --strip-toc

Requirements:
- Python 3.10+
- PyYAML if using --config
- pdftotext (recommended)
- pdfinfo (optional but helpful)
- ocrmypdf + tesseract (optional, only for scanned PDFs)

This script is deterministic and does not use any LLMs.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from manuscriptprep.config import ConfigError, ManuscriptPrepConfig, load_config
from manuscriptprep.paths import build_paths


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"[\s\-]+", "_", title)
    title = re.sub(r"_+", "_", title)
    return title.strip("_")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


class Logger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        line = f"[{utc_now_iso()}] {message}"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)


@dataclass
class PdfClassification:
    pdf_type: str
    needs_ocr: bool
    native_sample_chars: int
    page_count: Optional[int]
    warnings: List[str]


@dataclass
class ChunkRecord:
    chunk_id: str
    path: str
    word_count: int
    char_count: int
    start_offset: int
    end_offset: int
    part_hint: Optional[str]
    chapter_hint: Optional[str]
    contains_toc_like_content: bool
    contains_front_matter: bool
    warnings: List[str]


@dataclass
class IngestRuntimeSettings:
    input_pdf: Path
    title: str
    workdir: Path
    source_dir: Path
    extracted_dir: Path
    cleaned_dir: Path
    chunks_dir: Path
    manifests_dir: Path
    logs_dir: Path
    tmp_dir: Path
    chunk_words: int
    min_chunk_words: int
    max_chunk_words: int
    force_ocr: bool
    strip_front_matter: bool
    strip_toc: bool


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found in PATH: {name}")


def try_pdftotext_extract(pdf_path: Path, output_path: Path) -> subprocess.CompletedProcess:
    require_tool("pdftotext")
    return subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(output_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def detect_page_count(pdf_path: Path) -> Optional[int]:
    try:
        require_tool("pdfinfo")
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if line.lower().startswith("pages:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    return None
    except Exception:
        return None
    return None


def classify_pdf(pdf_path: Path, tmp_dir: Path, logger: Logger) -> PdfClassification:
    sample_txt = tmp_dir / "native_sample.txt"
    warnings: List[str] = []
    page_count = detect_page_count(pdf_path)

    native_chars = 0
    needs_ocr = False
    pdf_type = "text"

    try:
        result = try_pdftotext_extract(pdf_path, sample_txt)
        if result.returncode != 0:
            warnings.append("native_extraction_failed")
            needs_ocr = True
            pdf_type = "image_or_mixed"
        else:
            text = sample_txt.read_text(encoding="utf-8", errors="ignore")
            native_chars = len(text.strip())
            if native_chars < 500:
                needs_ocr = True
                pdf_type = "image_or_mixed"
                warnings.append("native_text_too_sparse")
    except Exception as exc:
        warnings.append(f"native_extraction_exception:{exc}")
        needs_ocr = True
        pdf_type = "image_or_mixed"

    logger.log(
        f"PDF classification: pdf_type={pdf_type}, needs_ocr={needs_ocr}, "
        f"native_sample_chars={native_chars}, page_count={page_count}"
    )
    return PdfClassification(
        pdf_type=pdf_type,
        needs_ocr=needs_ocr,
        native_sample_chars=native_chars,
        page_count=page_count,
        warnings=warnings,
    )


def run_ocr(pdf_path: Path, ocr_pdf_path: Path, logger: Logger) -> None:
    require_tool("ocrmypdf")
    logger.log("Running OCR with ocrmypdf")
    result = subprocess.run(
        ["ocrmypdf", "--skip-text", str(pdf_path), str(ocr_pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ocrmypdf failed: {result.stderr.strip() or result.stdout.strip()}")


def extract_raw_text(
    pdf_path: Path,
    raw_txt_path: Path,
    raw_ocr_txt_path: Path,
    tmp_dir: Path,
    classification: PdfClassification,
    force_ocr: bool,
    logger: Logger,
) -> Dict[str, Any]:
    extraction_info: Dict[str, Any] = {
        "extractor": "pdftotext",
        "ocr_used": False,
        "raw_text_path": str(raw_txt_path),
        "raw_ocr_text_path": None,
        "warnings": [],
    }

    if force_ocr or classification.needs_ocr:
        ocr_pdf_path = tmp_dir / "ocr_output.pdf"
        run_ocr(pdf_path, ocr_pdf_path, logger)
        extraction_info["ocr_used"] = True

        result = try_pdftotext_extract(ocr_pdf_path, raw_ocr_txt_path)
        if result.returncode != 0:
            raise RuntimeError(f"pdftotext after OCR failed: {result.stderr.strip() or result.stdout.strip()}")

        text = read_text(raw_ocr_txt_path)
        write_text(raw_txt_path, text)
        extraction_info["raw_ocr_text_path"] = str(raw_ocr_txt_path)
        logger.log(f"Wrote OCR-extracted raw text to {raw_ocr_txt_path}")
    else:
        result = try_pdftotext_extract(pdf_path, raw_txt_path)
        if result.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {result.stderr.strip() or result.stdout.strip()}")

    logger.log(f"Wrote raw text to {raw_txt_path}")
    raw = read_text(raw_txt_path)
    extraction_info["raw_char_count"] = len(raw)
    extraction_info["raw_word_count"] = count_words(raw)
    return extraction_info


HEADER_FOOTER_LINE_RE = re.compile(r"^\s*(?:page\s+\d+|\d+/\d+|\d+)\s*$", re.I)
CHAPTER_RE = re.compile(r"^\s*chapter\s+[ivxlcdm0-9]+\b", re.I)
PART_RE = re.compile(r"^\s*part\s+\w+\b", re.I)
SCENE_BREAK_RE = re.compile(r"^\s*(\*\s*\*\s*\*|-\s*-\s*-|•\s*•\s*•)\s*$")
TOC_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")


def normalize_unicode(text: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "—",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def is_probable_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if CHAPTER_RE.match(s) or PART_RE.match(s):
        return True
    if len(s) <= 90 and s == s.upper() and re.search(r"[A-Z]", s):
        return True
    return False


def detect_repeated_lines(lines: List[str], min_count: int = 3) -> set[str]:
    counts = Counter(line.strip() for line in lines if line.strip())
    repeated = {
        line for line, count in counts.items()
        if count >= min_count and len(line) <= 120 and not CHAPTER_RE.match(line) and not PART_RE.match(line)
    }
    return repeated


def clean_text(raw_text: str, logger: Logger) -> Tuple[str, Dict[str, Any]]:
    raw_text = normalize_unicode(raw_text)
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    lines = raw_text.split("\n")
    repeated_lines = detect_repeated_lines(lines)

    cleaned_lines: List[str] = []
    removed_page_markers = 0
    removed_repeated_headers = 0

    for line in lines:
        stripped = line.strip()

        if HEADER_FOOTER_LINE_RE.match(stripped):
            removed_page_markers += 1
            continue

        if stripped in repeated_lines and not is_probable_heading(stripped):
            removed_repeated_headers += 1
            continue

        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)

    lines = text.split("\n")
    paragraphs: List[str] = []
    buffer: List[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        para = " ".join(part.strip() for part in buffer if part.strip())
        para = re.sub(r"\s+", " ", para).strip()
        if para:
            paragraphs.append(para)
        buffer = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_buffer()
            continue

        if is_probable_heading(stripped) or SCENE_BREAK_RE.match(stripped):
            flush_buffer()
            paragraphs.append(stripped)
            continue

        if TOC_DOT_LEADER_RE.search(stripped):
            flush_buffer()
            paragraphs.append(stripped)
            continue

        buffer.append(stripped)

    flush_buffer()

    clean_text_out = "\n\n".join(paragraphs).strip() + "\n"

    cleaning_stats = {
        "removed_page_markers": removed_page_markers,
        "removed_repeated_headers": removed_repeated_headers,
        "raw_char_count": len(raw_text),
        "clean_char_count": len(clean_text_out),
        "raw_word_count": count_words(raw_text),
        "clean_word_count": count_words(clean_text_out),
    }

    logger.log(
        f"Cleaned text: removed_page_markers={removed_page_markers}, "
        f"removed_repeated_headers={removed_repeated_headers}, "
        f"clean_word_count={cleaning_stats['clean_word_count']}"
    )
    return clean_text_out, cleaning_stats


def detect_structure_hints(clean_text_value: str) -> Dict[str, Any]:
    paragraphs = [p.strip() for p in clean_text_value.split("\n\n") if p.strip()]

    parts: List[str] = []
    chapters: List[str] = []
    scene_breaks: List[str] = []

    for para in paragraphs:
        if PART_RE.match(para):
            parts.append(para)
        elif CHAPTER_RE.match(para):
            chapters.append(para)
        elif SCENE_BREAK_RE.match(para):
            scene_breaks.append(para)

    return {
        "parts": unique_preserve_order(parts),
        "chapters": unique_preserve_order(chapters),
        "scene_break_markers": unique_preserve_order(scene_breaks),
    }


def is_toc_like_paragraph(para: str) -> bool:
    s = para.strip()
    if TOC_DOT_LEADER_RE.search(s):
        return True
    if CHAPTER_RE.match(s) and re.search(r"\b\d+\s*$", s):
        return True
    return False


def is_front_matter_like(para: str) -> bool:
    s = para.strip().lower()
    markers = [
        "contents",
        "table of contents",
        "preface",
        "introduction",
        "copyright",
        "title page",
    ]
    return s in markers


def chunk_clean_text(
    clean_text_value: str,
    book_title: str,
    chunks_root: Path,
    min_chunk_words: int,
    target_chunk_words: int,
    max_chunk_words: int,
    logger: Logger,
) -> Tuple[List[ChunkRecord], Dict[str, Any]]:
    book_slug = slugify(book_title)
    book_chunk_dir = chunks_root / book_slug
    book_chunk_dir.mkdir(parents=True, exist_ok=True)

    paragraphs = [p.strip() for p in clean_text_value.split("\n\n") if p.strip()]

    chunks: List[ChunkRecord] = []
    current: List[str] = []
    current_words = 0
    char_cursor = 0

    current_part: Optional[str] = None
    current_chapter: Optional[str] = None

    def finalize_chunk(index: int) -> None:
        nonlocal current, current_words, char_cursor
        if not current:
            return

        chunk_text = "\n\n".join(current).strip() + "\n"
        chunk_id = f"chunk_{index:03d}"
        chunk_path = book_chunk_dir / f"{chunk_id}.txt"

        write_text(chunk_path, chunk_text)

        contains_toc_like = any(is_toc_like_paragraph(p) for p in current)
        contains_front_matter = any(is_front_matter_like(p) for p in current)
        warnings: List[str] = []

        wc = count_words(chunk_text)
        cc = len(chunk_text)

        if wc < min_chunk_words:
            warnings.append("short_chunk")
        if contains_toc_like:
            warnings.append("toc_like_content")
        if contains_front_matter:
            warnings.append("front_matter_like")

        chunk_record = ChunkRecord(
            chunk_id=chunk_id,
            path=str(chunk_path),
            word_count=wc,
            char_count=cc,
            start_offset=char_cursor,
            end_offset=char_cursor + cc,
            part_hint=current_part,
            chapter_hint=current_chapter,
            contains_toc_like_content=contains_toc_like,
            contains_front_matter=contains_front_matter,
            warnings=warnings,
        )
        chunks.append(chunk_record)
        logger.log(f"Wrote {chunk_id} -> {chunk_path} ({wc} words)")
        char_cursor += cc
        current = []
        current_words = 0

    chunk_index = 0

    for para in paragraphs:
        para_words = count_words(para)

        if PART_RE.match(para):
            current_part = para

        if CHAPTER_RE.match(para):
            if current and current_words >= min_chunk_words:
                finalize_chunk(chunk_index)
                chunk_index += 1
            current_chapter = para
            current.append(para)
            current_words += para_words
            continue

        if SCENE_BREAK_RE.match(para):
            if current and current_words >= target_chunk_words:
                finalize_chunk(chunk_index)
                chunk_index += 1
            current.append(para)
            current_words += para_words
            continue

        if current and (current_words + para_words > max_chunk_words):
            finalize_chunk(chunk_index)
            chunk_index += 1

        current.append(para)
        current_words += para_words

        if current_words >= target_chunk_words and (
            para.endswith(".") or para.endswith('"') or para.endswith("'") or is_probable_heading(para)
        ):
            finalize_chunk(chunk_index)
            chunk_index += 1

    if current:
        finalize_chunk(chunk_index)

    chunk_stats = {
        "book_title": book_title,
        "book_slug": book_slug,
        "chunk_dir": str(book_chunk_dir),
        "chunk_count": len(chunks),
        "total_chunk_words": sum(c.word_count for c in chunks),
        "avg_chunk_words": round(sum(c.word_count for c in chunks) / max(len(chunks), 1), 2),
        "target_chunk_words": target_chunk_words,
        "min_chunk_words": min_chunk_words,
        "max_chunk_words": max_chunk_words,
    }
    return chunks, chunk_stats


def resolve_work_paths(cfg: Optional[ManuscriptPrepConfig], workdir: Path, book_slug: str) -> Dict[str, Path]:
    if cfg is None:
        return {
            "source_dir": workdir / "source",
            "extracted_dir": workdir / "extracted" / book_slug,
            "cleaned_dir": workdir / "cleaned" / book_slug,
            "chunks_dir": workdir / "chunks",
            "manifests_dir": workdir / "manifests" / book_slug,
            "logs_dir": workdir / "logs",
            "tmp_dir": workdir / "tmp" / book_slug,
        }

    paths = build_paths(cfg)
    return {
        "source_dir": paths.input_root,
        "extracted_dir": paths.extracted_root / book_slug,
        "cleaned_dir": paths.cleaned_root / book_slug,
        "chunks_dir": paths.chunks_root,
        "manifests_dir": paths.workspace_root / "manifests" / book_slug,
        "logs_dir": paths.logs_root,
        "tmp_dir": paths.workspace_root / "tmp" / book_slug,
    }


def resolve_ingest_settings(args: argparse.Namespace, cfg: Optional[ManuscriptPrepConfig]) -> IngestRuntimeSettings:
    if args.input is None:
        raise ConfigError("Missing required input PDF. Use --input.")
    if args.title is None:
        raise ConfigError("Missing required book title. Use --title.")

    input_pdf = args.input.expanduser()
    title = args.title
    book_slug = slugify(title)

    if cfg is not None:
        workdir = (args.workdir.expanduser() if args.workdir is not None else Path(cfg.require("paths", "workspace_root")).expanduser())
        chunk_words = args.chunk_words if args.chunk_words is not None else int(cfg.get("chunking", "target_words", default=1800))
        min_chunk_words = args.min_chunk_words if args.min_chunk_words is not None else int(cfg.get("chunking", "min_words", default=1200))
        max_chunk_words = args.max_chunk_words if args.max_chunk_words is not None else int(cfg.get("chunking", "max_words", default=2200))
    else:
        if args.workdir is None:
            raise ConfigError("Missing required workspace directory. Use --workdir or provide --config.")
        workdir = args.workdir.expanduser()
        chunk_words = args.chunk_words if args.chunk_words is not None else 1800
        min_chunk_words = args.min_chunk_words if args.min_chunk_words is not None else 1200
        max_chunk_words = args.max_chunk_words if args.max_chunk_words is not None else 2200

    paths = resolve_work_paths(cfg, workdir, book_slug)
    return IngestRuntimeSettings(
        input_pdf=input_pdf,
        title=title,
        workdir=workdir,
        source_dir=paths["source_dir"],
        extracted_dir=paths["extracted_dir"],
        cleaned_dir=paths["cleaned_dir"],
        chunks_dir=paths["chunks_dir"],
        manifests_dir=paths["manifests_dir"],
        logs_dir=paths["logs_dir"],
        tmp_dir=paths["tmp_dir"],
        chunk_words=chunk_words,
        min_chunk_words=min_chunk_words,
        max_chunk_words=max_chunk_words,
        force_ocr=args.force_ocr,
        strip_front_matter=args.strip_front_matter,
        strip_toc=args.strip_toc,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="End-to-end ingest pipeline for ManuscriptPrep")
    parser.add_argument("--config", type=Path, default=None, help="Optional YAML config file")
    parser.add_argument("--input", type=Path, required=False, help="Source PDF path")
    parser.add_argument("--workdir", type=Path, required=False, help="Workspace directory")
    parser.add_argument("--title", required=False, help="Book title, used for book_slug subdirectories")
    parser.add_argument(
        "--chunk-words",
        type=int,
        default=None,
        help="Target chunk size in words. Reduce this if the orchestrator is timing out.",
    )
    parser.add_argument("--min-chunk-words", type=int, default=None, help="Minimum chunk size in words")
    parser.add_argument("--max-chunk-words", type=int, default=None, help="Maximum chunk size in words")
    parser.add_argument("--force-ocr", action="store_true", help="Force OCR extraction path")
    parser.add_argument("--strip-front-matter", action="store_true", help="Reserved flag for future front matter splitting")
    parser.add_argument("--strip-toc", action="store_true", help="Reserved flag for future TOC splitting")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        cfg = load_config(args.config) if args.config is not None else None
        settings = resolve_ingest_settings(args, cfg)
    except (ConfigError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    input_pdf = settings.input_pdf
    if not input_pdf.is_file():
        print(f"Input PDF does not exist: {input_pdf}", file=sys.stderr)
        return 1

    if settings.min_chunk_words > settings.chunk_words or settings.chunk_words > settings.max_chunk_words:
        print(
            "Chunk sizes must satisfy: min_chunk_words <= chunk_words <= max_chunk_words",
            file=sys.stderr,
        )
        return 1

    book_slug = slugify(settings.title)

    for d in [
        settings.source_dir,
        settings.extracted_dir,
        settings.cleaned_dir,
        settings.chunks_dir,
        settings.manifests_dir,
        settings.logs_dir,
        settings.tmp_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    logger = Logger(settings.logs_dir / "ingest.log")
    logger.log(f"Starting ManuscriptPrep ingest for title='{settings.title}' slug='{book_slug}'")

    workspace_pdf = settings.source_dir / input_pdf.name
    if workspace_pdf.resolve() != input_pdf.resolve():
        shutil.copy2(input_pdf, workspace_pdf)
        logger.log(f"Copied source PDF to workspace: {workspace_pdf}")
    else:
        logger.log(f"Using source PDF in place: {workspace_pdf}")

    raw_txt_path = settings.extracted_dir / "raw.txt"
    raw_ocr_txt_path = settings.extracted_dir / "raw_ocr.txt"
    clean_txt_path = settings.cleaned_dir / "clean.txt"

    classification = classify_pdf(workspace_pdf, settings.tmp_dir, logger)

    extraction_info = extract_raw_text(
        pdf_path=workspace_pdf,
        raw_txt_path=raw_txt_path,
        raw_ocr_txt_path=raw_ocr_txt_path,
        tmp_dir=settings.tmp_dir,
        classification=classification,
        force_ocr=settings.force_ocr,
        logger=logger,
    )

    raw_text = read_text(raw_txt_path)
    clean_text_value, cleaning_stats = clean_text(raw_text, logger)
    write_text(clean_txt_path, clean_text_value)
    logger.log(f"Wrote cleaned text to {clean_txt_path}")

    structure_hints = detect_structure_hints(clean_text_value)

    chunks, chunk_stats = chunk_clean_text(
        clean_text_value=clean_text_value,
        book_title=settings.title,
        chunks_root=settings.chunks_dir,
        min_chunk_words=settings.min_chunk_words,
        target_chunk_words=settings.chunk_words,
        max_chunk_words=settings.max_chunk_words,
        logger=logger,
    )

    chunk_manifest = {
        "source_pdf": str(workspace_pdf),
        "book_title": settings.title,
        "book_slug": book_slug,
        "raw_text": str(raw_txt_path),
        "clean_text": str(clean_txt_path),
        "chunk_dir": str(settings.chunks_dir / book_slug),
        "chunk_count": len(chunks),
        "chunk_settings": {
            "target_chunk_words": settings.chunk_words,
            "min_chunk_words": settings.min_chunk_words,
            "max_chunk_words": settings.max_chunk_words,
        },
        "chunks": [asdict(c) for c in chunks],
    }

    ingest_manifest = {
        "timestamp": utc_now_iso(),
        "source_pdf": str(workspace_pdf),
        "book_title": settings.title,
        "book_slug": book_slug,
        "paths": {
            "raw_text": str(raw_txt_path),
            "raw_ocr_text": str(raw_ocr_txt_path) if extraction_info.get("ocr_used") else None,
            "clean_text": str(clean_txt_path),
            "chunk_dir": str(settings.chunks_dir / book_slug),
        },
        "classification": asdict(classification),
        "extraction": extraction_info,
        "cleaning": cleaning_stats,
        "structure_hints": structure_hints,
        "chunking": chunk_stats,
        "flags": {
            "strip_front_matter": settings.strip_front_matter,
            "strip_toc": settings.strip_toc,
            "force_ocr": settings.force_ocr,
        },
        "config_path": str(args.config.expanduser().resolve()) if args.config is not None else None,
    }

    write_json(settings.manifests_dir / "chunk_manifest.json", chunk_manifest)
    write_json(settings.manifests_dir / "ingest_manifest.json", ingest_manifest)

    logger.log(f"Wrote chunk manifest to {settings.manifests_dir / 'chunk_manifest.json'}")
    logger.log(f"Wrote ingest manifest to {settings.manifests_dir / 'ingest_manifest.json'}")
    logger.log("Ingest complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
