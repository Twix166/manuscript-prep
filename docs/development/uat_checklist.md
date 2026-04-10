# UAT Checklist

This checklist is the minimum user-acceptance pass for the current `v1` stack.

## 1. Stack Startup

- Start the stack with `docker compose up --build`.
- Confirm `postgres`, `gateway`, and `worker` are running.
- Confirm `GET /health` returns `ok`.
- Confirm `GET /ready` returns `ready`.
- Confirm `GET /ui` loads the operator dashboard.

## 2. Authentication

- Confirm `/v1/jobs` rejects unauthenticated requests.
- Confirm an admin token can access `/v1/system/status`.
- Confirm a non-admin user can only see their own jobs and manuscripts.
- Confirm an admin can see all jobs.

## 3. Manuscript And Config Management

- Create a config profile through `POST /v1/config-profiles`.
- Create a manuscript through `POST /v1/manuscripts`.
- Confirm the manuscript appears in `GET /v1/manuscripts` for its owner.
- Create a job referencing `manuscript_id` and `config_profile_id`.
- Confirm the job inherits `book_slug`, `title`, `input_path`, and `config_path`.

## 4. End-To-End Pipeline

- Submit a real `manuscript-prep` job through the gateway.
- Confirm the worker claims it asynchronously.
- Confirm stage progression reaches `ingest`, `orchestrate`, `merge`, `resolve`, and `report`.
- Confirm the job reaches `succeeded`.
- Confirm the final report PDF exists and is readable.

## 5. Artifact Inspection

- Open `GET /v1/jobs/{job_id}/artifacts`.
- Confirm artifact entries include `bytes`, `sha256`, and `storage_backend`.
- Open at least one text artifact preview and one JSON artifact preview.
- Confirm the report PDF artifact path is present.

## 6. Operator UI

- Open `/ui` in a browser.
- Enter a valid API token.
- Confirm system status loads.
- Confirm jobs, manuscripts, and config profiles load.
- Select a job and confirm job detail and artifact index render correctly.

## 7. Recovery

- Restart the worker while the stack is running.
- Confirm the system returns to `ready`.
- Confirm worker heartbeat resumes in `/v1/system/status`.
- Requeue a finished or failed job and confirm it runs again.

## 8. Sign-Off

- Confirm expected operator workflow is clear in the web UI.
- Confirm the gateway-backed runtime is acceptable as the primary control plane.
- Record any blocking issues before cutting a wider release.
