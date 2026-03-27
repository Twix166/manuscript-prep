# Quickstart

This is the shortest path from manuscript PDF to final report.

## 1. Prepare config

Copy the example config and adjust paths and model names.

## 2. Ingest the manuscript

Run ingest to extract text, clean it, and create chunk files.

## 3. Run the orchestrator

Point the orchestrator at the chunk directory and wait for per-chunk outputs.

## 4. Merge the outputs

Create the book-level merged files.

## 5. Resolve likely identity variants

Run the resolver against the merged book directory.

## 6. Build the PDF report

Generate the final human-readable PDF from the resolved directory.
