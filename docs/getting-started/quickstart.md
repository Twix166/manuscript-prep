# Quickstart

This is the shortest path from manuscript PDF to final report.

## 1. Prepare config

Copy the example config and adjust paths and model names.

## 2. Ingest the manuscript

Run ingest to extract text, clean it, and create chunk files.

```bash
python manuscriptprep_ingest.py \
  --input source/TREASURE-ISLAND-by-Robert-Louis-Stevenson.pdf \
  --workdir work \
  --title "Treasure Island"
```

You can also provide shared defaults from config:

```bash
python manuscriptprep_ingest.py \
  --config config/manuscriptprep.example.yaml \
  --input source/TREASURE-ISLAND-by-Robert-Louis-Stevenson.pdf \
  --title "Treasure Island"
```

## 3. Run the orchestrator

Use the supported orchestrator entry point and point it at the chunk directory.

Supported runner:

- `python manuscriptprep_orchestrator_tui_refactored.py`

```bash
python manuscriptprep_orchestrator_tui_refactored.py \
  --input-dir work/chunks/treasure_island \
  --output-dir out/treasure_island
```

Or, to run orchestration through the gateway API:

```bash
python manuscriptprep_orchestrator_tui_refactored.py \
  --gateway-url http://127.0.0.1:8765 \
  --input-dir work/chunks/treasure_island \
  --output-dir out/treasure_island \
  --book-slug treasure_island
```

## 4. Merge the outputs

Create the book-level merged files.

```bash
python manuscriptprep_merger.py \
  --input-dir out/treasure_island \
  --output-dir merged/treasure_island \
  --chunk-manifest work/manifests/treasure_island/chunk_manifest.json
```

## 5. Resolve likely identity variants

Run the resolver against the merged book directory.

```bash
python manuscriptprep_resolver.py \
  --input-dir merged/treasure_island \
  --output-dir resolved/treasure_island \
  --model manuscriptprep-resolver
```

## 6. Build the PDF report

Generate the final human-readable PDF from the merged directory.

```bash
python manuscriptprep_pdf_report.py \
  --input-dir merged/treasure_island \
  --output reports/treasure_island_report.pdf \
  --title "Treasure Island"
```

Or, with shared defaults from config:

```bash
python manuscriptprep_pdf_report.py \
  --config config/manuscriptprep.example.yaml \
  --book-slug treasure_island
```
