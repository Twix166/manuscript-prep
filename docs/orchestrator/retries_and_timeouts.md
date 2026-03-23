# Retries and Timeouts

The orchestrator supports retries and multiple timeout controls.

## Retry logic

Each pass can retry after failures such as:

- malformed JSON
- empty output
- non-zero model exit
- idle timeout
- hard timeout

## Idle timeout

A pass is considered stalled if no stdout or stderr appears for the configured window.

Example base value:

```text
180 seconds
```

## Hard timeout

A pass also has a maximum total runtime.

Example:

```text
900 seconds
```

## Adaptive idle-timeout backoff

If a pass fails because of an idle timeout, the next retry increases the idle timeout.

Example with:

- base idle timeout = 180
- backoff multiplier = 1.5
- retries = 2

Results:

- attempt 1 → 180s
- attempt 2 → 270s
- attempt 3 → 405s

## Important behavior

Backoff is applied only after idle-timeout failures.
It is not applied for:

- invalid JSON
- empty stdout
- parse failures
- hard timeouts

## Recommended invocation

```bash
python manuscriptprep_orchestrator_tui.py \
  --input-dir work/chunks/treasure_island \
  --output-dir out/treasure_island \
  --retries 2 \
  --on-failure skip \
  --idle-timeout 180 \
  --idle-timeout-backoff 1.5 \
  --max-idle-timeout 600 \
  --hard-timeout 900
```
