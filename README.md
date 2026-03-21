# ManuscriptPrep

A local, multi-pass manuscript analysis stack for fiction manuscripts using Ollama and custom Modelfiles.

This project is designed for **audiobook preparation** and **editorial review**. It processes long-form fiction conservatively and structurally, with a focus on:

- chapter and part extraction
- narrative and dialogue detection
- entity extraction
- character dossier generation

The stack is built to run **locally** on your own hardware, using **Ollama**, **Qwen**, custom **Modelfiles**, PDF-to-text preprocessing, chunking, and a Python orchestration pipeline.

---

## Overview

ManuscriptPrep turns a source manuscript PDF into structured JSON outputs through a staged pipeline:

1. **Extract text from PDF**
2. **Clean the raw text**
3. **Split the text into chunks**
4. **Run a multi-pass Ollama pipeline**
5. **Save per-chunk structured JSON outputs**

The key design decision is to **split the task into multiple smaller passes** instead of asking one model to do everything in one go. This improves:

- grounding
- consistency
- JSON reliability
- resistance to hallucination
- easier downstream merging

---

## Tech Stack

### Ollama
Ollama runs local language models and lets you create custom models with `Modelfile`.

In this project, Ollama is used to host several custom models:

- `manuscriptprep-structure`
- `manuscriptprep-dialogue`
- `manuscriptprep-entities`
- `manuscriptprep-dossiers`

These are all based on the same foundation model, but each has a different system prompt and task specialization.

---

### Base Model
The current recommended base model is:

- `qwen3:8b-q4_K_M`

Why this model?

- fast enough for local chunk-by-chunk processing
- strong instruction following
- good structured output behavior
- performs well on 12 GB class GPUs
- more stable than larger reasoning-heavy models for this workflow

---

### Modelfiles
A `Modelfile` in Ollama defines:

- the base model
- sampling parameters
- the `SYSTEM` prompt

In this project, each pass has its own Modelfile so that each model performs one narrow task only.

That is much more reliable than a single monolithic prompt.

---

### Open WebUI
Open WebUI is optional but useful for interactive experimentation.

It gives you:

- a browser UI for chatting with your local Ollama models
- easy testing of prompts and model behavior
- a way to compare model variants before automating them

Open WebUI is not required for the pipeline scripts, but it is very useful during development and debugging.

---

### PDF/Text Preprocessing
LLMs do not work well on raw PDF artifacts such as:

- page headers
- page footers
- repeated titles
- pagination markers
- OCR noise

So the manuscript is first transformed through these stages:

- `pdf2txt` extraction
- raw text inspection
- cleaning
- chunking

This preprocessing step is critical. A well-grounded model will refuse to invent missing content if fed poor text.

---

## Repository Layout

A typical repository structure might look like this:

```text
.
├── Modelfiles/
│   ├── structure.Modelfile
│   ├── dialogue.Modelfile
│   ├── entities.Modelfile
│   └── dossiers.Modelfile
├── scripts/
│   ├── pdf_to_text.py
│   ├── clean_text.py
│   ├── chunk_text.py
│   ├── manuscriptprep_orchestrator.py
│   └── manuscriptprep_orchestrator_tui.py
├── input/
│   ├── manuscript.pdf
│   ├── raw.txt
│   ├── clean.txt
│   └── chunks/
├── out/
└── README.md
```

## Installation

### 1. Install Ollama

Install Ollama on your system.

On Linux, follow the standard Ollama installation instructions. Once installed, verify:

```bash
ollama --version
```

### 2. Install Python

Python 3.10+ is recommended.

Check your version:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the Python dependencies:

```bash
pip install rich
```

Depending on which PDF preprocessing path you use, you may also want:

```bash
pip install pymupdf pdfplumber
```

If you use only shell tools like pdftotext, then rich may be the only required Python dependency for the orchestrator TUI.

---

### 4. Install PDF extraction tools

*Option A*: `pdftotext`

Recommended for text-based PDFs.

Fedora:

```bash
sudo dnf install poppler-utils
```

Ubuntu/Debian:

```bash
sudo apt install poppler-utils
```

Verify:

```bash
pdftotext -v
```

*OptionB: OCR Tools*
Only needed if the PDF is image-based or scanned.

Fedora:

```bash
sudo dnf install tesseract ocrmypdf
```

Ubuntu/Debian:

```bash
sudo apt install tesseract-ocr ocrmypdf
```

---

### 5.  Install Open WebUI (optional)

If you want an interactive browser UI for Ollama:

```bash
docker run -d \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

Then open:

```text
http://localhost:3000
```


If Open WebUI is running on a different machine from Ollama, point OLLAMA_BASE_URL to your Ollama host.

---

## Model Design
This project uses four separate models, each with a focused responsibility.

---

'manuscriptprep-structure'

Purpose:

- extract chapter titles
- extract part titles
- identify real scene breaks
- ignore page numbers and metadata

Expected output:

```json
{
  "chapters": [],
  "parts": [],
  "scene_breaks": [],
  "status": ""
}
```

---

'manuscriptprep-dialogue'

Purpose:

- determine POV
- determine whether dialogue is present
- determine whether internal thought is present
- extract explicitly attributed speakers
- identify whether unattributed dialogue exists

Expected output:

```json
{
  "pov": "",
  "dialogue": false,
  "internal_thought": false,
  "explicitly_attributed_speakers": [],
  "unattributed_dialogue_present": false
}
```