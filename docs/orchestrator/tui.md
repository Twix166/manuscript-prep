# TUI (Terminal UI)

The orchestrator includes a live terminal dashboard.

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
