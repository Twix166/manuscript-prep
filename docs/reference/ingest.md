# Ingest Reference

## Purpose

The ingest stage prepares a source manuscript for LLM processing.

## Responsibilities

- classify the source PDF
- extract raw text
- optionally OCR when required
- clean the extracted text
- split the manuscript into chunks
- write manifests and ingest logs

## Inputs

- source PDF
- config file
- optional chunk size overrides

## Outputs

Typical outputs:

```text
work/
  extracted/<book_slug>/
  cleaned/<book_slug>/
  chunks/<book_slug>/
  manifests/<book_slug>/
```

## Key config sections

- `paths`
- `chunking`
- `logging`

## Notes

The ingest layer should remain deterministic and should not call Ollama.
