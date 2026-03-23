# Performance

## Main performance levers

- chunk size
- model size
- timeout settings
- retries
- adaptive idle-timeout backoff

## Practical advice

If the orchestrator is timing out too often:

- reduce chunk size first
- then enable or tune idle-timeout backoff

## Use timing data

Use `timing.json` and JSONL logs to determine:

- slowest pass
- average chunk duration
- whether retries are being rescued by backoff
