# Models Overview

ManuscriptPrep uses one specialized model per pass.

## Current models

- `manuscriptprep-structure`
- `manuscriptprep-dialogue`
- `manuscriptprep-entities`
- `manuscriptprep-dossiers`

## Why separate models

Separate models reduce:

- prompt conflicts
- schema drift
- over-broad reasoning
- accidental cross-task hallucination

This also makes debugging easier because each pass has a narrower role.
