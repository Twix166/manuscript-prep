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

## Supported Runner

The supported ingest entry point is:

```bash
python manuscriptprep_ingest.py
```

Config behavior:

- `--config` is optional.
- When `--config` is provided, ingest can derive workspace roots and chunk-size defaults from the shared YAML config.
- CLI flags still override config values.
- `--input` and `--title` remain required.

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
