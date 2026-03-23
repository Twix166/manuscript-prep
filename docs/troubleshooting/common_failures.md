# Common Failures

## Idle timeout

Cause:
- model slow to emit visible output

Fix:
- smaller chunks
- adaptive idle-timeout backoff
- more retries

## Malformed JSON

Cause:
- extra trailing output
- visible reasoning before JSON
- partial corruption

Fix:
- retry logic
- inspect raw outputs
- tighten prompts

## Hanging pass

Cause:
- no visible output for too long
- model stalled or looping

Fix:
- idle timeout
- hard timeout
- retry with backoff
