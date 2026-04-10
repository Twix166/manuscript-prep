"""Store selection for gateway persistence backends."""

from __future__ import annotations

from pathlib import Path

from manuscriptprep.job_store import BaseJobStore, JobStore
from manuscriptprep.postgres_job_store import PostgresJobStore


def create_job_store(
    *,
    backend: str,
    jobs_root: Path | None = None,
    database_url: str | None = None,
    postgres_schema: str = "public",
) -> BaseJobStore:
    normalized = backend.strip().lower()
    if normalized == "file":
        return JobStore(root=jobs_root)
    if normalized == "postgres":
        if not database_url:
            raise ValueError("PostgreSQL job storage requires a database URL.")
        return PostgresJobStore(database_url=database_url, schema=postgres_schema)
    raise ValueError(f"Unsupported job store backend: {backend}")
