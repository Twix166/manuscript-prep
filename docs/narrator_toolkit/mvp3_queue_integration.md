# MVP 3 Queue Integration

MVP 3 exposes cleaned manuscripts as a visible queue in Narrator's Toolkit.

## What Changed

- The reader now shows a queue of cleaned manuscripts with one row per document.
- Each row displays:
  - title
  - source filename
  - cleaning status
  - created date
  - highlight count or has-highlights indicator
  - chapter count
- Each row includes an `Open in Narrator's Toolkit` action.
- The reader still loads the selected cleaned document directly from the gateway; no manual paste step exists.

## Reused Gateway Surface

The queue uses the existing endpoint:

- `GET /v1/narrator-toolkit/documents`

The document payload is still fetched from:

- `GET /v1/narrator-toolkit/documents/{manuscript_id}`

## Manual Test

1. Run ingest on one or more PDFs.
2. Open `/ui/narrator-toolkit.html`.
3. Confirm the queue lists the cleaned manuscripts.
4. Click `Open in Narrator's Toolkit` on a row.
5. Confirm the reader loads that document.
6. Confirm the queue row shows the metadata fields above.

