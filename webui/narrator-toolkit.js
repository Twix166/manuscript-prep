const els = {
  documentQueue: document.getElementById("document-queue"),
  documentStatus: document.getElementById("document-status"),
  chapterSelect: document.getElementById("chapter-select"),
  chapterMode: document.getElementById("chapter-mode"),
  readingProgress: document.getElementById("reading-progress"),
  highlightLegend: document.getElementById("highlight-legend"),
  mappingWarning: document.getElementById("mapping-warning"),
  readerTitle: document.getElementById("reader-title"),
  readerContent: document.getElementById("reader-content"),
  resumeReading: document.getElementById("resume-reading"),
  scrollToggle: document.getElementById("scroll-toggle"),
  scrollSlower: document.getElementById("scroll-slower"),
  scrollFaster: document.getElementById("scroll-faster"),
  scrollSpeed: document.getElementById("scroll-speed"),
  scrollStatus: document.getElementById("scroll-status"),
};

const authToken = localStorage.getItem("manuscriptprep.apiToken");
const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
const SETTINGS_STORAGE_KEY = "manuscriptprep.narrator.settings";
const RESUME_STORAGE_KEY = "manuscriptprep.narrator.resume";
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
const readingState = {
  manuscriptId: null,
  chapterMetrics: [],
  resumeRecord: null,
  wordCount: 0,
  lastSavedScrollTop: 0,
  lastSaveAt: 0,
  lastKnownChapterIndex: 0,
};

function loadJsonStorage(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) {
      return fallback;
    }
    return JSON.parse(raw);
  } catch (_error) {
    return fallback;
  }
}

function writeJsonStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (_error) {
    return;
  }
}

function loadSettings() {
  const settings = loadJsonStorage(SETTINGS_STORAGE_KEY, {});
  if (settings && typeof settings === "object") {
    if (typeof settings.speed === "number") {
      scroller.speed = settings.speed;
    }
    if (settings.chapterMode === "stop" || settings.chapterMode === "continue") {
      els.chapterMode.value = settings.chapterMode;
    }
  }
}

function persistSettings() {
  writeJsonStorage(SETTINGS_STORAGE_KEY, {
    speed: scroller.speed,
    chapterMode: els.chapterMode.value,
  });
}

function loadResumeStore() {
  return loadJsonStorage(RESUME_STORAGE_KEY, {});
}

function saveResumeStore(store) {
  writeJsonStorage(RESUME_STORAGE_KEY, store);
}

function getResumeRecord(manuscriptId) {
  if (!manuscriptId) {
    return null;
  }
  const store = loadResumeStore();
  return store[manuscriptId] || null;
}

function setResumeRecord(manuscriptId, record) {
  if (!manuscriptId) {
    return;
  }
  const store = loadResumeStore();
  store[manuscriptId] = record;
  saveResumeStore(store);
}

function getChapterLabel(index, chapter) {
  return chapter?.title || `Chapter ${index + 1}`;
}

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

function getReadAheadGap() {
  return Math.max(180, Math.round(window.innerHeight * 0.2));
}

function maxScrollTop() {
  return Math.max(
    0,
    document.documentElement.scrollHeight - window.innerHeight,
  );
}

function estimateWordsPerMinute() {
  const scrollableHeight = maxScrollTop();
  if (scrollableHeight <= 0 || readingState.wordCount <= 0) {
    return 0;
  }
  const wordsPerPixel = readingState.wordCount / scrollableHeight;
  return Math.round(scroller.speed * wordsPerPixel * 60);
}

function getCurrentChapterIndex(scrollTop = window.scrollY) {
  if (!readingState.chapterMetrics.length) {
    return 0;
  }
  const probe = scrollTop + Math.round(window.innerHeight * 0.25);
  let currentIndex = 0;
  for (let index = 0; index < readingState.chapterMetrics.length; index += 1) {
    if (probe >= readingState.chapterMetrics[index].top) {
      currentIndex = index;
    } else {
      break;
    }
  }
  return currentIndex;
}

function formatChapterProgress() {
  if (!readingState.chapterMetrics.length) {
    const saved = readingState.resumeRecord;
    return saved ? `Saved ${formatDateTime(saved.saved_at)}` : "No chapters available";
  }
  const index = Math.min(getCurrentChapterIndex(), readingState.chapterMetrics.length - 1);
  const percent = maxScrollTop() > 0 ? Math.round((window.scrollY / maxScrollTop()) * 100) : 100;
  const saved = readingState.resumeRecord;
  const savedLabel = saved
    ? `Saved ${formatDateTime(saved.saved_at)} at ${saved.chapter_title || "chapter start"}`
    : "No reading position saved yet";
  return `Chapter ${index + 1} of ${readingState.chapterMetrics.length} • ${percent}% through document • ${savedLabel}`;
}

