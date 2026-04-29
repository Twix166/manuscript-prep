"""Shared text rules for Manuscript Prep cleaning and Narrator's Toolkit."""

from __future__ import annotations

import re


ROMAN_OR_WORD_NUMBER = r"(?:[ivxlcdm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
CHAPTER_KEYWORD_RE = re.compile(rf"^\s*(?:chapter|part|book)\s+{ROMAN_OR_WORD_NUMBER}(?:\s*[:.\-]\s*.+)?\s*$", re.I)
SPECIAL_SECTION_RE = re.compile(r"^\s*(?:prologue|epilogue|interlude|afterword|preface|foreword)\b(?:\s*[:.\-]\s*.+)?\s*$", re.I)
PAGE_MARKER_RE = re.compile(r"^\s*(?:page\s+\d+|\d+/\d+|\d+)\s*$", re.I)
TOC_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
SCENE_BREAK_RE = re.compile(r"^\s*(\*\s*\*\s*\*|-\s*-\s*-|•\s*•\s*•)\s*$")


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


def is_chapter_heading(text: str) -> bool:
    s = normalize_unicode(text).strip()
    if not s:
        return False
    return bool(CHAPTER_KEYWORD_RE.match(s) or SPECIAL_SECTION_RE.match(s))


def is_probable_heading(text: str) -> bool:
    s = normalize_unicode(text).strip()
    if not s:
        return False
    if is_chapter_heading(s):
        return True
    if len(s) <= 90 and s == s.upper() and re.search(r"[A-Z]", s):
        return True
    return False


def is_toc_like_paragraph(para: str) -> bool:
    s = para.strip()
    if TOC_DOT_LEADER_RE.search(s):
        return True
    if CHAPTER_KEYWORD_RE.match(s) and re.search(r"\b\d+\s*$", s):
        return True
    return False


def is_front_matter_like(para: str) -> bool:
    s = para.strip().lower()
    markers = {
        "contents",
        "table of contents",
        "preface",
        "introduction",
        "copyright",
        "title page",
    }
    return s in markers


def is_scene_break(text: str) -> bool:
    return bool(SCENE_BREAK_RE.match(text))
