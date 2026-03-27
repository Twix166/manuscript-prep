# Resolver Reference

## Purpose

The resolver performs book-level identity reconciliation using a hybrid approach.

## Responsibilities

- build a book-level character evidence pool
- form candidate groups deterministically
- send candidate groups to an Ollama resolver model
- write canonical resolution outputs
- produce a human-readable review file

## Inputs

- merged book outputs
- resolver model
- config file

## Outputs

```text
resolved/<book_slug>/
  resolution_candidates.json
  resolution_map.json
  resolution_report.json
  resolution_review.md
  book_resolved.json
```

## Key config sections

- `models`
- `timeouts`
- `paths`
- `logging`

## Notes

The resolver should prefer under-merging to over-merging.
