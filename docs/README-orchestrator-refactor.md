# Orchestrator config refactor starter

This bundle shows a clean way to wire the orchestrator into the shared config system.

## Included

- `manuscriptprep/config.py`
- `manuscriptprep/paths.py`
- `manuscriptprep/logging_utils.py`
- `scripts/manuscriptprep_orchestrator_tui_configured.py`

## How to use this

This is intentionally a **refactor scaffold** rather than a claim to replace your exact current orchestrator 1:1.

Use it to:

1. add `--config`
2. centralize model names
3. centralize paths
4. centralize timeout settings
5. centralize JSONL logging

Then move your current:
- TUI rendering
- streaming model output
- idle timeout watcher
- retry status display
- per-stage diagnostics

into the marked stage runner / TUI areas.

## Recommended next integration order

1. keep your existing orchestrator file
2. copy over:
   - config loading
   - settings dataclass
   - path building
   - logger setup
3. replace hard-coded values with config lookups
4. only then move over the rest of the refactor
