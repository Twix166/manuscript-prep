# Cleaning

The cleaning stage removes PDF artifacts while preserving narrative structure.

## Typical artifacts removed

- repeated headers
- repeated footers
- standalone page numbers
- line-wrap damage
- dehyphenation issues
- obvious OCR noise

## Structure that should be preserved

- chapter headings
- part headings
- scene break markers
- paragraph boundaries
- dialogue punctuation

## Why cleaning matters

Poor cleaning causes downstream problems such as:

- malformed chunks
- table-of-contents contamination
- poor entity extraction
- unnecessary timeouts in heavier passes

## Output location

Cleaned text is written to:

```text
work/cleaned/<book_slug>/clean.txt
```
