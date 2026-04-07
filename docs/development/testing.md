# Testing

ManuscriptPrep now uses a pytest-based test matrix. Any code change should run all of these suites before it is considered complete:

- `unit`
- `regression`
- `smoke`
- `integration`

Recommended command:

```bash
bash scripts/run_test_matrix.sh
```

You can also run suites individually:

```bash
python -m pytest -m unit
python -m pytest -m regression
python -m pytest -m smoke
python -m pytest -m integration
```

## What each suite covers

### Unit

Fast deterministic tests for isolated logic such as:

- text cleaning
- chunking
- merger normalization
- resolution-map application

### Regression

Tests for behaviors that are easy to break during refactors, such as:

- JSON extraction from model output
- dossier-input construction
- malformed artifact handling

### Smoke

A minimal end-to-end CLI run through the supported flow:

- ingest
- orchestrator
- merger
- resolver
- PDF report

These tests use fake local tool shims for `pdftotext`, `ocrmypdf`, `pdfinfo`, and `ollama` so they remain deterministic and do not depend on external services.

### Integration

Multi-component tests for stage boundaries and artifact contracts across real CLI invocations.

The default automated matrix does not require a live PostgreSQL instance. PostgreSQL-backed gateway testing is currently a manual stack-level check through [compose.yaml](/home/rbalm/Manuscript_Prep_Modelfile/compose.yaml).

## Additional checks worth keeping in mind

The required suites above are the baseline. As the codebase matures, add:

- contract/schema tests for JSON artifacts
- linting and formatting checks
- dependency-install checks in CI
- performance checks for very large manuscript runs when representative fixtures exist
