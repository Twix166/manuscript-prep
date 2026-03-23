# Data Flow

## Source input

The source input is typically a manuscript PDF.

## Workspace outputs from ingest

The ingest step writes to a working directory, typically something like:

```text
work/
  source/
  extracted/<book_slug>/
  cleaned/<book_slug>/
  chunks/<book_slug>/
  manifests/<book_slug>/
  logs/
```

## Analysis outputs from orchestrator

The orchestrator writes per-chunk results, typically:

```text
out/<book_slug>/<chunk_id>/
  structure.json
  dialogue.json
  entities.json
  dossiers.json
  *_raw.txt
  dossier_input.txt
  timing.json
  error.txt
```

## Traceability

Every meaningful stage writes an artifact to disk so that you can inspect:

- what text was extracted
- what text was cleaned
- what chunk boundaries were chosen
- what prompt inputs were sent to the dossier pass
- what raw model output produced a parsed JSON
