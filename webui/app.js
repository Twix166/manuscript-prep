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
const stageOrder = ["ingest", "orchestrate", "merge", "resolve", "report"];

const state = {
  token: localStorage.getItem(storageKey) || "",
  currentUser: null,
  authSetup: null,
  adminMode: false,
  pipelines: [],
  manuscripts: [],
  configProfiles: [],
  jobs: [],
  jobProgressById: {},
  analysisDetailsByJobId: {},
  manuscriptDrafts: {},
  selectedManuscriptId: null,
  selectedConfigProfileId: null,
  selectedJobId: null,
  selectedAnalysisChunkId: null,
  currentPage: "manuscripts",
};

const els = {
  authScreen: document.getElementById("auth-screen"),
  appShell: document.getElementById("app-shell"),
  authColumns: document.querySelector(".auth-columns"),
  setupForm: document.getElementById("setup-form"),
  setupUsername: document.getElementById("setup-username"),
  setupPassword: document.getElementById("setup-password"),
  setupStatus: document.getElementById("setup-status"),
  loginForm: document.getElementById("login-form"),
  loginUsername: document.getElementById("login-username"),
  loginPassword: document.getElementById("login-password"),
  loginStatus: document.getElementById("login-status"),
  registerForm: document.getElementById("register-form"),
  registerUsername: document.getElementById("register-username"),
  registerPassword: document.getElementById("register-password"),
  registerStatus: document.getElementById("register-status"),
  refreshWorkspace: document.getElementById("refresh-workspace"),
  pageButtons: Array.from(document.querySelectorAll("[data-page]")),
  pageManuscripts: document.getElementById("page-manuscripts"),
  pagePipeline: document.getElementById("page-pipeline"),
  pageJobs: document.getElementById("page-jobs"),
  profileSummary: document.getElementById("profile-summary"),
  profileDetail: document.getElementById("profile-detail"),
  toggleAdminMode: document.getElementById("toggle-admin-mode"),
  logoutButton: document.getElementById("logout-button"),
  uploadForm: document.getElementById("upload-form"),
  uploadStatus: document.getElementById("upload-status"),
  manuscriptTitle: document.getElementById("manuscript-title"),
  manuscriptSlug: document.getElementById("manuscript-slug"),
  manuscriptFile: document.getElementById("manuscript-file"),
  configProfileSelect: document.getElementById("config-profile-select"),
  configProfileDetail: document.getElementById("config-profile-detail"),
  manuscriptList: document.getElementById("manuscript-list"),
  workspaceManuscriptTitle: document.getElementById("workspace-manuscript-title"),
  workspaceManuscriptSubtitle: document.getElementById("workspace-manuscript-subtitle"),
  manuscriptDetail: document.getElementById("manuscript-detail"),
  openIngestResults: document.getElementById("open-ingest-results"),
  stageBoard: document.getElementById("stage-board"),
  stageActionStatus: document.getElementById("stage-action-status"),
  systemStatus: document.getElementById("system-status"),
  adminConsole: document.getElementById("admin-console"),
  adminSystemStatus: document.getElementById("admin-system-status"),
  adminInterfaceNote: document.getElementById("admin-interface-note"),
  jobList: document.getElementById("job-list"),
  jobDetail: document.getElementById("job-detail"),
  jobProgress: document.getElementById("job-progress"),
  jobArtifacts: document.getElementById("job-artifacts"),
  jobDownloads: document.getElementById("job-downloads"),
  cancelSelectedJob: document.getElementById("cancel-selected-job"),
  runFullPipeline: document.getElementById("run-full-pipeline"),
  analysisDetailModal: document.getElementById("analysis-detail-modal"),
  analysisDetailTitle: document.getElementById("analysis-detail-title"),
  analysisDetailClose: document.getElementById("analysis-detail-close"),
  analysisDetailSummary: document.getElementById("analysis-detail-summary"),
  analysisChunkList: document.getElementById("analysis-chunk-list"),
  analysisChunkTitle: document.getElementById("analysis-chunk-title"),
  analysisChunkDetail: document.getElementById("analysis-chunk-detail"),
  manuscriptPickerModal: document.getElementById("manuscript-picker-modal"),
  manuscriptPickerClose: document.getElementById("manuscript-picker-close"),
  manuscriptPickerSummary: document.getElementById("manuscript-picker-summary"),
  manuscriptPickerList: document.getElementById("manuscript-picker-list"),
};

function currentHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  return headers;
}

async function parseJsonResponse(response, fallbackPath) {
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed for ${fallbackPath}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: currentHeaders() });
  return parseJsonResponse(response, path);
}

async function sendJson(method, path, payload = null) {
  const response = await fetch(path, {
    method,
    headers: currentHeaders({ "Content-Type": "application/json" }),
    body: payload ? JSON.stringify(payload) : null,
  });
  return parseJsonResponse(response, path);
}

async function postBinary(path, filename, file) {
  const response = await fetch(path, {
    method: "POST",
    headers: currentHeaders({
      "Content-Type": file.type || "application/pdf",
      "X-Filename": filename,
    }),
    body: file,
  });
  return parseJsonResponse(response, path);
}

