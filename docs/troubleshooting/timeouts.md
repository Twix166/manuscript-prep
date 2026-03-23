# Timeouts

## Idle timeout

Triggered when a pass produces no stdout or stderr for too long.

## Hard timeout

Triggered when a pass exceeds maximum total runtime.

## What to tune first

1. reduce chunk size
2. increase retries
3. enable idle-timeout backoff
4. only then increase default timeouts further
