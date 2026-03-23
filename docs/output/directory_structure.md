# Output Directory Structure

## Orchestrator output layout

```text
out/<book_slug>/<chunk_id>/
├── structure.json
├── structure_raw.txt
├── dialogue.json
├── dialogue_raw.txt
├── entities.json
├── entities_raw.txt
├── dossiers.json
├── dossiers_raw.txt
├── dossier_input.txt
├── timing.json
└── error.txt
```

## Meaning

- `*_raw.txt` → raw model output
- `*.json` → parsed structured output
- `dossier_input.txt` → exact dossier payload
- `timing.json` → timing metrics
- `error.txt` → per-chunk failure record
