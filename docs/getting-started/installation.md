# Installation

This page documents the supported installation path for the local ManuscriptPrep stack.

See also: [System Requirements](system-requirements.md).

## Prerequisites

You will need:

- macOS or Linux host for the local-LLM deployment path
- Python 3
- virtual environment support
- Git
- Ollama for local inference
- PDF extraction tools
- optionally OCR tooling

If you plan to use a cloud LLM instead of local inference, see
[System Requirements](system-requirements.md) for the opt-in cloud-assisted
profile and privacy implications.

## Manual setup outline

1. Clone the repository.
2. Run `install/bootstrap.sh` or `install/install.sh`.
3. The installer will:
   - install Python dependencies from `requirements.txt`
   - install system tools such as `pdftotext`, `pdfinfo`, `tesseract`, `ghostscript`, and `ocrmypdf`
   - install or verify Ollama
   - start Ollama if it is not already running
   - pull the base model used by the repo
   - build the ManuscriptPrep model tags from the Modelfiles
4. Copy `config/manuscriptprep.example.yaml` to a real config path.
5. Update paths and model names for the host if needed.
6. Run ingest, orchestration, merger, resolver, and reporting manually or through the gateway.

## Recommended deployment locations

- code: `/opt/manuscriptprep`
- config: `/etc/manuscriptprep/config.yaml`
- data: `/var/lib/manuscriptprep`
- logs: `/var/log/manuscriptprep`
