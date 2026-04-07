from __future__ import annotations

import json
import pytest

from manuscriptprep.execution_adapter import ExecutionAdapter
from manuscriptprep.job_worker import JobWorker
from manuscriptprep.job_store import JobStore
from manuscriptprep_gateway_api import GatewayAPI


pytestmark = pytest.mark.integration


def test_gateway_api_exposes_health_pipelines_and_jobs(tmp_path) -> None:
    app = GatewayAPI(store=JobStore(root=tmp_path / "jobs"))

    status, health = app.health()
    assert status == 200
    assert health["service"] == "gateway-api"

    status, ready = app.ready()
    assert status == 200
    assert ready["status"] == "ready"

    status, system = app.system_status()
    assert status == 200
    assert system["ready"] is True
    assert system["queue"]["total"] == 0

    status, pipelines = app.list_pipelines()
    assert status == 200
    assert "manuscript-prep" in [item["pipeline"] for item in pipelines["pipelines"]]

    status, created = app.create_job({"pipeline": "manuscript-prep", "book_slug": "treasure_island", "title": "Treasure Island"})
    assert status == 201
    assert created["status"] == "queued"
    assert created["stage_runs"][0]["name"] == "ingest"

    job_id = created["job_id"]
    status, fetched = app.get_job(job_id)
    assert status == 200
    assert fetched["job_id"] == job_id

    status, jobs = app.list_jobs()
    assert status == 200
    assert len(jobs["jobs"]) == 1


