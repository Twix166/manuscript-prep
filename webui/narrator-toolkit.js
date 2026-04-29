const els = {
  documentQueue: document.getElementById("document-queue"),
  documentStatus: document.getElementById("document-status"),
  chapterSelect: document.getElementById("chapter-select"),
  highlightLegend: document.getElementById("highlight-legend"),
  mappingWarning: document.getElementById("mapping-warning"),
  readerTitle: document.getElementById("reader-title"),
  readerContent: document.getElementById("reader-content"),
  scrollToggle: document.getElementById("scroll-toggle"),
  scrollSlower: document.getElementById("scroll-slower"),
  scrollFaster: document.getElementById("scroll-faster"),
  scrollSpeed: document.getElementById("scroll-speed"),
  scrollStatus: document.getElementById("scroll-status"),
};

const authToken = localStorage.getItem("manuscriptprep.apiToken");
const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
const scroller = {
  running: false,
  speed: Number(document.getElementById("scroll-speed")?.value || 45),
  frameId: null,
  lastFrameTime: null,
};
const queueState = {
  documents: [],
  selectedDocumentId: null,
};

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function fetchJson(path) {
  const response = await fetch(path, { headers });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function renderTextWithSpans(block) {
  const spans = [...(block.spans || [])].sort((a, b) => a.start - b.start);
  let cursor = 0;
  let html = "";
  for (const span of spans) {
    if (span.start > cursor) {
      html += escapeHtml(block.text.slice(cursor, span.start));
    }
    const text = block.text.slice(span.start, span.end);
    const color = /^#[0-9a-f]{6}$/i.test(span.color) ? span.color : "#ffff00";
    html += `<mark class="reader-highlight" style="--highlight-color: ${color}" title="Page ${escapeHtml(span.source_page)}">${escapeHtml(text)}</mark>`;
    cursor = Math.max(cursor, span.end);
  }
  html += escapeHtml(block.text.slice(cursor));
  return html;
}

function renderLegend(document) {
  const palette = document.highlight_palette || [];
  if (!palette.length) {
    els.highlightLegend.innerHTML = '<li class="muted">No highlights found</li>';
    return;
  }
  els.highlightLegend.innerHTML = palette.map((item) => `
    <li>
      <span class="legend-swatch" style="background: ${escapeHtml(item.color)}"></span>
      <span>${escapeHtml(item.color)} (${Number(item.usage_count || 0)})</span>
    </li>
  `).join("");
}

function renderMappingWarning(report) {
  if (!report || !report.unmapped_highlights) {
    els.mappingWarning.classList.add("hidden");
    els.mappingWarning.textContent = "";
    return;
  }
  els.mappingWarning.classList.remove("hidden");
  els.mappingWarning.textContent = `${report.unmapped_highlights} of ${report.total_highlights} highlights could not be mapped. Review the highlight preservation report before narrating.`;
}

function formatDateTime(value) {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function maxScrollTop() {
  return Math.max(
    0,
    document.documentElement.scrollHeight - window.innerHeight,
  );
}

function renderScrollControls() {
  els.scrollToggle.textContent = scroller.running ? "Pause" : "Play";
  els.scrollToggle.setAttribute("aria-pressed", String(scroller.running));
  els.scrollSpeed.value = String(scroller.speed);
  els.scrollStatus.textContent = `${scroller.running ? "Scrolling" : "Stopped"} at ${scroller.speed} px/s`;
}

function stopScrolling() {
  scroller.running = false;
  scroller.lastFrameTime = null;
  if (scroller.frameId !== null) {
    cancelAnimationFrame(scroller.frameId);
    scroller.frameId = null;
  }
  renderScrollControls();
}

function openDocument(manuscriptId) {
  queueState.selectedDocumentId = manuscriptId;
  renderDocumentQueue();
  loadDocument(manuscriptId).catch((error) => {
    els.documentStatus.textContent = error.message;
  });
}

function scrollFrame(timestamp) {
  if (!scroller.running) {
    return;
  }
  if (scroller.lastFrameTime === null) {
    scroller.lastFrameTime = timestamp;
  }
  const elapsedSeconds = Math.min((timestamp - scroller.lastFrameTime) / 1000, 0.1);
  scroller.lastFrameTime = timestamp;
  const nextTop = Math.min(window.scrollY + scroller.speed * elapsedSeconds, maxScrollTop());
  window.scrollTo({ top: nextTop, behavior: "auto" });
  if (nextTop >= maxScrollTop()) {
    stopScrolling();
    return;
  }
  scroller.frameId = requestAnimationFrame(scrollFrame);
}

function startScrolling() {
  if (scroller.running || maxScrollTop() <= 0) {
    return;
  }
  scroller.running = true;
  scroller.lastFrameTime = null;
  renderScrollControls();
  scroller.frameId = requestAnimationFrame(scrollFrame);
}

function toggleScrolling() {
  if (scroller.running) {
    stopScrolling();
  } else {
    startScrolling();
  }
}

function setScrollSpeed(nextSpeed) {
  const min = Number(els.scrollSpeed.min);
  const max = Number(els.scrollSpeed.max);
  scroller.speed = Math.max(min, Math.min(max, Number(nextSpeed)));
  renderScrollControls();
}

function renderDocument(document, report) {
  stopScrolling();
  els.readerTitle.textContent = document.title || "Untitled manuscript";
  els.chapterSelect.innerHTML = (document.chapters || []).map((chapter, index) => (
    `<option value="${escapeHtml(chapter.id)}">${escapeHtml(chapter.title || `Chapter ${index + 1}`)}</option>`
  )).join("");
  els.readerContent.innerHTML = (document.chapters || []).map((chapter) => `
    <section class="reader-chapter" id="${escapeHtml(chapter.id)}">
      ${(chapter.blocks || []).map((block) => {
        const tag = block.type === "heading" ? "h3" : "p";
        return `<${tag} class="reader-block">${renderTextWithSpans(block)}</${tag}>`;
      }).join("")}
    </section>
  `).join("");
  renderLegend(document);
  renderMappingWarning(report || document.metadata?.highlight_report);
}

function renderDocumentQueue() {
  const documents = queueState.documents || [];
  if (!documents.length) {
    els.documentQueue.innerHTML = '<li class="muted">No cleaned manuscripts yet</li>';
    return;
  }
  els.documentQueue.innerHTML = documents.map((document, index) => {
    const selected = document.manuscript_id === queueState.selectedDocumentId;
    const queueLabel = `#${index + 1}`;
    return `
      <li class="queue-item ${selected ? "selected" : ""}" data-manuscript-id="${escapeHtml(document.manuscript_id)}">
        <div class="queue-item-main">
          <div class="queue-item-title">
            <span class="queue-label">${queueLabel}</span>
            <strong>${escapeHtml(document.title)}</strong>
          </div>
          <div class="queue-item-meta">
            <span>${escapeHtml(document.source_filename || "Unknown source")}</span>
            <span>${escapeHtml(document.cleaning_status || "unknown")}</span>
            <span>${escapeHtml(formatDateTime(document.created_at))}</span>
          </div>
          <div class="queue-item-meta">
            <span>${document.has_highlights ? `Highlights ${Number(document.highlight_count || 0)}` : "No highlights"}</span>
            <span>Chapters ${Number(document.chapter_count || 0)}</span>
          </div>
        </div>
        <div class="queue-item-actions">
          <button type="button" class="secondary-button open-reader">Open in Narrator's Toolkit</button>
        </div>
      </li>
    `;
  }).join("");

  for (const item of els.documentQueue.querySelectorAll(".queue-item")) {
    const manuscriptId = item.dataset.manuscriptId;
    item.addEventListener("click", () => openDocument(manuscriptId));
    const button = item.querySelector(".open-reader");
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openDocument(manuscriptId);
    });
  }
}

