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
      <button type="button" data-run-stage="${stage.name}">Run ${stageLabels[stage.name] || stage.name}</button>
    `;
    card.querySelector("button").addEventListener("click", () => triggerPipeline(stage.name));
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
