# Orchestrator Dependencies

The ManuscriptPrep orchestrator and installer share the same dependency
contract.

## Supported host combinations

See [System Requirements](../getting-started/system-requirements.md) for the
minimum and recommended operating system and hardware combinations, plus the
inference backend/API matrix. In short:

- minimum local operation: macOS 13+, Ubuntu 22.04 LTS, or Windows 11 with
  WSL2 / Docker; 4 cores; 16 GB RAM; 30 GB SSD
- recommended local operation: macOS 14+, Ubuntu 24.04 LTS, or Windows 11 Pro
  with Docker / WSL2; 8 cores; 32 GB RAM; 100 GB SSD

## Checked items

- Python modules: `PyYAML`, `rich`
- System tools: `ollama`, `pdftotext`, `pdfinfo`, `ocrmypdf`, `tesseract`, `ghostscript`
- Ollama service availability
- Ollama models:
  - `qwen3:8b-q4_K_M`
  - `manuscriptprep-structure`
  - `manuscriptprep-dialogue`
  - `manuscriptprep-entities`
  - `manuscriptprep-dossiers`
  - `manuscriptprep-resolver`

## Installer behavior

The installer is intentionally best-effort and idempotent:

1. installs the Python requirements from `requirements.txt`
2. installs missing system tools using the host package manager when available
3. installs Ollama when it is missing
4. starts Ollama when the binary exists but the server is not running
5. pulls the base model
6. builds the ManuscriptPrep model tags from the Modelfiles

## Runtime behavior

The orchestrator shows a dependency preflight screen before starting a run. If
dependencies are missing, the user can launch the installer from that screen and
recheck the stack before continuing.
