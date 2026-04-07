#!/usr/bin/env python3
"""Run the ManuscriptPrep queued worker."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from manuscriptprep.execution_adapter import ExecutionAdapter
from manuscriptprep.job_worker import JobWorker
from manuscriptprep.runtime_logging import emit_runtime_event
from manuscriptprep.store_factory import create_job_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ManuscriptPrep worker.")
    parser.add_argument(
        "--jobs-root",
        default="work/gateway_jobs",
        help="Directory used for file-backed jobs or runtime default root",
    )
    parser.add_argument(
        "--runtime-root",
        default=None,
        help="Directory used for command/stdout/stderr captures",
    )
    parser.add_argument(
        "--store-backend",
        choices=["file", "postgres"],
        default=os.environ.get("MANUSCRIPTPREP_STORE_BACKEND", "file"),
        help="Persistent store backend for worker job claims",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("MANUSCRIPTPREP_DATABASE_URL"),
        help="PostgreSQL connection string used when --store-backend=postgres",
    )
    parser.add_argument(
        "--postgres-schema",
        default=os.environ.get("MANUSCRIPTPREP_POSTGRES_SCHEMA", "public"),
        help="PostgreSQL schema used for gateway job tables",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("MANUSCRIPTPREP_WORKER_POLL_INTERVAL", "1.0")),
        help="Seconds between queue polls when no job is available",
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get("MANUSCRIPTPREP_WORKER_ID"),
        help="Optional explicit worker identifier",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=int(os.environ.get("MANUSCRIPTPREP_WORKER_STALE_AFTER_SECONDS", "600")),
        help="Requeue running jobs older than this age when the worker starts",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs_root = Path(args.jobs_root)
    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else jobs_root / "runtime"
    store = create_job_store(
        backend=args.store_backend,
        jobs_root=jobs_root,
        database_url=args.database_url,
        postgres_schema=args.postgres_schema,
    )
    adapter = ExecutionAdapter(runtime_root=runtime_root)
    worker = JobWorker(
        store=store,
        adapter=adapter,
        worker_id=args.worker_id,
        poll_interval=args.poll_interval,
        stale_after_seconds=args.stale_after_seconds,
    )
    emit_runtime_event(
        "worker",
        "startup",
        worker_id=worker.worker_id,
        poll_interval=args.poll_interval,
        stale_after_seconds=args.stale_after_seconds,
        store_backend=store.__class__.__name__,
    )
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
