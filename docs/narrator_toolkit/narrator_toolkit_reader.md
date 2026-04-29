# Narrator's Toolkit Reader

Narrator's Toolkit is a browser reader for cleaned manuscripts produced by ManuscriptPrep.

## What It Loads

- The queue endpoint returns cleaned documents that ManuscriptPrep already produced.
- Opening a document fetches the structured JSON artifact.
- The reader does not rerun ingest or cleaning.

## What It Renders

- Continuous manuscript text without PDF page breaks.
- Highlight spans with the original colours preserved.
- A highlight legend based on the saved palette.
- Chapter navigation when the cleaned document includes chapter blocks.

## Reader Controls

- `Play` / `Pause` starts or stops constant-speed scrolling.
- `Space` toggles scrolling.
- `Arrow Up` and `Arrow Down` adjust speed.
- `Esc` stops scrolling.
- The sidebar `Resume` button restores the last saved reading position for that manuscript.
- The chapter selector jumps directly to a chapter.

## Persistence

- Reading position is stored in the browser for each manuscript.
- Scroll settings are also stored locally.
- If the saved position exists, the reader restores it when the document loads.

## Known Limits

- WPM is an estimate derived from document length and scroll speed.
- Chapter detection only works where the source text has clear chapter markers or section headings.
- Highlight mapping still depends on the fidelity of the PDF text extraction and source context available in the PDF.
