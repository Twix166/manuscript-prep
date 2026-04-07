# ManuscriptPrep

![Alt text](orchestrator_tui.png?raw=true "Orchestrator TUI Screenshot")

A local, multi-pass manuscript analysis stack for fiction manuscripts using Ollama and custom Modelfiles.

This project is designed for **audiobook preparation** and **editorial review**. It processes long-form fiction conservatively and structurally, with a focus on:

- chapter and part extraction
- narrative and dialogue detection
- entity extraction
- character dossier generation

The stack is built to run **locally** on your own hardware, using **Ollama**, **Qwen**, custom **Modelfiles**, PDF-to-text preprocessing, chunking, and a Python orchestration pipeline.

---

## Supported Entry Points

The currently supported pipeline entry points are:

- `python manuscriptprep_ingest.py`
- `python manuscriptprep_orchestrator_tui_refactored.py`
- `python manuscriptprep_merger.py`
- `python manuscriptprep_resolver.py`
- `python manuscriptprep_pdf_report.py`
- `python manuscriptprep_gateway_api.py`
- `python manuscriptprep_worker.py`

The canonical orchestrator is:

- `manuscriptprep_orchestrator_tui_refactored.py`

Notes:

- `manuscriptprep_orchestrator_tui.py` is a legacy orchestrator kept for reference and comparison.
- `scripts/manuscriptprep_orchestrator_tui_configured.py` is a config wiring scaffold, not the supported production runner.
- `manuscriptprep_gateway_api.py` is the API control plane. It creates jobs, requeues jobs, and exposes persisted job artifacts and status through either a file-backed store or PostgreSQL.
- `manuscriptprep_worker.py` is the execution worker. It claims queued jobs and runs them outside the gateway process.
- `manuscriptprep_orchestrator_tui_refactored.py` can now also run in gateway-client mode with `--gateway-url` while preserving the existing direct local orchestration mode.

Operational endpoints:

- `GET /health`
- `GET /ready`
- `GET /v1/system/status`

Authentication:

- `GET /health` and `GET /ready` stay unauthenticated
- `/v1/*` routes can require an API token with `Authorization: Bearer <token>` or `X-API-Token`
- the compose stack now boots a default admin token for development via `MANUSCRIPTPREP_BOOTSTRAP_ADMIN_TOKEN`

Managed records:

- `POST /v1/manuscripts` and `GET /v1/manuscripts`
- `POST /v1/config-profiles` and `GET /v1/config-profiles`
- jobs can now reference `manuscript_id` and `config_profile_id` instead of repeating source/config paths on every request

Artifact management:

- `GET /v1/jobs/{job_id}/artifacts` returns the persisted artifact index for a job
- artifacts produced by workers are now enriched with `sha256`, `bytes`, and `storage_backend` metadata

Web UI:

- `GET /ui` serves a lightweight operator dashboard from the gateway
- the dashboard now supports manuscript upload, managed manuscript registration, config-profile selection, stage-by-stage triggering, full-pipeline runs, and live job/artifact status
- stage cards show pipeline substeps and the configured model names where applicable
- the compose stack now mounts a shared runtime volume for uploaded manuscripts and pipeline scratch data so gateway and worker can both access user uploads

---

## Test Workflow

Before merging code changes, run the full test matrix:

```bash
bash scripts/run_test_matrix.sh
```

Test suites currently required for code changes:

- `unit`
- `regression`
- `smoke`
- `integration`

Additional testing guidance lives in [docs/development/testing.md](docs/development/testing.md).

Release/UAT guidance lives in [docs/development/uat_checklist.md](docs/development/uat_checklist.md).

Release notes for the current baseline live in [docs/releases/v1.0.0.md](docs/releases/v1.0.0.md).

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

Key paths in the current repository:

```text
.
├── manuscriptprep_ingest.py
├── manuscriptprep_orchestrator_tui_refactored.py
├── manuscriptprep_merger.py
├── manuscriptprep_resolver.py
├── manuscriptprep_pdf_report.py
├── manuscriptprep/
├── modelfiles/
├── config/
├── docs/
├── work/
├── out/
├── merged/
├── resolved/
└── reports/
```

Typical runtime flow:

```text
source PDF
  -> work/extracted/<book_slug>/
  -> work/cleaned/<book_slug>/
  -> work/chunks/<book_slug>/
  -> out/<book_slug>/<chunk_id>/
  -> merged/<book_slug>/
  -> resolved/<book_slug>/
  -> reports/<book_slug>_report.pdf
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

### 4. Optional container stack

The repository now includes a root [compose.yaml](/home/rbalm/Manuscript_Prep_Modelfile/compose.yaml) that starts:

- `postgres`
- `gateway`
- `worker`

The compose stack configures the gateway and worker to use PostgreSQL by default:

```bash
docker compose up --build
```

The gateway will be available on `http://127.0.0.1:8765` and PostgreSQL will be published on host port `5433` by default. The container-to-container database port remains `5432`.

