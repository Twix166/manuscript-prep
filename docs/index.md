# ManuscriptPrep Documentation

Welcome to the ManuscriptPrep documentation.

This project is a local-first LLM pipeline for converting manuscript PDFs into structured, machine-readable outputs suitable for editorial review, narration preparation, and downstream tooling.

## Documentation map

- [Architecture](architecture/overview.md)
- [Ingest Pipeline](ingest/ingest_script.md)
- [Orchestrator](orchestrator/overview.md)
- [Models and Prompts](models/overview.md)
- [Output Reference](output/directory_structure.md)
- [Troubleshooting](troubleshooting/common_failures.md)
- [Development](development/contributing.md)

## Core ideas

ManuscriptPrep is built around a few key principles:

- deterministic preprocessing
- conservative extraction
- inspectable intermediate artifacts
- local execution with Ollama
- fault-tolerant orchestration
