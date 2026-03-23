# Design Decisions

## Separate ingest from orchestration

This is one of the most important decisions in the project.

Ingest is deterministic document handling.
Orchestration is runtime and model control.

Keeping them separate avoids a monolithic script that is hard to debug and hard to rerun partially.

## Book-scoped directory layout

Artifacts are grouped by `book_slug` so that multiple books can coexist safely.

Examples:

- `work/chunks/treasure_island/`
- `work/chunks/dracula/`
- `out/treasure_island/chunk_000/`

This keeps artifacts traceable and reduces collisions.

## JSON-first outputs

Each pass is designed to output structured JSON rather than prose. This makes the outputs usable in later automation and easier to validate.

## Conservative extraction policy

The system is intentionally cautious. When uncertain, it should preserve ambiguity rather than inventing structure, identities, or traits.
