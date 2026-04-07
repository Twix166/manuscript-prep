"""Persistent file-backed job store for the gateway slices."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from manuscriptprep.api_models import ArtifactRef, JobCreateRequest, JobRecord, StageRun, WorkerHeartbeat, utc_now_iso
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
        config_path=data.get("config_path"),
        input_path=data.get("input_path"),
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
        config_path=request.config_path,
        input_path=request.input_path,
        options=dict(request.options),
        stage_runs=[StageRun(name=stage.name, status="pending") for stage in definition.stages],
        artifacts=[],
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
    def claim_next_job(self, worker_id: str) -> Optional[JobRecord]:
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
    def is_ready(self) -> bool:
        raise NotImplementedError


class JobStore(BaseJobStore):
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path("work/gateway_jobs")).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._jobs: Dict[str, JobRecord] = {}
        self._workers: Dict[str, WorkerHeartbeat] = {}
        self._load_existing_jobs()

    def _job_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def _workers_path(self) -> Path:
        return self.root / "_workers.json"

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

    def _load_existing_jobs(self) -> None:
        for path in sorted(self.root.glob("*.json")):
            if path.name == "_workers.json":
                data = json.loads(path.read_text(encoding="utf-8"))
                self._workers = {item["worker_id"]: WorkerHeartbeat(**item) for item in data}
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
            return _job_from_dict(asdict(job))

    def claim_next_job(self, worker_id: str) -> Optional[JobRecord]:
        with self._lock:
            queued_jobs = sorted(
                (job for job in self._jobs.values() if job.status == "queued"),
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
            summary: Dict[str, int] = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "cancelled": 0}
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

    def is_ready(self) -> bool:
        return True
