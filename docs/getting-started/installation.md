# Installation

This page documents the manual installation path before the automated installer is introduced.

## Prerequisites

You will need:

- Linux host
- Python 3
- virtual environment support
- Git
- Ollama
- PDF extraction tools
- optionally OCR tooling

## Manual setup outline

1. Clone the repository.
2. Create a Python virtual environment.
3. Install Python dependencies.
4. Install system packages such as `pdftotext`.
5. Copy `config/manuscriptprep.example.yaml` to a real config path.
6. Update paths and model names for the host.
7. Build the Ollama stage models from the Modelfiles.
8. Run ingest, orchestration, merger, resolver, and reporting manually.

## Recommended deployment locations

- code: `/opt/manuscriptprep`
- config: `/etc/manuscriptprep/config.yaml`
- data: `/var/lib/manuscriptprep`
- logs: `/var/log/manuscriptprep`
