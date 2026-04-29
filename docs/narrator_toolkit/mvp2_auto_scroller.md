# MVP 2 Auto-Scroller

MVP 2 adds constant-speed browser scrolling to the Narrator's Toolkit reader. It does not change ManuscriptPrep workflows or the cleaned document format.

## Controls

- `Play` / `Pause`: starts and stops constant-speed scrolling.
- `Speed` slider: sets scroll speed from 10 to 180 pixels per second.
- `-` and `+`: decrease or increase speed in 5 px/s steps.
- `Space`: start or stop scrolling.
- `Arrow Up`: increase speed.
- `Arrow Down`: decrease speed.
- `Esc`: stop scrolling.

The implementation uses `requestAnimationFrame` with pixel-per-second motion. Highlight spans remain normal inline DOM elements, so scrolling does not change text layout or highlight alignment.

## Read-Ahead Behaviour

The reader keeps bottom padding in the continuous manuscript view so the current reading area does not sit at the bottom of the viewport near the end of the document.

## Manual Test

1. Open `/ui/narrator-toolkit.html`.
2. Select a cleaned manuscript.
3. Click `Play`.
4. Confirm the document scrolls continuously.
5. Press `Space` to pause and resume.
6. Use `Arrow Up`, `Arrow Down`, `+`, and `-` to change speed.
7. Confirm highlights remain visible and aligned while scrolling.

