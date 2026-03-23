# PDF to Text

The ingest pipeline starts by classifying the PDF and attempting native text extraction.

## Native extraction first

Preferred first step:

```bash
pdftotext -layout input.pdf output.txt
```

Native extraction is faster and usually cleaner for text PDFs.

## OCR fallback

If native extraction is too sparse or obviously unusable, OCR can be used via:

- `ocrmypdf`
- `tesseract`

OCR should be a fallback, not the default, because it is slower and more error-prone.

## Output paths

Raw extraction artifacts are stored under:

```text
work/extracted/<book_slug>/
```

Typical files:

- `raw.txt`
- `raw_ocr.txt` when OCR was used

## Recommended tooling

- `pdftotext`
- `pdfinfo`
- `ocrmypdf` for OCR cases
