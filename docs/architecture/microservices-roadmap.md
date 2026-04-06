# Microservices Roadmap

This document defines the first migration path from the current script-driven
pipeline to API-addressable services that can be used by a TUI client or a web
interface.

## Current Slice

The current slices introduce:

- an API-facing job model
- a pipeline and stage registry
- a persistent file-backed job store
- a minimal HTTP gateway service
- artifact references on jobs
- synchronous execution adapters for `ingest`, `orchestrate`, `merge`, `resolve`, and `report`

The current scripts remain the execution backend while the API contract is
established. The gateway can now create and run stage jobs against the
existing CLI implementations.

## Initial Gateway Endpoints

- `GET /health`
- `GET /v1/pipelines`
- `GET /v1/jobs`
- `POST /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `POST /v1/jobs/{job_id}/run`

## Immediate Follow-Up Slices

1. add execution adapters for orchestrate, merge, resolve, and report
2. attach richer artifact metadata and stage logs to jobs
3. update the TUI to consume the gateway instead of calling scripts directly
4. add a basic web UI against the same endpoints
5. replace file-backed jobs with a database-backed store when concurrency needs it

## Current Limitations

- execution is synchronous
- jobs are persisted as local JSON files, not database records
- there is not yet a single gateway endpoint that runs the full multi-stage pipeline as one long-lived job
- the TUI and web UI have not yet been switched to consume the gateway

## Target Service Split

- gateway-api
- ingest-service
- orchestrator-service
- merge-service
- resolver-service
- report-service
- persistent job store
- artifact store
- event stream for live progress
