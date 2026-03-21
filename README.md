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
python --version
```

---

### 3. Install Python dependencies

Create a virtual environment:

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

`manuscriptprep-structure`

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

`manuscriptprep-dialogue`

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

---

`manuscriptprep-entities`

Purpose:

- extract literal characters
- extract literal places
- extract literal objects
- capture identity uncertainty notes

Expected output:

{
  "characters": [],
  "places": [],
  "objects": [],
  "identity_notes": []
}

---

`manuscriptprep-dossiers`

Purpose:

- build conservative character dossiers
- use only the excerpt plus prior extraction data
- avoid broad story knowledge
- avoid future plot references

Expected output:

```json
{
  "character_dossiers": [
    {
      "name": "",
      "aliases": [],
      "role": "unknown",
      "biography": "",
      "personality_traits": [],
      "vocal_notes": "unknown",
      "accent": "not specified in excerpt",
      "spoken_dialogue": false,
      "identity_status": "confirmed"
    }
  ]
}
```

---

## Why Multi-Pass is Better Than One-Pass

A single-pass prompt tends to mix together:

- structure parsing
- speaker attribution
- entity extraction
- role inference
- biography writing

That causes:

- identity drift
- schema inconsistency
- role hallucination
- poor grounding
- worse JSON reliability

By splitting the work into four narrow passes, each model has a smaller and clearer job.

This gives much more stable results.

---

## Recommended Model Parameters

All four custom models currently use:

```text
FROM qwen3:8b-q4_K_M

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 16384
```

These settings bias the model toward:

- deterministic behavior
- conservative extraction
- lower hallucination risk
- stable JSON formatting

---

## Creating the Ollama Models

Create one Modelfile per pass.

Example structure model creation:

```bash
ollama create manuscriptprep-structure -f structure.Modelfile
```

Dialogue:

```bash
ollama create manuscriptprep-dialogue -f dialogue.Modelfile
```

Entities:

```bash
ollama create manuscriptprep-entities -f entities.Modelfile
```

Dossiers:

```bash
ollama create manuscriptprep-dossiers -f dossiers.Modelfile
```

List installed models:

```bash
ollama list
```

---

## PDF to Text Workflow

### Step 1: Convert PDF to raw text

Using `pdftotext`:

```bash
pdftotext -layout input/manuscript.pdf input/raw.txt
```

If the PDF is scanned, run OCR first:

```bash
ocrmypdf input/manuscript.pdf input/manuscript_ocr.pdf
pdftotext -layout input/manuscript_ocr.pdf input/raw.txt
```

---

### Step 2: Inspect the raw text

Check the first few lines:

```bash
head -n 50 input/raw.txt
```

Look for problems such as:

- repeated book title on every page
- page numbers as standalone lines
- missing paragraphs
- broken OCR
- chapter headings not preserved

---

### Step 3: Clean the raw text

A cleaning script should remove:

- blank page markers
- repeated titles
- isolated page numbers
- obvious header/footer noise

Example goals of the cleaner:

- preserve real prose
- preserve chapter titles
- preserve dialogue punctuation
- preserve paragraph breaks where possible

``bash
python ManuscriptTXTCleaner.py input/raw.txt input/clean.txt
```

Typical output:

```text
input/raw.txt   -> input/clean.txt
```

---

### Step 4: Chunk the clean text

The chunker should split the manuscript into manageable excerpt files.

Recommended chunk size:

- around 1500–3000 words
- or based on paragraph boundaries
- ideally not splitting in the middle of a scene if avoidable

Typical output directory:

```text
input/chunks/
  chunk_0.txt
  chunk_1.txt
  chunk_2.txt
  ...
```

---

## Orchestration

The orchestrator is the script that runs all four passes over each chunk.

It performs this sequence:

1 structure pass
1 dialogue pass
1 entities pass
1 dossier pass

The dossier pass consumes:

- the original excerpt
- character list from entities pass
- dialogue output from dialogue pass

### Standard orchestrator

```bash
python manuscriptprep_orchestrator.py --input-dir input/chunks --output-dir out
```

### TUI orchestrator

