---
name: UAT Checklist
about: Run the standard user-acceptance checklist for a release candidate or milestone
title: "UAT: <release or milestone>"
labels: ["uat"]
assignees: []
---

## Scope

- Release or milestone:
- Environment:
- Build/tag/commit:
- Tester:

## Startup

- [ ] `docker compose up --build` completed successfully
- [ ] `postgres`, `gateway`, and `worker` are healthy
- [ ] `GET /health` returns `ok`
- [ ] `GET /ready` returns `ready`
- [ ] `GET /ui` loads the operator dashboard

## Authentication

- [ ] `/v1/jobs` rejects unauthenticated requests
- [ ] Admin token can access `/v1/system/status`
- [ ] Non-admin user only sees owned jobs and manuscripts
- [ ] Admin can see all jobs

## Manuscripts And Config Profiles

- [ ] Config profile creation works
- [ ] Manuscript creation works
- [ ] Owner-scoped manuscript listing works
- [ ] Job creation from `manuscript_id` and `config_profile_id` works

## End-To-End Pipeline

- [ ] A real `manuscript-prep` job was submitted
- [ ] Worker claimed the job asynchronously
- [ ] All stages completed successfully
- [ ] Final report PDF exists and is readable

## Artifact Inspection

- [ ] Artifact index endpoint returns results
- [ ] Artifact metadata includes `bytes`, `sha256`, and `storage_backend`
- [ ] Text/JSON previews are readable

## Operator UI

- [ ] Dashboard loads with a valid API token
- [ ] System status renders correctly
- [ ] Jobs render correctly
- [ ] Manuscripts render correctly
- [ ] Config profiles render correctly
- [ ] Selected job detail and artifact index render correctly

## Recovery

- [ ] Worker restart recovery was checked
- [ ] Requeue behavior was checked

## Notes

- Blocking issues:
- Non-blocking issues:
- Suggested follow-up:
