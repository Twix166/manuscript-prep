# Narrator's Toolkit Cleaned Document Format

Current schema: `narrator-toolkit.cleaned-document.v1`

The document is a standalone JSON artifact. It is generated during ManuscriptPrep ingest next to `clean.txt`, but it can be consumed independently by Narrator's Toolkit.

Key fields:

- `schema_version`: migration-safe schema identifier.
- `document_format_version`: numeric format version.
- `chapters[].blocks[]`: cleaned continuous manuscript text, split into headings and paragraphs.
- `blocks[].spans[]`: structured highlight spans with block-relative offsets.
- `highlight_palette`: colours found in mapped highlights and their usage counts.
- `metadata.highlight_report`: mapping QA summary.

Highlight spans preserve:

- `start` and `end` offsets within the block text.
- `color` as a hex RGB string.
- `source_page`.
- `source_annotation_id`.
- `character`, currently `null`.
- mapping method and confidence.

The cleaner writes a separate `highlight_report.json`:

```json
{
  "total_highlights": 100,
  "mapped_highlights": 96,
  "unmapped_highlights": 4,
  "mapping_warnings": []
}
```

Narrator's Toolkit warns the user when `unmapped_highlights` is non-zero.