function persistToken(token) {
  state.token = token;
  if (token) {
    localStorage.setItem(storageKey, token);
  } else {
    localStorage.removeItem(storageKey);
  }
}

function showAuthScreen() {
  els.authScreen.classList.remove("hidden");
  els.appShell.classList.add("hidden");
}

function showAppShell() {
  els.authScreen.classList.add("hidden");
  els.appShell.classList.remove("hidden");
}

function resetWorkspaceState() {
  state.currentUser = null;
  state.adminMode = false;
  state.pipelines = [];
  state.manuscripts = [];
  state.configProfiles = [];
  state.jobs = [];
  state.jobProgressById = {};
  state.analysisDetailsByJobId = {};
  state.manuscriptDrafts = {};
  state.selectedManuscriptId = null;
  state.selectedConfigProfileId = null;
  state.selectedJobId = null;
  state.selectedAnalysisChunkId = null;
  state.currentPage = "manuscripts";
  els.manuscriptList.innerHTML = "";
  els.stageBoard.innerHTML = "";
  els.jobList.innerHTML = "";
  els.jobDownloads.innerHTML = "";
  els.jobDetail.textContent = "Choose a job to inspect stage timing, command lines, and errors.";
  els.jobProgress.textContent = "Live chunk progress appears here for categorisation and analysis jobs.";
  els.jobArtifacts.textContent = "Artifact index appears here, including checksums and output paths.";
  els.systemStatus.textContent = "Sign in to load workspace status.";
  els.adminSystemStatus.textContent = "Switch to admin mode from the profile menu to load system-wide status.";
  els.adminInterfaceNote.textContent = "Admin mode is intended for platform oversight. Your manuscript workflow remains available above.";
  els.adminConsole.classList.add("hidden");
}

async function refreshSetupState() {
  const payload = await fetchJson("/v1/auth/setup-state");
  state.authSetup = payload;
  els.setupUsername.value = payload.admin_username || "admin";
  if (payload.needs_admin_setup) {
    els.setupForm.classList.remove("hidden");
    els.authColumns.classList.add("hidden");
  } else {
    els.setupForm.classList.add("hidden");
    els.authColumns.classList.remove("hidden");
  }
}

function renderAdminMode() {
  const canAdmin = state.currentUser?.role === "admin";
  if (!canAdmin) {
    els.toggleAdminMode.classList.add("hidden");
    els.adminConsole.classList.add("hidden");
    return;
  }
  els.toggleAdminMode.classList.remove("hidden");
  els.toggleAdminMode.textContent = state.adminMode ? "Back To User Workspace" : "Open Admin Interface";
  els.adminConsole.classList.toggle("hidden", !state.adminMode);
}

