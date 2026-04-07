from __future__ import annotations

from pathlib import Path

import pytest

from manuscriptprep.api_models import JobCreateRequest
from manuscriptprep.job_store import JobStore
from manuscriptprep.store_factory import create_job_store


pytestmark = pytest.mark.unit


def test_create_job_store_returns_file_store(tmp_path: Path) -> None:
    store = create_job_store(backend="file", jobs_root=tmp_path / "jobs")
    assert isinstance(store, JobStore)
    assert store.root == tmp_path / "jobs"


def test_create_job_store_requires_database_url_for_postgres() -> None:
    with pytest.raises(ValueError, match="database URL"):
        create_job_store(backend="postgres")


def test_create_job_store_builds_postgres_store(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, str] = {}

    class FakePostgresJobStore:
        def __init__(self, database_url: str, schema: str = "public") -> None:
            created["database_url"] = database_url
            created["schema"] = schema

    monkeypatch.setattr("manuscriptprep.store_factory.PostgresJobStore", FakePostgresJobStore)
    store = create_job_store(
        backend="postgres",
        database_url="postgresql://example",
        postgres_schema="gateway",
    )

    assert isinstance(store, FakePostgresJobStore)
    assert created == {
        "database_url": "postgresql://example",
        "schema": "gateway",
    }


def test_file_store_can_claim_queued_job(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    created = store.create_job(JobCreateRequest(pipeline="ingest", book_slug="treasure_island"))

    claimed = store.claim_next_job("worker-1")

    assert claimed is not None
    assert claimed.job_id == created.job_id
    assert claimed.status == "running"
    assert claimed.options["_worker_id"] == "worker-1"