For the user-facing flow:

1. Open `http://127.0.0.1:8765/ui`
2. Enter the admin or user API token
3. Upload a manuscript PDF
4. Choose a config profile
5. Trigger the full pipeline or individual stages and watch live status updates

If those host ports conflict with your machine, override them when starting the stack:

```bash
MANUSCRIPTPREP_POSTGRES_PORT=55432 MANUSCRIPTPREP_GATEWAY_PORT=18765 docker compose up --build
```

The stack will use:

- PostgreSQL database: `manuscriptprep`
- PostgreSQL schema: `gateway`
- API auth: enabled for `/v1/*`
- Default development admin token: `dev-admin-token` unless `MANUSCRIPTPREP_BOOTSTRAP_ADMIN_TOKEN` is overridden
- environment-driven database credentials and admin token, with examples in `.env.example`
- non-root `manuscriptprep` user inside the gateway and worker containers

For local non-container development, the gateway can still run with the file-backed store by default.

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

## Canonical Pipeline Commands

Example end-to-end run:

```bash
python manuscriptprep_ingest.py \
  --input source/TREASURE-ISLAND-by-Robert-Louis-Stevenson.pdf \
  --workdir work \
  --title "Treasure Island"
```

Or, with shared defaults from config:

```bash
python manuscriptprep_ingest.py \
  --config config/manuscriptprep.example.yaml \
  --input source/TREASURE-ISLAND-by-Robert-Louis-Stevenson.pdf \
  --title "Treasure Island"
```

```bash
python manuscriptprep_orchestrator_tui_refactored.py \
  --input-dir work/chunks/treasure_island \
  --output-dir out/treasure_island
```

```bash
python manuscriptprep_merger.py \
  --input-dir out/treasure_island \
  --output-dir merged/treasure_island \
  --chunk-manifest work/manifests/treasure_island/chunk_manifest.json
```

Or, with shared defaults from config:

```bash
python manuscriptprep_merger.py \
  --config config/manuscriptprep.example.yaml \
  --book-slug treasure_island
```

```bash
python manuscriptprep_resolver.py \
  --input-dir merged/treasure_island \
  --output-dir resolved/treasure_island \
  --model manuscriptprep-resolver
```

Or, with shared defaults from config:

```bash
python manuscriptprep_resolver.py \
  --config config/manuscriptprep.example.yaml \
  --book-slug treasure_island
```

```bash
python manuscriptprep_pdf_report.py \
  --input-dir merged/treasure_island \
  --output reports/treasure_island_report.pdf \
  --title "Treasure Island"
```

Or, with shared defaults from config:

