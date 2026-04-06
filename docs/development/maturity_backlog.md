# Maturity Backlog

This document is the working backlog for moving ManuscriptPrep from a functional prototype toward a more maintainable and production-ready codebase.

## Working Rules

- prefer small clean patches
- never break existing functionality
- keep ingest deterministic
- keep intermediate artifacts inspectable
- update docs when behavior changes

## Todo List

### Now

- [x] Declare a single canonical orchestrator entry point and document it.
- [x] Retire or clearly mark non-canonical orchestrator variants.
- [x] Add a top-level execution guide showing the supported end-to-end pipeline.
- [ ] Centralize duplicated name-normalization logic used by merger and resolver.
- [x] Add smoke tests for ingest, orchestrator, merger, resolver, and report generation.

### Next

- [ ] Add consistent `--config` support to ingest, merger, resolver, and report scripts.
- [ ] Move shared filesystem, JSON, and runtime helpers into the `manuscriptprep/` package.
- [ ] Add contract tests for pass outputs and merged/resolved JSON schemas.
- [ ] Introduce fixture-based test data for at least one small sample manuscript.
- [ ] Normalize output naming conventions for raw outputs and error artifacts.
- [ ] Add lint and format checks alongside the test matrix.

### Later

- [ ] Package the supported CLIs through `pyproject.toml`.
- [ ] Split large script files into smaller package modules with focused responsibilities.
- [ ] Add CI for linting, tests, and basic docs validation.
- [ ] Add reproducible local dev setup for dependencies and tools.
- [ ] Improve operational docs for failure recovery and rerun workflows.

## Prioritized Backlog

### P0: Clarify Supported Runtime Surface

Goal: remove ambiguity about how the project is meant to be run.

- Define the canonical CLI entry points.
- Choose whether `manuscriptprep_orchestrator_tui_refactored.py` replaces `manuscriptprep_orchestrator_tui.py`.
- Mark scaffolds and archive-like files so users do not accidentally run them.
- Update README and docs to match the actual supported flow.

Why this matters:
- The repository currently exposes multiple orchestrator implementations with overlapping responsibilities.
- This creates drift risk, user confusion, and documentation inaccuracy.

Suggested deliverables:
- one supported orchestrator
- one documented end-to-end command sequence
- clear status labels for scaffold and legacy files

Status:
- Completed on April 6, 2026.

### P1: Unify Configuration

Goal: make config the default control surface across the full pipeline.

- Add shared config loading to ingest.
- Add shared config loading to merger.
- Add shared config loading to resolver.
- Add shared config loading to report generation.
- Standardize path derivation through `manuscriptprep.paths`.

Why this matters:
- The codebase already has shared config utilities, but only part of the runtime uses them consistently.
- Mixed config and ad hoc CLI wiring makes automation and deployment harder.

Suggested deliverables:
- every supported CLI accepts `--config`
- CLI flags override config in a consistent way
- no hard-coded default paths outside well-defined config fallbacks

### P2: Extract Shared Domain Logic

Goal: reduce duplication and make behavior easier to test.

- Create a shared module for name normalization, title canonicalization, and variant parsing.
- Create shared helpers for JSON read/write and artifact writing where duplication is high.
- Create shared runtime types for chunk records, timing records, and path contracts.

Why this matters:
- Merger and resolver currently duplicate identity parsing logic.
- Duplicated heuristics will drift and create hard-to-debug mismatches.

Suggested deliverables:
- `manuscriptprep/identity.py`
- `manuscriptprep/io.py`
- existing scripts switched to shared helpers with no behavior regressions

### P3: Add Test Coverage Around Pipeline Contracts

Goal: catch regressions before refactors spread risk.

- Add unit tests for text cleaning and chunking.
- Add unit tests for merger normalization and conflict detection.
- Add unit tests for resolver candidate grouping and resolution-map application.
- Add smoke tests that run the pipeline on small canned inputs without requiring a large manuscript.
- Add fixture outputs for malformed JSON and timeout/error paths.

Why this matters:
- The code is script-heavy and refactor pressure is high.
- Without tests, even small cleanup work carries significant regression risk.

Suggested deliverables:
- a `tests/` layout with fixtures
- deterministic tests for non-LLM stages
- mocked or stubbed tests for Ollama-dependent paths

Status:
- Baseline test workflow completed on April 6, 2026 with `unit`, `regression`, `smoke`, and `integration` suites plus CI wiring.

### P4: Improve Packaging and Developer Workflow

Goal: make the project easier to install, run, and contribute to safely.

- Populate `pyproject.toml`.
- Populate `requirements.txt` or replace it with a single supported dependency workflow.
- Add console script entry points for the main CLIs.
- Add formatting and linting standards.
- Add a documented local setup sequence.

Why this matters:
- The repository currently looks partially scaffolded from a packaging perspective.
- This increases onboarding cost and makes automation less reliable.

Suggested deliverables:
- installable package metadata
- repeatable dev environment
- documented dependency list

### P5: Harden Runtime Observability and Recovery

Goal: make long-running local processing easier to debug and resume.

- Standardize structured logs across all stages.
- Add explicit run manifests for orchestrator, merger, resolver, and report stages.
- Document rerun-from-stage workflows.
- Document partial-failure recovery for single chunks and single books.
- Add summary status artifacts for batch runs.

Why this matters:
- The orchestrator already has strong observability patterns.
- The rest of the pipeline should align with that same operational model.

Suggested deliverables:
- per-stage run metadata
- resumable operational playbooks
- consistent JSONL logging where appropriate

### P6: Tighten Documentation Accuracy

Goal: make docs describe the code that actually exists today.

- Update README repository layout to match the current tree.
- Update install docs to match real dependencies.
- Add a current architecture diagram or flow summary.
- Add a command cookbook for the canonical workflow.
- Note which docs are aspirational versus implemented.

Why this matters:
- Some docs currently describe the target shape more than the current state.
- Accurate docs are necessary before larger cleanup work starts.

Suggested deliverables:
- corrected README
- canonical quickstart
- implementation-status notes where needed

## Candidate Task Sequence

1. Canonicalize the orchestrator entry point.
2. Update README and quickstart to reflect the supported commands.
3. Add shared config support to the remaining CLIs.
4. Extract shared identity logic into the package.
5. Add tests around ingest, merger, and resolver contracts.
6. Finish packaging and CI once the runtime surface is stable.

## Out of Scope for Early Cleanup

- prompt redesign unless there is a demonstrated extraction failure
- model swaps without baseline comparison data
- UI redesign of the TUI before runtime contracts are stable
- large schema changes before tests exist
