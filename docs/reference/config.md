# Configuration Reference

ManuscriptPrep should be configured through a YAML file rather than by editing code.

Every major script should accept:

```bash
--config /etc/manuscriptprep/config.yaml
```

## Primary config file

The main example file lives at:

```text
config/manuscriptprep.example.yaml
```

In production, the active file should usually live outside the repository, for example:

```text
/etc/manuscriptprep/config.yaml
```

## Core sections

### `project`
Basic metadata about the deployment environment.

### `paths`
Defines where ManuscriptPrep stores:

- extracted text
- cleaned text
- chunks
- orchestrator outputs
- merged outputs
- resolved outputs
- reports
- logs

### `models`
Maps each pipeline stage to an Ollama model name.

Required keys:

- `structure`
- `dialogue`
- `entities`
- `dossiers`
- `resolver`

### `ollama`
Connection settings for the Ollama host and CLI command.

### `timeouts`
Shared runtime defaults for:

- idle timeout
- hard timeout
- retry count
- idle timeout backoff
- resolver timeout

### `chunking`
Shared defaults for ingest and chunk creation.

### `reporting`
Controls report behavior, such as whether resolution output should be included.

### `logging`
Controls log verbosity and log destinations.

## Design rules

- Paths should not be hard-coded in scripts.
- Model names should not be hard-coded in scripts.
- Runtime tuning should come from config wherever possible.
- CLI flags may override config values, but config should remain the source of truth.
