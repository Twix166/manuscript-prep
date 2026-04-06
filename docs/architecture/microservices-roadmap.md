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
- per-stage command/stdout/stderr capture for gateway-managed runs
- synchronous execution adapters for `ingest`, `orchestrate`, `merge`, `resolve`, and `report`
- a single gateway-managed `manuscript-prep` job that chains all stages locally

The current scripts remain the execution backend while the API contract is
established. The gateway can now create and run stage jobs against the
existing CLI implementations.

## Initial Gateway Endpoints

- `GET /health`
- `GET /v1/pipelines`
- `GET /v1/jobs`
- `POST /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/artifacts/{artifact_name}`
- `POST /v1/jobs/{job_id}/run`

## Immediate Follow-Up Slices

1. update the TUI to consume the gateway instead of calling scripts directly
2. add a basic web UI against the same endpoints
3. replace file-backed jobs with a database-backed store when concurrency needs it
4. add asynchronous workers and queue-backed execution

## Current Limitations

- execution is synchronous
- jobs are persisted as local JSON files, not database records
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
