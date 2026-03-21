import re

def clean_text(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")

    cleaned_lines = []
    for line in lines:
        line = line.strip()

        # Remove empty lines
        if not line:
            continue

        # Remove page numbers (lines that are just digits)
        if re.match(r"^\d+$", line):
            continue

        # Remove repeated headers (e.g., "Treasure Island")
        if line.lower() in ["treasure island"]:
            continue

        # Remove lines that are mostly non-letter
        if len(re.findall(r"[a-zA-Z]", line)) < 3:
            continue

        cleaned_lines.append(line)

    # Rejoin into paragraphs
    cleaned_text = "\n".join(cleaned_lines)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

clean_text("raw.txt", "clean.txt")
