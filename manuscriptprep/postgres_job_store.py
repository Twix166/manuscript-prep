"""PostgreSQL-backed job store for gateway persistence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from manuscriptprep.api_models import JobCreateRequest, JobRecord, utc_now_iso
from manuscriptprep.job_store import BaseJobStore, _job_from_dict, create_job_record


class PostgresJobStore(BaseJobStore):
    def __init__(self, database_url: str, schema: str = "public") -> None:
        self.database_url = database_url
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError(f"Invalid PostgreSQL schema name: {schema}")
        self.schema = schema
        self.root = Path("work/gateway_jobs")
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "psycopg is required for PostgreSQL job storage. Install with: pip install psycopg[binary]"
            ) from exc

        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self, *, autocommit: bool = True):
        return self._psycopg.connect(self.database_url, autocommit=autocommit)

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.gateway_jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_gateway_jobs_created_at
                ON {self.schema}.gateway_jobs (created_at DESC)
                """
            )

    def _row_to_job(self, payload: Any) -> JobRecord:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return _job_from_dict(data)

    def create_job(self, request: JobCreateRequest) -> JobRecord:
        job = create_job_record(request)
        payload = json.dumps(asdict(job), ensure_ascii=False)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.gateway_jobs (job_id, created_at, updated_at, payload)
                VALUES (%s, %s::timestamptz, %s::timestamptz, %s::jsonb)
                """,
                (job.job_id, job.created_at, job.updated_at, payload),
            )
        return self._row_to_job(asdict(job))

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT payload FROM {self.schema}.gateway_jobs WHERE job_id = %s",
                (job_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_job(row[0])

    def list_jobs(self) -> list[JobRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT payload FROM {self.schema}.gateway_jobs ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        return [self._row_to_job(row[0]) for row in rows]

    def update_job(self, job: JobRecord) -> JobRecord:
        payload = json.dumps(asdict(job), ensure_ascii=False)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self.schema}.gateway_jobs
                SET updated_at = %s::timestamptz, payload = %s::jsonb
                WHERE job_id = %s
                """,
                (job.updated_at, payload, job.job_id),
            )
        return self._row_to_job(asdict(job))

    def claim_next_job(self, worker_id: str) -> Optional[JobRecord]:
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_id, payload
                FROM {self.schema}.gateway_jobs
                WHERE payload->>'status' = 'queued'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None

            job_id, payload = row
            job = self._row_to_job(payload)
            now = utc_now_iso()
            job.status = "running"
            job.updated_at = now
            if job.stage_runs:
                job.stage_runs[0].status = "running"
                job.stage_runs[0].started_at = job.stage_runs[0].started_at or now
            job.options = {
                **job.options,
                "_worker_id": worker_id,
                "_claimed_at": now,
            }
            cur.execute(
                f"""
                UPDATE {self.schema}.gateway_jobs
                SET updated_at = %s::timestamptz, payload = %s::jsonb
                WHERE job_id = %s
                """,
                (job.updated_at, json.dumps(asdict(job), ensure_ascii=False), job_id),
            )
            conn.commit()
            return self._row_to_job(asdict(job))
