# Passes

The orchestrator runs four focused passes.

## Structure pass

Purpose:
- chapter titles
- part titles
- scene breaks
- structural status

## Dialogue pass

Purpose:
- POV
- whether dialogue is present
- whether internal thought is present
- explicitly attributed speakers
- unattributed dialogue flag

## Entities pass

Purpose:
- literal characters
- places
- objects
- identity notes where necessary

This pass may occasionally emit malformed JSON or trailing text.

## Dossiers pass

Purpose:
- conservative character dossiers using excerpt text plus prior extraction data

This is usually the heaviest pass and often the most latency-sensitive.
