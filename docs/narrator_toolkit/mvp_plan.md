# Narrator's Toolkit MVP Plan

Narrator's Toolkit is adjacent to ManuscriptPrep. ManuscriptPrep remains the ingestion, cleaning, chunking, and analysis workflow. Narrator's Toolkit consumes cleaned manuscript artifacts and presents a narrator-facing reader.

## Reused ManuscriptPrep Code

- `manuscriptprep_ingest.py`: source format detection, raw text extraction, deterministic cleaning, structure hints, workspace paths, and manifest writing.
- `manuscriptprep.execution_adapter`: gateway-managed ingest artifact registration.
- `manuscriptprep_gateway_api.py`: authentication, manuscript ownership checks, artifact lookup, and static web asset serving.
- `webui/`: visual shell and static asset serving conventions.

## MVP 1

Implemented:

- PDF highlight annotation extraction via PyMuPDF when available.
- Cleaned structured JSON artifact at `work/cleaned/<book_slug>/cleaned_document.json`.
- Highlight preservation report at `work/cleaned/<book_slug>/highlight_report.json`.
- Gateway endpoints:
  - `GET /v1/narrator-toolkit/documents`
  - `GET /v1/narrator-toolkit/documents/{manuscript_id}`
- Separate web page at `/ui/narrator-toolkit.html`.
- Continuous reader rendering with chapter selector and highlight legend.

Limitations:

- Character names are not inferred from highlight colours.
- Highlight mapping uses exact, whitespace-normalised, punctuation-tolerant, then fuzzy text matching. Ambiguous repeated passages can still require QA review.
- Real PDF highlight extraction requires `PyMuPDF`.

MVP 2 should add constant-speed auto-scroll controls without changing the cleaned document format.

