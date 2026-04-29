# ManuscriptPrep Ingest Workflow

ManuscriptPrep is still the system of record for document ingestion and cleaning. Narrator's Toolkit consumes the cleaned artifact that ManuscriptPrep writes.

## Flow

1. A source file is uploaded into ManuscriptPrep.
2. The ingest pipeline classifies the input and extracts raw text.
3. Cleaning removes page markers, repeated headers and footers, and layout noise.
4. PDF highlight annotations are extracted from the source PDF.
5. Highlight text is mapped back onto the cleaned text.
6. ManuscriptPrep writes:
   - `work/cleaned/<book_slug>/cleaned_document.json`
   - `work/cleaned/<book_slug>/highlight_report.json`
7. The gateway exposes the cleaned document through the Narrator's Toolkit API.

## Highlight Preservation

Highlights are treated as semantic spans, not styling.

- Each extracted highlight keeps its source page, annotation id, colour, and source text.
- The mapper first tries to place the highlight using source context from the PDF page.
- If that fails, it falls back to exact, whitespace-normalised, punctuation-tolerant, and fuzzy matching.
- The saved `highlight_report` records how many highlights mapped and which ones did not.

## Chapter and Header Rules

- Chapter headings are detected from explicit labels such as `Chapter 1`, `Chapter I`, `Part Two`, `Prologue`, and `Epilogue`.
- Repeated page-edge lines are removed when they behave like headers or footers.
- Page breaks are normalised so the cleaned document is a continuous reading surface.

## Outputs

The cleaned document JSON contains:

- chapters and blocks with stable offsets
- highlight spans attached to blocks
- a highlight palette for the reader
- metadata describing cleaner version, source type, and highlight preservation status