```bash
python manuscriptprep_pdf_report.py \
  --config config/manuscriptprep.example.yaml \
  --book-slug treasure_island
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

## TUI Orchestrator Features

The latest version of the ManuscriptPrep TUI orchestrator adds several operational and observability features that make long manuscript runs much easier to monitor and troubleshoot.

### Live TUI
The orchestrator includes a live terminal UI that shows the current state of the pipeline while it runs.

It displays:

- current chunk
- current pass
- current status
- current step
- elapsed time
- progress across all chunks

This gives you a live view of what the pipeline is doing without needing to inspect the output directory constantly.

---

### Per-Pass Status Updates During Processing
The TUI updates not only between chunks, but also during active pass execution.

Typical live states include:

- starting structure
- streaming model stdout
- waiting for model output
- writing raw output
- parsing JSON
- writing parsed JSON
- completed pass

This makes it much easier to understand whether the system is actively generating output, waiting on Ollama, parsing JSON, or writing files.

---

### Global Structured Log File
The orchestrator writes a global structured log in **JSON Lines** format.

Default location:

```text
out/orchestrator.log.jsonl
```

Each log line is a valid JSON object, which makes it suitable for ingestion into observability and log analysis tools such as:

- Loki
- Elasticsearch
- Splunk
- Datadog
- Vector
- Fluent Bit

Typical events include:

- run start
- chunk start
- pass start
- raw output written
- parsed JSON written
- pass success
- pass retry
- pass failure
- chunk failure
- run complete

Example log line:

```json
{
  "timestamp": "2026-03-21T12:34:56.789012+00:00",
  "level": "INFO",
  "event_type": "pass_start",
  "message": "Starting pass",
  "run_id": "uuid-here",
  "chunk": "chunk_0",
  "pass": "dialogue",
  "step": "starting dialogue",
  "model": "manuscriptprep-dialogue",
  "attempt": 1,
  "pid": 12345
}
```

---

### Per-Chunk `error.txt`

If a chunk fails, the orchestrator writes a plain-text error file inside that chunk’s output directory.

Example:

```text
out/chunk_7/error.txt
```

This gives you a simple human-readable record of what failed without needing to inspect the global log.

---

### Retry Support

The orchestrator supports automatic retries for failed passes.

For example, if the dialogue pass returns invalid JSON or Ollama exits with an error, the orchestrator can retry the pass before declaring the chunk failed.

This is useful for transient problems such as:

- malformed model output
- temporary Ollama failures
- empty stdout
- JSON extraction problems

Recommended usage:

```bash
python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --retries 1
```

---

### Skip-or-Stop Failure Behavior

When a chunk fails after retries, the orchestrator can be configured to either:

- skip the failed chunk and continue with the rest of the manuscript
s- top the entire run immediately

Default behavior is usually best set to skip, which is more practical for long manuscripts.

Examples:

Skip failed chunks:

```bash
python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --on-failure skip
```

Stop on first failed chunk:

```bash
python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --on-failure stop
```

---

Failure Summary

At the end of the run, the orchestrator produces a summary of failures.

This includes:

- number of chunks completed
- number of chunks failed
- list of failed chunks
- error messages for each failed chunk

This makes it easier to see whether the run was mostly successful or whether specific chunks need to be rerun.

---

### Approximate Token Speed in the TUI

The TUI Pipeline Status window includes a token speed field.

This is useful for getting a rough sense of model throughput during processing.

The orchestrator can show:

- reported token speed, if Ollama or the model emits a real token/sec value
- estimated token speed, based on visible streamed stdout

The token speed display helps distinguish between:

- a model that is actively producing output
- a model that is generating slowly
- a pass that may be stalled or looping

---

#### Notes on Token Speed

Ollama does not reliably expose the true backend evaluation tokens/sec through normal streamed stdout.

Because of that, the orchestrator uses the following logic:

- if a real token/sec value appears in model stdout or stderr, the TUI will display that
- otherwise, it shows a live estimated output token speed based on visible streamed stdout

This means the displayed value is operationally useful, but it may not exactly match the model’s true backend eval rate.

So the token speed shown in the TUI should be treated as:

- good for monitoring
- good for spotting stalls or regressions
- not guaranteed to be a precise benchmark

---

### Live TUI Monitoring

The TUI orchestrator provides a live terminal dashboard while the pipeline is running.

The **Pipeline Status** panel shows:

- current chunk
- current pass
- current status
- current step
- elapsed time
- overall progress
- retry count
- token speed
- age of last stdout line
- age of last stderr line

This makes it much easier to tell whether the system is:

- actively generating output
- waiting for model output
- parsing JSON
- writing files
- retrying after failure
- stalled long enough to trigger a timeout

---

### Real-Time Per-Pass Status Updates

The orchestrator updates the TUI during active processing, not just between chunks.

Typical steps shown in the UI include:

- loading excerpt
- launching model
- sending prompt to model
- streaming model stdout
- streaming model stderr
- waiting for model output
- writing raw output
- parsing JSON
- writing parsed JSON
- building dossier input
- completed pass

This gives a live view of what both the orchestrator and the model are doing.

---

### Failure Summary

At the end of a run, the orchestrator records a failure summary.

This includes:

- total chunks discovered
- chunks completed
- chunks failed
- failed chunk names
- failure messages

This makes it easier to assess the overall health of the run and identify which chunks need to be rerun or inspected.

---

### Idle Timeout Detection

One common problem with local model pipelines is that a subprocess can appear to hang indefinitely without actually exiting.

The updated orchestrator detects this condition using an idle timeout.

If a pass produces no stdout or stderr for a configurable number of seconds, the orchestrator treats the pass as stalled:

- the Ollama subprocess is terminated
- the event is logged
- the pass may be retried
- if retries are exhausted, the chunk is marked failed

Example:

```bash
python manuscriptprep_orchestrator_tui.py \
  --input-dir chunks \
  --output-dir out \
  --idle-timeout 90
```

This tells the orchestrator to treat 90 seconds of silence as a stall.

---

### Hard Timeout Detection

In addition to idle timeout detection, the orchestrator also supports a hard timeout for each pass.

If a pass runs longer than the configured maximum wall-clock time, the orchestrator will:

- terminate the subprocess
- log the timeout
- retry if configured
- fail the chunk if retries are exhausted

Example:

```bash
python manuscriptprep_orchestrator_tui.py \
  --input-dir chunks \
  --output-dir out \
  --hard-timeout 600
