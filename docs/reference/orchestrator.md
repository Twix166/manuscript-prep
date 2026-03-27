# Orchestrator Reference

## Purpose

The orchestrator runs the model passes over each chunk.

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