function renderCurrentPage() {
  const pageMap = {
    manuscripts: els.pageManuscripts,
    pipeline: els.pagePipeline,
    jobs: els.pageJobs,
  };
  for (const [page, element] of Object.entries(pageMap)) {
    element.classList.toggle("hidden", state.currentPage !== page);
  }
  for (const button of els.pageButtons) {
    button.classList.toggle("active", button.dataset.page === state.currentPage);
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

function latestStageCardJobForPipeline(pipeline) {
  const jobs = state.jobs.filter((job) => job.pipeline === pipeline);
  if (!jobs.length) {
    return null;
  }
  const active = jobs.find((job) => ["queued", "running", "cancel_requested", "pause_requested"].includes(job.status));
  if (active) {
    return active;
  }
  const paused = jobs.find((job) => job.status === "paused");
  if (paused) {
    return paused;
  }
  const succeeded = jobs.find((job) => job.status === "succeeded");
  if (succeeded) {
    return succeeded;
  }
  return null;
}

function latestIngestForSelectedManuscript() {
  const manuscript = selectedManuscript();
  return manuscript ? manuscript.latest_ingest || null : null;
}

function workflowExpansionKey() {
  const manuscript = selectedManuscript();
  if (!manuscript) {
    return "ingest";
  }
  const fullPipeline = state.pipelines.find((item) => item.pipeline === "manuscript-prep");
  if (!fullPipeline) {
    return "ingest";
  }
  for (const stage of fullPipeline.stages) {
    const latestJob = latestStageCardJobForPipeline(stage.name);
    if (latestJob && ["queued", "running", "cancel_requested", "pause_requested", "paused"].includes(latestJob.status)) {
      return stage.name;
    }
    if (!latestJob || latestJob.status !== "succeeded") {
      return stage.name;
    }
  }
  return fullPipeline.stages[fullPipeline.stages.length - 1]?.name || "report";
}

function stepNumber(stepName) {
  const index = stageOrder.indexOf(stepName);
  return index === -1 ? "?" : String(index + 1);
}

function manuscriptDraft(manuscript) {
  const draft = state.manuscriptDrafts[manuscript.manuscript_id];
  if (!draft) {
    return {
      title: manuscript.title,
      book_slug: manuscript.book_slug,
    };
  }
  return {
    title: draft.title,
    book_slug: draft.book_slug,
  };
}

function syncManuscriptDrafts() {
  const nextDrafts = {};
  for (const manuscript of state.manuscripts) {
    const existing = state.manuscriptDrafts[manuscript.manuscript_id];
    if (!existing) {
      continue;
    }
    const dirty = existing.title !== manuscript.title || existing.book_slug !== manuscript.book_slug;
    if (dirty) {
      nextDrafts[manuscript.manuscript_id] = existing;
    }
  }
  state.manuscriptDrafts = nextDrafts;
}

function renderManuscriptPicker() {
  els.manuscriptPickerList.innerHTML = "";
  if (!state.manuscripts.length) {
    els.manuscriptPickerList.innerHTML = '<li class="muted">No manuscripts are available yet</li>';
    return;
  }
  for (const manuscript of state.manuscripts) {
    const li = document.createElement("li");
    li.className = manuscript.manuscript_id === state.selectedManuscriptId ? "selected" : "";
    li.innerHTML = `
      <strong>${escapeHtml(manuscript.title)}</strong>
      <span class="meta">${escapeHtml(manuscript.book_slug)}</span>
    `;
    li.addEventListener("click", async () => {
      state.selectedManuscriptId = manuscript.manuscript_id;
      state.selectedJobId = null;
      renderManuscriptPicker();
      renderManuscripts();
      renderStageBoard();
      await refreshJobs();
      els.manuscriptPickerModal.close();
      els.stageActionStatus.textContent = `Selected manuscript: ${manuscript.title}`;
    });
    els.manuscriptPickerList.appendChild(li);
  }
}

function openManuscriptPicker() {
  renderManuscriptPicker();
  if (!els.manuscriptPickerModal.open) {
    els.manuscriptPickerModal.showModal();
  }
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

function renderProfileSummary() {
  if (!state.currentUser) {
    els.profileSummary.textContent = "Profile";
    els.profileDetail.textContent = "Profile details load after sign-in.";
    els.toggleAdminMode.classList.add("hidden");
    return;
  }
  els.profileSummary.textContent = state.currentUser.username;
  els.profileDetail.textContent = [
    `${state.currentUser.username}`,
    "",
    `Role: ${state.currentUser.role}`,
    `Created: ${formatDate(state.currentUser.created_at)}`,
    `Updated: ${formatDate(state.currentUser.updated_at)}`,
  ].join("\n");
  renderAdminMode();
}

function renderSystemSummary(payload) {
  const queue = payload.queue || {};
  const workers = payload.workers || [];
  const workerLines = workers.length
    ? workers.map((worker) => `- ${worker.worker_id}: ${worker.status} | heartbeat ${formatDate(worker.heartbeat_at)}${worker.last_job_id ? ` | last job ${worker.last_job_id}` : ""}`)
    : ["- No workers reporting yet"];
  return [
    `System`,
    `- Store backend: ${payload.store_backend || "n/a"}`,
    `- Ready: ${payload.ready ? "yes" : "no"}`,
    `- Updated: ${formatDate(payload.timestamp)}`,
    "",
    `Queue`,
    `- Queued: ${queue.queued || 0}`,
    `- Running: ${queue.running || 0}`,
    `- Cancel requested: ${queue.cancel_requested || 0}`,
    `- Succeeded: ${queue.succeeded || 0}`,
    `- Failed: ${queue.failed || 0}`,
    `- Cancelled: ${queue.cancelled || 0}`,
    `- Total: ${queue.total || 0}`,
    "",
    `Workers`,
    ...workerLines,
  ].join("\n");
}

function renderUserWorkspaceSummary() {
  return [
    `Workspace`,
    `- User: ${state.currentUser?.username || "n/a"}`,
    `- Role: ${state.currentUser?.role || "n/a"}`,
    `- Manuscripts: ${state.manuscripts.length}`,
    `- Config profiles: ${state.configProfiles.length}`,
    `- Selected manuscript jobs: ${state.jobs.length}`,
    "",
    `System details are visible to admin users. You can still upload manuscripts, run stages, and manage your pipeline from here.`,
  ].join("\n");
}

function renderJobSummary(job) {
  const stageLines = stageSummaryLines(job.stage_runs);
  const command = job.stage_runs?.find((stage) => stage.command && stage.command.length)?.command?.join(" ");
  return [
    `${stageLabels[job.pipeline] || job.pipeline} Job`,
    "",
    `Job ID: ${job.job_id}`,
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
    ? progress.recent_events.slice(-5).map((event) => `- ${formatDate(event.timestamp)} | ${event.chunk || "-"} | ${event.pass || "-"} | ${event.message || event.event_type || "-"}`)
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
  const throughput = progress.reported_tps || progress.estimated_tps;
  return `Chunk ${progress.current_chunk_index || "?"}/${progress.chunks_total || "?"}: ${progress.current_chunk} | Pass ${progress.current_pass_index || "?"}/4: ${progress.current_pass || "starting"} | ${progress.current_step || "working"}${throughput ? ` | ${throughput} tok/s` : ""}`;
}

async function pauseJob(jobId) {
  return sendJson("POST", `/v1/jobs/${encodeURIComponent(jobId)}/pause`, {});
}

function stringifyFlag(value) {
  if (value === true) return "yes";
  if (value === false) return "no";
  if (value === null || value === undefined || value === "") return "n/a";
  return String(value);
}

function analysisChunkSummaryLine(chunk) {
  return `${chunk.chunk_id} | ${chunk.passes_completed.length}/4 passes | ${chunk.entities.characters.length} characters | ${chunk.dossiers.character_dossiers.length} dossiers`;
}

function renderAnalysisSummary(details) {
  if (!details || details.available === false) {
    return details?.message || "No chunk findings are available yet.";
  }
  const progress = details.progress || {};
  const throughput = progress.reported_tps || progress.estimated_tps;
  return [
    "Analysis Summary",
    "",
    `- Processed chunks: ${details.chunks_with_outputs || 0} of ${details.chunks_total || 0}`,
    `- Active chunk: ${progress.current_chunk || "n/a"}`,
    `- Active pass: ${progress.current_pass || "n/a"}`,
    `- Active model: ${progress.current_model || "n/a"}`,
    `- Throughput: ${throughput ? `${throughput} tok/s` : "n/a"}`,
  ].join("\n");
}

function renderAnalysisChunkDetail(chunk) {
  if (!chunk) {
    return "Select a processed chunk to inspect structure, dialogue, entities, and dossiers.";
  }
  const dossiers = chunk.dossiers.character_dossiers || [];
  const dossierLines = dossiers.length
    ? dossiers.map((item) => {
      const role = item.role || item.roles?.join(", ") || "role not set";
      return `- ${item.name || "Unnamed"} | ${role}`;
    })
    : ["- No dossier entries yet"];
  return [
    `${chunk.chunk_id}`,
    "",
    `Completion`,
    `- Passes completed: ${chunk.passes_completed.join(", ") || "none yet"}`,
    `- Total duration: ${chunk.timing.total_duration_seconds ?? "n/a"} s`,
    "",
    `Structure`,
    `- Chapters: ${(chunk.structure.chapters || []).join(", ") || "none"}`,
    `- Parts: ${(chunk.structure.parts || []).join(", ") || "none"}`,
    `- Scene breaks: ${(chunk.structure.scene_breaks || []).length}`,
    `- Status: ${chunk.structure.status || "n/a"}`,
    "",
    `Dialogue`,
    `- POV: ${chunk.dialogue.pov || "n/a"}`,
    `- Dialogue present: ${stringifyFlag(chunk.dialogue.dialogue)}`,
    `- Internal thought: ${stringifyFlag(chunk.dialogue.internal_thought)}`,
    `- Attributed speakers: ${(chunk.dialogue.explicitly_attributed_speakers || []).join(", ") || "none"}`,
    `- Unattributed dialogue: ${stringifyFlag(chunk.dialogue.unattributed_dialogue_present)}`,
    "",
    `Entities`,
    `- Characters: ${(chunk.entities.characters || []).join(", ") || "none"}`,
    `- Places: ${(chunk.entities.places || []).join(", ") || "none"}`,
    `- Objects: ${(chunk.entities.objects || []).join(", ") || "none"}`,
    `- Identity notes: ${(chunk.entities.identity_notes || []).join(" | ") || "none"}`,
    "",
    `Dossiers`,
    ...dossierLines,
  ].join("\n");
}

function renderAnalysisChunkList(details) {
  els.analysisChunkList.innerHTML = "";
  const chunks = details?.chunks || [];
  if (!chunks.length) {
    els.analysisChunkList.innerHTML = '<li class="muted">No processed chunks yet</li>';
    els.analysisChunkTitle.textContent = "Chunk Findings";
    els.analysisChunkDetail.textContent = "Select a processed chunk to inspect structure, dialogue, entities, and dossiers.";
    return;
  }
  if (!state.selectedAnalysisChunkId || !chunks.find((chunk) => chunk.chunk_id === state.selectedAnalysisChunkId)) {
    state.selectedAnalysisChunkId = chunks[0].chunk_id;
  }
  for (const chunk of chunks) {
    const li = document.createElement("li");
    li.className = chunk.chunk_id === state.selectedAnalysisChunkId ? "selected" : "";
    li.innerHTML = `<strong>${chunk.chunk_id}</strong><span class="meta">${analysisChunkSummaryLine(chunk)}</span>`;
    li.addEventListener("click", () => {
      state.selectedAnalysisChunkId = chunk.chunk_id;
      renderAnalysisChunkList(details);
    });
    els.analysisChunkList.appendChild(li);
  }
  const selectedChunk = chunks.find((chunk) => chunk.chunk_id === state.selectedAnalysisChunkId) || chunks[0];
  els.analysisChunkTitle.textContent = selectedChunk.chunk_id;
  els.analysisChunkDetail.textContent = renderAnalysisChunkDetail(selectedChunk);
}

function showAnalysisDetailModal(details, job) {
  els.analysisDetailTitle.textContent = `${stageLabels.orchestrate} Detail`;
  els.analysisDetailSummary.textContent = renderAnalysisSummary(details);
  renderAnalysisChunkList(details);
  if (!els.analysisDetailModal.open) {
    els.analysisDetailModal.showModal();
  }
  if (job?.job_id) {
    els.stageActionStatus.textContent = `Showing processed chunk detail for job ${job.job_id}`;
  }
}

async function openAnalysisDetails(job) {
  if (!job) {
    els.stageActionStatus.textContent = "No categorisation job is available for detail view yet.";
    return;
  }
  try {
    const details = await fetchJson(`/v1/jobs/${encodeURIComponent(job.job_id)}/analysis-details`);
    state.analysisDetailsByJobId[job.job_id] = details;
    state.selectedAnalysisChunkId = details.chunks?.[0]?.chunk_id || null;
    showAnalysisDetailModal(details, job);
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
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
      // ignore
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

async function cancelJob(jobId) {
  return sendJson("POST", `/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {});
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
    els.workspaceManuscriptTitle.textContent = "Choose a manuscript";
    els.workspaceManuscriptSubtitle.textContent = "Upload a manuscript to begin.";
    els.manuscriptDetail.textContent = "Upload and register a manuscript to begin.";
    return;
  }
  for (const manuscript of state.manuscripts) {
    const latestIngest = manuscript.latest_ingest;
    const draft = manuscriptDraft(manuscript);
    const safeTitle = escapeHtml(draft.title);
    const safeSlug = escapeHtml(draft.book_slug);
    const li = document.createElement("li");
    li.dataset.manuscriptId = manuscript.manuscript_id;
    li.className = manuscript.manuscript_id === state.selectedManuscriptId ? "selected" : "";
    li.innerHTML = `
      <div class="manuscript-row">
        <div class="manuscript-row-head">
          <div>
            <strong>${safeTitle}</strong>
            <span>${safeSlug}</span><br>
            <span class="meta">Ingest: ${latestIngest ? `${latestIngest.status} at ${formatDate(latestIngest.finished_at || latestIngest.updated_at)}` : "not run yet"}</span>
          </div>
          <div class="manuscript-row-actions">
            <button type="button" class="secondary-button" data-save-manuscript="${manuscript.manuscript_id}" disabled>Save</button>
            <button type="button" class="danger-button" data-delete-manuscript="${manuscript.manuscript_id}">Remove</button>
          </div>
        </div>
        <div class="manuscript-row-fields">
          <input type="text" data-manuscript-title="${manuscript.manuscript_id}" value="${safeTitle}" aria-label="Title for ${safeTitle}">
          <input type="text" data-manuscript-slug="${manuscript.manuscript_id}" value="${safeSlug}" aria-label="Slug for ${safeTitle}">
        </div>
      </div>
    `;
    li.addEventListener("click", async () => {
      state.selectedManuscriptId = manuscript.manuscript_id;
      state.selectedJobId = null;
      renderManuscripts();
      await refreshJobs();
      renderStageBoard();
    });
    const titleInput = li.querySelector(`[data-manuscript-title="${manuscript.manuscript_id}"]`);
    const slugInput = li.querySelector(`[data-manuscript-slug="${manuscript.manuscript_id}"]`);
    const saveButton = li.querySelector(`[data-save-manuscript="${manuscript.manuscript_id}"]`);
    const deleteButton = li.querySelector(`[data-delete-manuscript="${manuscript.manuscript_id}"]`);
    const syncDirtyState = () => {
      state.manuscriptDrafts[manuscript.manuscript_id] = {
        title: titleInput.value,
        book_slug: slugInput.value,
      };
      const dirty = titleInput.value.trim() !== manuscript.title || slugInput.value.trim() !== manuscript.book_slug;
      saveButton.disabled = !dirty;
      if (!dirty) {
        delete state.manuscriptDrafts[manuscript.manuscript_id];
      }
    };
    titleInput.addEventListener("click", (event) => event.stopPropagation());
    slugInput.addEventListener("click", (event) => event.stopPropagation());
    titleInput.addEventListener("input", syncDirtyState);
    slugInput.addEventListener("input", syncDirtyState);
    syncDirtyState();
    saveButton.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        const updated = await sendJson("PUT", `/v1/manuscripts/${manuscript.manuscript_id}`, {
          title: titleInput.value.trim(),
          book_slug: slugInput.value.trim(),
        });
        delete state.manuscriptDrafts[manuscript.manuscript_id];
        state.selectedManuscriptId = updated.manuscript_id;
        els.stageActionStatus.textContent = `Manuscript updated: ${updated.title}`;
        await refreshManuscripts();
        await refreshJobs();
      } catch (error) {
        els.stageActionStatus.textContent = error.message;
      }
    });
    deleteButton.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!window.confirm(`Remove manuscript ${manuscript.title}?`)) {
        return;
      }
      try {
        await sendJson("DELETE", `/v1/manuscripts/${manuscript.manuscript_id}`);
        delete state.manuscriptDrafts[manuscript.manuscript_id];
        els.stageActionStatus.textContent = `Removed manuscript: ${manuscript.title}`;
        if (state.selectedManuscriptId === manuscript.manuscript_id) {
          state.selectedManuscriptId = null;
          state.selectedJobId = null;
        }
        await refreshManuscripts();
        await refreshJobs();
      } catch (error) {
        els.stageActionStatus.textContent = error.message;
      }
    });
    els.manuscriptList.appendChild(li);
  }
  const manuscript = selectedManuscript();
  if (!manuscript) {
    els.manuscriptDetail.textContent = "Select a manuscript to see pipeline-ready details.";
    return;
  }
  els.workspaceManuscriptTitle.textContent = manuscript.title;
  els.workspaceManuscriptSubtitle.textContent = `Working on ${manuscript.book_slug}. Jobs and stage controls below apply only to this manuscript.`;
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
    els.stageActionStatus.textContent = `${stageLabels[pipeline] || pipeline} job queued: ${created.job_id}`;
    await refreshJobs();
    await refreshManuscripts();
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
}

async function resumeJob(jobId) {
  return sendJson("POST", `/v1/jobs/${encodeURIComponent(jobId)}/run`, {});
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
  const expandedKey = workflowExpansionKey();

  for (const stage of fullPipeline.stages) {
    const manuscript = selectedManuscript();
    const latestJob = latestStageCardJobForPipeline(stage.name);
    const stageStatus = latestJob ? latestJob.status : "not-started";
    const progress = latestJob ? state.jobProgressById[latestJob.job_id] : null;
    const compactProgress = stage.name === "orchestrate" ? renderCompactStageProgress(progress) : "";
    const throughput = stage.name === "orchestrate" ? (progress?.reported_tps || progress?.estimated_tps) : null;
    const models = resolveModelRefs(stage);
    const card = document.createElement("details");
    card.className = `workflow-step stage-card status-${stageStatus}`;
    if (expandedKey === stage.name) {
      card.open = true;
    }
    const actionRow = document.createElement("div");
    actionRow.className = "stage-card-actions";
    const runPauseButton = document.createElement("button");
    runPauseButton.type = "button";
    if (!latestJob || ["not-started", "failed", "cancelled", "succeeded"].includes(stageStatus)) {
      runPauseButton.textContent = "Run";
      runPauseButton.disabled = false;
      runPauseButton.addEventListener("click", () => triggerPipeline(stage.name));
    } else if (["queued", "running"].includes(stageStatus)) {
      runPauseButton.textContent = "Pause";
      runPauseButton.disabled = false;
      runPauseButton.addEventListener("click", async () => {
        try {
          await pauseJob(latestJob.job_id);
          els.stageActionStatus.textContent = `Pause requested for job ${latestJob.job_id}`;
          await refreshJobs();
        } catch (error) {
          els.stageActionStatus.textContent = error.message;
        }
      });
    } else if (stageStatus === "paused") {
      runPauseButton.textContent = "Run";
      runPauseButton.disabled = false;
      runPauseButton.addEventListener("click", async () => {
        try {
          await resumeJob(latestJob.job_id);
          els.stageActionStatus.textContent = `Resumed job ${latestJob.job_id}`;
          await refreshJobs();
        } catch (error) {
          els.stageActionStatus.textContent = error.message;
        }
      });
    } else if (["pause_requested", "cancel_requested"].includes(stageStatus)) {
      runPauseButton.textContent = stageStatus === "pause_requested" ? "Pausing" : "Stopping";
      runPauseButton.disabled = true;
    } else {
      runPauseButton.textContent = "Run";
      runPauseButton.disabled = false;
      runPauseButton.addEventListener("click", () => triggerPipeline(stage.name));
    }

    const stopButton = document.createElement("button");
    stopButton.type = "button";
    stopButton.className = "danger-button";
    stopButton.textContent = stageStatus === "cancel_requested" ? "Stopping" : "Stop";
    stopButton.disabled = !latestJob || ["cancel_requested", "pause_requested", "succeeded", "failed", "cancelled", "not-started"].includes(stageStatus);
    stopButton.addEventListener("click", async () => {
      try {
        await cancelJob(latestJob.job_id);
        els.stageActionStatus.textContent = `Stop requested for job ${latestJob.job_id}`;
        await refreshJobs();
      } catch (error) {
        els.stageActionStatus.textContent = error.message;
      }
    });

    actionRow.appendChild(runPauseButton);
    actionRow.appendChild(stopButton);

    card.innerHTML = `
      <summary>
        <div class="workflow-step-head">
          <div>
            <p class="eyebrow">${stage.kind}</p>
            <h3>${stepNumber(stage.name)}. ${stageLabels[stage.name] || stage.name}</h3>
          </div>
          <span class="status-pill">${stageStatus}</span>
        </div>
        <p class="meta">${stage.description}</p>
      </summary>
      <div class="workflow-step-body">
        ${stage.name === "ingest" ? `<p class="meta"><strong>Selected manuscript:</strong> ${manuscript ? `${escapeHtml(manuscript.title)} (${escapeHtml(manuscript.book_slug)})` : "none selected"}</p>` : ""}
        <p class="meta"><strong>Substeps:</strong> ${(stage.metadata.substeps || []).join(", ") || "n/a"}</p>
        <p class="meta"><strong>Models:</strong> ${models.length ? models.join(", ") : "Deterministic stage"}</p>
        <p class="meta"><strong>Last update:</strong> ${latestJob ? formatDate(latestJob.updated_at) : "n/a"}</p>
        ${throughput ? `<p class="meta"><strong>Throughput:</strong> ${throughput} tok/s</p>` : ""}
        ${compactProgress ? `<p class="meta"><strong>Live progress:</strong> ${compactProgress}</p>` : ""}
        <div class="stage-card-actions" data-stage-actions="${stage.name}"></div>
      </div>
    `;
    card.querySelector(`[data-stage-actions="${stage.name}"]`).replaceWith(actionRow);
    if (stage.name === "ingest" && latestIngestForSelectedManuscript()) {
      const viewButton = document.createElement("button");
      viewButton.type = "button";
      viewButton.className = "secondary-button";
      viewButton.textContent = "Open Ingest Results";
      viewButton.addEventListener("click", openLatestIngestResults);
      actionRow.appendChild(viewButton);
    }
    if (stage.name === "ingest") {
      const chooseButton = document.createElement("button");
      chooseButton.type = "button";
      chooseButton.className = "secondary-button";
      chooseButton.textContent = "Choose Manuscript";
      chooseButton.addEventListener("click", openManuscriptPicker);
      actionRow.appendChild(chooseButton);
    }
    if (stage.name === "orchestrate" && latestJob) {
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.className = "secondary-button";
      detailButton.textContent = "Detail";
      detailButton.addEventListener("click", () => openAnalysisDetails(latestJob));
      actionRow.appendChild(detailButton);
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
    li.innerHTML = `
      <div class="job-list-item">
        <div class="job-list-head">
          <strong>${stageLabels[job.pipeline] || job.pipeline}</strong>
          <span class="status-chip status-${job.status}">${job.status.replaceAll("_", " ")}</span>
        </div>
        <span class="meta">Job ID: ${job.job_id}</span>
        <span class="meta">Updated: ${formatDate(job.updated_at)}</span>
      </div>
    `;
    li.addEventListener("click", async (event) => {
      if (event.target instanceof HTMLElement && event.target.closest("button")) {
        return;
      }
      state.selectedJobId = job.job_id;
      renderJobs();
      await refreshSelectedJob();
    });
    if (["queued", "running", "cancel_requested"].includes(job.status)) {
      const actions = document.createElement("div");
      actions.className = "panel-actions";
      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "danger-button";
      cancelButton.textContent = job.status === "cancel_requested" ? "Cancellation Requested" : "Cancel Job";
      cancelButton.disabled = job.status === "cancel_requested";
      cancelButton.addEventListener("click", async (event) => {
        event.stopPropagation();
        try {
          await cancelJob(job.job_id);
          els.stageActionStatus.textContent = `Cancellation requested for job ${job.job_id}`;
          await refreshJobs();
        } catch (error) {
          els.stageActionStatus.textContent = error.message;
        }
      });
      actions.appendChild(cancelButton);
      li.appendChild(actions);
    }
    els.jobList.appendChild(li);
  }
}

async function refreshSelectedJob() {
  const job = selectedJob();
  if (!job) {
    els.jobDownloads.innerHTML = "";
    els.jobProgress.textContent = "Live chunk progress appears here for categorisation and analysis jobs.";
    els.cancelSelectedJob.disabled = true;
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
    els.cancelSelectedJob.disabled = !["queued", "running", "cancel_requested"].includes(freshJob.status);
    renderStageBoard();
  } catch (error) {
    els.jobDetail.textContent = error.message;
    els.jobProgress.textContent = error.message;
    els.jobArtifacts.textContent = error.message;
    els.jobDownloads.innerHTML = "";
    els.cancelSelectedJob.disabled = true;
  }
}

async function refreshSystem() {
  if (!state.currentUser) {
    els.systemStatus.textContent = "Sign in to load workspace status.";
    return;
  }
  try {
    const payload = await fetchJson("/v1/system/status");
    const rendered = renderSystemSummary(payload);
    if (state.currentUser.role === "admin") {
      els.systemStatus.textContent = state.adminMode
        ? "Admin mode is active. See the Admin Interface panel below for system-wide status."
        : renderUserWorkspaceSummary();
      els.adminSystemStatus.textContent = rendered;
      els.adminInterfaceNote.textContent = [
        "Admin Interface",
        "- Use this mode for queue, worker, and persistence oversight.",
        "- The manuscript workflow above remains active while admin mode is open.",
      ].join("\n");
    } else {
      els.systemStatus.textContent = rendered;
    }
  } catch (error) {
    if (error.status === 403) {
      els.systemStatus.textContent = renderUserWorkspaceSummary();
      return;
    }
    els.systemStatus.textContent = error.message;
  }
}

async function refreshPipelines() {
  const payload = await fetchJson("/v1/pipelines");
  state.pipelines = payload.pipelines;
  renderStageBoard();
}

async function refreshConfigProfiles() {
  const payload = await fetchJson("/v1/config-profiles");
  state.configProfiles = payload.config_profiles;
  renderConfigProfiles();
  renderStageBoard();
}

async function refreshManuscripts() {
  const payload = await fetchJson("/v1/manuscripts");
  state.manuscripts = payload.manuscripts;
  syncManuscriptDrafts();
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
  const orchestrateJob = latestStageCardJobForPipeline("orchestrate");
  if (orchestrateJob) {
    try {
      state.jobProgressById[orchestrateJob.job_id] = await fetchJson(`/v1/jobs/${orchestrateJob.job_id}/progress`);
    } catch {
      // keep last known progress if the lightweight refresh fails
    }
  }
  if (!state.selectedJobId && state.jobs.length) {
    state.selectedJobId = state.jobs[0].job_id;
  }
  if (state.selectedJobId && !selectedJob()) {
    state.selectedJobId = state.jobs[0]?.job_id || null;
  }
  renderJobs();
  renderStageBoard();
  await refreshSelectedJob();
}

async function refreshAll() {
  if (!state.token) {
    await refreshSetupState();
    showAuthScreen();
    return;
  }
  try {
    const me = await fetchJson("/v1/auth/me");
    state.currentUser = me.user;
    renderProfileSummary();
    renderCurrentPage();
    showAppShell();
    await Promise.all([refreshConfigProfiles(), refreshManuscripts(), refreshPipelines()]);
    await refreshJobs();
    await refreshSystem();
  } catch (error) {
    persistToken("");
    resetWorkspaceState();
    els.loginStatus.textContent = error.message;
    await refreshSetupState();
    showAuthScreen();
  }
}

async function handleAuthSuccess(payload, message) {
  persistToken(payload.api_token);
  state.currentUser = payload.user;
  state.adminMode = false;
  renderProfileSummary();
  els.loginStatus.textContent = message;
  els.registerStatus.textContent = message;
  els.setupStatus.textContent = message;
  showAppShell();
  await refreshAll();
}

function attachUploadFormHandler() {
  if (!els.uploadForm || els.uploadForm.dataset.bound === "true") {
    return;
  }
  els.uploadForm.dataset.bound = "true";
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
}

els.setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    els.setupStatus.textContent = "Setting admin password...";
    const payload = await sendJson("POST", "/v1/auth/bootstrap-admin", {
      username: els.setupUsername.value.trim(),
      password: els.setupPassword.value,
    });
    await refreshSetupState();
    await handleAuthSuccess(payload, `Admin setup complete for ${payload.user.username}.`);
    els.setupForm.reset();
    els.setupUsername.value = payload.user.username;
  } catch (error) {
    els.setupStatus.textContent = error.message;
  }
});

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    els.loginStatus.textContent = "Signing in...";
    const payload = await sendJson("POST", "/v1/auth/login", {
      username: els.loginUsername.value.trim(),
      password: els.loginPassword.value,
    });
    await handleAuthSuccess(payload, `Signed in as ${payload.user.username}.`);
    els.loginForm.reset();
  } catch (error) {
    els.loginStatus.textContent = error.message;
  }
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    els.registerStatus.textContent = "Creating account...";
    const payload = await sendJson("POST", "/v1/auth/register", {
      username: els.registerUsername.value.trim(),
      password: els.registerPassword.value,
    });
    await handleAuthSuccess(payload, `Account created for ${payload.user.username}.`);
    els.registerForm.reset();
  } catch (error) {
    els.registerStatus.textContent = error.message;
  }
});

els.logoutButton.addEventListener("click", () => {
  persistToken("");
  resetWorkspaceState();
  renderProfileSummary();
  showAuthScreen();
  els.loginStatus.textContent = "Signed out.";
  els.registerStatus.textContent = "Create a new account or sign back in.";
  refreshSetupState().catch(() => {
    // keep signed-out screen even if setup probe fails
  });
});

els.toggleAdminMode.addEventListener("click", async () => {
  state.adminMode = !state.adminMode;
  renderAdminMode();
  await refreshSystem();
});

els.refreshWorkspace.addEventListener("click", refreshAll);

for (const button of els.pageButtons) {
  button.addEventListener("click", () => {
    state.currentPage = button.dataset.page;
    renderCurrentPage();
  });
}

els.configProfileSelect.addEventListener("change", () => {
  state.selectedConfigProfileId = els.configProfileSelect.value;
  renderConfigProfiles();
  renderStageBoard();
});

els.openIngestResults.addEventListener("click", openLatestIngestResults);
els.cancelSelectedJob.addEventListener("click", async () => {
  const job = selectedJob();
  if (!job) {
    els.stageActionStatus.textContent = "Select a job first.";
    return;
  }
  try {
    await cancelJob(job.job_id);
    els.stageActionStatus.textContent = `Cancellation requested for job ${job.job_id}`;
    await refreshJobs();
  } catch (error) {
    els.stageActionStatus.textContent = error.message;
  }
});
els.runFullPipeline.addEventListener("click", () => triggerPipeline("manuscript-prep"));
els.analysisDetailClose.addEventListener("click", () => els.analysisDetailModal.close());
els.analysisDetailModal.addEventListener("click", (event) => {
  const rect = els.analysisDetailModal.getBoundingClientRect();
  const withinDialog =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom;
  if (!withinDialog) {
    els.analysisDetailModal.close();
  }
});
els.manuscriptPickerClose.addEventListener("click", () => els.manuscriptPickerModal.close());
els.manuscriptPickerModal.addEventListener("click", (event) => {
  const rect = els.manuscriptPickerModal.getBoundingClientRect();
  const withinDialog =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom;
  if (!withinDialog) {
    els.manuscriptPickerModal.close();
  }
});

for (const button of document.querySelectorAll("[data-refresh]")) {
  button.addEventListener("click", async () => {
    const target = button.getAttribute("data-refresh");
    if (target === "system") await refreshSystem();
    if (target === "pipelines") await refreshPipelines();
    if (target === "manuscripts" || target === "selected-manuscript") await refreshManuscripts();
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

attachUploadFormHandler();

renderProfileSummary();
resetWorkspaceState();
refreshAll();
els.cancelSelectedJob.disabled = true;
