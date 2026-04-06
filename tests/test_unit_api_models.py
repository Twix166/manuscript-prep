from __future__ import annotations

import pytest

from manuscriptprep.api_models import JobCreateRequest
from manuscriptprep.job_store import JobStore
from manuscriptprep.service_registry import get_pipeline_definition, list_pipelines


pytestmark = pytest.mark.unit


def test_service_registry_exposes_pipeline_definition() -> None:
    pipelines = list_pipelines()
    assert pipelines
    definition = get_pipeline_definition("manuscript-prep")
    assert definition is not None
    assert [stage.name for stage in definition.stages] == ["ingest", "orchestrate", "merge", "resolve", "report"]


def test_job_store_creates_queued_job_with_stage_runs() -> None:
    store = JobStore()
    job = store.create_job(JobCreateRequest(pipeline="manuscript-prep", book_slug="treasure_island"))
    assert job.status == "queued"
    assert len(job.stage_runs) == 5
    assert job.stage_runs[0].name == "ingest"


def test_job_store_persists_jobs_to_disk(tmp_path) -> None:
    store = JobStore(root=tmp_path)
    created = store.create_job(JobCreateRequest(pipeline="ingest", book_slug="treasure_island"))
    reloaded = JobStore(root=tmp_path)
    fetched = reloaded.get_job(created.job_id)
    assert fetched is not None
    assert fetched.job_id == created.job_id


def test_job_store_persists_stage_execution_metadata(tmp_path) -> None:
    store = JobStore(root=tmp_path)
    created = store.create_job(JobCreateRequest(pipeline="ingest", book_slug="treasure_island"))
    created.stage_runs[0].command = ["python", "manuscriptprep_ingest.py"]
    created.stage_runs[0].exit_code = 0
    created.stage_runs[0].stdout_path = "/tmp/stdout.txt"
    created.stage_runs[0].stderr_path = "/tmp/stderr.txt"
    store.update_job(created)

    reloaded = JobStore(root=tmp_path)
    fetched = reloaded.get_job(created.job_id)
    assert fetched is not None
    assert fetched.stage_runs[0].command == ["python", "manuscriptprep_ingest.py"]
    assert fetched.stage_runs[0].exit_code == 0
    assert fetched.stage_runs[0].stdout_path == "/tmp/stdout.txt"