async function loadDocument(manuscriptId) {
  if (!manuscriptId) {
    els.readerContent.textContent = "No cleaned document selected.";
    return;
  }
  els.documentStatus.textContent = "Loading cleaned document...";
  const payload = await fetchJson(`/v1/narrator-toolkit/documents/${encodeURIComponent(manuscriptId)}`);
  queueState.selectedDocumentId = manuscriptId;
  renderDocumentQueue();
  renderDocument(payload.document, payload.highlight_report);
  els.documentStatus.textContent = `Loaded ${payload.manuscript.title}`;
}

async function loadDocuments() {
  const payload = await fetchJson("/v1/narrator-toolkit/documents");
  queueState.documents = payload.documents || [];
  if (!payload.documents.length) {
    queueState.selectedDocumentId = null;
    renderDocumentQueue();
    els.documentStatus.textContent = "Run an ingest job first to create a Narrator's Toolkit cleaned document.";
    return;
  }
  els.documentStatus.textContent = `${payload.documents.length} cleaned manuscript${payload.documents.length === 1 ? "" : "s"} available.`;
  if (!queueState.selectedDocumentId || !queueState.documents.some((document) => document.manuscript_id === queueState.selectedDocumentId)) {
    queueState.selectedDocumentId = queueState.documents[0].manuscript_id;
  }
  renderDocumentQueue();
  await loadDocument(queueState.selectedDocumentId);
}

els.chapterSelect.addEventListener("change", () => {
  stopScrolling();
  const target = document.getElementById(els.chapterSelect.value);
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

els.scrollToggle.addEventListener("click", toggleScrolling);
els.scrollSpeed.addEventListener("input", () => setScrollSpeed(els.scrollSpeed.value));
els.scrollSlower.addEventListener("click", () => setScrollSpeed(scroller.speed - 5));
els.scrollFaster.addEventListener("click", () => setScrollSpeed(scroller.speed + 5));

document.addEventListener("keydown", (event) => {
  const target = event.target;
  const isTyping = target instanceof HTMLElement && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
  if (isTyping && event.code !== "Escape") {
    return;
  }
  if (event.code === "Space") {
    event.preventDefault();
    toggleScrolling();
  } else if (event.code === "ArrowUp") {
    event.preventDefault();
    setScrollSpeed(scroller.speed + 5);
  } else if (event.code === "ArrowDown") {
    event.preventDefault();
    setScrollSpeed(scroller.speed - 5);
  } else if (event.code === "Escape") {
    stopScrolling();
  }
});

renderScrollControls();

loadDocuments().catch((error) => {
  els.documentStatus.textContent = error.message;
});
