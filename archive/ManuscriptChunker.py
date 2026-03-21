def chunk_text(text, chunk_size=2000):
    words = text.split()
    chunks = []

    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i+chunk_size])
        chunks.append(chunk)

    return chunks

with open("clean.txt", "r", encoding="utf-8") as f:
    text = f.read()

chunks = chunk_text(text)

for i, chunk in enumerate(chunks):
    with open(f"chunk_{i}.txt", "w", encoding="utf-8") as f:
        f.write(chunk)
