from __future__ import annotations

from pathlib import Path

import pytest

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
