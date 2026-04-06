"""Persistent file-backed job store for the gateway slices."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from manuscriptprep.api_models import ArtifactRef, JobCreateRequest, JobRecord, StageRun, utc_now_iso
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


class JobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path("work/gateway_jobs")).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._jobs: Dict[str, JobRecord] = {}
        self._load_existing_jobs()

    def _load_existing_jobs(self) -> None:
        for path in sorted(self.root.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            job = _job_from_dict(data)
            self._jobs[job.job_id] = job

    def _job_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def _persist(self, job: JobRecord) -> None:
        self._job_path(job.job_id).write_text(
            json.dumps(asdict(job), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def create_job(self, request: JobCreateRequest) -> JobRecord:
        definition = get_pipeline_definition(request.pipeline)
        if definition is None:
            raise ValueError(f"Unknown pipeline: {request.pipeline}")

        now = utc_now_iso()
        job = JobRecord(
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
