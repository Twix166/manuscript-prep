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
const stageOrder = ["upload", "ingest", "orchestrate", "merge", "resolve", "report"];

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
  manuscriptDrafts: {},
  selectedManuscriptId: null,
  selectedConfigProfileId: null,
  selectedJobId: null,
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
  state.manuscriptDrafts = {};
  state.selectedManuscriptId = null;
  state.selectedConfigProfileId = null;
  state.selectedJobId = null;
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
  const active = jobs.find((job) => ["queued", "running", "cancel_requested"].includes(job.status));
  if (active) {
    return active;
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
    return "upload";
  }
  const fullPipeline = state.pipelines.find((item) => item.pipeline === "manuscript-prep");
  if (!fullPipeline) {
    return "upload";
  }
  for (const stage of fullPipeline.stages) {
    const latestJob = latestStageCardJobForPipeline(stage.name);
    if (latestJob && ["queued", "running", "cancel_requested"].includes(latestJob.status)) {
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

  const uploadStep = document.createElement("details");
  uploadStep.className = "workflow-step";
  if (expandedKey === "upload") {
    uploadStep.open = true;
  }
  const manuscript = selectedManuscript();
  const uploadStatus = manuscript ? "ready" : "not-started";
  uploadStep.innerHTML = `
    <summary>
      <div class="workflow-step-head">
        <div>
          <p class="eyebrow">workspace</p>
          <h3>${stepNumber("upload")}. Upload Manuscript</h3>
        </div>
        <span class="status-pill">${uploadStatus}</span>
      </div>
      <p class="meta">${manuscript ? `Current manuscript: ${manuscript.title}` : "Upload a manuscript PDF to start a new pipeline."}</p>
    </summary>
    <div class="workflow-step-body">
      <form id="upload-form-inline" class="stack">
        <label for="manuscript-title">Title</label>
        <input id="manuscript-title" type="text" placeholder="Treasure Island">
        <label for="manuscript-slug">Slug</label>
        <input id="manuscript-slug" type="text" placeholder="Optional; generated from title if blank">
        <label for="manuscript-file">PDF manuscript</label>
        <input id="manuscript-file" type="file" accept=".pdf,application/pdf">
        <button type="submit">Upload And Register</button>
        <p id="upload-status" class="muted">Upload a PDF to create a managed manuscript record.</p>
      </form>
    </div>
  `;
  els.stageBoard.appendChild(uploadStep);
  els.uploadForm = document.getElementById("upload-form-inline");
  els.uploadStatus = document.getElementById("upload-status");
  els.manuscriptTitle = document.getElementById("manuscript-title");
  els.manuscriptSlug = document.getElementById("manuscript-slug");
  els.manuscriptFile = document.getElementById("manuscript-file");
  attachUploadFormHandler();

  for (const stage of fullPipeline.stages) {
    const latestJob = latestStageCardJobForPipeline(stage.name);
    const stageStatus = latestJob ? latestJob.status : "not-started";
    const progress = latestJob ? state.jobProgressById[latestJob.job_id] : null;
    const compactProgress = stage.name === "orchestrate" ? renderCompactStageProgress(progress) : "";
    const models = resolveModelRefs(stage);
    const card = document.createElement("details");
    card.className = `workflow-step stage-card status-${stageStatus}`;
    if (expandedKey === stage.name) {
      card.open = true;
    }
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
        <p class="meta"><strong>Substeps:</strong> ${(stage.metadata.substeps || []).join(", ") || "n/a"}</p>
        <p class="meta"><strong>Models:</strong> ${models.length ? models.join(", ") : "Deterministic stage"}</p>
        <p class="meta"><strong>Last update:</strong> ${latestJob ? formatDate(latestJob.updated_at) : "n/a"}</p>
        ${compactProgress ? `<p class="meta"><strong>Live progress:</strong> ${compactProgress}</p>` : ""}
        <div class="stage-card-actions">
          <button type="button" data-run-stage="${stage.name}">Run ${stageLabels[stage.name] || stage.name}</button>
        </div>
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
    li.innerHTML = `
      <strong>${stageLabels[job.pipeline] || job.pipeline}</strong>
      <span class="meta">Job ID: ${job.job_id}</span><br>
      <span class="meta">Status: ${job.status} | Updated: ${formatDate(job.updated_at)}</span>
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

renderProfileSummary();
resetWorkspaceState();
refreshAll();
els.cancelSelectedJob.disabled = true;
