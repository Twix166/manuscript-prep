# Prompts

Each pass uses a dedicated system prompt.

## Prompt goals

- JSON-first output
- conservative extraction
- no invented facts
- minimal visible reasoning
- strict schema adherence

## Practical reality

Even with strong prompts, some models may still emit visible `Thinking...` text before the final JSON. That is why the orchestrator:

- keeps raw outputs
- supports retries
- enforces timeouts
- records per-pass logs
