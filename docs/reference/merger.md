# Merger Reference

## Purpose

The merger combines per-chunk outputs into book-level artifacts.

## Responsibilities

- merge chunk-level structure
- merge dialogue summaries
- merge entities
- merge dossiers
- detect conflicts
- write book-level outputs

## Inputs

- orchestrator chunk outputs
- optional chunk manifest

## Outputs

```text
merged/<book_slug>/
  structure_merged.json
  dialogue_merged.json
  entities_merged.json
  dossiers_merged.json
  conflict_report.json
  merge_report.json
  book_merged.json
```

## Notes

The merger should remain deterministic. It may perform heuristic grouping, but it should not be the only identity-resolution layer.
