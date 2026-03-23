# Orchestrator Overview

The orchestrator runs the multi-pass analysis pipeline over chunk files.

## Responsibilities

- run all passes in sequence
- write raw and parsed outputs
- retry failures
- handle idle and hard timeouts
- apply adaptive idle-timeout backoff
- maintain structured logs
- display live runtime state in a TUI
- record per-pass and per-chunk timing

## Pass order

1. structure
2. dialogue
3. entities
4. dossiers

## Key runtime principles

- never hang forever
- write observable artifacts
- retry intelligently
- preserve per-chunk traceability
