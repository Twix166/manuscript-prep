# Modelfiles

Each Ollama model is defined by a Modelfile.

## Typical components

- base model
- parameter settings
- system prompt

## Example

```text
FROM qwen3:8b-q4_K_M

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 16384

SYSTEM """
You are a strict extraction engine.
Output ONLY valid JSON.
"""
```

## Why Modelfiles matter

They provide reproducibility and make it possible to specialize behavior per pass.
