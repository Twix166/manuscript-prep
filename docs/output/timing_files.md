# Timing Files

Each successful chunk includes `timing.json`.

## Contents

- total chunk duration
- per-pass durations

## Purpose

Timing files are useful for:

- performance profiling
- spotting the slowest pass
- tracking chunk-size improvements
- deciding whether pass-specific timeout tuning is worth doing
