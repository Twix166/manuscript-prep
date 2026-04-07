const storageKey = "manuscriptprep.apiToken";
const state = {
  token: localStorage.getItem(storageKey) || "",
  selectedJobId: null,
};

const els = {
  authForm: document.getElementById("auth-form"),
  apiToken: document.getElementById("api-token"),
  authStatus: document.getElementById("auth-status"),
  systemStatus: document.getElementById("system-status"),
  pipelineList: document.getElementById("pipeline-list"),
  jobList: document.getElementById("job-list"),
  manuscriptList: document.getElementById("manuscript-list"),
  configProfileList: document.getElementById("config-profile-list"),
  jobDetail: document.getElementById("job-detail"),
  jobArtifacts: document.getElementById("job-artifacts"),
};

function headers() {
  const result = {};
  if (state.token) {
    result.Authorization = `Bearer ${state.token}`;
  }
  return result;
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: headers() });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed for ${path}`);
  }
  return payload;
}

function renderList(target, items, formatter, onClick) {
  target.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No items";
    target.appendChild(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = formatter(item);
    if (onClick) {
      li.tabIndex = 0;
      li.addEventListener("click", () => onClick(item));
    }
    target.appendChild(li);
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
  try {
    const payload = await fetchJson("/v1/pipelines");
    renderList(
      els.pipelineList,
      payload.pipelines,
      (item) => `${item.pipeline}: ${item.stages.map((stage) => stage.name).join(" -> ")}`
    );
  } catch (error) {
    els.pipelineList.innerHTML = `<li class="muted">${error.message}</li>`;
  }
}

async function refreshJobs() {
  try {
    const payload = await fetchJson("/v1/jobs");
    renderList(
      els.jobList,
      payload.jobs,
      (item) => `${item.job_id} | ${item.pipeline} | ${item.status}`,
      (item) => {
        state.selectedJobId = item.job_id;
        refreshSelectedJob();
      }
    );
  } catch (error) {
    els.jobList.innerHTML = `<li class="muted">${error.message}</li>`;
  }
}

async function refreshManuscripts() {
  try {
    const payload = await fetchJson("/v1/manuscripts");
    renderList(
      els.manuscriptList,
      payload.manuscripts,
      (item) => `${item.book_slug} | ${item.title} | owner=${item.owner_username || "n/a"}`
    );
  } catch (error) {
    els.manuscriptList.innerHTML = `<li class="muted">${error.message}</li>`;
  }
}

async function refreshConfigProfiles() {
  try {
    const payload = await fetchJson("/v1/config-profiles");
    renderList(
      els.configProfileList,
      payload.config_profiles,
      (item) => `${item.name}@${item.version} | ${item.config_path}`
    );
  } catch (error) {
    els.configProfileList.innerHTML = `<li class="muted">${error.message}</li>`;
  }
}

async function refreshSelectedJob() {
  if (!state.selectedJobId) {
    return;
  }
  try {
    const [job, artifacts] = await Promise.all([
      fetchJson(`/v1/jobs/${state.selectedJobId}`),
      fetchJson(`/v1/jobs/${state.selectedJobId}/artifacts`),
    ]);
    els.jobDetail.textContent = JSON.stringify(job, null, 2);
    els.jobArtifacts.textContent = JSON.stringify(artifacts, null, 2);
  } catch (error) {
    els.jobDetail.textContent = error.message;
    els.jobArtifacts.textContent = error.message;
  }
}

async function refreshAll() {
  await Promise.all([
    refreshSystem(),
    refreshPipelines(),
    refreshJobs(),
    refreshManuscripts(),
    refreshConfigProfiles(),
  ]);
  await refreshSelectedJob();
}

els.apiToken.value = state.token;
els.authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = els.apiToken.value.trim();
  localStorage.setItem(storageKey, state.token);
  await refreshAll();
});

for (const button of document.querySelectorAll("[data-refresh]")) {
  button.addEventListener("click", async () => {
    const target = button.getAttribute("data-refresh");
    if (target === "system") await refreshSystem();
    if (target === "pipelines") await refreshPipelines();
    if (target === "jobs") await refreshJobs();
    if (target === "manuscripts") await refreshManuscripts();
    if (target === "config-profiles") await refreshConfigProfiles();
    if (target === "selected-job") await refreshSelectedJob();
  });
}

refreshAll();
