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

## Supported Runner

The supported resolver entry point is:

```bash
python manuscriptprep_resolver.py
```

Config behavior:

- `--config` is optional.
- When `--config` is provided, resolver can derive `input_dir` from `paths.merged_root/<book_slug>`, `output_dir` from `paths.resolved_root/<book_slug>`, and `model` from `models.resolver`.
- Explicit CLI values still override config-derived values.

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
