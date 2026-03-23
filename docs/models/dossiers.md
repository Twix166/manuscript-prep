# Dossiers Model

The dossiers model generates conservative character dossiers.

## Inputs

- excerpt text
- entity output
- dialogue output

## Why this pass is heavier

This pass often does the most synthesis work and is usually:

- slower
- more stall-prone
- more likely to benefit from adaptive idle-timeout backoff

## Practical recommendation

If the dossier pass remains the main bottleneck, consider:

- smaller chunks
- narrower dossier input
- pass-specific timeout defaults in a future version
