"""PostgreSQL-backed job store for gateway persistence."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from manuscriptprep.api_models import (
    ArtifactRef,
    ConfigProfileRecord,
    JobCreateRequest,
    JobRecord,
    ManuscriptRecord,
    UserRecord,
    WorkerHeartbeat,
    utc_now_iso,
)
from manuscriptprep.job_store import (
    BaseJobStore,
    _config_profile_from_dict,
    _job_from_dict,
    _manuscript_from_dict,
    _user_from_dict,
    create_job_record,
)


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
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.schema}.schema_bootstrap",))
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
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.gateway_workers (
                    worker_id TEXT PRIMARY KEY,
                    heartbeat_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL,
                    last_job_id TEXT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.gateway_users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL,
                    api_token TEXT NOT NULL UNIQUE,
                    password_hash TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                ALTER TABLE {self.schema}.gateway_users
                ADD COLUMN IF NOT EXISTS password_hash TEXT NULL
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.gateway_manuscripts (
                    manuscript_id TEXT PRIMARY KEY,
                    book_slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    file_size_bytes BIGINT NULL,
                    owner_user_id TEXT NULL,
                    owner_username TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.gateway_config_profiles (
                    config_profile_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config_path TEXT NOT NULL,
                    version TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (name, version)
                )
                """
            )
            cur.execute(
                f"""
                ALTER TABLE {self.schema}.gateway_config_profiles
                ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                """
            )
            cur.execute(
                f"""
                ALTER TABLE {self.schema}.gateway_manuscripts
                ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT NULL
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.gateway_artifacts (
                    job_id TEXT NOT NULL,
                    artifact_name TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (job_id, artifact_name)
                )
                """
            )
            conn.commit()

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
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self.schema}.gateway_jobs
                SET updated_at = %s::timestamptz, payload = %s::jsonb
                WHERE job_id = %s
                """,
                (job.updated_at, payload, job.job_id),
            )
            cur.execute(
                f"DELETE FROM {self.schema}.gateway_artifacts WHERE job_id = %s",
                (job.job_id,),
            )
            for artifact in job.artifacts:
                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.gateway_artifacts (job_id, artifact_name, payload)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (job.job_id, artifact.name, json.dumps(asdict(artifact), ensure_ascii=False)),
                )
            conn.commit()
        return self._row_to_job(asdict(job))

    def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> Optional[JobRecord]:
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT payload
                FROM {self.schema}.gateway_jobs
                WHERE job_id = %s
                FOR UPDATE
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None

            job = self._row_to_job(row[0])
            if job.status in {"succeeded", "failed", "cancelled"}:
                conn.commit()
                return job

            now = utc_now_iso()
            active_stage = next((stage for stage in job.stage_runs if stage.status == "running"), None)
            if job.status == "queued":
                job.status = "cancelled"
                if active_stage is None and job.stage_runs:
                    active_stage = job.stage_runs[0]
                if active_stage is not None:
                    active_stage.status = "cancelled"
                    active_stage.finished_at = now
                    active_stage.error = reason
            else:
                job.status = "cancel_requested"
                if active_stage is not None:
                    active_stage.error = reason

            job.updated_at = now
            job.options = {
                **job.options,
                "_cancel_requested_at": now,
                "_cancel_reason": reason,
            }
            cur.execute(
                f"""
                UPDATE {self.schema}.gateway_jobs
                SET updated_at = %s::timestamptz, payload = %s::jsonb
                WHERE job_id = %s
                """,
                (job.updated_at, json.dumps(asdict(job), ensure_ascii=False), job.job_id),
            )
            conn.commit()
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

    def record_worker_heartbeat(self, worker_id: str, status: str, last_job_id: Optional[str] = None) -> None:
        heartbeat_at = utc_now_iso()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.gateway_workers (worker_id, heartbeat_at, status, last_job_id)
                VALUES (%s, %s::timestamptz, %s, %s)
                ON CONFLICT (worker_id) DO UPDATE
                SET heartbeat_at = EXCLUDED.heartbeat_at,
                    status = EXCLUDED.status,
                    last_job_id = EXCLUDED.last_job_id
                """,
                (worker_id, heartbeat_at, status, last_job_id),
            )

    def list_worker_heartbeats(self) -> list[WorkerHeartbeat]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT worker_id, status, heartbeat_at, last_job_id
                FROM {self.schema}.gateway_workers
                ORDER BY heartbeat_at DESC
                """
            )
            rows = cur.fetchall()
        return [
            WorkerHeartbeat(
                worker_id=row[0],
                status=row[1],
                heartbeat_at=row[2].isoformat(),
                last_job_id=row[3],
            )
            for row in rows
        ]

    def queue_summary(self) -> dict[str, int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT payload->>'status' AS status, COUNT(*)
                FROM {self.schema}.gateway_jobs
                GROUP BY payload->>'status'
                """
            )
            rows = cur.fetchall()
        summary: dict[str, int] = {
            "queued": 0,
            "running": 0,
            "cancel_requested": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
        }
        total = 0
        for status, count in rows:
            summary[str(status)] = int(count)
            total += int(count)
        summary["total"] = total
        return summary

    def recover_stale_running_jobs(self, stale_after_seconds: int, recovery_worker_id: str) -> list[str]:
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_id, payload
                FROM {self.schema}.gateway_jobs
                WHERE payload->>'status' = 'running'
                  AND ((payload->'options'->>'_claimed_at')::timestamptz < (NOW() - (%s || ' seconds')::interval))
                FOR UPDATE
                """,
                (str(stale_after_seconds),),
            )
            rows = cur.fetchall()
            recovered: list[str] = []
            for job_id, payload in rows:
                job = self._row_to_job(payload)
                job.status = "queued"
                job.updated_at = utc_now_iso()
                for stage in job.stage_runs:
                    if stage.status == "running":
                        stage.status = "pending"
                        stage.started_at = None
                        stage.finished_at = None
                        stage.error = "Recovered from stale running state"
                        break
                job.options = {
                    **job.options,
                    "_recovered_by": recovery_worker_id,
                    "_recovered_at": job.updated_at,
                }
                cur.execute(
                    f"""
                    UPDATE {self.schema}.gateway_jobs
                    SET updated_at = %s::timestamptz, payload = %s::jsonb
                    WHERE job_id = %s
                    """,
                    (job.updated_at, json.dumps(asdict(job), ensure_ascii=False), job_id),
                )
                recovered.append(job_id)
            conn.commit()
            return recovered

    def finalize_stale_cancel_requests(self, stale_after_seconds: int) -> list[str]:
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_id, payload
                FROM {self.schema}.gateway_jobs
                WHERE payload->>'status' = 'cancel_requested'
                  AND COALESCE(
                        (payload->'options'->>'_cancel_requested_at')::timestamptz,
                        updated_at
                      ) < (NOW() - (%s || ' seconds')::interval)
                FOR UPDATE
                """,
                (str(stale_after_seconds),),
            )
            rows = cur.fetchall()
            finalized: list[str] = []
            for job_id, payload in rows:
                job = self._row_to_job(payload)
                job.status = "cancelled"
                job.updated_at = utc_now_iso()
                for stage in job.stage_runs:
                    if stage.status == "running":
                        stage.status = "cancelled"
                        stage.finished_at = job.updated_at
                        stage.error = stage.error or "Cancelled by housekeeping"
                        break
                cur.execute(
                    f"""
                    UPDATE {self.schema}.gateway_jobs
                    SET updated_at = %s::timestamptz, payload = %s::jsonb
                    WHERE job_id = %s
                    """,
                    (job.updated_at, json.dumps(asdict(job), ensure_ascii=False), job_id),
                )
                finalized.append(job_id)
            conn.commit()
            return finalized

    def is_ready(self) -> bool:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception:
            return False

    def upsert_user(self, username: str, role: str, api_token: str, password_hash: Optional[str] = None) -> UserRecord:
        now = utc_now_iso()
        user = UserRecord(
            user_id="",
            username=username,
            role=role,
            api_token=api_token,
            created_at=now,
            updated_at=now,
            password_hash=password_hash,
        )
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT user_id, created_at, password_hash
                FROM {self.schema}.gateway_users
                WHERE api_token = %s OR username = %s
                FOR UPDATE
                """,
                (api_token, username),
            )
            row = cur.fetchone()
            if row is None:
                from uuid import uuid4

                user.user_id = str(uuid4())
                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.gateway_users
                        (user_id, username, role, api_token, password_hash, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                    """,
                    (user.user_id, username, role, api_token, password_hash, user.created_at, user.updated_at),
                )
            else:
                user.user_id = row[0]
                user.created_at = row[1].isoformat()
                user.password_hash = password_hash if password_hash is not None else row[2]
                cur.execute(
                    f"""
                    UPDATE {self.schema}.gateway_users
                    SET username = %s,
                        role = %s,
                        api_token = %s,
                        password_hash = %s,
                        updated_at = %s::timestamptz
                    WHERE user_id = %s
                    """,
                    (username, role, api_token, user.password_hash, user.updated_at, user.user_id),
                )
            conn.commit()
        return _user_from_dict(asdict(user))

    def get_user_by_token(self, api_token: str) -> Optional[UserRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT user_id, username, role, api_token, created_at, updated_at, password_hash
                FROM {self.schema}.gateway_users
                WHERE api_token = %s
                """,
                (api_token,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _user_from_dict(
            {
                "user_id": row[0],
                "username": row[1],
                "role": row[2],
                "api_token": row[3],
                "created_at": row[4].isoformat(),
                "updated_at": row[5].isoformat(),
                "password_hash": row[6],
            }
        )

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT user_id, username, role, api_token, created_at, updated_at, password_hash
                FROM {self.schema}.gateway_users
                WHERE username = %s
                """,
                (username,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _user_from_dict(
            {
                "user_id": row[0],
                "username": row[1],
                "role": row[2],
                "api_token": row[3],
                "created_at": row[4].isoformat(),
                "updated_at": row[5].isoformat(),
                "password_hash": row[6],
            }
        )

    def upsert_manuscript(
        self,
        *,
        book_slug: str,
        title: str,
        source_path: str,
        file_size_bytes: Optional[int],
        owner_user_id: Optional[str],
        owner_username: Optional[str],
    ) -> ManuscriptRecord:
        now = utc_now_iso()
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT manuscript_id, created_at
                FROM {self.schema}.gateway_manuscripts
                WHERE book_slug = %s AND owner_user_id IS NOT DISTINCT FROM %s
                FOR UPDATE
                """,
                (book_slug, owner_user_id),
            )
            row = cur.fetchone()
            if row is None:
                from uuid import uuid4

                manuscript_id = str(uuid4())
                created_at = now
                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.gateway_manuscripts
                        (manuscript_id, book_slug, title, source_path, file_size_bytes, owner_user_id, owner_username, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                    """,
                    (manuscript_id, book_slug, title, source_path, file_size_bytes, owner_user_id, owner_username, created_at, now),
                )
            else:
                manuscript_id = row[0]
                created_at = row[1].isoformat()
                cur.execute(
                    f"""
                        UPDATE {self.schema}.gateway_manuscripts
                        SET title = %s,
                            source_path = %s,
                            file_size_bytes = %s,
                            owner_user_id = %s,
                            owner_username = %s,
                            updated_at = %s::timestamptz
                        WHERE manuscript_id = %s
                    """,
                    (title, source_path, file_size_bytes, owner_user_id, owner_username, now, manuscript_id),
                )
            conn.commit()
        return _manuscript_from_dict(
            {
                "manuscript_id": manuscript_id,
                "book_slug": book_slug,
                "title": title,
                "source_path": source_path,
                "file_size_bytes": file_size_bytes,
                "owner_user_id": owner_user_id,
                "owner_username": owner_username,
                "created_at": created_at,
                "updated_at": now,
            }
        )

    def get_manuscript(self, manuscript_id: str) -> Optional[ManuscriptRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT manuscript_id, book_slug, title, source_path, file_size_bytes, owner_user_id, owner_username, created_at, updated_at
                FROM {self.schema}.gateway_manuscripts
                WHERE manuscript_id = %s
                """,
                (manuscript_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _manuscript_from_dict(
            {
                "manuscript_id": row[0],
                "book_slug": row[1],
                "title": row[2],
                "source_path": row[3],
                "file_size_bytes": row[4],
                "owner_user_id": row[5],
                "owner_username": row[6],
                "created_at": row[7].isoformat(),
                "updated_at": row[8].isoformat(),
            }
        )

    def list_manuscripts(self) -> list[ManuscriptRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT manuscript_id, book_slug, title, source_path, file_size_bytes, owner_user_id, owner_username, created_at, updated_at
                FROM {self.schema}.gateway_manuscripts
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
        return [
            _manuscript_from_dict(
                {
                    "manuscript_id": row[0],
                    "book_slug": row[1],
                    "title": row[2],
                    "source_path": row[3],
                    "file_size_bytes": row[4],
                    "owner_user_id": row[5],
                    "owner_username": row[6],
                    "created_at": row[7].isoformat(),
                    "updated_at": row[8].isoformat(),
                }
            )
            for row in rows
        ]

    def update_manuscript(
        self,
        manuscript_id: str,
        *,
        book_slug: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[ManuscriptRecord]:
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT manuscript_id, book_slug, title, source_path, file_size_bytes, owner_user_id, owner_username, created_at, updated_at
                FROM {self.schema}.gateway_manuscripts
                WHERE manuscript_id = %s
                FOR UPDATE
                """,
                (manuscript_id,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            now = utc_now_iso()
            next_book_slug = book_slug or row[1]
            next_title = title or row[2]
            cur.execute(
                f"""
                UPDATE {self.schema}.gateway_manuscripts
                SET book_slug = %s,
                    title = %s,
                    updated_at = %s::timestamptz
                WHERE manuscript_id = %s
                """,
                (next_book_slug, next_title, now, manuscript_id),
            )
            conn.commit()
            return _manuscript_from_dict(
                {
                    "manuscript_id": row[0],
                    "book_slug": next_book_slug,
                    "title": next_title,
                    "source_path": row[3],
                    "file_size_bytes": row[4],
                    "owner_user_id": row[5],
                    "owner_username": row[6],
                    "created_at": row[7].isoformat(),
                    "updated_at": now,
                }
            )

    def delete_manuscript(self, manuscript_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self.schema}.gateway_manuscripts WHERE manuscript_id = %s",
                (manuscript_id,),
            )
            return cur.rowcount > 0

    def upsert_config_profile(
        self,
        *,
        name: str,
        config_path: str,
        version: str,
        checksum: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> ConfigProfileRecord:
        now = utc_now_iso()
        profile_metadata = dict(metadata or {})
        with self._connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT config_profile_id, created_at
                FROM {self.schema}.gateway_config_profiles
                WHERE name = %s AND version = %s
                FOR UPDATE
                """,
                (name, version),
            )
            row = cur.fetchone()
            if row is None:
                from uuid import uuid4

                profile_id = str(uuid4())
                created_at = now
                cur.execute(
                    f"""
                    INSERT INTO {self.schema}.gateway_config_profiles
                        (config_profile_id, name, config_path, version, checksum, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::timestamptz, %s::timestamptz)
                    """,
                    (profile_id, name, config_path, version, checksum, json.dumps(profile_metadata, ensure_ascii=False), created_at, now),
                )
            else:
                profile_id = row[0]
                created_at = row[1].isoformat()
                cur.execute(
                    f"""
                    UPDATE {self.schema}.gateway_config_profiles
                    SET config_path = %s,
                        checksum = %s,
                        metadata = %s::jsonb,
                        updated_at = %s::timestamptz
                    WHERE config_profile_id = %s
                    """,
                    (config_path, checksum, json.dumps(profile_metadata, ensure_ascii=False), now, profile_id),
                )
            conn.commit()
        return _config_profile_from_dict(
            {
                "config_profile_id": profile_id,
                "name": name,
                "config_path": config_path,
                "version": version,
                "checksum": checksum,
                "metadata": profile_metadata,
                "created_at": created_at,
                "updated_at": now,
            }
        )

    def get_config_profile(self, config_profile_id: str) -> Optional[ConfigProfileRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT config_profile_id, name, config_path, version, checksum, metadata, created_at, updated_at
                FROM {self.schema}.gateway_config_profiles
                WHERE config_profile_id = %s
                """,
                (config_profile_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _config_profile_from_dict(
            {
                "config_profile_id": row[0],
                "name": row[1],
                "config_path": row[2],
                "version": row[3],
                "checksum": row[4],
                "metadata": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                "created_at": row[6].isoformat(),
                "updated_at": row[7].isoformat(),
            }
        )

    def list_config_profiles(self) -> list[ConfigProfileRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT config_profile_id, name, config_path, version, checksum, metadata, created_at, updated_at
                FROM {self.schema}.gateway_config_profiles
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
        return [
            _config_profile_from_dict(
                {
                    "config_profile_id": row[0],
                    "name": row[1],
                    "config_path": row[2],
                    "version": row[3],
                    "checksum": row[4],
                    "metadata": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
                    "created_at": row[6].isoformat(),
                    "updated_at": row[7].isoformat(),
                }
            )
            for row in rows
        ]

    def list_job_artifacts(self, job_id: str) -> list[ArtifactRef]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT payload
                FROM {self.schema}.gateway_artifacts
                WHERE job_id = %s
                ORDER BY artifact_name ASC
                """,
                (job_id,),
            )
            rows = cur.fetchall()
        return [ArtifactRef(**(json.loads(row[0]) if isinstance(row[0], str) else row[0])) for row in rows]
