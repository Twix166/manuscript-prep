# Microservices Roadmap

This document defines the first migration path from the current script-driven
pipeline to API-addressable services that can be used by a TUI client or a web
interface.

## Current Slice

The current slices introduce:

- an API-facing job model
- a pipeline and stage registry
- a pluggable job store with file-backed and PostgreSQL-backed implementations
- a minimal HTTP gateway service
- a queued worker service that claims and executes jobs
- artifact references on jobs
- per-stage command/stdout/stderr capture for gateway-managed runs
- execution adapters for `ingest`, `orchestrate`, `merge`, `resolve`, and `report`
- a single gateway-managed `manuscript-prep` job that chains all stages locally
- a `compose.yaml` stack that runs gateway, worker, and PostgreSQL together

The current scripts remain the execution backend while the API contract is
established. The gateway now queues jobs while workers execute them against the
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

1. add health, readiness, and worker heartbeat reporting
2. add a basic web UI against the same endpoints
3. introduce auth and user management on top of the PostgreSQL-backed gateway
4. split stage runners into independently deployable worker services

## Current Limitations

- file-backed persistence still exists as a fallback path and test backend
- the TUI can use the gateway, but the web UI does not exist yet
- worker retry, cancellation, and recovery semantics are still minimal

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
