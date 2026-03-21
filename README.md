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