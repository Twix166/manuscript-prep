# Timing Metrics

The orchestrator records both per-pass and per-chunk timing.

## TUI timing

The TUI shows:

- pass elapsed
- chunk elapsed

## timing.json

Each successful chunk writes:

```text
out/<book_slug>/<chunk_id>/timing.json
```

## Example

```json
{
  "chunk": "chunk_001",
  "total_duration_seconds": 109.4,
  "passes": {
    "structure": 12.2,
    "dialogue": 14.7,
    "entities": 33.4,
    "dossiers": 49.1
  }
}
```

## Why this matters

Timing data helps you identify:

- slowest pass
- heavy chunks
- effects of chunk-size changes
- whether retries are being rescued by backoff
