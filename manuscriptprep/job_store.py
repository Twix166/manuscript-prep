"""Persistent file-backed job store for the gateway slices."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from manuscriptprep.api_models import (
    ArtifactRef,
    ConfigProfileRecord,
    JobCreateRequest,
    JobRecord,
    ManuscriptRecord,
    StageRun,
    UserRecord,
    WorkerHeartbeat,
    utc_now_iso,
)
from manuscriptprep.service_registry import get_pipeline_definition


def _job_from_dict(data: Dict) -> JobRecord:
    return JobRecord(
        job_id=data["job_id"],
        pipeline=data["pipeline"],
        status=data["status"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        book_slug=data.get("book_slug"),
        title=data.get("title"),
        manuscript_id=data.get("manuscript_id"),
        config_profile_id=data.get("config_profile_id"),
        config_path=data.get("config_path"),
        input_path=data.get("input_path"),
        owner_user_id=data.get("owner_user_id"),
        owner_username=data.get("owner_username"),
        options=data.get("options", {}) or {},
        stage_runs=[StageRun(**item) for item in data.get("stage_runs", [])],
        artifacts=[ArtifactRef(**item) for item in data.get("artifacts", [])],
    )


def create_job_record(request: JobCreateRequest) -> JobRecord:
    definition = get_pipeline_definition(request.pipeline)
    if definition is None:
        raise ValueError(f"Unknown pipeline: {request.pipeline}")

    now = utc_now_iso()
    return JobRecord(
        job_id=str(uuid4()),
        pipeline=request.pipeline,
        status="queued",
        created_at=now,
        updated_at=now,
        book_slug=request.book_slug,
        title=request.title,
        manuscript_id=request.manuscript_id,
        config_profile_id=request.config_profile_id,
        config_path=request.config_path,
        input_path=request.input_path,
        owner_user_id=request.owner_user_id,
        owner_username=request.owner_username,
        options=dict(request.options),
        stage_runs=[StageRun(name=stage.name, status="pending") for stage in definition.stages],
        artifacts=[],
    )


def _user_from_dict(data: Dict) -> UserRecord:
    return UserRecord(
        user_id=data["user_id"],
        username=data["username"],
        role=data["role"],
        api_token=data["api_token"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        password_hash=data.get("password_hash"),
    )


def _manuscript_from_dict(data: Dict) -> ManuscriptRecord:
    return ManuscriptRecord(
        manuscript_id=data["manuscript_id"],
        book_slug=data["book_slug"],
        title=data["title"],
        source_path=data["source_path"],
        document_type=data.get("document_type"),
        file_size_bytes=data.get("file_size_bytes"),
        owner_user_id=data.get("owner_user_id"),
        owner_username=data.get("owner_username"),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _config_profile_from_dict(data: Dict) -> ConfigProfileRecord:
    return ConfigProfileRecord(
        config_profile_id=data["config_profile_id"],
        name=data["name"],
        config_path=data["config_path"],
        version=data["version"],
        checksum=data["checksum"],
        metadata=data.get("metadata", {}) or {},
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


class BaseJobStore(ABC):
    @abstractmethod
    def create_job(self, request: JobCreateRequest) -> JobRecord:
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_jobs(self) -> List[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def update_job(self, job: JobRecord) -> JobRecord:
        raise NotImplementedError

    @abstractmethod
    def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> Optional[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def pause_job(self, job_id: str, reason: str = "Paused by user") -> Optional[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def claim_next_job(
        self,
        worker_id: str,
        *,
        include_pipelines: Optional[List[str]] = None,
        exclude_pipelines: Optional[List[str]] = None,
    ) -> Optional[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def record_worker_heartbeat(self, worker_id: str, status: str, last_job_id: Optional[str] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_worker_heartbeats(self) -> List[WorkerHeartbeat]:
        raise NotImplementedError

    @abstractmethod
    def queue_summary(self) -> Dict[str, int]:
        raise NotImplementedError

    @abstractmethod
    def recover_stale_running_jobs(self, stale_after_seconds: int, recovery_worker_id: str) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def finalize_stale_cancel_requests(self, stale_after_seconds: int) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def is_ready(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def upsert_user(self, username: str, role: str, api_token: str, password_hash: Optional[str] = None) -> UserRecord:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_token(self, api_token: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert_manuscript(
        self,
        *,
        book_slug: str,
        title: str,
        source_path: str,
        document_type: Optional[str],
        file_size_bytes: Optional[int],
        owner_user_id: Optional[str],
        owner_username: Optional[str],
    ) -> ManuscriptRecord:
        raise NotImplementedError

    @abstractmethod
    def get_manuscript(self, manuscript_id: str) -> Optional[ManuscriptRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_manuscripts(self) -> List[ManuscriptRecord]:
        raise NotImplementedError

    @abstractmethod
    def update_manuscript(
        self,
        manuscript_id: str,
        *,
        book_slug: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[ManuscriptRecord]:
        raise NotImplementedError

    @abstractmethod
    def delete_manuscript(self, manuscript_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def upsert_config_profile(
        self,
        *,
        name: str,
        config_path: str,
        version: str,
        checksum: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> ConfigProfileRecord:
        raise NotImplementedError

    @abstractmethod
    def get_config_profile(self, config_profile_id: str) -> Optional[ConfigProfileRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_config_profiles(self) -> List[ConfigProfileRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_job_artifacts(self, job_id: str) -> List[ArtifactRef]:
        raise NotImplementedError


class JobStore(BaseJobStore):
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path("work/gateway_jobs")).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._jobs: Dict[str, JobRecord] = {}
        self._workers: Dict[str, WorkerHeartbeat] = {}
        self._users: Dict[str, UserRecord] = {}
        self._manuscripts: Dict[str, ManuscriptRecord] = {}
        self._config_profiles: Dict[str, ConfigProfileRecord] = {}
        self._artifact_index: Dict[str, List[ArtifactRef]] = {}
        self._load_existing_jobs()

    def _job_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def _workers_path(self) -> Path:
        return self.root / "_workers.json"

    def _users_path(self) -> Path:
        return self.root / "_users.json"

    def _manuscripts_path(self) -> Path:
        return self.root / "_manuscripts.json"

    def _config_profiles_path(self) -> Path:
        return self.root / "_config_profiles.json"

    def _artifact_index_path(self) -> Path:
        return self.root / "_artifact_index.json"

    def _persist(self, job: JobRecord) -> None:
        self._job_path(job.job_id).write_text(
            json.dumps(asdict(job), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _persist_workers(self) -> None:
        self._workers_path().write_text(
            json.dumps([asdict(worker) for worker in self._workers.values()], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _persist_users(self) -> None:
        self._users_path().write_text(
            json.dumps([asdict(user) for user in self._users.values()], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _persist_manuscripts(self) -> None:
        self._manuscripts_path().write_text(
            json.dumps([asdict(item) for item in self._manuscripts.values()], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _persist_config_profiles(self) -> None:
        self._config_profiles_path().write_text(
            json.dumps([asdict(item) for item in self._config_profiles.values()], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _persist_artifact_index(self) -> None:
        serializable = {
            job_id: [asdict(item) for item in artifacts]
            for job_id, artifacts in self._artifact_index.items()
        }
        self._artifact_index_path().write_text(
            json.dumps(serializable, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _load_existing_jobs(self) -> None:
        for path in sorted(self.root.glob("*.json")):
            if path.name == "_workers.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self._workers = {item["worker_id"]: WorkerHeartbeat(**item) for item in data}
                continue
            if path.name == "_users.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self._users = {item["api_token"]: _user_from_dict(item) for item in data}
                continue
            if path.name == "_manuscripts.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self._manuscripts = {item["manuscript_id"]: _manuscript_from_dict(item) for item in data}
                continue
            if path.name == "_config_profiles.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self._config_profiles = {item["config_profile_id"]: _config_profile_from_dict(item) for item in data}
                continue
            if path.name == "_artifact_index.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self._artifact_index = {
                    job_id: [ArtifactRef(**item) for item in items]
                    for job_id, items in data.items()
                }
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            job = _job_from_dict(data)
            self._jobs[job.job_id] = job

    def create_job(self, request: JobCreateRequest) -> JobRecord:
        job = create_job_record(request)

        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return _job_from_dict(asdict(job))

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            return _job_from_dict(asdict(job)) if job is not None else None

    def list_jobs(self) -> List[JobRecord]:
        with self._lock:
            return [_job_from_dict(asdict(job)) for job in self._jobs.values()]

    def update_job(self, job: JobRecord) -> JobRecord:
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
            self._artifact_index[job.job_id] = [ArtifactRef(**asdict(item)) for item in job.artifacts]
            self._persist_artifact_index()
            return _job_from_dict(asdict(job))

    def _request_control_state(
        self,
        job_id: str,
        *,
        reason: str,
        requested_status: str,
        terminal_status: str,
        requested_at_key: str,
    ) -> Optional[JobRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {"succeeded", "failed", "cancelled"}:
                return _job_from_dict(asdict(job))

            now = utc_now_iso()
            active_stage = next((stage for stage in job.stage_runs if stage.status == "running"), None)
            if job.status in {"queued", "paused"}:
                job.status = terminal_status
                if active_stage is None and job.stage_runs:
                    active_stage = job.stage_runs[0]
                if active_stage is not None:
                    active_stage.status = terminal_status
                    active_stage.finished_at = now
                    active_stage.error = reason
            else:
                job.status = requested_status
                if active_stage is not None:
                    active_stage.error = reason

            job.updated_at = now
            job.options = {
                **job.options,
                requested_at_key: now,
                "_cancel_reason": reason,
                "_control_target_status": terminal_status,
            }
            self._jobs[job.job_id] = job
            self._persist(job)
            return _job_from_dict(asdict(job))

    def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> Optional[JobRecord]:
        return self._request_control_state(
            job_id,
            reason=reason,
            requested_status="cancel_requested",
            terminal_status="cancelled",
            requested_at_key="_cancel_requested_at",
        )

    def pause_job(self, job_id: str, reason: str = "Paused by user") -> Optional[JobRecord]:
        return self._request_control_state(
            job_id,
            reason=reason,
            requested_status="pause_requested",
            terminal_status="paused",
            requested_at_key="_pause_requested_at",
        )

    def claim_next_job(
        self,
        worker_id: str,
        *,
        include_pipelines: Optional[List[str]] = None,
        exclude_pipelines: Optional[List[str]] = None,
    ) -> Optional[JobRecord]:
        with self._lock:
            queued_jobs = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.status == "queued"
                    and (not include_pipelines or job.pipeline in include_pipelines)
                    and (not exclude_pipelines or job.pipeline not in exclude_pipelines)
                ),
                key=lambda item: item.created_at,
            )
            if not queued_jobs:
                return None

            job = queued_jobs[0]
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
            self._jobs[job.job_id] = job
            self._persist(job)
            return _job_from_dict(asdict(job))

    def record_worker_heartbeat(self, worker_id: str, status: str, last_job_id: Optional[str] = None) -> None:
        with self._lock:
            self._workers[worker_id] = WorkerHeartbeat(
                worker_id=worker_id,
                status=status,
                heartbeat_at=utc_now_iso(),
                last_job_id=last_job_id,
            )
            self._persist_workers()

    def list_worker_heartbeats(self) -> List[WorkerHeartbeat]:
        with self._lock:
            return [WorkerHeartbeat(**asdict(worker)) for worker in self._workers.values()]

    def queue_summary(self) -> Dict[str, int]:
        with self._lock:
            summary: Dict[str, int] = {
                "queued": 0,
                "running": 0,
                "paused": 0,
                "pause_requested": 0,
                "cancel_requested": 0,
                "succeeded": 0,
                "failed": 0,
                "cancelled": 0,
            }
            for job in self._jobs.values():
                summary[job.status] = summary.get(job.status, 0) + 1
            summary["total"] = len(self._jobs)
            return summary

    def recover_stale_running_jobs(self, stale_after_seconds: int, recovery_worker_id: str) -> List[str]:
        from datetime import datetime, timezone

        recovered: List[str] = []
        now = datetime.now(timezone.utc)
        with self._lock:
            for job in self._jobs.values():
                if job.status != "running":
                    continue
                claimed_at = job.options.get("_claimed_at")
                if not claimed_at:
                    continue
                claimed_dt = datetime.fromisoformat(str(claimed_at))
                age = (now - claimed_dt).total_seconds()
                if age < stale_after_seconds:
                    continue
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
                self._persist(job)
                recovered.append(job.job_id)
        return recovered

    def finalize_stale_cancel_requests(self, stale_after_seconds: int) -> List[str]:
        from datetime import datetime, timezone

        finalized: List[str] = []
        now = datetime.now(timezone.utc)
        with self._lock:
            for job in self._jobs.values():
                if job.status not in {"cancel_requested", "pause_requested"}:
                    continue
                requested_at = (
                    job.options.get("_pause_requested_at")
                    or job.options.get("_cancel_requested_at")
                    or job.updated_at
                )
                try:
                    requested_dt = datetime.fromisoformat(str(requested_at))
                except ValueError:
                    requested_dt = now
                age = (now - requested_dt).total_seconds()
                if age < stale_after_seconds:
                    continue
                target_status = str(job.options.get("_control_target_status") or "cancelled")
                job.status = target_status
                job.updated_at = utc_now_iso()
                for stage in job.stage_runs:
                    if stage.status == "running":
                        stage.status = target_status
                        stage.finished_at = job.updated_at
                        stage.error = stage.error or ("Paused by housekeeping" if target_status == "paused" else "Cancelled by housekeeping")
                        break
                self._persist(job)
                finalized.append(job.job_id)
        return finalized

    def is_ready(self) -> bool:
        return True

    def upsert_user(self, username: str, role: str, api_token: str, password_hash: Optional[str] = None) -> UserRecord:
        with self._lock:
            now = utc_now_iso()
            existing = self._users.get(api_token)
            if existing is None:
                existing = next((user for user in self._users.values() if user.username == username), None)
            if existing is not None:
                user = UserRecord(
                    user_id=existing.user_id,
                    username=username,
                    role=role,
                    api_token=api_token,
                    created_at=existing.created_at,
                    updated_at=now,
                    password_hash=password_hash if password_hash is not None else existing.password_hash,
                )
            else:
                user = UserRecord(
                    user_id=str(uuid4()),
                    username=username,
                    role=role,
                    api_token=api_token,
                    created_at=now,
                    updated_at=now,
                    password_hash=password_hash,
                )
            for token, existing_user in list(self._users.items()):
                if existing_user.user_id == user.user_id and token != api_token:
                    del self._users[token]
            self._users[api_token] = user
            self._persist_users()
            return _user_from_dict(asdict(user))

    def get_user_by_token(self, api_token: str) -> Optional[UserRecord]:
        with self._lock:
            user = self._users.get(api_token)
            return _user_from_dict(asdict(user)) if user is not None else None

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        with self._lock:
            user = next((item for item in self._users.values() if item.username == username), None)
            return _user_from_dict(asdict(user)) if user is not None else None

    def upsert_manuscript(
        self,
        *,
        book_slug: str,
        title: str,
        source_path: str,
        document_type: Optional[str],
        file_size_bytes: Optional[int],
        owner_user_id: Optional[str],
        owner_username: Optional[str],
    ) -> ManuscriptRecord:
        with self._lock:
            now = utc_now_iso()
            existing = next(
                (
                    item
                    for item in self._manuscripts.values()
                    if item.book_slug == book_slug and item.owner_user_id == owner_user_id
                ),
                None,
            )
            if existing is not None:
                manuscript = ManuscriptRecord(
                    manuscript_id=existing.manuscript_id,
                    book_slug=book_slug,
                    title=title,
                    source_path=source_path,
                    document_type=document_type or existing.document_type,
                    file_size_bytes=file_size_bytes,
                    owner_user_id=owner_user_id,
                    owner_username=owner_username,
                    created_at=existing.created_at,
                    updated_at=now,
                )
            else:
                manuscript = ManuscriptRecord(
                    manuscript_id=str(uuid4()),
                    book_slug=book_slug,
                    title=title,
                    source_path=source_path,
                    document_type=document_type,
                    file_size_bytes=file_size_bytes,
                    owner_user_id=owner_user_id,
                    owner_username=owner_username,
                    created_at=now,
                    updated_at=now,
                )
            self._manuscripts[manuscript.manuscript_id] = manuscript
            self._persist_manuscripts()
            return _manuscript_from_dict(asdict(manuscript))

    def get_manuscript(self, manuscript_id: str) -> Optional[ManuscriptRecord]:
        with self._lock:
            manuscript = self._manuscripts.get(manuscript_id)
            return _manuscript_from_dict(asdict(manuscript)) if manuscript is not None else None

    def list_manuscripts(self) -> List[ManuscriptRecord]:
        with self._lock:
            return [_manuscript_from_dict(asdict(item)) for item in self._manuscripts.values()]

    def update_manuscript(
        self,
        manuscript_id: str,
        *,
        book_slug: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[ManuscriptRecord]:
        with self._lock:
            manuscript = self._manuscripts.get(manuscript_id)
            if manuscript is None:
                return None
            updated = ManuscriptRecord(
                manuscript_id=manuscript.manuscript_id,
                book_slug=book_slug or manuscript.book_slug,
                title=title or manuscript.title,
                source_path=manuscript.source_path,
                document_type=manuscript.document_type,
                file_size_bytes=manuscript.file_size_bytes,
                owner_user_id=manuscript.owner_user_id,
                owner_username=manuscript.owner_username,
                created_at=manuscript.created_at,
                updated_at=utc_now_iso(),
            )
            self._manuscripts[manuscript_id] = updated
            self._persist_manuscripts()
            return _manuscript_from_dict(asdict(updated))

    def delete_manuscript(self, manuscript_id: str) -> bool:
        with self._lock:
            if manuscript_id not in self._manuscripts:
                return False
            del self._manuscripts[manuscript_id]
            self._persist_manuscripts()
            return True

    def upsert_config_profile(
        self,
        *,
        name: str,
        config_path: str,
        version: str,
        checksum: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> ConfigProfileRecord:
        with self._lock:
            now = utc_now_iso()
            profile_metadata = dict(metadata or {})
            existing = next(
                (
                    item
                    for item in self._config_profiles.values()
                    if item.name == name and item.version == version
                ),
                None,
            )
            if existing is not None:
                profile = ConfigProfileRecord(
                    config_profile_id=existing.config_profile_id,
                    name=name,
                    config_path=config_path,
                    version=version,
                    checksum=checksum,
                    metadata=profile_metadata,
                    created_at=existing.created_at,
                    updated_at=now,
                )
            else:
                profile = ConfigProfileRecord(
                    config_profile_id=str(uuid4()),
                    name=name,
                    config_path=config_path,
                    version=version,
                    checksum=checksum,
                    metadata=profile_metadata,
                    created_at=now,
                    updated_at=now,
                )
            self._config_profiles[profile.config_profile_id] = profile
            self._persist_config_profiles()
            return _config_profile_from_dict(asdict(profile))

    def get_config_profile(self, config_profile_id: str) -> Optional[ConfigProfileRecord]:
        with self._lock:
            profile = self._config_profiles.get(config_profile_id)
            return _config_profile_from_dict(asdict(profile)) if profile is not None else None

    def list_config_profiles(self) -> List[ConfigProfileRecord]:
        with self._lock:
            return [_config_profile_from_dict(asdict(item)) for item in self._config_profiles.values()]

    def list_job_artifacts(self, job_id: str) -> List[ArtifactRef]:
        with self._lock:
            return [ArtifactRef(**asdict(item)) for item in self._artifact_index.get(job_id, [])]
