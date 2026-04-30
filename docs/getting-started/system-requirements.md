# System Requirements

This project is designed to run locally, in Docker, or on a VM. The tables
below describe practical minimum and recommended host combinations for the
combined ManuscriptPrep and Narrator's Toolkit stack.

## Minimum supported local setup

Use this if you want the stack to run on a single machine and you are willing to
accept slower model execution on larger books.

| Component | Minimum |
| --- | --- |
| Operating system | macOS 13+, Ubuntu 22.04 LTS, or Windows 11 with WSL2 / Docker |
| CPU | 4 physical cores |
| Memory | 16 GB RAM |
| Storage | 30 GB free SSD space |
| Browser | Current Chromium, Firefox, or Safari |
| GPU | Not required |

This minimum profile is suitable for:

- the web UI
- manuscript ingest and cleaning
- narrator viewing
- smaller or text-based PDFs

Expect OCR, large books, and local Ollama models to run slowly on this profile.

## Recommended local setup

Use this for day-to-day authoring, narration prep, and model-heavy workflows.

| Component | Recommended |
| --- | --- |
| Operating system | macOS 14+, Ubuntu 24.04 LTS, or Windows 11 Pro with Docker / WSL2 |
| CPU | 8 physical cores or better |
| Memory | 32 GB RAM |
| Storage | 100 GB free SSD space |
| Browser | Current Chromium, Firefox, or Safari |
| GPU | Optional, but useful if you later add local acceleration |

This recommended profile is suitable for:

- the full ManuscriptPrep pipeline
- Ollama model execution on the same machine
- OCR-heavy PDFs
- multiple books or long manuscripts
- the Narrator's Toolkit queue and reader experience

## Docker and VM guidance

- For a Docker host, use the recommended profile if Ollama and the gateway run on
  the same machine.
- For a VM, allocate the same CPU and memory as the recommended local setup if
  the VM is responsible for ingest, orchestration, and model execution.
- If Ollama runs on a different host, the local machine can be smaller, but the
  remote Ollama host still needs the recommended resources.

## Practical notes

- SSD storage matters more than raw CPU once the pipeline starts writing chunks,
  manifests, reports, and Ollama model layers.
- The Narrator's Toolkit viewer itself is light; the heavy requirements come from
  PDF extraction, OCR, and local model execution.
- If you only use the web UI against a remote gateway, the browser machine can be
  much smaller than the processing host.
