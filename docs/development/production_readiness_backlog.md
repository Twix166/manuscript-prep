# Production Readiness Backlog

This backlog tracks the work needed to move ManuscriptPrep from a working local stack to a production-capable service platform.

## Principles

- keep the existing pipeline behavior stable
- prefer additive infrastructure changes over rewrites
- separate control plane concerns from execution concerns
- keep artifacts inspectable and auditable
- make recovery and operations first-class

## P0: Asynchronous Execution

Goal: stop running long manuscript jobs inside the gateway process.

- add a queued job model in PostgreSQL
- add a worker service that claims and runs queued jobs
- change gateway job submission to enqueue instead of execute inline
- add worker-safe job claiming and heartbeat updates
- add retryable terminal and non-terminal job states

Why this matters:
- synchronous execution in the gateway is the main operational bottleneck and failure risk
- production API services should stay responsive while workers handle long-running tasks

Suggested deliverables:
- `gateway` service for API only
- `worker` service for execution
- queued job lifecycle with atomic claims

## P1: Operational Health and Recovery

Goal: make the stack observable and restart-safe.

- add readiness and liveness endpoints
- report active persistence backend and DB connectivity
- add worker heartbeat and queue depth reporting
- add restart recovery for jobs stuck in `running`
- document failure recovery and requeue workflows

Why this matters:
- once jobs move to workers, operations need direct visibility into service health and queue state

Suggested deliverables:
- `/health`
- `/ready`
- `/v1/system/status`
- restart-safe recovery policy for interrupted jobs

## P2: Authentication and Identity

Goal: prepare the API for multi-user access.

- add user accounts and auth tokens
- add user-to-job ownership
- add user-scoped manuscript and artifact access rules
- add service roles for gateway and worker operations

Why this matters:
- user management and manuscript management are only safe after persistence and execution control are stable

Suggested deliverables:
- users table
- auth flow
- ownership checks on job and artifact endpoints

Status:
- implemented bootstrap admin token support
- added token-based access control for `/v1/*`
- added job ownership enforcement with admin override

## P3: Manuscript and Configuration Management

Goal: move from ad hoc file inputs toward managed domain records.

- add manuscript records in PostgreSQL
- store per-manuscript metadata and stage history
- add managed pipeline configuration profiles
- add versioned runtime configuration references on jobs

Why this matters:
- production systems need durable references to manuscripts, runs, configs, and outputs

Suggested deliverables:
- manuscripts table
- configuration profiles table
- job-to-manuscript and job-to-config foreign keys

Status:
- implemented managed manuscript records in the gateway store
- implemented managed configuration profiles in the gateway store
- jobs can now carry manuscript and config profile references

## P4: Artifact Storage Hardening

Goal: separate metadata storage from durable artifact storage.

- define an artifact storage abstraction
- keep local filesystem storage as one backend
- add object storage support later if needed
- add retention and cleanup policies
- add checksums for important output artifacts

Why this matters:
- PostgreSQL should store metadata and references, not large generated artifacts

Suggested deliverables:
- artifact metadata table
- artifact storage adapter
- retention policy docs

## P5: Deployment and Security Hardening

Goal: turn the compose stack into a secure deployable baseline.

- move secrets out of `compose.yaml`
- add environment-driven config for passwords and connection strings
- run gateway and worker as non-root containers
- add reverse proxy / TLS termination strategy
- add structured logs for containers and services

Why this matters:
- the current compose stack is fine for development verification but not for production deployment

Suggested deliverables:
- `.env.example`
- hardened container config
- deployment checklist

## P6: Web UI and Operator Experience

Goal: provide a production-facing interface on top of the stable API.

- add a minimal web UI for jobs, manuscripts, and artifacts
- add live job progress views
- add artifact browsing and downloads
- keep the TUI as an operator-focused client

Why this matters:
- once the control plane is stable, the same API should support both operator and end-user workflows

Suggested deliverables:
- web job list
- web job detail
- artifact viewer

## Recommended Build Order

1. queued worker execution
2. health, readiness, and recovery
3. auth and user ownership
4. manuscript and configuration management
5. artifact storage hardening
6. deployment/security hardening
7. web UI

## Immediate Next Slice

The best next implementation slice is:

1. add a worker service to `compose.yaml`
2. add queued execution in PostgreSQL
3. make the gateway return immediately after job submission
4. add worker claim/retry/recovery semantics

That is the point where the stack starts acting like a real production microservice platform rather than a synchronous API wrapper.
