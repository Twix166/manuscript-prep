# Logging

The orchestrator writes structured logs in JSON Lines format.

## Default location

```text
out/orchestrator.log.jsonl
```

## Why JSONL

Each line is valid JSON, which makes it easy to ingest into observability tooling such as:

- Loki
- Elasticsearch
- Splunk
- Datadog
- Vector
- Fluent Bit

## Typical event types

- `run_start`
- `chunk_start`
- `pass_start`
- `raw_written`
- `json_written`
- `pass_success`
- `pass_retry`
- `pass_idle_timeout`
- `chunk_failure`
- `run_complete`

## Per-chunk error files

A human-readable `error.txt` is also written inside failed chunk directories.
