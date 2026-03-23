# Architecture Overview

ManuscriptPrep is split into three major layers.

## 1. Ingest layer

The ingest layer is deterministic preprocessing. It is responsible for:

- classifying PDFs
- extracting raw text
- cleaning text
- detecting structural hints
- chunking the manuscript
- writing manifests and ingest logs

This layer should not call LLMs.

## 2. Orchestrator layer

The orchestrator is responsible for:

- running all model passes
- retries
- timeout handling
- adaptive idle-timeout backoff
- logging
- live TUI monitoring
- per-chunk timing

This is runtime control, not document preprocessing.

## 3. Model layer

The model layer consists of multiple specialized Ollama models, each with its own Modelfile and system prompt.

Current pass models:

- manuscriptprep-structure
- manuscriptprep-dialogue
- manuscriptprep-entities
- manuscriptprep-dossiers

## Why this architecture

This split makes it easier to:

- rerun chunking without rerunning models
- compare chunking strategies
- debug extraction issues separately from model issues
- keep runtime behavior observable and recoverable
