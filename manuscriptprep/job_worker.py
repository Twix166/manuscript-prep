"""Queued worker execution for ManuscriptPrep jobs."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from manuscriptprep.artifact_store import LocalArtifactStore
from manuscriptprep.api_models import utc_now_iso
from manuscriptprep.execution_adapter import ExecutionAdapter
from manuscriptprep.job_store import BaseJobStore


class JobWorker:
    def __init__(
        self,
        store: BaseJobStore,
        adapter: ExecutionAdapter,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        stale_after_seconds: int = 600,
        cancel_grace_seconds: int = 15,
        artifact_store: LocalArtifactStore | None = None,
        include_pipelines: list[str] | None = None,
        exclude_pipelines: list[str] | None = None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.worker_id = worker_id or f"worker-{uuid.uuid4()}"
        self.poll_interval = poll_interval
        self.stale_after_seconds = stale_after_seconds
        self.cancel_grace_seconds = cancel_grace_seconds
        self.artifact_store = artifact_store or LocalArtifactStore()
        self.include_pipelines = include_pipelines or []
        self.exclude_pipelines = exclude_pipelines or []
        self.adapter.cancel_check = self._should_cancel_job

    def _should_cancel_job(self, job_id: str) -> bool:
        job = self.store.get_job(job_id)
        return job is not None and job.status in {"cancel_requested", "pause_requested"}

    def recover_stale_jobs(self) -> list[str]:
        recovered = self.store.recover_stale_running_jobs(
            stale_after_seconds=self.stale_after_seconds,
            recovery_worker_id=self.worker_id,
        )
        self.store.finalize_stale_cancel_requests(self.cancel_grace_seconds)
        return recovered

    def process_next_job(self) -> bool:
        self.recover_stale_jobs()
        self.store.record_worker_heartbeat(self.worker_id, "idle")
        job = self.store.claim_next_job(
            self.worker_id,
            include_pipelines=self.include_pipelines or None,
            exclude_pipelines=self.exclude_pipelines or None,
        )
        if job is None:
            return False

        self.store.record_worker_heartbeat(self.worker_id, "running", last_job_id=job.job_id)
        try:
            updated_job, artifacts = self.adapter.run_job(job)
            updated_job.artifacts = self.artifact_store.register(artifacts)
            updated_job.updated_at = utc_now_iso()
            self.store.update_job(updated_job)
            self.store.record_worker_heartbeat(self.worker_id, "idle", last_job_id=job.job_id)
        except Exception as exc:
            failed = self.store.get_job(job.job_id) or job
            if failed.status in {"cancel_requested", "pause_requested"}:
                target_status = str(failed.options.get("_control_target_status") or "cancelled")
                failed.status = target_status
            else:
                failed.status = "failed"
            failed.updated_at = utc_now_iso()
            if all(stage.error is None for stage in failed.stage_runs) and failed.stage_runs:
                failed.stage_runs[0].status = failed.status if failed.status in {"cancelled", "paused"} else "failed"
                failed.stage_runs[0].finished_at = failed.updated_at
                failed.stage_runs[0].error = str(exc)
            self.store.update_job(failed)
            self.store.record_worker_heartbeat(self.worker_id, "idle", last_job_id=job.job_id)
        return True

    def run_forever(self) -> None:
        while True:
            processed = self.process_next_job()
            if not processed:
                self.recover_stale_jobs()
                time.sleep(self.poll_interval)
