# Malformed JSON

Some passes may emit JSON followed by extra text, which leads to errors such as:

```text
Extra data: line 7 column 1
```

## What this means

The model likely produced:

- valid JSON
- then additional trailing output

## Common causes

- visible reasoning
- repeated output
- accidental schema commentary

## Mitigations

- keep retries enabled
- inspect `*_raw.txt`
- tighten prompts
- prefer smaller chunks
