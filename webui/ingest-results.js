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
  chunkList: document.getElementById("ingest-chunk-list"),
  rawText: document.getElementById("ingest-raw-text"),
  cleanText: document.getElementById("ingest-clean-text"),
  downloadRawText: document.getElementById("download-raw-text"),
  downloadCleanText: document.getElementById("download-clean-text"),
  downloadChunkManifest: document.getElementById("download-chunk-manifest"),
  downloadIngestManifest: document.getElementById("download-ingest-manifest"),
};

let currentJobId = null;

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

async function downloadArtifact(artifactName) {
  if (!currentJobId) {
    renderError("No ingest job is available for download yet.");
    return;
  }
  const response = await fetch(`/v1/jobs/${encodeURIComponent(currentJobId)}/artifacts/${encodeURIComponent(artifactName)}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    let message = `Download failed for ${artifactName}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      // fall back to default message
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : artifactName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function summaryCard(label, value) {
  const article = document.createElement("article");
  article.className = "panel";
  article.innerHTML = `<p class="eyebrow">${label}</p><h2>${value}</h2>`;
  return article;
}

function renderPayload(payload) {
  currentJobId = payload.job.job_id;
  const ingestManifest = payload.ingest_manifest.content || {};
  const chunkManifest = payload.chunk_manifest.content || {};
  const classification = ingestManifest.classification || ingestManifest;
  const extraction = ingestManifest.extraction || {};
  const cleaning = ingestManifest.cleaning || {};
  const chunks = chunkManifest.chunks || [];
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
      chunk_settings: chunkManifest.chunk_settings || null,
      chunk_count: chunkManifest.chunk_count || chunks.length,
    },
    null,
    2,
  );
  els.extract.textContent = JSON.stringify(extraction, null, 2);
  els.clean.textContent = JSON.stringify(cleaning, null, 2);
  els.chunkList.textContent = JSON.stringify(chunks, null, 2);
  els.rawText.textContent = payload.raw_text.content || payload.raw_text.preview || "";
  els.cleanText.textContent = payload.clean_text.content || payload.clean_text.preview || "";
}

function renderError(message) {
  els.status.textContent = message;
  els.classification.textContent = message;
  els.chunking.textContent = message;
  els.extract.textContent = message;
  els.clean.textContent = message;
  els.chunkList.textContent = message;
  els.rawText.textContent = message;
  els.cleanText.textContent = message;
}

async function load() {
  if (!manuscriptId) {
    renderError("Missing manuscript_id in URL.");
    return;
  }
  els.status.textContent = "Loading ingest results...";
  try {
    const payload = await fetchJson(`/v1/manuscripts/${encodeURIComponent(manuscriptId)}/ingest-results`);
    renderPayload(payload);
  } catch (error) {
    renderError(error.message);
  }
}

for (const [button, artifactName] of [
  [els.downloadRawText, "raw_text"],
  [els.downloadCleanText, "clean_text"],
  [els.downloadChunkManifest, "chunk_manifest"],
  [els.downloadIngestManifest, "ingest_manifest"],
]) {
  button.addEventListener("click", async () => {
    try {
      await downloadArtifact(artifactName);
    } catch (error) {
      renderError(error.message);
    }
  });
}

load();
