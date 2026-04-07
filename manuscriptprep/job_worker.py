"""Queued worker execution for ManuscriptPrep jobs."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

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
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.worker_id = worker_id or f"worker-{uuid.uuid4()}"
        self.poll_interval = poll_interval

    def process_next_job(self) -> bool:
        job = self.store.claim_next_job(self.worker_id)
        if job is None:
            return False

        try:
            updated_job, artifacts = self.adapter.run_job(job)
            updated_job.artifacts = artifacts
            updated_job.updated_at = utc_now_iso()
            self.store.update_job(updated_job)
        except Exception as exc:
            failed = self.store.get_job(job.job_id) or job
            failed.status = "failed"
            failed.updated_at = utc_now_iso()
            if all(stage.error is None for stage in failed.stage_runs) and failed.stage_runs:
                failed.stage_runs[0].status = "failed"
                failed.stage_runs[0].finished_at = failed.updated_at
                failed.stage_runs[0].error = str(exc)
            self.store.update_job(failed)
        return True

    def run_forever(self) -> None:
        while True:
            processed = self.process_next_job()
            if not processed:
                time.sleep(self.poll_interval)