def test_gateway_api_persists_and_runs_ingest_jobs(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "book_slug": "treasure_island",
            "title": "Treasure Island",
            "input_path": str(sample_pdf),
            "options": {
                "workdir": str(tmp_path / "work"),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201
    job_id = created["job_id"]

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = test_env["PATH"]
    try:
        status, queued = app.run_job(job_id)
        assert status == 202
        assert queued["status"] == "queued"
        assert worker.process_next_job() is True
    finally:
        os.environ["PATH"] = old_path

    status, ran = app.get_job(job_id)
    assert status == 200
    assert status == 200
    assert ran["status"] == "succeeded"
    assert ran["artifacts"]
    assert ran["stage_runs"][0]["command"]
    assert ran["stage_runs"][0]["stdout_path"]
    assert ran["stage_runs"][0]["stderr_path"]
    persisted = store.get_job(job_id)
    assert persisted is not None
    assert persisted.status == "succeeded"
    assert persisted.artifacts[0].stage == "ingest"

    status, system = app.system_status()
    assert status == 200
    assert system["queue"]["succeeded"] == 1
    assert any(item["worker_id"] == worker.worker_id for item in system["workers"])

    status, artifact = app.get_job_artifact(job_id, "ingest_stdout")
    assert status == 200
    assert artifact["exists"] is True
    assert "preview" in artifact
    assert "sha256" in artifact["artifact"]["metadata"]

    status, artifact_index = app.list_job_artifact_index(job_id)
    assert status == 200
    assert {item["name"] for item in artifact_index["artifacts"]} >= {"ingest_stdout", "ingest_stderr", "ingest_command"}


def test_gateway_api_runs_full_service_sequence(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    book_slug = "treasure_island"
    workdir = tmp_path / "work"
    out_dir = tmp_path / "out" / book_slug
    merged_dir = tmp_path / "merged" / book_slug
    resolved_dir = tmp_path / "resolved" / book_slug
    report_path = tmp_path / "reports" / "treasure_island_report.pdf"

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "book_slug": book_slug,
            "title": "Treasure Island",
            "input_path": str(sample_pdf),
            "options": {
                "workdir": str(workdir),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201
    status, ingested = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, ingested = app.get_job(created["job_id"])
    assert status == 200
    assert ingested["status"] == "succeeded"

    status, created = app.create_job(
        {
            "pipeline": "orchestrate",
            "book_slug": book_slug,
            "options": {
                "input_dir": str(workdir / "chunks" / book_slug),
                "output_dir": str(out_dir),
            },
        }
    )
    assert status == 201
    status, orchestrated = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, orchestrated = app.get_job(created["job_id"])
    assert status == 200
    assert orchestrated["status"] == "succeeded"

    chunk_manifest = workdir / "manifests" / book_slug / "chunk_manifest.json"
    status, created = app.create_job(
        {
            "pipeline": "merge",
            "book_slug": book_slug,
            "options": {
                "input_dir": str(out_dir),
                "output_dir": str(merged_dir),
                "chunk_manifest": str(chunk_manifest),
            },
        }
    )
    assert status == 201
    status, merged = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, merged = app.get_job(created["job_id"])
    assert status == 200
    assert merged["status"] == "succeeded"
    assert any(item["name"] == "book_merged" for item in merged["artifacts"])

    status, created = app.create_job(
        {
            "pipeline": "resolve",
            "book_slug": book_slug,
            "options": {
                "input_dir": str(merged_dir),
                "output_dir": str(resolved_dir),
                "model": "manuscriptprep-resolver",
            },
        }
    )
    assert status == 201
    status, resolved = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, resolved = app.get_job(created["job_id"])
    assert status == 200
    assert resolved["status"] == "succeeded"
    resolved_book = json.loads((resolved_dir / "book_resolved.json").read_text(encoding="utf-8"))
    assert "characters_resolved" in resolved_book["entities"]

    status, created = app.create_job(
        {
            "pipeline": "report",
            "book_slug": book_slug,
            "title": "Treasure Island",
            "options": {
                "input_dir": str(merged_dir),
                "output_path": str(report_path),
            },
        }
    )
    assert status == 201
    status, reported = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, reported = app.get_job(created["job_id"])
    assert status == 200
    assert reported["status"] == "succeeded"
    assert report_path.exists()


def test_gateway_api_runs_single_end_to_end_pipeline_job(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    book_slug = "treasure_island"
    workdir = tmp_path / "work"

    status, created = app.create_job(
        {
            "pipeline": "manuscript-prep",
            "book_slug": book_slug,
            "title": "Treasure Island",
            "input_path": str(sample_pdf),
            "options": {
                "workdir": str(workdir),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
                "output_dir": str(tmp_path / "out" / book_slug),
                "merged_dir": str(tmp_path / "merged" / book_slug),
                "resolved_dir": str(tmp_path / "resolved" / book_slug),
                "report_output": str(tmp_path / "reports" / "treasure_island_report.pdf"),
                "model": "manuscriptprep-resolver",
            },
        }
    )
    assert status == 201

    status, completed = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, completed = app.get_job(created["job_id"])
    assert status == 200
    assert completed["status"] == "succeeded"
    assert [stage["status"] for stage in completed["stage_runs"]] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    artifact_names = {item["name"] for item in completed["artifacts"]}
    assert "chunk_manifest" in artifact_names
    assert "book_merged" in artifact_names
    assert "book_resolved" in artifact_names
    assert "report_pdf" in artifact_names


def test_gateway_api_enforces_auth_and_job_ownership(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    app = GatewayAPI(
        store=store,
        auth_required=True,
        bootstrap_username="admin",
        bootstrap_token="admin-token",
    )
    alice = store.upsert_user(username="alice", role="user", api_token="alice-token")
    bob = store.upsert_user(username="bob", role="user", api_token="bob-token")
    admin = app.authenticate("admin-token")
    assert admin is not None

    status, payload = app.list_jobs()
    assert status == 401
    assert payload["error"] == "Authentication required"

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "book_slug": "treasure_island",
            "title": "Treasure Island",
        },
        actor=alice,
    )
    assert status == 201
    assert created["owner_user_id"] == alice.user_id
    assert created["owner_username"] == "alice"

    job_id = created["job_id"]

    status, alice_jobs = app.list_jobs(actor=alice)
    assert status == 200
    assert [job["job_id"] for job in alice_jobs["jobs"]] == [job_id]

    status, bob_jobs = app.list_jobs(actor=bob)
    assert status == 200
    assert bob_jobs["jobs"] == []

    status, forbidden = app.get_job(job_id, actor=bob)
    assert status == 403
    assert forbidden["error"] == "Not authorized for this job"

    status, admin_jobs = app.list_jobs(actor=admin)
    assert status == 200
    assert [job["job_id"] for job in admin_jobs["jobs"]] == [job_id]

    status, system = app.system_status(actor=alice)
    assert status == 403
    assert system["error"] == "Admin access required"

    status, system = app.system_status(actor=admin)
    assert status == 200
    assert system["store_backend"] == "JobStore"


def test_gateway_api_manages_manuscripts_and_config_profiles(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    app = GatewayAPI(
        store=store,
        auth_required=True,
        bootstrap_username="admin",
        bootstrap_token="admin-token",
    )
    alice = store.upsert_user(username="alice", role="user", api_token="alice-token")
    admin = app.authenticate("admin-token")
    assert admin is not None

    status, profile = app.create_config_profile(
        {
            "name": "default",
            "config_path": "/tmp/manuscriptprep.yaml",
            "version": "v1",
        },
        actor=admin,
    )
    assert status == 201

    status, forbidden = app.create_config_profile(
        {
            "name": "user-profile",
            "config_path": "/tmp/user.yaml",
            "version": "v1",
        },
        actor=alice,
    )
    assert status == 403
    assert forbidden["error"] == "Admin access required"

    status, manuscript = app.create_manuscript(
        {
            "book_slug": "treasure_island",
            "title": "Treasure Island",
            "source_path": "/tmp/treasure-island.pdf",
        },
        actor=alice,
    )
    assert status == 201

    status, alice_manuscripts = app.list_manuscripts(actor=alice)
    assert status == 200
    assert [item["manuscript_id"] for item in alice_manuscripts["manuscripts"]] == [manuscript["manuscript_id"]]

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "manuscript_id": manuscript["manuscript_id"],
            "config_profile_id": profile["config_profile_id"],
            "options": {"workdir": str(tmp_path / "work")},
        },
        actor=alice,
    )
    assert status == 201
    assert created["manuscript_id"] == manuscript["manuscript_id"]
    assert created["config_profile_id"] == profile["config_profile_id"]
    assert created["book_slug"] == "treasure_island"
    assert created["title"] == "Treasure Island"
    assert created["input_path"] == "/tmp/treasure-island.pdf"
    assert created["config_path"] == "/tmp/manuscriptprep.yaml"
