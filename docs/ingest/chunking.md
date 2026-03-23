# Chunking

Chunking should be structure-aware and paragraph-aware.

## Output location

Chunk files are written to:

```text
work/chunks/<book_slug>/
```

This makes each manuscript's chunks easy to identify and pass into the orchestrator.

## Chunk size controls

The ingest script supports:

- `--chunk-words`
- `--min-chunk-words`
- `--max-chunk-words`

Example:

```bash
python manuscriptprep_ingest.py \
  --input source/book.pdf \
  --workdir work \
  --title "Treasure Island" \
  --chunk-words 1200 \
  --min-chunk-words 800 \
  --max-chunk-words 1500
```

## Why smaller chunks helped this project

In this project, smaller chunks reduced:

- idle timeout failures
- dossier stalls
- malformed output frequency
- overly long visible reasoning

## Practical recommendation

For this stack, start around:

- target chunk size: 1200 words
- minimum chunk size: 800 words
- maximum chunk size: 1500 words

Then tune based on real timing and failure data.
