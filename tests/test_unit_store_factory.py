from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

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


def test_file_store_reports_queue_summary_and_heartbeats(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    store.create_job(JobCreateRequest(pipeline="ingest", book_slug="a"))
    store.record_worker_heartbeat("worker-1", "idle")

    summary = store.queue_summary()
    workers = store.list_worker_heartbeats()

    assert summary["queued"] == 1
    assert summary["total"] == 1
    assert workers[0].worker_id == "worker-1"
    assert workers[0].status == "idle"


def test_file_store_recovers_stale_running_jobs(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    created = store.create_job(JobCreateRequest(pipeline="ingest", book_slug="a"))
    claimed = store.claim_next_job("worker-1")
    assert claimed is not None

    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
    claimed.options["_claimed_at"] = stale_time
    store.update_job(claimed)

    recovered = store.recover_stale_running_jobs(600, "worker-recovery")
    refreshed = store.get_job(created.job_id)

    assert recovered == [created.job_id]
    assert refreshed is not None
    assert refreshed.status == "queued"
    assert refreshed.options["_recovered_by"] == "worker-recovery"


def test_file_store_can_upsert_and_lookup_users(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path / "jobs")

    created = store.upsert_user(username="alice", role="admin", api_token="token-1")
    fetched = store.get_user_by_token("token-1")

    assert fetched is not None
    assert fetched.user_id == created.user_id
    assert fetched.username == "alice"
    assert fetched.role == "admin"


def test_file_store_can_upsert_manuscripts_and_config_profiles(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path / "jobs")

    manuscript = store.upsert_manuscript(
        book_slug="treasure_island",
        title="Treasure Island",
        source_path="/tmp/treasure-island.pdf",
        owner_user_id="user-1",
        owner_username="alice",
    )
    profile = store.upsert_config_profile(
        name="default",
        config_path="/tmp/config.yaml",
        version="v1",
        checksum="abc123",
    )

    assert store.get_manuscript(manuscript.manuscript_id) is not None
    assert store.list_manuscripts()[0].book_slug == "treasure_island"
    assert store.get_config_profile(profile.config_profile_id) is not None
    assert store.list_config_profiles()[0].name == "default"
