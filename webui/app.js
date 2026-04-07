const storageKey = "manuscriptprep.apiToken";
const autoRefreshMs = 3000;
const stageOrder = ["ingest", "orchestrate", "merge", "resolve", "report"];
const stageLabels = {
  ingest: "Ingest",
  orchestrate: "Categorisation And Analysis",
  merge: "Merge",
  resolve: "Resolution",
  report: "Report",
};

const state = {
  token: localStorage.getItem(storageKey) || "",
  pipelines: [],
  manuscripts: [],
  configProfiles: [],
  jobs: [],
  selectedManuscriptId: null,
  selectedConfigProfileId: null,
  selectedJobId: null,
  artifactViewer: {
    jobId: null,
    tab: "classification",
  },
};

const els = {
  authForm: document.getElementById("auth-form"),
  apiToken: document.getElementById("api-token"),
  authStatus: document.getElementById("auth-status"),
  uploadForm: document.getElementById("upload-form"),
  uploadStatus: document.getElementById("upload-status"),
  manuscriptTitle: document.getElementById("manuscript-title"),
  manuscriptSlug: document.getElementById("manuscript-slug"),
  manuscriptFile: document.getElementById("manuscript-file"),
  configProfileSelect: document.getElementById("config-profile-select"),
  configProfileDetail: document.getElementById("config-profile-detail"),
  manuscriptList: document.getElementById("manuscript-list"),
  manuscriptDetail: document.getElementById("manuscript-detail"),
  pipelineOverview: document.getElementById("pipeline-overview"),
  stageBoard: document.getElementById("stage-board"),
  stageActionStatus: document.getElementById("stage-action-status"),
  systemStatus: document.getElementById("system-status"),
  jobList: document.getElementById("job-list"),
  jobDetail: document.getElementById("job-detail"),
  jobArtifacts: document.getElementById("job-artifacts"),
  runFullPipeline: document.getElementById("run-full-pipeline"),
  artifactViewer: document.getElementById("artifact-viewer"),
  artifactViewerTitle: document.getElementById("artifact-viewer-title"),
  artifactViewerStatus: document.getElementById("artifact-viewer-status"),
  artifactViewerSummary: document.getElementById("artifact-viewer-summary"),
  artifactViewerPanels: document.getElementById("artifact-viewer-panels"),
  artifactViewerClose: document.getElementById("artifact-viewer-close"),
};

function currentHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  return headers;
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: currentHeaders() });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed for ${path}`);
  }
  return payload;
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: currentHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed for ${path}`);
  }
  return data;
}

