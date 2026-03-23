# Pipeline Overview

The full pipeline is:

PDF → raw text → cleaned text → chunks → multi-pass analysis → structured output

## Ingest stage

The ingest stage takes a source PDF and produces:

- raw extracted text
- cleaned text
- chunk files
- structure hints
- manifests

## Analysis stage

The orchestrator runs four passes over every chunk:

1. structure
2. dialogue
3. entities
4. dossiers

Each pass writes:

- raw model output
- parsed JSON output
- timing information through the orchestrator

## Why multi-pass

A single large prompt tends to mix together too many tasks:

- document structure
- POV and dialogue analysis
- literal entity extraction
- conservative character dossier generation

Splitting these into dedicated passes improves:

- determinism
- schema reliability
- debuggability
- prompt clarity