```

This caps any single pass at 10 minutes.

---

### Kill-and-Retry Behavior

When either an idle timeout or hard timeout occurs, the orchestrator does not simply wait forever.

Instead it:

- detects the timeout
- kills the running Ollama subprocess
- logs the timeout event
- retries the pass if retries remain
- otherwise fails or skips the chunk according to policy

This is a major improvement over earlier versions that could appear to hang indefinitely.

---

### Last Stdout / Stderr Age

The TUI also displays:

- age of `last stdout` output
- age of `last stderr` output

These fields are especially useful when diagnosing stalls.

For example:

- a growing `Last stdout` age usually means the model has gone silent
- a very old `Last stderr` age with no progress may indicate a silent hang
- a constantly resetting `Last stdout` age suggests active streaming

This makes it easier to distinguish between:

- a slow pass
- a quiet pass
- a stalled pass

---

### Natural Chunk Sorting

The orchestrator now sorts chunk files in natural numeric order.

That means:

```text
chunk_1.txt
chunk_2.txt
chunk_3.txt
...
chunk_10.txt
```

instead of lexicographic ordering like:

```text
chunk_1.txt
chunk_10.txt
chunk_11.txt
chunk_2.txt
```

This makes progress reporting easier to understand and keeps the run aligned with the manuscript’s actual order.

---

## Adaptive Idle Timeout Backoff

The orchestrator now supports **adaptive idle-timeout backoff** for retries.

This feature is designed to reduce failures on chunks or passes that are slow to begin emitting visible output but are not truly broken.

### Why this is needed

Some local model passes can be slow to produce their first visible stdout, especially when:

- the chunk is large or noisy
- the dossier pass is especially heavy
- the model spends time in visible reasoning before returning JSON
- system load varies between chunks

A fixed idle timeout can therefore be too strict.  
If the timeout is too low, the orchestrator may kill a pass that would have succeeded if given a little more time.

---

### How adaptive idle-timeout backoff works

The orchestrator starts each pass with a base idle timeout.

If a pass fails specifically because of an **idle timeout**, the next retry increases the idle timeout by a configurable multiplier.

For example, with:

- base idle timeout = `180`
- backoff multiplier = `1.5`
- retries = `2`

the retry sequence becomes:

- attempt 1 → `180s`
- attempt 2 → `270s`
- attempt 3 → `405s`

This gives slow-starting passes a better chance of succeeding without forcing every pass to use an excessively large timeout from the beginning.

---

### Important behavior

Idle-timeout backoff is applied **only** when the previous failure was caused by an **idle timeout**.

It is **not** applied for other failure types such as:

- invalid JSON
- empty model output
- non-zero Ollama exit
- hard timeout
- parsing failure

This keeps retries targeted and avoids unnecessarily extending timeouts for unrelated problems.

---

### Maximum idle-timeout cap

To prevent the idle timeout from growing without bound, the orchestrator also supports a maximum cap.

For example:

- base idle timeout = `180`
- backoff multiplier = `1.5`
- max idle timeout = `600`

This ensures that retries remain reasonable even if a pass stalls multiple times.

---

### TUI support

The TUI now shows the current idle-timeout state for the active pass.

The **Pipeline Status** panel includes:

- current effective idle timeout
- number of idle-timeout backoffs applied for the current pass

This makes it easier to see whether a retry is simply being rerun with the same configuration or whether the timeout has been expanded because of a previous idle-timeout failure.

---

### Structured logging support

The structured JSONL log also records the effective idle timeout used for each attempt.

This makes it possible to trace:

- which retry used which timeout
- whether a retry was triggered by an idle-timeout failure
- whether the timeout increased between attempts

Example fields written into the log include:

- `idle_timeout_s`
- `idle_timeout_failures_for_pass`
- `previous_idle_timeout_s`
- `next_idle_timeout_s`

This is useful for observability and later tuning.

---

### Recommended invocation

A good default configuration for long manuscript runs is:

```bash
python manuscriptprep_orchestrator_tui.py \
  --input-dir chunks/treasure_island \
  --output-dir out/treasure_island \
  --retries 2 \
  --on-failure skip \
  --idle-timeout 180 \
  --idle-timeout-backoff 1.5 \
  --max-idle-timeout 600 \
  --hard-timeout 900
```


This gives you:

- live TUI monitoring
- structured JSONL logs
- retry protection
- per-chunk error files
- idle stall detection
- hard timeout protection
- resilient long-run behavior
- idle-timeout-backoff

---

### Why These Features Matter

Local LLM pipelines often fail in subtle ways:

- visible reasoning loops
- partial JSON output
- long silent stalls
- no clear indication of whether the model is still active
- awkward recovery when one chunk fails partway through a book

The updated orchestrator addresses these practical runtime problems directly.

It turns the pipeline from a basic automation script into something much closer to a production processing tool.

---

## Recommended Next Steps

Once per-chunk outputs are stable, the next major improvement is a book-level merger that can:

- combine structure across chunks
- merge entity references conservatively
- aggregate dossier facts
- track recurring characters across excerpts