```bash
python manuscriptprep_orchestrator_tui.py --input-dir input/chunks --output-dir out
```

The TUI version is useful because it can show:

- current chunk
- current pass
- orchestrator actions
- visible model stdout
- visible model stderr

---

## Output Layout

A typical output directory for one chunk looks like:

```text
out/chunk_0/
  structure_raw.txt
  structure.json
  dialogue_raw.txt
  dialogue.json
  entities_raw.txt
  entities.json
  dossier_input.txt
  dossiers_raw.txt
  dossiers.json
```

### Raw files

These contain the model’s original stdout and are useful for debugging malformed JSON or prompt drift.

### JSON files

These are the parsed outputs suitable for downstream merging and analysis.

`dossier_input.txt`

This shows exactly what was passed into the dossier model.

---

## Python Dependencies

Current core dependencies:

```text
rich
```

Optional preprocessing dependencies:

```text
pymupdf
pdfplumber
```

Optional OCR/system tooling:

- pdftotext
- ocrmypdf
- tesseract

---

## Example End-to-End Workflow

### 1. Extract text

```bash
pdftotext -layout input/manuscript.pdf input/raw.txt
```

### 2. Clean text

```bash
python scripts/clean_text.py input/raw.txt input/clean.txt
```

### 3. Chunk text

```bash
python scripts/chunk_text.py input/clean.txt input/chunks
```

### 4. Create Ollama models

```bash
ollama create manuscriptprep-structure -f Modelfiles/structure.Modelfile
ollama create manuscriptprep-dialogue -f Modelfiles/dialogue.Modelfile
ollama create manuscriptprep-entities -f Modelfiles/entities.Modelfile
ollama create manuscriptprep-dossiers -f Modelfiles/dossiers.Modelfile
```

### 5. Run orchestrator

```bash
python scripts/manuscriptprep_orchestrator_tui.py --input-dir input/chunks --output-dir out
```

---

## Design Principles

ManuscriptPrep is built around a few strict principles.

### Conservative grounding

The models should use only the excerpt they are given.

### No prior-knowledge dependency

The system should not rely on the model already knowing the novel.

### JSON-first outputs

Each pass should emit machine-usable structured data.

### Narrow prompts

Each pass should do one thing well rather than many things badly.

### Human-auditable outputs

All intermediate results should be inspectable.

---

## Known Limitations

### Visible reasoning text

Some local models may still emit visible Thinking... text before the JSON.
The orchestrator can often recover by extracting the JSON object, but this is still undesirable.

### Role inference drift

Even with strict prompts, some models may still over-infer roles such as:

- pirate
- magistrate
- innkeeper
- narrator

### TOC contamination

If chunks contain table-of-contents material, the structure model may extract chapter lists that are not local to the narrative body.

### OCR noise

Poor OCR can still degrade the downstream quality of extraction.

--- 

## Troubleshooting

### The model prints `Thinking...`

This means the model is emitting visible reasoning text.
The orchestrator may still succeed if the JSON can be extracted from the raw output.

Check:

- *_raw.txt
- error.txt if present

### The orchestrator stops after one pass

Usually this means one pass emitted invalid JSON or Ollama returned an error.

Check:

- structure_raw.txt
- dialogue_raw.txt
- entities_raw.txt
- dossiers_raw.txt
- error.txt

### The TUI shows nothing

This usually means the UI is not refreshing often enough, not that the pipeline has stopped.
Check whether files are appearing in out/.

### The model hallucinates broad story details

This usually means:

- the prompt is too permissive
- the chunk contains too much metadata
- the text cleaner has not removed enough noise
- the task is too broad for a single pass

---

## Example Goals for This Stack

This stack is well suited to:

- audiobook prep
- editorial review
- dialogue extraction
- character dossier preparation
- narrative structure analysis
- book-to-JSON pipelines

It is not intended as a creative writing assistant. It is intended as a forensic manuscript analysis tool.

---

## Recommended Next Steps

Once per-chunk outputs are stable, the next major improvement is a book-level merger that can:

- combine structure across chunks
- merge entity references conservatively
- aggregate dossier facts
- track recurring characters across excerpts