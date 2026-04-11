# PDF Report Reference

## Purpose

The PDF report generator creates a human-readable book report from merged or resolved outputs.

## Responsibilities

- generate executive summary
- render structure
- render dialogue summary
- render entity tables
- render dossiers
- render conflict section
- render resolution section when available

## Inputs

- merged or resolved output directory
- optional shared YAML config plus `book_slug` for derived paths

## Outputs

- PDF report file

## Notes

The report generator should prefer resolved outputs when present, but remain compatible with merged-only outputs.

Supported invocation modes:
- explicit paths: `--input-dir` and `--output`
- config-derived paths: `--config` plus `--book-slug`, which resolves
  - input dir from `paths.resolved_root/<book_slug>` when `book_resolved.json` exists
  - otherwise input dir from `paths.merged_root/<book_slug>`
  - output PDF from `paths.reports_root/<book_slug>_report.pdf`

Explicit CLI paths override config-derived defaults. The generated PDF includes a
visible source marker so readers can tell whether it was built from merged or
resolved data.
