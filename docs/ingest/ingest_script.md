# Ingest Script

The ingest script prepares source documents for LLM analysis.

## Responsibilities

- copy the source PDF into the workspace
- classify the PDF
- extract raw text
- optionally OCR
- clean the text
- detect structure hints
- split the text into chunks
- write manifests and logs

## Book-scoped output layout

Artifacts are grouped by `book_slug`:

```text
work/
  source/
  extracted/<book_slug>/
  cleaned/<book_slug>/
  chunks/<book_slug>/
  manifests/<book_slug>/
  logs/
```

## Typical usage

```bash
python manuscriptprep_ingest.py \
  --input source/book.pdf \
  --workdir work \
  --title "Treasure Island"
```

## Smaller chunk settings

If the orchestrator is timing out too often, use smaller chunk settings:

```bash
python manuscriptprep_ingest.py \
  --input source/book.pdf \
  --workdir work \
  --title "Treasure Island" \
  --chunk-words 1200 \
  --min-chunk-words 800 \
  --max-chunk-words 1500
```

## Output manifests

The ingest step writes:

- `chunk_manifest.json`
- `ingest_manifest.json`

These should be treated as the contract between ingest and orchestrator.
