# MVP 1 Manual Test

1. Install dependencies:

   ```bash
   pip install -r requirements-dev.txt
   ```

2. Start the gateway and worker in the usual ManuscriptPrep flow.

3. Upload or register a PDF with highlight annotations.

4. Run the ingest stage for that manuscript.

5. Confirm these artifacts exist:

   ```text
   work/cleaned/<book_slug>/clean.txt
   work/cleaned/<book_slug>/cleaned_document.json
   work/cleaned/<book_slug>/highlight_report.json
   ```

6. Open:

   ```text
   http://localhost:8000/ui/narrator-toolkit.html
   ```

7. Select the cleaned manuscript and verify:

   - Text is continuous, not PDF page based.
   - Chapter headings appear in the chapter selector.
   - Highlight colours are visible inline.
   - Any incomplete mapping warning matches `highlight_report.json`.