async function postBinary(path, filename, file) {
  const response = await fetch(path, {
    method: "POST",
    headers: currentHeaders({ "Content-Type": file.type || "application/pdf", "X-Filename": filename }),
    body: file,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed for ${path}`);
  }
  return data;
}

function selectedManuscript() {
  return state.manuscripts.find((item) => item.manuscript_id === state.selectedManuscriptId) || null;
}

function selectedConfigProfile() {
  return state.configProfiles.find((item) => item.config_profile_id === state.selectedConfigProfileId) || null;
}

function selectedJob() {
  return state.jobs.find((item) => item.job_id === state.selectedJobId) || null;
}

function latestJobForPipeline(pipeline) {
  return state.jobs.find((job) => job.pipeline === pipeline) || null;
}

function prettyLabel(value) {
  return String(value || "n/a")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function truncateText(value, maxLength = 5000) {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength)}\n\n... truncated ...`;
}

function setArtifactTab(tab) {
  state.artifactViewer.tab = tab;
  for (const button of document.querySelectorAll("[data-artifact-tab]")) {
    button.classList.toggle("active", button.getAttribute("data-artifact-tab") === tab);
  }
  for (const panel of els.artifactViewerPanels.querySelectorAll(".artifact-panel")) {
    panel.classList.toggle("active", panel.getAttribute("data-artifact-panel") === tab);
  }
}

function ingestSummaryCards(ingestManifest = {}, chunkManifest = {}) {
  const extraction = ingestManifest.extraction || {};
  const cleaning = ingestManifest.cleaning || {};
  const chunking = chunkManifest.summary || {};
  const classification = ingestManifest.classification || {};
  return [
    {
      title: "Classification",
      body: classification.mode || classification.pdf_type || classification.type || "Unknown",
    },
    {
      title: "Pages",
      body: extraction.page_count || ingestManifest.page_count || "n/a",
    },
    {
      title: "Clean Words",
      body: cleaning.word_count || chunking.total_words || "n/a",
    },
    {
      title: "Chunks",
      body: chunking.chunk_count || (Array.isArray(chunkManifest.chunks) ? chunkManifest.chunks.length : "n/a"),
    },
  ];
}

function renderArtifactSummary(cards) {
  els.artifactViewerSummary.innerHTML = "";
  for (const card of cards) {
    const article = document.createElement("article");
    article.className = "artifact-card";
    article.innerHTML = `
      <p class="eyebrow">${card.title}</p>
      <h3>${card.body}</h3>
    `;
    els.artifactViewerSummary.appendChild(article);
  }
}

function renderArtifactPanels({ ingestManifest, rawText, cleanText, chunkManifest }) {
  const classification = ingestManifest.classification || ingestManifest.pdf_analysis || ingestManifest;
  const extraction = ingestManifest.extraction || ingestManifest.text_extraction || {};
  const cleaning = ingestManifest.cleaning || {};
  const chunks = Array.isArray(chunkManifest.chunks) ? chunkManifest.chunks : [];
  const chunkLines = chunks.slice(0, 20).map((chunk) => {
    const label = chunk.chunk_id || chunk.id || "chunk";
    const words = chunk.word_count || chunk.words || "n/a";
    const title = chunk.title || chunk.heading || "";
    return `${label} | ${words} words${title ? ` | ${title}` : ""}`;
  });
  els.artifactViewerPanels.innerHTML = "";

  const panelDefinitions = [
    {
      tab: "classification",
      title: "Classification",
      description: "How the PDF was classified before extraction and chunking.",
      blocks: [JSON.stringify(classification, null, 2)],
    },
    {
      tab: "extract",
      title: "Extract",
      description: "Extraction metadata and a preview of the raw text pulled from the PDF.",
      blocks: [JSON.stringify(extraction, null, 2), truncateText(rawText)],
    },
    {
      tab: "clean",
      title: "Clean",
      description: "Normalization and cleaning output before orchestration.",
      blocks: [JSON.stringify(cleaning, null, 2), truncateText(cleanText)],
    },
    {
      tab: "chunking",
      title: "Chunking",
      description: "Chunk manifest summary and the first chunk records from ingest.",
      blocks: [JSON.stringify(chunkManifest.summary || {}, null, 2), JSON.stringify(chunks.slice(0, 10), null, 2)],
      chunkLines,
    },
  ];

  for (const definition of panelDefinitions) {
    const section = document.createElement("section");
    section.className = "artifact-panel";
    section.setAttribute("data-artifact-panel", definition.tab);

    const heading = document.createElement("h3");
    heading.textContent = definition.title;
    section.appendChild(heading);

    const description = document.createElement("p");
    description.className = "meta";
    description.textContent = definition.description;
    section.appendChild(description);

    if (definition.chunkLines) {
      const chunkCard = document.createElement("div");
      chunkCard.className = "artifact-card";
      const chunkHeading = document.createElement("h3");
      chunkHeading.textContent = "Chunk Index";
      chunkCard.appendChild(chunkHeading);
      const chunkList = document.createElement("ol");
      chunkList.className = "artifact-list";
      if (definition.chunkLines.length) {
        for (const line of definition.chunkLines) {
          const item = document.createElement("li");
          item.textContent = line;
          chunkList.appendChild(item);
        }
      } else {
        const item = document.createElement("li");
        item.textContent = "No chunks found";
        chunkList.appendChild(item);
      }
      chunkCard.appendChild(chunkList);
      section.appendChild(chunkCard);
    }

    for (const block of definition.blocks) {
      const pre = document.createElement("pre");
      pre.textContent = block;
      section.appendChild(pre);
    }

    els.artifactViewerPanels.appendChild(section);
  }
  setArtifactTab(state.artifactViewer.tab);
}

async function openIngestViewer(jobId) {
  try {
    state.artifactViewer.jobId = jobId;
    els.artifactViewerTitle.textContent = "Ingest Results";
    els.artifactViewerStatus.textContent = "Loading classification, extract, clean, and chunking results...";
    els.artifactViewerSummary.innerHTML = "";
    els.artifactViewerPanels.innerHTML = "";
    els.artifactViewer.showModal();
    const names = ["ingest_manifest", "raw_text", "clean_text", "chunk_manifest"];
    const [job, ...artifactPayloads] = await Promise.all([
      fetchJson(`/v1/jobs/${jobId}`),
      ...names.map((name) => fetchJson(`/v1/jobs/${jobId}/artifacts/${name}`)),
    ]);
    const byName = Object.fromEntries(artifactPayloads.map((payload) => [payload.artifact.name, payload]));
    const ingestManifest = byName.ingest_manifest?.content || {};
    const chunkManifest = byName.chunk_manifest?.content || {};
    const rawText = byName.raw_text?.preview || "";
    const cleanText = byName.clean_text?.preview || "";
    els.artifactViewerTitle.textContent = `${job.title || job.book_slug || "Ingest"} Results`;
    els.artifactViewerStatus.textContent = `Showing ingest outputs for job ${job.job_id}.`;
    renderArtifactSummary(ingestSummaryCards(ingestManifest, chunkManifest));
    renderArtifactPanels({ ingestManifest, rawText, cleanText, chunkManifest });
  } catch (error) {
    els.artifactViewerStatus.textContent = error.message;
    els.artifactViewerPanels.innerHTML = "";
    const section = document.createElement("section");
    section.className = "artifact-panel active";
    section.setAttribute("data-artifact-panel", "classification");
    const pre = document.createElement("pre");
    pre.textContent = error.message;
    section.appendChild(pre);
    els.artifactViewerPanels.appendChild(section);
  }
}

function resolveModelRefs(stage) {
  const profile = selectedConfigProfile();
  const models = (profile && profile.metadata && profile.metadata.models) || {};
  return (stage.metadata.models || []).map((ref) => {
    const key = ref.split(".").pop();
    return models[key] ? `${key}: ${models[key]}` : ref;
  });
}

function formatDate(value) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

function renderConfigProfiles() {
  els.configProfileSelect.innerHTML = "";
  for (const profile of state.configProfiles) {
    const option = document.createElement("option");
    option.value = profile.config_profile_id;
    option.textContent = `${profile.name}@${profile.version}`;
    option.selected = profile.config_profile_id === state.selectedConfigProfileId;
    els.configProfileSelect.appendChild(option);
  }
  if (!state.selectedConfigProfileId && state.configProfiles.length) {
    state.selectedConfigProfileId = state.configProfiles[0].config_profile_id;
    els.configProfileSelect.value = state.selectedConfigProfileId;
  }
  const profile = selectedConfigProfile();
  if (!profile) {
    els.configProfileDetail.textContent = "No config profile selected.";
    return;
  }
  els.configProfileDetail.textContent = JSON.stringify(profile, null, 2);
}

function renderManuscripts() {
  els.manuscriptList.innerHTML = "";
  if (!state.manuscripts.length) {
    els.manuscriptList.innerHTML = '<li class="muted">No manuscripts yet</li>';
    els.manuscriptDetail.textContent = "Upload and register a manuscript to begin.";
    return;
  }
  for (const manuscript of state.manuscripts) {
    const li = document.createElement("li");
    li.className = manuscript.manuscript_id === state.selectedManuscriptId ? "selected" : "";
    li.textContent = `${manuscript.title} | ${manuscript.book_slug} | ${manuscript.file_size_bytes || 0} bytes`;
    li.addEventListener("click", async () => {
      state.selectedManuscriptId = manuscript.manuscript_id;
      state.selectedJobId = null;
      renderManuscripts();
      await refreshJobs();
      renderStageBoard();
    });
    els.manuscriptList.appendChild(li);
  }
  const manuscript = selectedManuscript();
  els.manuscriptDetail.textContent = manuscript
    ? JSON.stringify(manuscript, null, 2)
    : "Select a manuscript to see pipeline-ready details.";
}

function renderPipelineOverview() {
  els.pipelineOverview.innerHTML = "";
  const fullPipeline = state.pipelines.find((item) => item.pipeline === "manuscript-prep");
  if (!fullPipeline) {
    els.pipelineOverview.textContent = "Pipeline metadata unavailable.";
    return;
  }
  for (const stage of fullPipeline.stages) {
    const card = document.createElement("article");
    card.className = "stage-summary";
    const models = resolveModelRefs(stage);
    card.innerHTML = `
      <h3>${stageLabels[stage.name] || stage.name}</h3>
      <p>${stage.description}</p>
      <p class="meta">Substeps: ${(stage.metadata.substeps || []).join(", ") || "n/a"}</p>
      <p class="meta">Models: ${models.length ? models.join(", ") : "Deterministic stage"}</p>
    `;
    els.pipelineOverview.appendChild(card);
  }
}

async function triggerPipeline(pipeline) {
  const manuscript = selectedManuscript();
  const profile = selectedConfigProfile();
  if (!manuscript) {
    els.stageActionStatus.textContent = "Select a manuscript first.";
    return;
  }
  if (!profile) {
    els.stageActionStatus.textContent = "Select a config profile first.";
    return;
  }
  try {
    const created = await postJson("/v1/jobs", {
      pipeline,
      manuscript_id: manuscript.manuscript_id,
      config_profile_id: profile.config_profile_id,
    });
    await postJson(`/v1/jobs/${created.job_id}/run`, {});
    state.selectedJobId = created.job_id;
    els.stageActionStatus.textContent = `${pipeline} job queued: ${created.job_id}`;
    await refreshJobs();
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
}

function renderStageBoard() {
  els.stageBoard.innerHTML = "";
  const fullPipeline = state.pipelines.find((item) => item.pipeline === "manuscript-prep");
  if (!fullPipeline) {
    return;
  }
  for (const stage of fullPipeline.stages) {
    const latestJob = latestJobForPipeline(stage.name);
    const stageStatus = latestJob ? latestJob.status : "not-started";
    const models = resolveModelRefs(stage);
    const card = document.createElement("article");
    card.className = `stage-card status-${stageStatus}`;
    card.innerHTML = `
      <div class="stage-card-head">
        <div>
          <p class="eyebrow">${stage.kind}</p>
          <h3>${stageLabels[stage.name] || stage.name}</h3>
        </div>
        <span class="status-pill">${stageStatus}</span>
      </div>
      <p>${stage.description}</p>
      <p class="meta"><strong>Substeps:</strong> ${(stage.metadata.substeps || []).join(", ") || "n/a"}</p>
      <p class="meta"><strong>Models:</strong> ${models.length ? models.join(", ") : "Deterministic stage"}</p>
      <p class="meta"><strong>Last update:</strong> ${latestJob ? formatDate(latestJob.updated_at) : "n/a"}</p>
      <div class="stage-card-actions">
        <button type="button" data-run-stage="${stage.name}">Run ${stageLabels[stage.name] || stage.name}</button>
      </div>
    `;
    card.querySelector("button").addEventListener("click", () => triggerPipeline(stage.name));
    if (stage.name === "ingest" && latestJob && latestJob.status === "succeeded") {
      const viewButton = document.createElement("button");
      viewButton.type = "button";
      viewButton.className = "secondary-button";
      viewButton.textContent = "View Ingest Results";
      viewButton.addEventListener("click", () => openIngestViewer(latestJob.job_id));
      card.querySelector(".stage-card-actions").appendChild(viewButton);
    }
    els.stageBoard.appendChild(card);
  }
}

function renderJobs() {
  els.jobList.innerHTML = "";
  if (!state.jobs.length) {
    els.jobList.innerHTML = '<li class="muted">No jobs for the selected manuscript yet</li>';
    els.jobDetail.textContent = "Run a stage to generate job details.";
    els.jobArtifacts.textContent = "Artifact index will appear after a stage produces output.";
    return;
  }
  for (const job of state.jobs) {
    const li = document.createElement("li");
    li.className = job.job_id === state.selectedJobId ? "selected" : "";
    li.textContent = `${job.pipeline} | ${job.status} | ${formatDate(job.updated_at)}`;
    li.addEventListener("click", async () => {
      state.selectedJobId = job.job_id;
      renderJobs();
      await refreshSelectedJob();
    });
    els.jobList.appendChild(li);
  }
}

async function refreshSelectedJob() {
  const job = selectedJob();
  if (!job) {
    return;
  }
  try {
    const [freshJob, artifacts] = await Promise.all([
      fetchJson(`/v1/jobs/${job.job_id}`),
      fetchJson(`/v1/jobs/${job.job_id}/artifacts`),
    ]);
    els.jobDetail.textContent = JSON.stringify(freshJob, null, 2);
    els.jobArtifacts.textContent = JSON.stringify(artifacts, null, 2);
    if (freshJob.pipeline === "ingest" && freshJob.status === "succeeded") {
      const viewLine = "\n\n[UI] Use the \"View Ingest Results\" button in the ingest stage card to inspect classification, extract, clean, and chunking.";
      els.jobArtifacts.textContent += viewLine;
    }
  } catch (error) {
    els.jobDetail.textContent = error.message;
    els.jobArtifacts.textContent = error.message;
  }
}

async function refreshSystem() {
  try {
    const payload = await fetchJson("/v1/system/status");
    els.systemStatus.textContent = JSON.stringify(payload, null, 2);
    els.authStatus.textContent = "Connected";
  } catch (error) {
    els.systemStatus.textContent = error.message;
    els.authStatus.textContent = error.message;
  }
}

async function refreshPipelines() {
  const payload = await fetchJson("/v1/pipelines");
  state.pipelines = payload.pipelines;
  renderPipelineOverview();
  renderStageBoard();
}

async function refreshConfigProfiles() {
  const payload = await fetchJson("/v1/config-profiles");
  state.configProfiles = payload.config_profiles;
  renderConfigProfiles();
  renderPipelineOverview();
  renderStageBoard();
}

async function refreshManuscripts() {
  const payload = await fetchJson("/v1/manuscripts");
  state.manuscripts = payload.manuscripts;
  if (!state.selectedManuscriptId && state.manuscripts.length) {
    state.selectedManuscriptId = state.manuscripts[0].manuscript_id;
  }
  renderManuscripts();
}

async function refreshJobs() {
  const manuscript = selectedManuscript();
  if (!manuscript) {
    state.jobs = [];
    renderJobs();
    return;
  }
  const payload = await fetchJson(`/v1/jobs?manuscript_id=${encodeURIComponent(manuscript.manuscript_id)}`);
  state.jobs = payload.jobs;
  if (!state.selectedJobId && state.jobs.length) {
    state.selectedJobId = state.jobs[0].job_id;
  }
  renderJobs();
  renderStageBoard();
  await refreshSelectedJob();
}

async function refreshAll() {
  try {
    await Promise.all([refreshSystem(), refreshConfigProfiles(), refreshManuscripts(), refreshPipelines()]);
    await refreshJobs();
  } catch (error) {
    els.authStatus.textContent = error.message;
  }
}

els.apiToken.value = state.token;
els.authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = els.apiToken.value.trim();
  localStorage.setItem(storageKey, state.token);
  await refreshAll();
});

els.configProfileSelect.addEventListener("change", () => {
  state.selectedConfigProfileId = els.configProfileSelect.value;
  renderConfigProfiles();
  renderPipelineOverview();
  renderStageBoard();
});

els.uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = els.manuscriptTitle.value.trim();
  const slug = els.manuscriptSlug.value.trim();
  const file = els.manuscriptFile.files[0];
  if (!title || !file) {
    els.uploadStatus.textContent = "Title and PDF file are required.";
    return;
  }
  try {
    els.uploadStatus.textContent = "Uploading manuscript...";
    const upload = await postBinary("/v1/uploads/manuscripts", file.name, file);
    els.uploadStatus.textContent = "Registering manuscript...";
    const manuscript = await postJson("/v1/manuscripts", {
      title,
      book_slug: slug || upload.book_slug_guess,
      source_path: upload.path,
      file_size_bytes: upload.size_bytes,
    });
    state.selectedManuscriptId = manuscript.manuscript_id;
    els.uploadStatus.textContent = `Manuscript registered: ${manuscript.title}`;
    els.uploadForm.reset();
    await refreshManuscripts();
    await refreshJobs();
  } catch (error) {
    els.uploadStatus.textContent = error.message;
  }
});

els.runFullPipeline.addEventListener("click", () => triggerPipeline("manuscript-prep"));
els.artifactViewerClose.addEventListener("click", () => els.artifactViewer.close());
els.artifactViewer.addEventListener("click", (event) => {
  if (event.target === els.artifactViewer) {
    els.artifactViewer.close();
  }
});
for (const button of document.querySelectorAll("[data-artifact-tab]")) {
  button.addEventListener("click", () => setArtifactTab(button.getAttribute("data-artifact-tab")));
}

for (const button of document.querySelectorAll("[data-refresh]")) {
  button.addEventListener("click", async () => {
    const target = button.getAttribute("data-refresh");
    if (target === "system") await refreshSystem();
    if (target === "pipelines") await refreshPipelines();
    if (target === "manuscripts" || target === "upload-context" || target === "selected-manuscript") await refreshManuscripts();
    if (target === "config-profiles") await refreshConfigProfiles();
    if (target === "jobs" || target === "selected-job") await refreshJobs();
  });
}

setInterval(() => {
  if (state.token) {
    refreshSystem();
    refreshJobs();
  }
}, autoRefreshMs);

refreshAll();
