# Narrator's Toolkit MVP 4

This release adds chapter-aware reading controls and session resume.

## Included

- Manual chapter jumping from the sidebar.
- Chapter behaviour selector:
  - continue through chapters
  - stop at chapter boundaries
- Persistent reading position per cleaned manuscript.
- Resume action for returning to the last saved position.
- Scroll status that shows:
  - px/s
  - estimated WPM
  - chapter mode

## Notes

- Resume state is stored locally in the browser.
- Estimated WPM is derived from document length and scrollable height, so it is approximate.
- The reader still consumes the cleaned document artifact produced by Manuscript Prep; it does not invoke the ingest pipeline itself.
