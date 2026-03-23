# Entities Model

The entities model extracts literal entities from the excerpt.

## Responsibilities

- characters
- places
- objects
- identity notes where needed

## Known operational issue

This pass can occasionally emit malformed JSON or valid JSON followed by trailing output. Retries often recover these failures.
