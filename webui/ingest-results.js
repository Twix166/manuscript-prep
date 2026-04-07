const storageKey = "manuscriptprep.apiToken";
const params = new URLSearchParams(window.location.search);
const manuscriptId = params.get("manuscript_id");
const token = localStorage.getItem(storageKey) || "";

const els = {
  title: document.getElementById("ingest-results-title"),
  status: document.getElementById("ingest-results-status"),
  summary: document.getElementById("ingest-results-summary"),
  classification: document.getElementById("ingest-classification"),
  chunking: document.getElementById("ingest-chunking"),
  extract: document.getElementById("ingest-extract"),
  clean: document.getElementById("ingest-clean"),
};

async function fetchJson(path) {
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed for ${path}`);
  }
  return payload;
}

function summaryCard(label, value) {
  const article = document.createElement("article");
  article.className = "panel";
  article.innerHTML = `<p class="eyebrow">${label}</p><h2>${value}</h2>`;
  return article;
}

async function load() {
  if (!manuscriptId) {
    els.status.textContent = "Missing manuscript_id in URL.";
    return;
  }
  try {
    const payload = await fetchJson(`/v1/manuscripts/${encodeURIComponent(manuscriptId)}/ingest-results`);
    const ingestManifest = payload.ingest_manifest.content || {};
    const chunkManifest = payload.chunk_manifest.content || {};
    const classification = ingestManifest.classification || ingestManifest;
    const extraction = ingestManifest.extraction || {};
    const cleaning = ingestManifest.cleaning || {};
    const chunking = ingestManifest.chunking || {
      chunk_count: chunkManifest.chunk_count,
      chunk_settings: chunkManifest.chunk_settings,
    };
    els.title.textContent = `${payload.manuscript.title} Ingest Results`;
    els.status.textContent = `Showing the latest ingest for manuscript ${payload.manuscript.book_slug}.`;
    els.summary.innerHTML = "";
    els.summary.appendChild(summaryCard("PDF Type", classification.pdf_type || "Unknown"));
    els.summary.appendChild(summaryCard("Pages", classification.page_count || extraction.page_count || "n/a"));
    els.summary.appendChild(summaryCard("Chunks", chunking.chunk_count || chunkManifest.chunk_count || "n/a"));
    els.classification.textContent = JSON.stringify(classification, null, 2);
    els.chunking.textContent = JSON.stringify(
      {
        summary: chunking,
        chunks: (chunkManifest.chunks || []).slice(0, 10),
      },
      null,
      2,
    );
    els.extract.textContent = `${JSON.stringify(extraction, null, 2)}\n\n${payload.raw_text.preview || ""}`;
    els.clean.textContent = `${JSON.stringify(cleaning, null, 2)}\n\n${payload.clean_text.preview || ""}`;
  } catch (error) {
    els.status.textContent = error.message;
    els.classification.textContent = error.message;
    els.chunking.textContent = error.message;
    els.extract.textContent = error.message;
    els.clean.textContent = error.message;
  }
}

load();
