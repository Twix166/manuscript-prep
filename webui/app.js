const storageKey = "manuscriptprep.apiToken";
const autoRefreshMs = 3000;
const ingestResultsCachePrefix = "manuscriptprep.ingestResults.";
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
  jobProgressById: {},
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
  selectedManuscriptTitle: document.getElementById("selected-manuscript-title"),
  selectedManuscriptSlug: document.getElementById("selected-manuscript-slug"),
  saveManuscript: document.getElementById("save-manuscript"),
  openIngestResults: document.getElementById("open-ingest-results"),
  deleteManuscript: document.getElementById("delete-manuscript"),
  pipelineOverview: document.getElementById("pipeline-overview"),
  stageBoard: document.getElementById("stage-board"),
  stageActionStatus: document.getElementById("stage-action-status"),
  systemStatus: document.getElementById("system-status"),
  jobList: document.getElementById("job-list"),
  jobDetail: document.getElementById("job-detail"),
  jobProgress: document.getElementById("job-progress"),
  jobArtifacts: document.getElementById("job-artifacts"),
  jobDownloads: document.getElementById("job-downloads"),
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

async function sendJson(method, path, payload = null) {
  const response = await fetch(path, {
    method,
    headers: currentHeaders({ "Content-Type": "application/json" }),
    body: payload ? JSON.stringify(payload) : null,
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

async function downloadJobArtifact(jobId, artifactName) {
  const response = await fetch(`/v1/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactName)}/download`, {
    headers: currentHeaders(),
  });
  if (!response.ok) {
    let message = `Download failed for ${artifactName}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      // fall back
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

function artifactButtonLabel(name) {
  const labels = {
    orchestrator_log: "Download Orchestrator Log",
    book_merged: "Download Merged Book",
    merge_report: "Download Merge Report",
    conflict_report: "Download Conflict Report",
    book_resolved: "Download Resolved Book",
    resolution_map: "Download Resolution Map",
    resolution_report: "Download Resolution Report",
    report_pdf: "Download Report PDF",
    ingest_stdout: "Download Ingest Stdout",
    orchestrate_stdout: "Download Orchestrate Stdout",
    merge_stdout: "Download Merge Stdout",
    resolve_stdout: "Download Resolve Stdout",
    report_stdout: "Download Report Stdout",
  };
  return labels[name] || `Download ${name.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase())}`;
}

function renderJobDownloads(job, artifactIndex) {
  els.jobDownloads.innerHTML = "";
  const downloadable = artifactIndex.artifacts.filter((artifact) => {
    const kind = artifact.kind || "";
    const exists = artifact.metadata?.exists;
    return exists !== false && !["directory"].includes(kind);
  });
  const preferredOrder = [
    "book_merged",
    "merge_report",
    "conflict_report",
    "book_resolved",
    "resolution_map",
    "resolution_report",
    "report_pdf",
    "orchestrator_log",
  ];
  downloadable.sort((left, right) => {
    const leftIndex = preferredOrder.indexOf(left.name);
    const rightIndex = preferredOrder.indexOf(right.name);
    if (leftIndex === -1 && rightIndex === -1) return left.name.localeCompare(right.name);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
  for (const artifact of downloadable) {
    if (job.pipeline === "ingest" && ["raw_text", "clean_text", "chunk_manifest", "ingest_manifest"].includes(artifact.name)) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button";
    button.textContent = artifactButtonLabel(artifact.name);
    button.addEventListener("click", async () => {
      try {
        await downloadJobArtifact(job.job_id, artifact.name);
      } catch (error) {
        els.stageActionStatus.textContent = error.message;
      }
    });
    els.jobDownloads.appendChild(button);
  }
  if (!els.jobDownloads.children.length) {
    const muted = document.createElement("span");
    muted.className = "muted";
    muted.textContent = "No downloadable artifacts for the selected job yet.";
    els.jobDownloads.appendChild(muted);
  }
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

function latestIngestForSelectedManuscript() {
  const manuscript = selectedManuscript();
  return manuscript ? manuscript.latest_ingest || null : null;
}

function formatDate(value) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "n/a";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatList(items) {
  return Array.isArray(items) && items.length ? items.join(", ") : "n/a";
}

function stageSummaryLines(stageRuns) {
  return (stageRuns || []).map((stage) => {
    const finished = stage.finished_at ? ` | finished ${formatDate(stage.finished_at)}` : "";
    const error = stage.error ? ` | error: ${stage.error}` : "";
    return `- ${stageLabels[stage.name] || stage.name}: ${stage.status}${finished}${error}`;
  });
}

function renderConfigProfileSummary(profile) {
  if (!profile) {
    return "No config profile selected.";
  }
  const metadata = profile.metadata || {};
  const models = metadata.models || {};
  const chunking = metadata.chunking || {};
  const timeouts = metadata.timeouts || {};
  const paths = metadata.paths || {};
  return [
    `${profile.name}@${profile.version}`,
    "",
    `Models`,
    `- Structure: ${models.structure || "n/a"}`,
    `- Dialogue: ${models.dialogue || "n/a"}`,
    `- Entities: ${models.entities || "n/a"}`,
    `- Dossiers: ${models.dossiers || "n/a"}`,
    `- Resolver: ${models.resolver || "n/a"}`,
    "",
    `Chunking`,
    `- Target words: ${chunking.target_words || "n/a"}`,
    `- Min words: ${chunking.min_words || "n/a"}`,
    `- Max words: ${chunking.max_words || "n/a"}`,
    "",
    `Timeouts`,
    `- Idle: ${timeouts.idle_seconds || "n/a"} s`,
    `- Hard: ${timeouts.hard_seconds || "n/a"} s`,
    `- Retries: ${timeouts.retries || 0}`,
    "",
    `Workspace`,
    `- Root: ${paths.workspace_root || "n/a"}`,
    `- Output: ${paths.output_root || "n/a"}`,
    `- Reports: ${paths.reports_root || "n/a"}`,
  ].join("\n");
}

function renderManuscriptSummary(manuscript) {
  if (!manuscript) {
    return "Select a manuscript to see pipeline-ready details.";
  }
  const latestIngest = manuscript.latest_ingest;
  return [
    `${manuscript.title}`,
    "",
    `Slug: ${manuscript.book_slug}`,
    `Size: ${formatBytes(manuscript.file_size_bytes)}`,
    `Created: ${formatDate(manuscript.created_at)}`,
    `Updated: ${formatDate(manuscript.updated_at)}`,
    `Source file: ${manuscript.source_path}`,
    "",
    `Latest ingest`,
    latestIngest
      ? `- Status: ${latestIngest.status}
- Started: ${formatDate(latestIngest.started_at)}
- Finished: ${formatDate(latestIngest.finished_at)}
- Job: ${latestIngest.job_id}${latestIngest.error ? `\n- Error: ${latestIngest.error}` : ""}`
      : "- Not run yet",
  ].join("\n");
}

function renderSystemSummary(payload) {
  const queue = payload.queue || {};
  const workers = payload.workers || [];
  const workerLines = workers.length
    ? workers.map((worker) => `- ${worker.worker_id}: ${worker.status} | heartbeat ${formatDate(worker.heartbeat_at)}${worker.last_job_id ? ` | last job ${worker.last_job_id}` : ""}`)
    : ["- No workers reporting yet"];
  return [
    `Gateway`,
    `- Store backend: ${payload.store_backend || "n/a"}`,
    `- Ready: ${payload.ready ? "yes" : "no"}`,
    `- Updated: ${formatDate(payload.timestamp)}`,
    "",
    `Queue`,
    `- Queued: ${queue.queued || 0}`,
    `- Running: ${queue.running || 0}`,
    `- Succeeded: ${queue.succeeded || 0}`,
    `- Failed: ${queue.failed || 0}`,
    `- Cancelled: ${queue.cancelled || 0}`,
    `- Total: ${queue.total || 0}`,
    "",
    `Workers`,
    ...workerLines,
  ].join("\n");
}

function renderJobSummary(job) {
  const stageLines = stageSummaryLines(job.stage_runs);
  const command = job.stage_runs?.find((stage) => stage.command && stage.command.length)?.command?.join(" ");
  return [
    `${stageLabels[job.pipeline] || job.pipeline} Job`,
    "",
    `Status: ${job.status}`,
    `Book: ${job.title || job.book_slug || "n/a"}`,
    `Created: ${formatDate(job.created_at)}`,
    `Updated: ${formatDate(job.updated_at)}`,
    `Config profile: ${job.config_profile_id || "n/a"}`,
    command ? `Command: ${command}` : "Command: n/a",
    "",
    `Stages`,
    ...(stageLines.length ? stageLines : ["- No stage data yet"]),
  ].join("\n");
}

function renderJobProgressSummary(progress) {
  if (!progress || progress.available === false) {
    return progress?.message || "Live chunk progress appears here for categorisation and analysis jobs.";
  }

  const currentChunk = progress.current_chunk
    ? `${progress.current_chunk} (${progress.current_chunk_index || "?"} of ${progress.chunks_total || "?"})`
    : progress.chunks_total
      ? `${progress.chunks_completed || 0} of ${progress.chunks_total} chunks completed`
      : "Waiting for the first chunk";
  const currentPass = progress.current_pass
    ? `${progress.current_pass} (${progress.current_pass_index || "?"} of 4)`
    : "Waiting for the first pass";
  const throughput = progress.reported_tps || progress.estimated_tps;
  const recentEvents = Array.isArray(progress.recent_events) && progress.recent_events.length
    ? progress.recent_events.slice(-5).map((event) => (
      `- ${formatDate(event.timestamp)} | ${event.chunk || "-"} | ${event.pass || "-"} | ${event.message || event.event_type || "-"}`
    ))
    : ["- No progress events yet"];

  return [
    `Live Chunk Progress`,
    "",
    `Chunk`,
    `- Current: ${currentChunk}`,
    `- Completed: ${progress.chunks_completed || 0}`,
    `- Failed: ${progress.chunks_failed || 0}`,
    `- Overall progress: ${progress.chunk_percent ?? 0}%`,
    "",
    `Pass`,
    `- Current: ${currentPass}`,
    `- Step: ${progress.current_step || "n/a"}`,
    `- Model: ${progress.current_model || "n/a"}`,
    `- Attempt: ${progress.current_attempt || "n/a"}`,
    `- Throughput: ${throughput ? `${throughput} tok/s` : "n/a"}`,
    `- Idle timeout: ${progress.current_idle_timeout_s || "n/a"} s`,
    `- Idle backoffs: ${progress.idle_backoffs || 0}`,
    "",
    `Recent events`,
    ...recentEvents,
  ].join("\n");
}

function renderCompactStageProgress(progress) {
  if (!progress || progress.available === false || !progress.current_chunk) {
    return "";
  }
  return `Chunk ${progress.current_chunk_index || "?"}/${progress.chunks_total || "?"}: ${progress.current_chunk} | Pass ${progress.current_pass_index || "?"}/4: ${progress.current_pass || "starting"} | ${progress.current_step || "working"}`;
}

function renderArtifactSummary(artifactIndex) {
  const artifacts = artifactIndex.artifacts || [];
  if (!artifacts.length) {
    return "No artifacts for this job yet.";
  }
  return artifacts.map((artifact) => {
    const bytes = artifact.metadata?.bytes ? ` | ${formatBytes(artifact.metadata.bytes)}` : "";
    const exists = artifact.metadata?.exists === false ? "missing" : "ready";
    return `- ${artifact.name} (${artifact.stage || "job"} | ${artifact.kind} | ${exists}${bytes})`;
  }).join("\n");
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
  els.configProfileDetail.textContent = renderConfigProfileSummary(profile);
}

function renderManuscripts() {
  els.manuscriptList.innerHTML = "";
  if (!state.manuscripts.length) {
    els.manuscriptList.innerHTML = '<li class="muted">No manuscripts yet</li>';
    els.manuscriptDetail.textContent = "Upload and register a manuscript to begin.";
    els.selectedManuscriptTitle.value = "";
    els.selectedManuscriptSlug.value = "";
    return;
  }
  for (const manuscript of state.manuscripts) {
    const latestIngest = manuscript.latest_ingest;
    const li = document.createElement("li");
    li.className = manuscript.manuscript_id === state.selectedManuscriptId ? "selected" : "";
    li.innerHTML = `
      <strong>${manuscript.title}</strong>
      <span>${manuscript.book_slug}</span><br>
      <span class="meta">Ingest: ${latestIngest ? `${latestIngest.status} at ${formatDate(latestIngest.finished_at || latestIngest.updated_at)}` : "not run yet"}</span>
    `;
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
  if (!manuscript) {
    els.manuscriptDetail.textContent = "Select a manuscript to see pipeline-ready details.";
    return;
  }
  els.selectedManuscriptTitle.value = manuscript.title;
  els.selectedManuscriptSlug.value = manuscript.book_slug;
  els.manuscriptDetail.textContent = renderManuscriptSummary(manuscript);
}

function resolveModelRefs(stage) {
  const profile = selectedConfigProfile();
  const models = (profile && profile.metadata && profile.metadata.models) || {};
  return (stage.metadata.models || []).map((ref) => {
    const key = ref.split(".").pop();
    return models[key] ? `${key}: ${models[key]}` : ref;
  });
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
    const created = await sendJson("POST", "/v1/jobs", {
      pipeline,
      manuscript_id: manuscript.manuscript_id,
      config_profile_id: profile.config_profile_id,
    });
    await sendJson("POST", `/v1/jobs/${created.job_id}/run`, {});
    state.selectedJobId = created.job_id;
    els.stageActionStatus.textContent = `${pipeline} job queued: ${created.job_id}`;
    await refreshJobs();
    await refreshManuscripts();
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
}

async function openLatestIngestResults() {
  const manuscript = selectedManuscript();
  if (!manuscript || !manuscript.latest_ingest) {
    els.stageActionStatus.textContent = "No ingest results are available for the selected manuscript yet.";
    return;
  }
  try {
    const payload = await fetchJson(`/v1/manuscripts/${encodeURIComponent(manuscript.manuscript_id)}/ingest-results`);
    localStorage.setItem(`${ingestResultsCachePrefix}${manuscript.manuscript_id}`, JSON.stringify(payload));
    window.open(`/ui/ingest-results.html?manuscript_id=${encodeURIComponent(manuscript.manuscript_id)}`, "_blank", "noopener");
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
    const progress = latestJob ? state.jobProgressById[latestJob.job_id] : null;
    const compactProgress = stage.name === "orchestrate" ? renderCompactStageProgress(progress) : "";
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
      ${compactProgress ? `<p class="meta"><strong>Live progress:</strong> ${compactProgress}</p>` : ""}
      <div class="stage-card-actions">
        <button type="button" data-run-stage="${stage.name}">Run ${stageLabels[stage.name] || stage.name}</button>
      </div>
    `;
    card.querySelector("button").addEventListener("click", () => triggerPipeline(stage.name));
    if (stage.name === "ingest" && latestIngestForSelectedManuscript()) {
      const viewButton = document.createElement("button");
      viewButton.type = "button";
      viewButton.className = "secondary-button";
      viewButton.textContent = "Open Ingest Results";
      viewButton.addEventListener("click", openLatestIngestResults);
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
    els.jobProgress.textContent = "Live chunk progress appears here for categorisation and analysis jobs.";
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
    els.jobDownloads.innerHTML = "";
    els.jobProgress.textContent = "Live chunk progress appears here for categorisation and analysis jobs.";
    return;
  }
  try {
    const [freshJob, artifacts, progress] = await Promise.all([
      fetchJson(`/v1/jobs/${job.job_id}`),
      fetchJson(`/v1/jobs/${job.job_id}/artifacts`),
      fetchJson(`/v1/jobs/${job.job_id}/progress`),
    ]);
    state.jobProgressById[freshJob.job_id] = progress;
    els.jobDetail.textContent = renderJobSummary(freshJob);
    els.jobProgress.textContent = renderJobProgressSummary(progress);
    els.jobArtifacts.textContent = renderArtifactSummary(artifacts);
    renderJobDownloads(freshJob, artifacts);
    renderStageBoard();
  } catch (error) {
    els.jobDetail.textContent = error.message;
    els.jobProgress.textContent = error.message;
    els.jobArtifacts.textContent = error.message;
    els.jobDownloads.innerHTML = "";
  }
}

async function refreshSystem() {
  try {
    const payload = await fetchJson("/v1/system/status");
    els.systemStatus.textContent = renderSystemSummary(payload);
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
  if (state.selectedManuscriptId && !selectedManuscript()) {
    state.selectedManuscriptId = state.manuscripts[0]?.manuscript_id || null;
  }
  renderManuscripts();
  renderStageBoard();
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
    const manuscript = await sendJson("POST", "/v1/manuscripts", {
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

els.saveManuscript.addEventListener("click", async () => {
  const manuscript = selectedManuscript();
  if (!manuscript) {
    els.stageActionStatus.textContent = "Select a manuscript first.";
    return;
  }
  try {
    const updated = await sendJson("PUT", `/v1/manuscripts/${manuscript.manuscript_id}`, {
      title: els.selectedManuscriptTitle.value.trim(),
      book_slug: els.selectedManuscriptSlug.value.trim(),
    });
    state.selectedManuscriptId = updated.manuscript_id;
    els.stageActionStatus.textContent = `Manuscript updated: ${updated.title}`;
    await refreshManuscripts();
    await refreshJobs();
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
});

els.deleteManuscript.addEventListener("click", async () => {
  const manuscript = selectedManuscript();
  if (!manuscript) {
    els.stageActionStatus.textContent = "Select a manuscript first.";
    return;
  }
  if (!window.confirm(`Remove manuscript ${manuscript.title}?`)) {
    return;
  }
  try {
    await sendJson("DELETE", `/v1/manuscripts/${manuscript.manuscript_id}`);
    els.stageActionStatus.textContent = `Removed manuscript: ${manuscript.title}`;
    state.selectedManuscriptId = null;
    state.selectedJobId = null;
    await refreshManuscripts();
    await refreshJobs();
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
});

els.openIngestResults.addEventListener("click", openLatestIngestResults);
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
    refreshManuscripts();
    refreshJobs();
  }
}, autoRefreshMs);

refreshAll();
