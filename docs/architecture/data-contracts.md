# Data Contracts

The pipeline relies on stable JSON contracts between stages.

## Important artifacts

- `chunk_manifest.json`
- per-chunk pass outputs
- `book_merged.json`
- `conflict_report.json`
- `resolution_map.json`
- `book_resolved.json`

Each contract should be documented so refactors do not silently break downstream stages.
