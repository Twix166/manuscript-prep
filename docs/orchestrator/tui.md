# TUI (Terminal UI)

The orchestrator includes a live terminal dashboard.

## Dependency preflight

Before a run starts, the orchestrator checks for:

- the required Python modules
- the PDF extraction binaries
- Ollama availability
- the required Ollama models

If any item is missing, the interface shows a dependency table and offers an install action that runs the repository installer.

The preflight also shows an inference backend diagnostics panel. That panel is
informational only: it reports whether the host appears ready for CUDA, ROCm,
Metal, Vulkan, or CPU fallback, but it does not block the run.

## Pipeline Status panel

The status panel shows:

- current chunk
- current pass
- pass status
- current step
- pass elapsed time
- chunk elapsed time
- progress
- retries used
- effective idle timeout
- idle backoff count
- estimated or reported token speed
- age of last stdout
- age of last stderr

## Log panel

The orchestrator log panel shows events such as:

- chunk start
- pass start
- raw output written
- parsed JSON written
- retry scheduled
- pass error
- chunk completion

## Stdout and stderr panels

These show live model stdout and stderr so you can observe:

- visible reasoning
- silence before output
- malformed output patterns
- possible stalls

## Installer action

When the dependency table shows missing items, press the install action in the preflight screen to run the repository installer. The installer will try to satisfy the Python, system, Ollama, and model layers in one pass.