function renderScrollControls() {
  els.scrollToggle.textContent = scroller.running ? "Pause" : "Play";
  els.scrollToggle.setAttribute("aria-pressed", String(scroller.running));
  els.scrollSpeed.value = String(scroller.speed);
  const wpm = estimateWordsPerMinute();
  const modeLabel = els.chapterMode.value === "stop" ? "chapter stop" : "chapter continue";
  els.scrollStatus.textContent = `${scroller.running ? "Scrolling" : "Stopped"} at ${scroller.speed} px/s${wpm ? ` • ~${wpm} wpm` : ""} • ${modeLabel}`;
  els.resumeReading.disabled = !readingState.resumeRecord;
  els.readingProgress.textContent = formatChapterProgress();
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

function saveReadingPosition() {
  if (!readingState.manuscriptId) {
    return;
  }
  const chapterIndex = getCurrentChapterIndex();
  const chapter = readingState.chapterMetrics[chapterIndex];
  const record = {
    scroll_top: Math.round(window.scrollY),
    chapter_id: chapter?.id || null,
    chapter_title: chapter?.title || null,
    chapter_index: chapterIndex,
    saved_at: new Date().toISOString(),
  };
  readingState.resumeRecord = record;
  readingState.lastSavedScrollTop = record.scroll_top;
  readingState.lastSaveAt = Date.now();
  readingState.lastKnownChapterIndex = chapterIndex;
  setResumeRecord(readingState.manuscriptId, record);
  renderScrollControls();
}

function restoreReadingPosition(record, behavior = "auto") {
  if (!record) {
    return;
  }
  const top = Math.max(0, Number(record.scroll_top || 0));
  window.scrollTo({ top, behavior });
  readingState.lastSavedScrollTop = top;
  readingState.lastKnownChapterIndex = Number(record.chapter_index || 0);
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
  const currentTop = window.scrollY;
  const readAheadCeiling = Math.max(0, maxScrollTop() - getReadAheadGap());
  const currentChapterIndex = getCurrentChapterIndex(currentTop);
  const chapterMode = els.chapterMode.value || "continue";
  let nextTop = Math.min(currentTop + scroller.speed * elapsedSeconds, readAheadCeiling);
  if (chapterMode === "stop" && readingState.chapterMetrics[currentChapterIndex + 1]) {
    const nextChapterTop = readingState.chapterMetrics[currentChapterIndex + 1].top;
    if (nextTop >= nextChapterTop - 4) {
      window.scrollTo({ top: nextChapterTop, behavior: "auto" });
      saveReadingPosition();
      stopScrolling();
      return;
    }
  }
  window.scrollTo({ top: nextTop, behavior: "auto" });
  if (nextTop >= readAheadCeiling || nextTop >= maxScrollTop()) {
    saveReadingPosition();
    stopScrolling();
    return;
  }
  if (Date.now() - readingState.lastSaveAt > 400) {
    saveReadingPosition();
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
  persistSettings();
  renderScrollControls();
}

function updateChapterMetrics() {
  readingState.chapterMetrics = [...els.readerContent.querySelectorAll(".reader-chapter")].map((element, index) => {
    const rect = element.getBoundingClientRect();
    return {
      id: element.id,
      title: element.dataset.chapterTitle || getChapterLabel(index, null),
      top: Math.round(rect.top + window.scrollY),
      bottom: Math.round(rect.bottom + window.scrollY),
    };
  });
  renderScrollControls();
}

function renderDocument(document, report) {
  stopScrolling();
  els.readerTitle.textContent = document.title || "Untitled manuscript";
  readingState.manuscriptId = document.manuscript_id || null;
  readingState.wordCount = (document.chapters || []).reduce((total, chapter) => (
    total + (chapter.blocks || []).reduce((chapterTotal, block) => chapterTotal + String(block.text || "").trim().split(/\s+/).filter(Boolean).length, 0)
  ), 0);
  readingState.resumeRecord = getResumeRecord(readingState.manuscriptId);
  els.chapterSelect.innerHTML = (document.chapters || []).map((chapter, index) => (
    `<option value="${escapeHtml(chapter.id)}">${escapeHtml(getChapterLabel(index, chapter))}</option>`
  )).join("");
  els.chapterSelect.disabled = !(document.chapters || []).length;
  els.chapterMode.value = els.chapterMode.value || "continue";
  els.readerContent.innerHTML = (document.chapters || []).map((chapter) => `
    <section class="reader-chapter" id="${escapeHtml(chapter.id)}" data-chapter-title="${escapeHtml(chapter.title || "")}">
      ${(chapter.blocks || []).map((block) => {
        const tag = block.type === "heading" ? "h3" : "p";
        return `<${tag} class="reader-block">${renderTextWithSpans(block)}</${tag}>`;
      }).join("")}
    </section>
  `).join("");
  renderLegend(document);
  renderMappingWarning(report || document.metadata?.highlight_report);
  els.resumeReading.disabled = !readingState.resumeRecord;
  els.chapterSelect.value = readingState.resumeRecord?.chapter_id || document.chapters?.[0]?.id || "";
  requestAnimationFrame(() => {
    updateChapterMetrics();
    if (readingState.resumeRecord) {
      restoreReadingPosition(readingState.resumeRecord);
      els.documentStatus.textContent = `Loaded ${document.title || "Untitled manuscript"} and restored the last reading position.`;
    } else {
      els.documentStatus.textContent = `Loaded ${document.title || "Untitled manuscript"}`;
    }
  });
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

function handleViewportScroll() {
  if (!readingState.manuscriptId) {
    return;
  }
  if (Date.now() - readingState.lastSaveAt > 350) {
    saveReadingPosition();
  }
  renderScrollControls();
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
    requestAnimationFrame(() => saveReadingPosition());
  }
});

els.chapterMode.addEventListener("change", () => {
  persistSettings();
  renderScrollControls();
});

els.resumeReading.addEventListener("click", () => {
  stopScrolling();
  if (readingState.resumeRecord) {
    restoreReadingPosition(readingState.resumeRecord, "smooth");
  }
});

els.scrollToggle.addEventListener("click", toggleScrolling);
els.scrollSpeed.addEventListener("input", () => setScrollSpeed(els.scrollSpeed.value));
els.scrollSlower.addEventListener("click", () => setScrollSpeed(scroller.speed - 5));
els.scrollFaster.addEventListener("click", () => setScrollSpeed(scroller.speed + 5));

window.addEventListener("scroll", handleViewportScroll, { passive: true });
window.addEventListener("resize", () => {
  updateChapterMetrics();
  renderScrollControls();
});
window.addEventListener("beforeunload", saveReadingPosition);

loadSettings();
persistSettings();

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
