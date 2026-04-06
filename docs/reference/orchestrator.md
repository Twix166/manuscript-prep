# Orchestrator Reference

## Purpose

The orchestrator runs the model passes over each chunk.

## Supported Runner

The canonical supported orchestrator entry point is:

```bash
python manuscriptprep_orchestrator_tui_refactored.py
```

Status notes:

- `manuscriptprep_orchestrator_tui_refactored.py` is the supported runner.
- `manuscriptprep_orchestrator_tui.py` is a legacy implementation kept for reference.
- `scripts/manuscriptprep_orchestrator_tui_configured.py` is a scaffold for config refactoring, not the production runner.

## Responsibilities

- run structure, dialogue, entities, and dossiers
- manage retries
- enforce idle and hard timeouts
- apply idle-timeout backoff
- write raw and parsed outputs
- record timing
- update the TUI
- write structured logs

## Inputs

- chunk directory
- config file
- available Ollama models

## Outputs

Typical outputs:

```text
out/<book_slug>/<chunk_id>/
  structure.json
  dialogue.json
  entities.json
  dossiers.json
  timing.json
  error.txt
```

And global logging:

```text
out/orchestrator.log.jsonl
```

## Key config sections

- `paths`
- `models`
- `timeouts`
- `logging`

## Notes

The orchestrator should be the only stage responsible for pass-level runtime policy.
Use the refactored orchestrator when following the documented pipeline flow.
