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
- optional config file

## Supported Runner

The supported merger entry point is:

```bash
python manuscriptprep_merger.py
```

Config behavior:

- `--config` is optional.
- When `--config` is provided, merger can derive `input_dir` from `paths.output_root/<book_slug>` and `output_dir` from `paths.merged_root/<book_slug>`.
- When `--book-slug` is provided with config, merger also defaults `chunk_manifest` to `workspace_root/manifests/<book_slug>/chunk_manifest.json`.
- Explicit CLI paths still override config-derived paths.

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
